"""Write the curator's decisions on statements that contradict each other (rule 77).

    python -u scripts/apply_clash_decisions.py DECISIONS.json [--write]

DECISIONS.json is written from the judgement page's section "Statements that
contradict each other" (read with ArtifactData) and lists every write with its
author and reason, e.g. data/review/relation_clash_decisions_2026-10-10.json:

* `reject`: statements to hold out of the ontology for good. "Leave this
  statement out" rejects the statement itself; "Keep it" rejects the
  statements on its target that made the target the wrong kind, so the kept
  statement passes the reasoner check again. Each is a rejection in the term
  dict beside the assertion (rule 33), by `curator` or by `same type` (a
  statement of the type the curator decided, applied by Claude and listed so
  it can be reversed). The relation check lifts only its own verdicts, so
  these stand through every rebuild.
* `category`: a term's kind, as a curator's term ruling (rule 57).
* `scope_out`: a term the curator said to delete ("Delete it"): a curator
  verdict `out` on its record (rule 40). The term leaves the view everywhere,
  with every statement on it or pointing at it; the abstracts keep it.
* `place`: a parent the curator named for a term (rule 72): the pair gets
  `placement: {verdict: "narrower"}` and a curator mark, as the judgement
  queue writes it. The parent is given by its label as the class tree spells
  it, with its IRI beside it for the reader.

Dry by default. With --write: the term dict is backed up, written once per
author, and every decision is read back from disk.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

AUTHORS = {"curator": "curator (judgement page: statements that contradict each other, {date})",
           "same type": "same type as the curator's decisions (Claude, {date}; listed in {file})"}


def main(argv: list[str]) -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.llm.extraction_adapter import normalize_predicate
    from wound_ontology.mappers.term_mapping_and_gate import TERM_RULING
    from wound_ontology.orchestrator import Orchestrator

    path = Path(argv[1])
    dec = json.loads(path.read_text(encoding="utf-8"))
    by_of = {k: v.format(date=dec["made"], file=path.relative_to(ROOT) if path.is_absolute() else path)
             for k, v in AUTHORS.items()}
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    st, gt = p.store, p.term_mapper._term_mapping

    # Every statement must be a cell the view holds (rejected or not) -- a
    # decision on a statement nobody reads would vanish (rule 73).
    present = {(e, t) for _, ents in st.view(include_rejected=True) for e, attrs in ents.items() for t in attrs}
    cells: dict[str, list] = defaultdict(list)
    missing = []
    for r in dec["reject"]:
        cell = (r["subject"], f"{normalize_predicate(r['predicate'])}: {r['object']}")
        (cells[r["by"]] if cell in present else missing).append(cell)
    if missing:
        raise RuntimeError(f"[clash] {len(missing)} statement(s) are in no abstract's record, nothing written: {missing}")
    if set(cells) - set(AUTHORS):
        raise RuntimeError(f"[clash] unknown author(s): {set(cells) - set(AUTHORS)}")
    cats = []
    for c in dec.get("category", []):
        hits = {gt.resolve(k) for k in gt.records if k.lower() == c["term"].lower()}
        if len(hits) != 1:
            raise RuntimeError(f"[clash] {c['term']!r}: {len(hits)} records, nothing written")
        term = next(iter(hits))
        cats.append((term, c))
        print(f"[clash] category of {term!r}: now {(gt.categories().get(term) or {}).get('verdict')!r} -> {c['category']!r}")
    outs = []
    for o in dec.get("scope_out", []):
        hits = {gt.resolve(k) for k in gt.records if k.lower() == o["term"].lower()}
        if len(hits) != 1:
            raise RuntimeError(f"[clash] {o['term']!r}: {len(hits)} records, nothing written")
        term = next(iter(hits))
        outs.append((term, o))
        print(f"[clash] scope of {term!r}: now {gt.effective_gate_verdict(term)[0]!r} -> 'out'")
    places = []
    for c in dec.get("place", []):
        hits = {gt.resolve(k) for k in gt.records if k.lower() == c["term"].lower()}
        if len(hits) != 1:
            raise RuntimeError(f"[clash] {c['term']!r}: {len(hits)} records, nothing written")
        term = next(iter(hits))
        if gt.data.get(term):
            raise RuntimeError(f"[clash] {term!r} is mapped onto {gt.data[term]!r}; a parent would not count")
        places.append((term, c))
        print(f"[clash] parent of {term!r}: {c['parent']!r} ({c['parent_iri']})")
    print(f"[clash] statements to hold out: {dict(Counter({k: len(v) for k, v in cells.items()}))}")
    for by, cs in cells.items():
        for e, t in cs:
            print(f"[clash]   {by:9} {e} | {t}")
    if "--write" not in argv:
        print("[clash] dry run; --write to apply")
        return 0

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_clash_decisions_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[clash] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    for term, c in cats:
        print(f"[clash] category of {term!r}: {gt.set_category(term, c['category'], source=TERM_RULING, note=c['why'])}")
    when = datetime.now().isoformat(timespec="seconds")
    for term, o in outs:
        gt.gate(term, curator={"verdict": "out", "when": when, "by": by_of["curator"], "reason": o["why"]})
    for term, c in places:
        gt.judge(term, c["parent"],
                 curator={"verdict": "narrower", "when": when, "by": by_of["curator"],
                          "iri": c["parent_iri"], "reason": c["why"]})
    for by, cs in cells.items():
        n = st.reject_cells(cs, by=by_of[by], note=f"decision and reason: {path.name}")
        if n != len(cs):
            raise RuntimeError(f"[clash] {by}: {n} of {len(cs)} written")
    gt._dirty()
    gt.save()

    # read back from disk
    p2 = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    lost = [(by, e, t) for by, cs in cells.items() for e, t in cs
            if ((p2.term_mapper._term_mapping.records.get(e) or {}).get("relations", {}).get(t) or {}).get("by") != by_of[by]]
    lost += [("category", term, c["category"]) for term, c in cats
             if (p2.term_mapper._term_mapping.categories().get(term) or {}).get("verdict") != c["category"]]
    lost += [("scope", term, "out") for term, _ in outs
             if p2.term_mapper._term_mapping.effective_gate_verdict(term)[0] != "out"]
    placed = set(p2.term_mapper._term_mapping.placements())
    lost += [("place", term, c["parent"]) for term, c in places if (term, c["parent"]) not in placed]
    if lost:
        raise RuntimeError(f"[clash] {len(lost)} decision(s) did not land: {lost}")
    print(f"[clash] written and read back: {sum(map(len, cells.values()))} statements held out, "
          f"{len(cats)} category ruling(s), {len(outs)} term(s) out of scope, {len(places)} parent(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
