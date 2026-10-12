"""The concept store is evidence; every decision about a term is in the term dict (rule 51).

Until 2026-09-27 the store was rewritten in place -- pass 0, the mapping apply
and the sense split each overwrote the abstracts' names -- and kept its own
`decisions` record beside the PMIDs. Two files decided things about terms, and
what an abstract actually said had to be carried through every rename by a
provenance book. Now the store keeps what each abstract said, the term dict
keeps every decision, and the store's view resolves one through the other.
"""
import asyncio

import pytest

from conftest import memory_mapping
from wound_ontology.store.concept_store import ConceptStore


class _DM:
    def __init__(self, data=None): self.json = data
    def load_latest_json(self, _): return self.json
    def save_as_json(self, d, _): self.json = d


def _store(data, terms=None):
    return ConceptStore(_DM(data), "concept_store", terms=terms)


def _view(st, **kw):
    return dict(st.view(**kw))


# ── ingestion keeps the string ───────────────────────────────────────────────

def test_ingestion_stores_the_literal_string_and_records_its_spelling(monkeypatch):
    from wound_ontology.llm import extraction_adapter
    from wound_ontology.store import concept_store as cs

    monkeypatch.setattr(extraction_adapter, "result_to_store_entities", lambda r: {
        "Diabetic Foot Ulcers (DFUs)": {"is_a: material entity": 1.0,
                                        "has_quality: Necrotising Edges": 1.0}})

    class _LLM:
        async def extract_two_stage(self, text):
            return object(), {}

    payload = asyncio.run(cs._extract_schema_constrained(_LLM(), "text", "m1"))
    assert payload["entities"] == {"Diabetic Foot Ulcers (DFUs)": {
        "is_a: material entity": 1.0, "has_quality: Necrotising Edges": 1.0}}
    st = _store({"1": payload})
    st._spell_ingested(payload, set())
    assert _view(st)["1"] == {"Diabetic Foot Ulcer": {
        "is_a: material entity": 1.0, "has_quality: Necrotizing Edge": 1.0}}
    assert st.terms.aliases()["Diabetic Foot Ulcers (DFUs)"]["by"] == "ingestion"
    assert st.dict["1"] == payload, "the evidence is as written"


def test_ingestion_never_respells_a_name_the_store_already_holds():
    """`vitamins` is an ontology label pass 0 left alone (rule 41.5). An alias
    written because a new abstract mentioned it would re-spell it in EVERY
    abstract, not just the new one."""
    st = _store({"1": {"entities": {"vitamins": {"is_a: material entity": 1.0}}}})
    settled = {"vitamins"}
    st._spell_ingested({"entities": {"vitamins": {}}}, settled)
    assert st.terms.aliases() == {}


def test_ingestion_never_respells_a_string_that_carries_a_decision():
    terms = memory_mapping({"wounds": {"to": "Wound", "pairs": {}}})
    st = _store({}, terms)
    st._spell_ingested({"entities": {"wounds": {}}}, set())
    assert not terms.is_alias("wounds")


# ── an alias is a spelling and nothing else ──────────────────────────────────

def test_a_rename_leaves_an_alias_even_for_a_string_nobody_decided_about():
    terms = memory_mapping({})
    terms.apply_renames({"Cuts": "cut"}, by="pass0")
    assert terms.aliases()["Cuts"]["to"] == "cut"
    assert terms.resolve("Cuts") == "cut"


def test_a_decision_moves_to_the_new_spelling_and_the_alias_stays_bare():
    terms = memory_mapping({"Tumours": {
        "to": None, "pairs": {},
        "gate": {"curator": {"verdict": "in"}},
        "rejected": {"status": "rejected", "by": "blocklist"},
        "relations": {"is_a: Lesions": {"status": "rejected", "by": "gate"}}}})
    terms.apply_renames({"Tumours": "Tumor", "Lesions": "Lesion"}, by="pass0")
    moved = terms.records["Tumor"]
    assert moved["gate"] == {"curator": {"verdict": "in"}}
    assert moved["rejected"]["by"] == "blocklist"
    assert set(moved["relations"]) == {"is_a: Lesion"}, "the relation's target is respelled too"
    assert set(terms.records["Tumours"]) == {"spelling"}


def test_a_write_to_an_old_spelling_lands_on_the_current_one():
    terms = memory_mapping({})
    terms.spell("Tumours", "Tumor", by="pass0")
    terms.gate("Tumours", curator={"verdict": "out"})
    assert terms.peek_gate("Tumor") == {"curator": {"verdict": "out"}}
    assert set(terms.records["Tumours"]) == {"spelling"}


def test_spelling_a_string_that_still_holds_decisions_is_refused():
    terms = memory_mapping({"Tumours": {"to": "Neoplasm", "pairs": {}}})
    with pytest.raises(ValueError, match="apply_renames"):
        terms.spell("Tumours", "Tumor", by="pass0")


def test_a_spelling_cycle_is_refused():
    terms = memory_mapping({})
    terms.spell("a", "b", by="x")
    with pytest.raises(ValueError, match="cycle"):
        terms.spell("b", "a", by="x")


def test_an_alias_is_not_a_term_to_any_view():
    terms = memory_mapping({"Tumor": {"to": "Neoplasm", "pairs": {}}})
    terms.spell("Tumours", "Tumor", by="pass0")
    assert terms.data == {"Tumor": "Neoplasm"}
    assert terms.gated("out") == {} and terms.gated("in") == {}


def test_an_alias_follows_when_its_target_is_renamed_again():
    terms = memory_mapping({})
    terms.spell("Wounds", "Wound", by="ingestion")
    terms.apply_renames({"Wound": "wound"}, by="pass0")
    assert terms.resolve("Wounds") == "wound"



