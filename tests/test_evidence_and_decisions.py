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

from conftest import J, memory_mapping, rule89_file
from wound_ontology.mappers.judgements import current
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
    assert _view(st)["1"] == {"Diabetic foot ulcer": {      # sentence case, rule 81
        "is_a: material entity": 1.0, "has_quality: Necrotizing edge": 1.0}}
    assert st.terms.aliases()["Diabetic Foot Ulcers (DFUs)"]["by"] == "string-normalisation"
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
    terms = memory_mapping(rule89_file({"wounds": {"name": [J("Wound", "sapbert-clustering")]}}))
    st = _store({}, terms)
    st._spell_ingested({"entities": {"wounds": {}}}, set())
    assert not terms.is_alias("wounds")
    assert terms.data == {"wounds": "Wound"}, "the mapping is untouched"


def test_ingestion_records_its_spelling_as_string_normalisation():
    terms = memory_mapping({})
    st = _store({}, terms)
    st._spell_ingested({"entities": {"Diabetic Foot Ulcers": {}}}, set())
    assert terms.aliases()["Diabetic Foot Ulcers"]["by"] == "string-normalisation"


# ── an alias is a spelling and nothing else ──────────────────────────────────

def test_a_rename_leaves_an_alias_even_for_a_string_nobody_decided_about():
    terms = memory_mapping({})
    terms.apply_renames({"Cuts": "cut"}, by="pass0")
    assert terms.aliases()["Cuts"]["to"] == "cut"
    assert terms.resolve("Cuts") == "cut"


def test_a_decision_moves_to_the_new_spelling_and_the_alias_keeps_only_its_name():
    terms = memory_mapping(rule89_file({"Tumours": {
        "scope": [J("in")],
        "relations": {"part_of: Lesions": [J("no", "elk", "a clash")]}}}))
    terms.apply_renames({"Tumours": "Tumor", "Lesions": "Lesion"}, by="pass0")
    moved = terms.records["Tumor"]
    assert current(moved["scope"])["verdict"] == "in"
    assert set(moved["relations"]) == {"part_of: Lesion"}, "the relation's target is respelled too"
    assert set(terms.records["Tumours"]) == {"name"}
    assert terms.resolve("Tumours") == "Tumor"


def test_a_write_to_an_old_spelling_lands_on_the_current_one():
    terms = memory_mapping({})
    terms.spell("Tumours", "Tumor", by="pass0")
    terms.gate("Tumours", curator={"verdict": "out"})
    assert current(terms.records["Tumor"]["scope"])["verdict"] == "out"
    assert set(terms.records["Tumours"]) == {"name"}


def test_spelling_a_string_that_still_holds_decisions_is_refused():
    terms = memory_mapping(rule89_file({"Tumours": {"name": [J("Neoplasm")]}}))
    with pytest.raises(ValueError, match="apply_renames"):
        terms.spell("Tumours", "Tumor", by="pass0")


