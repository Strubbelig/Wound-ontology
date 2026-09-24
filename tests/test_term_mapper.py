import numpy as np
import pandas as pd
import pytest

from wound_ontology.mappers.term_mapping import TermMapping
from wound_ontology.mappers.term_mapper import TermMapper


INITIAL_MAPPING = {
    "chronic wound": "wound",
    "acute wound": "wound",
    "granulation": "granulation",
}


class MockDM:
    def __init__(self, mapping=None):
        self.mapping = dict(INITIAL_MAPPING if mapping is None else mapping)
        self.saved = []

    def load_latest_json(self, _):
        return dict(self.mapping)

    def save_as_json(self, data, file_name):
        self.saved.append((dict(data), file_name))


class FakeEmbedder:
    """Returns pre-set L2-normalised embeddings for unit tests."""

    def __init__(self, embeddings: dict[str, list[float]]):
        self._raw = embeddings

    def embed(self, texts: list[str]) -> np.ndarray:
        dim = len(next(iter(self._raw.values())))
        vecs = []
        for t in texts:
            v = np.array(self._raw.get(t, [0.0] * dim), dtype=float)
            norm = np.linalg.norm(v)
            vecs.append(v / norm if norm > 0 else v)
        return np.vstack(vecs)


@pytest.fixture
def dm():
    return MockDM()


@pytest.fixture
def term_mapping(dm):
    return TermMapping(dm, "term_mapping")


@pytest.fixture
def mapper(term_mapping):
    return TermMapper(term_mapping=term_mapping, name="test_mapper")


# ── Mapping access ────────────────────────────────────────────────────────────

def test_standards_are_unique_and_sorted(mapper):
    assert mapper.standards == ["granulation", "wound"]


def test_originals_are_sorted(mapper):
    assert mapper.originals == ["acute wound", "chronic wound", "granulation"]


def test_map_known_term(mapper):
    assert mapper.map("chronic wound") == "wound"


def test_map_unknown_term_passthrough(mapper):
    assert mapper.map("unknown term") == "unknown term"


def test_apply_renames_index_and_columns_without_mutating_original(mapper):
    df = pd.DataFrame(
        [[1, 0], [0, 1]],
        index=["chronic wound", "unknown entity"],
        columns=["acute wound", "unknown term"],
    )

    result = mapper.apply(df)

    assert "wound" in result.index
    assert "wound" in result.columns
    assert "unknown entity" in result.index
    assert "unknown term" in result.columns
    assert "chronic wound" not in result.index
    assert "acute wound" not in result.columns
    assert list(df.index) == ["chronic wound", "unknown entity"]
    assert list(df.columns) == ["acute wound", "unknown term"]


def test_empty_term_mapping_passthrough():
    dm = MockDM({})
    tm = TermMapping(dm, "empty_term_mapping")
    mapper = TermMapper(term_mapping=tm, name="empty")
    df = pd.DataFrame([[1, 0]], columns=["term_a", "term_b"])

    assert list(mapper.apply(df).columns) == ["term_a", "term_b"]
    assert mapper.standards == []
    assert mapper.originals == []


def test_term_mapper_has_default_name(dm):
    tm = TermMapping(dm, "terms")
    mapper = TermMapper(term_mapping=tm)

    assert mapper.__class__ is TermMapper
    assert mapper.name == "Term mapper"


# ── build_from_embeddings ─────────────────────────────────────────────────────

def _make_mapper(data=None):
    dm = MockDM(data or {})
    tm = TermMapping(dm, "t")
    return TermMapper(term_mapping=tm, name="t")


def test_build_from_embeddings_merges_near_identical_surface_forms():
    """Case and hyphen variants of the same term collapse to one canonical."""
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "Wound Healing":  [1.0, 0.0, 0.0],
        "wound healing":  [1.0, 0.0, 0.0],
        "full-thickness": [0.0, 1.0, 0.0],
        "full thickness": [0.0, 1.0, 0.0],
    })
    freq = {"Wound Healing": 10, "wound healing": 5, "full-thickness": 8, "full thickness": 3}

    result = mapper.build_from_embeddings(
        list(freq.keys()), embedder, similarity_threshold=0.95, frequencies=freq
    )

    assert result["wound healing"] == result["Wound Healing"]
    assert result["Wound Healing"] == "Wound Healing"
    assert result["full thickness"] == result["full-thickness"]
    assert result["full-thickness"] == "full-thickness"


def test_build_from_embeddings_pre_merges_trailing_abbreviations():
    """Terms identical after normalize_term merge without SapBERT (step 0)."""
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "Systemic Sclerosis (SSc)":          [1.0, 0.0],
        "Split-Thickness Skin Graft (STSG)": [0.0, 1.0],
    })
    freq = {
        "Systemic Sclerosis (SSc)":          10,
        "Systemic Sclerosis":                 5,
        "Split-Thickness Skin Graft (STSG)":  8,
        "Split-thickness skin graft (STSG)":  3,
    }

    result = mapper.build_from_embeddings(list(freq.keys()), embedder, frequencies=freq)

    assert result["Systemic Sclerosis"] == result["Systemic Sclerosis (SSc)"]
    assert result["Split-thickness skin graft (STSG)"] == result["Split-Thickness Skin Graft (STSG)"]


