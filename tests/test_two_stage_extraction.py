"""End-to-end test of the schema-constrained extraction path.

Uses a stub LLM so no network is needed. The point is to prove that a model
behaving badly — inventing a category, hallucinating an IRI, asserting a
relation across a category boundary MILD/WONT reject — cannot get that content
into the store.
"""
import asyncio

import pytest

from wound_ontology.llm.extraction_models import ExtractionResult
from wound_ontology.llm import extraction_adapter as ad
from wound_ontology.llm.schemas import (
    RelationCandidate,
    RelationResponse,
    TypedTerm,
    TypingResponse,
)
from wound_ontology.llm.llm_client import LLMClient


class StubLLM(LLMClient):
    """LLMClient with the network call replaced by canned responses."""

    def __init__(self, typing, relations):
        self._typing = typing
        self._relations = relations
        self.abort_event = None
        self._consec_errors = 0
        self._max_consec_errors = 0

    async def _call_json(self, prompt, schema, temperature=0.0, timeout=240):
        if schema is TypingResponse:
            return self._typing
        if schema is RelationResponse:
            return self._relations
        raise AssertionError(f"unexpected schema {schema}")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def misbehaving_llm():
    return StubLLM(
        typing=TypingResponse(terms=[
            TypedTerm(label="Wound", category="material entity"),
            TypedTerm(label="Wound development process", category="process"),
            TypedTerm(label="reddened", category="quality"),
            TypedTerm(label="Novel Foam Dressing", category="material entity"),
            TypedTerm(label="Something Unclear", category="continuant"),
            TypedTerm(label="Study Design", category="Symptom"),        # invented category
        ]),
        relations=RelationResponse(relations=[
            RelationCandidate(subject="Wound", predicate="has quality", object="reddened"),
            RelationCandidate(subject="Wound", predicate="output of",
                              object="Wound development process"),
            RelationCandidate(subject="reddened", predicate="has part",
                              object="Wound"),                          # unlicensed pair
            RelationCandidate(subject="Wound", predicate="affects",
                              object="reddened"),                       # invented predicate
        ]),
    )


def test_invented_category_is_rejected_not_stored(misbehaving_llm):
    result, report = _run(misbehaving_llm.extract_two_stage("text"))
    labels = {e.label for e in result.entities}
    assert "Study Design" not in labels
    assert ("Study Design", "Symptom", "not a BFO/MILD category") in report["rejected_terms"]


def test_invented_predicate_is_dropped(misbehaving_llm):
    _, report = _run(misbehaving_llm.extract_two_stage("text"))
    assert ("Wound", "affects", "reddened") in report["unknown_predicates"]


def test_unlicensed_relation_is_dropped_with_a_reason(misbehaving_llm):
    result, report = _run(misbehaving_llm.extract_two_stage("text"))
    kept = {(r.subject, r.predicate.value, r.object) for r in result.relations}
    assert ("reddened", "has part", "Wound") not in kept
    assert any(r[:3] == ("reddened", "has part", "Wound")
               for r in report["rejected_relations"])


def test_licensed_relations_survive(misbehaving_llm):
    result, _ = _run(misbehaving_llm.extract_two_stage("text"))
    kept = {(r.subject, r.predicate.value, r.object) for r in result.relations}
    assert ("Wound", "has quality", "reddened") in kept
    assert ("Wound", "output of", "Wound development process") in kept


def test_grounding_is_lookup_not_generation(misbehaving_llm):
    """The model never emits an IRI; grounding comes from MILD/WONT."""
    result, _ = _run(misbehaving_llm.extract_two_stage("text"))
    grounded = ad.grounding_map(result)
    assert grounded["Wound"].endswith("WONT_0000380")
    assert all(v.startswith("https://bioportal") or v.startswith("http://purl")
               for v in grounded.values())


def test_new_terms_survive_and_are_bfo_subsumed(misbehaving_llm):
    result, _ = _run(misbehaving_llm.extract_two_stage("text"))
    fresh = dict((lab, iri) for lab, _c, iri in ad.new_terms(result))
    assert fresh["Novel Foam Dressing"] == "http://purl.obolibrary.org/obo/BFO_0000040"
    assert fresh["Something Unclear"] == "http://purl.obolibrary.org/obo/BFO_0000002"


def test_coarse_terms_are_flagged_for_refinement(misbehaving_llm):
    result, _ = _run(misbehaving_llm.extract_two_stage("text"))
    assert ("Something Unclear", "continuant") in ad.needs_refinement(result)


def test_every_stored_entity_carries_an_is_a_edge(misbehaving_llm):
    """No extracted term enters the store unparented."""
    result, _ = _run(misbehaving_llm.extract_two_stage("text"))
    store_shape = ad.result_to_store_entities(result)
    for label, attrs in store_shape.items():
        assert any(k.startswith("is_a: ") for k in attrs), label


def test_predicates_normalize_to_hierarchy_keys():
    assert ad.normalize_predicate("part of") == "part_of"
    assert ad.normalize_predicate("has quality") == "has_quality"


def test_empty_typing_short_circuits():
    llm = StubLLM(TypingResponse(terms=[]), RelationResponse(relations=[]))
    result, report = _run(llm.extract_two_stage("text"))
    assert result.entities == [] and result.relations == []
    assert report["rejected_relations"] == []


def test_single_term_skips_the_relation_call():
    """With fewer than two terms there is no pair to relate; do not call the model."""
    class Boom(StubLLM):
        async def _call_json(self, prompt, schema, temperature=0.0, timeout=240):
            if schema is RelationResponse:
                raise AssertionError("relation stage should not run")
            return self._typing

    llm = Boom(TypingResponse(terms=[TypedTerm(label="Wound", category="material entity")]),
               RelationResponse(relations=[]))
    result, _ = _run(llm.extract_two_stage("text"))
    assert len(result.entities) == 1
