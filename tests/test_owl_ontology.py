"""
Unit tests for OWLOntology — covers both build-from-hierarchies (get_data)
and load/curate (load, rename_iris, save) paths.
"""
import pytest
from pathlib import Path
import types as python_types

from owlready2 import get_ontology, Thing

from wound_ontology.tbox_abox_reasoner.for_owl.tbox import TBox as OWLOntology
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy


class MockDM:
    def load_latest_csv(self, _): return None
    def save_as_csv(self, df, _): pass


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def class_hier():
    h = ClassHierarchy(MockDM())
    h._set_edge("Chronic Wound", "Wound")
    h._set_edge("Acute Wound",   "Wound")
    h._set_edge("Venous Ulcer",  "Chronic Wound")
    return h


@pytest.fixture
def mere_hier():
    h = MereologicalHierarchy(MockDM())
    h._set_edge("Wound Bed",   "Wound")
    h._set_edge("Wound Fluid", "Wound")
    return h


def _onto(iri_suffix="test") -> OWLOntology:
    """Each test needs a unique IRI — owlready2 caches ontologies globally."""
    return OWLOntology(iri=f"http://test.org/{iri_suffix}_{id(object())}/")


def _owl_text(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _make_minimal_owl(tmp_path, iri_suffix="onto_test") -> Path:
    """Create a tiny OWL file with three local classes."""
    owl_path = tmp_path / f"{iri_suffix}.owl"
    onto = get_ontology(f"http://test.org/{iri_suffix}/")
    with onto:
        ChronicWound = python_types.new_class("Chronic_Wound", (Thing,))
        AcuteWound   = python_types.new_class("Acute_Wound",   (Thing,))
        Wound        = python_types.new_class("Wound",         (Thing,))
        ChronicWound.is_a.append(Wound)
        AcuteWound.is_a.append(Wound)
    onto.save(file=str(owl_path), format="rdfxml")
    return owl_path


# ── get_data: file creation ────────────────────────────────────────────────────

def test_owl_file_is_created(class_hier, tmp_path):
    onto = _onto("file_created")
    onto.get_data(class_hier)
    onto.save(str(tmp_path / "test.owl"))
    assert (tmp_path / "test.owl").exists()
    assert (tmp_path / "test.owl").stat().st_size > 0


def test_owl_file_is_valid_rdf(class_hier, tmp_path):
    onto = _onto("valid_rdf")
    onto.get_data(class_hier)
    out = tmp_path / "test.owl"
    onto.save(str(out))
    content = _owl_text(out)
    assert "owl" in content.lower()
    assert "rdf" in content.lower()


# ── get_data: class hierarchy ──────────────────────────────────────────────────

def test_class_concepts_appear_in_owl(class_hier, tmp_path):
    onto = _onto("class_concepts")
    onto.get_data(class_hier)
    out = tmp_path / "test.owl"
    onto.save(str(out))
    content = _owl_text(out)
    assert "Chronic_Wound" in content
    assert "Wound" in content


def test_subclass_axiom_present(class_hier, tmp_path):
    onto = _onto("subclass")
    onto.get_data(class_hier)
    out = tmp_path / "test.owl"
    onto.save(str(out))
    assert "subClassOf" in _owl_text(out)


def test_transitive_concept_exported(class_hier, tmp_path):
    onto = _onto("transitive")
    onto.get_data(class_hier)
    out = tmp_path / "test.owl"
    onto.save(str(out))
    assert "Venous_Ulcer" in _owl_text(out)


# ── get_data: mereological hierarchy ──────────────────────────────────────────

def test_mere_concepts_appear_in_owl(mere_hier, tmp_path):
    onto = _onto("mere_concepts")
    onto.get_data(mereological_hierarchy=mere_hier)
    out = tmp_path / "test.owl"
    onto.save(str(out))
    content = _owl_text(out)
    assert "Wound_Bed"   in content
    assert "Wound_Fluid" in content


def test_part_of_property_declared(mere_hier, tmp_path):
    onto = _onto("part_of_decl")
    onto.get_data(mereological_hierarchy=mere_hier)
    out = tmp_path / "test.owl"
    onto.save(str(out))
    assert "part_of" in _owl_text(out)


def test_part_of_restriction_on_branch(mere_hier, tmp_path):
    onto = _onto("part_of_restr")
    onto.get_data(mereological_hierarchy=mere_hier)
    out = tmp_path / "test.owl"
    onto.save(str(out))
    content = _owl_text(out)
    assert "someValuesFrom" in content or "subClassOf" in content


# ── get_data: combined ─────────────────────────────────────────────────────────

def test_combined_export(class_hier, mere_hier, tmp_path):
    onto = _onto("combined")
    onto.get_data(class_hier, mere_hier)
    out = tmp_path / "test.owl"
    onto.save(str(out))
    content = _owl_text(out)
    assert "Chronic_Wound" in content
    assert "Wound_Bed"     in content


def test_no_hierarchy_produces_minimal_owl(tmp_path):
    onto = OWLOntology(iri="http://test.org/empty_onto/")
    onto.get_data()
    out = tmp_path / "empty.owl"
    onto.save(str(out))
    assert out.exists()
    assert "owl" in _owl_text(out).lower()


# ── load ───────────────────────────────────────────────────────────────────────

def test_load_returns_self(tmp_path):
    owl = _make_minimal_owl(tmp_path, "load_self")
    onto = _onto("load_self")
    result = onto.load(str(owl))
    assert result is onto


def test_load_populates_onto(tmp_path):
    owl = _make_minimal_owl(tmp_path, "load_pop")
    onto = _onto("load_pop")
    onto.load(str(owl))
    assert onto._onto is not None
    assert onto._world is not None


# ── rename_iris ────────────────────────────────────────────────────────────────

def test_rename_iris_assigns_new_iri(tmp_path):
    owl = _make_minimal_owl(tmp_path, "rename_iri")
    onto = OWLOntology(
        iri=f"http://test.org/ri_{id(object())}/",
        base_iri="http://example.org/TST_",
        id_prefix="TST",
    )
    onto.load(str(owl))
    onto.rename_iris()
    for cls in onto._onto.classes():
        assert "TST_" in cls.iri, f"Expected TST_ prefix, got {cls.iri}"


def test_rename_iris_assigns_label(tmp_path):
    owl = _make_minimal_owl(tmp_path, "rename_lbl")
    onto = _onto("rename_lbl")
    onto.load(str(owl))
    onto.rename_iris()
    for cls in onto._onto.classes():
        assert cls.label, f"No label assigned to {cls.iri}"


def test_rename_iris_increments_counter(tmp_path):
    owl = _make_minimal_owl(tmp_path, "rename_ctr")
    onto = OWLOntology(
        iri=f"http://test.org/rc_{id(object())}/",
        base_iri="http://example.org/CTR_",
        id_prefix="CTR",
        id_start=10,
    )
    onto.load(str(owl))
    onto.rename_iris()
    ids = sorted(int(cls.iri.split("CTR_")[-1]) for cls in onto._onto.classes())
    assert ids == list(range(10, 10 + len(ids)))


def test_rename_preserves_subclass_structure(tmp_path):
    owl = _make_minimal_owl(tmp_path, "rename_struct")
    onto = _onto("rename_struct")
    onto.load(str(owl))
    onto.rename_iris()
    has_subclass = any(
        hasattr(parent, "iri") and parent.iri != "http://www.w3.org/2002/07/owl#Thing"
        for cls in onto._onto.classes()
        for parent in cls.is_a
    )
    assert has_subclass, "subClassOf relations lost after IRI renaming"


def test_self_loop_entity_gets_iri(tmp_path):
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
    onto = OWLOntology(
        iri=f"http://test.org/sl_{id(object())}/",
        base_iri="http://example.org/SL_",
        id_prefix="SL",
    )
    onto.load(str(owl_path))
    onto.rename_iris()
    assert any("SL_" in cls.iri for cls in onto._onto.classes())


# ── save ──────────────────────────────────────────────────────────────────────

def test_save_creates_file(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "save_in")
    owl_out = tmp_path / "curated.owl"
    onto = _onto("save_in")
    onto.load(str(owl_in))
    onto.rename_iris()
    onto.save(str(owl_out))
    assert owl_out.exists()
    assert owl_out.stat().st_size > 0


def test_saved_file_contains_new_iris(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "iri_check")
    owl_out = tmp_path / "iri_check_out.owl"
    onto = OWLOntology(
        iri=f"http://test.org/ic_{id(object())}/",
        base_iri="http://example.org/CHK_",
        id_prefix="CHK",
    )
    onto.load(str(owl_in))
    onto.rename_iris()
    onto.save(str(owl_out))
    assert "CHK_" in owl_out.read_text()


def test_saved_file_contains_labels(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "lbl_check")
    owl_out = tmp_path / "lbl_check_out.owl"
    onto = _onto("lbl_check")
    onto.load(str(owl_in))
    onto.rename_iris()
    onto.save(str(owl_out))
    assert "label" in owl_out.read_text().lower()


def test_existing_label_not_overwritten(tmp_path):
    owl_path = tmp_path / "prelabelled.owl"
    existing = get_ontology("http://test.org/prelabelled/")
    with existing:
        cls = python_types.new_class("Hsgi_Hydrogel", (Thing,))
        cls.label = ["HSGI Hydrogel"]
    existing.save(file=str(owl_path), format="rdfxml")

    onto = OWLOntology(
        iri=f"http://test.org/plb_{id(object())}/",
        base_iri="http://example.org/PLB_",
        id_prefix="PLB",
    )
    onto.load(str(owl_path))
    onto.rename_iris()
    renamed = list(onto._onto.classes())
    assert renamed
    assert renamed[0].label.first() == "HSGI Hydrogel"


# ── rdf_graph property ────────────────────────────────────────────────────────

def test_rdf_graph_populated_after_load(tmp_path):
    from rdflib import Graph
    owl = _make_minimal_owl(tmp_path, "rdf_graph")
    onto = _onto("rdf_graph")
    onto.load(str(owl))
    g = onto.rdf_graph
    assert isinstance(g, Graph)
    assert len(g) > 0


def test_rdf_graph_lazy_from_get_data(class_hier):
    from rdflib import Graph
    onto = _onto("lazy_rdf")
    onto.get_data(class_hier)
    g = onto.rdf_graph
    assert isinstance(g, Graph)
    assert len(g) > 0


# ── label_of ──────────────────────────────────────────────────────────────────


def test_label_of_known_label(tmp_path):
    """Classes created by owlready2 in _make_minimal_owl have name-derived labels."""
    from rdflib import URIRef
    owl_path = tmp_path / "labelled_onto.owl"
    from owlready2 import get_ontology, Thing, locstr
    import types as python_types
    local_onto = get_ontology("http://test.org/labelled_onto/")
    with local_onto:
        cls = python_types.new_class("Test_Class", (Thing,))
        cls.label = [locstr("Test Class", "en")]
    local_onto.save(file=str(owl_path), format="rdfxml")

    onto = _onto("label_of_known")
    onto.load(str(owl_path))
    lbl = onto.label_of("http://test.org/labelled_onto/Test_Class")
    assert lbl == "Test Class"


# ── iri_of_label ──────────────────────────────────────────────────────────────

def test_iri_of_label_reverse_lookup(tmp_path):
    from rdflib import URIRef
    from owlready2 import get_ontology, Thing, locstr
    import types as python_types
    owl_path = tmp_path / "reverse_onto.owl"
    local_onto = get_ontology("http://test.org/reverse_onto/")
    with local_onto:
        cls = python_types.new_class("Wound_Entity", (Thing,))
        cls.label = [locstr("Wound Entity", "en")]
    local_onto.save(file=str(owl_path), format="rdfxml")

    onto = _onto("reverse_lookup")
    onto.load(str(owl_path))
    found = onto.iri_of_label("Wound Entity")
    assert found is not None
    assert "Wound_Entity" in str(found)


def test_iri_of_label_case_insensitive(tmp_path):
    from owlready2 import get_ontology, Thing, locstr
    import types as python_types
    owl_path = tmp_path / "case_onto.owl"
    local_onto = get_ontology("http://test.org/case_onto/")
    with local_onto:
        cls = python_types.new_class("CWound", (Thing,))
        cls.label = [locstr("Chronic Wound", "en")]
    local_onto.save(file=str(owl_path), format="rdfxml")

    onto = _onto("case_insensitive")
    onto.load(str(owl_path))
    assert onto.iri_of_label("CHRONIC WOUND") is not None
    assert onto.iri_of_label("chronic wound") is not None


def test_iri_of_label_missing_returns_none(tmp_path):
    owl = _make_minimal_owl(tmp_path, "missing_label")
    onto = _onto("missing_label")
    onto.load(str(owl))
    assert onto.iri_of_label("Nonexistent Concept XYZ") is None


# ── normalize_labels ──────────────────────────────────────────────────────────

def test_normalize_labels_strips_whitespace(tmp_path):
    from owlready2 import get_ontology, Thing, locstr
    import types as python_types
    owl_path = tmp_path / "whitespace_onto.owl"
    local_onto = get_ontology("http://test.org/whitespace_onto/")
    with local_onto:
        cls = python_types.new_class("SpaceWound", (Thing,))
        cls.label = [locstr("  Chronic   Wound  ", "en")]
    local_onto.save(file=str(owl_path), format="rdfxml")

    onto = _onto("normalize_ws")
    onto.load(str(owl_path))
    onto.normalize_labels(strip_whitespace=True)

    found = onto.iri_of_label("Chronic Wound")
    assert found is not None


def test_normalize_labels_returns_self(tmp_path):
    owl = _make_minimal_owl(tmp_path, "nl_self")
    onto = _onto("nl_self")
    onto.load(str(owl))
    result = onto.normalize_labels()
    assert result is onto


# ── (existing tests continue) ─────────────────────────────────────────────────

def test_curated_owl_differs_from_source(tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "diff_test")
    owl_out = tmp_path / "diff_out.owl"
    original = owl_in.read_text()
    onto = OWLOntology(
        iri=f"http://test.org/df_{id(object())}/",
        base_iri="http://example.org/DIF_",
        id_prefix="DIF",
    )
    onto.load(str(owl_in))
    onto.rename_iris()
    onto.save(str(owl_out))
    assert original != owl_out.read_text()
