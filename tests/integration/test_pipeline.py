"""
Integration tests for the full wound ontology pipeline.

Requirements:
  - OPENROUTER_API_KEY and ENTREZ_EMAIL set in .env or environment
  - Network access to PubMed and OpenRouter API

Run with:
  pytest tests/integration/ -m integration -v

Skip during normal unit test runs:
  pytest tests/ -m "not integration"
"""
import os
from pathlib import Path

import pandas as pd
import pytest

from wound_ontology.orchestrator import Orchestrator

# Every test here drives the live LLM pipeline.
pytestmark = pytest.mark.needs_llm


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tmp_data_dir():
    """
    Output directory for integration test artefacts.
    Uses a fixed path so OWL files survive after the test run for inspection.
    """
    d = Path(__file__).resolve().parents[1] / "test_output"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="module")
def pipeline(tmp_data_dir):
    return Orchestrator(base_path=tmp_data_dir)


@pytest.fixture(scope="module")
def predefined_df():
    """A small curated overlay. The old data/raw/predefined_concept_hierarchy.csv
    is gone — that table is merged into WONT and MILD — so curated edges now
    reach run_build_hierarchies() only when passed explicitly."""
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
    # The abstracts come from test_pubmed_search through the shared module
    # fixture. Run on its own (a node id, -k, --lf) or after that search came
    # back empty, this test used to find no abstracts and fail as `assert 0 > 0`,
    # which said nothing about why. It now runs the search itself, and says so.
    if pipeline.pubcon.database.empty:
        print("\n[test_extract_to_cache] the abstract table is empty "
              "(test_pubmed_search did not run first, or found nothing); "
              "running the same search here")
        pipeline.run_pubmed_search("wound healing", max_results_per_query=3)
    assert not pipeline.pubcon.database.empty, (
        "PubMed returned no abstracts for 'wound healing', so there is nothing "
        "to extract; this is a search failure, not an extraction failure")
    pipeline.run_extract_to_store(batch_size=2)
    assert len(pipeline.store.dict) > 0
    # Every entry must have an "entities" key
    for pmid_data in pipeline.store.dict.values():
        assert "entities" in pmid_data


# ── Step 3: Build hierarchies ─────────────────────────────────────────────────

@pytest.mark.integration
def test_build_hierarchies(pipeline, predefined_df):
    # Passed explicitly to keep this test off the real WONT/MILD files;
    # predefined_df=None would read them via curated_seed.load_curated_edges.
    pipeline.run_build_hierarchies(predefined_df=predefined_df)

    # Normalization may rename concepts, so check size rather than specific
    # (potentially renamed) names.
    assert len(pipeline.class_hier.concepts) > 3, \
        "ClassHierarchy has too few concepts — the store may not have loaded"
    # At least one root must exist (top-level parents have no parent of their own)
    assert len(pipeline.class_hier.roots) > 0
    # All values in the DataFrame must be numeric
    assert pipeline.class_hier.df.dtypes.apply(
        lambda d: d.kind in ("f", "i")
    ).all(), "ClassHierarchy df must be numeric"


@pytest.mark.integration
def test_mereological_hierarchy_populated(pipeline):
    # Only meaningful if cache contained part_of / has_part triples
    # — check structure is valid regardless of content
    assert isinstance(pipeline.mere_hier.df, pd.DataFrame)
    assert pipeline.mere_hier.df.dtypes.apply(
        lambda d: d.kind in ("f", "i")
    ).all(), "MereologicalHierarchy df must be numeric"


# ── Step 4: Store attribute fill ─────────────────────────────────────────────

@pytest.mark.integration
def test_store_fill(pipeline):
    """run_store_fill evaluates missing entity–attribute pairs in the ConceptStore."""
    attrs_before = len(pipeline.store.attributes)
    pipeline.run_store_fill(batch_size=2, entity_batch=3, max_entities=5, max_attrs_per_entity=20)

    # A "llm_fill" key should appear in the store (unless all pairs were already known)
    store_keys = list(pipeline.store.dict.keys())
    if "llm_fill" in store_keys:
        fill_entities = pipeline.store.dict["llm_fill"].get("entities", {})
        # Every filled entity must only contain 0.0 / 1.0 values
        for entity, attrs in fill_entities.items():
            for val in attrs.values():
                assert val in (0.0, 1.0), f"Unexpected fill value {val} for {entity}"

    # Attribute count must not shrink
    assert len(pipeline.store.attributes) >= attrs_before


