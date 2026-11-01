#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Two renames of 2026-10-29, as the author's.

    python -u scripts/apply_renames_necrosis_mri_2026_10_29.py --write

* Necrosis -> Necrotic material. The author on the pair page: "Necrosis is
  better denoted as necrotic material"; WONT_120020 carries that label since
  ground_truth_final_2026-10-29.owl (written with his one-time leave). Without
  the rename the 83 abstracts that name Necrosis would no longer find the WONT
  class and the export would mint a second one.
* MRI -> Magnetic resonance imaging. The author's rule of 2026-09-30, "no
  abbreviations ever"; the full form is known without guessing (it is the name
  the abstracts spell out, and it already pointed to MRI). His naming of the
  full form by MRI on 2026-09-25 (review UI) came before the rule; it stays on
  the record as history. Done on his word to take care of the smaller points.

The decisions move with the name (`apply_renames`); the old name points to the
new one. The read-back checks that no string ends in a loop of names.
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

RENAMES = {
    "Necrosis": ("Necrotic material", "author, 2026-10-29, pair page note: 'Necrosis is better denoted as "
                 "necrotic material'; WONT_120020 is labelled so in ground_truth_final_2026-10-29.owl"),
    "MRI": ("Magnetic resonance imaging", "author's rule of 2026-09-30, 'no abbreviations ever' (the full "
            "form is the one the abstracts spell out); applied 2026-10-29 on his word to take care of the "
            "smaller points"),
}


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    for old, (new, _) in RENAMES.items():
        if gt.concept(gt.resolve(old)) != old:
            raise SystemExit(f"[renames] {old!r} is not its own concept; nothing written")
        if new in gt.records and gt.concept(gt.resolve(new)) != old:
            raise SystemExit(f"[renames] {new!r} is another concept already; nothing written")
    cats = {old: (gt.categories().get(old) or {}).get("verdict") for old in RENAMES}
    scopes = {old: gt.gate_verdict(old)[0] for old in RENAMES}
    n_placed = len(gt.placements())
    print(f"[renames] {live.name}: {', '.join(f'{o_} -> {n}' for o_, (n, _) in RENAMES.items())}; "
          f"{n_placed:,} placements")
    if "--write" not in argv:
        print("[renames] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_renames_necrosis_mri_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[renames] backed up {live.name} -> {backup.relative_to(ROOT)}")
    for old, (new, why) in RENAMES.items():
        rep = gt.apply_renames({old: new}, by="author", why=why)
        print(f"[renames] {old} -> {new}: { {k: v for k, v in rep.items() if v} }")

    o2 = Orchestrator()
    g2 = o2.term_mapper._term_mapping
    bad = []
    for old, (new, _) in RENAMES.items():
        if g2.concept(g2.resolve(old)) != new:
            bad.append(f"{old} does not lead to {new}")
        if (g2.categories().get(new) or {}).get("verdict") != cats[old]:
            bad.append(f"{new}: category {g2.categories().get(new)}, was {cats[old]}")
        if g2.gate_verdict(new)[0] != scopes[old]:
            bad.append(f"{new}: scope {g2.gate_verdict(new)}, was {scopes[old]}")
    if len(g2.placements()) != n_placed:
        bad.append(f"placements {len(g2.placements())}, were {n_placed}")
    loops = []
    for t in list(g2.records):
        try:
            g2.concept(g2.resolve(t))
        except RuntimeError:
            loops.append(t)
    if loops:
        bad.append(f"{len(loops)} string(s) in a loop of names: {loops[:5]}")
    seen = {}
    for key, ents in o2.store.view():
        for e in ents:
            seen.setdefault(e, set()).add(key)
    print(f"[renames] read back: {', '.join(f'{n} {len(seen.get(n, ()))} abstracts' for n, _ in RENAMES.values())}; "
          f"problems: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
