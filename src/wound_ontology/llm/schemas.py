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


class SemanticNameResponse(BaseModel):
    superclass_name: str