# ── Step 6: OWL export ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_export_to_owl(pipeline, tmp_data_dir):
    owl_file = tmp_data_dir / "test_ontology.owl"
    pipeline.export_to_owl(output_file=str(owl_file))
    assert owl_file.exists()
    assert owl_file.stat().st_size > 0
    content = owl_file.read_text()
    assert "owl" in content.lower()


# ── Step 7: FCA on subtree ────────────────────────────────────────────────────

@pytest.mark.integration
def test_fca_on_subtree(pipeline, tmp_data_dir):
    pipeline.run_fca(
        subtree_root="Wound",
        predicates=["has_quality", "occurs_in", "caused_by", "is_treatment_for"],
        batch_size=2,
    )
    # With a tiny corpus the FCA predicates may yield no columns — that's valid.
    # We assert entities exist but allow an empty attribute set.
    if pipeline.context_matrix.df.empty and not pipeline.context_matrix.df.index.empty:
        print("\nWARN: FCA matrix has entities but no matching predicate columns "
              "(expected with a very small corpus).")
    elif not pipeline.context_matrix.df.empty:
        wound_subtree = pipeline.class_hier.subtree_of("Wound")
        for entity in pipeline.context_matrix.df.index:
            assert entity in wound_subtree, f"{entity} not in Wound subtree"

    # FCAHierarchy must be a valid DataFrame
    assert isinstance(pipeline.fca_hier.df, pd.DataFrame)

    # Every named FCA superclass must be accounted for: committed as an edge,
    # recorded as a review candidate, or judged by the head-word rule with a
    # reason (rule 79) or withheld before it, in the rule's report.
    #
    # This used to assert membership in .concepts outright, which run_fca stopped
    # honouring when commit_fca gained its False default: FCA observes that terms
    # share attributes, which is evidence for a superclass rather than an
    # assertion of one, so suggestions go to .candidates for review. The stale
    # assertion survived only because a three-abstract corpus produced no FCA
    # columns at all, so the loop never had a name to check. Conceptual scaling
    # gives the context an is_a column, so it does now. Since rule 79
    # (2026-10-18) the head-word rule empties the review queue, so a refused
    # name is in the report, not in .candidates ("Skin And Soft Tissue Injury",
    # refused for Acute Wound: "says ['and', 'skin', 'soft', 'tissue']").
    lattice = pipeline.lattice.lattice
    if lattice is not None:
        fca_names = [
            getattr(c, 'name', None) for c in lattice
            if isinstance(getattr(c, 'name', None), str)
        ]
        # _set_edge Title-cases names, so normalise before checking
        fca_names_title = [n.strip().title() for n in fca_names]
        print(f"\nFCA superclass names: {fca_names_title}")
        proposed_parents = {p for _, p in pipeline.class_hier.candidates}
        judged = pipeline.fca_head_rule
        if fca_names:
            assert judged and Path(judged["report"]).exists(), \
                "run_fca named concepts but left no head-word rule report"
        verdict_of: dict[str, list[str]] = {}
        for verdict in ("licensed", "refused", "synonym", "open"):
            for r in judged.get(verdict, []):
                assert r.get("reason"), f"{verdict} edge without a reason: {r}"
                for n in (r["parent"], r["as"]):
                    verdict_of.setdefault(n.lower(), []).append(f"{verdict}: {r['reason']}")
        for why, names in judged.get("withheld", {}).items():
            for n in names:
                verdict_of.setdefault(n.lower(), []).append(f"withheld: {why}")
        for name in fca_names_title:
            assert (name in pipeline.class_hier.concepts
                    or name in proposed_parents
                    or name.lower() in verdict_of), \
                (f"FCA superclass '{name}' reached neither ClassHierarchy, its "
                 f"review candidates nor the head-word rule's report — it was "
                 f"named and then dropped")
        print(f"FCA names judged by the head-word rule: "
              f"{ {n: verdict_of[n.lower()][:2] for n in fca_names_title if n.lower() in verdict_of} }")

    # Re-export OWL with FCA results merged in and verify FCA names appear
    owl_out = tmp_data_dir / "ontology_with_fca.owl"
    pipeline.export_to_owl(output_file=str(owl_out))
    assert owl_out.exists()
    content = owl_out.read_text()

    if lattice is not None:
        # Only *committed* names can be in the OWL. This is the same stale
        # expectation the .concepts assertion above carried: under
        # commit_fca=False a named superclass is a review candidate, so its
        # absence from the export is the contract working, not a lost edge.
        # That a candidate was recorded rather than dropped is asserted above;
        # this checks the other half — a committed one really is written out.
        committed = [n for n in fca_names_title if n in pipeline.class_hier.concepts]
        for name in committed:
            safe = name.strip().replace(" ", "_")
            assert safe in content, f"FCA superclass '{safe}' not found in OWL"
        pending = [n for n in fca_names_title if n not in committed]
        if pending:
            print(f"FCA names awaiting review (correctly absent from OWL): {pending}")
    print(f"\nOWL with FCA → {owl_out} ({owl_out.stat().st_size} bytes)")


