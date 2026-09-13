# -*- coding: utf-8 -*-
"""Competency questions as executable queries, not prompt text (C8).

`config/competency_questions.json` has always been read only to build a prompt
section. Its `example_triple` payloads are machine-checkable claims about what
the ontology must be able to answer, so this module compiles them into SPARQL
ASK queries and runs them against the artefact. That turns "justify the ontology
by its purpose" from an assertion into a measurement.

Four verdicts, and the third is the interesting one:

  PASS           the ontology answers the question.
  FAIL           it should and does not — a genuine coverage gap.
  UNEXPRESSIBLE  the question is phrased with a relation this ontology
                 deliberately does not have, so it can never pass as written and
                 counting it as a failure would be misleading. `affects` has no
                 IRI at all (removed in C3); `caused_by` asserts causation, which
                 MILD model commitment 4 explicitly rejects in favour of
                 co-location. These CQs predate those decisions and need
                 rewriting, not the ontology changing.
  UNRESOLVED     a term in the triple has no class with that label, so the
                 question cannot even be posed.

Out-of-scope questions are inverted: they PASS when the ontology does NOT answer
them, which is how scope boundaries get tested rather than merely declared.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import rdflib
from rdflib.namespace import RDF, RDFS, OWL
from rdflib import RDFS

from wound_ontology.utils.label_match import LabelIndex

OBO = "http://purl.obolibrary.org/obo/"
MILD = "https://bioportal.bioontology.org/ontologies/MILD/"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNEXPRESSIBLE = "UNEXPRESSIBLE"
    UNRESOLVED = "UNRESOLVED"
    # An out-of-scope question with no triple to test. It is NOT a pass: nothing
    # was checked. Counting these as passes would inflate the score with
    # questions the ontology was never asked, which is the sort of manufactured
    # success this pipeline exists to remove.
    DECLARED = "DECLARED"


# CQ predicate -> how to ask it of the ontology.
#   ("subclass", None)      transitive rdfs:subClassOf
#   ("restriction", IRI)    subClassOf* / restriction on that property
#   None                    deliberately not expressible; see module docstring
PREDICATE_MAP: dict[str, tuple[str, str] | None] = {
    "is_a": ("subclass", ""),
    "part_of": ("restriction", OBO + "BFO_0000050"),
    "has_quality": ("restriction", OBO + "RO_0000086"),
    "occurs_in": ("restriction", OBO + "BFO_0000066"),
    "has_part": ("restriction", OBO + "BFO_0000051"),
    "is_treatment_for": ("restriction", OBO + "RO_0002606"),
    # The relation MILD actually licenses in place of aetiology. "X co_located_with
    # Y" asks whether the ontology says X and Y are parts of one material disease
    # entity in one patient -- which is assertable -- rather than whether Y caused
    # X, which model commitment 4 refuses. This is the target form for every CQ
    # that was originally written with caused_by.
    "co_located_with": ("colocation", MILD + "MILD_120020"),
    # ---- deliberately unexpressible ----
    "affects": None,      # no IRI; removed in C3 as unmappable
    "caused_by": None,    # MILD commitment 4: aetiology is not asserted causally
}

UNEXPRESSIBLE_REASON: dict[str, str] = {
    "affects": ("'affects' has no IRI and was removed in C3 as unmappable. "
                "Rewrite the CQ using a located-in or participates-in relation."),
    "caused_by": ("MILD model commitment 4 rejects causal aetiology: what a "
                  "disease causes cannot be reliably separated from what it is. "
                  "Rewrite the CQ with 'co_located_with', which asks the "
                  "assertable question, or as a predisposition."),
}


@dataclass
class CompetencyQuestion:
    id: str
    question: str
    theme: str = ""
    triple: tuple[str, str, str] | None = None
    in_scope: bool = True
    reason: str = ""


@dataclass
class CQResult:
    cq: CompetencyQuestion
    verdict: Verdict
    detail: str = ""
    query: str = ""


def load_questions(path: str | Path) -> list[CompetencyQuestion]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[CompetencyQuestion] = []
    for theme_block in data.get("clinical_themes", []):
        theme = theme_block.get("theme", "")
        for q in theme_block.get("in_scope", []):
            t = q.get("example_triple")
            out.append(CompetencyQuestion(
                id=q["id"], question=q["question"], theme=theme,
                triple=tuple(t) if t and len(t) == 3 else None, in_scope=True))
        for q in theme_block.get("out_of_scope", []):
            out.append(CompetencyQuestion(
                id=q["id"], question=q["question"], theme=theme,
                triple=None, in_scope=False, reason=q.get("reason", "")))
    for q in data.get("global_out_of_scope", []):
        out.append(CompetencyQuestion(
            id=q["id"], question=q["question"], theme=q.get("category", ""),
            triple=None, in_scope=False))
    return out


ALT_TERM = rdflib.URIRef(OBO + "IAO_0000118")


def label_index(graph: rdflib.Graph) -> LabelIndex:
    """Label -> IRI, including IAO_0000118 alternative terms.

    Preferred labels win over synonyms, so a synonym never shadows a real label.
    Matching is case-insensitive because the CQs are written in clinical prose
    while the ontology labels follow its own casing convention.

    This used to build a plain ``{lower(label): iri}`` dict and match on the
    exact string only, which is a second normalisation rule living alongside
    :class:`~wound_ontology.utils.label_match.LabelIndex` -- the one the rest of
    the pipeline uses, which already carries the folded fallback. Two rules for
    one job is what standing rule 13 forbids, and the cost was measurable: a CQ
    asking about "Acute Wound" could not see a class labelled "Acute Wounds".

    ``preferred=False`` throughout is deliberate and preserves the old
    behaviour exactly: labels are added before alternative terms, so whoever
    claims a key first keeps it, and resolution does not depend on graph
    iteration order.
    """
    idx = LabelIndex()
    for s, o in graph.subject_objects(RDFS.label):
        if isinstance(s, rdflib.URIRef):
            idx.add(str(o), s, preferred=False)
    for s, o in graph.subject_objects(ALT_TERM):
        if isinstance(s, rdflib.URIRef):
            idx.add(str(o), s, preferred=False)
    return idx


def compile_ask(subject_iri: str, predicate: str, object_iri: str) -> str | None:
    """SPARQL ASK for one CQ triple, or None if the predicate is unexpressible."""
    spec = PREDICATE_MAP.get(predicate)
    if spec is None:
        return None
    kind, prop = spec
    if kind == "subclass":
        return (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            f"ASK {{ <{subject_iri}> rdfs:subClassOf* <{object_iri}> }}"
        )
    if kind == "colocation":
        # Returned for display and provenance only. Co-location is evaluated by
        # colocation_holds() below, not by SPARQL: the pattern needs two
        # unbounded rdfs:subClassOf* walks plus a list traversal, and over the
        # ~220k-triple import closure rdflib's path evaluation does not finish.
        # A hand-written traversal that starts from the (very few) MILD_120020
        # intersections is milliseconds instead.
        return (
            f"# co-location check (evaluated natively, not via SPARQL)\n"
            f"# ASK: <{subject_iri}> subClassOf/equivalentClass\n"
            f"#        Wound and part_of some (<{prop}> and has_part some <{object_iri}>)"
        )
    # A restriction may be asserted as a necessary condition (rdfs:subClassOf)
    # or sit inside a defining axiom (owl:equivalentClass of an intersection).
    # The second entails the first, and it is how WONT states every
    # determinate-defined class ("Open wound ≡ Wound and has_quality some
    # open"), so a checker that only walked rdfs:subClassOf reported those as
    # FAIL -- measured 2026-09-12: 8 of the 9 has_quality CQs.
    return (
        "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
        "ASK {\n"
        f"  <{subject_iri}> rdfs:subClassOf* ?c .\n"
        "  { ?c rdfs:subClassOf ?r }\n"
        "  UNION\n"
        "  { ?c owl:equivalentClass/owl:intersectionOf/rdf:rest*/rdf:first ?r }\n"
        f"  ?r owl:onProperty <{prop}> ; owl:someValuesFrom ?target .\n"
        f"  ?target rdfs:subClassOf* <{object_iri}> .\n"
        "}"
    )



def _list_members(graph: rdflib.Graph, node) -> list:
    """Members of an owl:intersectionOf / rdf:List, flattened one level."""
    out, seen = [], set()
    for coll in graph.objects(node, OWL.intersectionOf):
        cur = coll
        while cur and cur != RDF.nil and cur not in seen:
            seen.add(cur)
            for item in graph.objects(cur, RDF.first):
                out.append(item)
            cur = graph.value(cur, RDF.rest)
    return out


def _ancestors(graph: rdflib.Graph, node, limit: int = 5000) -> set:
    """Named rdfs:subClassOf* ancestors of node, including node itself."""
    seen, stack = {node}, [node]
    while stack and len(seen) < limit:
        cur = stack.pop()
        for parent in graph.objects(cur, RDFS.subClassOf):
            if isinstance(parent, rdflib.URIRef) and parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def colocation_holds(graph: rdflib.Graph, subject_iri, object_iri,
                     disease_cls=None) -> bool:
    """Does the ontology assert subject and object are co-located?

    True when subject is asserted (or inherits) an axiom of the Structure-2
    shape used throughout WONT:

        subject  =  Wound and part_of some (material disease entity
                                            and has_part some object)

    This is the relation MILD licenses in place of aetiology. It is emphatically
    not a causal claim -- it says only that the two are parts of one material
    disease entity in one patient.
    """
    disease_cls = disease_cls or rdflib.URIRef(MILD + "MILD_120020")
    part_of = rdflib.URIRef(OBO + "BFO_0000050")
    has_part = rdflib.URIRef(OBO + "BFO_0000051")
    subject_iri = rdflib.URIRef(str(subject_iri))
    object_iri = rdflib.URIRef(str(object_iri))

    # Start from the handful of intersections mentioning MILD_120020 -- the most
    # selective anchor in the graph -- and keep the ones whose has_part filler
    # subsumes the object.
    good_disease = set()
    for node in set(graph.subjects(OWL.intersectionOf, None)):
        members = _list_members(graph, node)
        if disease_cls not in members:
            continue
        for m in members:
            if isinstance(m, rdflib.URIRef):
                continue
            if graph.value(m, OWL.onProperty) != has_part:
                continue
            filler = graph.value(m, OWL.someValuesFrom)
            if filler is None:
                continue
            if object_iri in _ancestors(graph, filler):
                good_disease.add(node)
    if not good_disease:
        return False

    # Restrictions part_of-ing one of those disease intersections.
    good_restr = {
        r for r in graph.subjects(OWL.onProperty, part_of)
        if graph.value(r, OWL.someValuesFrom) in good_disease
    }
    if not good_restr:
        return False

    # Reachable from the subject, directly or through a named ancestor, and
    # through either subClassOf or equivalentClass, flattening intersections.
    for cls in _ancestors(graph, subject_iri):
        for side in (RDFS.subClassOf, OWL.equivalentClass):
            for expr in graph.objects(cls, side):
                if expr in good_restr:
                    return True
                if any(m in good_restr for m in _list_members(graph, expr)):
                    return True
    return False


def _answerable(graph: rdflib.Graph, idx: dict, cq: CompetencyQuestion):
    """(verdict, detail, query) for an in-scope CQ."""
    if cq.triple is None:
        return Verdict.UNRESOLVED, "no example_triple to compile", ""
    subj, pred, obj = cq.triple
    if PREDICATE_MAP.get(pred, "missing") is None:
        return (Verdict.UNEXPRESSIBLE,
                UNEXPRESSIBLE_REASON.get(pred, f"'{pred}' is not expressible"), "")
    if pred not in PREDICATE_MAP:
        return Verdict.UNEXPRESSIBLE, f"unknown CQ predicate '{pred}'", ""

    s_iri, s_how = idx.get(subj)
    o_iri, o_how = idx.get(obj)
    missing = [(n, h) for n, v, h in ((subj, s_iri, s_how), (obj, o_iri, o_how))
               if v is None]
    if missing:
        # Distinguish a label mismatch from a genuine vocabulary gap: the CQs are
        # written in clinical prose ("Wound Bed") while the ontology has its own
        # label ("Wound base"). A near miss means fix the CQ; no near miss means
        # the concept really is absent.
        #
        # 'ambiguous' is a third thing again -- several classes fold to the same
        # key, so a match exists but choosing one would attach the verdict to a
        # coin flip. Say so rather than reporting it as absent.
        hints = []
        for name, how in missing:
            if how == "ambiguous":
                hints.append(f"{name!r} (several classes share that name)")
                continue
            close = difflib.get_close_matches(name.strip().lower(), idx.keys(),
                                              n=1, cutoff=0.75)
            hints.append(f"{name!r}" + (f" (did you mean {close[0]!r}?)" if close else ""))
        return Verdict.UNRESOLVED, "no class labelled " + ", ".join(hints), ""

    q = compile_ask(str(s_iri), pred, str(o_iri))
    if PREDICATE_MAP[pred][0] == "colocation":
        ok = colocation_holds(graph, s_iri, o_iri)
    else:
        ok = bool(graph.query(q).askAnswer)
    # A label matched on its folded key rather than as written is still a pass,
    # but it is a different fact about the ontology and the report should say so.
    variants = [f"{n!r} matched as a variant" for n, h in
                ((subj, s_how), (obj, o_how)) if h == "variant"]
    note = "; ".join(variants)
    if ok:
        return Verdict.PASS, note, q
    return Verdict.FAIL, "; ".join(["query returned false"] + variants), q


def run_suite(graph: rdflib.Graph, questions) -> list[CQResult]:
    idx = label_index(graph)
    results: list[CQResult] = []
    for cq in questions:
        if cq.in_scope:
            verdict, detail, query = _answerable(graph, idx, cq)
        elif cq.triple is None:
            verdict, detail, query = (
                Verdict.DECLARED,
                "out of scope, no triple supplied — nothing was tested", "")
        else:
            # A negative test: the ontology passes by NOT answering this.
            verdict, detail, query = _answerable(graph, idx, cq)
            if verdict is Verdict.PASS:
                verdict, detail = Verdict.FAIL, "out-of-scope claim IS answerable"
            elif verdict is Verdict.FAIL:
                verdict, detail = Verdict.PASS, "correctly not answerable"
        results.append(CQResult(cq=cq, verdict=verdict, detail=detail, query=query))
    return results


def summarize(results) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict.value] = counts.get(r.verdict.value, 0) + 1
    return counts


def in_scope_score(results) -> tuple[int, int]:
    """(passing, testable) over in-scope questions only.

    UNEXPRESSIBLE questions are excluded from the denominator: they cannot pass
    as written because they use relations the ontology deliberately rejects, so
    counting them as failures would blame the ontology for the CQ's phrasing.
    """
    testable = [r for r in results
                if r.cq.in_scope and r.verdict is not Verdict.UNEXPRESSIBLE]
    passing = [r for r in testable if r.verdict is Verdict.PASS]
    return len(passing), len(testable)


def report(results, show: int = 0) -> str:
    p, n = in_scope_score(results)
    lines = [f"Competency questions: {len(results)}",
             f"  in-scope score: {p}/{n} "
             f"({(100.0 * p / n) if n else 0:.0f}%)"]
    for k, v in sorted(summarize(results).items()):
        lines.append(f"  {k:<14} {v}")
    for verdict in (Verdict.FAIL, Verdict.UNEXPRESSIBLE, Verdict.UNRESOLVED):
        hits = [r for r in results if r.verdict is verdict]
        if not hits:
            continue
        lines.append(f"\n{verdict.value} ({len(hits)}):")
        for r in hits[: show or len(hits)]:
            t = " ".join(r.cq.triple) if r.cq.triple else "-"
            lines.append(f"  {r.cq.id:<10} {t:<62} {r.detail}")
    return "\n".join(lines)
