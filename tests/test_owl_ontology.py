"""Tests for owl.OWLOntology, OntologyRepository, and OntologyCurator."""

import pytest
from pathlib import Path
import types as python_types

from owlready2 import get_ontology, Thing

from wound_ontology.owl import OWLOntology, OntologyCurator
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy


class MockDM:
    def load_latest_csv(self, _): return None
    def save_as_csv(self, df, _): pass


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def dm(tmp_path):
    from wound_ontology.data_manager.data_manager import DataManager
    return DataManager(base_path=tmp_path)


@pytest.fixture
def class_hier():
    h = ClassHierarchy(MockDM())
    h._set_edge("Chronic Wound", "Wound")
    h._set_edge("Acute Wound",   "Wound")
    h._set_edge("Venous Ulcer",  "Chronic Wound")
    return h


def _onto(iri_suffix="test") -> OWLOntology:
    """Each test needs a unique IRI — owlready2 caches ontologies globally."""
    return OWLOntology.create(iri=f"http://test.org/{iri_suffix}_{id(object())}/")


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


# ── from_hierarchies: file creation ───────────────────────────────────────────

def test_owl_file_is_created(class_hier, dm, tmp_path):
    onto = _onto("file_created")
    OntologyCurator(onto).from_hierarchies(class_hierarchy=class_hier)
    onto.save(dm, str(tmp_path / "test.owl"))
    assert (tmp_path / "test.owl").exists()
    assert (tmp_path / "test.owl").stat().st_size > 0


def test_owl_file_is_valid_rdf(class_hier, dm, tmp_path):
    onto = _onto("valid_rdf")
    OntologyCurator(onto).from_hierarchies(class_hierarchy=class_hier)
    out = tmp_path / "test.owl"
    onto.save(dm, str(out))
    content = _owl_text(out)
    assert "owl" in content.lower()
    assert "rdf" in content.lower()


# ── from_hierarchies: class hierarchy ─────────────────────────────────────────

def test_class_concepts_appear_in_owl(class_hier, dm, tmp_path):
    onto = _onto("class_concepts")
    OntologyCurator(onto).from_hierarchies(class_hierarchy=class_hier)
    out = tmp_path / "test.owl"
    onto.save(dm, str(out))
    content = _owl_text(out)
    assert "Chronic_Wound" in content
    assert "Wound" in content


def test_subclass_axiom_present(class_hier, dm, tmp_path):
    onto = _onto("subclass")
    OntologyCurator(onto).from_hierarchies(class_hierarchy=class_hier)
    out = tmp_path / "test.owl"
    onto.save(dm, str(out))
    assert "subClassOf" in _owl_text(out)


def test_transitive_concept_exported(class_hier, dm, tmp_path):
    onto = _onto("transitive")
    OntologyCurator(onto).from_hierarchies(class_hierarchy=class_hier)
    out = tmp_path / "test.owl"
    onto.save(dm, str(out))
    assert "Venous_Ulcer" in _owl_text(out)


def test_no_hierarchy_produces_minimal_owl(dm, tmp_path):
    onto = OWLOntology.create(iri="http://test.org/empty_onto/")
    OntologyCurator(onto).from_hierarchies()
    out = tmp_path / "empty.owl"
    onto.save(dm, str(out))
    assert out.exists()
    assert "owl" in _owl_text(out).lower()


# ── load ───────────────────────────────────────────────────────────────────────

def test_load_returns_owlontology(dm, tmp_path):
    owl = _make_minimal_owl(tmp_path, "load_self")
    result = OWLOntology.load(str(owl), dm)
    assert isinstance(result, OWLOntology)


def test_load_populates_onto(dm, tmp_path):
    owl = _make_minimal_owl(tmp_path, "load_pop")
    onto = OWLOntology.load(str(owl), dm)
    assert onto.onto is not None
    assert onto.world is not None


# ── rename_iris ────────────────────────────────────────────────────────────────

def test_rename_iris_assigns_new_iri(dm, tmp_path):
    owl  = _make_minimal_owl(tmp_path, "rename_iri")
    onto = OWLOntology.load(
        str(owl), dm,
        base_iri="http://example.org/TST_",
        id_prefix="TST",
        iri=f"http://test.org/ri_{id(object())}/",
    )
    OntologyCurator(onto).rename_iris()
    for cls in onto.onto.classes():
        assert "TST_" in cls.iri, f"Expected TST_ prefix, got {cls.iri}"


