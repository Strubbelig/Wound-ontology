# -*- coding: utf-8 -*-
"""The store -> reasoner-gate adapter.

The gate itself is tested in test_reasoner_gate.py. What is tested here is the
translation into it, because that is where a silent failure would hide: every
term the adapter cannot type is a term the reasoner never sees, and an adapter
that quietly returned fewer entities would make the gate report "clean" on a
store it had barely inspected.
"""
from __future__ import annotations

import pathlib

import pytest

from wound_ontology.llm.extraction_adapter import (
    describe_gate_inputs,
    store_to_gate_inputs,
)


def _doc(entities: dict, stamp: str = "s") -> dict:
    return {"entities": entities, "meta_stamp": stamp}


# ── shape ─────────────────────────────────────────────────────────────────────
def test_reads_the_document_keyed_shape_not_a_flat_dict():
    """The store is {pmid: {entities: {...}}}. Reading the top level as terms
    yields zero typed terms and a report blaming the abstracts, which is how
    this was caught the first time."""
    store = {"111": _doc({"Wound": {"is_a: MaterialEntity": 1.0}})}
    entities, _, report = store_to_gate_inputs(store)
    assert [e.label for e in entities] == ["Wound"]
    assert report["untyped"] == []


def test_zero_valued_cells_are_not_assertions():
    store = {"111": _doc({"Wound": {"is_a: MaterialEntity": 1.0,
                                    "part_of: Skin": 0.0},
                          "Skin": {"is_a: MaterialEntity": 1.0}})}
    _, relations, _ = store_to_gate_inputs(store)
    assert relations == []


# ── typing ────────────────────────────────────────────────────────────────────
def test_a_term_typed_differently_by_two_abstracts_is_reported_not_resolved():
    """Last-writer-wins would silently pick one. The disagreement IS the finding."""
    store = {
        "1": _doc({"Wound": {"is_a: MaterialEntity": 1.0}}),
        "2": _doc({"Wound": {"is_a: Quality": 1.0}}),
    }
    entities, _, report = store_to_gate_inputs(store)
    assert entities == []
    assert report["conflicting"] == {"Wound": ["MaterialEntity", "Quality"]}


def test_the_same_typing_from_many_abstracts_is_agreement_not_conflict():
    store = {str(i): _doc({"Wound": {"is_a: MaterialEntity": 1.0}}) for i in range(5)}
    entities, _, report = store_to_gate_inputs(store)
    assert [e.label for e in entities] == ["Wound"]
    assert report["conflicting"] == {}


def test_a_non_bfo_is_a_target_is_not_a_typing():
    """`is_a: Skin Lesion` is a subsumption edge for the other gate, not a
    stage-1 category. Treating it as one would type the term to nonsense."""
    store = {"1": _doc({"Wound": {"is_a: Skin Lesion": 1.0}})}
    entities, _, report = store_to_gate_inputs(store)
    assert entities == []
    assert report["untyped"] == ["Wound"]


def test_untyped_terms_are_counted_not_dropped():
    store = {"1": _doc({"Legacy Term": {"occurs_in: Somewhere": 1.0}})}
    _, relations, report = store_to_gate_inputs(store)
    assert report["untyped"] == ["Legacy Term"]
    assert relations == []


# ── relations ─────────────────────────────────────────────────────────────────
def test_a_relation_needs_both_endpoints_typed():
    store = {"1": _doc({"Wound": {"is_a: MaterialEntity": 1.0,
                                  "part_of: Skin": 1.0}})}
    _, relations, report = store_to_gate_inputs(store)
    assert relations == []
    assert report["untyped_object"] == {"Skin": 1}


def test_a_predicate_with_no_relationtype_is_counted_per_predicate():
    """`occurs_in` and `is_treatment_for` are legacy-only: no RelationType emits
    them, so they cannot become an OWL restriction and must be reported."""
    store = {"1": _doc({"A": {"is_a: Process": 1.0, "occurs_in: B": 1.0},
                        "B": {"is_a: MaterialEntity": 1.0}})}
    _, relations, report = store_to_gate_inputs(store)
    assert relations == []
    assert report["unknown_predicate"] == {"occurs_in": 1}


def test_is_a_never_becomes_a_relation():
    """Subsumption belongs to run_gate_hierarchy_edges. Emitting it here too
    would gate the same edge twice and double every quarantine count."""
    store = {"1": _doc({"Wound": {"is_a: MaterialEntity": 1.0},
                        "Skin": {"is_a: MaterialEntity": 1.0}})}
    _, relations, _ = store_to_gate_inputs(store)
    assert relations == []


