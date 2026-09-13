"""The store is the one record; a rejection is a verdict in it, not a deletion.

Until 2026-09-12 the blocklist, the predicate filter, the empty-entity prune
and the reasoner gate all `del`-ed cells from the store. The 606-abstract
extraction lost 278 entities that way with no trace in the file, and a term
whose blocklist entry was later withdrawn stayed gone, because there was
nothing left to un-block. Now every one of them writes a verdict -- who, when,
why -- beside the assertion, every reader applies the verdicts through ONE
function, and a verdict can be lifted.
"""
from __future__ import annotations

import pytest

from wound_ontology.store.concept_store import (
    DECISIONS,
    ConceptStore,
    effective_records,
    records_of,
)
from wound_ontology.store.store_cleaner import StoreCleaner


class MockDM:
    def __init__(self, initial=None):
        self._data = initial
        self.saves = 0

    def load_latest_json(self, _):
        return self._data

    def save_as_json(self, data, _):
        self._data = data
        self.saves += 1

    def get_meta_stamp(self, prefix):
        return f"meta_{prefix}_id", f"{prefix}_1"


def _store(data) -> ConceptStore:
    return ConceptStore(MockDM(data), "concept_store")


def _two_abstracts():
    return {
        "1": {"entities": {
            "Wound": {"is_a: material entity": 1.0, "has_quality: Chronic": 1.0},
            "Randomized Controlled Trial": {"is_a: process": 1.0},
        }, "meta_stamp": "a"},
        "2": {"entities": {
            "Wound": {"is_a: material entity": 1.0, "part_of: Skin": 1.0},
            "Skin": {"is_a: material entity": 1.0},
        }, "meta_stamp": "b"},
    }


# ── the verdict, not the delete ──────────────────────────────────────────────

def test_a_rejected_entity_stays_in_the_file_and_leaves_the_view():
    st = _store(_two_abstracts())
    assert st.reject_entities(["Randomized Controlled Trial"], by="blocklist", note="methodology") == 1
    assert "Randomized Controlled Trial" in st.dict["1"]["entities"], "it was deleted"
    assert "Randomized Controlled Trial" not in st.entities
    assert "Randomized Controlled Trial" in st.entities_raw()
    v = st.verdict("Randomized Controlled Trial")
    assert v["by"] == "blocklist" and v["note"] == "methodology" and v["when"]


def test_a_rejected_cell_leaves_only_that_cell():
    st = _store(_two_abstracts())
    assert st.reject_cells([("Wound", "part_of: Skin")], by="reasoner_gate") == 1
    standing = {(e, t) for _, e, t, _ in st.assertions()}
    assert ("Wound", "part_of: Skin") not in standing
    assert ("Wound", "is_a: material entity") in standing
    assert st.dict["2"]["entities"]["Wound"]["part_of: Skin"] == 1.0, "the assertion is gone"


def test_a_verdict_names_a_thing_that_is_in_the_store(capsys):
    """A verdict on nothing is a typo in a list, and is said, not stored."""
    st = _store(_two_abstracts())
    assert st.reject_entities(["Wuond"], by="blocklist") == 0
    assert "Wuond" not in st.decisions()["entity_verdicts"]
    assert "not in the store" in capsys.readouterr().out


def test_the_decisions_record_carries_no_entities_key():
    """A legacy reader doing rec.get("entities", {}) must see nothing there."""
    st = _store(_two_abstracts())
    st.reject_entities(["Skin"], by="blocklist")
    assert "entities" not in st.dict[DECISIONS]
    assert DECISIONS not in dict(st.records())
    assert st.document_keys() == ["1", "2"]


# ── one reading, everywhere ──────────────────────────────────────────────────

def test_every_reader_applies_the_same_verdicts():
    raw = _two_abstracts()
    raw[DECISIONS] = {"entity_verdicts": {"Skin": {"status": "rejected", "by": "blocklist"}},
                      "cell_verdicts": {"Wound": {"has_quality: Chronic":
                                                  {"status": "rejected", "by": "reasoner_gate"}}}}
    from types import SimpleNamespace
    seen_direct = {(e, t) for _, ents in effective_records(raw)
                   for e, a in ents.items() for t in a}
    seen_fake = {(e, t) for _, ents in records_of(SimpleNamespace(dict=raw))
                 for e, a in ents.items() for t in a}
    seen_store = {(e, t) for _, e, t, _ in _store(raw).assertions()}
    assert seen_direct == seen_fake == seen_store
    assert ("Skin", "is_a: material entity") not in seen_direct
    assert ("Wound", "has_quality: Chronic") not in seen_direct
    assert ("Wound", "part_of: Skin") in seen_direct


