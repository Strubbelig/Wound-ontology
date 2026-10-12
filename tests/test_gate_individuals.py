# -*- coding: utf-8 -*-
"""The relation gate when an emptied class holds one of WONT's individuals.

2026-10-07: `p4_derive.py` stopped at the relation gate with "The ontology is
inconsistent". WONT's 48 named individuals (Shea and Wagner grades, zones of a
burn) sit in classes; once the store's relations empty such a class, ELK no
longer reports unsatisfiable classes but an inconsistent ontology, which names
no culprit. The gate now asks again without the individuals, names the
emptied classes, and says that it did (rule 1). And a check that crashes no
longer leaves its earlier verdicts lifted in the saved store.
"""
from __future__ import annotations

import json
import shutil

import pytest
import rdflib
from rdflib import OWL, RDF, RDFS, URIRef

from wound_ontology.llm.extraction_models import BFOCategory, RelationType
from wound_ontology.reasoning.gate import ReasonerGate, without_individuals

OBO = "http://purl.obolibrary.org/obo/"
A = URIRef("http://example.org/Grade")
IND = URIRef("http://example.org/Grade_I")
INCONSISTENT = ("ELK did not run to a result (exit 1); nothing can be called clean:\n"
                "ERROR org.obolibrary.robot.ReasonerHelper - The ontology is inconsistent.")


class E:
    def __init__(self, label, cat, grounded=None):
        self.label, self.category, self.grounded_to = label, cat, grounded


class R:
    def __init__(self, s, p, o):
        self.subject, self.predicate, self.object = s, p, o


@pytest.fixture
def skeleton(tmp_path):
    """One class, `Grade`, with one named individual in it."""
    g = rdflib.Graph()
    g.add((A, RDF.type, OWL.Class))
    g.add((A, RDFS.label, rdflib.Literal("Grade")))
    g.add((A, RDFS.subClassOf, URIRef(OBO + "BFO_0000019")))
    g.add((IND, RDF.type, OWL.NamedIndividual))
    g.add((IND, RDF.type, A))
    g.add((IND, RDFS.label, rdflib.Literal("Grade I")))
    p = tmp_path / "skeleton.ttl"
    g.serialize(destination=str(p), format="turtle")
    return p


def _restricts_grade(graph) -> bool:
    """Whether the batch put a relation on `Grade` itself."""
    return any(isinstance(o, rdflib.BNode) for o in graph.objects(A, RDFS.subClassOf))


class FakeElk(ReasonerGate):
    """ELK as it behaves on WONT: a relation on `Grade` empties it, which is an
    inconsistency while its individual is in, and `Grade` unsatisfiable without."""

    def __init__(self, skeleton):
        super().__init__(skeleton)
        self.explained = []

    def available(self):
        return None

    def _run_elk(self, graph):
        if not _restricts_grade(graph):
            return set()
        if set(graph.subjects(RDF.type, OWL.NamedIndividual)):
            raise RuntimeError(INCONSISTENT)
        return {str(A)}

    def _explain(self, graph, max_expl=5):
        self.explained.append(graph)
        return "stub explanation"


def _batch():
    ents = [E("Grade", BFOCategory.Quality, str(A)), E("healing", BFOCategory.Process),
            E("gel", BFOCategory.MaterialEntity)]
    bad = R("Grade", RelationType.PARTICIPATES_IN, "healing")
    good = R("gel", RelationType.PARTICIPATES_IN, "healing")
    return ents, bad, good


# ── the check names the emptied class instead of failing ──────────────────
def test_an_emptied_class_with_an_individual_is_named_not_a_crash(skeleton, capsys):
    gate = FakeElk(skeleton)
    ents, bad, good = _batch()
    res = gate.check(ents, [bad, good])
    assert str(A) in res.unsatisfiable
    assert bad in res.quarantined_relations
    assert good in res.accepted_relations


def test_it_says_loudly_that_individuals_were_set_aside_and_which(skeleton, capsys):
    gate = FakeElk(skeleton)
    ents, bad, good = _batch()
    res = gate.check(ents, [bad, good])
    out = capsys.readouterr().out
    assert "without them" in out and "Grade I" in out and "member of Grade" in out
    assert len(res.without_individuals) == 1
    assert "Grade I" in res.without_individuals[0]
    assert "asked again without" in res.summary()


def test_the_explanation_is_asked_of_the_graph_without_individuals(skeleton):
    gate = FakeElk(skeleton)
    ents, bad, good = _batch()
    gate.check(ents, [bad, good])
    assert gate.explained
    assert not list(gate.explained[0].subjects(RDF.type, OWL.NamedIndividual))


def test_a_consistent_batch_carries_no_note(skeleton):
    gate = FakeElk(skeleton)
    ents, _, good = _batch()
    res = gate.check(ents, [good])
    assert res.clean and res.without_individuals == []
    assert "individuals" not in res.summary()


