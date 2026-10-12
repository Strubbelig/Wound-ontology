"""Read `has_disposition` cells whose value is a tendency as `has_tendency` (rule 68).

    python -u scripts/shift_has_tendency.py [--write]

Curator, 2026-10-03: "do the has disposition to has tendency shift for
tendency targets". MILD keeps tendency disjoint from disposition and now has
MILD_120101 `has tendency`; the old extraction schema licensed `has
disposition` for material entity -> tendency (copied from WONT's three axioms
that were wrong), so the abstracts' tendencies came out as dispositions.

Decided per (subject, value) pair, from the evidence: it shifts when the
value's most frequent typing across the store is tendency and the abstracts
asserting the pair do not type it disposition or function. (A first draft
followed the asserting abstract's typing alone and would have made
`Osteomyelitis`, `Smoking` and `diabetic peripheral neuropathy` tendencies.)

The store is not edited (rule 33): each shifted cell gets a `repredicated`
decision beside it in the term dict, which the view applies. Backed up first,
read back after.
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

BY = "rule 68: has_disposition with a tendency value (curator 2026-10-03)"
REPORT = ROOT / "data" / "review" / "has_tendency_shift_2026-10-03.json"


def main(argv: list[str]) -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.store.concept_store import declared_category

    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    recs = list(p.store.view())

    def typings(attrs):
        return {declared_category(t.split(":", 1)[1].strip()) for t, v in attrs.items()
                if v == 1.0 and t.startswith("is_a:")} - {None}

    everywhere: dict[str, Counter] = defaultdict(Counter)
    for _, ents in recs:
        for e, attrs in ents.items():
            for c in typings(attrs):
                everywhere[e][c] += 1
    local: dict[tuple, Counter] = defaultdict(Counter)
    pairs = set()
    for _, ents in recs:
        for e, attrs in ents.items():
            for t, v in attrs.items():
                if v == 1.0 and t.startswith("has_disposition:"):
                    val = t.split(":", 1)[1].strip()
                    pairs.add((e, t))
                    if val in ents:
                        for c in typings(ents[val]):
                            local[(e, t)][c] += 1
    shift, why = {}, Counter()
    rows = []
    for e, t in sorted(pairs):
        val = t.split(":", 1)[1].strip()
        here, glob = local.get((e, t), Counter()), everywhere.get(val, Counter())
        # The value must BE a tendency: its most frequent typing across the store
        # is tendency (one abstract typing `Osteomyelitis` tendency -- it meant
        # the risk of it -- does not make the disorder a tendency), and the
        # abstracts asserting this pair do not type it disposition or function.
        top = glob.most_common(1)[0][0] if glob else None
        ok = top == "tendency" and not (here["disposition"] or here["function"])
        basis = "value mostly typed tendency" if top == "tendency" else f"value mostly typed {top}"
        why[(basis, "shift" if ok else "stays")] += 1
        if ok:
            shift[(e, t)] = "has_tendency"
        rows.append({"subject": e, "value": val, "shift": ok, "basis": basis,
                     "typed_here": dict(here), "typed_everywhere": dict(glob)})
    print(f"[shift] {len(pairs)} has_disposition pair(s); {len(shift)} shift to has_tendency")
    for k, n in sorted(why.items()):
        print(f"[shift]   {k[0]:34} {k[1]:6} {n}")
    print("[shift]   e.g. shift:", [f"{r['subject']} -> {r['value']}" for r in rows if r["shift"]][:12])
    print("[shift]   e.g. stays:", [f"{r['subject']} -> {r['value']} {r['typed_here'] or r['typed_everywhere']}"
                                    for r in rows if not r["shift"]][:8])
    REPORT.write_text(json.dumps({"by": BY, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--write" not in argv:
        print("[shift] dry run; --write to record the decisions")
        return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_has_tendency_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[shift] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    n = p.store.repredicate_cells(shift, by=BY, note="value typed tendency; MILD keeps tendency disjoint "
                                                      "from disposition (MILD_120101 has tendency)")
    p2 = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    now = Counter()
    left = []
    for _, ents in p2.store.view():
        for e, attrs in ents.items():
            for t in attrs:
                if t.startswith("has_tendency:"):
                    now["has_tendency"] += 1
                    now[(e, "has_disposition:" + t.split(":", 1)[1])] += 1
                if (e, t) in shift:
                    left.append((e, t))
    landed = sum(1 for k in shift if now[(k[0], k[1])] > 0)
    if left or landed != len(shift):
        raise RuntimeError(f"[shift] read back: {len(left)} cell(s) still read as has_disposition, "
                           f"{landed}/{len(shift)} read as has_tendency")
    print(f"[shift] written and read back: {n} cell decision(s); {landed} pair(s) now read as has_tendency "
          f"({now['has_tendency']} has_tendency cells in the view)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
