#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Rule 87 on the live term dict, and the curator's names for Biopsy (2026-10-26).

    python -u scripts/apply_rule87_biopsy_2026_10_26.py            # dry run
    python -u scripts/apply_rule87_biopsy_2026_10_26.py --write

Loading the file moves every `category` section into `relations` as a decided
`is_a`, and the one `senses` section into `to` (the loader does that; saving
writes it down). Then the curator's answers of 2026-10-26:

* Biopsy points at `Biopsy procedure` for its process sense and at `Biopsy
  material` for its material sense ("Biopsy procedure + Biopsy material"),
  each a record of its own. Until today the senses were `Biopsy` and `Biopsy
  sample`, the first named like the term itself.
* `Biopsy material` is in scope ("In aufnehmen").
* The curator's placement of Biopsy under OBI's sample collection process
  (2026-10-02) is about the procedure, so it moves onto `Biopsy procedure`: a
  split term is no node of its own, its senses are.
"""
from __future__ import annotations

import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

BY = "curator 2026-10-26"
WHEN = "2026-10-26T12:00:00"
TERM = "Biopsy"
NAMES = {"process": "Biopsy procedure", "material entity": "Biopsy material"}
PLACEMENT = "Sample collection process"


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.term_mapping_and_gate import split_of
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    n_cats, n_data = len(gt.categories()), len(gt.data)
    print(f"[rule87] {live.name}: {n_cats:,} decided categories, {len(gt.splits())} split term(s) "
          f"{gt.splits()}, {n_data:,} one-name mappings")
    if "--write" in argv:
        backup = ROOT / "data" / "backup" / f"term_mapping_before_rule87_{datetime.now():%Y-%m-%d_%H-%M}.json"
        shutil.copy2(live, backup)
        print(f"[rule87] backed up {live.name} -> {backup.relative_to(ROOT)}")

    gt.split_by_category(TERM, NAMES, method="curator")
    rec = gt.records[TERM]
    placed = (rec.get("pairs") or {}).pop(PLACEMENT, None)
    if placed:
        moved = dict(placed)
        cur = dict(moved["curator"])
        cur["note"] = f"moved from {TERM!r} when it was split by category ({BY})"
        moved["curator"] = cur
        gt.record(NAMES["process"])["pairs"][PLACEMENT] = moved
        print(f"[rule87] placement under {PLACEMENT!r} moved {TERM!r} -> {NAMES['process']!r}")
    elif PLACEMENT not in (gt.records[NAMES["process"]].get("pairs") or {}):
        print(f"[rule87] WARNING: no placement under {PLACEMENT!r} on {TERM!r} or its procedure")
    gt.gate(NAMES["material entity"], curator={
        "verdict": "in", "by": BY, "when": WHEN,
        "reason": "the material sense of Biopsy; the curator took it in"})
    gt._dirty()
    for name in NAMES.values():
        print(f"  {name!r}: {gt.records[name]} -> scope {gt.effective_gate_verdict(name)}")
    print(f"  {TERM!r}: to = {gt.records[TERM]['to']}")
    if "--write" not in argv:
        print("[rule87] dry run; --write to apply")
        return 0
    gt.save()

    o2 = Orchestrator()
    g2 = o2.term_mapper._term_mapping
    bad = []
    if split_of(g2.records.get(TERM) or {}) != NAMES:
        bad.append("split")
    if len(g2.categories()) != n_cats:
        bad.append(f"categories {len(g2.categories())} != {n_cats}")
    if len(g2.data) != n_data:
        bad.append(f"one-name mappings {len(g2.data)} != {n_data}")
    if any("category" in r or "senses" in r for r in g2.records.values()):
        bad.append("an old section is still on file")
    mentions = Counter(e for _, ents in o2.store.view() for e in ents
                       if e in NAMES.values() or e == TERM)
    print(f"[rule87] read back: problems {bad or 'none'}; mentions in the cleaned store: "
          f"{dict(mentions)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
