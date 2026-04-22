"""
Unit tests for OWLGenerator, TBoxGenerator, and ABoxGenerator.
"""
import pytest
from pathlib import Path

from rdflib import Graph, URIRef, Literal, RDF, RDFS, OWL
from rdflib.namespace import XSD

from wound_ontology.export.owl_generator import OWLGenerator
from wound_ontology.export.tbox_generator import TBoxGenerator
from wound_ontology.export.abox_generator import ABoxGenerator

EX = "http://example.org/test/"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _iri(local: str) -> URIRef:
    return URIRef(EX + local)


def _has_triple(g: Graph, s, p, o) -> bool:
    return (s, p, o) in g


# ── TBoxGenerator ─────────────────────────────────────────────────────────────

class TestTBoxGenerator:

    def test_add_class_declares_owl_class(self):
        gen = TBoxGenerator()
        iri = _iri("Wound")
        gen.add_class(iri, "Wound")
        assert _has_triple(gen.graph, iri, RDF.type, OWL.Class)

    def test_add_class_sets_label(self):
        gen = TBoxGenerator()
        iri = _iri("ChronicWound")
        gen.add_class(iri, "Chronic wound")
        labels = list(gen.graph.objects(iri, RDFS.label))
        assert any("Chronic wound" in str(l) for l in labels)

    def test_add_class_with_parent(self):
        gen = TBoxGenerator()
        parent = _iri("Wound")
        child  = _iri("ChronicWound")
        gen.add_class(parent, "Wound")
        gen.add_class(child, "Chronic wound", parent=parent)
        assert _has_triple(gen.graph, child, RDFS.subClassOf, parent)

    def test_add_class_without_parent_no_subclass(self):
        gen = TBoxGenerator()
        iri = _iri("Wound")
        gen.add_class(iri, "Wound")
        assert not list(gen.graph.objects(iri, RDFS.subClassOf))

    def test_add_subclass_of(self):
        gen = TBoxGenerator()
        parent = _iri("Wound")
        child  = _iri("SurgicalWound")
        gen.add_class(parent, "Wound")
        gen.add_class(child,  "Surgical wound")
        gen.add_subclass_of(child, parent)
        assert _has_triple(gen.graph, child, RDFS.subClassOf, parent)

    def test_add_some_values_from_creates_restriction(self):
        gen  = TBoxGenerator()
        cls  = _iri("Wound")
        prop = _iri("locatedIn")
        fill = _iri("Skin")
        gen.add_class(cls, "Wound")
        restr = gen.add_some_values_from(cls, prop, fill)
        # Restriction blank node should be typed owl:Restriction
        assert _has_triple(gen.graph, restr, RDF.type, OWL.Restriction)
        assert _has_triple(gen.graph, restr, OWL.onProperty, prop)
        assert _has_triple(gen.graph, restr, OWL.someValuesFrom, fill)
        # Class linked to restriction
        assert _has_triple(gen.graph, cls, RDFS.subClassOf, restr)

    def test_add_all_values_from(self):
        gen  = TBoxGenerator()
        cls  = _iri("Wound")
        prop = _iri("locatedIn")
        fill = _iri("Skin")
        gen.add_class(cls, "Wound")
        restr = gen.add_all_values_from(cls, prop, fill)
        assert _has_triple(gen.graph, restr, OWL.allValuesFrom, fill)

    def test_add_has_value(self):
        gen  = TBoxGenerator()
        cls  = _iri("Wound")
        prop = _iri("stage")
        val  = _iri("StageII")
        restr = gen.add_has_value(cls, prop, val)
        assert _has_triple(gen.graph, restr, OWL.hasValue, val)

    def test_add_union_restriction(self):
        gen    = TBoxGenerator()
        cls    = _iri("Wound")
        prop   = _iri("hasPart")
        fillers = [_iri("Skin"), _iri("Fascia"), _iri("Muscle")]
        gen.add_class(cls, "Wound")
        restr = gen.add_union_restriction(cls, prop, fillers)
        assert _has_triple(gen.graph, restr, RDF.type, OWL.Restriction)
        assert _has_triple(gen.graph, cls, RDFS.subClassOf, restr)
        # union blank node must be referenced
        union_node = next(gen.graph.objects(restr, OWL.someValuesFrom), None)
        assert union_node is not None
        assert next(gen.graph.objects(union_node, OWL.unionOf), None) is not None

    def test_add_union_restriction_all_type(self):
        gen  = TBoxGenerator()
        cls  = _iri("Wound")
        prop = _iri("hasPart")
        restr = gen.add_union_restriction(cls, prop, [_iri("A"), _iri("B")],
                                          restriction_type="all")
        assert next(gen.graph.objects(restr, OWL.allValuesFrom), None) is not None

    def test_add_intersection_restriction(self):
        gen  = TBoxGenerator()
        cls  = _iri("Wound")
        prop = _iri("hasPart")
        restr = gen.add_intersection_restriction(cls, prop, [_iri("A"), _iri("B")])
        inter = next(gen.graph.objects(restr, OWL.someValuesFrom), None)
        assert next(gen.graph.objects(inter, OWL.intersectionOf), None) is not None

    def test_add_class_returns_iri(self):
        gen = TBoxGenerator()
        iri = _iri("Wound")
        result = gen.add_class(iri, "Wound")
        assert result == iri

    def test_label_of_from_own_graph(self):
        gen = TBoxGenerator()
        iri = _iri("Wound")
        gen.add_class(iri, "Wound")
        assert gen.label_of(iri) == "Wound"

    def test_label_of_missing_returns_none(self):
        gen = TBoxGenerator()
        assert gen.label_of(_iri("Unknown")) is None

    def test_save_creates_file(self, tmp_path):
        gen = TBoxGenerator()
        gen.add_class(_iri("Wound"), "Wound")
        out = tmp_path / "tbox.owl"
        gen.save(str(out))
        assert out.exists()
        assert out.stat().st_size > 0

    def test_saved_file_is_valid_rdf(self, tmp_path):
        gen = TBoxGenerator()
        gen.add_class(_iri("Wound"), "Wound")
        out = tmp_path / "tbox.owl"
        gen.save(str(out))
        g2 = Graph()
        g2.parse(str(out), format="xml")
        assert len(g2) > 0

    def test_rdf_list_has_correct_members(self):
        gen   = TBoxGenerator()
        items = [_iri("A"), _iri("B"), _iri("C")]
        head  = gen._make_rdf_list(items)
        collected = []
        node = head
        while node and node != RDF.nil:
            first = next(gen.graph.objects(node, RDF.first), None)
            if first:
                collected.append(first)
            node = next(gen.graph.objects(node, RDF.rest), RDF.nil)
        assert collected == items

    def test_empty_rdf_list_returns_nil(self):
        gen  = TBoxGenerator()
        head = gen._make_rdf_list([])
        assert head == RDF.nil


