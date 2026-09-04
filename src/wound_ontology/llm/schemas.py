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
    # label was new and trivially satisfied by answering "MaterialEntity". Across
    # five live runs it refused no bad name and lost one good one to a missing
    # field. What the group *is* comes from the concept's intent, which needs no
    # model at all; what remains of the check is grounded in the ontologies.


class ScopeCheckResponse(BaseModel):
    inappropriate: list[str]  # entity names from the input that are out of scope


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
