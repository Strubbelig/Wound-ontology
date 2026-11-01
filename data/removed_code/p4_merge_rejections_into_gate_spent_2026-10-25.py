"""Merge the store's blocklist rejections into the gate (rule 51). One-time.

The cleaner wrote the blocklist's answer into the store as rejections -- 2,330
terms and 6,436 relations, all `by: "blocklist"`, all as the lists stood on
2026-09-20 -- while the gate answered the same question with its own 10,531
`out` verdicts. The curator, 2026-09-28: merge into the gate. The view now asks
the gate live (the Blocker: gate verdicts plus the keyword lists), so the
frozen copies are removed. Nothing else is: a predicate-filter, prune or
reasoner-gate verdict is not a scope decision and stays.

The report says exactly what the change does downstream: which terms come
back (rejected on 2026-09-20, in scope now) and which leave (out of scope now,
never rejected), with mention counts.

    python scripts/p4_merge_rejections_into_gate.py [--write]
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

AUTHOR = "blocklist"


def _names(view) -> Counter:
    c: Counter = Counter()
    for _, ents in view:
        c.update(ents.keys())
    return c


def _cells(view) -> int:
    return sum(len(a) for _, ents in view for a in ents.values())


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator

    write = "--write" in argv
    p = Orchestrator()
    st, terms = p.store, p.term_mapper._term_mapping
    live = st.scope

    st.scope = lambda n: False                           # before: the frozen copies only
    before, before_cells = _names(st.view()), _cells(st.view())
    lifted_e = {t: r["rejected"] for t, r in terms.records.items()
                if (r.get("rejected") or {}).get("by") == AUTHOR}
    lifted_c = {t: {tr: v for tr, v in (r.get("relations") or {}).items() if v.get("by") == AUTHOR}
                for t, r in terms.records.items()}
    lifted_c = {t: v for t, v in lifted_c.items() if v}
    others = Counter(v.get("by") for r in terms.records.values()
                     for v in ([r["rejected"]] if r.get("rejected") else [])
                     + list((r.get("relations") or {}).values())
                     if v.get("by") != AUTHOR)
    print(f"[merge] {len(lifted_e):,} term rejection(s) and "
          f"{sum(map(len, lifted_c.values())):,} relation rejection(s) by {AUTHOR!r} "
          f"to remove; other verdicts kept: {dict(others) or 'none'}")

    for t in lifted_e:
        terms.records[t].pop("rejected")
    for t, cells in lifted_c.items():
        rel = terms.records[t]["relations"]
        for tr in cells:
            rel.pop(tr)
        if not rel:
            terms.records[t].pop("relations")
    terms._dirty()
    st.scope = live                                      # after: the gate, live
    after, after_cells = _names(st.view()), _cells(st.view())

    back = {n: c for n, c in after.items() if n not in before}
    gone = {n: c for n, c in before.items() if n not in after}
    print(f"[merge] entity names downstream: {len(before):,} -> {len(after):,}; "
          f"cells {before_cells:,} -> {after_cells:,}")
    print(f"[merge] {len(back):,} term(s) come back (rejected on 2026-09-20, in scope "
          f"now), {sum(back.values()):,} mention(s): "
          f"{sorted(back, key=lambda n: -back[n])[:10]}")
    print(f"[merge] {len(gone):,} term(s) leave (out of scope now, never rejected), "
          f"{sum(gone.values()):,} mention(s): {sorted(gone, key=lambda n: -gone[n])[:10]}")
    if not write:
        print("[merge] dry run -- nothing written. Pass --write.")
        return 0

    latest = sorted((ROOT / "data" / "cache").glob("term_mapping_*.json"))[-1]
    backup = ROOT / "data" / "backup" / f"term_mapping_before_gate_merge_{date.today()}.json"
    shutil.copy2(latest, backup)
    print(f"[merge] backed up {latest.name} -> {backup.name}")
    rows = {"terms": lifted_e, "relations": lifted_c}
    record = ROOT / "data" / "backup" / f"store_blocklist_rejections_removed_{date.today()}.json"
    record.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[merge] the removed verdicts are kept in {record.name}")
    terms.save()

    fresh = Orchestrator()
    left = sum(1 for r in fresh.term_mapper._term_mapping.records.values()
               if (r.get("rejected") or {}).get("by") == AUTHOR
               or any(v.get("by") == AUTHOR for v in (r.get("relations") or {}).values()))
    again = _names(fresh.store.view())
    if left or again != after:
        raise RuntimeError(f"[merge] read back: {left} blocklist verdict(s) remain, "
                           f"view {'differs' if again != after else 'matches'}")
    print(f"[merge] written and read back: no blocklist verdicts remain, and the view "
          f"downstream reads {len(after):,} names as measured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