def test_the_same_triple_from_many_abstracts_is_one_relation():
    store = {str(i): _doc({"Wound": {"is_a: MaterialEntity": 1.0,
                                     "part_of: Skin": 1.0},
                           "Skin": {"is_a: MaterialEntity": 1.0}})
             for i in range(7)}
    _, relations, _ = store_to_gate_inputs(store)
    assert len(relations) == 1
    assert (relations[0].subject, relations[0].predicate.value,
            relations[0].object) == ("Wound", "part of", "Skin")


def test_store_predicate_keys_map_back_to_relation_types():
    """result_to_store_entities writes "part_of"; this must read it back."""
    store = {"1": _doc({"Wound": {"is_a: MaterialEntity": 1.0,
                                  "has_quality: Chronicity": 1.0},
                        "Chronicity": {"is_a: Quality": 1.0}})}
    _, relations, report = store_to_gate_inputs(store)
    assert report["unknown_predicate"] == {}
    assert [r.predicate.value for r in relations] == ["has quality"]


def test_the_round_trip_from_extraction_survives_the_store():
    """Whatever result_to_store_entities writes, this must be able to read."""
    from wound_ontology.llm.extraction_adapter import result_to_store_entities
    from wound_ontology.llm.extraction_models import (
        ExtractedEntity, ExtractedRelation, ExtractionResult, RelationType,
    )
    result = ExtractionResult(
        entities=[ExtractedEntity(label="Wound Healing", category="Process"),
                  ExtractedEntity(label="Granulation Tissue",
                                  category="MaterialEntity")],
        relations=[ExtractedRelation(subject="Wound Healing",
                                     predicate=RelationType.HAS_PARTICIPANT,
                                     object="Granulation Tissue")],
    )
    flat = result_to_store_entities(result)
    entities, relations, report = store_to_gate_inputs({"1": _doc(flat)})
    assert sorted(e.label for e in entities) == ["Granulation Tissue", "Wound Healing"]
    assert report["untyped"] == [] and report["conflicting"] == {}
    assert report["unknown_predicate"] == {} and report["untyped_object"] == {}
    assert len(relations) == len(result.relations)


# ── licensing ─────────────────────────────────────────────────────────────────
def test_unlicensed_relations_are_reported_but_still_gated():
    """The reasoner is the authority; the table is a second opinion. A relation
    the table refuses is still handed to ELK, and the disagreement is printed."""
    store = {"1": _doc({"Anti-Inflammatory Function": {"is_a: Function": 1.0,
                                                       "part_of: Wound Repair": 1.0},
                        "Wound Repair": {"is_a: Process": 1.0}})}
    _, relations, report = store_to_gate_inputs(store)
    assert len(relations) == 1
    assert report["unlicensed"] == [
        ("Anti-Inflammatory Function", "part of", "Wound Repair")]


# ── reporting ─────────────────────────────────────────────────────────────────
def test_every_count_is_printed_even_when_zero():
    """Absence of a message must never mean absence of a problem."""
    entities, relations, report = store_to_gate_inputs(
        {"1": _doc({"Wound": {"is_a: MaterialEntity": 1.0}})})
    text = describe_gate_inputs(entities, relations, report)
    for phrase in ("no BFO category", "irreconcilable categories", "reconciled",
                   "no RelationType", "not a typed term", "licensing violations"):
        assert phrase in text
    assert "0 term(s)" in text or "0 edge(s)" in text


def test_nothing_gateable_is_distinguishable_from_nothing_wrong():
    """A store the adapter cannot read yields 0 relations AND a loud report --
    never 0 relations and an empty report, which would read as success."""
    store = {"1": _doc({"Legacy": {"occurs_in: Somewhere": 1.0}})}
    entities, relations, report = store_to_gate_inputs(store)
    assert not relations
    assert report["untyped"] or report["unknown_predicate"]


# ── corpus accounting ─────────────────────────────────────────────────────────
def test_pubmed_row_count_is_not_reported_as_an_abstract_count(capsys):
    """The connector dedupes whole ROWS, not PMIDs: one paper matched by two
    queries stays as two rows. It used to print that row count as "unique
    abstracts", which overstated a 606-abstract corpus as 860."""
    import pandas as pd
    from wound_ontology.connectors.pubmed_connector import PubmedConnector

    db = pd.DataFrame([
        {"pmid": 1, "query": "a", "abstract": "x"},
        {"pmid": 1, "query": "b", "abstract": "x"},
        {"pmid": 2, "query": "a", "abstract": "y"},
    ])
    con = PubmedConnector.__new__(PubmedConnector)
    con._database = db
    rows = len(con.database)
    uniq = con.database["pmid"].nunique()
    assert (rows, uniq) == (3, 2), "fixture no longer exercises the duplication"

    # Resolve from the module object, not from a path relative to the cwd:
    # pytest is run from the workspace root as often as from this directory.
    import inspect
    text = pathlib.Path(inspect.getfile(PubmedConnector)).read_text(encoding="utf-8")
    assert "Total unique abstracts in database" not in text, (
        "the row count is being reported as an abstract count again")
    assert "unique abstracts" in text and "nunique()" in text, (
        "get_data must report rows AND unique PMIDs")



