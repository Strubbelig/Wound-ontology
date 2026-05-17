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


def test_build_from_embeddings_pre_merges_trailing_abbreviations(dm):
    """Terms identical after normalize_term merge without SapBERT (step 0)."""
    mapper = TermMapper(data_manager=MockDM({}), file_name="t", mapper_name="t")
    # Embedder only knows the canonical form — pre-merged variants never reach it.
    embedder = FakeEmbedder({
        "Systemic Sclerosis (SSc)": [1.0, 0.0],
        "Split-Thickness Skin Graft (STSG)": [0.0, 1.0],
    })
    freq = {
        "Systemic Sclerosis (SSc)": 10,
        "Systemic Sclerosis":       5,
        "Split-Thickness Skin Graft (STSG)": 8,
        "Split-thickness skin graft (STSG)": 3,
    }

    result = mapper.build_from_embeddings(list(freq.keys()), embedder, frequencies=freq)

    assert result["Systemic Sclerosis"] == result["Systemic Sclerosis (SSc)"]
    assert result["Split-thickness skin graft (STSG)"] == result["Split-Thickness Skin Graft (STSG)"]


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


def test_build_from_embeddings_single_linkage_would_merge_complete_linkage_does_not(dm):
    """
    Classic Union-Find failure case: A↔B valid, B↔C valid, but A↔C invalid.
    Complete-linkage must keep A and C in separate clusters.
    Uses FakeEmbedder (identical cosine=1.0 for all pairs) so only the
    string-similarity guard distinguishes which pairs are valid.
    """
    mapper = TermMapper(data_manager=MockDM({}), file_name="t", mapper_name="t")
    # A="Wound Healing", B="Wound Healings" (high str_sim with both A and C),
    # C="Sound Healing" — str_sim(A,C) ≈ 0.889 < 0.92.
    # Union-Find would merge all three (A↔B→{A,B}, then B↔C→{A,B,C}).
    # Complete-linkage must reject the merge of {A,B} with {C} because A↔C is invalid.
    terms = ["Wound Healing", "Wound Healings", "Sound Healing"]
    embedder = FakeEmbedder({t: [1.0, 0.0] for t in terms})  # cosine=1.0 for all

    result = mapper.build_from_embeddings(terms, embedder, frequencies={})

    wh = result["Wound Healing"]
    assert result["Wound Healings"] == wh, "Near-identical terms must merge"
    assert result.get("Sound Healing", "Sound Healing") != wh, \
        "Complete linkage must not transitively pull 'Sound Healing' into the Wound Healing cluster"


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


def test_build_from_embeddings_complete_linkage_blocks_transitive_merge():
    """
    Complete-linkage must block transitive false merges.

    A↔B and B↔C each pass cosine+string thresholds, but A and C do not.
    With single-linkage (Union-Find) all three end up in one cluster.
    With complete-linkage, A and C stay separate.
    """
    mapper = TermMapper(data_manager=MockDM({}), file_name="t", mapper_name="t")

    # A=[1,0], B=[cos45,sin45], C=[0,1]
    # cos(A,B)=0.707 — below 0.95, so this test is actually verifying the threshold logic.
    # Use embeddings where A↔B and B↔C are ≥0.95 but A↔C is not.
    # cos(A,B) = A·B / (|A||B|). With L2-normalised: [1,0]·[0.98,0.2] ≈ 0.98 ✓
    # [0.98,0.2]·[0.2,0.98] ≈ 0.196+0.196 = 0.392 — not ≥ 0.95, so B↔C edge is weak.
    # Better: use 3D embeddings to place B between A and C with each edge ≥0.95.
    # A=[1,0,0], B=[0.97,0.24,0], C=[0.97,0,0.24]
    # cos(A,B)=0.97 ✓, cos(A,C)=0.97 ✓ — that merges all three. Not what we want.
    #
    # Correct setup: A and C are far, B is close to both.
    # Use string-sim guard: A="Wound Healing", B="Wound Healings", C="Sound Healing"
    # string_sim(A,C) < 0.92 → blocks direct A↔C edge even if cosine were high.
    # Give all three cosine=1.0 via identical embeddings to test string-sim guard only.
    terms = ["Wound Healing", "Wound Healings", "Sound Healing"]
    embedder = FakeEmbedder({t: [1.0, 0.0] for t in terms})  # cosine=1.0 for all pairs

    result = mapper.build_from_embeddings(terms, embedder, frequencies={})

    # "Wound Healing" and "Wound Healings" are near-identical → should merge
    assert result["Wound Healing"] == result["Wound Healings"], \
        "Near-identical terms must merge"

    # "Sound Healing" has low string-sim with "Wound Healing" (< 0.92) → must NOT merge
    # With Union-Find it would merge via "Wound Healings" as bridge;
    # with complete-linkage it stays separate because "Sound Healing"↔"Wound Healing" is invalid.
    wh_canonical = result["Wound Healing"]
    assert result.get("Sound Healing", "Sound Healing") != wh_canonical, \
        "Complete linkage must not transitively merge 'Sound Healing' with 'Wound Healing'"
