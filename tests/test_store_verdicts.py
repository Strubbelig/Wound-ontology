"""The store is the one record; a rejection is a verdict in it, not a deletion.

Until 2026-09-12 the blocklist, the predicate filter, the empty-entity prune
and the reasoner gate all `del`-ed cells from the store. The 606-abstract
extraction lost 278 entities that way with no trace in the file, and a term
whose blocklist entry was later withdrawn stayed gone, because there was
nothing left to un-block. Now every one of them writes a verdict -- who, when,
why -- beside the assertion, every reader applies the verdicts through ONE
function, and a verdict can be lifted.

Since rule 51 (2026-09-27) the verdicts are written onto the TERM's record in
the term mapping and gate dict, not into a `decisions` record beside the
PMIDs; the store's file is evidence only, and its view applies them.

Since rule 89 (2026-10-28) a verdict is a judgement -- verdict, by, why, when --
in that record: a whole entity is kept out by its scope, a cell by a `no`. A
verdict is never lifted; a later judgement counts instead, and the reasoner
hears its own verdicts again by having the view set them aside (`reopen`).
"""
from __future__ import annotations

import pytest

from wound_ontology.mappers.judgements import current
from wound_ontology.store.concept_store import (
    DECISIONS,
    ConceptStore,
    effective_records,
    records_of,
)


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
    assert st.reject_entities(["Randomized Controlled Trial"], by="methodology-blocklist", note="methodology") == 1
    assert "Randomized Controlled Trial" in st.dict["1"]["entities"], "it was deleted"
    assert "Randomized Controlled Trial" not in st.entities
    assert "Randomized Controlled Trial" in st.entities_raw()
    v = st.verdict("Randomized Controlled Trial")
    assert v["by"] == "methodology-blocklist" and v["note"] == "methodology" and v["when"]


def test_a_rejected_cell_leaves_only_that_cell():
    st = _store(_two_abstracts())
    assert st.reject_cells([("Wound", "part_of: Skin")], by="elk") == 1
    standing = {(e, t) for _, e, t, _ in st.assertions()}
    assert ("Wound", "part_of: Skin") not in standing
    assert ("Wound", "is_a: material entity") in standing
    assert st.dict["2"]["entities"]["Wound"]["part_of: Skin"] == 1.0, "the assertion is gone"


def test_a_verdict_names_a_thing_that_is_in_the_store(capsys):
    """A verdict on nothing is a typo in a list, and is said, not stored."""
    st = _store(_two_abstracts())
    assert st.reject_entities(["Wuond"], by="methodology-blocklist") == 0
    assert "Wuond" not in st.decisions()["entity_verdicts"]
    assert "not in the store" in capsys.readouterr().out


def test_a_verdict_goes_to_the_term_dict_and_the_file_stays_evidence():
    """Rule 51: nothing but PMIDs (and synthetic evidence) sits in the file."""
    st = _store(_two_abstracts())
    st.reject_entities(["Skin"], by="methodology-blocklist")
    st.reject_cells([("Wound", "part_of: Skin")], by="elk")
    assert DECISIONS not in st.dict
    assert current(st.terms.records["Skin"]["scope"])["by"] == "methodology-blocklist"
    assert current(st.terms.records["Wound"]["relations"]["part_of: Skin"])["by"] == "elk"
    assert st.document_keys() == ["1", "2"]


def test_a_file_that_still_holds_decisions_is_refused():
    """A pre-rule-51 file's verdicts would be ignored by the view -- 2,330
    rejected entities back in the hierarchy, and nothing said. Loud instead."""
    raw = _two_abstracts()
    raw[DECISIONS] = {"entity_verdicts": {"Skin": {"status": "rejected", "by": "blocklist"}}}
    with pytest.raises(ValueError, match="p4_split_evidence_and_decisions"):
        _store(raw)


# ── one reading, everywhere ──────────────────────────────────────────────────

