"""The two exact curation lists are a printout of the gate, not a place to decide.

Until 2026-09-25 `METHODOLOGY_BLOCKLIST` (7,757) and `WHITELIST` (2,684) were
the authoring surface, and a `cos >= 0.92` threshold and an LLM batch wrote
straight into them. Now the record decides and the literal is regenerated from
it, so an entry cannot exist without naming who put it there — and a hand edit
between exports is a decision the next export erases, which the banner says.

The invariant these pin: after any write, the file and the gate agree. Drift
means two writers again.
"""

import ast
import importlib.util
import shutil
from pathlib import Path

import pytest

from conftest import memory_mapping
from wound_ontology.store.term_lists import (
    export_gate_lists, write_generated_list, _entry_value,
)

ROOT = Path(__file__).resolve().parents[1]


def _members(path: Path, var: str) -> set[str]:
    """Every entry the literal holds, by executing the module it lives in."""
    spec = importlib.util.spec_from_file_location("cfg_" + var.lower(), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(getattr(mod, var))


@pytest.fixture
def config(tmp_path):
    """A copy of the real config files, so a test can rewrite them safely."""
    d = tmp_path / "config"
    d.mkdir()
    for name in ("blocklist.py", "whitelist.py"):
        shutil.copy(ROOT / "config" / name, d / name)
    return d


# ── the writer ───────────────────────────────────────────────────────────────

def test_the_export_reproduces_what_was_there(config):
    before_b = _members(config / "blocklist.py", "METHODOLOGY_BLOCKLIST")
    g = memory_mapping()
    for t in before_b:
        g.gate(t, rule={"verdict": "out", "by": "list", "section": "# ── s ──"})
    export_gate_lists(g, config, quiet=True)
    assert _members(config / "blocklist.py", "METHODOLOGY_BLOCKLIST") == before_b


def test_the_other_literals_in_the_file_are_untouched(config):
    before = _members(config / "whitelist.py", "KEYWORD_WHITELIST")
    g = memory_mapping()
    g.gate("wound care", rule={"verdict": "in", "by": "list"})
    export_gate_lists(g, config, quiet=True)
    assert _members(config / "whitelist.py", "KEYWORD_WHITELIST") == before


def test_the_file_says_it_is_generated(config):
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out"})
    export_gate_lists(g, config, quiet=True)
    text = (config / "blocklist.py").read_text()
    assert "GENERATED" in text and "do not edit by hand" in text


def test_a_term_dropped_from_the_gate_leaves_the_file(config):
    # a spelling no real list holds, so the assertion cannot pass on a file the
    # export never touched
    probe = "zzz gate probe term"
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out"})
    g.gate(probe, rule={"verdict": "out"})
    export_gate_lists(g, config, quiet=True)
    assert _members(config / "blocklist.py", "METHODOLOGY_BLOCKLIST") == {"cohort", probe}
    g.gate(probe, curator={"verdict": "in"})
    export_gate_lists(g, config, quiet=True)
    assert _members(config / "blocklist.py", "METHODOLOGY_BLOCKLIST") == {"cohort"}
    assert _members(config / "whitelist.py", "WHITELIST") == {probe}


def test_the_section_headers_survive_the_round_trip(config):
    g = memory_mapping()
    g.gate("a term", rule={"verdict": "out", "section": "# ── alpha ──"})
    g.gate("b term", rule={"verdict": "out", "section": "# ── beta ──"})
    export_gate_lists(g, config, quiet=True)
    text = (config / "blocklist.py").read_text()
    assert "# ── alpha ──" in text and "# ── beta ──" in text


def test_an_entry_with_no_section_says_who_decided_it(config):
    g = memory_mapping()
    g.gate("photobiomodulation", curator={"verdict": "out", "reason": "…"})
    export_gate_lists(g, config, quiet=True)
    assert "# ── decided by curator, no section ──" in (config / "blocklist.py").read_text()


def test_a_term_holding_a_double_quote_round_trips(config):
    # one real blocklist entry does, and an f-string writer emitted broken Python
    g = memory_mapping()
    g.gate('"long hu hui" pi risk management platform', rule={"verdict": "out"})
    export_gate_lists(g, config, quiet=True)
    assert _members(config / "blocklist.py", "METHODOLOGY_BLOCKLIST") == {
        '"long hu hui" pi risk management platform'}


def test_a_non_ascii_term_stays_readable(config):
    g = memory_mapping()
    g.gate("lésions endothéliales chroniques", rule={"verdict": "out"})
    export_gate_lists(g, config, quiet=True)
    assert "lésions endothéliales chroniques" in (config / "blocklist.py").read_text()


def test_the_file_still_parses_as_python(config):
    g = memory_mapping()
    for t in ('a "quoted" term', "lésion", "plain"):
        g.gate(t, rule={"verdict": "out"})
    export_gate_lists(g, config, quiet=True)
    ast.parse((config / "blocklist.py").read_text())


def test_the_write_is_verified_not_assumed(config, monkeypatch):
    # rule 30: a write that did not land raises instead of reporting success
    import wound_ontology.store.term_lists as tl
    monkeypatch.setattr(tl, "_entry_line", lambda t: "    # swallowed")
    with pytest.raises(RuntimeError, match="did not read back"):
        write_generated_list(config / "blocklist.py", "METHODOLOGY_BLOCKLIST",
                             [("# ── s ──", ["cohort"])])


def test_an_absent_variable_is_named(config):
    # the message has to say the file does not DECLARE it; falling through to
    # `_find_block_end` also raises and also names it, which is a different bug
    # reported as this one
    with pytest.raises(RuntimeError, match="does not declare 'NOT_A_LIST'"):
        write_generated_list(config / "blocklist.py", "NOT_A_LIST", [("", ["x"])])


# ── the drift check ──────────────────────────────────────────────────────────

def test_the_live_files_and_the_live_gate_agree():
    # the invariant, on the real record and the real config files
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    from config.blocklist import METHODOLOGY_BLOCKLIST
    from config.whitelist import WHITELIST
    g = TermMappingAndGate(DataManager(), file_name="term_mapping")
    assert {t.lower() for t in g.gated("out")} == {t.lower() for t in METHODOLOGY_BLOCKLIST}
    assert {t.lower() for t in g.gated("in")} == {t.lower() for t in WHITELIST}
