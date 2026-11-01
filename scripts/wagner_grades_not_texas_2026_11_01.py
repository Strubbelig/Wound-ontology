#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A Wagner grade is no University of Texas grade: the author's `no` on 16 placements (2026-11-01).

    python -u scripts/wagner_grades_not_texas_2026_11_01.py            # dry run
    python -u scripts/wagner_grades_not_texas_2026_11_01.py --write

The curator decided WONT_0000375 is the University of Texas wound
classification ("University of Texas"); its grade class, "Wagner and Anderson
wound classification grade" until WONT 2026-11-01, is the University of Texas
wound classification grade. Claude's placement reading of 2026-10-29 had put
16 Wagner grade terms (Wagner grade 1 ... 4-5, Meggitt-Wagner grade 0-1, ...)
under that grade class, by its old name. A Wagner grade is not a Texas grade,
and the old name is gone, so the extension would mint "Wagner and Anderson
wound classification grade" anew for them (rule 97). His decision is written as
the author's `no` on each; nothing else changes.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

OLD_PARENT = "Wagner and Anderson wound classification grade"
WHY = ("curator 2026-11-01 (\"University of Texas\"): WONT_0000375 is the University of Texas wound classification, "
       "its grade class the University of Texas wound classification grade (WONT ground_truth_final_2026-11-01.owl); "
       "a Wagner grade is not a University of Texas grade")


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current, rank, AUTHOR
    gt = Orchestrator().term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    hit, his_own = [], []
    for term, r in gt.records.items():
        for parent, js in (r.get("is_a") or {}).items():
            cj = current(js)
            if parent.lower() == OLD_PARENT.lower() and cj and cj["verdict"] == "yes":
                if rank(cj) == AUTHOR:
                    # his earlier 'yes' was given to the class under its wrong name; his newer
                    # decision says what the class is, so it gives way (as Immunosuppression, rule 98)
                    his_own.append((term, cj["when"]))
                gt._put(term, "is_a", gt._j("no", "author", WHY), parent)
                hit.append(term)
    print(f"[wagner] {live.name}: author 'no' on {len(hit)} placement(s) under {OLD_PARENT!r}: {sorted(hit)}")
    print(f"[wagner]   of them his own earlier 'yes', giving way to his newer decision: {his_own}")
    if len(hit) != 16:
        raise SystemExit(f"[wagner] expected the 16 found on 2026-11-01, found {len(hit)}; nothing written")
    if "--write" not in argv:
        print("[wagner] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_texas_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[wagner] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()
    g2 = Orchestrator().term_mapper._term_mapping
    left = [t for t in hit if (current(((g2.records.get(t) or {}).get("is_a") or {}).get(OLD_PARENT) or []) or {})
            .get("verdict") != "no"]
    if left:
        raise SystemExit(f"[wagner] read back: still placed: {left}")
    print(f"[wagner] read back: all {len(hit)} now 'no' by the author")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
