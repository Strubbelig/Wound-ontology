"""Exported subsumption axioms must carry the source that produced them."""
import pandas as pd
import pytest
from rdflib import Graph, Literal, OWL, RDF, RDFS, URIRef

from wound_ontology.hierarchies.base_hierarchy import (
    PROVENANCE_ANNOTATION,
    SOURCE_CURATED,
    SOURCE_FCA,
    SOURCE_TEXT,
)
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.owl.provenance import annotate_file, read_provenance

EX = "http://example.org/"


class MockDM:
    def __init__(self): self.saved = {}
    def load_latest_csv(self, name): return self.saved.get(name)
    def save_as_csv(self, df, name): self.saved[name] = df


@pytest.fixture
def ontology_file(tmp_path):
    g = Graph()
    for name in ("Chronic Wound", "Wound", "Moist Wound"):
        iri = URIRef(EX + name.replace(" ", "_"))
        g.add((iri, RDF.type, OWL.Class))
        g.add((iri, RDFS.label, Literal(name)))
    g.add((URIRef(EX + "Chronic_Wound"), RDFS.subClassOf, URIRef(EX + "Wound")))
    g.add((URIRef(EX + "Chronic_Wound"), RDFS.subClassOf, URIRef(EX + "Moist_Wound")))
    p = tmp_path / "onto.ttl"
    g.serialize(destination=str(p), format="turtle")
    return p


@pytest.fixture
def hier():
    h = ClassHierarchy(MockDM())
    h._set_edge("Chronic Wound", "Wound", source=SOURCE_CURATED)
    h._set_edge("Chronic Wound", "Moist Wound", source=SOURCE_FCA)
    return h


def test_sources_are_written_onto_the_axioms(ontology_file, hier):
    counts = annotate_file(ontology_file, hier, fmt="turtle")
    assert counts[SOURCE_CURATED] == 1
    assert counts[SOURCE_FCA] == 1
    assert counts["unmatched"] == 0


def test_provenance_reads_back(ontology_file, hier):
    annotate_file(ontology_file, hier, fmt="turtle")
    got = {(c.rsplit("/", 1)[-1], p.rsplit("/", 1)[-1], s)
           for c, p, s in read_provenance(ontology_file, fmt="turtle")}
    assert ("Chronic_Wound", "Wound", SOURCE_CURATED) in got
    assert ("Chronic_Wound", "Moist_Wound", SOURCE_FCA) in got


def test_uses_owl_axiom_reification(ontology_file, hier):
    """Protégé/ROBOT read axiom metadata through owl:Axiom, not a bare triple."""
    annotate_file(ontology_file, hier, fmt="turtle")
    g = Graph(); g.parse(str(ontology_file), format="turtle")
    nodes = list(g.subjects(RDF.type, OWL.Axiom))
    assert len(nodes) == 2
    for n in nodes:
        assert (n, OWL.annotatedProperty, RDFS.subClassOf) in g
        assert g.value(n, URIRef(PROVENANCE_ANNOTATION)) is not None


def test_annotation_property_is_declared(ontology_file, hier):
    annotate_file(ontology_file, hier, fmt="turtle")
    g = Graph(); g.parse(str(ontology_file), format="turtle")
    assert (URIRef(PROVENANCE_ANNOTATION), RDF.type, OWL.AnnotationProperty) in g


def test_is_idempotent(ontology_file, hier):
    annotate_file(ontology_file, hier, fmt="turtle")
    second = annotate_file(ontology_file, hier, fmt="turtle")
    assert second.get(SOURCE_CURATED, 0) == 0
    g = Graph(); g.parse(str(ontology_file), format="turtle")
    assert len(list(g.subjects(RDF.type, OWL.Axiom))) == 2


def test_edges_absent_from_the_file_are_reported_not_invented(ontology_file, hier):
    hier._set_edge("Ghost Term", "Wound", source=SOURCE_TEXT)
    counts = annotate_file(ontology_file, hier, fmt="turtle")
    assert counts["unmatched"] == 1


def test_uncommitted_candidates_are_never_exported(ontology_file, hier):
    hier.propose_edge("Chronic Wound", "Ghost Parent", SOURCE_FCA)
    annotate_file(ontology_file, hier, fmt="turtle")
    sources = {s for _, _, s in read_provenance(ontology_file, fmt="turtle")}
    assert sources == {SOURCE_CURATED, SOURCE_FCA}
    assert len(read_provenance(ontology_file, fmt="turtle")) == 2
