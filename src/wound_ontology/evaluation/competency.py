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
from rdflib import RDFS

OBO = "http://purl.obolibrary.org/obo/"


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
    # ---- deliberately unexpressible ----
    "affects": None,      # no IRI; removed in C3 as unmappable
    "caused_by": None,    # MILD commitment 4: aetiology is not asserted causally
}

UNEXPRESSIBLE_REASON: dict[str, str] = {
    "affects": ("'affects' has no IRI and was removed in C3 as unmappable. "
                "Rewrite the CQ using a located-in or participates-in relation."),
    "caused_by": ("MILD model commitment 4 rejects causal aetiology: what a "
                  "disease causes cannot be reliably separated from what it is. "
                  "Rewrite the CQ as co-location, or as a predisposition."),
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


def label_index(graph: rdflib.Graph) -> dict[str, rdflib.URIRef]:
    """Label -> IRI, including IAO_0000118 alternative terms.

    Preferred labels win over synonyms, so a synonym never shadows a real label.
    Matching is case-insensitive because the CQs are written in clinical prose
    while the ontology labels follow its own casing convention.
    """
    idx: dict[str, rdflib.URIRef] = {}
    for s, o in graph.subject_objects(RDFS.label):
        if isinstance(s, rdflib.URIRef):
            idx.setdefault(str(o).strip().lower(), s)
    for s, o in graph.subject_objects(ALT_TERM):
        if isinstance(s, rdflib.URIRef):
            idx.setdefault(str(o).strip().lower(), s)
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
    return (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
        "ASK {\n"
        f"  <{subject_iri}> rdfs:subClassOf*/rdfs:subClassOf ?r .\n"
        f"  ?r owl:onProperty <{prop}> ; owl:someValuesFrom ?target .\n"
        f"  ?target rdfs:subClassOf* <{object_iri}> .\n"
        "}"
    )


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

    s_iri = idx.get(subj.strip().lower())
    o_iri = idx.get(obj.strip().lower())
    missing = [n for n, v in ((subj, s_iri), (obj, o_iri)) if v is None]
    if missing:
        # Distinguish a label mismatch from a genuine vocabulary gap: the CQs are
        # written in clinical prose ("Wound Bed") while the ontology has its own
        # label ("Wound base"). A near miss means fix the CQ; no near miss means
        # the concept really is absent.
        hints = []
        for name in missing:
            close = difflib.get_close_matches(name.strip().lower(), idx.keys(),
                                              n=1, cutoff=0.75)
            hints.append(f"{name!r}" + (f" (did you mean {close[0]!r}?)" if close else ""))
        return Verdict.UNRESOLVED, "no class labelled " + ", ".join(hints), ""

    q = compile_ask(str(s_iri), pred, str(o_iri))
    ok = bool(graph.query(q).askAnswer)
    return (Verdict.PASS if ok else Verdict.FAIL,
            "" if ok else "query returned false", q)


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
