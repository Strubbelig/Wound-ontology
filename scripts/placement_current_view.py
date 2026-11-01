"""Which placement answers still apply to the current store view. Sandbox only.

    python -u scripts/placement_current_view.py

The placement sandbox (`data/review/placement_2026-09-29.json`) was asked
against the view of 2026-09-29. Mapping and gate decisions since then change
which names exist: a name merged onto a class is no longer a term to place, a
name freed by a refusal is one again. This keeps the answers whose term is a
name in today's view, in scope, and not itself a WONT/MILD label (a class that
exists needs no placement), and lists the in-scope view names the sandbox has no
answer for.

Writes `output/placement_current_2026-10-01.json` (the file the verify and merge
scripts read; the previous one is backed up) and reads it back.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

SANDBOX = ROOT / "data" / "review" / "placement_2026-09-29.json"
OUT = ROOT / "output" / "placement_current_2026-10-01.json"


def main() -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import normalize_term as N
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    # compared as the placement step compares them: normalised (p4_place_terms)
    labels = {N(str(l)) for l in p.ontology_labels()}
    names, typings = set(), {}
    for _, ents in p.store.view():
        for name, attrs in ents.items():
            names.add(name)
            typings.setdefault(N(name), set()).update(
                t.partition(":")[2].strip() for t in attrs if t.partition(":")[0].strip() == "is_a")
    inscope = {n for n in names if gt.effective_gate_verdict(gt.resolve(n))[0] == "in"}
    names, inscope = {N(n) for n in names}, {N(n): n for n in inscope}
    rows = json.loads(SANDBOX.read_text(encoding="utf-8"))["rows"]
    answered = {N(r["term"]) for r in rows}
    gone = Counter()
    cur = []
    for r in rows:
        t = N(r["term"])
        if t not in names:
            gone["no longer a name in the view"] += 1
        elif t not in inscope:
            gone["out of scope"] += 1
        elif t in labels:
            gone["is a WONT/MILD label"] += 1
        else:
            cur.append(r)
    unasked = sorted(inscope[k] for k in set(inscope) - answered - labels)
    why = {n: ("no category in any abstract" if not typings.get(N(n)) else
               f"typed {sorted(typings[N(n)])}") for n in unasked}

    if OUT.exists():
        bak = ROOT / "data" / "backup" / f"{OUT.stem}_before_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
        shutil.copy2(OUT, bak)
        print(f"[current] backed up {OUT.name} -> {bak.relative_to(ROOT)}")
    OUT.write_text(json.dumps({"measured": datetime.now().isoformat(timespec="seconds"),
                               "rows": cur, "unasked": why}, ensure_ascii=False), encoding="utf-8")
    back = json.loads(OUT.read_text(encoding="utf-8"))
    if len(back["rows"]) != len(cur) or len(back["unasked"]) != len(unasked):
        raise SystemExit("[current] read-back does not match")
    print(f"[current] written and read back: {len(rows):,} sandbox answers -> {len(cur):,} current "
          f"{dict(Counter(r['relation'] for r in cur))}; left out {dict(gone)}")
    print(f"[current] {len(unasked):,} in-scope view names have no placement answer:")
    for n, w in why.items():
        print(f"[current]     {n!r}: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
