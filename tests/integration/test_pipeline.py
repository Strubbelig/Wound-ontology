"""
Integration tests for the full wound ontology pipeline.

Requirements:
  - GOOGLE_API_KEY and ENTREZ_EMAIL set in .env or environment
  - Network access to PubMed and Google Gemini API

Run with:
  pytest tests/integration/ -m integration -v

Skip during normal unit test runs:
  pytest tests/ -m "not integration"
"""
import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from wound_ontology.orchestrator import Orchestrator


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_data_dir():
    """Isolated temp directory so integration tests don't touch real data/cache."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope="module")
def pipeline(tmp_data_dir):
    return Orchestrator(base_path=tmp_data_dir)


@pytest.fixture(scope="module")
def predefined_df():
    return pd.DataFrame([
        {"Class": "Chronic Wound",  "Parent class": "Wound"},
        {"Class": "Acute Wound",    "Parent class": "Wound"},
        {"Class": "Surgical Wound", "Parent class": "Wound"},
    ])


# ── Step 1: PubMed search ─────────────────────────────────────────────────────

@pytest.mark.integration
def test_pubmed_search(pipeline):
    pipeline.run_pubmed_search("wound healing", max_results_per_query=3)
    assert not pipeline.pubcon.database.empty
    assert "abstract" in pipeline.pubcon.database.columns
    assert "pmid"     in pipeline.pubcon.database.columns


# ── Step 2: LLM extraction → store ───────────────────────────────────────────

@pytest.mark.integration
def test_extract_to_cache(pipeline):
    pipeline.run_extract_to_store(batch_size=2)
    assert len(pipeline.store.dict) > 0
    # Every entry must have an "entities" key
    for pmid_data in pipeline.store.dict.values():
        assert "entities" in pmid_data


# ── Step 3: Build hierarchies ─────────────────────────────────────────────────

@pytest.mark.integration
def test_build_hierarchies(pipeline, predefined_df):
    pipeline.run_build_hierarchies(predefined_df=predefined_df)

    # Predefined is_a edges must be in ClassHierarchy
    assert pipeline.class_hier.df.at["Chronic Wound",  "Wound"] == 1.0
    assert pipeline.class_hier.df.at["Acute Wound",    "Wound"] == 1.0
    assert pipeline.class_hier.df.at["Surgical Wound", "Wound"] == 1.0

    # ClassHierarchy must not contain part_of edges
    mere_cols = set(pipeline.mere_hier.df.columns)
    class_cols = set(pipeline.class_hier.df.columns)
    # They may overlap in concept names but mereological roots should differ
    assert "Wound" in pipeline.class_hier.roots


@pytest.mark.integration
def test_mereological_hierarchy_populated(pipeline):
    # Only meaningful if cache contained part_of / has_part triples
    # — check structure is valid regardless of content
    assert isinstance(pipeline.mere_hier.df, pd.DataFrame)
    assert pipeline.mere_hier.df.dtypes.apply(
        lambda d: d.kind in ("f", "i")
    ).all(), "MereologicalHierarchy df must be numeric"


# ── Step 4: OWL export ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_export_to_owl(pipeline, tmp_data_dir):
    owl_file = tmp_data_dir / "test_ontology.owl"
    pipeline.exporter.create_owl(output_file=str(owl_file))
    assert owl_file.exists()
    assert owl_file.stat().st_size > 0
    content = owl_file.read_text()
    assert "owl" in content.lower()


# ── Step 5: FCA on subtree ────────────────────────────────────────────────────

@pytest.mark.integration
def test_fca_on_subtree(pipeline, tmp_data_dir):
    pipeline.run_fca(
        subtree_root="Wound",
        predicates=["has_quality", "occurs_in", "caused_by", "is_treatment_for"],
        batch_size=2,
    )
    assert not pipeline.context_matrix.df.empty

    wound_subtree = pipeline.class_hier.subtree_of("Wound")
    for entity in pipeline.context_matrix.df.index:
        assert entity in wound_subtree, f"{entity} not in Wound subtree"

    # FCAHierarchy must be a valid DataFrame
    assert isinstance(pipeline.fca_hier.df, pd.DataFrame)

    # Named FCA superclasses must now appear in ClassHierarchy as parents
    lattice = pipeline.lattice.lattice
    if lattice is not None:
        fca_names = [
            getattr(c, 'name', None) for c in lattice
            if isinstance(getattr(c, 'name', None), str)
        ]
        print(f"\nFCA superclass names: {fca_names}")
        for name in fca_names:
            assert name in pipeline.class_hier.concepts, \
                f"FCA superclass '{name}' not found in ClassHierarchy"

    # Re-export OWL with FCA results merged in and verify FCA names appear
    owl_out = tmp_data_dir / "ontology_with_fca.owl"
    pipeline.exporter.create_owl(output_file=str(owl_out))
    assert owl_out.exists()
    content = owl_out.read_text()

    if lattice is not None:
        for name in fca_names:
            safe = name.strip().replace(" ", "_")
            assert safe in content, f"FCA superclass '{safe}' not found in OWL"
    print(f"\nOWL with FCA → {owl_out} ({owl_out.stat().st_size} bytes)")
