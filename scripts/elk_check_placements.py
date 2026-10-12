"""Does ELK accept the checked placements? Sandbox only: no term dict, no ontology file.

    python -u scripts/elk_check_placements.py

Curator, 2026-10-01: "What does elk have to say. I know there were inconsistency
issues." Before any placement is written, every `placed` and `synonym` outcome
of `data/review/placement_merged_2026-10-01.json` is asserted on the skeleton
TBox (WONT + MILD + BFO, with BFO's disjointness axioms):

* the term becomes a fresh class under its own category (the one the abstracts
  or the curator's ruling gave it) and under its parent (`placed`), or
  equivalent to its class (`synonym`);
* a parent from an import module that the skeleton lacks is added under the
  category the placement step computed for it, so the category clash still
  shows.

ELK then reasons once. An unsatisfiable term class is a placement that
contradicts its own category (a process under a material entity). Because the
term classes are fresh and nothing else points at them, every unsatisfiable
class is attributed to its own placement; a parent or WONT class going
unsatisfiable is reported separately (a synonym can drag its class down).

Writes `data/review/placement_elk_2026-10-01.json` and reads it back.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

MERGED = ROOT / "data" / "review" / "placement_merged_2026-10-01.json"
CURRENT = ROOT / "output" / "placement_current_2026-10-01.json"
SKELETON = ROOT / "output" / "owl" / "skeleton_tbox.ttl"
OUT = ROOT / "data" / "review" / "placement_elk_2026-10-01.json"
NS = "http://example.org/placement-check/"
UNSAT = re.compile(r"unsatisfiable:\s*(\S+)", re.I)


def main() -> int:
    from wound_ontology.llm.extraction_models import CATEGORY_IRI
    rows = [r for r in json.loads(MERGED.read_text(encoding="utf-8"))["rows"]
            if r["outcome"] in ("placed", "synonym")]
    cur = json.loads(CURRENT.read_text(encoding="utf-8"))["rows"]
    parent_cat = {r["parent iri"]: r.get("parent category") for r in cur
                  if r.get("parent iri") and r.get("parent category")}

    g = rdflib.Graph()
    g.parse(SKELETON, format="turtle")
    known = set(g.subjects(RDF.type, OWL.Class))
    term_iri, problems = {}, []
    added_parents = 0
    for i, r in enumerate(rows):
        cat = CATEGORY_IRI.get(r["category"])
        if cat is None:
            problems.append(f"{r['term']!r}: category {r['category']!r} has no IRI")
            continue
        t = rdflib.URIRef(f"{NS}t{i}")
        term_iri[str(t)] = r
        g.add((t, RDF.type, OWL.Class))
        g.add((t, RDFS.label, rdflib.Literal(r["term"])))
        g.add((t, RDFS.subClassOf, rdflib.URIRef(cat)))
        p = rdflib.URIRef(r["parent iri"])
        if p not in known:
            pc = CATEGORY_IRI.get(parent_cat.get(r["parent iri"]) or "")
            g.add((p, RDF.type, OWL.Class))
            g.add((p, RDFS.label, rdflib.Literal(r["parent"])))
            if pc:
                g.add((p, RDFS.subClassOf, rdflib.URIRef(pc)))
            else:
                problems.append(f"{r['parent']!r}: not in the skeleton and no category known")
            known.add(p)
            added_parents += 1
        g.add((t, OWL.equivalentClass if r["outcome"] == "synonym" else RDFS.subClassOf, p))

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "placements.ttl"
        g.serialize(destination=str(src), format="turtle")
        proc = subprocess.run(["robot", "reason", "--input", str(src), "--reasoner", "ELK",
                               "--equivalent-classes-allowed", "all",
                               "--output", str(Path(td) / "out.owl")],
                              capture_output=True, text=True, timeout=1800)
    log = proc.stdout + proc.stderr
    unsat = set(UNSAT.findall(log))
    if proc.returncode != 0 and not unsat:
        raise SystemExit(f"[elk] robot failed without naming unsatisfiable classes:\n{log[-2000:]}")

    bad_terms = [term_iri[u] for u in sorted(unsat) if u in term_iri]
    bad_other = sorted(u for u in unsat if u not in term_iri)
    labels = {str(s): str(o) for s, o in g.subject_objects(RDFS.label)}
    report = {
        "asserted": len(term_iri), "module parents added": added_parents,
        "unsatisfiable placements": [{"term": r["term"], "category": r["category"],
                                      "outcome": r["outcome"], "parent": r["parent"],
                                      "check": r["check"]} for r in bad_terms],
        "unsatisfiable existing classes": [{"iri": u, "label": labels.get(u, "")} for u in bad_other],
        "problems": problems,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(OUT.read_text(encoding="utf-8"))
    print(f"[elk] written and read back: {back['asserted']:,} placements asserted "
          f"({back['module parents added']} module parents added); ELK exit {proc.returncode}")
    print(f"[elk] unsatisfiable placements: {len(bad_terms)}; unsatisfiable existing classes: {len(bad_other)}")
    for r in bad_terms[:40]:
        print(f"[elk]     {r['term']!r} [{r['category']}] {r['outcome']} {r['parent']!r}  ({r['check']})")
    for u in bad_other[:20]:
        print(f"[elk]     EXISTING {labels.get(u, u)!r}")
    print(f"[elk] by category of the bad placements: {dict(Counter(r['category'] for r in bad_terms))}")
    for p in problems[:20]:
        print(f"[elk] PROBLEM {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
