"""The class hierarchy is a view, and the edge gate's verdicts are is_a judgements.

Curator, 2026-10-21: "Die Klassenhierarchie kann es weiterhin geben, aber
einfach als view." refresh_class_hierarchy derives it from WONT + MILD, the
store read through the register, the placements and the accepted FCA slices;
nothing but a provenance snapshot is written.

Rule 89 (2026-10-28): ELK writes its verdict on an edge into the term dict, as
an is_a judgement of the child, with its own reason and only when its own last
word changes. Every fresh view takes off what an is_a `no` refuses; the gate
hears ELK's own verdicts again. An edge the author made or confirmed is never
dropped: if ELK cannot keep one, the run stops.
"""
from types import SimpleNamespace

import pandas as pd
import pytest

import wound_ontology.orchestrator as orch
from wound_ontology.hierarchies.base_hierarchy import SOURCE_CURATED, SOURCE_TEXT
from wound_ontology.mappers.judgements import current, make
from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate


class _DM:
    def __init__(self):
        self.json = {}

    def load_latest_json(self, prefix):
        return self.json.get(prefix)

    def save_as_json(self, data, prefix):
        self.json[prefix] = data


class _View:
    """Three edges, stamped like the real view."""

    def __init__(self):
        self.df = pd.DataFrame(0.0, index=["Burn", "Ulcer", "Chronic Wound"],
                               columns=["Process", "Wound"])
        self.df.at["Burn", "Process"] = 1.0
        self.df.at["Ulcer", "Wound"] = 1.0
        self.df.at["Chronic Wound", "Wound"] = 1.0
        self._prov = {("Burn", "Process"): SOURCE_TEXT, ("Ulcer", "Wound"): SOURCE_TEXT,
                      ("Chronic Wound", "Wound"): SOURCE_CURATED}
        self.names = {}
        self.verdicts_applied = False
        self.snapshot = 0

    def save_snapshot(self):
        self.snapshot += 1


class _Result:
    def __init__(self, quarantined, skipped=None):
        self.quarantined = quarantined
        self.quarantined_sources = {}
        self.spared = []
        self.skipped = skipped
        self.explanation = "the run's one explanation"
        self.why = {e: f"{e[0]} is an occurrent" for e in quarantined}
        self.unsatisfiable = []

    def summary(self):
        return "fake"


class _Gate:
    def __init__(self, result):
        self.result, self.seen, self.sources = result, None, None

    def check_edges(self, edges, sources=None):
        self.seen, self.sources = sorted(edges), sources
        return self.result


def _tm():
    return TermMappingAndGate(_DM())


def _pipeline(tm, gate, view):
    p = orch.Orchestrator.__new__(orch.Orchestrator)
    p.dm = _DM()
    p._gate = gate
    p._class_hier = None
    p.term_mapper = SimpleNamespace(_term_mapping=tm)
    calls = []

    def refresh(include_rejected=False):
        calls.append(include_rejected)
        p._apply_is_a_verdicts(view, reopen=p.GATE_AUTHOR if include_rejected else None)
        view.verdicts_applied = not include_rejected
        p._class_hier = view
        return view

    p.refresh_class_hierarchy = refresh
    p.calls = calls
    return p


