"""Withdraw the nearest-neighbour scope verdicts that copied an unauthored one.

    python scripts/p4_gate_pass1_withdraw.py [--write]

The first run of `p4_gate_pass1.py` (2026-09-28) inherited from any decided
neighbour, and 1,275 of its 1,598 verdicts copied an imported list entry with
no author -- `biological treatment` took `out` from `biological therapy`,
which the list had excluded and the model has since put back in. A further 72
copies now contradict the neighbour they were copied from. Both kinds are
withdrawn: the `pass1` verdict moves to `gate_withdrawn` on the same record,
with the reason, so the history stays and nothing reads it as a decision. The
terms become undecided and go back to the queue; `p4_gate_pass1.py` now
inherits only from authored decisions.

A verdict is kept when its neighbour's own decision is authored (curator or
model) and still says the same thing.
"""
from __future__ import annotations

import shutil
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str]) -> int:
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    write = "--write" in argv
    gt = TermMappingAndGate(DataManager(), file_name="term_mapping")
    when = datetime.now().isoformat(timespec="seconds")
    withdraw: list[tuple[str, str]] = []
    tally: Counter = Counter()
    for term, rec in gt.records.items():
        p1 = (rec.get("gate") or {}).get("pass1")
        if not p1:
            continue
        near = gt.resolve(p1.get("near", ""))
        verdict, source = gt.own_gate_verdict(near)
        if source in ("", "rule", "pass1"):
            why = f"copied from {near!r}, whose own decision is {source or 'none'} -- unauthored"
            tally["neighbour unauthored"] += 1
        elif verdict != p1["verdict"]:
            why = f"copied {p1['verdict']!r} from {near!r}, which now says {verdict!r} ({source})"
            tally["neighbour now disagrees"] += 1
        else:
            tally["kept"] += 1
            continue
        withdraw.append((term, why))
    print(f"[withdraw] pass-1 verdicts: {dict(tally)}")
    if not write:
        for t, why in withdraw[:8]:
            print(f"[withdraw]   {t!r}: {why}")
        print("[withdraw] dry run -- nothing written. Pass --write.")
        return 0
    latest = sorted((ROOT / "data" / "cache").glob("term_mapping_*.json"))[-1]
    shutil.copy2(latest, ROOT / "data" / "backup" / f"term_mapping_before_pass1_withdraw_{date.today()}.json")
    for term, why in withdraw:
        rec = gt.records[term]
        entry = dict(rec["gate"].pop("pass1"))
        entry.update({"withdrawn": why, "withdrawn when": when})
        rec.setdefault("gate_withdrawn", []).append({"source": "pass1", **entry})
        if not rec["gate"]:
            rec.pop("gate")
    gt._dirty()
    gt._gate_idx = None
    gt.save()
    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    left = [t for t, _ in withdraw if (check.peek_gate(t).get("pass1"))]
    if left:
        raise RuntimeError(f"[withdraw] still carry pass1: {left[:5]}")
    print(f"[withdraw] written and read back: {len(withdraw):,} verdict(s) withdrawn, "
          f"kept as history in `gate_withdrawn`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
