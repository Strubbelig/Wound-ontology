"""The relation typing check of 2026-10-02 into the term dict (2026-10-30).

`scripts/relation_typing_check.py` checked every relation of the store view on
2026-10-02 on both ends against what its predicate requires (curator,
2026-10-02: "I'd rather take little nodes and edges and add them to the onto
than bad ones") and wrote `data/review/relation_typing_check_2026-10-02.json`.
Its answers are judgements of a program on the relations, and belong in the
term dict like every other reading (curator, 2026-10-30, on moving the files
beside it: "Ja"):

  ok            -> yes        (both ends have the category the predicate requires)
  violates      -> no         (an end's category is disjoint from the required one)
  undetermined  -> undecided  (the check could not tell; never counts)

A `no` is a refusal of the relation in the store view, as every `no` on a
cell is; a later reading's or the author's word counts over it. Each
judgement is dated 2026-10-02 and names both ends' categories and the
abstracts the relation was found in that day. Rows that land on one relation
after the renames since give one judgement per answer, `no` last. The file
goes to `data/backup/relation_decision_files_2026-10-30`.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))

CHECK = ROOT / "data" / "review" / "relation_typing_check_2026-10-02.json"
SET_ASIDE = ROOT / "data" / "backup" / "relation_decision_files_2026-10-30"
AGENT = "relation-typing-check"
VERDICT = {"ok": "yes", "violates": "no", "undetermined": "undecided"}


def why(r: dict) -> str:
    s, v = r["subject_check"], r["value_check"]
    return (f"subject {s[1] or 'no category'}: {s[0]}; value {v[1] or 'no category'}: {v[0]} "
            f"({r['abstracts']} abstract(s) on 2026-10-02)")


def main(argv) -> int:
    from move_relation_decisions_2026_10_30 import concept_finder
    from wound_ontology.mappers.judgements import AGENTS, current
    from wound_ontology.orchestrator import Orchestrator
    if AGENT not in AGENTS:
        raise RuntimeError(f"add {AGENT!r} to judgements.AGENTS first")
    gt = Orchestrator().term_mapper._term_mapping
    find = concept_finder(gt)
    norm = lambda p: p.strip().lower().replace(" ", "_")  # noqa: E731
    rows = json.loads(CHECK.read_text(encoding="utf-8"))["rows"]
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    keys: dict[str, dict] = {}
    for r in rows:
        subj, tgt = find(r["subject"]), find(r["value"])
        if subj not in keys:
            keys[subj] = {(norm(k.partition(":")[0]), find(k.partition(":")[2].strip())): k
                          for k in ((gt.records.get(subj) or {}).get("relations") or {})}
        key = keys[subj].get((norm(r["predicate"]), tgt)) or f"{norm(r['predicate'])}: {tgt}"
        keys[subj][(norm(r["predicate"]), tgt)] = key
        cells[(subj, key)].append(r)
    before = {c: current(((gt.records.get(c[0]) or {}).get("relations") or {}).get(c[1])) for c in cells}
    tally, mixed = Counter(), 0
    for (subj, key), rs in cells.items():
        answers = {VERDICT[r["verdict"]]: r for r in sorted(rs, key=lambda r: -r["abstracts"])}
        mixed += len(answers) > 1
        for v in sorted(answers, key=lambda v: v == "no"):          # `no` last: the weaker counts
            gt._put(subj, "relations", gt._j(v, AGENT, why(answers[v]), "2026-10-02"), key, dated=True)
            tally[v] += 1
    after = {c: current(((gt.records.get(c[0]) or {}).get("relations") or {}).get(c[1])) for c in cells}
    refused = [c for c in cells if (after[c] or {}).get("verdict") == "no" and (before[c] or {}).get("verdict") != "no"]
    held_over = Counter((before[c] or {}).get("by") for c in cells
                        if any(r["verdict"] == "violates" for r in cells[c]) and (after[c] or {}).get("verdict") != "no")
    print(f"[typing] {len(rows):,} row(s) of 2026-10-02 on {len(cells):,} relation(s) ({mixed} with rows "
          f"that answered differently): {dict(tally)}")
    print(f"[typing] newly refused in the store view: {len(refused):,} relation(s); a violation a later word "
          f"counts over: {dict(held_over)}")
    for c in refused[:8]:
        print(f"[typing]     {c[0]} | {c[1]}: {why(cells[c][0])}")
    if "--write" not in argv:
        print("[typing] dry run; --write saves and sets the file aside")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_typing_check_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[typing] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt._dirty()
    gt.save()
    SET_ASIDE.mkdir(parents=True, exist_ok=True)
    shutil.move(str(CHECK), SET_ASIDE / CHECK.name)
    print(f"[typing] {CHECK.relative_to(ROOT)} -> {(SET_ASIDE / CHECK.name).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
