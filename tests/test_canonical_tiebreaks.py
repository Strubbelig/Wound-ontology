"""One class, several names, and a ruling on which name it keeps.

The page at claude.ai/artifact/7U8LSVMuQspKoieS2sUYVM holds the 30 rows of the
Contradiction Queue that could not be written — 28 conflicts, each a set of
spellings the curator agrees are one class with no ruling on the canonical.
Tapping the winner repoints every other spelling onto it.

The page stops offering a conflict the moment it is answered, so anything this
script cannot write has to be NAMED. A ruling silently dropped is one the
curator believes they made and will never be asked for again.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "apply_canonical_tiebreaks", ROOT / "scripts" / "apply_canonical_tiebreaks.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


def _d(i, verdict, spellings):
    return {"id": i, "verdict": verdict, "spellings": spellings, "queue": "canonical"}


def test_every_other_spelling_points_at_the_winner():
    writes, held, clashes = mod.plan([_d("x", "b", ["a", "b", "c"])], {}.get)
    assert writes == [("a", "b"), ("c", "b")]
    assert not held and not clashes


def test_not_one_class_is_an_answer_not_a_failure():
    """It says the curator looked. Writing nothing is the whole point."""
    writes, held, clashes = mod.plan(
        [_d("x", mod.NOT_ONE_CLASS, ["a", "b"])], {}.get)
    assert not writes and not clashes and [h["id"] for h in held] == ["x"]


def test_a_verdict_that_is_not_one_of_the_spellings_is_named():
    _, _, clashes = mod.plan([_d("x", "z", ["a", "b"])], {}.get)
    assert "not one of the spellings" in clashes["x"]


def test_a_winner_that_is_another_conflicts_loser_is_named():
    """`b` cannot be the name of its class and a synonym of `c` at once."""
    _, _, clashes = mod.plan(
        [_d("x", "b", ["a", "b"]), _d("y", "c", ["b", "c"])], {}.get)
    assert "winner here and a loser in" in clashes["x"]


def test_a_spelling_that_maps_outside_the_conflict_is_named():
    """Overwriting it would drop a mapping nobody in this queue was asked about."""
    _, _, clashes = mod.plan([_d("x", "b", ["a", "b"])], {"a": "elsewhere"}.get)
    assert "'elsewhere'" in clashes["x"]


def test_a_mapping_inside_the_conflict_is_not_in_the_way():
    """The whole point is that these spellings already point at each other."""
    writes, _, clashes = mod.plan([_d("x", "b", ["a", "b"])], {"a": "b"}.get)
    assert writes == [("a", "b")] and not clashes


def test_two_conflicts_sending_one_spelling_to_one_name_is_one_write():
    """`areas under the receiver operating characteristic curve` lost twice."""
    writes, _, clashes = mod.plan(
        [_d("x", "roc", ["a", "shared", "roc"]),
         _d("y", "roc", ["b", "shared", "roc"])], {}.get)
    assert writes == [("a", "roc"), ("shared", "roc"), ("b", "roc")]
    assert not clashes


def test_two_conflicts_sending_one_spelling_to_two_names_is_written_neither_way():
    writes, _, clashes = mod.plan(
        [_d("x", "b", ["torn", "b"]), _d("y", "c", ["torn", "c"])], {}.get)
    assert writes == []
    assert set(clashes) == {"x", "y"}
    assert "more than one name" in clashes["x"]


def test_the_document_name_is_the_decision_id(tmp_path):
    (tmp_path / "d0500+d0502.json").write_text(
        json.dumps({"verdict": "b", "spellings": ["a", "b"]}), encoding="utf-8")
    assert mod.load(tmp_path)[0]["id"] == "d0500+d0502"


# ── the writes themselves ────────────────────────────────────────────────────

def _store(seed=None):
    recs = dict(seed or {})
    def record(term):
        return recs.setdefault(term, {"to": None, "pairs": {}})
    return recs, record


def test_the_winner_stops_pointing_anywhere():
    """`ulcer area` pointed at `area of ulcer` and won against it. Four of the
    28 conflicts are two-cycles like that, so the winner has to be cleared
    before the loser is turned round or the two end up facing each other."""
    recs, record = _store({"ulcer area": {"to": "area of ulcer", "pairs": {}},
                           "area of ulcer": {"to": "ulcer area", "pairs": {}}})
    mod.apply_writes(record, [("area of ulcer", "ulcer area")], "t")
    assert recs["ulcer area"]["to"] is None
    assert recs["area of ulcer"]["to"] == "ulcer area"


def test_a_retired_loser_comes_back_pointing_at_the_winner():
    recs, record = _store({"a": {"to": None, "pairs": {},
                                 "retired": {"reason": "withdrawn"}}})
    mod.apply_writes(record, [("a", "b")], "t")
    assert recs["a"]["to"] == "b" and "retired" not in recs["a"]


def test_the_ruling_is_recorded_on_the_pair_not_just_in_the_arrow():
    recs, record = _store()
    mod.apply_writes(record, [("a", "b")], "2026-09-27T00:00:00+00:00")
    assert recs["a"]["pairs"]["b"]["curator"]["verdict"] == "same_class"
