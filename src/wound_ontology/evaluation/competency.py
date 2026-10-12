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
    # RO_0001025 located in: a wound is located in a body part (Diabetic foot
    # ulcer = Diabetic wound and located_in some Foot), never part of it.
    "located_in": ("restriction", OBO + "RO_0001025"),
    # RO_0000057 has participant: a process CQ may ask what takes part in it
    # (CQ100 asks it of clinical wound assessment and the wound).
    "has_participant": ("restriction", OBO + "RO_0000057"),
    # RO_0000056 participates in: the curator's form for treatment questions
    # (2026-09-17) -- an agent (dressing, drug, device) participates in a
    # treatment process; is_treatment_for is not needed for them.
    "participates_in": ("restriction", OBO + "RO_0000056"),
    # IAO_0000136 is about: a classification grade (an ICE individual such as
    # 'Proliferative phase') is about the processes it labels.
    "is_about": ("restriction", OBO + "IAO_0000136"),
    "is_treatment_for": ("restriction", OBO + "RO_0002606"),
    # RO_0002353 output of (not OBI_0000312 is_specified_output_of: a wound
    # development process is not a planned process). WONT defines its
    # aetiological wound classes this way (Traumatic wound = Wound and
    # output_of some Wound causing trauma process), so a CQ may ask which
    # process a wound class is the output of.
    "output_of": ("restriction", OBO + "RO_0002353"),
    # The relation MILD licenses in place of aetiology (commitment 4, as amended
    # 2026-09-17). "X complication_of Y" asks whether X is the output of a
    # development process that has, as a part, a wound causing process of Y's
    # disease course -- MILD_120053's pattern -- rather than whether Y caused X,
    # which stays refused. Evaluated natively by complication_holds(). This is
    # the target form for every CQ originally written with caused_by; it
    # replaced co_located_with, which only asserted that a diagnostic
    # classification files the two under one disease.
    "complication_of": ("complication", OBO + "RO_0002353"),
    # ---- deliberately unexpressible ----
    "affects": None,      # no IRI; removed in C3 as unmappable
    "caused_by": None,    # MILD commitment 4: aetiology is not asserted causally
}

