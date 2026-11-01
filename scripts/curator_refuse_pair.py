"""Record a curator's refusal of one mapping pair, and unmap it.

    python -u scripts/curator_refuse_pair.py "reason" "TERM|CANONICAL" ["TERM|CANONICAL" ...]

The pair is refused, not deleted (rule 33): `TermMappingAndGate.refuse` marks it
`refused` and `curator: refused`, so no later build re-proposes it. A curator
verdict already on the pair is kept under `curator_history`. The term dict is
backed up first, and a fresh Orchestrator reads the file back.

First use, 2026-10-01 (curator: "'wound healing' -> 'impaired wound healing'
thats wrong"): the pair had been marked `kept` from the review page on
2026-09-24, which made every `wound healing` mention read as impaired healing.
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
from wound_ontology.orchestrator import Orchestrator  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 3 or any("|" not in a for a in argv[2:]):
        raise SystemExit(__doc__)
    reason = argv[1]
    pairs = [tuple(a.split("|", 1)) for a in argv[2:]]
    gt = Orchestrator().term_mapper._term_mapping
    missing = [(t, c) for t, c in pairs if gt.data.get(t) != c]
    if missing:
        raise SystemExit(f"[refuse] not mapped that way now, nothing written: {missing}")

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_refuse_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[refuse] backed up {latest.name} -> {backup.relative_to(ROOT)}")

    for term, canonical in pairs:
        pair = gt.judgement(term, canonical)
        if pair.get("curator"):
            pair["curator_history"] = pair.get("curator_history", []) + [pair.pop("curator")]
        gt.refuse(term, canonical, reason=reason, by="curator")

    gt2 = Orchestrator().term_mapper._term_mapping
    bad = [(t, c) for t, c in pairs if gt2.data.get(t) == c or not gt2.is_refused(t, c)]
    if bad:
        raise SystemExit(f"[refuse] read back: {len(bad)} refusal(s) did not land: {bad}")
    for t, c in pairs:
        print(f"[refuse] written and read back: {t!r} -/-> {c!r}; {t!r} now -> {gt2.data.get(t)!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
