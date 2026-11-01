"""Build the scope-review queue for the Scope Rulings page.

One row per CONCEPT whose gate sources disagree (`gate_disagreements`) and that
the curator has not ruled on -- a curator verdict already outranks every source,
so asking again would be noise. Each side is one source: what it said, why,
when, and on which spelling.

Row ids are derived from the term, not its position, so the page can be
republished with a longer queue (gate pass 2 is still adding verdicts) and
every answer already given stays attached to its question.
`apply_contradiction_verdicts.py <dir> --queue <this file> --write` applies
the answers as `gate.curator`.

    python scripts/scope_review_queue.py [--out data/review/scope_queue_<date>.json]
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))


def row_id(term: str) -> str:
    return "s" + hashlib.sha1(term.encode("utf-8")).hexdigest()[:12]


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else \
        ROOT / "data" / "review" / f"scope_queue_{date.today()}.json"
    p = Orchestrator()
    g = p.term_mapper._term_mapping
    freq: Counter = Counter()
    for _, ents in p.store.view(mapped=False, include_rejected=True):
        freq.update(ents.keys())
    rows, ruled = [], 0
    for d in g.gate_disagreements():
        if "curator" in d["said"]:
            ruled += 1
            continue
        members = g._members(d["term"])
        sides = []
        for src, verdict in d["said"].items():
            ev = g.peek_gate(d["where"][src]).get(src) or {}
            sides.append({"who": src, "verdict": verdict, "spelling": d["where"][src],
                          "reason": ev.get("reason") or
                                    (f"{ev.get('by')}" + (f" · near {ev['near']} ({ev['score']})"
                                                          if ev.get("near") else "")),
                          "when": ev.get("when", "")})
        rows.append({"id": row_id(d["term"]), "term": d["term"],
                     "mentions": sum(freq[m] for m in members),
                     "spellings": len(members), "sides": sides,
                     "gate_now": f"{d['verdict'] or 'undecided'} ({d['source'] or '-'})",
                     "source": "gate"})
    rows.sort(key=lambda r: (-r["mentions"], r["term"].lower()))
    out.write_text(json.dumps({"contested": rows, "disagreements": []},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[scope] {len(rows):,} disagreement(s) to rule on "
          f"({ruled:,} already ruled by the curator) -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