def test_rename_iris_assigns_label(dm, tmp_path):
    owl  = _make_minimal_owl(tmp_path, "rename_lbl")
    onto = OWLOntology.load(str(owl), dm)
    OntologyCurator(onto).rename_iris()
    for cls in onto.onto.classes():
        assert cls.label, f"No label assigned to {cls.iri}"


def test_rename_iris_increments_counter(dm, tmp_path):
    owl  = _make_minimal_owl(tmp_path, "rename_ctr")
    onto = OWLOntology.load(
        str(owl), dm,
        base_iri="http://example.org/CTR_",
        id_prefix="CTR",
        id_start=10,
        iri=f"http://test.org/rc_{id(object())}/",
    )
    OntologyCurator(onto).rename_iris()
    ids = sorted(int(cls.iri.split("CTR_")[-1]) for cls in onto.onto.classes())
    assert ids == list(range(10, 10 + len(ids)))


def test_rename_preserves_subclass_structure(dm, tmp_path):
    owl  = _make_minimal_owl(tmp_path, "rename_struct")
    onto = OWLOntology.load(str(owl), dm)
    OntologyCurator(onto).rename_iris()
    has_subclass = any(
        hasattr(parent, "iri") and parent.iri != "http://www.w3.org/2002/07/owl#Thing"
        for cls in onto.onto.classes()
        for parent in cls.is_a
    )
    assert has_subclass, "subClassOf relations lost after IRI renaming"


def test_self_loop_entity_gets_iri(dm, tmp_path):
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
    onto = OWLOntology.load(
        str(owl_path), dm,
        base_iri="http://example.org/SL_",
        id_prefix="SL",
        iri=f"http://test.org/sl_{id(object())}/",
    )
    OntologyCurator(onto).rename_iris()
    assert any("SL_" in cls.iri for cls in onto.onto.classes())


# ── save ──────────────────────────────────────────────────────────────────────

def test_save_creates_file(dm, tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "save_in")
    owl_out = tmp_path / "curated.owl"
    onto    = OWLOntology.load(str(owl_in), dm)
    OntologyCurator(onto).rename_iris()
    onto.save(dm, str(owl_out))
    assert owl_out.exists()
    assert owl_out.stat().st_size > 0


def test_saved_file_contains_new_iris(dm, tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "iri_check")
    owl_out = tmp_path / "iri_check_out.owl"
    onto    = OWLOntology.load(
        str(owl_in), dm,
        base_iri="http://example.org/CHK_",
        id_prefix="CHK",
        iri=f"http://test.org/ic_{id(object())}/",
    )
    OntologyCurator(onto).rename_iris()
    onto.save(dm, str(owl_out))
    assert "CHK_" in owl_out.read_text()


def test_saved_file_contains_labels(dm, tmp_path):
    owl_in  = _make_minimal_owl(tmp_path, "lbl_check")
    owl_out = tmp_path / "lbl_check_out.owl"
    onto    = OWLOntology.load(str(owl_in), dm)
    OntologyCurator(onto).rename_iris()
    onto.save(dm, str(owl_out))
    assert "label" in owl_out.read_text().lower()


def test_existing_label_not_overwritten(dm, tmp_path):
    owl_path = tmp_path / "prelabelled.owl"
    existing = get_ontology("http://test.org/prelabelled/")
    with existing:
        cls = python_types.new_class("Hsgi_Hydrogel", (Thing,))
        cls.label = ["HSGI Hydrogel"]
    existing.save(file=str(owl_path), format="rdfxml")

    onto = OWLOntology.load(
        str(owl_path), dm,
        base_iri="http://example.org/PLB_",
        id_prefix="PLB",
        iri=f"http://test.org/plb_{id(object())}/",
    )
    OntologyCurator(onto).rename_iris()
    renamed = list(onto.onto.classes())
    assert renamed
    assert renamed[0].label.first() == "HSGI Hydrogel"


# ── rdf_graph property ────────────────────────────────────────────────────────

def test_rdf_graph_populated_after_load(dm, tmp_path):
    from rdflib import Graph
    owl  = _make_minimal_owl(tmp_path, "rdf_graph")
    onto = OWLOntology.load(str(owl), dm)
    g    = onto.rdf_graph
    assert isinstance(g, Graph)
    assert len(g) > 0


