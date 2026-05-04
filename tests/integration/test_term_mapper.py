"""
Integration tests for TermMapper.build_from_embeddings with real SapBERT.

Tests surface-form synonym merging — only near-identical strings (case, hyphen,
whitespace, parenthetical abbreviation variants) collapse.  Morphological variants
like infected/infection are intentionally kept separate.

Run with:
  pytest tests/integration/test_term_mapper.py -m integration -v

Skip during normal unit test runs:
  pytest tests/ -m "not integration"
"""
import tempfile
from pathlib import Path

import pytest

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.embedding.embedder import Embedder
from wound_ontology.mappers.term_mapper import TermMapper


# Pairs that MUST collapse: same concept, different surface form only.
SYNONYM_PAIRS = [
    ("full-thickness",     "full thickness"),     # hyphen variant
    ("Wound Healing",      "wound healing"),       # case variant
    ("deep partial thickness", "deep-partial thickness"),  # hyphen + case
]

# Pairs that MUST stay separate: different specificity or different concept.
DISTINCT_PAIRS = [
    ("full thickness",       "full thickness burn"),  # extra word = more specific concept
    ("wound",                "laceration"),            # generic vs specific type
    ("infected",             "infection"),             # morphological variant — accepted difference
]

TERMS = list(dict.fromkeys(
    t for pair in SYNONYM_PAIRS + DISTINCT_PAIRS for t in pair
))


# ── Module-scoped fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope="module")
def embedder():
    return Embedder(batch_size=64)


@pytest.fixture(scope="module")
def built_mapper(tmp_data_dir, embedder):
    dm = DataManager(base_path=tmp_data_dir)
    mapper = TermMapper(data_manager=dm, file_name="term_mapping_test", mapper_name="test_mapper")
    mapper.build_from_embeddings(
        TERMS,
        embedder=embedder,
        similarity_threshold=0.95,
        string_threshold=0.92,
    )
    return mapper


# ── Mechanics ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_all_terms_in_mapping(built_mapper):
    """Every input term must appear as a key in the output mapping."""
    for term in TERMS:
        assert term in built_mapper.mapping, f"'{term}' missing from mapping"


@pytest.mark.integration
def test_every_canonical_maps_to_itself(built_mapper):
    for term, canonical in built_mapper.mapping.items():
        assert built_mapper.mapping[canonical] == canonical, \
            f"Canonical '{canonical}' does not map to itself"


@pytest.mark.integration
def test_term_mapping_persisted_to_disk(built_mapper, tmp_data_dir):
    files = list(tmp_data_dir.glob("term_mapping_test_*.json"))
    assert len(files) > 0, "No JSON file written to disk"


# ── Semantic content: collapsing ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("term_a, term_b", SYNONYM_PAIRS)
def test_surface_form_synonyms_collapse(built_mapper, term_a, term_b):
    """
    Near-identical surface forms (case / hyphen / whitespace variants)
    must map to the same canonical.
    """
    std_a = built_mapper.mapping[term_a]
    std_b = built_mapper.mapping[term_b]
    assert std_a == std_b, (
        f"'{term_a}' → '{std_a}' and '{term_b}' → '{std_b}' "
        f"should collapse to one canonical"
    )


# ── Semantic content: separation ──────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("term_a, term_b", DISTINCT_PAIRS)
def test_distinct_terms_stay_separate(built_mapper, term_a, term_b):
    """
    Terms with different meaning or specificity must not share a canonical.
    Note: morphological variants like infected/infection are also expected to
    stay separate under the string-similarity guard (string_sim ≈ 0.71 < 0.92).
    """
    std_a = built_mapper.mapping[term_a]
    std_b = built_mapper.mapping[term_b]
    assert std_a != std_b, (
        f"'{term_a}' and '{term_b}' incorrectly collapsed to '{std_a}'"
    )