def test_the_gate_adapter_does_not_see_a_rejected_cell():
    from wound_ontology.llm.extraction_adapter import store_to_gate_inputs
    raw = _two_abstracts()
    _, before, _ = store_to_gate_inputs(raw)
    raw[DECISIONS] = {"cell_verdicts": {"Wound": {"part_of: Skin":
                                                  {"status": "rejected", "by": "reasoner_gate"}}}}
    _, after, _ = store_to_gate_inputs(raw)
    assert len(before) == 1 and after == []


def test_the_hierarchy_does_not_see_a_rejected_entity():
    from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
    from types import SimpleNamespace
    raw = _two_abstracts()
    raw[DECISIONS] = {"entity_verdicts": {"Randomized Controlled Trial":
                                          {"status": "rejected", "by": "blocklist"}}}
    class _DM:
        def load_latest_csv(self, _): return None
        def save_as_csv(self, df, _): pass
    h = ClassHierarchy(_DM())
    h.get_data(SimpleNamespace(dict=raw))
    names = set(h.df.index) | set(h.df.columns)
    assert "Randomized Controlled Trial" not in names
    assert "Wound" in names


# ── the cleaner ──────────────────────────────────────────────────────────────

def test_the_cleaner_rejects_by_name_and_can_be_told_to_reconsider():
    """The capability the delete never had: withdraw the list entry, clean
    again, and the term stands again."""
    st = _store(_two_abstracts())
    c = StoreCleaner(["is_a", "has_quality", "part_of"], extra_blocked_entities={"skin"})
    report = c.clean(st)
    # `Randomized Controlled Trial` is on the real methodology blocklist, so two.
    assert report["blocked_entities"] == 2
    assert st.verdict("Skin")["by"] == "blocklist"
    assert "Skin" not in st.entities
    assert "Skin" in st.dict["2"]["entities"]

    c2 = StoreCleaner(["is_a", "has_quality", "part_of"])       # entry withdrawn
    report = c2.clean(st)
    # two entities plus the `part_of: Skin` cell, whose target was blocked too
    assert report["verdicts_lifted"] == 3, "the earlier verdicts were not reconsidered"
    assert st.verdict("Skin") is None
    assert "Skin" in st.entities
    assert st.verdict("Randomized Controlled Trial")["by"] == "blocklist", "still on the list"


def test_a_rogue_predicate_is_a_cell_verdict():
    st = _store(_two_abstracts())
    StoreCleaner(["is_a", "has_quality"]).clean(st)
    v = st.verdict("Wound", "part_of: Skin")
    assert v and v["by"] == "predicate_filter"
    assert st.dict["2"]["entities"]["Wound"]["part_of: Skin"] == 1.0


def test_the_prune_reads_the_whole_store_not_one_abstract():
    """Denied in one abstract, asserted in another, is a standing term."""
    raw = _two_abstracts()
    raw["3"] = {"entities": {"Skin": {"is_a: material entity": 0.0}}, "meta_stamp": "c"}
    st = _store(raw)
    StoreCleaner(["is_a", "has_quality", "part_of"]).clean(st)
    assert st.verdict("Skin") is None
    raw2 = {"3": {"entities": {"Only Denied": {"is_a: process": 0.0}}, "meta_stamp": "c"}}
    st2 = _store(raw2)
    StoreCleaner(["is_a"]).clean(st2)
    assert st2.verdict("Only Denied")["by"] == "prune"


def test_lifting_is_by_author_only():
    st = _store(_two_abstracts())
    st.reject_entities(["Skin"], by="blocklist")
    st.reject_cells([("Wound", "part_of: Skin")], by="reasoner_gate")
    lifted = st.lift_decisions("blocklist")
    assert set(lifted["entity_verdicts"]) == {"Skin"} and lifted["cell_verdicts"] == {}
    assert st.verdict("Wound", "part_of: Skin")["by"] == "reasoner_gate"
    assert st.restore_decisions(lifted) == 1
    assert st.verdict("Skin")["by"] == "blocklist"


