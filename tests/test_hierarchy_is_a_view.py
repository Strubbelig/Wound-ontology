"""The class hierarchy is a view, and the edge gate's verdicts live beside it.

Curator, 2026-10-21: "Die Klassenhierarchie kann es weiterhin geben, aber
einfach als view." refresh_class_hierarchy derives it from WONT + MILD, the
store read through the register, the placements and the accepted FCA slices;
nothing but a provenance snapshot is written. What used to make the gated
hierarchy durable -- the matrix CSV the edge gate saved after removing edges --
is replaced by a verdict record the gate rewrites on every run and every fresh
view applies. These tests pin that contract.
"""
import pandas as pd

import wound_ontology.orchestrator as orch
from wound_ontology.hierarchies.base_hierarchy import SOURCE_CURATED, SOURCE_TEXT


class _DM:
    def __init__(self, verdicts=None):
        self.json = {}
        if verdicts is not None:
            self.json["class_hierarchy_edge_verdicts"] = verdicts

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
        self.explanation = "Burn is an occurrent"
        self.unsatisfiable = []

    def summary(self):
        return "fake"


class _Gate:
    def __init__(self, result):
        self.result, self.seen = result, None

    def check_edges(self, edges, sources=None):
        self.seen = sorted(edges)
        return self.result


def _pipeline(dm, gate, view):
    p = orch.Orchestrator.__new__(orch.Orchestrator)
    p.dm = dm
    p._gate = gate
    p._class_hier = None
    calls = []

    def refresh(include_rejected=False):
        calls.append(include_rejected)
        if not include_rejected:
            p._apply_edge_verdicts(view)
            view.verdicts_applied = True
        p._class_hier = view
        return view

    p.refresh_class_hierarchy = refresh
    p.calls = calls
    return p


def test_the_gate_hears_every_edge_again_and_replaces_the_record(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.QUARANTINE_DIR", tmp_path, raising=False)
    dm = _DM(verdicts={"rejected": [{"child": "Ulcer", "parent": "Wound"}]})
    view = _View()
    gate = _Gate(_Result([("Burn", "Process")]))
    p = _pipeline(dm, gate, view)

    p.run_gate_hierarchy_edges(quarantine=False)

    assert p.calls == [True], "the gate must derive the view WITH earlier rejections"
    assert ("Ulcer", "Wound") in gate.seen, "an earlier rejection gets its hearing again"
    rec = dm.json["class_hierarchy_edge_verdicts"]["rejected"]
    assert [(r["child"], r["parent"], r["source"]) for r in rec] == [("Burn", "Process", SOURCE_TEXT)]
    assert view.df.at["Burn", "Process"] == 0.0
    assert view.df.at["Ulcer", "Wound"] == 1.0, "re-heard and accepted: back in the view"
    assert view.verdicts_applied and view.snapshot == 1


def test_a_gate_that_does_not_run_keeps_the_old_verdicts(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.QUARANTINE_DIR", tmp_path, raising=False)
    old = {"rejected": [{"child": "Ulcer", "parent": "Wound"}]}
    dm = _DM(verdicts=old)
    view = _View()
    p = _pipeline(dm, _Gate(_Result([], skipped="robot not on PATH")), view)

    p.run_gate_hierarchy_edges(quarantine=False)

    assert dm.json["class_hierarchy_edge_verdicts"] is old, "a skipped gate rewrites nothing"
    assert view.df.at["Ulcer", "Wound"] == 0.0, "the standing verdict is put back on the view"
    assert view.verdicts_applied


def test_a_curated_edge_is_never_taken_off_by_a_verdict():
    dm = _DM(verdicts={"rejected": [{"child": "Chronic Wound", "parent": "Wound"}]})
    p = orch.Orchestrator.__new__(orch.Orchestrator)
    p.dm = dm
    view = _View()
    assert p._apply_edge_verdicts(view) == 0
    assert view.df.at["Chronic Wound", "Wound"] == 1.0


def test_a_malformed_verdict_record_stops_the_build():
    import pytest
    p = orch.Orchestrator.__new__(orch.Orchestrator)
    p.dm = _DM(verdicts=[["Burn", "Process"]])
    with pytest.raises(ValueError, match="edge-verdict record"):
        p._edge_verdicts()
