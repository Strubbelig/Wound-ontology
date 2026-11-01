"""2026-10-03: BFO whole and right in the hierarchy; read relations only in the export.

Curator: "why the heck is role under quality. BFO is the top onto of WONT ...
every bfo class should be in there and with correct hierarchy."
"""
import rdflib
import pytest
from rdflib import OWL, RDF, RDFS, URIRef

from wound_ontology.hierarchies.curated_seed import bfo_edges, default_curated_sources, module_ancestry
from wound_ontology.reasoning.skeleton import add_bfo_and_relation_axioms

O = "http://purl.obolibrary.org/obo/"


def test_the_hierarchy_gets_all_of_bfo_with_role_under_realizable_entity():
    _, modules = default_curated_sources()
    df = bfo_edges(modules)
    pairs = set(map(tuple, df.values))
    assert ("role", "realizable entity") in pairs
    assert ("role", "quality") not in pairs
    assert ("disposition", "realizable entity") in pairs
    assert ("function", "disposition") in pairs
    assert ("object", "material entity") in pairs and ("site", "immaterial entity") in pairs
    assert ("information entity", "generically dependent continuant") in pairs
    assert ("tendency", "realizable entity") in pairs
    children = {c for c, _ in pairs}
    assert len(children) >= 37          # 35 BFO children of BFO + the two non-BFO categories


def _module(tmp_path):
    """BFO role and quality, plus ChEBI's `role` filed under PATO's `quality`
    (what obi_module states)."""
    g = rdflib.Graph()
    def cls(i, label, parent=None):
        u = URIRef(O + i); g.add((u, RDF.type, OWL.Class)); g.add((u, RDFS.label, rdflib.Literal(label)))
        if parent:
            g.add((u, RDFS.subClassOf, URIRef(O + parent)))
    cls("BFO_0000017", "realizable entity")
    cls("BFO_0000023", "role", "BFO_0000017")
    cls("BFO_0000019", "quality")
    cls("PATO_0000001", "quality", "BFO_0000019")
    cls("CHEBI_50906", "role", "PATO_0000001")
    cls("CHEBI_33281", "antimicrobial agent", "CHEBI_50906")
    p = tmp_path / "m.ttl"; g.serialize(p, format="turtle")
    return p


def test_a_namesake_of_a_bfo_class_does_not_bring_its_parents(tmp_path):
    df = module_ancestry([O + "CHEBI_33281"], [_module(tmp_path)])
    pairs = set(map(tuple, df.values))
    assert ("antimicrobial agent", "role") in pairs       # hangs on the Role node
    assert ("role", "quality") not in pairs                # but ChEBI role's parent is not BFO role's


def test_the_skeleton_takes_domains_and_ranges_from_the_modules(tmp_path):
    from rdflib import BNode
    from rdflib.collection import Collection
    m = rdflib.Graph()
    hq = URIRef(O + "RO_0000086")
    m.add((hq, RDFS.range, URIRef(O + "BFO_0000019")))
    inh = URIRef(O + "BFO_0000197")
    node, lst = BNode(), BNode()
    Collection(m, lst, [URIRef(O + "BFO_0000004"), BNode()])
    m.add((node, OWL.intersectionOf, lst)); m.add((inh, RDFS.range, node))
    conc = URIRef(O + "RO_0000059")
    u, ul = BNode(), BNode()
    Collection(m, ul, [URIRef(O + "BFO_0000015"), URIRef(O + "BFO_0000020")])
    m.add((u, OWL.unionOf, ul)); m.add((conc, RDFS.domain, u))
    p = tmp_path / "m.ttl"; m.serialize(p, format="turtle")
    g = rdflib.Graph()
    rep = add_bfo_and_relation_axioms(g, [p])
    assert (hq, RDFS.range, URIRef(O + "BFO_0000019")) in g
    assert (inh, RDFS.range, URIRef(O + "BFO_0000004")) in g      # the named part of an intersection
    assert rep["weakened_intersection"] == 1
    assert "concretizes domain" in rep["skipped_not_EL"]           # a union is not EL: left out, counted


