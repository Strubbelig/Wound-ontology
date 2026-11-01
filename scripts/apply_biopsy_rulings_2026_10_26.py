#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The curator's two biopsy rulings of 2026-10-26 ("ja, beides so machen").

    python -u scripts/apply_biopsy_rulings_2026_10_26.py            # dry run
    python -u scripts/apply_biopsy_rulings_2026_10_26.py --write

* `Biopsy sample` (with its spellings `biopsy specimen(s)`, `biopsy
  sample(s)`) is the same as `Biopsy material`, the material sense of Biopsy
  (rule 87): it maps onto it, with the curator's `same_class` on the pair
  (rule 85). Its own scope verdict (pass 2: out) is pooled under the
  cluster's, where the curator's `in` outranks it.
* The head rule `biopsy` is `process`, not `material entity`
  (`config/category_head_rules.py`): the terms it had typed as material --
  `Wound biopsy`, `Skin biopsy` -- are procedures, and `Wound biopsy` is placed
  under WONT's wound specimen procurement by biopsy process. A head rule
  decides only a disputed term (rule 57), so only the terms it decided move.
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
WHEN = "2026-10-26T13:30:00"
SAME = ("Biopsy material", "Biopsy sample")       # (name, the term that joins it)
HEAD = "biopsy"


def main(argv: list[str]) -> int:
    from config.category_head_rules import HEAD_CATEGORY
    from wound_ontology.orchestrator import Orchestrator
    if HEAD_CATEGORY.get(HEAD) != "process":
        print(f"[biopsy] the head rule says {HEAD_CATEGORY.get(HEAD)!r}; set it to 'process' first")
        return 1
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    if "--write" in argv:
        backup = ROOT / "data" / "backup" / f"term_mapping_before_biopsy_rulings_{datetime.now():%Y-%m-%d_%H-%M}.json"
        shutil.copy2(live, backup)
        print(f"[biopsy] backed up {live.name} -> {backup.relative_to(ROOT)}")

    name, joins = SAME
    print(f"[biopsy] before: {joins!r} -> {gt.data.get(joins)!r}, scope {gt.effective_gate_verdict(joins)}")
    gt.decide_name(name, joins, by=BY, when=WHEN,
                   reason="the same thing as the material sense of Biopsy")
    head_terms = sorted(t for t, c in gt.categories().items()
                        if c.get("source") == f"head rule: {HEAD}")
    for t in head_terms:
        what = gt.set_category(t, "process", source=f"head rule: {HEAD}", by="curator",
                               note="head rule changed 2026-10-26: a biopsy is the procedure")
        print(f"  category {t!r}: {what} -> process")
    gt._dirty()
    print(f"[biopsy] after: {joins!r} -> {gt.data.get(joins)!r}, scope {gt.effective_gate_verdict(joins)}")
    if "--write" not in argv:
        print("[biopsy] dry run; --write to apply")
        return 0
    gt.save()

    o2 = Orchestrator()
    g2 = o2.term_mapper._term_mapping
    bad = []
    if g2.data.get(joins) != name:
        bad.append(f"{joins!r} maps onto {g2.data.get(joins)!r}")
    if g2.effective_gate_verdict(joins)[0] != "in":
        bad.append(f"{joins!r} is {g2.effective_gate_verdict(joins)}")
    cats = g2.categories()
    bad += [f"{t!r} is {cats.get(t)}" for t in head_terms
            if (cats.get(t) or {}).get("verdict") != "process"]
    typed = Counter()
    for _, ents in o2.store.view():
        for e, attrs in ents.items():
            if e in head_terms or e == name:
                for tr in attrs:
                    if tr.startswith("is_a: "):
                        typed[(e, tr)] += 1
    print(f"[biopsy] read back: problems {bad or 'none'}; typings in the cleaned store: {dict(typed)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
