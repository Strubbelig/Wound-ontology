"""
Integration tests for TermMapper.build_mapping.

Requirements:
  - OPENROUTER_API_KEY set in .env or environment
  - Network access to OpenRouter API

Run with:
  pytest tests/integration/test_term_mapper.py -m integration -v

Skip during normal unit test runs:
  pytest tests/ -m "not integration"
"""
import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.llm.llm_client import LLMClient
from wound_ontology.mappers.term_mapper import TermMapper

load_dotenv()

# Each pair is the same concept in different surface forms.
# Both must collapse to the same standard — having both as separate
# has_quality: infected / has_quality: infection columns is the bug we prevent.
SYNONYM_PAIRS = [
    ("infected",  "infection"),      # same concept, adj vs noun form
    ("necrotic",  "necrosis"),       # same concept, adj vs noun form
    ("granulating", "granulation tissue"),  # same concept, participle vs noun phrase
]

# Concepts that are genuinely different and must NOT collapse.
DISTINCT_PAIRS = [
    ("infected",  "necrotic"),
    ("chronic",   "infected"),
]

TERMS = list({t for pair in SYNONYM_PAIRS + DISTINCT_PAIRS for t in pair})


# ── Module-scoped fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope="module")
def llm():
    return LLMClient(os.getenv("OPENROUTER_API_KEY", ""))


@pytest.fixture(scope="module")
def mapper(tmp_data_dir):
    dm = DataManager(base_path=tmp_data_dir)
    return TermMapper(data_manager=dm, file_name="term_mapping_test", mapper_name="test_mapper")


@pytest.fixture(scope="module")
def built_mapper(mapper, llm):
    """Run build_mapping once; all tests below share the result."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        mapper.build_mapping(TERMS, llm, batch_size=2)
    )
    return mapper


# ── Mechanics ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_all_terms_in_originals(built_mapper):
    """Every input term must be stored after processing."""
    for term in TERMS:
        assert term in built_mapper.originals, f"'{term}' missing from originals"


@pytest.mark.integration
def test_standards_are_non_empty(built_mapper):
    assert len(built_mapper.standards) > 0


@pytest.mark.integration
def test_term_mapping_persisted_to_disk(built_mapper, tmp_data_dir):
    files = list(tmp_data_dir.glob("term_mapping_test_*.json"))
    assert len(files) > 0, "No JSON file written to disk"


@pytest.mark.integration
def test_already_processed_terms_skipped(built_mapper, llm):
    """Second call with the same terms must be a no-op (no new API call)."""
    import asyncio
    originals_before = set(built_mapper.originals)
    asyncio.get_event_loop().run_until_complete(
        built_mapper.build_mapping(TERMS, llm, batch_size=2)
    )
    assert set(built_mapper.originals) == originals_before


# ── Semantic content: collapsing ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("term_a, term_b", SYNONYM_PAIRS)
def test_synonyms_collapse_to_same_standard(built_mapper, term_a, term_b):
    """
    Same-concept terms must map to the same standard.
    Having has_quality: infected and has_quality: infection as separate
    matrix columns is the redundancy this mapper exists to prevent.
    """
    std_a = built_mapper.mapping[term_a]
    std_b = built_mapper.mapping[term_b]
    assert std_a == std_b, (
        f"'{term_a}' → '{std_a}' and '{term_b}' → '{std_b}' "
        f"should collapse to one standard"
    )


# ── Semantic content: separation ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("term_a, term_b", DISTINCT_PAIRS)
def test_distinct_concepts_stay_separate(built_mapper, term_a, term_b):
    """Different concepts must not collapse to the same standard."""
    std_a = built_mapper.mapping[term_a]
    std_b = built_mapper.mapping[term_b]
    assert std_a != std_b, (
        f"'{term_a}' and '{term_b}' collapsed to '{std_a}' "
        f"but they are different concepts"
    )


# ── Apply methods use the built mapping ───────────────────────────────────────

@pytest.mark.integration
def test_apply_then_matrix_merge_collapses_synonyms(built_mapper, tmp_data_dir):
    """
    apply renames; ContextMatrix.merge() deduplicates.
    After the full round-trip, synonym columns must be collapsed to one.
    """
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.fca.context_matrix import ContextMatrix

    dm = DataManager(base_path=tmp_data_dir / "merge_col_test")
    matrix = ContextMatrix(dm, "col_merge_test")

    for term_a, term_b in SYNONYM_PAIRS:
        matrix._df = None   # reset between pairs
        df = pd.DataFrame([[1.0, 0.0]], columns=[term_a, term_b], index=["entity_a"])
        renamed = built_mapper.apply(df)
        matrix.df = renamed  # triggers merge()
        assert len(matrix.attributes) == 1, (
            f"After rename+merge, '{term_a}' and '{term_b}' should be one column, "
            f"got: {matrix.attributes}"
        )


@pytest.mark.integration
def test_apply_then_matrix_merge_collapses_synonyms(built_mapper, tmp_data_dir):
    """
    apply renames; ContextMatrix.merge() deduplicates.
    After the full round-trip, synonym rows must be collapsed to one.
    """
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.fca.context_matrix import ContextMatrix

    dm = DataManager(base_path=tmp_data_dir / "merge_idx_test")
    matrix = ContextMatrix(dm, "idx_merge_test")

    for term_a, term_b in SYNONYM_PAIRS:
        matrix._df = None   # reset between pairs
        df = pd.DataFrame([[1.0], [1.0]], index=[term_a, term_b], columns=["has_quality: wound"])
        renamed = built_mapper.apply(df)
        matrix.df = renamed  # triggers merge()
        assert len(matrix.objects) == 1, (
            f"After rename+merge, '{term_a}' and '{term_b}' should be one row, "
            f"got: {matrix.objects}"
        )
