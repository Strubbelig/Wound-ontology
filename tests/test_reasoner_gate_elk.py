"""Real ELK runs against the real MILD/WONT skeleton.

Slow (a few seconds per reason call) and needs `robot` on PATH, so it is marked
and excluded from the default suite. It exists because the stubbed tests prove
the *plumbing* and this proves the gate actually catches the errors it claims to.
"""
import shutil

import pytest

from wound_ontology.reasoning.gate import BATCH_NS, ReasonerGate
from wound_ontology.reasoning.skeleton import build_skeleton

pytestmark = [
    pytest.mark.reasoner,
    pytest.mark.skipif(shutil.which("robot") is None, reason="robot not on PATH"),
]

MILD = "https://bioportal.bioontology.org/ontologies/MILD/"


@pytest.fixture(scope="module")
def skeleton(tmp_path_factory):
    from config.settings import GROUND_TRUTH_TTL, MILD_TTL
    out = tmp_path_factory.mktemp("sk") / "skeleton.ttl"
    path, n = build_skeleton(GROUND_TRUTH_TTL, MILD_TTL, out)
    assert n > 1000
    return path


@pytest.fixture(scope="module")
def gate(skeleton):
    return ReasonerGate(skeleton)


def test_skeleton_has_no_baseline_unsatisfiable_classes(gate, skeleton):
    """The whole reason the gate reasons over a skeleton rather than the full
    closure: the closure carries 54 pre-existing unsatisfiable classes."""
    import rdflib
    g = rdflib.Graph(); g.parse(str(skeleton), format="turtle")
    assert gate._unsatisfiable(g) == set()


def test_catches_a_disposition_typed_as_a_material_entity(gate, skeleton):
    """The historical Round-1 error, which survived until a manual audit."""
    import rdflib
    from rdflib import RDF, RDFS, OWL, URIRef
    g = rdflib.Graph(); g.parse(str(skeleton), format="turtle")
    bad = URIRef(BATCH_NS + "wound_infecting_disposition")
    g.add((bad, RDF.type, OWL.Class))
    g.add((bad, RDFS.subClassOf, URIRef("http://purl.obolibrary.org/obo/BFO_0000040")))
    g.add((bad, RDFS.subClassOf, URIRef("http://purl.obolibrary.org/obo/BFO_0000016")))
    assert str(bad) in gate._unsatisfiable(g)


def test_catches_same_category_disjointness_the_schema_cannot(gate):
    """`Wound base` and `Wound edge` are both MaterialEntity but disjoint, so the
    category table cannot reject an edge to both — only a reasoner can."""
    out = gate.check_edges([
        ("Chronic Wound", "Wound"),
        ("Weird Thing", "Wound base"),
        ("Weird Thing", "Wound edge"),
    ])
    assert ("Weird Thing", "Wound base") in out.quarantined
    assert ("Weird Thing", "Wound edge") in out.quarantined
    assert ("Chronic Wound", "Wound") in out.accepted


def test_catches_disorder_versus_predisposition(gate):
    """MILD asserts material disease entity (pathological disorder, its exact
    synonym, was a class of its own until 2026-10-30) and disease
    predisposition disjoint."""
    out = gate.check_edges([
        ("Some Risk Thing", "material disease entity"),
        ("Some Risk Thing", "disease predisposition"),
    ])
    assert len(out.quarantined) == 2
    assert out.accepted == []


def test_a_clean_batch_of_edges_passes(gate):
    out = gate.check_edges([
        ("Chronic Wound", "Wound"),
        ("Novel Dressing", "Wound dressing"),
    ])
    assert out.clean
    assert len(out.accepted) == 2


def test_a_relation_wrong_on_its_own_is_held_back_without_taking_its_neighbours(gate):
    """2026-09-30: `healing --has as process boundary at end--> completely
    healed` (a quality) made `healing` unsatisfiable, and through every
    relation to it, 7,163 classes. The bad sentence alone is held back; the
    good relations on the same hub term are accepted."""
    from wound_ontology.llm.extraction_models import BFOCategory, RelationType

    class E:
        def __init__(self, label, cat):
            self.label, self.category, self.grounded_to = label, cat, None

    class R:
        def __init__(self, s, p, o):
            self.subject, self.predicate, self.object = s, p, o

    ents = [E("healing", BFOCategory.Process), E("completely healed", BFOCategory.Quality),
            E("impaired wound healing", BFOCategory.Process), E("gel", BFOCategory.MaterialEntity)]
    bad = R("healing", RelationType.HAS_AS_PROCESS_BOUNDARY_AT_END, "completely healed")
    good1 = R("impaired wound healing", RelationType.PART_OF, "healing")
    good2 = R("gel", RelationType.PARTICIPATES_IN, "impaired wound healing")
    res = gate.check(ents, [bad, good1, good2])
    assert bad in res.quarantined_relations
    assert good1 in res.accepted_relations and good2 in res.accepted_relations