def test_orchestrator_default_predicates_are_the_configured_ones():
    """StoreCleaner DELETES any attribute whose predicate is not on this list.

    The orchestrator used to define its own five-entry literal, so the 29-entry
    config.settings.ALLOWED_PREDICATES was never consulted and 19 of the 26
    relation types the extractor emits were deleted from every store. Any
    divergence between the two lists is that bug returning.
    """
    from config.settings import ALLOWED_PREDICATES
    from wound_ontology.orchestrator import _DEFAULT_ALLOWED_PREDICATES
    assert list(_DEFAULT_ALLOWED_PREDICATES) == list(ALLOWED_PREDICATES)


def test_every_emitted_relation_survives_the_cleaner():
    """End to end: what the extractor emits must reach the store intact."""
    from config.settings import ALLOWED_PREDICATES
    from wound_ontology.llm.extraction_adapter import normalize_predicate
    from wound_ontology.llm.extraction_models import RELATION_IRI
    emitted = {normalize_predicate(label) for label in RELATION_IRI}
    stripped = sorted(emitted - set(ALLOWED_PREDICATES))
    assert stripped == [], f"the cleaner would delete these on sight: {stripped}"


# ── category reconciliation ───────────────────────────────────────────────────
def test_a_conflict_retreats_to_the_common_ancestor_when_a_resolver_is_given():
    """Two abstracts calling a term Process and ProcessBoundary agree it is an
    Occurrent. Gating it there asserts only what both actually support."""
    store = {"1": _doc({"closure": {"is_a: Process": 1.0}}),
             "2": _doc({"closure": {"is_a: ProcessBoundary": 1.0}})}
    entities, _, report = store_to_gate_inputs(
        store, resolve_conflict=lambda cats: "Occurrent")
    assert [(e.label, e.category.value) for e in entities] == [("closure", "Occurrent")]
    assert report["conflicting"] == {}
    assert report["reconciled"] == {
        "closure": (["Process", "ProcessBoundary"], "Occurrent")}


def test_an_irreconcilable_conflict_is_still_excluded():
    """A resolver returning None means there is no honest category. The term
    must stay out of the gate rather than be forced to something nobody said."""
    store = {"1": _doc({"complications": {"is_a: MaterialEntity": 1.0}}),
             "2": _doc({"complications": {"is_a: Process": 1.0}})}
    entities, _, report = store_to_gate_inputs(
        store, resolve_conflict=lambda cats: None)
    assert entities == []
    assert report["conflicting"] == {"complications": ["MaterialEntity", "Process"]}
    assert report["reconciled"] == {}


def test_without_a_resolver_nothing_is_reconciled():
    """The default must not silently start rewriting categories."""
    store = {"1": _doc({"x": {"is_a: Process": 1.0}}),
             "2": _doc({"x": {"is_a: ProcessBoundary": 1.0}})}
    _, _, report = store_to_gate_inputs(store)
    assert report["reconciled"] == {}
    assert report["conflicting"] == {"x": ["Process", "ProcessBoundary"]}


# ── batch IRIs ────────────────────────────────────────────────────────────────
def test_labels_differing_only_in_punctuation_get_distinct_batch_iris():
    """'wound care practice' and 'wound-care practice' both reduced to
    `wound_care_practice`. The merged class inherited BOTH category parents --
    material entity and process -- and ELK reported a contradiction the gate had
    manufactured itself. Merging surface forms is the term mapper's job."""
    from wound_ontology.reasoning.gate import _slug
    assert _slug("wound care practice") != _slug("wound-care practice")
    assert _slug("Wound Care") != _slug("wound care")
    assert _slug("x") == _slug("x")                      # deterministic
    assert _slug("wound care practice").startswith("wound_care_practice_")


def test_the_reasoner_gate_resolver_agrees_with_mild():
    """The retreat target is read from the skeleton TBox, not hardcoded here."""
    import shutil
    from config.settings import REASONER_SKELETON
    from wound_ontology.reasoning.gate import ReasonerGate
    if not pathlib.Path(REASONER_SKELETON).exists():
        pytest.skip("skeleton TBox not built")
    g = ReasonerGate(REASONER_SKELETON)
    assert g.least_common_category(["Process", "ProcessBoundary"]) == "Occurrent"
    assert g.least_common_category(["Disposition", "Role"]) == "RealizableEntity"
    assert g.least_common_category(["MaterialEntity", "Process"]) is None
    assert g.least_common_category(["Quality"]) == "Quality"

