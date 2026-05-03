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


# ── Embedding-assisted incremental mapping ────────────────────────────────────

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


@pytest.mark.asyncio
async def test_map_new_terms_auto_maps_high_similarity_terms(mapper, dm):
    client = FakeTermMappingClient(embeddings={"slow wound": [0.0, 0.95]})

    result = await mapper.map_new_terms(["slow wound"], client)

    assert result["slow wound"] == "wound"
    assert mapper._metadata["slow wound"] == {
        "standard": "wound",
        "confidence": pytest.approx(1.0),
        "method": "similarity",
    }
    assert client.normalization_calls == []
    assert dm.saved[-1][1] == "term_mapping"


@pytest.mark.asyncio
async def test_map_new_terms_uses_llm_fallback_for_uncertain_similarity(mapper):
    client = FakeTermMappingClient(
        embeddings={"fragile skin": [0.2, 0.2], "skin fragility": [0.3, 0.4]},
        normalization_results={"fragile skin": "skin fragility"},
    )

    await mapper.map_new_terms(["fragile skin"], client)

    assert mapper.mapping["fragile skin"] == "skin fragility"
    assert mapper._metadata["fragile skin"] == {
        "standard": "skin fragility",
        "confidence": 0.6,
        "method": "llm",
    }
    assert client.normalization_calls == [(["fragile skin"], ["granulation", "wound"])]
    assert "skin fragility" in mapper._standard_embeddings


@pytest.mark.asyncio
async def test_map_new_terms_records_unresolved_terms(mapper):
    client = FakeTermMappingClient(embeddings={"ambiguous term": [0.2, 0.2]})

    await mapper.map_new_terms(["ambiguous term"], client)

    assert "ambiguous term" not in mapper.mapping
    assert mapper._unresolved_terms == ["ambiguous term"]
    assert mapper._metadata["ambiguous term"] == {
        "standard": None,
        "confidence": 0.0,
        "method": "unresolved",
    }


@pytest.mark.asyncio
async def test_map_new_terms_skips_cached_terms_without_llm_calls(mapper):
    client = FakeTermMappingClient()

    result = await mapper.map_new_terms(["chronic wound"], client)

    assert result == mapper.mapping
    assert client.embedding_calls == []
    assert client.normalization_calls == []


# ── Bulk bootstrap mode ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_mapping_normalizes_only_new_terms_and_records_bulk_metadata(mapper, dm):
    client = FakeTermMappingClient(
        normalization_results={
            "sloughy": "slough",
            "granulating": "granulation",
        }
    )

    result = await mapper.build_mapping(
        ["chronic wound", "sloughy", "granulating"],
        client,
        batch_size=1,
        chunk_size=1,
    )

    assert result["sloughy"] == "slough"
    assert result["granulating"] == "granulation"
    assert "chronic wound" not in [call[0][0] for call in client.normalization_calls]
    assert mapper._metadata["sloughy"] == {
        "standard": "slough",
        "confidence": 0.6,
        "method": "llm_bulk",
    }
    assert dm.saved[-1][1] == "term_mapping"


@pytest.mark.asyncio
async def test_build_mapping_returns_cached_mapping_when_every_term_is_known(mapper, dm):
    client = FakeTermMappingClient()

    result = await mapper.build_mapping(["chronic wound", "acute wound"], client)

    assert result == mapper.mapping
    assert client.normalization_calls == []
    assert dm.saved == []


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
