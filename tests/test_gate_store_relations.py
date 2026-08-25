# -*- coding: utf-8 -*-
"""The store -> reasoner-gate adapter.

The gate itself is tested in test_reasoner_gate.py. What is tested here is the
translation into it, because that is where a silent failure would hide: every
term the adapter cannot type is a term the reasoner never sees, and an adapter
that quietly returned fewer entities would make the gate report "clean" on a
store it had barely inspected.
"""
from __future__ import annotations

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
    for phrase in ("no BFO category", "conflicting categories",
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