def test_the_gate_hears_its_own_verdicts_again_and_writes_each_with_its_reason(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.QUARANTINE_DIR", tmp_path, raising=False)
    tm = _tm()
    tm.records["Ulcer"] = {"is_a": {"Wound": [make("no", "elk", "old WONT", "2026-10-01T12:00:00")]}}
    tm._dirty()
    view = _View()
    gate = _Gate(_Result([("Burn", "Process")]))
    p = _pipeline(tm, gate, view)

    p.run_gate_hierarchy_edges(quarantine=False)

    assert p.calls == [True], "the gate must derive the view with ELK's verdicts set aside"
    assert ("Ulcer", "Wound") in gate.seen, "an earlier refusal gets its hearing again"
    burn = current(tm.records["Burn"]["is_a"]["Process"])
    assert (burn["verdict"], burn["by"], burn["why"]) == ("no", "elk", "Burn is an occurrent")
    ulcer = current(tm.records["Ulcer"]["is_a"]["Wound"])
    assert (ulcer["verdict"], ulcer["by"]) == ("yes", "elk"), "re-heard and kept: ELK says so"
    assert view.df.at["Burn", "Process"] == 0.0
    assert view.df.at["Ulcer", "Wound"] == 1.0
    assert view.verdicts_applied and view.snapshot == 1


def test_elk_writes_only_when_its_word_changes(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.QUARANTINE_DIR", tmp_path, raising=False)
    tm = _tm()
    for _ in range(3):
        p = _pipeline(tm, _Gate(_Result([("Burn", "Process")])), _View())
        p.run_gate_hierarchy_edges(quarantine=False)
    assert len(tm.records["Burn"]["is_a"]["Process"]) == 1
    assert "Ulcer" not in tm.records, "an edge ELK never refused needs no yes"


def test_a_gate_that_does_not_run_keeps_the_old_verdicts(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.QUARANTINE_DIR", tmp_path, raising=False)
    tm = _tm()
    tm.records["Ulcer"] = {"is_a": {"Wound": [make("no", "elk", "old WONT", "2026-10-01T12:00:00")]}}
    tm._dirty()
    view = _View()
    p = _pipeline(tm, _Gate(_Result([], skipped="robot not on PATH")), view)

    p.run_gate_hierarchy_edges(quarantine=False)

    assert len(tm.records["Ulcer"]["is_a"]["Wound"]) == 1, "a skipped gate writes nothing"
    assert view.df.at["Ulcer", "Wound"] == 0.0, "the standing verdict is put back on the view"
    assert view.verdicts_applied


def test_a_curated_edge_is_never_taken_off_by_a_verdict():
    tm = _tm()
    tm.records["Chronic Wound"] = {"is_a": {"Wound": [make("no", "elk", "x", "2026-10-01T12:00:00")]}}
    tm._dirty()
    p = _pipeline(tm, _Gate(_Result([])), _View())
    view = _View()
    assert p._apply_is_a_verdicts(view) == 0
    assert view.df.at["Chronic Wound", "Wound"] == 1.0


def test_any_is_a_no_takes_the_edge_off_the_view():
    """The hierarchy is a view of the is_a judgements: the author's `no` counts too."""
    tm = _tm()
    tm.records["Ulcer"] = {"is_a": {"Wound": [make("no", "author", "not a wound", "2026-10-01T12:00:00")]}}
    tm._dirty()
    p = _pipeline(tm, _Gate(_Result([])), _View())
    view = _View()
    assert p._apply_is_a_verdicts(view) == 1
    assert view.df.at["Ulcer", "Wound"] == 0.0
    assert p._apply_is_a_verdicts(_View(), reopen="elk") == 1, "only ELK's own are set aside"


def test_an_author_edge_ranks_as_curated_and_is_never_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.QUARANTINE_DIR", tmp_path, raising=False)
    tm = _tm()
    tm.records["Ulcer"] = {"is_a": {"Wound": [make("yes", "author", "a wound", "2026-10-01T12:00:00")]}}
    tm._dirty()
    gate = _Gate(_Result([("Ulcer", "Wound")]))
    p = _pipeline(tm, gate, _View())
    with pytest.raises(RuntimeError, match="author"):
        p.run_gate_hierarchy_edges(quarantine=False)
    assert gate.sources[("Ulcer", "Wound")] == SOURCE_CURATED, "the author's edge gives way last"
    assert [j["by"] for j in tm.records["Ulcer"]["is_a"]["Wound"]] == ["author"], "nothing written"


def test_the_spellings_of_one_edge_are_read_together():
    """`Drug product` (the author's yes) and `drug product` (a refused proposal)
    are one edge in the view: the author's word counts, whichever key is read last."""
    tm = _tm()
    tm.records["Ulcer"] = {"is_a": {
        "Wound": [make("yes", "author", "placed", "2026-10-07T12:00:00", iri="WONT_1")],
        "wound": [make("yes", "deepseek-v4-flash_top_15", "proposed", "2026-10-01T12:00:00", iri="X_1"),
                  make("no", "elk", "a clash", "2026-10-20T12:00:00")]}}
    tm._dirty()
    p = _pipeline(tm, _Gate(_Result([])), _View())
    view = _View()
    assert p._apply_is_a_verdicts(view) == 0
    assert view.df.at["Ulcer", "Wound"] == 1.0


def test_a_refused_placement_is_not_a_verdict_on_the_edge():
    """Refusing to put a term directly under an ontology class says nothing
    against the term being one (2026-10-28: 14 typings to `quality` were lost
    when a refused placement under PATO `quality` was read as a `no`)."""
    tm = _tm()
    tm.records["Ulcer"] = {"is_a": {"Wound": [
        make("yes", "deepseek-v4-flash_top_15", "proposed", "2026-10-01T12:00:00", iri="WONT_1"),
        make("no", "claude-opus-5-5", "placement refused; self-check: no parent", "2026-10-02T12:00:00", iri="WONT_1")]}}
    tm._dirty()
    p = _pipeline(tm, _Gate(_Result([])), _View())
    view = _View()
    assert p._apply_is_a_verdicts(view) == 0
    assert tm.cell("Ulcer", "is_a: Wound")["verdict"] == "yes"
    assert tm.placements() == [], "the placement itself stays refused"