def test_rdf_graph_lazy_from_hierarchies(class_hier):
    from rdflib import Graph
    onto = _onto("lazy_rdf")
    OntologyCurator(onto).from_hierarchies(class_hierarchy=class_hier)
    g = onto.rdf_graph
    assert isinstance(g, Graph)
    assert len(g) > 0


# ── label_of ──────────────────────────────────────────────────────────────────

def test_label_of_known_label(dm, tmp_path):
    from owlready2 import locstr
    owl_path   = tmp_path / "labelled_onto.owl"
    local_onto = get_ontology("http://test.org/labelled_onto/")
    with local_onto:
        cls = python_types.new_class("Test_Class", (Thing,))
        cls.label = [locstr("Test Class", "en")]
    local_onto.save(file=str(owl_path), format="rdfxml")

    onto = OWLOntology.load(str(owl_path), dm)
    lbl  = onto.label_of("http://test.org/labelled_onto/Test_Class")
    assert lbl == "Test Class"


# ── iri_of_label ──────────────────────────────────────────────────────────────

def test_iri_of_label_reverse_lookup(dm, tmp_path):
    from owlready2 import locstr
    owl_path   = tmp_path / "reverse_onto.owl"
    local_onto = get_ontology("http://test.org/reverse_onto/")
    with local_onto:
        cls = python_types.new_class("Wound_Entity", (Thing,))
        cls.label = [locstr("Wound Entity", "en")]
    local_onto.save(file=str(owl_path), format="rdfxml")

    onto  = OWLOntology.load(str(owl_path), dm)
    found = onto.iri_of_label("Wound Entity")
    assert found is not None
    assert "Wound_Entity" in str(found)


def test_iri_of_label_case_insensitive(dm, tmp_path):
    from owlready2 import locstr
    owl_path   = tmp_path / "case_onto.owl"
    local_onto = get_ontology("http://test.org/case_onto/")
    with local_onto:
        cls = python_types.new_class("CWound", (Thing,))
        cls.label = [locstr("Chronic Wound", "en")]
    local_onto.save(file=str(owl_path), format="rdfxml")

    onto = OWLOntology.load(str(owl_path), dm)
    assert onto.iri_of_label("CHRONIC WOUND") is not None
    assert onto.iri_of_label("chronic wound") is not None


def test_iri_of_label_missing_returns_none(dm, tmp_path):
    owl  = _make_minimal_owl(tmp_path, "missing_label")
    onto = OWLOntology.load(str(owl), dm)
    assert onto.iri_of_label("Nonexistent Concept XYZ") is None


# ── normalize_labels ──────────────────────────────────────────────────────────

def test_normalize_labels_strips_whitespace(dm, tmp_path):
    from owlready2 import locstr
    owl_path   = tmp_path / "whitespace_onto.owl"
    local_onto = get_ontology("http://test.org/whitespace_onto/")
    with local_onto:
        cls = python_types.new_class("SpaceWound", (Thing,))
        cls.label = [locstr("  Chronic   Wound  ", "en")]
    local_onto.save(file=str(owl_path), format="rdfxml")

    onto = OWLOntology.load(str(owl_path), dm)
    OntologyCurator(onto).normalize_labels(strip_whitespace=True)
    assert onto.iri_of_label("Chronic Wound") is not None


def test_normalize_labels_modifies_ontology(dm, tmp_path):
    owl  = _make_minimal_owl(tmp_path, "nl_self")
    onto = OWLOntology.load(str(owl), dm)
    OntologyCurator(onto).normalize_labels()
    assert onto.onto is not None


# ── curated differs from source ────────────────────────────────────────────────

def test_curated_owl_differs_from_source(dm, tmp_path):
    owl_in   = _make_minimal_owl(tmp_path, "diff_test")
    owl_out  = tmp_path / "diff_out.owl"
    original = owl_in.read_text()
    onto = OWLOntology.load(
        str(owl_in), dm,
        base_iri="http://example.org/DIF_",
        id_prefix="DIF",
        iri=f"http://test.org/df_{id(object())}/",
    )
    OntologyCurator(onto).rename_iris()
    onto.save(dm, str(owl_out))
    assert original != owl_out.read_text()
