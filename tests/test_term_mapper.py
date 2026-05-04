import numpy as np
import pandas as pd
import pytest

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


class FakeTermMappingClient:
    def __init__(self, embeddings=None, normalization_results=None):
        self.embeddings = {
            "wound": [0.0, 1.0],
            "granulation": [1.0, 0.0],
            **(embeddings or {}),
        }
        self.normalization_results = normalization_results or {}
        self.embedding_calls = []
        self.normalization_calls = []

    async def create_embeddings(self, terms):
        self.embedding_calls.append(list(terms))
        return [self.embeddings[term] for term in terms]

    async def create_normalization_mapping(self, terms, standards):
        self.normalization_calls.append((list(terms), list(standards)))
        return {
            term: self.normalization_results[term]
            for term in terms
            if term in self.normalization_results
        }


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
def mapper(dm):
    return TermMapper(data_manager=dm, file_name="term_mapping", mapper_name="test_mapper")


# ── Legacy public surface ─────────────────────────────────────────────────────

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
    mapper = TermMapper(data_manager=MockDM({}), file_name="empty_term_mapping", mapper_name="empty")
    df = pd.DataFrame([[1, 0]], columns=["term_a", "term_b"])

    assert list(mapper.apply(df).columns) == ["term_a", "term_b"]
    assert mapper.standards == []
    assert mapper.originals == []


# ── Embedding utilities ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_standard_embeddings_only_embeds_missing_standards(mapper):
    client = FakeTermMappingClient()

    await mapper._ensure_standard_embeddings(client)
    await mapper._ensure_standard_embeddings(client)

    assert client.embedding_calls == [["granulation", "wound"]]
    assert set(mapper._standard_embeddings) == {"granulation", "wound"}


def test_nearest_standard_returns_best_cosine_match(mapper):
    mapper._standard_embeddings = {
        "granulation": np.array([1.0, 0.0]),
        "wound": np.array([0.0, 1.0]),
    }

    standard, score = mapper._nearest_standard(np.array([0.0, 0.9]))

    assert standard == "wound"
    assert score == pytest.approx(1.0)


def test_nearest_standard_without_embeddings_returns_empty_match(mapper):
    assert mapper._nearest_standard(np.array([1.0, 0.0])) == (None, 0.0)


# ── build_from_embeddings ─────────────────────────────────────────────────────

def test_build_from_embeddings_merges_near_identical_surface_forms(dm):
    """Case and hyphen variants of the same term collapse to one canonical."""
    mapper = TermMapper(data_manager=MockDM({}), file_name="t", mapper_name="t")
    # Identical (after L2 norm) embeddings → cosine = 1.0
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

    # Higher-frequency term becomes canonical
    assert result["wound healing"] == result["Wound Healing"]
    assert result["Wound Healing"] == "Wound Healing"
    assert result["full thickness"] == result["full-thickness"]
    assert result["full-thickness"] == "full-thickness"


def test_build_from_embeddings_keeps_distinct_terms_separate(dm):
    """Orthogonal embeddings never merge regardless of string similarity."""
    mapper = TermMapper(data_manager=MockDM({}), file_name="t", mapper_name="t")
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


def test_build_from_embeddings_generic_term_not_merged_without_string_match(dm):
    """Generic single-word terms (wound, pain…) require string_sim ≥ 0.90."""
    mapper = TermMapper(data_manager=MockDM({}), file_name="t", mapper_name="t")
    # High cosine (0.99) between "wound" and "pain" — must still be blocked
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


def test_build_from_embeddings_canonicals_map_to_themselves(dm):
    """Every canonical in the output must map to itself."""
    mapper = TermMapper(data_manager=MockDM({}), file_name="t", mapper_name="t")
    embedder = FakeEmbedder({
        "A": [1.0, 0.0],
        "B": [1.0, 0.0],  # merges with A
        "C": [0.0, 1.0],
    })

    result = mapper.build_from_embeddings(
        ["A", "B", "C"], embedder, similarity_threshold=0.95
    )

    for term, canonical in result.items():
        assert result[canonical] == canonical, f"Canonical '{canonical}' does not map to itself"


def test_build_from_embeddings_max_cluster_assertion(dm):
    """AssertionError is raised when a cluster reaches 20+ members."""
    mapper = TermMapper(data_manager=MockDM({}), file_name="t", mapper_name="t")
    # 25 terms all with identical embeddings → one giant cluster
    terms = [f"term_{i}" for i in range(25)]
    embedder = FakeEmbedder({t: [1.0, 0.0] for t in terms})

    with pytest.raises(AssertionError, match="≥ 20"):
        mapper.build_from_embeddings(terms, embedder, similarity_threshold=0.95)


# ── Human review and unresolved retry ─────────────────────────────────────────

def test_export_review_csv_writes_low_confidence_metadata(mapper, tmp_path):
    mapper._metadata = {
        "needs review": {"standard": "candidate", "confidence": 0.6, "method": "llm"},
        "accepted": {"standard": "wound", "confidence": 0.95, "method": "similarity"},
    }
    path = tmp_path / "review.csv"

    mapper.export_review_csv(str(path))

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
    path = tmp_path / "review.csv"
    pd.DataFrame([{
        "term": "needs review",
        "suggested_standard": "candidate",
        "confidence": 0.6,
        "method": "llm",
        "reviewed_standard": "manual standard",
        "notes": "reviewed",
    }]).to_csv(path, index=False)

    mapper.import_review_csv(str(path))

    assert mapper.mapping["needs review"] == "manual standard"
    assert mapper._metadata["needs review"] == {
        "standard": "manual standard",
        "confidence": 1.0,
        "method": "manual",
    }
    assert dm.saved[-1][1] == "term_mapping"


@pytest.mark.asyncio
async def test_resolve_unresolved_retries_terms_and_clears_queue(mapper, dm):
    mapper._unresolved_terms = ["ambiguous term"]
    client = FakeTermMappingClient(normalization_results={"ambiguous term": "resolved standard"})

    await mapper.resolve_unresolved(client)

    assert mapper.mapping["ambiguous term"] == "resolved standard"
    assert mapper._metadata["ambiguous term"] == {
        "standard": "resolved standard",
        "confidence": 0.7,
        "method": "llm_retry",
    }
    assert mapper._unresolved_terms == []
    assert dm.saved[-1][1] == "term_mapping"


def test_term_mapper_has_default_term_mapping_identity(dm):
    mapper = TermMapper(data_manager=dm, file_name="terms")

    assert mapper.__class__ is TermMapper
    assert mapper.name == "Term mapper"
    assert mapper.file_name == "terms"