def test_a_spelling_decision_can_be_reversed():
    """The curator, 2026-09-28: -ical, not -ic. Pass 0 had written
    `pharmacological intervention -> pharmacologic intervention`, so reversing
    it renames the current spelling back onto its own alias. The alias gives
    way instead of the rename refusing as a clash, the decisions move to the
    restored spelling, and the reversed spelling is kept as history."""
    terms = memory_mapping({"pharmacologic intervention": {
        "to": None, "pairs": {}, "gate": {"pass2": {"verdict": "in"}}}})
    terms.spell("pharmacological intervention", "pharmacologic intervention", by="pass0")
    terms.spell("pharmacological interventions", "pharmacologic intervention", by="pass0")
    terms.apply_renames({"pharmacologic intervention": "pharmacological intervention"},
                        by="pass0")
    back = terms.records["pharmacological intervention"]
    assert back["gate"] == {"pass2": {"verdict": "in"}}
    assert back["spelling_reversed"][0]["to"] == "pharmacologic intervention"
    assert terms.resolve("pharmacologic intervention") == "pharmacological intervention"
    assert terms.resolve("pharmacological interventions") == "pharmacological intervention"
    assert terms.resolve("pharmacological intervention") == "pharmacological intervention"


def test_a_reversed_spelling_with_no_decisions_leaves_no_empty_record():
    terms = memory_mapping({})
    terms.spell("Physiological Response", "physiologic response", by="pass0")
    terms.apply_renames({"physiologic response": "Physiological Response"}, by="pass0")
    assert terms.resolve("physiologic response") == "Physiological Response"
    assert not terms.is_alias("Physiological Response")
    assert terms.records["Physiological Response"]["spelling_reversed"][0]["by"] == "pass0"


# ── the view ─────────────────────────────────────────────────────────────────

def test_the_view_resolves_spelling_then_mapping_and_can_stop_at_spelling():
    terms = memory_mapping({"ulcer": {"to": "Ulceration", "pairs": {}}})
    st = _store({"1": {"entities": {"Ulcers": {"is_a: material entity": 1.0}}}}, terms)
    terms.spell("Ulcers", "ulcer", by="ingestion")
    assert list(_view(st)["1"]) == ["Ulceration"]
    assert list(_view(st, mapped=False)["1"]) == ["ulcer"]
    assert list(st.dict["1"]["entities"]) == ["Ulcers"]


def test_trace_goes_from_the_view_back_to_what_each_abstract_wrote():
    terms = memory_mapping({"ulcer": {"to": "Ulceration", "method": "sapbert_cluster",
                                      "pairs": {"Ulceration": {"curator": {"verdict": "kept"}}}}})
    st = _store({"1": {"entities": {"Ulcers": {}}},
                 "2": {"entities": {"Lesion": {"part_of: ulcer": 1.0}}}}, terms)
    terms.spell("Ulcers", "ulcer", by="ingestion")
    t = st.trace("Ulceration")
    assert t["Ulcers"]["documents"] == ["1"]
    assert [s["from"] for s in t["Ulcers"]["spelling"]] == ["Ulcers"]
    assert t["Ulcers"]["mapped_by"]["method"] == "sapbert_cluster"
    assert t["Ulcers"]["mapped_by"]["pair"] == {"curator": {"verdict": "kept"}}
    assert t["ulcer"]["documents"] == ["2"]


def test_a_rename_is_one_line_in_the_term_dict_not_an_edit_of_the_abstracts():
    data = {str(i): {"entities": {"Tumours": {"is_a: material entity": 1.0}}}
            for i in range(50)}
    st = _store(data)
    before = repr(st.dict)
    st.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert repr(st.dict) == before
    assert {e for _, ents in st.records() for e in ents} == {"Tumor"}


def test_a_merge_keeps_the_rejection_of_whichever_spelling_carried_it():
    """`Tumours` is merged first and carries nothing; `tumour`'s rejection must
    survive being absorbed into it, or a blocklisted term comes back."""
    terms = memory_mapping({
        "Tumours": {"to": None, "pairs": {}},
        "tumour": {"to": None, "pairs": {},
                   "rejected": {"status": "rejected", "by": "blocklist"},
                   "relations": {"is_a: Lesion": {"status": "rejected", "by": "gate"}}}})
    terms.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert terms.records["Tumor"]["rejected"]["by"] == "blocklist"
    assert terms.records["Tumor"]["relations"]["is_a: Lesion"]["by"] == "gate"


def test_a_rename_with_nothing_to_do_reports_in_the_usual_shape():
    """Pass 0 on a settled store printed `report['keys renamed']` and crashed:
    the empty case returned a three-key dict (2026-09-28)."""
    st = _store({"1": {"entities": {"Wound": {"is_a: material entity": 1.0}}}})
    report = st.apply_renames({}, by="pass0")
    assert report["keys renamed"] == 0 and report["renamed"] == 0


def test_a_merge_keeps_withdrawn_scope_verdicts_of_both_spellings():
    terms = memory_mapping({
        "Offloadings": {"to": None, "pairs": {},
                        "gate_withdrawn": [{"source": "pass1", "verdict": "out"}]},
        "offloading": {"to": None, "pairs": {},
                       "gate_withdrawn": [{"source": "pass1", "verdict": "in"}]}})
    terms.apply_renames({"Offloadings": "offloading"}, by="pass0")
    assert sorted(w["verdict"] for w in terms.records["offloading"]["gate_withdrawn"]) == ["in", "out"]
