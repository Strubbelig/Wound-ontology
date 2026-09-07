"""The pipeline must extend WONT, not build a parallel ontology beside it.

Until 2026-08-20 ``export_to_owl`` started from an empty ``OWLOntology.create()``
and wrote ``ontology_classes.owl``. Nothing read the ground truth as a base and
nothing merged back, so no run ever produced "WONT plus what the abstracts
taught us". These tests pin the merge, and — more importantly — pin the rule
that curated content is never overwritten by an extraction run.
"""

from __future__ import annotations

import pytest
import rdflib
from rdflib.namespace import OWL, RDF, RDFS

from wound_ontology.owl.extend import (
    WONT_NS,
    RELATION_IRIS,
    existing_ids,
    extend_ground_truth,
    label_index,
    next_free_id,
)

OBO = "http://purl.obolibrary.org/obo/"

GROUND_TRUTH = f"""
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo:  <{OBO}> .
@prefix wont: <{WONT_NS}> .

wont:WONT_0000380 a owl:Class ; rdfs:label "Wound"@en .
wont:WONT_0000382 a owl:Class ; rdfs:label "Wound base"@en ;
    obo:IAO_0000118 "Wound bed"@en .
wont:WONT_0000474 a owl:Class ; rdfs:label "painful"@en .
wont:WONT_120000  a owl:Class ; rdfs:label "wound protection function"@en .
"""


class FakeHier:
    def __init__(self, df):
        self.df = df


class FakeStore:
    def __init__(self, d):
        self.dict = d


@pytest.fixture()
def gt(tmp_path):
    p = tmp_path / "gt.ttl"
    p.write_text(GROUND_TRUTH, encoding="utf-8")
    return p


@pytest.fixture()
def graph(gt):
    g = rdflib.Graph()
    g.parse(str(gt), format="turtle")
    return g


def _hier(pairs):
    import pandas as pd
    children = sorted({c for c, _ in pairs})
    parents = sorted({p for _, p in pairs})
    df = pd.DataFrame(0.0, index=children, columns=parents)
    for c, p in pairs:
        df.at[c, p] = 1.0
    return FakeHier(df)


# ── label resolution ────────────────────────────────────────────────────────

def test_label_index_is_case_insensitive_and_includes_alt_terms(graph):
    idx = label_index(graph)
    assert idx["wound"] == rdflib.URIRef(WONT_NS + "WONT_0000380")
    assert idx["wound bed"] == rdflib.URIRef(WONT_NS + "WONT_0000382")


def test_preferred_label_beats_alt_term(graph):
    idx = label_index(graph)
    assert idx["wound base"] == rdflib.URIRef(WONT_NS + "WONT_0000382")


# ── id minting ──────────────────────────────────────────────────────────────

def test_minting_continues_the_main_series_not_the_1200xx_block(graph):
    """The 1200xx block mirrors MILD. Minting past the global max would jump to
    120001 and abandon the whole main range."""
    assert 120000 in existing_ids(graph)
    assert next_free_id(graph) == 475


def test_minted_ids_never_collide_with_either_series(gt, tmp_path):
    report = extend_ground_truth(
        gt, tmp_path / "out.ttl",
        class_hier=_hier([(f"New Term {i}", "Wound") for i in range(30)]),
    )
    minted = {v.rsplit("_", 1)[-1] for v in report.minted.values()}
    assert "0120000" not in minted
    assert "0000380" not in minted and "0000474" not in minted
    assert len(minted) == len(report.minted)      # no duplicates


# ── the ground truth is ground truth ────────────────────────────────────────

def test_existing_classes_are_never_given_new_parents(gt, tmp_path):
    """An extraction run must not reparent a curated class."""
    report = extend_ground_truth(
        gt, tmp_path / "out.ttl",
        class_hier=_hier([("Wound", "Some Invented Genus")]),
    )
    assert ("Wound", "is_a", "Some Invented Genus") in report.withheld_existing
    g = rdflib.Graph(); g.parse(str(tmp_path / "out.ttl"), format="turtle")
    parents = list(g.objects(rdflib.URIRef(WONT_NS + "WONT_0000380"), RDFS.subClassOf))
    assert parents == []