def test_every_reader_applies_the_same_cell_verdicts():
    raw = _two_abstracts()
    raw[DECISIONS] = {"cell_verdicts": {"Wound": {"has_quality: Chronic":
                                                  {"status": "rejected", "by": "elk"}}}}
    from types import SimpleNamespace
    seen_direct = {(e, t) for _, ents in effective_records(raw)
                   for e, a in ents.items() for t in a}
    seen_fake = {(e, t) for _, ents in records_of(SimpleNamespace(dict=raw))
                 for e, a in ents.items() for t in a}
    st = _store(_two_abstracts())
    st.reject_cells([("Wound", "has_quality: Chronic")], by="elk")
    seen_store = {(e, t) for _, e, t, _ in st.assertions()}
    seen_store_fn = {(e, t) for _, ents in records_of(st) for e, a in ents.items() for t in a}
    assert seen_direct == seen_fake == seen_store == seen_store_fn
    assert ("Wound", "has_quality: Chronic") not in seen_direct
    assert ("Wound", "part_of: Skin") in seen_direct


def test_the_gate_adapter_does_not_see_a_rejected_cell():
    from wound_ontology.llm.extraction_adapter import store_to_gate_inputs
    raw = _two_abstracts()
    _, before, _ = store_to_gate_inputs(raw)
    raw[DECISIONS] = {"cell_verdicts": {"Wound": {"part_of: Skin":
                                                  {"status": "rejected", "by": "elk"}}}}
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


# ── the cleaned store is a view (rule 86) ───────────────────────────────────

def test_scope_is_read_live_so_a_later_judgement_needs_no_lifting():
    """A later judgement and the term stands again: the view asks the term
    dict each time, and the store holds no copy of the answer (rules 51, 86, 89)."""
    st = _store(_two_abstracts())
    st.terms.gate("Skin", rule={"verdict": "out", "by": "noise: test"})
    assert "Skin" not in st.entities
    assert ("Wound", "part_of: Skin") not in {(e, t) for _, e, t, _ in st.assertions()}
    assert "Skin" in st.dict["2"]["entities"], "the evidence is untouched"
    st.terms.gate("Skin", pass2={"verdict": "in", "reason": "skin is where a wound is"})
    assert "Skin" in st.entities
    assert ("Wound", "part_of: Skin") in {(e, t) for _, e, t, _ in st.assertions()}


def test_the_cleaned_store_is_a_property_computed_on_every_read():
    st = _store(_two_abstracts())
    assert "Skin" in st.cleaned["2"]
    st.terms.gate("Skin", curator={"verdict": "out"})
    assert "Skin" not in st.cleaned["2"]
    assert "Skin" in st.dict["2"]["entities"]


