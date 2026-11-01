#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fold the keys Claude's placement reading wrote beside a key of the same class (2026-10-29).

    python -u scripts/merge_duplicate_class_keys_2026_10_29.py [--write]

`scripts/claude_read_placements.py` wrote a chosen class under the ontology's
label; where the record already held the class under another spelling (same
IRI), the two keys stood side by side and the author's judgement on one did not
reach the other: `Burn wound surface` -- the author withdrew `Immaterial
anatomical entity` on the conflict page that morning, Claude's `immaterial
anatomical entity` put it back, and ELK stopped on the author's own edges. Each
such key is folded into the key that was there first: its judgements join that
list in time order. Nothing is dropped.
"""
from __future__ import annotations

import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
AGENT = "claude-opus-5-5_placement"


def main(argv):
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.judgements import ordered, current
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    gt = TermMappingAndGate(DataManager(), file_name="term_mapping")
    folds = []
    for t, r in gt.records.items():
        for q in ("is_a", "pairs"):
            keys = r.get(q) or {}
            by_iri = defaultdict(list)
            for k, js in keys.items():
                for i in {j.get("iri") for j in js if j.get("iri")}:
                    by_iri[i].append(k)
            for i, ks in by_iri.items():
                new = [k for k in ks if all(j["by"] == AGENT for j in keys[k])]
                old = [k for k in ks if k not in new]
                if new and old:
                    folds += [(t, q, k, old[0]) for k in new]
    for t, q, k, into in folds:
        print(f"  {t} {q}: {k!r} -> {into!r}")
    if "--write" not in argv:
        print(f"[fold] {len(folds)} key(s); dry run, --write to fold")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    shutil.copy2(live, ROOT / "data" / "backup" / f"term_mapping_before_key_folds_{datetime.now():%Y-%m-%d_%H-%M}.json")
    for t, q, k, into in folds:
        keys = gt.records[t][q]
        keys[into] = ordered(keys[into] + keys.pop(k))
    gt._dirty()
    gt.save()
    g2 = TermMappingAndGate(DataManager(), file_name="term_mapping")
    bad = [(t, q, k) for t, q, k, _ in folds if k in (g2.records[t].get(q) or {})]
    for t, q, _, into in folds:
        print(f"  {t} {q} {into!r}: now {current(g2.records[t][q][into])['verdict']} by {current(g2.records[t][q][into])['by']}")
    print(f"[fold] {len(folds)} folded; problems: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