def test_a_spelling_cycle_is_refused():
    terms = memory_mapping({})
    terms.spell("a", "b", by="pass0")
    with pytest.raises(ValueError, match="cycle"):
        terms.spell("b", "a", by="pass0")


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
    restored spelling, and the reversed spelling stays in its list as history."""
    terms = memory_mapping(rule89_file({"pharmacologic intervention": {
        "scope": [J("in", "deepseek-v4-flash")]}}))
    terms.spell("pharmacological intervention", "pharmacologic intervention", by="pass0")
    terms.spell("pharmacological interventions", "pharmacologic intervention", by="pass0")
    terms.apply_renames({"pharmacologic intervention": "pharmacological intervention"},
                        by="pass0")
    back = terms.records["pharmacological intervention"]
    assert current(back["scope"])["verdict"] == "in"
    assert [j["verdict"] for j in back["name"]] == ["pharmacologic intervention",
                                                     "pharmacological intervention"]
    assert terms.resolve("pharmacologic intervention") == "pharmacological intervention"
    assert terms.resolve("pharmacological interventions") == "pharmacological intervention"
    assert terms.resolve("pharmacological intervention") == "pharmacological intervention"


def test_a_reversed_spelling_with_no_decisions_keeps_its_history():
    terms = memory_mapping({})
    terms.spell("Physiological Response", "physiologic response", by="pass0")
    terms.apply_renames({"physiologic response": "Physiological Response"}, by="pass0")
    assert terms.resolve("physiologic response") == "Physiological Response"
    assert not terms.is_alias("Physiological Response")
    assert terms.records["Physiological Response"]["name"][0]["verdict"] == "physiologic response"


# ── the view ─────────────────────────────────────────────────────────────────

def test_the_view_resolves_spelling_then_mapping_and_can_stop_at_spelling():
    terms = memory_mapping({"ulcer": {"to": "Ulceration", "pairs": {}}})
    st = _store({"1": {"entities": {"Ulcers": {"is_a: material entity": 1.0}}}}, terms)
    terms.spell("Ulcers", "ulcer", by="ingestion")
    assert list(_view(st)["1"]) == ["Ulceration"]
    assert list(_view(st, mapped=False)["1"]) == ["ulcer"]
    assert list(st.dict["1"]["entities"]) == ["Ulcers"]


def test_trace_goes_from_the_view_back_to_what_each_abstract_wrote():
    terms = memory_mapping(rule89_file({"ulcer": {
        "name": [J("Ulceration", "sapbert-clustering", "cosine similarity 0.97")],
        "pairs": {"Ulceration": [J("same_class", "author", "kept")]}}}))
    st = _store({"1": {"entities": {"Ulcers": {}}},
                 "2": {"entities": {"Lesion": {"part_of: ulcer": 1.0}}}}, terms)
    terms.spell("Ulcers", "ulcer", by="ingestion")
    t = st.trace("Ulceration")
    assert t["Ulcers"]["documents"] == ["1"]
    assert [s["from"] for s in t["Ulcers"]["spelling"]] == ["Ulcers"]
    assert t["Ulcers"]["mapped_by"]["by"] == "sapbert-clustering"
    assert [j["verdict"] for j in t["Ulcers"]["mapped_by"]["pair"]] == ["same_class"]
    assert t["ulcer"]["documents"] == ["2"]


def test_a_rename_is_one_line_in_the_term_dict_not_an_edit_of_the_abstracts():
    data = {str(i): {"entities": {"Tumours": {"is_a: material entity": 1.0}}}
            for i in range(50)}
    st = _store(data)
    before = repr(st.dict)
    st.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert repr(st.dict) == before
    assert {e for _, ents in st.records() for e in ents} == {"Tumor"}


def test_a_merge_keeps_the_judgements_of_whichever_spelling_carried_them():
    """`Tumours` is merged first and carries nothing; `tumour`'s judgements must
    survive being absorbed into it, or an out-of-scope term comes back."""
    terms = memory_mapping(rule89_file({
        "Tumours": {"pairs": {}},
        "tumour": {"scope": [J("out", "methodology-blocklist")],
                   "is_a": {"Lesion": [J("no", "elk", "a clash")]}}}))
    terms.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert current(terms.records["Tumor"]["scope"])["by"] == "methodology-blocklist"
    assert current(terms.records["Tumor"]["is_a"]["Lesion"])["by"] == "elk"


def test_a_rename_with_nothing_to_do_reports_in_the_usual_shape():
    """Pass 0 on a settled store printed `report['keys renamed']` and crashed:
    the empty case returned a three-key dict (2026-09-28)."""
    st = _store({"1": {"entities": {"Wound": {"is_a: material entity": 1.0}}}})
    report = st.apply_renames({}, by="pass0")
    assert report["keys renamed"] == 0 and report["renamed"] == 0


def test_a_merge_keeps_the_abstentions_of_both_spellings():
    terms = memory_mapping(rule89_file({
        "Offloadings": {"scope": [J("undecided", "neighbour-check", "withdrawn", "2026-09-28T16:08:06")]},
        "offloading": {"scope": [J("undecided", "neighbour-check", "withdrawn", "2026-09-28T16:08:07")]}}))
    terms.apply_renames({"Offloadings": "offloading"}, by="pass0")
    assert [j["verdict"] for j in terms.records["offloading"]["scope"]] == ["undecided", "undecided"]
    assert terms.gate_verdict("offloading") == ("", ""), "an abstention never counts"
