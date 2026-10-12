"""Give proper names back the word `disease` that the disorder rule took. One-time, 2026-10-02.

    python -u scripts/restore_disease_proper_names.py [--write]

The rule `disease/illness/pathology/dysfunction -> disorder` (curator,
2026-10-02, "disorder wins") reached into proper names: `Centers for Disorder
Control and Prevention`, `International Classification of Disorders`, `Global
Burden of Disorder`, `Ocular Surface Disorder Index`. The phrases are now
protected in `utils.normalise.DISORDER_KEEP`, which stops new damage but does
not repair the old: pass 0 normalises the CURRENT spelling, which no longer
holds `disease`.

Every string the abstracts wrote that the morning's pass 0 renamed and that
holds a protected phrase is given `normalise(string)` under the rules as they
now stand; its current name is renamed onto that (`apply_renames`, which turns
the alias back into the name and keeps the reversed decision as history).
Then pass 0 runs once more for the case variants.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

BY = "disorder rule: proper names restored (2026-10-02)"


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.normalise import DISORDER_KEEP, normalise

    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    originals = [t for t, rec in gt.records.items()
                 if gt.is_alias(t) and DISORDER_KEEP.search(t)
                 and "isorder" in gt.resolve(t) and "isorder" not in t]
    wanted = defaultdict(Counter)                 # current name -> {restored spelling: count}
    for t in originals:
        wanted[gt.resolve(t)][normalise(t).name] += 1
    renames = {cur: c.most_common(1)[0][0] for cur, c in wanted.items()
               if c.most_common(1)[0][0] != cur}
    print(f"[restore] {len(originals)} original spelling(s) hold a protected phrase; "
          f"{len(renames)} current name(s) to rename back")
    for a, b in sorted(renames.items()):
        print(f"[restore]     {a!r} -> {b!r}")
    if "--write" not in argv:
        print("[restore] dry run; --write to apply")
        return 0

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_disease_restore_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[restore] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    rep = p.store.apply_renames(renames, by=BY)
    print(f"[restore] {({k: v for k, v in rep.items() if not isinstance(v, list)})}")
    g2 = Orchestrator().term_mapper._term_mapping
    wrong = [a for a, b in renames.items() if g2.resolve(a) != b]
    if wrong:
        raise RuntimeError(f"[restore] {len(wrong)} rename(s) did not land: {wrong[:5]}")
    print(f"[restore] written and read back: {len(renames)} name(s) restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
