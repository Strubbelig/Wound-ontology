"""The Contradiction Queue's verdicts have to arrive, or not count as made.

The page at claude.ai/artifact/9VpYXEKfmQ1zxmgEfidLG4 holds two queues that
land in two different places, and it stops offering a row the moment it is
answered. So a decision this applier quietly drops is not a decision deferred
— it is one the curator believes they made and nobody will ever be asked
again. Everything unrecognised is collected and named rather than skipped.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "apply_contradiction_verdicts", ROOT / "scripts" / "apply_contradiction_verdicts.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


def _row(**kw):
    base = {"queue": "contested", "verdict": "in", "term": "pain score", "note": ""}
    base.update(kw)
    return base


# ── what goes where ──────────────────────────────────────────────────────────

def test_a_scope_answer_and_a_pair_answer_are_kept_apart():
    scope, pairs, held, unknown = mod.classify([
        _row(queue="contested", verdict="out"),
        _row(queue="pairs", verdict="same_class", term="a", canonical="b"),
    ])
    assert len(scope) == 1 and len(pairs) == 1 and not held and not unknown


def test_cant_say_is_held_open_not_applied():
    """`unsure` is a real answer — it says the curator looked and could not
    decide. Writing it as a verdict would close a question that is still open."""
    scope, pairs, held, unknown = mod.classify([_row(verdict="unsure")])
    assert not scope and not unknown and len(held) == 1


@pytest.mark.parametrize("row", [
    {"queue": "contested", "verdict": "same_class", "term": "x"},   # pair verdict, scope queue
    {"queue": "pairs", "verdict": "in", "term": "x"},               # scope verdict, pair queue
    {"queue": "pairs", "verdict": "probably", "term": "x"},         # invented verdict
    {"verdict": "in", "term": "x"},                                 # no queue at all
])
def test_anything_it_cannot_place_is_named_not_dropped(row):
    scope, pairs, held, unknown = mod.classify([row])
    assert not scope and not pairs and not held
    assert unknown == [row], "a decision this script cannot apply must be reported"


# ── reading the store's export ───────────────────────────────────────────────

def test_it_reads_one_document_per_file(tmp_path):
    (tmp_path / "c0000.json").write_text(json.dumps(_row()))
    (tmp_path / "d0000.json").write_text(json.dumps(
        _row(queue="pairs", verdict="different", term="a", canonical="b")))
    assert len(mod._load(tmp_path)) == 2


def test_it_reads_a_file_holding_a_list_of_documents(tmp_path):
    """`read_db` writes one file per document, but a hand-assembled export is
    a list — both have arrived before."""
    (tmp_path / "all.json").write_text(json.dumps([_row(), _row(verdict="out")]))
    assert len(mod._load(tmp_path)) == 2


def test_it_looks_in_subdirectories(tmp_path):
    """The store's export nests by collection path."""
    nested = tmp_path / "decisions"
    nested.mkdir()
    (nested / "c0000.json").write_text(json.dumps(_row()))
    assert len(mod._load(tmp_path)) == 1


def test_an_undecided_row_is_not_a_decision(tmp_path):
    """A document with no verdict is a row the page touched and left open."""
    (tmp_path / "c0000.json").write_text(json.dumps({"queue": "contested", "term": "x"}))
    assert mod._load(tmp_path) == []
