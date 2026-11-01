"""The author's relation decisions of the review pages into the term dict (2026-10-30).

Asked whether the decisions still kept in files beside TermMappingAndGate should
move into it, the curator: "Ja" (rule 51: every decision on the term's record;
2026-10-30 on a reading kept in files: "das machst du ganz sicher nicht").

* `data/review/curator_axioms_2026-10-03.json`: the axiom review page of
  2026-10-03 and three axioms given later in chat or on a review page (rule 69).
  A relation axiom is the author's `yes` on the subject's relation; a plain
  subclass axiom his is_a `yes`; a row he left out (`left_out`, the ids of
  `withheld_relations_2026-10-03.json`, which stays as that page's rows) his `no`.
* `data/review/new_class_relation_decisions.json`: the judgement queue of
  2026-10-07/08 and eleven relations on Burn Injury decided in chat on
  2026-10-20 (rule 72): `add` is his `yes`, `leave out` his `no`.

Each judgement keeps its day (and time, where the page recorded one) and names
the page and item in its reason. The names were the build's labels (title
case); each is found by its normalised spelling, and must find one concept.
Both files go to `data/backup/relation_decision_files_2026-10-30`.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

REVIEW = ROOT / "data" / "review"
AXIOMS = REVIEW / "curator_axioms_2026-10-03.json"
WITHHELD = REVIEW / "withheld_relations_2026-10-03.json"
QUEUE = REVIEW / "new_class_relation_decisions.json"
SET_ASIDE = ROOT / "data" / "backup" / "relation_decision_files_2026-10-30"
QUEUE_CHAT = "chat 2026-10-20 (review page https://claude.ai/artifact/17qogz8rnhq7XuWL6uA7Q9)"


def concept_finder(gt):
    from wound_ontology.utils.string_utils import normalize_term as N
    idx = defaultdict(set)
    for t in gt.records:
        try:
            idx[N(t)].add(gt.concept(gt.resolve(t)))
        except RuntimeError:
            pass

    def find(name: str) -> str:
        """The concept `name` names; a name no record has stays as it is (a target only)."""
        if name in gt.records:
            return gt.concept(gt.resolve(name))
        hit = idx.get(N(name), set())
        if len(hit) > 1:
            raise RuntimeError(f"{name!r} names {len(hit)} concepts: {sorted(hit)}")
        return next(iter(hit)) if hit else name
    return find


def decisions() -> list[dict]:
    """Every decision of the two files, in one shape."""
    ax = json.loads(AXIOMS.read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in json.loads(WITHHELD.read_text(encoding="utf-8"))["rows"]}
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))["decisions"]
    out = []
    for a in ax["axioms"]:
        day = re.search(r"\d{4}-\d\d-\d\d", a["by"]).group(0)
        why = f"{a['by'].removeprefix('curator, ')} ({a['from']})" + (f": {a['note']}" if a.get("note") else "")
        out.append({"subject": a["subject_label"], "predicate": a["predicate"], "value": a["filler_label"],
                    "verdict": "yes", "when": day, "why": why, "iri": a.get("filler_iri"),
                    "is_a": not a.get("property_iri")})
    for i in ax["left_out"]:
        r = rows[i]
        out.append({"subject": r["subject"], "predicate": r["predicate"], "value": r["value"], "verdict": "no",
                    "when": "2026-10-03", "why": f"axiom review page 2026-10-03: left out (row {i})", "iri": None,
                    "is_a": False})
    for k, d in queue.items():
        when = d["decided"][:19]
        page = QUEUE_CHAT if when.startswith("2026-10-20") else f"WONT judgement queue (item {d.get('item_id', k)})"
        out.append({"subject": d["subject"], "predicate": d["predicate"], "value": d["value"],
                    "verdict": {"add": "yes", "leave out": "no"}[d["v"]], "when": when,
                    "why": f"{page}: {d['v']}" + (f": {d['note']}" if d.get("note") else ""), "iri": None,
                    "is_a": False})
    return out


def write_into(gt, items) -> Counter:
    find = concept_finder(gt)
    norm = lambda p: p.strip().lower().replace(" ", "_")  # noqa: E731
    tally = Counter()
    for d in items:
        subj, tgt = find(d["subject"]), find(d["value"])
        rec = gt.records.get(subj) or {}
        if d["is_a"]:
            have = next((k for k, js in (rec.get("is_a") or {}).items()
                         if find(k) == tgt or (d["iri"] and any(j.get("iri") == d["iri"] for j in js))), None)
            gt._put(subj, "is_a", gt._j("yes", "author", d["why"], d["when"], d["iri"]), have or tgt, dated=True)
            tally["is_a yes (a subclass axiom)"] += 1
            continue
        have = next((k for k in (rec.get("relations") or {})
                     if norm(k.partition(":")[0]) == norm(d["predicate"]) and find(k.partition(":")[2].strip()) == tgt), None)
        key = have or f"{norm(d['predicate'])}: {tgt}"
        gt._put(subj, "relations", gt._j(d["verdict"], "author", d["why"], d["when"], d["iri"]), key, dated=True)
        tally[f"relation {d['verdict']}" + ("" if have else " (a relation no reading had)")] += 1
    return tally


def main(argv) -> int:
    from wound_ontology.fca.universality import load_verdicts
    from wound_ontology.mappers.judgements import RELATION_READER
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    if p.store.terms is not gt:
        raise RuntimeError("the store reads another term dict than the term mapper")
    items = decisions()
    before, _ = load_verdicts(p.store)                       # the term dict, then the files
    axioms_before = {(s, k, t) for s, k, t, ax, _ in gt.read_relations(RELATION_READER) if ax}
    tally = write_into(gt, items)
    gt._dirty()
    after, _ = load_verdicts(p.store)    # since 2026-10-30 the term dict alone (it was run while the loader still read the files)
    axioms_after = {(s, k, t) for s, k, t, ax, _ in gt.read_relations(RELATION_READER) if ax}
    print(f"[move-decisions] {len(items)} decision(s) written: {dict(tally)}")
    print(f"[move-decisions] axioms: {len(axioms_before)} -> {len(axioms_after)}; "
          f"new {len(axioms_after - axioms_before)}, gone {len(axioms_before - axioms_after)}")
    for x in sorted(axioms_before - axioms_after):
        print(f"[move-decisions]     gone: {x}")
    differ = sorted(k for k in set(before) | set(after) if (before.get(k) or (None,))[0] != (after.get(k) or (None,))[0])
    print(f"[move-decisions] the concept lattice's verdicts: {len(before)} with the files, {len(after)} from the term "
          f"dict; {len(differ)} differ")
    for k in differ:
        print(f"[move-decisions]     {k}: {before.get(k)} -> {after.get(k)}")
    if "--write" not in argv:
        print("[move-decisions] dry run; --write saves and sets the two files aside")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_relation_decisions_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[move-decisions] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()
    SET_ASIDE.mkdir(parents=True, exist_ok=True)
    for f in (AXIOMS, QUEUE):
        shutil.move(str(f), SET_ASIDE / f.name)
        print(f"[move-decisions] {f.relative_to(ROOT)} -> {(SET_ASIDE / f.name).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
