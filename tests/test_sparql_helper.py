"""
Unit tests for SPARQLHelper — including the new label_of / iri_of_label methods.
"""
import pytest
from rdflib import Graph, URIRef, Literal, RDF, RDFS, OWL
from rdflib.namespace import XSD

from wound_ontology.graph.sparql_helper import SPARQLHelper

EX = "http://example.org/test/"


def _build_graph() -> Graph:
    g = Graph()
    wound = URIRef(EX + "Wound")
    chronic = URIRef(EX + "ChronicWound")
    g.add((wound,   RDF.type,       OWL.Class))
    g.add((wound,   RDFS.label,     Literal("Wound",         lang="en")))
    g.add((chronic, RDF.type,       OWL.Class))
    g.add((chronic, RDFS.label,     Literal("Chronic wound", lang="en")))
    g.add((chronic, RDFS.subClassOf, wound))
    return g


@pytest.fixture
def sq() -> SPARQLHelper:
    return SPARQLHelper(_build_graph())


# ── Construction ──────────────────────────────────────────────────────────────

def test_accepts_rdflib_graph():
    g = Graph()
    helper = SPARQLHelper(g)
    assert helper is not None


def test_rejects_unknown_type():
    with pytest.raises(TypeError):
        SPARQLHelper("not a graph")


# ── label_of ─────────────────────────────────────────────────────────────────

def test_label_of_returns_string(sq):
    lbl = sq.label_of(EX + "Wound")
    assert lbl == "Wound"


def test_label_of_prefers_lang_tag(sq):
    g = Graph()
    iri = URIRef(EX + "Thing")
    g.add((iri, RDFS.label, Literal("Thing", lang="de")))
    g.add((iri, RDFS.label, Literal("Thing EN", lang="en")))
    lbl = SPARQLHelper(g).label_of(str(iri), lang="en")
    assert lbl == "Thing EN"


def test_label_of_falls_back_to_any_lang(sq):
    g = Graph()
    iri = URIRef(EX + "German")
    g.add((iri, RDFS.label, Literal("Wunde", lang="de")))
    lbl = SPARQLHelper(g).label_of(str(iri), lang="en")
    assert lbl == "Wunde"


def test_label_of_missing_returns_none(sq):
    lbl = sq.label_of(EX + "Nonexistent")
    assert lbl is None


def test_label_of_chronic_wound(sq):
    lbl = sq.label_of(EX + "ChronicWound")
    assert lbl == "Chronic wound"


# ── iri_of_label ──────────────────────────────────────────────────────────────

def test_iri_of_label_exact_match(sq):
    iri = sq.iri_of_label("Wound")
    assert iri is not None
    assert EX + "Wound" in iri


def test_iri_of_label_case_insensitive(sq):
    assert sq.iri_of_label("wound") is not None
    assert sq.iri_of_label("WOUND") is not None
    assert sq.iri_of_label("WoUnD") is not None


def test_iri_of_label_missing_returns_none(sq):
    assert sq.iri_of_label("Nonexistent XYZ") is None


def test_iri_of_label_with_lang_filter(sq):
    result = sq.iri_of_label("Wound", lang="en")
    assert result is not None


def test_iri_of_label_lang_filter_wrong_lang(sq):
    result = sq.iri_of_label("Wound", lang="de")
    assert result is None


# ── Existing named queries ────────────────────────────────────────────────────

def test_all_classes_returns_list(sq):
    classes = sq.all_classes()
    assert isinstance(classes, list)
    assert len(classes) == 2


def test_subclasses_of(sq):
    subs = sq.subclasses_of(EX + "Wound")
    iris = [r["iri"] for r in subs]
    assert EX + "ChronicWound" in iris


def test_superclasses_of(sq):
    supers = sq.superclasses_of(EX + "ChronicWound")
    iris = [r["iri"] for r in supers]
    assert EX + "Wound" in iris


def test_find_by_label(sq):
    results = sq.find_by_label("wound")
    assert len(results) >= 1


def test_add_prefix(sq):
    sq.add_prefix("ex", EX)
    assert "ex" in sq._extra_prefixes


def test_raw_query(sq):
    rows = list(sq.query("SELECT ?s WHERE { ?s a owl:Class . }"))
    assert len(rows) == 2
