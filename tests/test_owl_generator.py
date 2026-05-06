"""
Unit tests for ABoxGenerator.
TBoxGenerator (rdflib-based) was removed — TBox is now owlready2-only.
"""
import pytest
from pathlib import Path

from rdflib import Graph, URIRef, Literal, RDF, RDFS, OWL
from rdflib.namespace import XSD

from wound_ontology.tbox_abox_reasoner.for_rdflib.abox_generator import ABoxGenerator

EX = "http://example.org/test/"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _iri(local: str) -> URIRef:
    return URIRef(EX + local)


def _has_triple(g: Graph, s, p, o) -> bool:
    return (s, p, o) in g


class TestABoxGenerator:

    def test_add_individual_declares_named_individual(self):
        gen = ABoxGenerator()
        iri = _iri("patient1")
        gen.add_individual(iri, "Patient 1")
        assert _has_triple(gen.graph, iri, RDF.type, OWL.NamedIndividual)

    def test_add_individual_sets_label(self):
        gen = ABoxGenerator()
        iri = _iri("patient1")
        gen.add_individual(iri, "Patient 1")
        labels = list(gen.graph.objects(iri, RDFS.label))
        assert any("Patient 1" in str(l) for l in labels)

    def test_add_individual_with_types(self):
        gen  = ABoxGenerator()
        iri  = _iri("wound1")
        cls1 = _iri("ChronicWound")
        cls2 = _iri("InfectedWound")
        gen.add_individual(iri, "Wound", cls1, cls2)
        assert _has_triple(gen.graph, iri, RDF.type, cls1)
        assert _has_triple(gen.graph, iri, RDF.type, cls2)

    def test_add_individual_without_types(self):
        gen = ABoxGenerator()
        iri = _iri("patient1")
        gen.add_individual(iri, "Patient 1")
        types = [t for t in gen.graph.objects(iri, RDF.type)
                 if t != OWL.NamedIndividual]
        assert types == []

    def test_add_type(self):
        gen = ABoxGenerator()
        ind = _iri("wound1")
        cls = _iri("ChronicWound")
        gen.add_individual(ind, "Wound")
        gen.add_type(ind, cls)
        assert _has_triple(gen.graph, ind, RDF.type, cls)

    def test_add_object_property(self):
        gen  = ABoxGenerator()
        subj = _iri("wound1")
        prop = _iri("hasPatient")
        obj  = _iri("patient1")
        gen.add_individual(subj, "Wound")
        gen.add_individual(obj,  "Patient")
        gen.add_object_property(subj, prop, obj)
        assert _has_triple(gen.graph, subj, prop, obj)

    def test_add_data_property_plain_literal(self):
        gen  = ABoxGenerator()
        subj = _iri("wound1")
        prop = _iri("hasNote")
        gen.add_individual(subj, "Wound")
        gen.add_data_property(subj, prop, "some note")
        vals = list(gen.graph.objects(subj, prop))
        assert any("some note" in str(v) for v in vals)

    def test_add_data_property_with_datatype(self):
        gen  = ABoxGenerator()
        subj = _iri("wound1")
        prop = _iri("hasArea")
        gen.add_individual(subj, "Wound")
        gen.add_data_property(subj, prop, 42.5, datatype=XSD.float)
        vals = list(gen.graph.objects(subj, prop))
        assert len(vals) == 1
        assert float(str(vals[0])) == pytest.approx(42.5)

    def test_add_individual_returns_iri(self):
        gen = ABoxGenerator()
        iri = _iri("patient1")
        result = gen.add_individual(iri, "Patient 1")
        assert result == iri

    def test_save_creates_file(self, tmp_path):
        gen = ABoxGenerator()
        gen.add_individual(_iri("patient1"), "Patient 1")
        out = tmp_path / "abox.owl"
        gen.save(str(out))
        assert out.exists()
        assert out.stat().st_size > 0

    def test_saved_abox_is_valid_rdf(self, tmp_path):
        gen = ABoxGenerator()
        gen.add_individual(_iri("patient1"), "Patient 1")
        out = tmp_path / "abox.owl"
        gen.save(str(out))
        g2 = Graph()
        g2.parse(str(out), format="xml")
        assert len(g2) > 0

    def test_multiple_individuals(self):
        gen = ABoxGenerator()
        for i in range(5):
            gen.add_individual(_iri(f"ind{i}"), f"Individual {i}")
        individuals = list(gen.graph.subjects(RDF.type, OWL.NamedIndividual))
        assert len(individuals) == 5


