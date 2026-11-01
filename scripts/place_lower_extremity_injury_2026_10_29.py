#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lower extremity injury under WONT's Injury, as an author judgement.

    python -u scripts/place_lower_extremity_injury_2026_10_29.py            # dry run
    python -u scripts/place_lower_extremity_injury_2026_10_29.py --write

On the conflict page (2026-10-29) the author kept Lower extremity injury as
the injury itself, a material entity, and withdrew Trauma process. That left
it no placed superclass, so the core build sent it to the candidates. The
author then placed it under WONT's Injury (WONT_0007817, "a pathological
disorder that is structural damage to a tissue or an organ, whatever its
cause"; added to WONT by the curator on 2026-10-20), which is a material
entity too.
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

WHY = ("author, 2026-10-29: the injury itself, a material entity, goes under WONT's Injury "
       "(its Trauma process superclass was withdrawn on the conflict page)")
TERM, KEY = "Lower extremity injury", "Injury"
IRI = "https://bioportal.bioontology.org/ontologies/WONT/WONT_0007817"


def main(argv: list[str]) -> int:
    import rdflib
    from config.settings import GROUND_TRUTH_TTL
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current
    g = rdflib.Graph(); g.parse(str(GROUND_TRUTH_TTL), format="turtle")
    label = g.value(rdflib.URIRef(IRI), rdflib.RDFS.label)
    if str(label) != KEY:
        raise SystemExit(f"[injury] {IRI} is labelled {label!r} in {GROUND_TRUTH_TTL.name}, not {KEY!r}; nothing written")

    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    rec = gt.records.get(TERM) or {}
    cat = (gt.categories().get(TERM) or {}).get("verdict")
    if cat != "material entity":
        raise SystemExit(f"[injury] {TERM!r} has category {cat!r}, not material entity; nothing written")
    cj = current(((rec.get("is_a") or {}).get(KEY)) or [])
    if cj and cj["verdict"] == "yes":
        print(f"[injury] {TERM} is_a {KEY} already stands ({cj['by']}, {cj['when']}); nothing to do")
        return 0
    n_placed = len(gt.placements())
    gt._put(TERM, "is_a", gt._j("yes", "author", WHY, iri=IRI), KEY)
    gt._dirty()
    print(f"[injury] {live.name}: + {TERM} is_a {KEY}  ({IRI.rsplit('/', 1)[-1]})")

    if "--write" not in argv:
        print("[injury] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_injury_placement_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[injury] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()

    o2 = Orchestrator()
    g2 = o2.term_mapper._term_mapping
    placed = set(g2.placements())
    bad = []
    if (TERM, KEY) not in placed:
        bad.append(f"not placed: {(TERM, KEY)}")
    if g2.placement_iri(TERM, KEY) != IRI:
        bad.append(f"iri: {g2.placement_iri(TERM, KEY)}")
    if (TERM, "Trauma process") in placed:
        bad.append("Trauma process is back")
    n_abs = sum(1 for _, ents in o2.store.view() if TERM in ents)
    print(f"[injury] read back: {len(placed):,} placements (was {n_placed:,}); "
          f"{TERM} named in {n_abs} abstracts of the cleaned store; problems: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
