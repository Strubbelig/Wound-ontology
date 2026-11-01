"""
Pipeline inspection test.

Runs the full pipeline against the real data directory and writes all
intermediate artifacts to tests/test_output/ for manual inspection.

Run with:
  pytest tests/test_inspection.py -m integration -v -s

Output files:
  tests/test_output/ontology.owl          — OWL export
  tests/test_output/cache.json            — raw extraction cache
  tests/test_output/matrix.csv           — FCA context matrix
  tests/test_output/class_hierarchy.csv  — ClassHierarchy DataFrame
  tests/test_output/fca_hierarchy.csv    — FCAHierarchy DataFrame
"""
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from wound_ontology.orchestrator import Orchestrator

# Real reference files — copied into temp dir so BFO leaf attributes are available
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_REAL_REFERENCE_DIR = _PROJECT_ROOT / "data" / "reference"

OUTPUT_DIR = Path(__file__).parent / "test_output"
OUTPUT_DIR.mkdir(exist_ok=True)

QUERIES = [
    "chronic wound healing",
    "surgical wound infection",
]
MAX_ABSTRACTS = 3   # keep small: fast extraction, small hierarchies


@pytest.fixture(scope="module")
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        cache_dir = tmp / "cache"
        cache_dir.mkdir()
        # reference_path = base_path.parent / "reference" = tmp / "reference"
        ref_dst = tmp / "reference"
        ref_dst.mkdir()
        if _REAL_REFERENCE_DIR.exists():
            for f in _REAL_REFERENCE_DIR.glob("*.csv"):
                shutil.copy(f, ref_dst / f.name)
        yield cache_dir


@pytest.fixture(scope="module")
def pipeline(tmp_data_dir):
    return Orchestrator(base_path=tmp_data_dir)


@pytest.mark.integration
def test_run_full_pipeline(pipeline):
    pipeline.run_pubmed_search(QUERIES, max_results_per_query=MAX_ABSTRACTS)
    assert not pipeline.pubcon.database.empty
    assert len(pipeline.pubcon.database) <= MAX_ABSTRACTS * len(QUERIES)


@pytest.mark.integration
def test_extract_and_dump_cache(pipeline):
    pipeline.run_extract_to_store(batch_size=MAX_ABSTRACTS * len(QUERIES))
    assert len(pipeline.store.dict) > 0

    out = OUTPUT_DIR / "cache.json"
    out.write_text(json.dumps(pipeline.store.dict, indent=2, ensure_ascii=False))
    print(f"\nStore → {out}  ({len(pipeline.store.dict)} PMIDs)")


@pytest.mark.integration
def test_build_hierarchies_and_dump(pipeline):
    import pandas as pd
    predefined = pd.DataFrame([
        {"Class": "Chronic Wound",  "Parent class": "Wound"},
        {"Class": "Surgical Wound", "Parent class": "Wound"},
        {"Class": "Acute Wound",    "Parent class": "Wound"},
    ])
    pipeline.run_build_hierarchies(predefined_df=predefined)

    pipeline.class_hier.df.to_csv(OUTPUT_DIR / "class_hierarchy.csv")
    print(f"\nClassHierarchy    → {OUTPUT_DIR / 'class_hierarchy.csv'}")


@pytest.mark.integration
def test_fca_and_dump(pipeline):
    pipeline.run_fca(
        subtree_root="Wound",
        predicates=["has_quality", "occurs_in", "caused_by", "is_treatment_for"],
        batch_size=MAX_ABSTRACTS * len(QUERIES),
    )
    pipeline.context_matrix.df.to_csv(OUTPUT_DIR / "matrix.csv")
    pipeline.fca_hier.df.to_csv(OUTPUT_DIR / "fca_hierarchy.csv")
    print(f"\nFCA matrix        → {OUTPUT_DIR / 'matrix.csv'}")
    print(f"FCAHierarchy      → {OUTPUT_DIR / 'fca_hierarchy.csv'}")


@pytest.mark.integration
def test_export_owl_and_dump(pipeline):
    owl_out = OUTPUT_DIR / "ontology.owl"
    pipeline.export_to_owl(output_file=owl_out)
    assert owl_out.exists()
    print(f"\nOWL               → {owl_out}  ({owl_out.stat().st_size} bytes)")
    # Print a short snippet so it's visible in -s output
    lines = owl_out.read_text().splitlines()
    print("\n--- OWL snippet (first 30 lines) ---")
    print("\n".join(lines[:30]))