def test_the_export_refuses_store_and_read_relations_together(tmp_path):
    from wound_ontology.owl.extend import extend_ground_truth
    with pytest.raises(ValueError, match="not both"):
        extend_ground_truth(tmp_path / "gt.ttl", tmp_path / "out.ttl", store=object(), relations=[])


# ── the gate never calls a failed run clean ─────────────────────────────────

def _gate(tmp_path):
    from wound_ontology.reasoning.gate import ReasonerGate
    sk = tmp_path / "sk.ttl"
    g = rdflib.Graph()
    w = URIRef("urn:x#Grade"); c = URIRef("urn:x#Scale")
    g.add((c, RDF.type, OWL.Class)); g.add((w, RDF.type, OWL.NamedIndividual)); g.add((w, RDF.type, c))
    g.serialize(sk, format="turtle")
    return ReasonerGate(str(sk))


def test_an_elk_run_that_ends_without_a_result_raises(tmp_path, monkeypatch):
    import wound_ontology.reasoning.gate as gate_module
    gate = _gate(tmp_path)

    class P:
        returncode = 1
        stdout = ""
        stderr = "ERROR org.obolibrary.robot.ReasonerHelper - The ontology is inconsistent."
    monkeypatch.setattr(gate_module, "_run_robot", lambda *a, **k: P())
    with pytest.raises(RuntimeError, match="nothing can be called clean"):
        gate._unsatisfiable(rdflib.Graph())


def test_a_listed_unsatisfiable_class_is_a_result_not_a_failure(tmp_path, monkeypatch):
    import wound_ontology.reasoning.gate as gate_module
    gate = _gate(tmp_path)

    class P:
        returncode = 1
        stdout = "unsatisfiable: urn:x#A\n"
        stderr = ""
    monkeypatch.setattr(gate_module, "_run_robot", lambda *a, **k: P())
    assert gate._unsatisfiable(rdflib.Graph()) == {"urn:x#A"}


def test_the_edge_graph_carries_no_individuals(tmp_path):
    gate = _gate(tmp_path)
    g = gate.build_edge_graph([("Scale", "Thing")], label_index={})
    assert not list(g.subjects(RDF.type, OWL.NamedIndividual))


def test_the_schema_keeps_has_disposition_and_offers_has_tendency():
    """2026-10-03: WONT's only `has disposition` axioms moved to MILD_120101
    `has tendency`; a usage-derived relation list then dropped `has disposition`
    from extraction although the store holds 102 such relations."""
    from wound_ontology.llm.extraction_models import RELATION_DOMAINS, RELATION_IRI
    assert RELATION_IRI["has disposition"].endswith("RO_0000091")
    assert ("material entity", "disposition") in RELATION_DOMAINS["has disposition"]
    assert ("material entity", "tendency") not in RELATION_DOMAINS["has disposition"]
    assert RELATION_IRI["has tendency"].endswith("MILD_120101")


def test_a_repredicated_cell_reads_under_its_new_predicate():
    """Rule 68: the assertion stays as written; the view reads it as has_tendency."""
    from wound_ontology.store.concept_store import ConceptStore

    class _DM:
        def __init__(self, data): self.data = data
        def load_latest_json(self, name): return self.data if name == "concept_store" else {}
        def save_as_json(self, data, name): pass

    st = ConceptStore(_DM({"1": {"entities": {"Diabetic foot ulcer": {"has_disposition: amputation risk": 1.0}}}}),
                      "concept_store")
    assert st.repredicate_cells({("Diabetic foot ulcer", "has_disposition: amputation risk"): "has_tendency"},
                                by="tendency-not-disposition") == 1
    (_, ents), = list(st.view())
    assert ents["Diabetic foot ulcer"] == {"has_tendency: amputation risk": 1.0}
    assert "has_disposition: amputation risk" in st.dict["1"]["entities"]["Diabetic foot ulcer"]
