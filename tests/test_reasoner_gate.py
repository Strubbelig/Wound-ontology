"""The per-batch reasoner gate (C7).

Round 1 added disjointness axioms; nothing enforced them at extraction time,
which is how `wound infecting disposition ⊑ material entity` survived until a
manual audit. These tests use a stub reasoner so the suite stays fast; the real
ELK path is exercised separately (see test_reasoner_gate_elk.py).
"""
import json

import pytest
import rdflib
from rdflib import OWL, RDF, RDFS, URIRef

from wound_ontology.llm.extraction_models import ExtractionResult
from wound_ontology.reasoning.gate import (
    BATCH_NS,
    _slug,
    EdgeGateResult,
    GateResult,
    ReasonerGate,
)
from wound_ontology.reasoning.skeleton import (
    BFO_DISJOINT,
    BFO_SKELETON,
    build_skeleton,
)

OBO = "http://purl.obolibrary.org/obo/"


@pytest.fixture
def tiny_skeleton(tmp_path):
    """A minimal TBox: two disjoint material siblings under BFO."""
    g = rdflib.Graph()
    for child, parent in BFO_SKELETON.items():
        g.add((URIRef(OBO + child), RDFS.subClassOf, URIRef(OBO + parent)))
    for a, b in BFO_DISJOINT:
        g.add((URIRef(OBO + a), OWL.disjointWith, URIRef(OBO + b)))
    for name in ("Wound Base", "Wound Edge"):
        iri = URIRef("http://example.org/" + name.replace(" ", "_"))
        g.add((iri, RDF.type, OWL.Class))
        g.add((iri, RDFS.label, rdflib.Literal(name)))
        g.add((iri, RDFS.subClassOf, URIRef(OBO + "BFO_0000040")))
    g.add((URIRef("http://example.org/Wound_Base"), OWL.disjointWith,
           URIRef("http://example.org/Wound_Edge")))
    p = tmp_path / "skeleton.ttl"
    g.serialize(destination=str(p), format="turtle")
    return p


class StubGate(ReasonerGate):
    """ReasonerGate with the ELK subprocess replaced by a canned verdict."""

    def __init__(self, skeleton, unsat_sequence):
        super().__init__(skeleton)
        self._seq = list(unsat_sequence)
        self.calls = 0

    def available(self):
        return None

    def _unsatisfiable(self, graph):
        self.calls += 1
        return set(self._seq.pop(0)) if self._seq else set()

    def _explain(self, graph, max_expl=5):
        return "stub explanation"


# ── entity/relation gate ───────────────────────────────────────────────────
def _result():
    return ExtractionResult(
        entities=[
            {"label": "Wound", "category": "material entity"},
            {"label": "Bad Term", "category": "material entity"},
        ],
        relations=[],
    )


def test_clean_batch_is_accepted_untouched(tiny_skeleton):
    g = StubGate(tiny_skeleton, [])
    res = _result()
    out = g.check(res.entities, res.relations)
    assert out.clean
    assert len(out.accepted_entities) == 2
    assert "clean" in out.summary()


def test_offending_term_is_quarantined_and_the_rest_survive(tiny_skeleton):
    g = StubGate(tiny_skeleton, [{BATCH_NS + _slug("Bad Term")}, set()])
    res = _result()
    out = g.check(res.entities, res.relations)
    assert [e.label for e in out.quarantined_entities] == ["Bad Term"]
    assert [e.label for e in out.accepted_entities] == ["Wound"]
    assert not out.clean


def test_grounded_terms_use_their_real_iri(tiny_skeleton):
    """A relation on a known class must be checked against that class's axioms."""
    g = StubGate(tiny_skeleton, [])
    res = ExtractionResult(entities=[{"label": "Wound", "category": "material entity"}])
    iri = str(g._iri_for(res.entities[0]))
    assert iri.endswith("WONT_0000380")
    assert not iri.startswith(BATCH_NS)


def test_new_terms_get_a_batch_local_iri(tiny_skeleton):
    g = StubGate(tiny_skeleton, [])
    res = ExtractionResult(entities=[{"label": "Brand New", "category": "process"}])
    assert str(g._iri_for(res.entities[0])).startswith(BATCH_NS)