def test_the_quarantine_file_records_it(skeleton, tmp_path):
    gate = FakeElk(skeleton)
    ents, bad, good = _batch()
    res = gate.check(ents, [bad, good])
    path = ReasonerGate.write_quarantine(res, tmp_path / "q")
    data = json.loads(path.read_text())
    assert data["asked_without_individuals"] == res.without_individuals


def test_notes_do_not_carry_over_to_the_next_check(skeleton):
    gate = FakeElk(skeleton)
    ents, bad, good = _batch()
    gate.check(ents, [bad, good])
    assert gate.check(ents, [good]).without_individuals == []


# ── when nothing can be named, it still stops ──────────────────────────────
def test_inconsistent_without_any_individual_still_raises(skeleton):
    gate = ReasonerGate(skeleton)

    def boom(graph):
        raise RuntimeError(INCONSISTENT)
    gate._run_elk = boom
    with pytest.raises(RuntimeError, match="nothing can be called clean"):
        gate._unsatisfiable(rdflib.Graph())


def test_inconsistent_and_no_class_empty_without_individuals_raises(skeleton):
    gate = ReasonerGate(skeleton)
    calls = []

    def elk(graph):
        calls.append(graph)
        if len(calls) == 1:
            raise RuntimeError(INCONSISTENT)
        return set()
    gate._run_elk = elk
    g = rdflib.Graph(); g.parse(str(skeleton), format="turtle")
    with pytest.raises(RuntimeError, match="look by hand"):
        gate._unsatisfiable(g)
    assert gate.individual_notes == []


def test_another_elk_failure_is_not_taken_for_an_inconsistency(skeleton):
    gate = ReasonerGate(skeleton)

    def oom(graph):
        raise RuntimeError("ELK did not run to a result (exit 1); OutOfMemoryError")
    gate._run_elk = oom
    g = rdflib.Graph(); g.parse(str(skeleton), format="turtle")
    with pytest.raises(RuntimeError, match="OutOfMemoryError"):
        gate._unsatisfiable(g)


def test_without_individuals_leaves_the_input_alone(skeleton):
    g = rdflib.Graph(); g.parse(str(skeleton), format="turtle")
    n = len(g)
    bare, removed = without_individuals(g)
    assert len(g) == n
    assert removed == {IND: {A}}
    assert not list(bare.triples((IND, None, None)))
    assert (A, RDF.type, OWL.Class) in bare


# ── a crash puts the lifted verdicts back ──────────────────────────────────
def test_a_crashed_check_puts_the_lifted_verdicts_back(monkeypatch):
    import wound_ontology.llm.extraction_adapter as adapter
    from wound_ontology.orchestrator import Orchestrator

    lifted = {"entity_verdicts": {}, "cell_verdicts": {"gel": {"t": {"by": "reasoner_gate"}}}}

    class Store:
        restored = None

        def lift_decisions(self, by):
            return lifted

        def restore_decisions(self, what):
            Store.restored = what
            return 1

    class Gate:
        least_common_category = staticmethod(lambda cats: None)

        def check(self, ents, rels):
            raise RuntimeError("ELK did not run to a result")

    ents, _, good = _batch()
    monkeypatch.setattr(adapter, "store_to_gate_inputs",
                        lambda st, resolve_conflict=None: (ents, [good],
                                                           {"conflicting": {}, "unlicensed": []}))
    monkeypatch.setattr(adapter, "describe_gate_inputs", lambda e, r, rep: "inputs")
    orch = Orchestrator.__new__(Orchestrator)
    orch._gate = Gate()
    with pytest.raises(RuntimeError):
        orch.run_gate_store_relations(store=Store(), apply=True)
    assert Store.restored is lifted


# ── real ELK on the real skeleton ──────────────────────────────────────────
@pytest.mark.reasoner
@pytest.mark.skipif(shutil.which("robot") is None, reason="robot not on PATH")
def test_real_elk_names_the_emptied_shea_grade(tmp_path, capsys):
    """WONT's `Shea classification grade` holds four individuals. Made both a
    material entity and a process (BFO makes them disjoint), it is empty, and
    ROBOT says the ontology is inconsistent; the gate names the class instead."""
    from config.settings import GROUND_TRUTH_TTL, MILD_TTL
    from wound_ontology.reasoning.skeleton import build_skeleton

    path, _ = build_skeleton(GROUND_TRUTH_TTL, MILD_TTL, tmp_path / "skeleton.ttl")
    gate = ReasonerGate(path)
    g = rdflib.Graph(); g.parse(str(path), format="turtle")
    shea = URIRef("https://bioportal.bioontology.org/ontologies/WONT/WONT_0000438")
    assert list(g.subjects(RDF.type, shea)), "Shea grades are no longer individuals"
    g.add((shea, RDFS.subClassOf, URIRef(OBO + "BFO_0000040")))
    g.add((shea, RDFS.subClassOf, URIRef(OBO + "BFO_0000015")))
    found = gate._unsatisfiable(g)
    assert str(shea) in found
    assert "Shea classification grade I" in capsys.readouterr().out
    assert len(gate.individual_notes) == 1


