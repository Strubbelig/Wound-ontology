"""Terms defined in an import must resolve to their real IRI, not be minted.

``extend_ground_truth`` built its label index from the ground truth alone, so
anything whose IRI lives in an import — BFO_0000034 "function", IAO_0000033,
MILD_120092 — looked unknown and got a freshly minted WONT twin, complete with
the "no BFO anchor, not usable as ground truth" note. Harmless while nothing
curated reached ``class_hier``; once curated seed edges did, it minted 67
duplicates of classes the output already ``owl:imports``.
"""
import pandas as pd
import pytest
import rdflib

from wound_ontology.hierarchies.base_hierarchy import SOURCE_CURATED
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.owl.extend import (
    default_lexicon, extend_ground_truth, label_index,
)

GROUND_TRUTH = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wont: <https://bioportal.bioontology.org/ontologies/WONT/> .

wont:WONT_0000001 a owl:Class ; rdfs:label "Wound" .
wont:WONT_0000002 a owl:Class ; rdfs:label "Chronic Wound" ;
                  rdfs:subClassOf wont:WONT_0000001 .
"""

# Stands in for bfo_module.owl / mild.ttl: defines the label, and
# is imported by the ground truth rather than part of it.
#
# The lexicon tier is exercised with IAO_0000030, NOT with BFO_0000040. Since
# rule 25 the fifteen BFO category names are spelled exactly as BFO labels them,
# so `material entity` is DECLARED and resolves before the lexicon is ever
# consulted -- a test using it would be testing the wrong tier and would pass
# for the wrong reason. `information content entity` is an ordinary imported
# class: it is IAO_0000030, not the `information entity` category (BFO_0000031).
LEXICON = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo:  <http://purl.obolibrary.org/obo/> .

obo:IAO_0000030 a owl:Class ; rdfs:label "information content entity" .
obo:BFO_0000040 a owl:Class ; rdfs:label "material entity" .
"""


@pytest.fixture
def gt(tmp_path):
    p = tmp_path / "gt.ttl"
    p.write_text(GROUND_TRUTH)
    return p


@pytest.fixture
def lexicon(tmp_path):
    p = tmp_path / "lexicon.ttl"
    p.write_text(LEXICON)
    return p


def _hier(edges):
    h = ClassHierarchy.__new__(ClassHierarchy)
    h._df = pd.DataFrame(dtype=float)
    h._prov, h._candidates = {}, {}
    h._prov_loaded = True
    h.apply_curated(pd.DataFrame(edges, columns=["Class", "Parent class"]))
    return h


def test_an_imported_parent_resolves_instead_of_minting(gt, lexicon, tmp_path):
    hier = _hier([{"Class": "Wound", "Parent class": "information content entity"}])
    rep = extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                              class_hier=hier, lexicon=[lexicon])
    assert rep.minted == {}, f"should mint nothing, minted {rep.minted}"
    assert rep.resolved_imported.get("Information Content Entity") == \
        "http://purl.obolibrary.org/obo/IAO_0000030"


def test_without_a_lexicon_it_still_mints_the_duplicate(gt, tmp_path):
    """Pinning the behaviour the lexicon exists to prevent, so a regression here
    is visible rather than showing up as a bigger ontology."""
    hier = _hier([{"Class": "Wound", "Parent class": "information content entity"}])
    rep = extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                              class_hier=hier, lexicon=())
    assert "Information Content Entity" in rep.minted
    assert rep.resolved_imported == {}


def test_an_imported_class_is_not_ours_to_edit(gt, lexicon, tmp_path):
    """An edge whose CHILD is imported must be withheld, exactly as one whose
    child is a curated WONT class is. Resolving must not make IAO writable."""
    hier = _hier([{"Class": "information content entity", "Parent class": "Wound"}])
    out = tmp_path / "out.ttl"
    rep = extend_ground_truth(ground_truth=gt, output=out,
                              class_hier=hier, lexicon=[lexicon])
    assert ("Information Content Entity", "is_a", "Wound") in rep.withheld_existing
    assert rep.subclass_added == 0
    g = rdflib.Graph()
    g.parse(str(out), format="turtle")
    iao = rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000030")
    assert list(g.objects(iao, rdflib.RDFS.subClassOf)) == []


