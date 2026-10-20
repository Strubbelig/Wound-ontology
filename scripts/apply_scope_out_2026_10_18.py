"""Curator, 2026-10-18 (chat): these terms are out of scope -- on the blocklist.

    python -u scripts/apply_scope_out_2026_10_18.py [--write]

"skin loss und skin breakdown sind auch wieder so komische Begriffe, die einfach
nur Jargon sind. kannste ruhig löschen"; "Spearman's Rank Correlation gehört ...
absolut nicht rein ... der muss in die blocklist". Every record that spells the
term (case-insensitively) gets a curator `out` verdict; the gate lists are
re-exported (they are views of the term dict, rule 51). Dry by default.
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
TERMS = {
    "spearman's rank correlation": "statistics jargon, not a wound-ontology concept: on the blocklist",
    "skin loss": "jargon (curator: 'einfach nur Jargon')",
    "total skin loss": "jargon (curator: 'einfach nur Jargon')",
    "skin breakdown": "jargon (curator: 'einfach nur Jargon')",
}


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(); gt = p.term_mapper._term_mapping
    when = datetime.now().isoformat(timespec="seconds")
    plan = []
    for term, why in TERMS.items():
        recs = [k for k in gt.records if k.lower() == term]
        if not recs:
            raise RuntimeError(f"{term!r}: no record in the term dict; nothing written")
        for k in recs:
            plan.append((k, why)); print(f"[scope] out  {k!r:36} was {gt.effective_gate_verdict(k)}")
    if "--write" not in argv:
        print("[scope] dry run; --write to apply"); return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_scope_out_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup); print(f"[scope] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    for k, why in plan:
        gt.gate(k, curator={"verdict": "out", "when": when, "by": BY, "reason": why})
    gt._dirty(); gt.save()
    print(f"[scope] gate lists re-exported: {p.export_gate_lists()}")
    g2 = Orchestrator().term_mapper._term_mapping
    lost = [k for k, _ in plan if g2.effective_gate_verdict(k)[0] != "out"]
    if lost:
        raise RuntimeError(f"[scope] did not land: {lost}")
    print(f"[scope] written and read back: {len(plan)} record(s) out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
