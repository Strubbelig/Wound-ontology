"""Curator, 2026-10-20: MILD's complication classes go; their placements with them.

    python -u scripts/apply_mild_complication_2026_10_20.py [--write]

"die können alle weg": material complication disease entity (MILD_120051),
complication disease process (MILD_120092), disease complication diagnostic
result (MILD_120050) are not in mild_2026-10-20.ttl. Every placement onto one
of them is refused, so the term falls back to its other parents or to the
candidates; "Complicated und Uncomplicated Diabetes Mellitus können weg" -> out
of scope. Dry by default; backs up, writes, re-exports, reads back.
"""
from __future__ import annotations
import shutil, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
BY = "curator, chat 2026-10-20"
GONE = {"material complication disease entity", "complication disease process", "disease complication diagnostic result"}
OUT = {"complicated diabetes mellitus", "uncomplicated diabetes mellitus"}


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(); gt = p.term_mapper._term_mapping
    refuse = []
    for k, rec in gt.records.items():
        for c, j in (rec.get("pairs") or {}).items():
            if c.lower() in GONE and (j.get("curator") or {}).get("iri") and not j.get("refused"):
                refuse.append((k, c))
    out = [k for k in gt.records if k.lower() in OUT]
    print(f"[mild] refuse {len(refuse)} placement(s): {sorted(refuse)}")
    print(f"[mild] out of scope: {out}")
    if "--write" not in argv:
        print("[mild] dry run; --write to apply"); return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    shutil.copy2(latest, ROOT / "data" / "backup" / f"term_mapping_before_mild_complication_{datetime.now():%Y-%m-%d_%H-%M-%S}.json")
    when = datetime.now().isoformat(timespec="seconds")
    for k, c in refuse:
        # curator 2026-10-25: a pair onto a class MILD no longer has is deleted, not refused
        gt.records[k].get("pairs", {}).pop(c, None)
        if gt.records[k].get("to") == c:
            gt.records[k]["to"] = None
    for k in out:
        gt.gate(k, curator={"verdict": "out", "when": when, "by": BY, "reason": "complication is an epistemic label"})
    gt._dirty(); gt.save()
    print(f"[mild] gate lists re-exported: {p.export_gate_lists()}")
    g2 = Orchestrator().term_mapper._term_mapping
    lost = [(k, c) for k, c in refuse if not g2.peek(k, c).get("refused")] + \
           [k for k in out if g2.effective_gate_verdict(k)[0] != "out"]
    if lost:
        raise RuntimeError(f"[mild] did not land: {lost}")
    print(f"[mild] written and read back: {len(refuse)} refused, {len(out)} out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