UNEXPRESSIBLE_REASON: dict[str, str] = {
    "affects": ("'affects' has no IRI and was removed in C3 as unmappable. "
                "Rewrite the CQ using a located-in or participates-in relation."),
    "caused_by": ("MILD model commitment 4 rejects causal aetiology: what a "
                  "disease causes cannot be reliably separated from what it is. "
                  "Rewrite the CQ with 'complication_of', which asks the "
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
    # Classes before individuals, own before imported, sorted within each: "first claim wins"
    # only means something if the order is fixed. It was rdflib's hash order,
    # and WONT labels a quality class AND an IWII grade individual
    # `contaminated` (and `infected`), so CQ040/CQ093 passed or failed
    # depending on the run (found 2026-09-28 on the split extension).
    classes = set(graph.subjects(RDF.type, OWL.Class))

    def ordered(pred):
        rows = [(s, o) for s, o in graph.subject_objects(pred) if isinstance(s, rdflib.URIRef)]
        # Then the ontology's OWN classes before imported ones: WONT has its own
        # `chronic` because PATO's is a duration of a process (a false friend),
        # and its own `Pressure ulcer` beside HP's phenotype of that name.
        own = ("https://bioportal.bioontology.org/ontologies/WONT/",
               "https://bioportal.bioontology.org/ontologies/MILD/")
        return sorted(rows, key=lambda so: (so[0] not in classes,
                                            not str(so[0]).startswith(own),
                                            str(so[0]), str(so[1])))

    idx = LabelIndex()
    for s, o in ordered(RDFS.label):
        idx.add(str(o), s, preferred=False)
    for s, o in ordered(ALT_TERM):
        idx.add(str(o), s, preferred=False)
    return idx


def compile_ask(subject_iri: str, predicate: str, object_iri: str) -> str | None:
    """SPARQL ASK for one CQ triple, or None if the predicate is unexpressible."""
    spec = PREDICATE_MAP.get(predicate)
    if spec is None:
        return None
    kind, prop = spec
    if kind == "subclass":
        # A class defined as `X = Y and ...` is a subclass of Y by entailment;
        # WONT states every aetiological wound class that way, and the asserted
        # rdfs:subClassOf beside the equivalence is convention, not guaranteed.
        # The subject may be an individual (WONT's classification grades --
        # 'Inflammatory phase' is an instance of 'Wound healing phase', by the
        # decision that grades are individuals); then the first step is rdf:type.
        return (
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
            f"ASK {{ <{subject_iri}> rdf:type?/(rdfs:subClassOf|owl:equivalentClass/owl:intersectionOf/rdf:rest*/rdf:first)* <{object_iri}> }}"
        )
    if kind == "complication":
        # Returned for display and provenance only; evaluated natively by
        # complication_holds() -- the pattern nests three restrictions and two
        # intersections, which is faster and clearer as a traversal.
        return (
            f"# complication check (evaluated natively, not via SPARQL)\n"
            f"# ASK: <{subject_iri}> subClassOf/equivalentClass\n"
            f"#        Wound and output_of some (Wound development process\n"
            f"#          and has_part some P), P a process of <{object_iri}>'s course"
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
        # An individual carries the relation as a plain assertion
        # ('Proliferative phase' is_about 'Granulation tissue formation
        # process'), or inherits a restriction through its type.
        "  {\n"
        f"    <{subject_iri}> <{prop}> ?f .\n"
        "  } UNION {\n"
        f"    <{subject_iri}> rdf:type?/rdfs:subClassOf* ?c .\n"
        "    { ?c rdfs:subClassOf ?r }\n"
        "    UNION\n"
        "    { ?c owl:equivalentClass/owl:intersectionOf/rdf:rest*/rdf:first ?r }\n"
        f"    ?r owl:onProperty <{prop}> ; owl:someValuesFrom ?f .\n"
        "  }\n"
        # The filler may itself be an intersection (Malignant wound = Wound and
        # output_of some (Wound development process and has_part some ...));
        # any named member of it counts, since the intersection is subsumed by
        # each of its members.
        "  ?f (owl:intersectionOf/rdf:rest*/rdf:first)? ?target .\n"
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


def _process_of(graph: rdflib.Graph, proc, object_iri) -> bool:
    """Is `proc` (a process class, possibly anonymous) a process of the
    object's course? True when a named ancestor of proc is the object, or
    carries `has_participant some X` with X subsumed by the object -- the two
    ways WONT names a disease process (Angiopathic disease process is a
    subclass; Venous insufficiency disease process has the disorder as
    participant)."""
    has_participant = rdflib.URIRef(OBO + "RO_0000057")
    named = [proc] if isinstance(proc, rdflib.URIRef) else [
        m for m in _list_members(graph, proc) if isinstance(m, rdflib.URIRef)]
    # Ancestors through rdfs:subClassOf AND through the named members of an
    # equivalentClass intersection: `Wound causing trauma process = Trauma
    # process and Wound causing process` makes Trauma process a superclass
    # without any rdfs:subClassOf saying so.
    seen: set = set()
    stack = list(named)
    while stack:
        n = stack.pop()
        for cls in _ancestors(graph, n):
            if cls in seen:
                continue
            seen.add(cls)
            for expr in graph.objects(cls, OWL.equivalentClass):
                stack.extend(m for m in _list_members(graph, expr)
                             if isinstance(m, rdflib.URIRef) and m not in seen)
    if object_iri in seen:
        return True
    for cls in seen:
        for side in (RDFS.subClassOf, OWL.equivalentClass):
            for expr in graph.objects(cls, side):
                for r in [expr] + _list_members(graph, expr):
                    if (graph.value(r, OWL.onProperty) == has_participant
                            and object_iri in _ancestors(graph, graph.value(r, OWL.someValuesFrom) or r)):
                        return True
    return False


def complication_holds(graph: rdflib.Graph, subject_iri, object_iri) -> bool:
    """Does the ontology assert that subject is a complication of object?

    True when subject is asserted (or inherits) an axiom of the shape WONT
    uses for every aetiological wound class since 2026-09-17:

        subject = Wound and output_of some (Wound development process
                                             and has_part some P)

    with P a wound causing process of the object's disease course (P is the
    object, a subclass of it, or a process that has the object as
    participant). A direct `output_of some P` with P of the object's course
    counts too (Traumatic wound = Wound and output_of some Wound causing
    trauma process). This is MILD_120053's pattern: a disorder put out by a
    process in another disease's course. It is emphatically not a causal
    claim between the two disorders (MILD commitment 4).
    """
    output_of = rdflib.URIRef(OBO + "RO_0002353")
    has_part = rdflib.URIRef(OBO + "BFO_0000051")
    subject_iri = rdflib.URIRef(str(subject_iri)); object_iri = rdflib.URIRef(str(object_iri))
    for cls in _ancestors(graph, subject_iri):
        for side in (RDFS.subClassOf, OWL.equivalentClass):
            for expr in graph.objects(cls, side):
                for r in [expr] + _list_members(graph, expr):
                    if graph.value(r, OWL.onProperty) != output_of:
                        continue
                    filler = graph.value(r, OWL.someValuesFrom)
                    if filler is None:
                        continue
                    if _process_of(graph, filler, object_iri):
                        return True
                    for m in _list_members(graph, filler):
                        if (graph.value(m, OWL.onProperty) == has_part
                                and _process_of(graph, graph.value(m, OWL.someValuesFrom), object_iri)):
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
    if PREDICATE_MAP[pred][0] == "complication":
        ok = complication_holds(graph, s_iri, o_iri)
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
