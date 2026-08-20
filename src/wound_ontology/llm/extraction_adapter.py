# -*- coding: utf-8 -*-
"""Bridge schema-constrained extraction into the existing ConceptStore shape.

The store, the FCA matrix and the hierarchies all speak one dialect:

    {entity_label: {"<predicate>: <target>": 1.0 | 0.0}}

`BaseHierarchy.get_data` normalises the predicate with
``pred.strip().lower().replace(" ", "_")``, so an ontology property label such as
"part of" arrives as ``part_of`` and "has quality" as ``has_quality`` — the names
the hierarchies already consume. Nothing downstream has to change.

Two things this adapter does that the old free-text path could not:

1. **Subsumption is deterministic.** Every term gets ``is_a: <BFO category>`` from
   its stage-1 typing rather than from the model guessing a parent. A newly
   discovered term is therefore never unparented — it enters the hierarchy under
   a real BFO class and curation only moves it further down.
2. **Nothing unlicensed survives.** Relations were already filtered by
   ``ExtractionResult`` against the category pairs MILD/WONT actually license.
"""
from __future__ import annotations

from wound_ontology.llm.extraction_models import (
    CATEGORY_IRI,
    COARSE_CATEGORIES,
    ExtractionResult,
)


def normalize_predicate(label: str) -> str:
    """Ontology property label -> store predicate key ("part of" -> "part_of")."""
    return label.strip().lower().replace(" ", "_")


def result_to_store_entities(
    result: ExtractionResult,
    *,
    emit_category_is_a: bool = True,
) -> dict[str, dict[str, float]]:
    """Convert an ExtractionResult into the store's {entity: {triple: value}} shape."""
    entities: dict[str, dict[str, float]] = {}

    for e in result.entities:
        attrs = entities.setdefault(e.label, {})
        if emit_category_is_a:
            # Deterministic BFO subsumption — not an LLM guess.
            attrs[f"is_a: {e.category.value}"] = 1.0

    for r in result.relations:
        attrs = entities.setdefault(r.subject, {})
        attrs[f"{normalize_predicate(r.predicate.value)}: {r.object}"] = 1.0

    return entities


def grounding_map(result: ExtractionResult) -> dict[str, str]:
    """Labels that matched an existing MILD/WONT class, mapped to its IRI."""
    return {e.label: e.grounded_to for e in result.entities if e.grounded_to}


def new_terms(result: ExtractionResult) -> list[tuple[str, str, str]]:
    """(label, category, BFO IRI) for terms not already in MILD/WONT."""
    return [
        (e.label, e.category.value, e.bfo_iri)
        for e in result.entities
        if e.grounded_to is None
    ]


def needs_refinement(result: ExtractionResult) -> list[tuple[str, str]]:
    """(label, category) for terms typed at a coarse BFO node.

    These are correct answers, not errors: the model retreated up the tree rather
    than guessing. They are surfaced so a human can sharpen them.
    """
    return [
        (e.label, e.category.value)
        for e in result.entities
        if e.category.value in COARSE_CATEGORIES
    ]


def subsumption_axioms(result: ExtractionResult) -> list[tuple[str, str, str]]:
    """(subject, rdfs:subClassOf, BFO IRI) for every extracted term."""
    return [e.subsumption_axiom() for e in result.entities]


def summarize(result: ExtractionResult, report: dict | None = None) -> str:
    """One-paragraph account of what the schema accepted and refused."""
    grounded = len(grounding_map(result))
    fresh = len(new_terms(result))
    coarse = len(needs_refinement(result))
    lines = [
        f"terms: {len(result.entities)} "
        f"({grounded} grounded to MILD/WONT, {fresh} new, {coarse} coarse)",
        f"relations kept: {len(result.relations)}",
    ]
    if report:
        if report.get("rejected_terms"):
            lines.append(f"terms rejected: {len(report['rejected_terms'])}")
        if report.get("rejected_relations"):
            lines.append(
                f"relations rejected by licensing: {len(report['rejected_relations'])}"
            )
        if report.get("unknown_predicates"):
            lines.append(
                f"unknown predicates dropped: {len(report['unknown_predicates'])}"
            )
    return "; ".join(lines)