# ── causes first, knock-ons kept (2026-10-08) ──────────────────────────────
# On 2026-10-08 the check held back 20,363 of 24,584 relations: a few terms
# whose relations asked for two kinds of thing at once went empty, through
# them `Wound`, and through `Wound` 6,756 classes; every relation touching an
# empty class was held back. Only the causes may go.
EX = "http://example.org/"


@pytest.fixture
def kinds_skeleton(tmp_path):
    """BFO's backbone and disjointness, `Wound` as a material entity, and the
    domains and ranges the real skeleton takes from RO and IAO."""
    from wound_ontology.llm.extraction_models import RELATION_IRI
    from wound_ontology.reasoning.skeleton import BFO_DISJOINT, BFO_SKELETON
    g = rdflib.Graph()
    for child, parent in BFO_SKELETON.items():
        g.add((URIRef(OBO + child), RDFS.subClassOf, URIRef(OBO + parent)))
    for a, b in BFO_DISJOINT:
        g.add((URIRef(OBO + a), OWL.disjointWith, URIRef(OBO + b)))
    g.add((URIRef(EX + "Wound"), RDF.type, OWL.Class))
    g.add((URIRef(EX + "Wound"), RDFS.subClassOf, URIRef(OBO + "BFO_0000040")))
    for pred, axis, cls in (("inheres in", RDFS.domain, "BFO_0000020"),
                            ("is about", RDFS.domain, "BFO_0000031"),
                            ("has quality", RDFS.range, "BFO_0000019")):
        prop = URIRef(RELATION_IRI[pred])
        g.add((prop, RDF.type, OWL.ObjectProperty))
        g.add((prop, axis, URIRef(OBO + cls)))
    p = tmp_path / "kinds.ttl"
    g.serialize(destination=str(p), format="turtle")
    return p


def _key(rs):
    return sorted((r.subject, r.predicate.value, r.object) for r in rs)


@pytest.mark.reasoner
@pytest.mark.skipif(shutil.which("robot") is None, reason="robot not on PATH")
def test_two_kinds_at_once_holds_back_those_two_and_keeps_the_knock_ons(kinds_skeleton):
    """`wound size` inheres in Wound (a property) and is about a topic (a piece
    of information): nothing is both, so it is empty, and so is Wound, which
    has it as a quality, and everything part of a wound. Only the two clashing
    relations are held back."""
    gate = ReasonerGate(kinds_skeleton)
    ents = [E("Wound", BFOCategory.MaterialEntity, EX + "Wound"),
            E("wound size", BFOCategory.Continuant),
            E("topic", BFOCategory.InformationEntity),
            E("gel", BFOCategory.MaterialEntity),
            E("dressing", BFOCategory.MaterialEntity),
            E("redness", BFOCategory.Quality)]
    clash = [R("wound size", RelationType.INHERES_IN, "Wound"),
             R("wound size", RelationType.IS_ABOUT, "topic")]
    knock_on = [R("Wound", RelationType.HAS_QUALITY, "wound size"),
                R("gel", RelationType.PART_OF, "Wound"),
                R("dressing", RelationType.PART_OF, "gel"),
                R("gel", RelationType.HAS_QUALITY, "redness")]
    res = gate.check(ents, clash + knock_on)
    assert _key(res.quarantined_relations) == _key(clash)
    assert _key(res.accepted_relations) == _key(knock_on)
    assert res.still_empty == [] and res.quarantined_entities == []
    # what the curator is shown: the two sides of the clash
    assert res.causes == [{"kind": "two kinds", "subject": "wound size",
                           "clashing": [["inheres in", "is about"]],
                           "groups": {"inheres in": ["Wound"], "is about": ["topic"]}}]


