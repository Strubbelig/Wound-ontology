#!/usr/bin/env python
"""Textual definitions for WONT's classes that have none (2026-10-30).

    python -u scripts/claude_write_definitions.py                 # dry run: rows, one prompt
    python -u scripts/claude_write_definitions.py --test 20       # send the first 20 rows, wait, show
    python -u scripts/claude_write_definitions.py --submit --wait # all rows, as one batch run
    python -u scripts/claude_write_definitions.py --write         # the definitions into a new WONT file

The thesis (MIRO): "Definitionen für die übrigen Klassen, größtenteils die
Blattklassen der Behandlungsmittel und Medizinprodukte, sind vor der
Veröffentlichung zu schreiben. Dies ist der größte offene Punkt nach MIRO."
The curator: "dann mach es". 299 of WONT's 439 classes had no IAO_0000115.

Claude (Opus 5.5, OpenRouter batch, as the readings) writes one sentence per
class in genus-differentia form: "A <parent label> that ...", the genus the
parent's label as WONT's own definitions have it ("A material disease entity
that is the output of a wound development process"). It sees the class's
label, synonyms, comments and logical axioms, its parent's definition, and up
to three definitions of its siblings as the house style; it states only what
is true of every instance and answers `cannot` where no sound definition can
be written. A definition whose genus is not a parent's label is not written.

`--write` puts each definition on its class as IAO_0000115, with IAO_0000119
(definition source) saying it was drafted by Claude for the curator to
review, into `ground_truth_final_2026-10-30b.owl` (from `..._2026-10-30.owl`);
the rows not written, and why, go to the review list beside the run.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

GT_DIR = ROOT / "data" / "ground truth"
# the run was sent on `..._2026-10-30.owl`; the definitions go into the file that
# by then also had Wound's definition and Injury's location (same classes
# without a definition, same rows, same order -- checked by `write`)
WONT_SENT = GT_DIR / "ground_truth_final_2026-10-30.owl"
WONT_OLD, WONT_NEW = GT_DIR / "ground_truth_final_2026-10-30c.owl", GT_DIR / "ground_truth_final_2026-10-30d.owl"
RUN_DIR = ROOT / "data" / "llm_runs" / "claude_definitions_2026-10-30"
REVIEW = RUN_DIR / "review.md"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
OBO = "http://purl.obolibrary.org/obo/"
OIO = "http://www.geneontology.org/formats/oboInOwl#"
ROWS_PER_REQUEST = 20
SOURCE = ("Drafted by Claude (Anthropic, claude-opus-5.5) on 2026-10-30 from the class's label, synonyms, axioms, "
          "parent and siblings, at the curator's request; to be reviewed by the curator.")

SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {"row": {"type": "integer"},
                       "status": {"type": "string", "enum": ["defined", "cannot"]},
                       "definition": {"type": "string"},
                       "why": {"type": "string"}},
        "required": ["row", "status", "definition", "why"],
        "additionalProperties": False}}},
    "required": ["answers"],
    "additionalProperties": False,
}

INSTRUCTIONS = """\
You are writing textual definitions for classes of WONT, a wound ontology for
publication. WONT is built on MILD (a disease ontology: a disease is a material
disease entity, a material entity in a patient that medicine classifies as
pathological), on OBO ontologies and on BFO 2020. Each row below is one class
that has no definition yet.

For each row write ONE English sentence in genus-differentia form:
* Begin with "A" or "An" followed by the GENUS: the label of the class's parent
  exactly as given under "parent" (keep its spelling; lower-case its first
  letter unless it is a proper name or an abbreviation), then "that ..." (or
  "used ...", "consisting of ...") with the DIFFERENTIA: what sets this class
  apart from its parent and its siblings.
* Use what the label, synonyms, comments and logical axioms say, and the
  established meaning of the term in wound care, surgery and medicine.
* State only what is true of EVERY instance. No examples, no brand or product
  names, no indications or claims of effectiveness, no numbers or measurements
  unless the class is named by them (a thread size designation, a grade).
* Not circular: the differentia must not merely repeat the label's words.
* Match the style of the parent's definition and of the siblings' definitions
  where they are given.
* If no sound definition can be written -- the label is unclear, or the parent
  does not fit what the label names -- answer status "cannot", leave
  "definition" empty and say why. Do not guess.