def test_no_list_decides_anything():
    """`Randomized Controlled Trial` was on the methodology blocklist; with the
    lists gone (2026-10-25) only a verdict keeps it out."""
    st = _store(_two_abstracts())
    assert "Randomized Controlled Trial" in st.entities
    st.terms.gate("Randomized Controlled Trial", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert "Randomized Controlled Trial" not in st.entities


def test_a_curator_scope_ruling_reaches_the_store_at_once():
    """Without a Blocker the gate itself decides; a ruling needs no clean."""
    st = _store(_two_abstracts())
    st.terms.gate("Skin", curator={"verdict": "out"})
    assert "Skin" not in st.entities
    st.terms.gate("Skin", curator={"verdict": "in"})
    assert "Skin" in st.entities



@pytest.mark.parametrize("category", ["process", "material entity", "Process", "quality"])
def test_a_bfo_category_is_never_out_of_scope(category):
    """2026-09-28: the scope pass was asked about `process`, `material entity`
    and the other category names -- they are typing TARGETS, so they sat in
    the undecided pool -- and answered `out` ("generic upper-level class").
    The view drops a cell whose target is out of scope, so every `is_a:
    <category>` typing in the store vanished, and with it the category the
    mapping guard, the hierarchies and the reasoner gate all read. A category
    is declared, never gated (rules 20, 22)."""
    st = _store(_two_abstracts())
    st.terms.gate(category, pass2={"verdict": "out"})
    st.terms.gate(category.lower(), pass2={"verdict": "out"})
    kept = {(e, t) for _, e, t, _ in st.assertions()}
    assert ("Wound", "is_a: material entity") in kept
    assert not st.out_of_scope({category})


def test_a_relation_the_schema_does_not_allow_is_left_out_of_the_view():
    st = _store(_two_abstracts())
    st.allowed_predicates = ["is_a", "has_quality"]
    assert ("Wound", "part_of: Skin") not in {(e, t) for _, e, t, _ in st.assertions()}
    assert st.dict["2"]["entities"]["Wound"]["part_of: Skin"] == 1.0, "nothing is written"
    st.allowed_predicates = None
    assert ("Wound", "part_of: Skin") in {(e, t) for _, e, t, _ in st.assertions()}


def test_an_entity_nothing_affirms_is_left_out_but_the_whole_store_counts():
    """Denied in one abstract, asserted in another, is a standing term; an
    entity only ever denied is not in the cleaned store."""
    raw = _two_abstracts()
    raw["3"] = {"entities": {"Skin": {"is_a: material entity": 0.0},
                             "Only Denied": {"is_a: process": 0.0}}, "meta_stamp": "c"}
    st = _store(raw)
    assert "Skin" in st.cleaned["3"], "denied here, asserted in abstract 2"
    assert "Only Denied" not in st.entities
    assert "Only Denied" in st.dict["3"]["entities"]


def test_a_refused_typing_takes_off_the_typing_not_the_mention():
    """A term whose every cell is refused is still named by its abstract: only
    its scope takes it out of the cleaned store (curator, 2026-10-29 -- ELK's
    refusal of `Allergy is_a disposition` had emptied Allergy from all 4
    abstracts, and its placement fell below the evidence cut)."""
    st = _store(_two_abstracts())
    assert st.reject_cells([("Randomized Controlled Trial", "is_a: process")], by="elk") == 1
    assert st.cleaned["1"]["Randomized Controlled Trial"] == {}, "the typing stayed, or the mention went"
    assert "Randomized Controlled Trial" in st.entities
    st.reject_entities(["Randomized Controlled Trial"], by="methodology-blocklist", note="methodology")
    assert "Randomized Controlled Trial" not in st.entities, "scope no longer takes it out"


def test_reopening_sets_aside_one_agents_verdicts_and_writes_nothing():
    st = _store(_two_abstracts())
    st.reject_cells([("Wound", "part_of: Skin")], by="elk")
    st.reject_cells([("Wound", "has_quality: Chronic")], by="author")
    before = {k: [dict(j) for j in v] for k, v in st.terms.records["Wound"]["relations"].items()}
    st.reopen = ("elk", "relations")
    seen = {(e, t) for _, e, t, _ in st.assertions()}
    st.reopen = None
    assert ("Wound", "part_of: Skin") in seen, "ELK's own verdict is set aside for its re-check"
    assert ("Wound", "has_quality: Chronic") not in seen, "the author's still counts"
    assert ("Wound", "part_of: Skin") not in {(e, t) for _, e, t, _ in st.assertions()}
    assert st.terms.records["Wound"]["relations"] == before


def test_reopening_also_rehears_a_decided_category_elk_refused():
    """A category the end-word rule decided and ELK refused is heard again
    when ELK's verdicts are set aside: the refusal must not hide its own
    subject (2026-10-29: 98 such categories were never re-heard)."""
    raw = _two_abstracts()
    raw["2"]["entities"]["Skin"] = {"is_a: process": 1.0}
    st = _store(raw)
    st.terms.set_category("Skin", "material entity", source="head rule: skin", by="end-word-category")
    st.reject_cells([("Skin", "is_a: material entity")], by="elk")
    assert st.cleaned["2"]["Skin"] == {"is_a: process": 1.0}, "ELK's refusal counts in the plain view"
    st.reopen = ("elk", "is_a")
    reheard = st.cleaned["2"]["Skin"]
    st.reopen = None
    assert reheard == {"is_a: material entity": 1.0}, "the decided category was not heard again"


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
    assert v and v["by"] == "elk" and "clash" in v["note"]
    assert st.dict["2"]["entities"]["Wound"]["part_of: Skin"] == 1.0


def test_the_gate_writes_each_triple_its_own_reason():
    from wound_ontology.reasoning.gate import GateResult
    st = _store(_two_abstracts())
    r = _Rel("Wound", "part_of", "Skin")
    o = _orchestrator_with_gate(GateResult(quarantined_relations=[r], explanation="the run's one note",
                                           why={("Wound", "part_of", "Skin"): "Skin is a process here"}))
    o.run_gate_store_relations(store=st, quarantine=False)
    assert st.verdict("Wound", "part_of: Skin")["note"] == "Skin is a process here"
    o.run_gate_store_relations(store=st, quarantine=False)
    assert len(st.terms.records["Wound"]["relations"]["part_of: Skin"]) == 1, "unchanged: nothing written"


def test_a_rerun_of_the_gate_gives_its_own_verdicts_a_new_hearing():
    st = _store(_two_abstracts())
    st.reject_cells([("Wound", "part_of: Skin")], by="elk", note="old WONT")
    o = _orchestrator_with_gate(_gate_result())          # clean this time
    o.run_gate_store_relations(store=st, quarantine=False)
    assert st.verdict("Wound", "part_of: Skin") is None, "the old verdict outlived the re-test"
    js = st.terms.records["Wound"]["relations"]["part_of: Skin"]
    assert [j["verdict"] for j in js] == ["no", "yes"], "nothing is deleted; ELK's later yes counts"


def test_a_skipped_gate_leaves_its_verdicts_standing():
    st = _store(_two_abstracts())
    st.reject_cells([("Wound", "part_of: Skin")], by="elk", note="old WONT")
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
    st.reject_entities(["diabetic foot ulcers"], by="methodology-blocklist")
    st.reject_cells([("diabetic foot ulcers", "part_of: lower limbs")], by="elk")
    class _Mapper:
        mapping = {"diabetic foot ulcers": "Diabetic Foot Ulcer", "lower limbs": "Lower Limb"}
    st.normalize(_Mapper())
    # the evidence is as written, the view reads the mapped names ...
    assert list(st.dict["1"]["entities"]) == ["diabetic foot ulcers"]
    shown = dict(st.view(include_rejected=True))["1"]
    assert shown == {"Diabetic Foot Ulcer": {"is_a: material entity": 1.0,
                                             "part_of: Lower Limb": 1.0}}
    # ... and the verdicts written against the old name still apply to the new
    assert st.entities == []
    st.terms.gate("diabetic foot ulcers", curator={"verdict": "in", "reason": "a wound"})
    assert dict(st.records())["1"] == {"Diabetic Foot Ulcer": {"is_a: material entity": 1.0}}


def test_summary_is_measured():
    st = _store(_two_abstracts())
    st.reject_entities(["Skin"], by="methodology-blocklist")
    st.reject_cells([("Wound", "has_quality: Chronic")], by="elk")
    s = st.summary()
    # Skin out of scope takes `part_of: Skin` with it: its target is out
    assert s == {"documents": 2, "cells_raw": 6, "cells_standing": 3, "cells_rejected": 3,
                 "rejected_entities": 1, "rejected_cells": 1,
                 "verdicts_by": {"cell:elk": 1, "entity:methodology-blocklist": 1},
                 "renamed": 0}


def test_a_refused_relation_is_found_under_any_spelling_of_its_ends():
    """2026-10-29: the WONT export takes the relations read as true of every
    instance; one the term dict refuses must be found there and held back,
    whatever spelling the reading used for the predicate or the ends."""
    from conftest import J
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    class DM:
        def load_latest_json(self, name):
            return None

        def save_as_json(self, data, name):
            pass

    gt = TermMappingAndGate(DM(), file_name="term_mapping")
    gt.records["Wound"] = {"relations": {"has_quality: Debridement": [J("no", "elk")]}}
    gt.records["debridement"] = {"name": [J("Debridement", "string-normalisation")]}
    gt.records["Debridement"] = {}
    gt._dirty()
    assert gt.relation_judgement("Wound", "has quality", "debridement")["verdict"] == "no"
    assert gt.relation_judgement("Wound", "has_quality", "Granulation tissue") is None