@pytest.mark.reasoner
@pytest.mark.skipif(shutil.which("robot") is None, reason="robot not on PATH")
def test_a_relation_that_clashes_with_what_its_target_is_goes_alone(kinds_skeleton):
    """`report` is a piece of information (it is about a topic); `has quality`
    needs a quality. Each relation is fine with the typing alone, so only the
    whole batch shows it -- and only `X has quality report` is to blame."""
    gate = ReasonerGate(kinds_skeleton)
    ents = [E("X", BFOCategory.MaterialEntity), E("report", BFOCategory.Continuant),
            E("topic", BFOCategory.InformationEntity), E("Z", BFOCategory.MaterialEntity)]
    bad = R("X", RelationType.HAS_QUALITY, "report")
    keep = [R("report", RelationType.IS_ABOUT, "topic"), R("Z", RelationType.PART_OF, "X")]
    res = gate.check(ents, [bad] + keep)
    assert res.quarantined_relations == [bad]
    assert _key(res.accepted_relations) == _key(keep)
    # the report's own `is about` is what makes it the wrong kind
    assert res.causes == [{"kind": "target", "subject": "X", "predicate": "has quality",
                           "object": "report", "target_blamed": ["is about"],
                           "target_statements": [("is about", "topic")]}]



@pytest.mark.reasoner
@pytest.mark.skipif(shutil.which("robot") is None, reason="robot not on PATH")
def test_a_loop_does_not_hide_its_cause(kinds_skeleton):
    """2026-10-09, second pass: 6,721 empty classes, each empty only because it
    points at another. `X has quality note` needs a quality; `note is about X`
    makes the note a piece of information; so X is empty, and the note, which
    is about X, with it. Each probe saw only an empty target. A stand-in that
    keeps the note's kind but not its emptiness shows the cause."""
    gate = ReasonerGate(kinds_skeleton)
    ents = [E("X", BFOCategory.MaterialEntity), E("note", BFOCategory.Continuant),
            E("Z", BFOCategory.MaterialEntity)]
    bad = R("X", RelationType.HAS_QUALITY, "note")
    keep = [R("note", RelationType.IS_ABOUT, "X"), R("Z", RelationType.PART_OF, "X")]
    res = gate.check(ents, [bad] + keep)
    assert res.quarantined_relations == [bad]
    assert _key(res.accepted_relations) == _key(keep)
    assert res.still_empty == []


@pytest.mark.reasoner
@pytest.mark.skipif(shutil.which("robot") is None, reason="robot not on PATH")
def test_a_term_about_itself_is_still_caught(kinds_skeleton):
    """2026-10-09: `pressure ulcer stage` inheres in Pressure ulcer AND is about
    pressure ulcer stage. Tested against its targets, the clash hid behind the
    target being the term itself, as empty as it is; 6,702 classes stayed
    empty. Two relation types clash whatever they point at."""
    gate = ReasonerGate(kinds_skeleton)
    ents = [E("Pressure ulcer", BFOCategory.MaterialEntity),
            E("stage", BFOCategory.Continuant), E("Wound", BFOCategory.MaterialEntity, EX + "Wound")]
    clash = [R("stage", RelationType.INHERES_IN, "Pressure ulcer"),
             R("stage", RelationType.IS_ABOUT, "stage")]
    # `Pressure ulcer` has two relation types, one pointing at the emptied
    # `stage`: a test against targets would blame it too.
    keep = [R("Pressure ulcer", RelationType.HAS_QUALITY, "stage"),
            R("Pressure ulcer", RelationType.PART_OF, "Wound"),
            R("Wound", RelationType.HAS_PART, "Pressure ulcer")]
    res = gate.check(ents, clash + keep)
    assert _key(res.quarantined_relations) == _key(clash)
    assert _key(res.accepted_relations) == _key(keep)
    assert res.still_empty == []

def test_no_cause_found_falls_back_loudly_and_says_what_stays_empty(tmp_path, capsys):
    class Stuck(ReasonerGate):
        def available(self):
            return None

        def _run_elk(self, graph):
            return {"urn:unknown:thing"}

    p = tmp_path / "s.ttl"; rdflib.Graph().serialize(destination=str(p), format="turtle")
    res = Stuck(p).check([E("gel", BFOCategory.MaterialEntity)], [])
    assert res.still_empty == ["urn:unknown:thing"]
    assert "STILL empty" in res.summary()
    assert "the old way" in capsys.readouterr().out


# ── a timeout ends ROBOT's Java too ────────────────────────────────────────
def test_a_timeout_ends_the_process_the_script_started(tmp_path):
    """`robot` is a script that starts Java; on 2026-10-08 a timed-out
    explanation left Java reasoning for 25 hours. The stand-in script here
    starts a long sleep the way `robot` starts Java."""
    import os
    import subprocess
    import time

    from wound_ontology.reasoning.gate import _run_robot

    pidfile = tmp_path / "child.pid"
    script = tmp_path / "robot"
    script.write_text(f"#!/bin/sh\nsleep 60 &\necho $! > {pidfile}\nwait\n")
    script.chmod(0o755)
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_robot([str(script)], timeout=1)
    assert time.time() - t0 < 10, "the timeout waited for the child to finish by itself"
    child = int(pidfile.read_text())
    for _ in range(20):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(child, 9)
        pytest.fail("the child of the timed-out script is still running")