# ── Step 7b: lattice.summary() ───────────────────────────────────────────────

@pytest.mark.integration
def test_lattice_summary(pipeline, capsys):
    """lattice.summary() must run without error regardless of lattice size."""
    pipeline.lattice.summary(max_display=10)
    captured = capsys.readouterr()
    # Either named concepts were found, or the lattice was empty — both are valid
    assert ("named superclasses displayed" in captured.out
            or "No lattice available" in captured.out)


# ── Step 8: OWL enrichment (IRI rename + BFO/RO import) ──────────────────────

@pytest.mark.integration
def test_enrich_owl(pipeline, tmp_data_dir):
    """
    Enrich the FCA OWL: rename local IRIs to WOND_NNNNNNN, add labels,
    import BFO and RO. Compare against the plain export to confirm differences.
    """
    # Use FCA OWL if available, fall back to the plain export
    plain_owl = tmp_data_dir / "ontology_with_fca.owl"
    if not plain_owl.exists():
        plain_owl = tmp_data_dir / "test_ontology.owl"
    enriched_owl = tmp_data_dir / "ontology_enriched.owl"

    assert plain_owl.exists(), "No OWL file found to enrich — run export tests first"

    pipeline.run_curate_owl(
        input_file=str(plain_owl),
        output_file=str(enriched_owl),
        import_bfo=True,
        import_ro=True,
        import_obi=False,
    )

    assert enriched_owl.exists()
    assert enriched_owl.stat().st_size > 0

    plain_content    = plain_owl.read_text()
    enriched_content = enriched_owl.read_text()

    # Enriched file must differ from source
    assert plain_content != enriched_content, "Enriched OWL is identical to plain OWL"

    # Proper IRI prefix must be present (from settings.py ONTOLOGY_BASE_IRI)
    try:
        from config.settings import ONTOLOGY_ID_PREFIX
    except ImportError:
        ONTOLOGY_ID_PREFIX = "WOND"
    assert ONTOLOGY_ID_PREFIX + "_" in enriched_content, \
        f"Expected {ONTOLOGY_ID_PREFIX}_ IRIs in enriched OWL"

    # rdfs:label must appear (assigned from original class names)
    assert "label" in enriched_content.lower()

    # BFO import declaration must be present
    assert "bfo" in enriched_content.lower()

    print(f"\nPlain OWL    → {plain_owl}    ({plain_owl.stat().st_size:,} bytes)")
    print(f"Enriched OWL → {enriched_owl}  ({enriched_owl.stat().st_size:,} bytes)")
    print(f"Size delta: +{enriched_owl.stat().st_size - plain_owl.stat().st_size:,} bytes")

    # Print first class with a WOND_ IRI so we can visually verify
    from wound_ontology.owl import OWLOntology
    from wound_ontology.data_manager.data_manager import DataManager
    verifier = OWLOntology.load(str(enriched_owl), DataManager())
    sample = [(cls.iri, cls.label.first() if cls.label else None)
              for cls in verifier.onto.classes()
              if ONTOLOGY_ID_PREFIX + "_" in cls.iri][:5]
    print("\nSample enriched classes (IRI → label):")
    for iri, label in sample:
        print(f"  {iri}  →  {label}")
