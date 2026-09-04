"""Curated seed edges are read back out of WONT + MILD.

The table these edges come from used to be a CSV. It was merged into the
ontologies and nothing read it back, so the curated tier of the
curated > text > fca precedence was empty on every run.
"""
import pandas as pd
import pytest

from wound_ontology.hierarchies.curated_seed import (
    CuratedSeedReport, load_curated_edges, _sniff_format,
)

TTL = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://example.org/> .

ex:Wound        a owl:Class ; rdfs:label "Wound" .
ex:ChronicWound a owl:Class ; rdfs:label "Chronic Wound" ; rdfs:subClassOf ex:Wound .
ex:AcuteWound   a owl:Class ; rdfs:label "Acute Wound"   ; rdfs:subClassOf ex:Wound .
ex:Unlabelled   a owl:Class ; rdfs:subClassOf ex:Wound .
ex:Imported     a owl:Class ; rdfs:label "Imported Child" ; rdfs:subClassOf ex:Elsewhere .
ex:Gone         a owl:Class ; rdfs:label "Gone" ; owl:deprecated true ;
                  rdfs:subClassOf ex:Wound .
ex:Top          a owl:Class ; rdfs:label "Top" ; rdfs:subClassOf owl:Thing .
ex:Restricted   a owl:Class ; rdfs:label "Restricted" ;
                  rdfs:subClassOf [ a owl:Restriction ;
                                    owl:onProperty ex:p ;
                                    owl:someValuesFrom ex:Wound ] .
"""

LEXICON = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://example.org/> .

ex:Elsewhere a owl:Class ; rdfs:label "Elsewhere" ;
               rdfs:subClassOf ex:NeverACuratedEdge .
"""


@pytest.fixture
def onto(tmp_path):
    p = tmp_path / "onto.ttl"
    p.write_text(TTL)
    return p


@pytest.fixture
def lexicon(tmp_path):
    p = tmp_path / "lexicon.ttl"
    p.write_text(LEXICON)
    return p


def test_named_labelled_edges_are_kept(onto):
    df = load_curated_edges([onto])
    pairs = set(map(tuple, df[["Class", "Parent class"]].values))
    assert ("Chronic Wound", "Wound") in pairs
    assert ("Acute Wound", "Wound") in pairs


def test_what_is_dropped_is_counted_not_silent(onto):
    df, rep = load_curated_edges([onto], report=True)
    assert rep.skipped_anonymous == 1      # the owl:Restriction superclass
    assert rep.skipped_deprecated == 1     # ex:Gone
    assert rep.skipped_owl_thing == 1      # ex:Top
    assert rep.skipped_unlabelled == 2     # ex:Unlabelled child, ex:Elsewhere parent
    assert "http://example.org/Elsewhere" in rep.unresolved_iris
    assert rep.kept == len(df) == 2


def test_label_sources_name_imported_parents_without_seeding_their_edges(onto, lexicon):
    df, rep = load_curated_edges([onto], [lexicon], report=True)
    pairs = set(map(tuple, df[["Class", "Parent class"]].values))
    assert ("Imported Child", "Elsewhere") in pairs, "imported parent should resolve"
    assert rep.recovered_labels == 1
    assert rep.skipped_unlabelled == 1      # only ex:Unlabelled remains
    # The lexicon's OWN subsumption must never become a curated edge.
    assert not any(c == "Elsewhere" for c, _ in pairs)


def test_labels_are_pooled_across_sources(tmp_path):
    """A class whose parent is defined in the other file still resolves —
    this is the WONT-class-with-a-MILD-parent case (34 real edges)."""
    a = tmp_path / "a.ttl"
    a.write_text("""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/> .
ex:Child a owl:Class ; rdfs:label "Child" ; rdfs:subClassOf ex:ParentInB .
""")
    b = tmp_path / "b.ttl"
    b.write_text("""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/> .
ex:ParentInB a owl:Class ; rdfs:label "Parent In B" .
""")
    df = load_curated_edges([a, b])
    assert ("Child", "Parent In B") in set(map(tuple, df.values))


def test_a_missing_source_is_refused_not_skipped(tmp_path, onto):
    with pytest.raises(FileNotFoundError, match="outrank"):
        load_curated_edges([onto, tmp_path / "gone.ttl"])


def test_an_empty_result_is_refused_not_returned(tmp_path):
    empty = tmp_path / "empty.ttl"
    empty.write_text("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n")
    with pytest.raises(RuntimeError, match="curated tier is empty"):
        load_curated_edges([empty])


def test_an_unparseable_source_is_refused_not_skipped(tmp_path):
    bad = tmp_path / "bad.ttl"
    bad.write_text("this is not turtle at all <<<>>> ;;;")
    with pytest.raises(RuntimeError, match="could not be parsed"):
        load_curated_edges([bad])


def test_format_is_sniffed_from_content_not_suffix(tmp_path):
    """A .owl holding Turtle and a .owl holding RDF/XML must both be read
    correctly: rdflib's Turtle parser does not reject XML, it ingests the
    header as junk URIs and returns a graph full of garbage."""
    ttl_named_owl = tmp_path / "turtle.owl"
    ttl_named_owl.write_text(TTL)
    assert _sniff_format(ttl_named_owl) == "turtle"

    xml_named_owl = tmp_path / "xml.owl"
    xml_named_owl.write_text(
        '<?xml version="1.0"?>\n'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"\n'
        '         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"\n'
        '         xmlns:owl="http://www.w3.org/2002/07/owl#">\n'
        '  <owl:Class rdf:about="http://example.org/W">\n'
        '    <rdfs:label>W</rdfs:label></owl:Class>\n'
        '  <owl:Class rdf:about="http://example.org/CW">\n'
        '    <rdfs:label>CW</rdfs:label>\n'
        '    <rdfs:subClassOf rdf:resource="http://example.org/W"/></owl:Class>\n'
        '</rdf:RDF>\n'
    )
    assert _sniff_format(xml_named_owl) == "xml"
    assert ("CW", "W") in set(map(tuple, load_curated_edges([xml_named_owl]).values))


def test_edges_reach_the_hierarchy_as_curated(onto):
    """End to end: what the loader returns is what apply_curated stamps."""
    from wound_ontology.hierarchies.base_hierarchy import SOURCE_CURATED, SOURCE_FCA
    from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy

    hier = ClassHierarchy.__new__(ClassHierarchy)
    hier._df = pd.DataFrame(dtype=float)
    hier._prov, hier._candidates = {}, {}
    hier._prov_loaded = True

    n = hier.apply_curated(load_curated_edges([onto]))
    assert n == 2
    assert hier.provenance_summary().get(SOURCE_CURATED) == 2
    # And the precedence actually holds: FCA cannot demote a curated edge.
    assert hier._set_edge("Chronic Wound", "Wound", source=SOURCE_FCA) is False
    assert hier.source_of("Chronic Wound", "Wound") == SOURCE_CURATED


def test_report_summary_names_every_bucket(onto):
    _, rep = load_curated_edges([onto], report=True)
    text = rep.summary()
    for token in ("curated edges", "anonymous", "unlabelled", "deprecated",
                  "owl:Thing", "duplicates"):
        assert token in text
    assert isinstance(rep, CuratedSeedReport)