Answer for every row: row, status ("defined" or "cannot"), definition, why
(one short sentence: what the differentia rests on, or why it cannot be written).
"""


def labels_index():
    """Labels of every class and property WONT names: WONT, MILD, the modules, RO and BFO."""
    import rdflib
    from rdflib import RDFS
    from config.settings import BFO_OWL, GROUND_TRUTH_TTL, MILD_TTL, RO_OWL
    from wound_ontology.owl.extend import default_lexicon
    from wound_ontology.utils.rdf_io import parse_graph
    lab = {}
    for path in [GROUND_TRUTH_TTL, MILD_TTL, *default_lexicon(), RO_OWL, BFO_OWL]:
        p = Path(path)
        g = parse_graph(p, context="definitions") if p.suffix != ".ttl" and "ground_truth" not in p.name \
            else rdflib.Graph().parse(str(p), format="turtle")
        for s, o in g.subject_objects(RDFS.label):
            lab.setdefault(str(s), str(o))
    return lab


def manchester(g, node, lab) -> str:
    """A class expression in short Manchester form, labels for names."""
    import rdflib
    from rdflib import OWL
    from rdflib.collection import Collection
    if isinstance(node, rdflib.URIRef):
        return f"'{lab.get(str(node), str(node).rsplit('/', 1)[-1])}'"
    p, f = g.value(node, OWL.onProperty), g.value(node, OWL.someValuesFrom)
    if p is not None and f is not None:
        return f"'{lab.get(str(p), str(p).rsplit('/', 1)[-1])}' some {manchester(g, f, lab)}"
    for op, word in ((OWL.intersectionOf, " and "), (OWL.unionOf, " or ")):
        lst = g.value(node, op)
        if lst is not None:
            return "(" + word.join(manchester(g, m, lab) for m in Collection(g, lst)) + ")"
    return "(...)"


def build_rows(g, lab) -> list[dict]:
    import rdflib
    from rdflib import OWL, RDF, RDFS, URIRef
    iao115, iao118, iao116 = URIRef(OBO + "IAO_0000115"), URIRef(OBO + "IAO_0000118"), URIRef(OBO + "IAO_0000116")
    defined = {s: str(o) for s, o in g.subject_objects(iao115)}
    children = defaultdict(list)
    for c, p in g.subject_objects(RDFS.subClassOf):
        if isinstance(p, URIRef):
            children[p].append(c)
    rows = []
    for c in sorted({c for c in g.subjects(RDF.type, OWL.Class) if str(c).startswith(W)}, key=str):
        if c in defined or (c, OWL.deprecated, None) in g:
            continue
        parents = [p for p in g.objects(c, RDFS.subClassOf) if isinstance(p, URIRef)]
        parents.sort(key=lambda p: (not str(p).startswith(W), str(p)))
        if not parents:
            continue
        sib = [s for p in parents for s in children[p] if s != c and s in defined][:3]
        axioms = [f"SubClassOf {manchester(g, o, lab)}" for o in g.objects(c, RDFS.subClassOf)
                  if isinstance(o, rdflib.BNode)]
        axioms += [f"EquivalentTo {manchester(g, o, lab)}" for o in g.objects(c, OWL.equivalentClass)]
        syn = sorted({str(o) for p_ in (iao118, URIRef(OIO + "hasExactSynonym"), URIRef(OIO + "hasRelatedSynonym"))
                      for o in g.objects(c, p_)})
        comments = [str(o)[:400] for p_ in (RDFS.comment, iao116) for o in g.objects(c, p_)]
        rows.append({"iri": str(c), "label": lab.get(str(c), ""),
                     "parents": [lab.get(str(p), str(p)) for p in parents],
                     "parent_definition": defined.get(parents[0], ""),
                     "synonyms": syn, "comments": comments, "axioms": axioms,
                     "siblings": [f"{lab.get(str(s), '')}: {defined[s]}" for s in sib]})
    return rows


def prompt(chunk) -> str:
    parts = [INSTRUCTIONS, "\nROWS\n"]
    for r in chunk:
        parts.append(f"\nrow {r['row']}: '{r['label']}'")
        parts.append(f"  parent: {' ; '.join(repr(p) for p in r['parents'])}")
        if r["parent_definition"]:
            parts.append(f"  parent's definition: {r['parent_definition']}")
        for k in ("synonyms", "axioms", "comments", "siblings"):
            if r[k]:
                parts.append(f"  {k}: " + " | ".join(r[k]))
    return "\n".join(parts)


def requests_of(rows):
    from wound_ontology.llm.claude_batch import request_body
    out = []
    for i in range(0, len(rows), ROWS_PER_REQUEST):
        chunk = [dict(r, row=j + 1) for j, r in enumerate(rows[i:i + ROWS_PER_REQUEST])]
        out.append((f"d{i // ROWS_PER_REQUEST:04d}", request_body(prompt(chunk), SCHEMA), chunk))
    return out


def genus_ok(definition: str, parents: list[str]) -> bool:
    d = re.sub(r"\s+", " ", definition.strip()).lower()
    return any(re.match(rf"an? {re.escape(p.strip().lower())}\b", d) for p in parents)


def main(argv) -> int:
    import rdflib
    from wound_ontology.llm.claude_batch import BatchRun
    g = rdflib.Graph().parse(WONT_OLD, format="turtle")
    lab = labels_index()
    rows = build_rows(g, lab)
    reqs = requests_of(rows)
    print(f"[definitions] {len(rows)} class(es) without a definition; {len(reqs)} request(s)")
    if not argv:
        sample = ROOT / "output" / "claude_definitions_prompt_example.txt"
        sample.write_text(prompt([dict(r, row=j + 1) for j, r in enumerate(rows[:ROWS_PER_REQUEST])]), encoding="utf-8")
        print(f"[definitions] dry run; one prompt in {sample.relative_to(ROOT)}")
        return 0
    if "--test" in argv:
        n = int(argv[argv.index("--test") + 1])
        run = BatchRun(RUN_DIR.with_name(RUN_DIR.name + f"_test{n}"))
        test = requests_of(rows[:n])
        run.submit([(c, b) for c, b, _ in test])
        run.wait(poll=20)
        ans = run.answers()
        for c, _, chunk in test:
            got = {a["row"]: a for a in (ans[c].answer or {}).get("answers", [])}
            for r in chunk:
                a = got.get(r["row"], {})
                ok = "" if a.get("status") != "defined" or genus_ok(a.get("definition", ""), r["parents"]) else "  [GENUS?]"
                print(f"  {r['label']}  <  {r['parents'][0]}\n     {a.get('status')}: {a.get('definition') or a.get('why')}{ok}")
        print(f"[definitions] test cost ${run.cost():.4f}")
        return 0
    run = BatchRun(RUN_DIR)
    if "--submit" in argv:
        print(f"[definitions] sent {run.submit([(c, b) for c, b, _ in reqs])} request(s)")
    if "--wait" in argv:
        run.wait()
    if "--write" not in argv:
        return 0
    return write(g, run, reqs)


def write(g, run, reqs) -> int:
    import rdflib
    from rdflib import Literal, URIRef
    sent = [r["iri"] for _, _, chunk in requests_of(build_rows(rdflib.Graph().parse(WONT_SENT, format="turtle"),
                                                               labels_index())) for r in chunk]
    if sent != [r["iri"] for _, _, chunk in reqs for r in chunk]:
        raise RuntimeError("the rows of the file written into are not the rows the run was sent with")
    ans = run.answers()
    missing = [c for c, _, _ in reqs if c not in ans or ans[c].error or not ans[c].answer]
    if missing:
        print(f"[definitions] *** {len(missing)} request(s) without an answer; nothing written: {missing[:5]} ***")
        return 1
    written, held = [], []
    for c, _, chunk in reqs:
        got = {a["row"]: a for a in ans[c].answer["answers"]}
        for r in chunk:
            a = got.get(r["row"])
            if a is None:
                held.append((r, "no answer for this row"))
            elif a["status"] != "defined" or not a["definition"].strip():
                held.append((r, f"cannot: {a['why']}"))
            elif not genus_ok(a["definition"], r["parents"]):
                held.append((r, f"genus is not a parent's label: {a['definition']}"))
            else:
                written.append((r, a))
    out = g.__class__()
    for pfx, ns in g.namespaces():
        out.bind(pfx, ns)
    for t in g:
        out.add(t)
    for r, a in written:
        s = URIRef(r["iri"])
        out.add((s, URIRef(OBO + "IAO_0000115"), Literal(a["definition"].strip(), lang="en")))
        out.add((s, URIRef(OBO + "IAO_0000119"), Literal(SOURCE, lang="en")))
    if WONT_NEW.exists():
        raise RuntimeError(f"{WONT_NEW} exists; not overwritten")
    out.serialize(WONT_NEW, format="turtle")
    lines = ["# WONT definitions drafted by Claude, 2026-10-30 -- for the curator's review", "",
             f"{len(written)} written into `{WONT_NEW.name}`, {len(held)} not written.", "",
             "## Not written", ""]
    lines += [f"* **{r['label']}** (< {r['parents'][0]}): {why}" for r, why in held] + ["", "## Written", ""]
    lines += [f"* **{r['label']}** (< {r['parents'][0]}): {a['definition']}" for r, a in written]
    REVIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.dump({"written": [{"iri": r["iri"], "label": r["label"], "definition": a["definition"], "why": a["why"]}
                           for r, a in written],
               "held": [{"iri": r["iri"], "label": r["label"], "why": why} for r, why in held]},
              open(RUN_DIR / "result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[definitions] {len(written)} definition(s) written into {WONT_NEW.relative_to(ROOT)}; "
          f"{len(held)} held (review list {REVIEW.relative_to(ROOT)}); cost ${run.cost():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