def test_existing_classes_are_never_given_new_restrictions(gt, tmp_path):
    report = extend_ground_truth(
        gt, tmp_path / "out.ttl",
        store=FakeStore({"1": {"entities": {"Wound": {"has_quality: Chronic": 1.0}}}}),
    )
    assert ("Wound", "has_quality", "Chronic") in report.withheld_existing
    assert report.restrictions_added.get("has_quality", 0) == 0


def test_touch_existing_lifts_the_guard_deliberately(gt, tmp_path):
    report = extend_ground_truth(
        gt, tmp_path / "out.ttl",
        class_hier=_hier([("Wound", "Some Invented Genus")]),
        touch_existing=True,
    )
    assert report.withheld_existing == []
    assert report.subclass_added == 1


def test_refuses_to_overwrite_the_ground_truth_in_place(gt):
    with pytest.raises(ValueError, match="refusing to overwrite"):
        extend_ground_truth(gt, gt)


# ── relations reach OWL on real properties ──────────────────────────────────

def test_each_asserted_relation_is_emitted_on_its_own_ontology_property(gt, tmp_path):
    """Every predicate in the store reaches OWL on the IRI the table names.

    This used to assert ``props == set(RELATION_IRIS.values())``, which only held
    while the table had exactly the four predicates the fixture happened to use.
    The table is now derived from the extractor's 26 relation types, so the
    invariant is per-relation, not whole-table.
    """
    used = {
        "has_quality": "Chronic",
        "occurs_in": "Foot",
        "part_of": "Leg",
        "is_treatment_for": "Nothing",
        "inheres_in": "Patient",
        "has_participant": "Surgeon",
    }
    store = FakeStore({"1": {"entities": {
        "Novel Ulcer": {f"{k}: {v}": 1.0 for k, v in used.items()}}}})
    extend_ground_truth(gt, tmp_path / "out.ttl", store=store)
    g = rdflib.Graph(); g.parse(str(tmp_path / "out.ttl"), format="turtle")
    props = {str(o) for o in g.objects(None, OWL.onProperty)}
    assert props == {RELATION_IRIS[k] for k in used}


def test_part_of_is_bfo_not_a_minted_local_property(gt, tmp_path):
    """The old curator did search_one(iri="*part_of") and minted a local
    property when it found none, so exported mereology pointed at an invented
    IRI no reasoner would recognise."""
    extend_ground_truth(
        gt, tmp_path / "out.ttl", mere_hier=_hier([("New Part", "Wound")]))
    g = rdflib.Graph(); g.parse(str(tmp_path / "out.ttl"), format="turtle")
    props = {str(o) for o in g.objects(None, OWL.onProperty)}
    assert props == {OBO + "BFO_0000050"}


def test_false_valued_edges_are_not_exported(gt, tmp_path):
    store = FakeStore({"1": {"entities": {
        "Novel Ulcer": {"has_quality: Chronic": 0.0}}}})
    report = extend_ground_truth(gt, tmp_path / "out.ttl", store=store)
    assert report.restrictions_added == {}


# ── the relations that have no IRI stay out ─────────────────────────────────

@pytest.mark.parametrize("predicate", ["affects", "caused_by"])
def test_unmappable_predicates_are_reported_not_emitted(gt, tmp_path, predicate):
    """'affects' has no IRI; 'caused_by' is refused by MILD commitment 4.
    Neither may silently become a triple."""
    store = FakeStore({"1": {"entities": {
        "Novel Ulcer": {f"{predicate}: Something": 1.0}}}})
    report = extend_ground_truth(gt, tmp_path / "out.ttl", store=store)
    assert report.skipped_no_iri.get(predicate) == 1
    g = rdflib.Graph(); g.parse(str(tmp_path / "out.ttl"), format="turtle")
    assert set(g.objects(None, OWL.onProperty)) == set()


def test_predicate_map_has_no_iri_free_entries():
    """'affects' has no IRI; 'caused_by' is refused by MILD commitment 4.

    The IRI check allows MILD's own namespace as well as OBO -- MILD mints
    has_a_material_basis and the two process-boundary properties itself.
    """
    assert "affects" not in RELATION_IRIS
    assert "caused_by" not in RELATION_IRIS
    assert all(v.startswith(("http://purl.obolibrary.org/obo/",
                             "https://bioportal.bioontology.org/ontologies/MILD/"))
               for v in RELATION_IRIS.values())


