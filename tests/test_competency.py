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
    assert "ASK" in q and "rdfs:subClassOf" in q and ")*" in q


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


def test_has_participant_is_asked_as_a_restriction(graph):
    """CQ100 was rewritten from occurs_in (a wound is not a site) to
    has_participant. The predicate must reach RO_0000057 and be found on the
    class or an ancestor; without the axiom it fails rather than resolving to
    something else."""
    g = graph
    assess = URIRef(EX + "Assessment"); g.add((assess, RDF.type, OWL.Class)); g.add((assess, RDFS.label, rdflib.Literal("Wound assessment")))
    clinical = URIRef(EX + "Clinical"); g.add((clinical, RDF.type, OWL.Class)); g.add((clinical, RDFS.label, rdflib.Literal("Clinical wound assessment")))
    g.add((clinical, RDFS.subClassOf, assess))
    before = run_suite(g, [cq("T4p", ("Clinical wound assessment", "has_participant", "Wound"))])[0]
    assert before.verdict is Verdict.FAIL
    r = rdflib.BNode()
    g.add((r, RDF.type, OWL.Restriction)); g.add((r, OWL.onProperty, URIRef(OBO + "RO_0000057"))); g.add((r, OWL.someValuesFrom, URIRef(EX + "Wound")))
    g.add((assess, RDFS.subClassOf, r))
    after = run_suite(g, [cq("T4p", ("Clinical wound assessment", "has_participant", "Wound"))])[0]
    assert after.verdict is Verdict.PASS, after.detail


def test_an_individual_is_a_its_type(graph):
    """Grades are individuals (decision of 2026-09-16): 'Inflammatory phase'
    is an instance of 'Wound healing phase', so `is_a` must take rdf:type as
    its first step. Without it the CQ fails on a convention."""
    g = graph
    phase = URIRef(EX + "Phase"); g.add((phase, RDF.type, OWL.Class)); g.add((phase, RDFS.label, rdflib.Literal("Wound healing phase")))
    grade = URIRef(EX + "Grade"); g.add((grade, RDF.type, OWL.Class)); g.add((grade, RDFS.label, rdflib.Literal("Classification grade")))
    g.add((phase, RDFS.subClassOf, grade))
    infl = URIRef(EX + "Infl"); g.add((infl, RDF.type, OWL.NamedIndividual)); g.add((infl, RDF.type, phase)); g.add((infl, RDFS.label, rdflib.Literal("Inflammatory phase")))
    res = run_suite(g, [cq("T4i", ("Inflammatory phase", "is_a", "Wound healing phase")),
                        cq("T4j", ("Inflammatory phase", "is_a", "Classification grade")),
                        cq("T4k", ("Inflammatory phase", "is_a", "Wound"))])
    assert [r.verdict for r in res] == [Verdict.PASS, Verdict.PASS, Verdict.FAIL], [r.detail for r in res]


def test_an_individual_carries_a_relation_as_an_assertion(graph):
    """'Proliferative phase' is_about 'Granulation tissue formation process'
    is a plain property assertion on an individual, not a restriction on a
    class; the restriction path alone never sees it."""
    g = graph
    prol = URIRef(EX + "Prol"); g.add((prol, RDF.type, OWL.NamedIndividual)); g.add((prol, RDFS.label, rdflib.Literal("Proliferative phase")))
    gran = URIRef(EX + "Gran"); g.add((gran, RDF.type, OWL.Class)); g.add((gran, RDFS.label, rdflib.Literal("Granulation tissue formation process")))
    before = run_suite(g, [cq("T4m", ("Proliferative phase", "is_about", "Granulation tissue formation process"))])[0]
    assert before.verdict is Verdict.FAIL
    g.add((prol, URIRef(OBO + "IAO_0000136"), gran))
    after = run_suite(g, [cq("T4m", ("Proliferative phase", "is_about", "Granulation tissue formation process"))])[0]
    assert after.verdict is Verdict.PASS, after.detail


def test_quality_restriction_is_found(graph):
    r = run_suite(graph, [cq("T4", ("Chronic Wound", "has_quality", "reddened"))])[0]
    assert r.verdict is Verdict.PASS


