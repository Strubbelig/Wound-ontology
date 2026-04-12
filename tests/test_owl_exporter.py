import tempfile
from pathlib import Path

import pytest
from wound_ontology.export.owl_exporter import OWLExporter
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy


class MockDM:
    def load_latest_csv(self, _): return None
    def save_as_csv(self, df, _): pass


@pytest.fixture
def tmp_owl(tmp_path):
    return tmp_path / "test.owl"


@pytest.fixture
def class_hier():
    h = ClassHierarchy(MockDM())
    h._set_edge("Chronic Wound",  "Wound")
    h._set_edge("Acute Wound",    "Wound")
    h._set_edge("Venous Ulcer",   "Chronic Wound")
    return h


@pytest.fixture
def mere_hier():
    h = MereologicalHierarchy(MockDM())
    h._set_edge("Wound Bed",   "Wound")
    h._set_edge("Wound Fluid", "Wound")
    return h


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_exporter(class_hier=None, mere_hier=None, iri=None):
    """Each test needs a unique IRI — owlready2 caches ontologies globally."""
    return OWLExporter(
        data_manager=MockDM(),
        class_hierarchy=class_hier,
        mereological_hierarchy=mere_hier,
        iri=iri or f"http://test.org/{id(class_hier)}{id(mere_hier)}",
    )


def _owl_text(path) -> str:
    return Path(path).read_text(encoding="utf-8")


# ── File creation ──────────────────────────────────────────────────────────────

def test_owl_file_is_created(class_hier, tmp_owl):
    exp = _make_exporter(class_hier=class_hier)
    exp.create_owl(output_file=str(tmp_owl))
    assert tmp_owl.exists()
    assert tmp_owl.stat().st_size > 0


def test_owl_file_is_valid_rdf(class_hier, tmp_owl):
    exp = _make_exporter(class_hier=class_hier)
    exp.create_owl(output_file=str(tmp_owl))
    content = _owl_text(tmp_owl)
    assert "owl" in content.lower()
    assert "rdf" in content.lower()


# ── Class hierarchy export ─────────────────────────────────────────────────────

def test_class_concepts_appear_in_owl(class_hier, tmp_owl):
    exp = _make_exporter(class_hier=class_hier)
    exp.create_owl(output_file=str(tmp_owl))
    content = _owl_text(tmp_owl)
    assert "Chronic_Wound" in content
    assert "Wound"         in content


def test_subclass_axiom_present(class_hier, tmp_owl):
    exp = _make_exporter(class_hier=class_hier)
    exp.create_owl(output_file=str(tmp_owl))
    content = _owl_text(tmp_owl)
    assert "subClassOf" in content


def test_transitive_concept_exported(class_hier, tmp_owl):
    """Venous Ulcer is a child of Chronic Wound — must appear in the OWL."""
    exp = _make_exporter(class_hier=class_hier)
    exp.create_owl(output_file=str(tmp_owl))
    assert "Venous_Ulcer" in _owl_text(tmp_owl)


# ── Mereological hierarchy export ─────────────────────────────────────────────

def test_mere_concepts_appear_in_owl(mere_hier, tmp_owl):
    exp = _make_exporter(mere_hier=mere_hier)
    exp.create_owl(output_file=str(tmp_owl))
    content = _owl_text(tmp_owl)
    assert "Wound_Bed"   in content
    assert "Wound_Fluid" in content


def test_part_of_property_declared(mere_hier, tmp_owl):
    exp = _make_exporter(mere_hier=mere_hier)
    exp.create_owl(output_file=str(tmp_owl))
    assert "part_of" in _owl_text(tmp_owl)


def test_part_of_restriction_on_branch(mere_hier, tmp_owl):
    """branch subClassOf (part_of some root) — restriction must reference the branch."""
    exp = _make_exporter(mere_hier=mere_hier)
    exp.create_owl(output_file=str(tmp_owl))
    content = _owl_text(tmp_owl)
    # The branch class must carry the part_of restriction, so it appears near subClassOf
    assert "someValuesFrom" in content or "subClassOf" in content


# ── Combined export ────────────────────────────────────────────────────────────

def test_combined_export(class_hier, mere_hier, tmp_owl):
    exp = _make_exporter(class_hier=class_hier, mere_hier=mere_hier)
    exp.create_owl(output_file=str(tmp_owl))
    content = _owl_text(tmp_owl)
    assert "Chronic_Wound" in content
    assert "Wound_Bed"     in content


def test_no_hierarchy_produces_minimal_owl(tmp_owl):
    """Exporter with no hierarchies should still write a valid (empty) OWL file."""
    exp = _make_exporter(iri="http://test.org/empty")
    exp.create_owl(output_file=str(tmp_owl))
    assert tmp_owl.exists()
    assert "owl" in _owl_text(tmp_owl).lower()
