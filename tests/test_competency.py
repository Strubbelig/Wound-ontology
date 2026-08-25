"""Competency questions as executable queries (C8).

`config/competency_questions.json` was only ever read to build a prompt section.
Its `example_triple` payloads are machine-checkable claims, so they are compiled
into SPARQL ASK queries and run. This is the "justify the ontology by its
purpose" recommendation turned from an assertion into a measurement.
"""
import pytest
import rdflib
from rdflib import OWL, RDF, RDFS, URIRef

from wound_ontology.evaluation.competency import (
    CompetencyQuestion,
    Verdict,
    compile_ask,
    in_scope_score,
    label_index,
    load_questions,
    report,
    run_suite,
    summarize,
)

from config.settings import COMPETENCY_QUESTIONS_FILE as CQ_FILE

EX = "http://example.org/"
OBO = "http://purl.obolibrary.org/obo/"


@pytest.fixture
def graph():
    g = rdflib.Graph()

    def cls(name):
        iri = URIRef(EX + name.replace(" ", "_"))
        g.add((iri, RDF.type, OWL.Class))
        g.add((iri, RDFS.label, rdflib.Literal(name)))
        return iri

    wound = cls("Wound")
    chronic = cls("Chronic Wound")
    base = cls("Wound Base")
    red = cls("reddened")
    g.add((chronic, RDFS.subClassOf, wound))

    # Wound Base part_of some Wound
    r = rdflib.BNode()
    g.add((r, RDF.type, OWL.Restriction))
    g.add((r, OWL.onProperty, URIRef(OBO + "BFO_0000050")))
    g.add((r, OWL.someValuesFrom, wound))
    g.add((base, RDFS.subClassOf, r))

    # Chronic Wound has_quality some reddened
    r2 = rdflib.BNode()
    g.add((r2, RDF.type, OWL.Restriction))
    g.add((r2, OWL.onProperty, URIRef(OBO + "RO_0000086")))
    g.add((r2, OWL.someValuesFrom, red))
    g.add((chronic, RDFS.subClassOf, r2))

    # a synonym, to prove alt terms are matched
    g.add((chronic, URIRef(OBO + "IAO_0000118"), rdflib.Literal("Long-standing Wound")))
    return g


def cq(id_, triple, in_scope=True):
    return CompetencyQuestion(id=id_, question="?", triple=triple, in_scope=in_scope)


# ── compilation ────────────────────────────────────────────────────────────
def test_subclass_compiles_to_a_transitive_ask():
    q = compile_ask(EX + "A", "is_a", EX + "B")
    assert "ASK" in q and "rdfs:subClassOf*" in q


def test_restriction_predicate_compiles_to_a_restriction_ask():
    q = compile_ask(EX + "A", "part_of", EX + "B")
    assert "owl:onProperty <http://purl.obolibrary.org/obo/BFO_0000050>" in q


def test_rejected_predicates_do_not_compile():
    assert compile_ask(EX + "A", "affects", EX + "B") is None
    assert compile_ask(EX + "A", "caused_by", EX + "B") is None


# ── verdicts ───────────────────────────────────────────────────────────────
def test_true_subsumption_passes(graph):
    r = run_suite(graph, [cq("T1", ("Chronic Wound", "is_a", "Wound"))])[0]
    assert r.verdict is Verdict.PASS


def test_absent_subsumption_fails(graph):
    r = run_suite(graph, [cq("T2", ("Wound", "is_a", "Chronic Wound"))])[0]
    assert r.verdict is Verdict.FAIL


def test_restriction_is_found(graph):
    r = run_suite(graph, [cq("T3", ("Wound Base", "part_of", "Wound"))])[0]
    assert r.verdict is Verdict.PASS


def test_quality_restriction_is_found(graph):
    r = run_suite(graph, [cq("T4", ("Chronic Wound", "has_quality", "reddened"))])[0]
    assert r.verdict is Verdict.PASS


def test_rejected_relation_is_unexpressible_not_failed(graph):
    """Blaming the ontology for a CQ written against a relation it deliberately
    rejects would be misleading."""
    r = run_suite(graph, [cq("T5", ("Wound", "caused_by", "Chronic Wound"))])[0]
    assert r.verdict is Verdict.UNEXPRESSIBLE
    assert "commitment 4" in r.detail


def test_affects_is_unexpressible(graph):
    r = run_suite(graph, [cq("T6", ("Wound", "affects", "Chronic Wound"))])[0]
    assert r.verdict is Verdict.UNEXPRESSIBLE
    assert "no IRI" in r.detail


def test_missing_term_is_unresolved_with_a_near_miss_hint(graph):
    r = run_suite(graph, [cq("T7", ("Chronic Wounds", "is_a", "Wound"))])[0]
    assert r.verdict is Verdict.UNRESOLVED
    assert "did you mean" in r.detail


def test_genuinely_absent_term_gets_no_hint(graph):
    r = run_suite(graph, [cq("T8", ("Zygomatic Arch Fracture", "is_a", "Wound"))])[0]
    assert r.verdict is Verdict.UNRESOLVED
    assert "did you mean" not in r.detail


def test_synonyms_resolve(graph):
    idx = label_index(graph)
    assert idx["long-standing wound"] == URIRef(EX + "Chronic_Wound")


def test_preferred_label_wins_over_synonym(graph):
    idx = label_index(graph)
    assert idx["chronic wound"] == URIRef(EX + "Chronic_Wound")


# ── scoring honesty ────────────────────────────────────────────────────────
def test_out_of_scope_without_a_triple_is_declared_not_passed(graph):
    r = run_suite(graph, [CompetencyQuestion(id="O1", question="?", in_scope=False)])[0]
    assert r.verdict is Verdict.DECLARED