def test_a_restriction_whose_filler_is_an_intersection_is_found(graph):
    """`Malignant wound = Wound and output_of some (Wound development process
    and has_part some X)`: the filler is an intersection, and the CQ names one
    of its members. The intersection is subsumed by each member, so the member
    answers the question."""
    from rdflib.collection import Collection
    g = graph
    wound = URIRef(EX + "Wound")
    wdp = URIRef(EX + "WDP"); g.add((wdp, RDF.type, OWL.Class)); g.add((wdp, RDFS.label, rdflib.Literal("Wound development process")))
    mw = URIRef(EX + "Malignant_Wound"); g.add((mw, RDF.type, OWL.Class)); g.add((mw, RDFS.label, rdflib.Literal("Malignant Wound")))
    other = URIRef(EX + "Other"); g.add((other, RDF.type, OWL.Class)); g.add((other, RDFS.label, rdflib.Literal("Other process")))
    inner = rdflib.BNode(); inner_lst = rdflib.BNode()
    Collection(g, inner_lst, [wdp, other]); g.add((inner, OWL.intersectionOf, inner_lst))
    r = rdflib.BNode()
    g.add((r, RDF.type, OWL.Restriction)); g.add((r, OWL.onProperty, URIRef(OBO + "RO_0002353"))); g.add((r, OWL.someValuesFrom, inner))
    outer = rdflib.BNode(); outer_lst = rdflib.BNode()
    Collection(g, outer_lst, [wound, r]); g.add((outer, OWL.intersectionOf, outer_lst))
    g.add((mw, OWL.equivalentClass, outer))
    res = run_suite(g, [cq("T5", ("Malignant Wound", "output_of", "Wound development process")),
                        cq("T5b", ("Malignant Wound", "output_of", "reddened"))])
    assert res[0].verdict is Verdict.PASS, res[0].detail
    assert res[1].verdict is Verdict.FAIL


def test_a_defining_axiom_answers_a_subclass_cq(graph):
    """`Pressure ulcer = Wound and output_of some ...` with no asserted
    rdfs:subClassOf Wound (the 17 Sep hand edit dropped it) is still a
    subclass of Wound, and CQ002 must not fail on a convention."""
    from rdflib.collection import Collection
    g = graph
    wound = URIRef(EX + "Wound")
    pu = URIRef(EX + "PU"); g.add((pu, RDF.type, OWL.Class)); g.add((pu, RDFS.label, rdflib.Literal("Pressure ulcer")))
    r = rdflib.BNode(); g.add((r, RDF.type, OWL.Restriction))
    g.add((r, OWL.onProperty, URIRef(OBO + "RO_0002353"))); g.add((r, OWL.someValuesFrom, URIRef(EX + "WDP")))
    inter = rdflib.BNode(); lst = rdflib.BNode(); Collection(g, lst, [wound, r]); g.add((inter, OWL.intersectionOf, lst))
    g.add((pu, OWL.equivalentClass, inter))
    res = run_suite(g, [cq("T6", ("Pressure ulcer", "is_a", "Wound")),
                        cq("T6b", ("Pressure ulcer", "is_a", "reddened"))])
    assert res[0].verdict is Verdict.PASS, res[0].detail
    assert res[1].verdict is Verdict.FAIL


def test_a_defining_axiom_answers_a_restriction_cq(graph):
    """`Open Wound ≡ Wound and has_quality some open` entails the necessary
    condition the CQ asks for. WONT states every determinate-defined class this
    way, and a checker that only walked rdfs:subClassOf reported all of them
    as FAIL (8 of 9 has_quality CQs, measured 2026-09-12)."""
    from rdflib.collection import Collection
    g = graph
    wound = URIRef(EX + "Wound")
    open_q = URIRef(EX + "open"); g.add((open_q, RDF.type, OWL.Class)); g.add((open_q, RDFS.label, rdflib.Literal("open")))
    ow = URIRef(EX + "Open_Wound"); g.add((ow, RDF.type, OWL.Class)); g.add((ow, RDFS.label, rdflib.Literal("Open Wound")))
    r = rdflib.BNode()
    g.add((r, RDF.type, OWL.Restriction))
    g.add((r, OWL.onProperty, URIRef(OBO + "RO_0000086")))
    g.add((r, OWL.someValuesFrom, open_q))
    inter = rdflib.BNode(); lst = rdflib.BNode()
    Collection(g, lst, [wound, r])
    g.add((inter, RDF.type, OWL.Class)); g.add((inter, OWL.intersectionOf, lst))
    g.add((ow, OWL.equivalentClass, inter))          # no rdfs:subClassOf at all
    res = run_suite(g, [cq("T4b", ("Open Wound", "has_quality", "open")),
                        cq("T4c", ("Open Wound", "has_quality", "reddened"))])
    assert res[0].verdict is Verdict.PASS, res[0].detail
    assert res[1].verdict is Verdict.FAIL, "a quality the axiom does not state must still fail"


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
    """A term that folds onto nothing, but reads like something that is there.

    This used to be asserted of "Chronic Wounds", which the exact-match-only
    index could not see. It now resolves -- see the test below -- so the near
    miss is demonstrated with a term that really is a different word.
    """
    r = run_suite(graph, [cq("T7", ("Wound Bed", "is_a", "Wound"))])[0]
    assert r.verdict is Verdict.UNRESOLVED
    assert "did you mean" in r.detail


def test_a_plural_no_longer_counts_as_a_missing_class(graph):
    """One of the four label-index misses measured on 2026-09-10. Asking about
    "Chronic Wounds" against a class labelled "Chronic Wound" was reported as a
    vocabulary gap; it is a spelling."""
    r = run_suite(graph, [cq("T7b", ("Chronic Wounds", "is_a", "Wound"))])[0]
    assert r.verdict is Verdict.PASS
    assert "variant" in r.detail


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


