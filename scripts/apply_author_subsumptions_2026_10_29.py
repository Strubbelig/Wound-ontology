#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The author's `narrower` / `broader` between two terms, written as is_a `yes`.

    python -u scripts/apply_author_subsumptions_2026_10_29.py            # dry run
    python -u scripts/apply_author_subsumptions_2026_10_29.py --write

Rule 89 (curator, 2026-10-28): "the author's 44 `narrower` / `broader` between
two terms are also written as `is_a` `yes` (by author), so they act in the
hierarchy". `narrower` puts the term under the pair's other term, `broader` the
other way round (as `subsumption_candidates` reads them).

The link is written on the concept that answers is_a for the child now, under
the name its parent is written now: a pair answered on `Hydrocolloid dressing`
lands on `Ordinary hydrocolloid dressing`, the name the author gave it later;
`why` names the author's answer in the words it was given. An answer given on
both sides of a pair (`Burn wound` / `Burn injury`) is one link. A parent that
is no term (`Giant-sized` / `Sized`) is written as well -- it is the author's
answer -- and `term_links` leaves it out of the hierarchy.
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

DECIDED = "rule 89, curator 2026-10-28: the author's narrower/broader between two terms act in the hierarchy"
EXPECTED = 44


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current, rank, AUTHOR
    from wound_ontology.orchestrator import PLACEMENT_MIN_ABSTRACTS
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)

    answers = []
    for t, r in gt.records.items():
        for c, js in (r.get("pairs") or {}).items():
            au = [j for j in js if j["by"] == "author"]
            if au and au[-1]["verdict"] in ("narrower", "broader"):
                answers.append((t, c, au[-1]["verdict"]))
    if len(answers) != EXPECTED:
        raise SystemExit(f"[subsume] {len(answers)} answers, not the {EXPECTED} rule 89 decided on; nothing written")

    links: dict[tuple[str, str], list[str]] = {}
    for t, c, v in sorted(answers):
        child, parent = (t, c) if v == "narrower" else (c, t)
        ch, pa = gt.concept(gt.resolve(child)), gt.concept(gt.resolve(parent))
        said = f"{t!r} {v} than {c!r}"
        renamed = [f"{a!r} is now {b!r}" for a, b in ((child, ch), (parent, pa)) if a != b]
        links.setdefault((ch, pa), []).append(said + (f" ({'; '.join(renamed)})" if renamed else ""))
    print(f"[subsume] {live.name}: {len(answers)} answers -> {len(links)} links")

    same = [(ch, pa) for ch, pa in links if ch == pa]
    if same:
        raise SystemExit(f"[subsume] both ends name one concept: {same}; nothing written")
    n_links = len(gt.term_links())
    wrote, stood = [], []
    for (ch, pa), said in sorted(links.items()):
        cj = current(((gt.records.get(ch) or {}).get("is_a") or {}).get(pa) or [])
        if cj and cj["verdict"] == "yes" and rank(cj) == AUTHOR:
            stood.append((ch, pa))
            print(f"  = {ch} is_a {pa}  (stands already: {cj['why'][:70]})")
            continue
        gt._put(ch, "is_a", gt._j("yes", "author", f"the author's answer: {'; '.join(said)} ({DECIDED})"), pa)
        wrote.append((ch, pa))
        print(f"  + {ch} is_a {pa}" + ("" if pa in gt.records else "  [parent is no term]"))
    gt._dirty()
    print(f"[subsume] {len(wrote)} written, {len(stood)} stood already")

    if "--write" not in argv:
        print("[subsume] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_author_subsumptions_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[subsume] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()

    o2 = Orchestrator()
    g2 = o2.term_mapper._term_mapping
    got = set(g2.term_links())
    seen: dict[str, set] = {}
    for key, ents in o2.store.view():
        for e in ents:
            seen.setdefault(e, set()).add(key)
    bad = [f"not read back: {e}" for e in wrote if
           current(((g2.records.get(e[0]) or {}).get("is_a") or {}).get(e[1]) or [])["verdict"] != "yes"]
    print(f"[subsume] read back: {len(got)} author link(s) between two terms in scope (was {n_links}); "
          f"problems: {bad or 'none'}")
    for ch, pa in sorted(links):
        n_c, n_p = len(seen.get(ch, ())), len(seen.get(pa, ()))
        if (ch, pa) not in got:
            state = "not read as a link (an end out of scope or no term)"
        elif min(n_c, n_p) >= PLACEMENT_MIN_ABSTRACTS:
            state = "BUILT"
        else:
            state = f"below the cut ({n_c} / {n_p} abstracts)"
        print(f"  {ch} is_a {pa}: {state}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
