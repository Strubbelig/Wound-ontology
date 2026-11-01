"""Curator, 2026-10-18 (chat, later): two terms out, one onto its WONT class.

    python -u scripts/apply_review_chat_2026_10_18b.py [--write]

"kannste auch löschen: Occurrence Of Wound, Wound Event"; "Wound Phase ist schon
in WONT und dort eine information content entity" (WONT: `Wound healing phase`).
Dry by default; backs up, writes, re-exports the gate lists, reads back.
"""
from __future__ import annotations
import shutil, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

BY = "curator, chat 2026-10-18"
OUT = {"occurrence of wound": "curator: 'kannste auch löschen'", "wound event": "curator: 'kannste auch löschen'"}
SAME = {"wound phase": "Wound healing phase"}


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(); gt = p.term_mapper._term_mapping
    rec = lambda t: sorted(k for k in gt.records if k.lower() == t)
    plan = [("out", k, OUT[t]) for t in OUT for k in rec(t)] + [("same", k, SAME[t]) for t in SAME for k in rec(t)]
    for t in list(OUT) + list(SAME):
        if not rec(t):
            raise RuntimeError(f"{t!r}: no record; nothing written")
    for a, k, x in plan:
        print(f"[chat] {a:4} {k!r:28} {x!r}  (now: {gt.effective_gate_verdict(k)}, -> {gt.records[k].get('to')!r})")
    if "--write" not in argv:
        print("[chat] dry run; --write to apply"); return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_chat_b_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup); print(f"[chat] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    for a, k, x in plan:
        if a == "out":
            gt.gate(k, curator={"verdict": "out", "when": when, "by": BY, "reason": x})
        else:
            r = gt.record(k); r.update({"to": x, "confidence": 1.0, "method": "curator"}); r.pop("retired", None)
            gt.judge(k, x, curator={"verdict": "same_class", "when": when, "by": BY,
                                    "reason": "curator: 'Wound Phase ist schon in WONT'"})
    gt._dirty(); gt.save()
    g2 = Orchestrator().term_mapper._term_mapping
    lost = [k for a, k, x in plan if (a == "out" and g2.effective_gate_verdict(k)[0] != "out")
            or (a == "same" and g2.records[k].get("to") != x)]
    if lost:
        raise RuntimeError(f"[chat] did not land: {lost}")
    print(f"[chat] written and read back: {len(plan)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