def test_a_category_is_not_ours_to_edit_either(gt, lexicon, tmp_path):
    """The same, for a class reached by declaration rather than by lookup.

    Declaring a category adds its IRI to the untouchable set, so an extraction
    run cannot hang an axiom on BFO_0000040 -- rule 3 covers what rule 20
    resolves.
    """
    hier = _hier([{"Class": "material entity", "Parent class": "Wound"}])
    out = tmp_path / "out.ttl"
    rep = extend_ground_truth(ground_truth=gt, output=out,
                              class_hier=hier, lexicon=[lexicon])
    assert ("Material Entity", "is_a", "Wound") in rep.withheld_existing
    assert rep.subclass_added == 0
    g = rdflib.Graph()
    g.parse(str(out), format="turtle")
    bfo = rdflib.URIRef("http://purl.obolibrary.org/obo/BFO_0000040")
    assert list(g.objects(bfo, rdflib.RDFS.subClassOf)) == []


def test_genuinely_new_terms_are_still_minted(gt, lexicon, tmp_path):
    """The lexicon must not suppress minting for terms nothing defines."""
    hier = _hier([{"Class": "Novel Dressing", "Parent class": "Wound"}])
    rep = extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                              class_hier=hier, lexicon=[lexicon])
    assert "Novel Dressing" in rep.minted
    assert rep.subclass_added == 1


def test_the_ground_truth_still_wins_over_the_lexicon(gt, tmp_path):
    """A label defined in both resolves to the ground truth's own IRI."""
    clash = tmp_path / "clash.ttl"
    clash.write_text("""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
obo:SOMETHING_1 a owl:Class ; rdfs:label "Wound" .
""")
    hier = _hier([{"Class": "Novel Dressing", "Parent class": "Wound"}])
    rep = extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                              class_hier=hier, lexicon=[clash])
    assert "Wound" not in rep.resolved_imported
    assert rep.resolved.get("Wound", "").endswith("WONT_0000001")


def test_a_missing_lexicon_file_is_refused_not_skipped(gt, tmp_path):
    with pytest.raises(FileNotFoundError, match="minted as a WONT duplicate"):
        extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                            class_hier=_hier([{"Class": "A", "Parent class": "B"}]),
                            lexicon=[tmp_path / "nope.ttl"])


def test_default_lexicon_points_at_what_the_output_imports():
    names = {p.name for p in default_lexicon()}
    if not names:
        pytest.skip("MILD / modules not present in this checkout")
    assert "mild.ttl" in names
    assert any(n.endswith("_module.owl") for n in names)


def test_summary_reports_imported_resolutions(gt, lexicon, tmp_path):
    hier = _hier([{"Class": "Wound", "Parent class": "information content entity"}])
    rep = extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                              class_hier=hier, lexicon=[lexicon])
    assert "resolved imported 1" in rep.summary()


def test_curated_edges_survive_the_round_trip(gt, lexicon, tmp_path):
    """The provenance stamp is what makes an edge withheld-worthy downstream."""
    hier = _hier([{"Class": "Chronic Wound", "Parent class": "Wound"}])
    assert hier.source_of("Chronic Wound", "Wound") == SOURCE_CURATED
    rep = extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                              class_hier=hier, lexicon=[lexicon])
    assert ("Chronic Wound", "is_a", "Wound") in rep.withheld_existing


def test_a_category_in_the_lexicon_is_still_declared_not_matched(gt, lexicon, tmp_path):
    """Rule 25 made the category names identical to BFO's labels, which means the
    lexicon can now match one. It must not get the chance.

    Declaring and matching would reach the same IRI here, so nothing visibly
    breaks either way -- which is exactly why it is pinned: the whole point of
    rule 20 is that a closed vocabulary with a known IRI is never put through a
    lookup, however good that lookup has become.
    """
    hier = _hier([{"Class": "Wound", "Parent class": "material entity"}])
    rep = extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                              class_hier=hier, lexicon=[lexicon])
    assert rep.resolved_category.get("Material Entity") == \
        "http://purl.obolibrary.org/obo/BFO_0000040"
    assert "Material Entity" not in rep.resolved_imported
    assert "Material Entity" not in rep.minted


def test_a_category_resolves_even_with_no_lexicon_at_all(gt, tmp_path):
    """The declaration is the source, so an empty lexicon changes nothing."""
    hier = _hier([{"Class": "Wound", "Parent class": "material entity"}])
    rep = extend_ground_truth(ground_truth=gt, output=tmp_path / "out.ttl",
                              class_hier=hier, lexicon=())
    assert rep.resolved_category.get("Material Entity") == \
        "http://purl.obolibrary.org/obo/BFO_0000040"
    assert rep.minted == {}
