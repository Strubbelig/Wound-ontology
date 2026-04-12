"""
Unit tests for OWLEnricher.

These tests do NOT require network access or API keys — they work on
small OWL files built in-process with owlready2.
"""
import pytest
from pathlib import Path
from owlready2 import get_ontology, Thing
import types as python_types

from wound_ontology.export.owl_enricher import OWLEnricher


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_minimal_owl(tmp_path, iri_suffix="enricher_test") -> Path:
    """Create a tiny OWL file with three local classes and no external imports."""
    owl_path = tmp_path / f"{iri_suffix}.owl"
    onto = get_ontology(f"http://test.org/{iri_suffix}/")
    with onto:
        ChronicWound  = python_types.new_class("Chronic_Wound",  (Thing,))
        AcuteWound    = python_types.new_class("Acute_Wound",    (Thing,))
        Wound         = python_types.new_class("Wound",          (Thing,))
        ChronicWound.is_a.append(Wound)
        AcuteWound.is_a.append(Wound)
    onto.save(file=str(owl_path), format="rdfxml")
    return owl_path


def _enricher(base_iri="http://example.org/TEST_", prefix="TEST", id_start=1) -> OWLEnricher:
    return OWLEnricher(base_iri=base_iri, id_prefix=prefix, id_start=id_start)


# ── load ───────────────────────────────────────────────────────────────────────

def test_load_returns_self(tmp_path):
    owl = _make_minimal_owl(tmp_path, "load_test")
    e = _enricher()
    result = e.load(str(owl))
    assert result is e


def test_load_populates_onto(tmp_path):
    owl = _make_minimal_owl(tmp_path, "load_onto_test")
    e = _enricher()
    e.load(str(owl))
    assert e._onto is not None
    assert e._world is not None


# ── rename_iris ────────────────────────────────────────────────────────────────

def test_rename_iris_assigns_new_iri(tmp_path):
    owl = _make_minimal_owl(tmp_path, "rename_test")
    e = _enricher(base_iri="http://example.org/TST_", prefix="TST")
    e.load(str(owl))
    e.rename_iris()
    for cls in e._onto.classes():
        assert "TST_" in cls.iri, f"Expected TST_ prefix in IRI, got {cls.iri}"


def test_rename_iris_assigns_label(tmp_path):
    owl = _make_minimal_owl(tmp_path, "label_test")
    e = _enricher()
    e.load(str(owl))
    e.rename_iris()
    for cls in e._onto.classes():
        assert cls.label, f"No label assigned to {cls.iri}"


def test_rename_iris_increments_counter(tmp_path):
    owl = _make_minimal_owl(tmp_path, "counter_test")
    e = _enricher(base_iri="http://example.org/CTR_", prefix="CTR", id_start=10)
    e.load(str(owl))
    e.rename_iris()
    # IRIs are base_iri + zero-padded counter, e.g. http://example.org/CTR_0000010
    ids = sorted(int(cls.iri.split("CTR_")[-1]) for cls in e._onto.classes())
    assert ids == list(range(10, 10 + len(ids)))


def test_rename_preserves_subclass_structure(tmp_path):
    owl = _make_minimal_owl(tmp_path, "structure_test")
    e = _enricher()
    e.load(str(owl))
    e.rename_iris()
    # After renaming, subClassOf relationships must still exist
    has_subclass = False
    for cls in e._onto.classes():
        for parent in cls.is_a:
            if hasattr(parent, "iri") and parent.iri != "http://www.w3.org/2002/07/owl#Thing":
                has_subclass = True
    assert has_subclass, "subClassOf relations lost after IRI renaming"


def test_self_loop_entity_gets_iri(tmp_path):
    """
    An entity whose only parent is itself (self-loop in RDF) must still receive
    a new IRI. We write the RDF directly because owlready2 rejects self-loops
    in its Python API.
    """
    owl_path = tmp_path / "selfloop.owl"
    owl_path.write_text("""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://test.org/selfloop/"/>
  <owl:Class rdf:about="http://test.org/selfloop/Loop_Entity">
    <rdfs:subClassOf rdf:resource="http://test.org/selfloop/Loop_Entity"/>
  </owl:Class>
</rdf:RDF>""")
    e = _enricher(base_iri="http://example.org/SL_", prefix="SL")
    e.load(str(owl_path))
    e.rename_iris()   # must not raise
    irises = [cls.iri for cls in e._onto.classes()]
    assert any("SL_" in iri for iri in irises), "Self-loop entity did not get renamed"


# ── save ──────────────────────────────────────────────────────────────────────

def test_save_creates_file(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "save_in")
    owl_out = tmp_path / "enriched.owl"
    e = _enricher()
    e.load(str(owl_in))
    e.rename_iris()
    e.save(str(owl_out))
    assert owl_out.exists()
    assert owl_out.stat().st_size > 0


def test_saved_file_contains_new_iris(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "iri_check")
    owl_out = tmp_path / "iri_check_out.owl"
    e = _enricher(base_iri="http://example.org/CHK_", prefix="CHK")
    e.load(str(owl_in))
    e.rename_iris()
    e.save(str(owl_out))
    content = owl_out.read_text()
    assert "CHK_" in content


def test_saved_file_contains_labels(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "lbl_check")
    owl_out = tmp_path / "lbl_check_out.owl"
    e = _enricher()
    e.load(str(owl_in))
    e.rename_iris()
    e.save(str(owl_out))
    content = owl_out.read_text()
    assert "label" in content.lower()


# ── enrich (one-shot) ─────────────────────────────────────────────────────────

def test_enrich_no_imports(tmp_path):
    """enrich() without external imports still renames and saves."""
    owl_in  = _make_minimal_owl(tmp_path, "enrich_in")
    owl_out = tmp_path / "enrich_out.owl"
    e = OWLEnricher(base_iri="http://example.org/ENC_", id_prefix="ENC", id_start=1)
    e.enrich(
        input_file=str(owl_in),
        output_file=str(owl_out),
        import_bfo=False,
        import_ro=False,
        import_obi=False,
        run_reasoner=False,
    )
    assert owl_out.exists()
    content = owl_out.read_text()
    assert "ENC_" in content


def test_enriched_owl_differs_from_source(tmp_path):
    """The enriched file must differ from the original (IRIs were changed)."""
    owl_in  = _make_minimal_owl(tmp_path, "diff_test")
    owl_out = tmp_path / "diff_out.owl"
    original = owl_in.read_text()
    e = OWLEnricher(base_iri="http://example.org/DIF_", id_prefix="DIF", id_start=1)
    e.enrich(str(owl_in), str(owl_out), import_bfo=False, import_ro=False)
    enriched = owl_out.read_text()
    assert original != enriched