# ── ABoxGenerator ─────────────────────────────────────────────────────────────

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


# ── Combined TBox + ABox ──────────────────────────────────────────────────────

class TestCombinedGenerators:

    def test_shared_graph(self):
        """TBoxGenerator and ABoxGenerator can write into the same graph."""
        g    = Graph()
        tbox = TBoxGenerator(graph=g)
        abox = ABoxGenerator(graph=g)

        wound_cls = _iri("Wound")
        wound_ind = _iri("wound1")

        tbox.add_class(wound_cls, "Wound")
        abox.add_individual(wound_ind, "Wound of patient 1", wound_cls)

        assert _has_triple(g, wound_cls, RDF.type, OWL.Class)
        assert _has_triple(g, wound_ind, RDF.type, OWL.NamedIndividual)
        assert _has_triple(g, wound_ind, RDF.type, wound_cls)

    def test_tbox_and_abox_round_trip(self, tmp_path):
        """A file written by TBoxGenerator is readable and contains expected IRIs."""
        tbox = TBoxGenerator()
        cls  = _iri("Wound")
        tbox.add_class(cls, "Wound")
        out = tmp_path / "combined.owl"
        tbox.save(str(out))

        g2 = Graph()
        g2.parse(str(out), format="xml")
        assert (cls, RDF.type, OWL.Class) in g2