def test_complication_is_not_vacuous(real_graph):
    """complication_of must distinguish. If it answered true for any pair it
    would manufacture passes rather than measure anything."""
    from wound_ontology.evaluation.competency import complication_holds, label_index
    idx = label_index(real_graph)
    # through a subclass of the process (Angiopathic disease process)
    assert complication_holds(real_graph, idx["angiopathic wound"], idx["angiopathic disease process"]) is True
    # through has_participant on the process (Venous insufficiency disease process)
    assert complication_holds(real_graph, idx["venous insufficiency wound"], idx["venous insufficiency disorder"]) is True
    # a direct output_of, no has_part (Traumatic wound)
    assert complication_holds(real_graph, idx["traumatic wound"], idx["trauma process"]) is True
    assert complication_holds(real_graph, idx["venous insufficiency wound"], idx["peripheral arterial occlusive disease"]) is False
    # a bare Wound is a complication of nothing in particular
    assert complication_holds(real_graph, idx["wound"], idx["venous insufficiency disorder"]) is False


# ── the resolver uses the pipeline's one label index, not a second rule ──────
#
# label_index() used to build a plain {lower(label): iri} dict and _answerable
# matched on the exact string only -- a second normalisation rule beside
# utils.label_match.LabelIndex, which already carried the folded fallback and
# was sitting unused here. Standing rule 13: names are normalised in exactly
# one way.

@pytest.fixture
def plural_graph():
    """An ontology whose label is the plural of what the CQ asks about."""
    g = rdflib.Graph()

    def cls(name):
        iri = URIRef(EX + name.replace(" ", "_"))
        g.add((iri, RDF.type, OWL.Class))
        g.add((iri, RDFS.label, rdflib.Literal(name)))
        return iri

    wound = cls("Wound")
    acute = cls("Acute Wounds")          # the ontology's spelling
    g.add((acute, RDFS.subClassOf, wound))
    return g


def test_label_index_is_the_shared_index_not_a_dict():
    from wound_ontology.utils.label_match import LabelIndex
    g = rdflib.Graph()
    iri = URIRef(EX + "Wound")
    g.add((iri, RDFS.label, rdflib.Literal("Wound")))
    assert isinstance(label_index(g), LabelIndex)


def test_a_cq_resolves_through_the_folded_fallback(plural_graph):
    """"Acute Wound" against a class labelled "Acute Wounds" -- one of the four
    label-index misses measured on 2026-09-10."""
    cq = CompetencyQuestion(id="CQx", question="?", in_scope=True,
                            triple=("Acute Wound", "is_a", "Wound"))
    (res,) = run_suite(plural_graph, [cq])
    assert res.verdict is Verdict.PASS


def test_a_variant_match_is_named_in_the_detail(plural_graph):
    """A pass on a folded key is still a pass, but it is a different fact about
    the ontology and the report has to say which one it was."""
    cq = CompetencyQuestion(id="CQx", question="?", in_scope=True,
                            triple=("Acute Wound", "is_a", "Wound"))
    (res,) = run_suite(plural_graph, [cq])
    assert "variant" in res.detail and "Acute Wound" in res.detail


def test_an_exact_match_says_nothing_extra(graph):
    cq = CompetencyQuestion(id="CQx", question="?", in_scope=True,
                            triple=("Chronic Wound", "is_a", "Wound"))
    (res,) = run_suite(graph, [cq])
    assert res.verdict is Verdict.PASS and res.detail == ""


def test_two_classes_sharing_a_folded_key_are_reported_as_such_not_as_absent():
    """Ambiguity is a third outcome. Calling it "no class labelled X" would send
    the curator looking for a class that is already there twice."""
    g = rdflib.Graph()
    for name in ("Phase", "PHASE "):
        iri = URIRef(EX + name.strip().replace(" ", "_") + name[-1])
        g.add((iri, RDF.type, OWL.Class))
        g.add((iri, RDFS.label, rdflib.Literal(name)))
    g.add((URIRef(EX + "Wound"), RDFS.label, rdflib.Literal("Wound")))
    cq = CompetencyQuestion(id="CQx", question="?", in_scope=True,
                            triple=("Phases", "is_a", "Wound"))
    (res,) = run_suite(g, [cq])
    assert res.verdict is Verdict.UNRESOLVED
    assert "several classes share that name" in res.detail


def test_a_genuinely_absent_class_is_still_unresolved(plural_graph):
    cq = CompetencyQuestion(id="CQx", question="?", in_scope=True,
                            triple=("Osteomyelitis", "is_a", "Wound"))
    (res,) = run_suite(plural_graph, [cq])
    assert res.verdict is Verdict.UNRESOLVED
