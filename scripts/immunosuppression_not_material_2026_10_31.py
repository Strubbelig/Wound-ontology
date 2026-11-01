#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Immunosuppression is no material entity: the author's 2026-10-31 decision in the term dict.

    python -u scripts/immunosuppression_not_material_2026_10_31.py            # dry run
    python -u scripts/immunosuppression_not_material_2026_10_31.py --write

The curator's superclass decision #6 (relayed by the thesis session, his answer
"B") makes Immunosuppression (WONT_0000161) a disease predisposition, no longer a
material disease entity; `ground_truth_final_2026-10-31f.owl` says so. The term
dict still held his 2026-10-18 ruling `Immunosuppression is_a material entity:
yes`, and a disposition is no material entity, so the ELK check of the class
hierarchy view stopped on the two author edges (rule 79). His newer decision is
written as his `no` on that edge; nothing else changes.
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

TERM, PARENT = "Immunosuppression", "material entity"
WHY = ("superclass decision #6, curator 2026-10-31 (relayed by the thesis session, his answer \"B\"): "
       "Immunosuppression is a disease predisposition, no longer a material disease entity; a disposition is "
       "no material entity, so his 2026-10-18 'yes' gives way (WONT ground_truth_final_2026-10-31f.owl)")


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current, rank, AUTHOR
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)

    js = ((gt.records.get(TERM) or {}).get("is_a") or {}).get(PARENT) or []
    cj = current(js)
    if not cj or cj["verdict"] != "yes" or rank(cj) != AUTHOR:
        raise SystemExit(f"[immuno] {TERM} is_a {PARENT}: current verdict {cj}; not the author's 'yes' this undoes; nothing written")
    gt._put(TERM, "is_a", gt._j("no", "author", WHY), PARENT)
    gt._dirty()
    print(f"[immuno] {live.name}: {TERM} is_a {PARENT}: author 'yes' ({cj['when']}) -> author 'no'")

    if "--write" not in argv:
        print("[immuno] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_immunosuppression_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[immuno] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()

    g2 = Orchestrator().term_mapper._term_mapping
    back = current(((g2.records.get(TERM) or {}).get("is_a") or {}).get(PARENT) or [])
    if not back or back["verdict"] != "no" or rank(back) != AUTHOR:
        raise SystemExit(f"[immuno] read back {back}; the author's 'no' is not current")
    print(f"[immuno] read back: {TERM} is_a {PARENT}: {back['verdict']} by {back['by']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