# ── minted classes are marked as uncurated ──────────────────────────────────

def test_minted_classes_carry_provenance_and_are_not_passed_off_as_curated(gt, tmp_path):
    report = extend_ground_truth(
        gt, tmp_path / "out.ttl", class_hier=_hier([("Novel Ulcer", "Wound")]))
    iri = rdflib.URIRef(report.minted["Novel Ulcer"])
    g = rdflib.Graph(); g.parse(str(tmp_path / "out.ttl"), format="turtle")
    source = rdflib.URIRef("http://www.geneontology.org/formats/oboInOwl#source")
    assert str(g.value(iri, source)) == "wound-ontology-pipeline"
    note = str(g.value(iri, rdflib.URIRef(OBO + "IAO_0000116")))
    assert "not curated" in note
    assert (iri, RDF.type, OWL.Class) in g


def test_ground_truth_triples_survive_the_merge(gt, tmp_path):
    before = rdflib.Graph(); before.parse(str(gt), format="turtle")
    extend_ground_truth(
        gt, tmp_path / "out.ttl", class_hier=_hier([("Novel Ulcer", "Wound")]))
    after = rdflib.Graph(); after.parse(str(tmp_path / "out.ttl"), format="turtle")
    assert len(before - after) == 0, "the merge dropped ground-truth triples"


def test_resolved_counts_only_curated_matches(gt, tmp_path):
    """A term matching a class minted moments earlier is not a curated match."""
    report = extend_ground_truth(
        gt, tmp_path / "out.ttl",
        class_hier=_hier([("Novel Ulcer", "Wound"), ("Another", "Novel Ulcer")]))
    assert "Wound" in report.resolved
    assert "Novel Ulcer" not in report.resolved
    assert "Novel Ulcer" in report.minted


# ── the extractor, the cleaner and the exporter must speak one vocabulary ────

def test_export_vocabulary_covers_the_extractor():
    """Every relation two-stage extraction can emit must have an export IRI.

    These were three independent lists. The extractor emitted 26 relation types;
    owl/extend.py exported 4, of which only part_of and has_quality overlapped.
    So 24 types -- inheres_in, has_part, has_participant, realizes, has_output,
    the BFO backbone MILD is built on -- were counted into skipped_no_iri and
    silently absent from every extended artifact.
    """
    from wound_ontology.llm.extraction_adapter import normalize_predicate
    from wound_ontology.llm.extraction_models import RELATION_IRI

    emitted = {normalize_predicate(label) for label in RELATION_IRI}
    missing = sorted(emitted - set(RELATION_IRIS))
    assert missing == [], (
        f"the extractor can emit {missing} but owl/extend.py cannot export them; "
        "they would be counted as skipped_no_iri and lost")


def test_predicate_vocabularies_agree():
    """StoreCleaner deletes any predicate not in ALLOWED_PREDICATES, so a
    predicate missing there never even reaches the exporter."""
    from config.settings import ALLOWED_PREDICATES

    allowed = set(ALLOWED_PREDICATES) - {"is_a"}
    assert allowed - set(RELATION_IRIS) == set(), (
        "ALLOWED_PREDICATES permits a predicate the exporter has no IRI for")
    assert set(RELATION_IRIS) - allowed == set(), (
        "the exporter knows a predicate StoreCleaner would strip from the store")


def test_every_export_iri_is_a_real_ontology_iri():
    assert all(v.startswith(("http://purl.obolibrary.org/obo/",
                             "https://bioportal.bioontology.org/ontologies/MILD/"))
               for v in RELATION_IRIS.values())


# ── BFO categories are declared, never label-matched ─────────────────────────
#
# Every extracted term is typed with one of the BFO categories, and every
# category has an IRI declared in CATEGORY_IRI. Resolving those names through
# the label index half-worked: one-word names matched their BFO label, and the
# CamelCase multi-word ones could not, because normalization folds punctuation
# and plurals but does not split words. Five categories were therefore minted as
# unanchored WONT twins, and on output/owl/wont_extended.ttl 1770 classes hung
# under roots that subclass nothing.

