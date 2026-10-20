"""Curator, 2026-10-19: `burn injury` is not under `Thermal wound` (rule 79).

    python -u scripts/apply_burn_injury_placement_2026_10_19.py [--write]

Asked in chat ("Ablehnen"): a burn injury is more general than a wound (a burn
of the ocular surface is a burn injury and no wound); the burn wound stands
under both. Reverses the placement review of 2026-10-02. Dry by default.
"""
from __future__ import annotations
import shutil, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    gt = Orchestrator().term_mapper._term_mapping
    recs = [k for k in gt.records if k.lower() == "burn injury"]
    pairs = [(k, c) for k in recs for c in (gt.records[k].get("pairs") or {}) if c.lower() == "thermal wound"]
    print(f"[burn injury] refuse {pairs}")
    if not pairs:
        raise RuntimeError("no burn injury -> Thermal wound pair found; nothing written")
    if "--write" not in argv:
        print("[burn injury] dry run; --write to apply"); return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    shutil.copy2(latest, ROOT / "data" / "backup" / f"term_mapping_before_burn_injury_{datetime.now():%Y-%m-%d_%H-%M-%S}.json")
    for k, c in pairs:
        gt.refuse(k, c, reason="a burn injury is more general than a wound (rule 79); the burn wound stands under both",
                  by="curator, chat 2026-10-19")
    g2 = Orchestrator().term_mapper._term_mapping
    lost = [(k, c) for k, c in pairs if not g2.peek(k, c).get("refused")]
    if lost:
        raise RuntimeError(f"did not land: {lost}")
    print(f"[burn injury] written and read back: {len(pairs)} refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
