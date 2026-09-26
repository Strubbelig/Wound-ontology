from __future__ import annotations
from pydantic import BaseModel, Field


# 1. Nested schema to enforce RO/BFO Triple structure
class FCAAttribute(BaseModel):
    predicate: str  # e.g., "is_a", "has_part"
    target: str     # e.g., "CDC Surgical Wound Classification"

class Entity(BaseModel):
    object: str
    true_attributes: list[FCAAttribute] = Field(
        description="Attributes explicitly confirmed in the text."
    )
    false_attributes: list[FCAAttribute] = Field(
        description="Attributes explicitly denied or ruled out in the text."
    )

class ExtractResponse(BaseModel):
    entities: list[Entity]


class NormalizationEntry(BaseModel):
    original: str
    standard: str

class NormalizationResponse(BaseModel):
    mappings: list[NormalizationEntry]


class FillNanResponse(BaseModel):
    confirmed_attributes: list[str]


class FillNanEntityResult(BaseModel):
    object_name: str
    confirmed_attributes: list[str]
    # Attributes the model positively rules OUT. Anything in neither list is
    # left undecided rather than being silently written as false — "uncertain"
    # and "false" are different answers and must not be collapsed.
    denied_attributes: list[str] = []

class FillNanBatchResponse(BaseModel):
    results: list[FillNanEntityResult]


class SemanticNameResponse(BaseModel):
    superclass_name: str
    # No `category` field. Asking the model to declare the category of the name
    # it had just invented was a claim about a label, unverifiable whenever the
    # label was new and trivially satisfied by answering "material entity". Across
    # five live runs it refused no bad name and lost one good one to a missing
    # field. What the group *is* comes from the concept's intent, which needs no
    # model at all; what remains of the check is grounded in the ontologies.


class ScopeCheckResponse(BaseModel):
    inappropriate: list[str]  # entity names from the input that are out of scope


class GateVerdict(BaseModel):
    """One term, judged in or out, with the reason."""

    term: str
    verdict: str          # "in" | "out"
    reason: str = ""


class GateBatchResponse(BaseModel):
    """A verdict FOR EVERY TERM in the batch.

    `ScopeCheckResponse` returns only the out-of-scope names, so a term the
    model omitted is indistinguishable from one it judged in scope -- and
    `review_susp_entities` whitelisted every omission, which meant a short or
    truncated answer for a batch of 50 was 50 permanent decisions nobody made.
    Asking for an explicit verdict per term makes silence visible: a term absent
    from `verdicts` gets no gate verdict at all, and is asked again.
    """

    verdicts: list[GateVerdict]


class MereRelationResult(BaseModel):
    child: str
    parent: str
    verdict: str  # "keep" | "is_a" | "drop"

class MereRelationBatchResponse(BaseModel):
    results: list[MereRelationResult]


class OccursInTargetResult(BaseModel):
    term: str
    anatomical: bool

class OccursInTargetBatch(BaseModel):
    results: list[OccursInTargetResult]


# ── Two-stage schema-driven extraction (C2) ────────────────────────────────
# Wire models for the schema-constrained path. `category` and `predicate` are
# plain strings here ON PURPOSE: the permitted values are advertised to the model
# through json_schema_extra (so the JSON-schema hint still enumerates them) but a
# single bad value must not fail the whole batch and burn the retry budget.
# Values are validated locally, and anything unrecognised is dropped and reported
# rather than coerced — guessing which branch of BFO a bad label meant would be
# exactly the manufactured certainty this pipeline is trying to remove.

def _category_names() -> list[str]:
    from wound_ontology.llm.extraction_models import BFOCategory
    return [c.value for c in BFOCategory]


def _relation_names() -> list[str]:
    from wound_ontology.llm.extraction_models import RelationType
    return [r.value for r in RelationType]


class TypedTerm(BaseModel):
    """Stage 1 output: one term, one BFO/MILD category. No relations, no IRIs."""

    label: str = Field(description="the term exactly as it appears in the text")
    category: str = Field(
        description="exactly one category name from the allowed list",
        json_schema_extra=lambda s: s.update(enum=_category_names()),
    )


class TypingResponse(BaseModel):
    terms: list[TypedTerm] = Field(default_factory=list)


class RelationCandidate(BaseModel):
    """Stage 2 output: a relation between two already-typed terms."""

    subject: str
    predicate: str = Field(
        description="exactly one relation name from the allowed list",
        json_schema_extra=lambda s: s.update(enum=_relation_names()),
    )
    object: str


class RelationResponse(BaseModel):
    relations: list[RelationCandidate] = Field(default_factory=list)


# ── Anchor-mapping adjudication ────────────────────────────────────────────
# `verdict` is a plain string for the same reason `category` above is: the
# allowed values are advertised through json_schema_extra, but one bad value
# must not fail a batch of twenty good ones. Unrecognised verdicts are refused
# locally and reported -- never coerced into the accepting value.

def _verdict_names() -> list[str]:
    from wound_ontology.mappers.mapping_adjudicator import VERDICTS
    return list(VERDICTS)


class MappingVerdict(BaseModel):
    """Whether a store term and an existing ontology class name the same class."""

    store_term: str
    ontology_class: str
    verdict: str = Field(
        description="exactly one verdict name from the allowed list",
        json_schema_extra=lambda s: s.update(enum=_verdict_names()),
    )
    reason: str = Field(default="", description="one short clause, for the report")


class MappingVerdictBatch(BaseModel):
    results: list[MappingVerdict] = Field(default_factory=list)