def test_gate_skips_gracefully_when_robot_is_absent(tmp_path):
    g = ReasonerGate(tmp_path / "nope.ttl", robot_cmd="definitely-not-a-binary")
    res = _result()
    out = g.check(res.entities, res.relations)
    assert out.skipped
    assert len(out.accepted_entities) == 2      # fail open, never lose content
    assert "SKIPPED" in out.summary()


def test_gate_reports_missing_skeleton(tmp_path):
    g = ReasonerGate(tmp_path / "missing.ttl")
    assert "skeleton TBox missing" in (g.available() or "")


def test_passes_are_bounded(tiny_skeleton):
    """An unattributable failure must not loop forever."""
    g = StubGate(tiny_skeleton, [{"urn:unknown:thing"}] * 10)
    res = _result()
    out = g.check(res.entities, res.relations)
    assert g.calls <= 3


# ── subsumption-edge gate ──────────────────────────────────────────────────
def test_disjoint_parents_are_caught(tiny_skeleton):
    g = StubGate(tiny_skeleton, [{BATCH_NS + _slug("Weird Thing")}, set()])
    out = g.check_edges([("Chronic Wound", "Wound Base"),
                         ("Weird Thing", "Wound Base"),
                         ("Weird Thing", "Wound Edge")])
    assert out.quarantined == [("Weird Thing", "Wound Base"),
                               ("Weird Thing", "Wound Edge")]
    assert out.accepted == [("Chronic Wound", "Wound Base")]


def test_edge_graph_resolves_existing_labels_case_insensitively(tiny_skeleton):
    g = StubGate(tiny_skeleton, [])
    graph = g.build_edge_graph([("wound base", "wound edge")])
    assert (URIRef("http://example.org/Wound_Base"), RDFS.subClassOf,
            URIRef("http://example.org/Wound_Edge")) in graph


def test_edge_graph_skips_self_loops(tiny_skeleton):
    g = StubGate(tiny_skeleton, [])
    before = len(rdflib.Graph().parse(str(tiny_skeleton), format="turtle"))
    graph = g.build_edge_graph([("Wound Base", "Wound Base")])
    assert len(graph) == before


def test_edge_gate_skips_gracefully(tmp_path):
    g = ReasonerGate(tmp_path / "nope.ttl", robot_cmd="definitely-not-a-binary")
    out = g.check_edges([("A", "B")])
    assert out.skipped and out.accepted == [("A", "B")]


# ── quarantine file ────────────────────────────────────────────────────────
def test_quarantine_file_records_what_and_why(tiny_skeleton, tmp_path):
    g = StubGate(tiny_skeleton, [{BATCH_NS + _slug("Bad Term")}, set()])
    res = _result()
    out = g.check(res.entities, res.relations)
    path = ReasonerGate.write_quarantine(out, tmp_path, tag="t1")
    payload = json.loads(path.read_text())
    assert payload["entities"][0]["label"] == "Bad Term"
    assert payload["explanation"] == "stub explanation"
    assert payload["unsatisfiable"]


def test_no_quarantine_file_when_clean(tiny_skeleton, tmp_path):
    g = StubGate(tiny_skeleton, [])
    res = _result()
    out = g.check(res.entities, res.relations)
    assert ReasonerGate.write_quarantine(out, tmp_path) is None


# ── skeleton construction ──────────────────────────────────────────────────
def test_skeleton_strips_imports(tmp_path):
    src = tmp_path / "a.ttl"
    src.write_text(
        '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
        '<http://x.org/o> a owl:Ontology ; owl:imports <http://x.org/other> .\n',
        encoding="utf-8")
    out, _ = build_skeleton(src, src, tmp_path / "sk.ttl")
    g = rdflib.Graph(); g.parse(str(out), format="turtle")
    assert len(list(g.triples((None, OWL.imports, None)))) == 0


def test_skeleton_states_the_bfo_backbone(tmp_path):
    src = tmp_path / "a.ttl"
    src.write_text("", encoding="utf-8")
    out, _ = build_skeleton(src, src, tmp_path / "sk.ttl")
    g = rdflib.Graph(); g.parse(str(out), format="turtle")
    assert (URIRef(OBO + "BFO_0000040"), RDFS.subClassOf,
            URIRef(OBO + "BFO_0000004")) in g
    assert (URIRef(OBO + "BFO_0000002"), OWL.disjointWith,
            URIRef(OBO + "BFO_0000003")) in g