def test_declared_questions_do_not_inflate_the_score(graph):
    qs = [CompetencyQuestion(id="O1", question="?", in_scope=False),
          cq("T1", ("Chronic Wound", "is_a", "Wound"))]
    p, n = in_scope_score(run_suite(graph, qs))
    assert (p, n) == (1, 1)


def test_unexpressible_is_excluded_from_the_denominator(graph):
    qs = [cq("T1", ("Chronic Wound", "is_a", "Wound")),
          cq("T5", ("Wound", "caused_by", "Chronic Wound"))]
    p, n = in_scope_score(run_suite(graph, qs))
    assert (p, n) == (1, 1)


def test_out_of_scope_claim_that_IS_answerable_fails(graph):
    """A scope boundary the ontology crosses is a real failure."""
    q = CompetencyQuestion(id="O2", question="?", in_scope=False,
                           triple=("Chronic Wound", "is_a", "Wound"))
    assert run_suite(graph, [q])[0].verdict is Verdict.FAIL


# ── the real CQ file ───────────────────────────────────────────────────────
def test_real_cq_file_loads():
    qs = load_questions(CQ_FILE)
    assert len(qs) > 60
    assert any(q.in_scope for q in qs) and any(not q.in_scope for q in qs)


def test_report_renders():
    text = report(run_suite(rdflib.Graph(), load_questions(CQ_FILE)))
    assert "in-scope score" in text


# ── regression guard on the real artefact ──────────────────────────────────
#
# The current score is 0/51: the ontology answers NONE of its own in-scope
# competency questions as written. That is the measurement, not a target — most
# of the gap is the CQ file and the ontology having drifted apart. These pin the
# numbers so the score can only be improved, never silently regressed.
#
# 2026-08-20: 0/51 -> 6/65. Ten CQ terms were realigned to the labels the
# ontology actually uses, three wound-part classes gained the part_of Wound
# axiom their names always implied, and the 14 CQs written with 'affects' or
# 'caused_by' were rewritten against relations this ontology licenses. The
# denominator GREW because those 14 stopped being exempt from scoring -- the
# score percentage barely moved, but 14 questions went from "not counted" to
# "actually measured", which is the point.

BASELINE_PASS = 6
BASELINE_TESTABLE = 65
BASELINE_UNEXPRESSIBLE = 0


@pytest.fixture(scope="module")
def real_graph():
    """The full closure: WONT + MILD + every MILD module.

    The module loop used to be ``except Exception: pass``. A module that failed
    to parse was dropped without a word, and the competency score was then
    computed against a graph missing classes it was expected to reach -- a
    regression in the modules would have shown up as CQs mysteriously not
    answering, never as a parse error. Failures are collected and raised
    together, so one broken module names itself instead of moving the baseline.
    """
    from config.settings import GROUND_TRUTH_TTL, MILD_TTL, MILD_MODULES_DIR
    g = rdflib.Graph()
    g.parse(str(GROUND_TRUTH_TTL), format="turtle")
    g.parse(str(MILD_TTL), format="turtle")
    modules = sorted(MILD_MODULES_DIR.glob("*_module.owl"))
    assert modules, f"no MILD modules found under {MILD_MODULES_DIR}"
    broken = []
    for m in modules:
        try:
            g.parse(str(m))
        except Exception as exc:                      # noqa: BLE001 -- re-raised below
            broken.append(f"{m.name}: {type(exc).__name__}: {exc}")
    if broken:
        raise RuntimeError(
            "MILD modules failed to parse, so the competency score would be "
            "measured against an incomplete closure:\n  "
            + "\n  ".join(broken)
        )
    return g


@pytest.fixture(scope="module")
def real_results(real_graph):
    return run_suite(real_graph, load_questions(CQ_FILE))


def test_in_scope_score_does_not_regress(real_results):
    p, n = in_scope_score(real_results)
    assert p >= BASELINE_PASS, f"competency score regressed to {p}/{n}"


def test_unexpressible_count_does_not_grow(real_results):
    """More UNEXPRESSIBLE means new CQs were written against relations the
    ontology rejects — a drift between the CQ file and the model commitments."""
    n = summarize(real_results).get(Verdict.UNEXPRESSIBLE.value, 0)
    assert n <= BASELINE_UNEXPRESSIBLE, f"UNEXPRESSIBLE grew to {n}"


def test_no_new_relation_becomes_unexpressible(real_results):
    """The only relations this ontology may refuse are the two it refuses on
    principle. Anything else showing up here means a CQ was written against a
    relation nobody decided to reject — drift, not a commitment."""
    preds = {r.cq.triple[1] for r in real_results
             if r.verdict is Verdict.UNEXPRESSIBLE and r.cq.triple}
    assert preds <= {"affects", "caused_by"}, f"unexpected unexpressible: {preds}"


def test_colocation_is_not_vacuous(real_graph):
    """co_located_with must distinguish. If it answered true for any pair it
    would manufacture passes rather than measure anything."""
    from wound_ontology.evaluation.competency import colocation_holds, label_index
    idx = label_index(real_graph)
    yes = ("diabetic wound", "diabetic metabolic disorder")
    no = ("diabetic wound", "autoimmune tissue disorder")
    assert colocation_holds(real_graph, idx[yes[0]], idx[yes[1]]) is True
    assert colocation_holds(real_graph, idx[no[0]], idx[no[1]]) is False
    # a bare Wound is co-located with nothing in particular
    assert colocation_holds(real_graph, idx["wound"], idx["diabetic metabolic disorder"]) is False
