#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The term dict follows the curator's WONT decisions of 2026-10-31 evening (ground_truth_final_2026-10-31g.owl).

    python -u scripts/author_edges_after_wont_10_31g_2026_10_31.py            # dry run
    python -u scripts/author_edges_after_wont_10_31g_2026_10_31.py --write

Two of his decisions undo is_a edges he had confirmed earlier, which the
pipeline would otherwise keep building (rule 79 stops on the first; the second
would bring the obsolete class back as a minted, uncurated one):

* option B: Immunodeficiency disorder is WONT_0003586, a material disease
  entity. His earlier `is_a Abnormality of the immune system: yes` cannot stand:
  HP_0002715 is a phenotype, a quality, in the import closure.
* "20 obsolete": wound signaling function (WONT_120001) is obsolete without
  replacement, so nothing is placed under it any more.

Each is written as his `no` on that edge, as for Immunosuppression
(scripts/immunosuppression_not_material_2026_10_31.py); nothing else changes.
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

B = ("option B, curator 2026-10-31 (relayed by the thesis session): Immunodeficiency disorder is WONT_0003586, "
     "a material disease entity; HP_0002715 is a phenotype, a quality, which a material entity cannot be, so his "
     "earlier 'yes' gives way (WONT ground_truth_final_2026-10-31g.owl)")
RETIRED = ("curator 2026-10-31 (relayed by the thesis session: \"20 obsolete\"): wound signaling function "
           "(WONT_120001) is obsolete without replacement, so nothing is placed under it; his earlier 'yes' gives "
           "way (WONT ground_truth_final_2026-10-31g.owl)")
EDGES = [("Immunodeficiency disorder", "Abnormality of the immune system", B),
         ("Chemotactic activity", "wound signaling function", RETIRED),
         ("Endothelial cell chemotactic activity", "wound signaling function", RETIRED),
         ("Pro-angiogenic effect", "wound signaling function", RETIRED)]


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current, rank, AUTHOR
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)

    for term, parent, why in EDGES:
        cj = current(((gt.records.get(term) or {}).get("is_a") or {}).get(parent) or [])
        if not cj or cj["verdict"] != "yes" or rank(cj) != AUTHOR:
            raise SystemExit(f"[edges] {term} is_a {parent}: current verdict {cj}; not the author's 'yes' this undoes; nothing written")
        gt._put(term, "is_a", gt._j("no", "author", why), parent)
        print(f"[edges] {term} is_a {parent}: author 'yes' ({cj['when']}) -> author 'no'")
    gt._dirty()
    left = sorted(t for t, r in gt.records.items()
                  if (c := current(((r.get("is_a") or {}).get("wound signaling function")) or [])) and c["verdict"] == "yes")
    if left:
        raise SystemExit(f"[edges] still placed under wound signaling function: {left}; nothing written")

    if "--write" not in argv:
        print(f"[edges] {live.name}: dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_wont_10_31g_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[edges] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()

    g2 = Orchestrator().term_mapper._term_mapping
    bad = [(t, p) for t, p, _ in EDGES
           if not (b := current(((g2.records.get(t) or {}).get("is_a") or {}).get(p) or []))
           or b["verdict"] != "no" or rank(b) != AUTHOR]
    if bad:
        raise SystemExit(f"[edges] read back: the author's 'no' is not current on {bad}")
    print(f"[edges] read back: {len(EDGES)} edges, each the author's 'no'")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
