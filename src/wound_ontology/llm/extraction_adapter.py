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
    BFOCategory,
    ExtractionResult,
    RelationType,
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


# ── the reverse direction: store -> gate inputs ───────────────────────────────
#
# `result_to_store_entities` above flattens typed objects into the store's
# "<pred>: <target>" strings. The reasoner gate needs them back: `ReasonerGate
# .check` wants ExtractedEntity/ExtractedRelation, because it has to know each
# term's BFO category to anchor it in the skeleton TBox.
#
# The round trip is lossy in one direction only. A term's category survives as
# its `is_a: <BFOCategory>` attribute, so typing is recoverable. What is NOT
# recoverable is a term that never carried one -- a legacy free-text entity, or
# a bare relation target that was never itself extracted as an entity. Those
# cannot be gated at all, and the gate would otherwise skip them in silence
# (`build_batch_graph` drops any relation whose endpoint it cannot resolve).
# So every exclusion is counted and returned in `report` rather than dropped.

_CATEGORY_VALUES = frozenset(c.value for c in BFOCategory)


def _predicate_lookup() -> dict[str, "RelationType"]:
    """Store predicate key -> RelationType ("part_of" -> RelationType.PART_OF)."""
    return {normalize_predicate(r.value): r for r in RelationType}


def _iter_store_attributes(store_data: dict):
    """Yield (entity_label, attribute_string) for every asserted store cell.

    The store is keyed by DOCUMENT, not by term:
    ``{pmid: {"entities": {label: {"pred: target": 1.0}}, "meta_stamp": ...}}``.
    A term therefore appears once per abstract that mentioned it, and the same
    term can be typed differently by two abstracts -- which is the disagreement
    this module has to surface rather than let the last writer win.
    """
    from wound_ontology.store.concept_store import records_of
    for _, ents in records_of(store_data):
        for label, attrs in ents.items():
            for attr, value in attrs.items():
                if value == 1.0:
                    yield label, str(attr)


def store_to_gate_inputs(store_data: dict, resolve_conflict=None) -> tuple[list, list, dict]:
    """Recover (entities, relations, report) from the ConceptStore dictionary.

    `report` is the point of this function as much as the two lists are. It
    separates "the gate looked and found nothing wrong" from "the gate could not
    look", which are otherwise the same outcome from the caller's side:

        untyped            terms carrying no `is_a: <BFOCategory>` at all
        conflicting        terms two abstracts typed DIFFERENTLY that could NOT
                           be reconciled -- the cross-abstract disagreement
                           stage-1 typing cannot prevent, since it types each
                           abstract independently
        reconciled         {label: (proposed, agreed)} for conflicts retreated to
                           a common ancestor by `resolve_conflict`. These ARE
                           gated, at the category all the abstracts agree on.

    `resolve_conflict(categories) -> category | None` decides what a term typed
    several ways becomes; pass `ReasonerGate.least_common_category` to retreat to
    the most specific category MILD says subsumes them all. Without it every
    conflict is simply excluded (the safe default, but it discards real terms).
        unknown_predicate  predicate keys with no RelationType, counted per key
        untyped_object     relations whose target is not a typed term
        unlicensed         relations whose (subject cat, object cat) pair
                           MILD/WONT does not license
    """
    from wound_ontology.llm.extraction_models import (
        RELATION_DOMAINS,
        ExtractedEntity,
        ExtractedRelation,
    )

    preds = _predicate_lookup()
    report: dict = {
        "untyped": [],
        "conflicting": {},
        "unknown_predicate": {},
        "untyped_object": {},
        "unlicensed": [],
        "reconciled": {},
    }

    # ── pass 1: typing ────────────────────────────────────────────────────
    seen: set[str] = set()
    found: dict[str, set[str]] = {}
    for label, attr in _iter_store_attributes(store_data):
        seen.add(label)
        pred, sep, target = attr.partition(": ")
        if sep and pred.strip() == "is_a" and target.strip() in _CATEGORY_VALUES:
            found.setdefault(label, set()).add(target.strip())

    categories: dict[str, str] = {}
    for label in sorted(seen):
        cats = found.get(label, set())
        if not cats:
            report["untyped"].append(label)
        elif len(cats) > 1:
            agreed = resolve_conflict(cats) if resolve_conflict else None
            if agreed is None:
                report["conflicting"][label] = sorted(cats)
            else:
                report["reconciled"][label] = (sorted(cats), agreed)
                categories[label] = agreed
        else:
            categories[label] = next(iter(cats))

    entities = [
        ExtractedEntity(label=lab, category=BFOCategory(cat))
        for lab, cat in sorted(categories.items())
    ]

    # ── pass 2: relations between two typed terms ─────────────────────────
    # De-duplicated: the same triple asserted by twelve abstracts is one axiom,
    # and feeding it twelve times would inflate every count the gate reports.
    triples: set[tuple[str, str, str]] = set()
    for label, attr in _iter_store_attributes(store_data):
        if label not in categories:
            continue                      # subject untyped or conflicting
        pred, sep, target = attr.partition(": ")
        pred, target = pred.strip(), target.strip()
        if not sep or pred == "is_a":
            continue                      # subsumption: the OTHER gate's job
        rel = preds.get(pred)
        if rel is None:
            report["unknown_predicate"][pred] = \
                report["unknown_predicate"].get(pred, 0) + 1
            continue
        if target not in categories:
            report["untyped_object"][target] = \
                report["untyped_object"].get(target, 0) + 1
            continue
        triples.add((label, rel.value, target))

    relations = []
    for subj, pred_value, obj in sorted(triples):
        pair = (categories[subj], categories[obj])
        if pair not in RELATION_DOMAINS.get(pred_value, set()):
            report["unlicensed"].append((subj, pred_value, obj))
        relations.append(
            ExtractedRelation(subject=subj, predicate=RelationType(pred_value),
                              object=obj)
        )

    return entities, relations, report


def describe_gate_inputs(entities, relations, report: dict) -> str:
    """Human-readable account of what is gateable and what is not.

    Counts are printed even when zero, so silence never reads as success.
    """
    lines = [
        f"gateable: {len(entities)} typed term(s), {len(relations)} relation(s)",
        f"NOT gateable -- no BFO category: {len(report['untyped'])} term(s)",
        f"NOT gateable -- irreconcilable categories: "
        f"{len(report['conflicting'])} term(s)",
        f"reconciled to a common ancestor (gated): "
        f"{len(report.get('reconciled', {}))} term(s)",
        f"NOT gateable -- predicate has no RelationType: "
        f"{sum(report['unknown_predicate'].values())} edge(s) across "
        f"{len(report['unknown_predicate'])} predicate(s)",
        f"NOT gateable -- target is not a typed term: "
        f"{sum(report['untyped_object'].values())} edge(s)",
        f"licensing violations (gated anyway, reported): "
        f"{len(report['unlicensed'])}",
    ]
    return "\n".join(lines)
