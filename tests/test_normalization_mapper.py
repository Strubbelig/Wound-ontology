import pandas as pd
import pytest
from wound_ontology.mappers.normalization_mapper import NormalizationMapper


class MockDM:
    def load_latest_json(self, _): return {"chronic wound": "wound", "acute wound": "wound", "granulation": "granulation"}
    def save_as_json(self, *a): pass


@pytest.fixture
def mapper():
    return NormalizationMapper("test_mapper", MockDM(), "test_mapping")


# ── Properties ─────────────────────────────────────────────────────────────────

def test_standards_are_unique_and_sorted(mapper):
    assert mapper.standards == sorted(set(mapper.standards))
    assert mapper.standards == ["granulation", "wound"]


def test_originals_are_sorted(mapper):
    assert mapper.originals == sorted(mapper.originals)
    assert "chronic wound" in mapper.originals


# ── apply ──────────────────────────────────────────────────────────────────────

def test_apply_renames_columns(mapper):
    df = pd.DataFrame([[1, 0]], columns=["chronic wound", "granulation"])
    result = mapper.apply(df)
    assert "wound" in result.columns
    assert "granulation" in result.columns
    assert "chronic wound" not in result.columns


def test_apply_keeps_unknown_columns(mapper):
    df = pd.DataFrame([[1]], columns=["unknown term"])
    result = mapper.apply(df)
    assert "unknown term" in result.columns


def test_apply_renames_index(mapper):
    df = pd.DataFrame([[1], [0]], index=["chronic wound", "granulation"])
    result = mapper.apply(df)
    assert "wound" in result.index
    assert "granulation" in result.index
    assert "chronic wound" not in result.index


def test_apply_keeps_unknown_index(mapper):
    df = pd.DataFrame([[1]], index=["some entity"])
    result = mapper.apply(df)
    assert "some entity" in result.index


def test_apply_does_not_mutate_original(mapper):
    df = pd.DataFrame([[1]], columns=["chronic wound"])
    mapper.apply(df)
    assert "chronic wound" in df.columns


# ── map (single term) ──────────────────────────────────────────────────────────

def test_map_known_term(mapper):
    assert mapper.map("chronic wound") == "wound"


def test_map_unknown_term_passthrough(mapper):
    assert mapper.map("unknown term") == "unknown term"


# ── Empty mapping edge case ────────────────────────────────────────────────────

def test_empty_mapping_passthrough():
    class EmptyDM:
        def load_latest_json(self, _): return {}
        def save_as_json(self, *a): pass

    m = NormalizationMapper("empty", EmptyDM(), "empty_mapping")
    df = pd.DataFrame([[1, 0]], columns=["term_a", "term_b"])
    assert list(m.apply(df).columns) == ["term_a", "term_b"]
    assert m.standards == []
    assert m.originals == []