@pytest.mark.parametrize("category,iri", [
    ("MaterialEntity", OBO + "BFO_0000040"),
    ("InformationEntity", OBO + "BFO_0000031"),
    ("ImmaterialEntity", OBO + "BFO_0000141"),
    ("ProcessBoundary", OBO + "BFO_0000035"),
    ("RealizableEntity", OBO + "BFO_0000017"),
    ("Process", OBO + "BFO_0000015"),
])
def test_category_names_resolve_to_their_declared_iri(gt, tmp_path, category, iri):
    out = tmp_path / "out.ttl"
    report = extend_ground_truth(gt, out, class_hier=_hier([("Wound", category)]),
                                 lexicon=())
    assert report.resolved_category[category] == iri
    assert category not in report.minted

    g = rdflib.Graph()
    g.parse(str(out), format="turtle")
    # No WONT twin was minted for the category...
    twins = [s for s, _, o in g.triples((None, RDFS.label, None))
             if str(o) == category and str(s).startswith(WONT_NS)]
    assert twins == []
    # ...and the edge points at the real class.
    assert (rdflib.URIRef(WONT_NS + "WONT_0000380"),
            RDFS.subClassOf, rdflib.URIRef(iri)) in g or report.withheld_existing


def test_the_category_class_is_never_given_a_parent(gt, tmp_path):
    """BFO_0000040 belongs to BFO. An extraction run may not add axioms to it."""
    out = tmp_path / "out.ttl"
    report = extend_ground_truth(
        gt, out, class_hier=_hier([("MaterialEntity", "Wound")]), lexicon=())
    assert ("MaterialEntity", "is_a", "Wound") in report.withheld_existing
    g = rdflib.Graph()
    g.parse(str(out), format="turtle")
    assert list(g.objects(rdflib.URIRef(OBO + "BFO_0000040"), RDFS.subClassOf)) == []


def test_every_category_name_has_a_declared_iri():
    """A category the exporter cannot place is a term it would mint unanchored."""
    from wound_ontology.llm.extraction_models import CATEGORY_PARENT
    from wound_ontology.owl.extend import CATEGORY_IRIS

    missing = sorted(c for c in CATEGORY_PARENT if c.strip().lower() not in CATEGORY_IRIS)
    assert missing == [], f"categories with no export IRI: {missing}"


# ── two terms, one class ─────────────────────────────────────────────────────
#
# Matching folds punctuation and plurals, so terms the hierarchy kept apart can
# arrive at the same IRI, and every axiom on either becomes an axiom on both.
# Measured on the full run: 11 classes were claimed by two terms, and each of
# the 10 classes that ended up under two disjoint BFO branches was one of them
# -- `Bacterial Load` typed Quality meeting `Bacterial Loads` typed
# MaterialEntity. The merge happens after every upstream review, so the run has
# to say it happened.

def test_two_terms_landing_on_one_class_are_reported(gt, tmp_path):
    report = extend_ground_truth(
        gt, tmp_path / "out.ttl",
        class_hier=_hier([("Wound", "Quality"), ("wounds", "MaterialEntity")]),
        lexicon=())
    iri = WONT_NS + "WONT_0000380"
    assert report.folded[iri] == ["wound", "wounds"]
    assert "folded            1 class" in report.summary()


def test_a_term_resolving_to_itself_twice_is_not_a_fold(gt, tmp_path):
    report = extend_ground_truth(
        gt, tmp_path / "out.ttl",
        class_hier=_hier([("Wound", "Quality"), ("Wound", "Process")]),
        lexicon=())
    assert report.folded == {}


def test_folding_is_what_puts_one_class_under_two_categories(gt, tmp_path):
    """The report and the graph have to agree about why the class is incoherent."""
    out = tmp_path / "out.ttl"
    report = extend_ground_truth(
        gt, out,
        class_hier=_hier([("Bacterial Load", "Quality"),
                          ("Bacterial Loads", "MaterialEntity")]),
        lexicon=())
    assert len(report.folded) == 1
    folded_iri = next(iter(report.folded))
    g = rdflib.Graph()
    g.parse(str(out), format="turtle")
    parents = {str(p) for p in g.objects(rdflib.URIRef(folded_iri), RDFS.subClassOf)}
    assert parents == {OBO + "BFO_0000019", OBO + "BFO_0000040"}
