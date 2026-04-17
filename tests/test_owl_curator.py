"""
Unit tests for OWLCurator.

These tests do NOT require network access or API keys — they work on
small OWL files built in-process with owlready2.
"""
import pytest
from pathlib import Path
from owlready2 import get_ontology, Thing
import types as python_types

from wound_ontology.export.owl_curator import OWLCurator


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_minimal_owl(tmp_path, iri_suffix="curator_test") -> Path:
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


def _curator(base_iri="http://example.org/TEST_", prefix="TEST", id_start=1) -> OWLCurator:
    return OWLCurator(base_iri=base_iri, id_prefix=prefix, id_start=id_start)


# ── load ───────────────────────────────────────────────────────────────────────

def test_load_returns_self(tmp_path):
    owl = _make_minimal_owl(tmp_path, "load_test")
    c = _curator()
    result = c.load(str(owl))
    assert result is c


def test_load_populates_onto(tmp_path):
    owl = _make_minimal_owl(tmp_path, "load_onto_test")
    c = _curator()
    c.load(str(owl))
    assert c._onto is not None
    assert c._world is not None


# ── rename_iris ────────────────────────────────────────────────────────────────

def test_rename_iris_assigns_new_iri(tmp_path):
    owl = _make_minimal_owl(tmp_path, "rename_test")
    c = _curator(base_iri="http://example.org/TST_", prefix="TST")
    c.load(str(owl))
    c.rename_iris()
    for cls in c._onto.classes():
        assert "TST_" in cls.iri, f"Expected TST_ prefix in IRI, got {cls.iri}"


def test_rename_iris_assigns_label(tmp_path):
    owl = _make_minimal_owl(tmp_path, "label_test")
    c = _curator()
    c.load(str(owl))
    c.rename_iris()
    for cls in c._onto.classes():
        assert cls.label, f"No label assigned to {cls.iri}"


def test_rename_iris_increments_counter(tmp_path):
    owl = _make_minimal_owl(tmp_path, "counter_test")
    c = _curator(base_iri="http://example.org/CTR_", prefix="CTR", id_start=10)
    c.load(str(owl))
    c.rename_iris()
    # IRIs are base_iri + zero-padded counter, e.g. http://example.org/CTR_0000010
    ids = sorted(int(cls.iri.split("CTR_")[-1]) for cls in c._onto.classes())
    assert ids == list(range(10, 10 + len(ids)))


def test_rename_preserves_subclass_structure(tmp_path):
    owl = _make_minimal_owl(tmp_path, "structure_test")
    c = _curator()
    c.load(str(owl))
    c.rename_iris()
    # After renaming, subClassOf relationships must still exist
    has_subclass = False
    for cls in c._onto.classes():
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
    c = _curator(base_iri="http://example.org/SL_", prefix="SL")
    c.load(str(owl_path))
    c.rename_iris()   # must not raise
    irises = [cls.iri for cls in c._onto.classes()]
    assert any("SL_" in iri for iri in irises), "Self-loop entity did not get renamed"


# ── save ──────────────────────────────────────────────────────────────────────

def test_save_creates_file(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "save_in")
    owl_out = tmp_path / "curated.owl"
    c = _curator()
    c.load(str(owl_in))
    c.rename_iris()
    c.save(str(owl_out))
    assert owl_out.exists()
    assert owl_out.stat().st_size > 0


def test_saved_file_contains_new_iris(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "iri_check")
    owl_out = tmp_path / "iri_check_out.owl"
    c = _curator(base_iri="http://example.org/CHK_", prefix="CHK")
    c.load(str(owl_in))
    c.rename_iris()
    c.save(str(owl_out))
    content = owl_out.read_text()
    assert "CHK_" in content


def test_saved_file_contains_labels(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "lbl_check")
    owl_out = tmp_path / "lbl_check_out.owl"
    c = _curator()
    c.load(str(owl_in))
    c.rename_iris()
    c.save(str(owl_out))
    content = owl_out.read_text()
    assert "label" in content.lower()


# ── curate (one-shot) ─────────────────────────────────────────────────────────

def test_curate_no_imports(tmp_path):
    """curate() without external imports still renames and saves."""
    owl_in  = _make_minimal_owl(tmp_path, "curate_in")
    owl_out = tmp_path / "curate_out.owl"
    c = OWLCurator(base_iri="http://example.org/CUR_", id_prefix="CUR", id_start=1)
    c.curate(
        input_file=str(owl_in),
        output_file=str(owl_out),
        import_bfo=False,
        import_ro=False,
        import_obi=False,
    )
    assert owl_out.exists()
    content = owl_out.read_text()
    assert "CUR_" in content


def test_existing_label_not_overwritten(tmp_path):
    """
    If a class already carries an rdfs:label (set by OWLExporter),
    rename_iris() must keep it rather than replacing it with _name_to_label().
    """
    owl_path = tmp_path / "prelabelled.owl"
    onto = get_ontology("http://test.org/prelabelled/")
    with onto:
        cls = python_types.new_class("Hsgi_Hydrogel", (Thing,))
        cls.label = ["HSGI Hydrogel"]   # original casing, set by exporter
    onto.save(file=str(owl_path), format="rdfxml")

    c = _curator(base_iri="http://example.org/PLB_", prefix="PLB")
    c.load(str(owl_path))
    c.rename_iris()

    renamed = list(c._onto.classes())
    assert renamed, "No classes found after rename"
    label_val = renamed[0].label.first()
    assert label_val == "HSGI Hydrogel", (
        f"Pre-set label was overwritten; got '{label_val}'"
    )


def test_curated_owl_differs_from_source(tmp_path):
    """The curated file must differ from the original (IRIs were changed)."""
    owl_in  = _make_minimal_owl(tmp_path, "diff_test")
    owl_out = tmp_path / "diff_out.owl"
    original = owl_in.read_text()
    c = OWLCurator(base_iri="http://example.org/DIF_", id_prefix="DIF", id_start=1)
    c.curate(str(owl_in), str(owl_out), import_bfo=False, import_ro=False)
    curated = owl_out.read_text()
    assert original != curated