def test_build_from_embeddings_keeps_distinct_terms_separate():
    """Orthogonal embeddings never merge regardless of string similarity."""
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "wound":      [1.0, 0.0, 0.0],
        "laceration": [0.0, 1.0, 0.0],
        "necrosis":   [0.0, 0.0, 1.0],
    })

    result = mapper.build_from_embeddings(
        ["wound", "laceration", "necrosis"], embedder, similarity_threshold=0.95
    )

    assert result["wound"]      == "wound"
    assert result["laceration"] == "laceration"
    assert result["necrosis"]   == "necrosis"


def test_build_from_embeddings_generic_term_not_merged_without_string_match():
    """Generic single-word terms (wound, pain…) require string_sim ≥ 0.90."""
    mapper = _make_mapper()
    v = np.array([1.0, 0.01, 0.0])
    v /= np.linalg.norm(v)
    embedder = FakeEmbedder({
        "wound": v.tolist(),
        "pain":  [1.0, 0.0, 0.0],
    })

    result = mapper.build_from_embeddings(
        ["wound", "pain"], embedder, similarity_threshold=0.95
    )

    assert result["wound"] != result["pain"]


def test_build_from_embeddings_canonicals_map_to_themselves():
    """Every canonical in the output must map to itself."""
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "A": [1.0, 0.0],
        "B": [1.0, 0.0],
        "C": [0.0, 1.0],
    })

    result = mapper.build_from_embeddings(
        ["A", "B", "C"], embedder, similarity_threshold=0.95
    )

    for term, canonical in result.items():
        assert result[canonical] == canonical, f"Canonical '{canonical}' does not map to itself"


def test_build_from_embeddings_single_linkage_would_merge_complete_linkage_does_not():
    """
    Classic Union-Find failure case: A↔B valid, B↔C valid, but A↔C invalid.
    Complete-linkage must keep A and C in separate clusters.

    Geometry (3D, L2-normalised):
      B = [1, 0, 0]          — the bridge
      A = [0.95,  0.312, 0]  — cos(A,B) = 0.95  (at merge threshold)
      C = [0.95, -0.312, 0]  — cos(C,B) = 0.95  (at merge threshold)
      cos(A,C) = 0.95²-0.312² ≈ 0.805  (below threshold → no direct edge)
    """
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "term_a": [0.95,  0.312, 0.0],
        "term_b": [1.0,   0.0,   0.0],
        "term_c": [0.95, -0.312, 0.0],
    })

    result = mapper.build_from_embeddings(
        ["term_a", "term_b", "term_c"], embedder, frequencies={}
    )

    ab_merged = result.get("term_a", "term_a") == result.get("term_b", "term_b")
    bc_merged = result.get("term_b", "term_b") == result.get("term_c", "term_c")
    assert ab_merged or bc_merged, "At least one valid edge must produce a merge"

    assert result.get("term_a", "term_a") != result.get("term_c", "term_c"), \
        "Complete-linkage must not merge term_a and term_c via term_b as bridge"


# ── CSV review workflow (MappingCleaner) ──────────────────────────────────────

def test_export_review_csv_writes_low_confidence_metadata(mapper, tmp_path):
    from wound_ontology.mappers.mapping_cleaner import MappingCleaner
    # Confidence and method live ON the record now (rule 37); `metadata` is a
    # view over them rather than a dict of its own that vanished with the run.
    mapper._term_mapping._records = {
        "needs review": {"to": "candidate", "confidence": 0.6, "method": "llm",
                         "refused": {}},
        "accepted":     {"to": "wound", "confidence": 0.95, "method": "similarity",
                         "refused": {}},
    }
    mapper._term_mapping._dirty()
    cleaner = MappingCleaner(mapper)
    path = tmp_path / "review.csv"

    cleaner.export_review_csv(str(path))

    df = pd.read_csv(path)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["term"] == "needs review"
    assert row["suggested_standard"] == "candidate"
    assert row["confidence"] == 0.6
    assert row["method"] == "llm"
    assert pd.isna(row["reviewed_standard"])
    assert pd.isna(row["notes"])


def test_import_review_csv_overrides_mapping_and_marks_manual(mapper, dm, tmp_path):
    from wound_ontology.mappers.mapping_cleaner import MappingCleaner
    cleaner = MappingCleaner(mapper)
    path = tmp_path / "review.csv"
    pd.DataFrame([{
        "term":               "needs review",
        "suggested_standard": "candidate",
        "confidence":         0.6,
        "method":             "llm",
        "reviewed_standard":  "manual standard",
        "notes":              "reviewed",
    }]).to_csv(path, index=False)

    cleaner.import_review_csv(str(path))

    assert mapper.mapping["needs review"] == "manual standard"
    assert mapper._term_mapping.metadata["needs review"] == {
        "standard":   "manual standard",
        "confidence": 1.0,
        "method":     "manual",
    }
    assert dm.saved[-1][1] == "term_mapping"