# ── the gate ─────────────────────────────────────────────────────────────────

class _Rel:
    def __init__(self, s, p, o):
        from types import SimpleNamespace
        self.subject, self.predicate, self.object = s, SimpleNamespace(value=p), o


def _orchestrator_with_gate(result):
    from wound_ontology.orchestrator import Orchestrator
    o = object.__new__(Orchestrator)
    o._gate = type("G", (), {
        "least_common_category": staticmethod(lambda cats: None),
        "check": lambda self, e, r: result,
    })()
    return o


def _gate_result(*, quarantined=(), skipped=None):
    from wound_ontology.reasoning.gate import GateResult
    return GateResult(quarantined_relations=list(quarantined), skipped=skipped,
                      explanation="continuant/occurrent clash")


def test_the_gate_rejects_a_quarantined_triple_instead_of_deleting_it(monkeypatch):
    st = _store(_two_abstracts())
    o = _orchestrator_with_gate(_gate_result(quarantined=[_Rel("Wound", "part_of", "Skin")]))
    o.run_gate_store_relations(store=st, quarantine=False)
    v = st.verdict("Wound", "part_of: Skin")
    assert v and v["by"] == "reasoner_gate" and "clash" in v["note"]
    assert st.dict["2"]["entities"]["Wound"]["part_of: Skin"] == 1.0


def test_a_rerun_of_the_gate_gives_its_own_verdicts_a_new_hearing():
    st = _store(_two_abstracts())
    st.reject_cells([("Wound", "part_of: Skin")], by="reasoner_gate", note="old WONT")
    o = _orchestrator_with_gate(_gate_result())          # clean this time
    o.run_gate_store_relations(store=st, quarantine=False)
    assert st.verdict("Wound", "part_of: Skin") is None, "the old verdict outlived the re-test"


def test_a_skipped_gate_puts_its_lifted_verdicts_back():
    st = _store(_two_abstracts())
    st.reject_cells([("Wound", "part_of: Skin")], by="reasoner_gate", note="old WONT")
    o = _orchestrator_with_gate(_gate_result(skipped="robot not found"))
    o.run_gate_store_relations(store=st, quarantine=False)
    v = st.verdict("Wound", "part_of: Skin")
    assert v and v["note"] == "old WONT", "a gate that could not run un-vetted the store"


# ── normalisation keeps the verdicts attached ────────────────────────────────

def test_a_verdict_follows_its_entity_through_normalisation():
    raw = {"1": {"entities": {"diabetic foot ulcers": {"is_a: material entity": 1.0,
                                                       "part_of: lower limbs": 1.0}},
                 "meta_stamp": "a"}}
    st = _store(raw)
    st.reject_entities(["diabetic foot ulcers"], by="blocklist")
    st.reject_cells([("diabetic foot ulcers", "part_of: lower limbs")], by="reasoner_gate")
    class _Mapper:
        mapping = {"diabetic foot ulcers": "Diabetic Foot Ulcer", "lower limbs": "Lower Limb"}
    st.normalize(_Mapper())
    assert "Diabetic Foot Ulcer" in st.dict["1"]["entities"]
    assert st.verdict("Diabetic Foot Ulcer")["by"] == "blocklist"
    assert st.rejected_cells()["Diabetic Foot Ulcer"]["part_of: Lower Limb"]["by"] == "reasoner_gate"
    assert st.decisions()["renamed"]["diabetic foot ulcers"]["to"] == "Diabetic Foot Ulcer"
    assert st.entities == []


def test_summary_is_measured():
    st = _store(_two_abstracts())
    st.reject_entities(["Skin"], by="blocklist")
    st.reject_cells([("Wound", "has_quality: Chronic")], by="reasoner_gate")
    s = st.summary()
    assert s == {"documents": 2, "cells_raw": 6, "cells_standing": 4, "cells_rejected": 2,
                 "rejected_entities": 1, "rejected_cells": 1,
                 "verdicts_by": {"cell:reasoner_gate": 1, "entity:blocklist": 1},
                 "renamed": 0}
