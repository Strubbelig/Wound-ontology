#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The author's answers to the questions his pair-page notes raised, 2026-10-29.

    python -u scripts/apply_pair_followups_2026_10_29.py            # dry run
    python -u scripts/apply_pair_followups_2026_10_29.py --write

* Debridement method "is the plan specification": placed under WONT's Wound
  treatment plan specification (WONT_0000200), as Pressure ulcer therapy plan
  specification was that morning.
* Aseptic conditions "have the quality aseptic", the conditions themselves:
  kept apart from WONT's Aseptic conditions plan specification, whose exact
  synonym it is, with the relation has quality Aseptic. The author removes the
  synonym from WONT himself; until then the export files the term under the plan.
* Acute infection, "I would add the end word to infection", for all process
  terms ending in "infection": each is renamed "<term> process", the way
  Infection's process sense is Infection process. Its decisions move with it
  (`apply_renames`); the plain name points at the new one. A term that is an
  ontology class's label keeps its name and the ontology's sense (the author's
  rule): Methicillin-resistant Staphylococcus aureus infection (HP) and Viral
  infection (DOID). Acute infection disorder, kept apart on the pair page as
  "the acute infection material entity", takes that category.
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

ASKED = "author, 2026-10-29, answering the questions his pair-page notes raised"
WTPS = ("Wound treatment plan specification", "https://bioportal.bioontology.org/ontologies/WONT/WONT_0000200")
ASEPTIC_PLAN = "Aseptic conditions plan specification"
END_WORD = "infection"


def main(argv: list[str]) -> int:
    import rdflib
    from config.settings import GROUND_TRUTH_TTL
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current
    from wound_ontology.mappers.term_mapping_and_gate import TERM_RULING
    from wound_ontology.owl.extend import label_index, default_lexicon, lexicon_index
    g = rdflib.Graph(); g.parse(str(GROUND_TRUTH_TTL), format="turtle")
    if str(g.value(rdflib.URIRef(WTPS[1]), rdflib.RDFS.label)) != WTPS[0]:
        raise SystemExit(f"[followups] {WTPS[1]} is not {WTPS[0]!r} in {GROUND_TRUTH_TTL.name}; nothing written")
    idx, imp = label_index(g), lexicon_index(default_lexicon())

    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    print(f"[followups] {live.name}")

    # Debridement method
    if gt.concept(gt.resolve("Debridement method")) != "Debridement method":
        raise SystemExit("[followups] Debridement method is not its own concept; nothing written")
    gt._put("Debridement method", "is_a", gt._j("yes", "author", f"{ASKED}: 'Debridement method is the plan "
            "specification'; under WONT's Wound treatment plan specification", iri=WTPS[1]), WTPS[0])
    print(f"  + Debridement method is_a {WTPS[0]}")

    # Aseptic conditions
    gt._put("Aseptic conditions", "pairs", gt._j("different", "author", f"{ASKED}: the conditions themselves, "
            "not WONT's plan; the author removes the exact synonym from WONT"), ASEPTIC_PLAN)
    gt._put("Aseptic conditions", "relations", gt._j("yes", "author", f"{ASKED}: 'aseptic conditions have the "
            "quality aseptic'"), "has_quality: Aseptic")
    print(f"  + Aseptic conditions different from {ASEPTIC_PLAN}; has_quality: Aseptic")

    # Acute infection disorder
    gt.set_category("Acute infection disorder", "material entity", source=TERM_RULING,
                    note=f"{ASKED}: 'the acute infection material entity' (pair page note)")
    print("  + Acute infection disorder category material entity")

    # The end word
    cats = gt.categories()
    terms = sorted(t for t, c in cats.items() if t.lower().endswith(END_WORD) and c["verdict"] == "process"
                   and gt.concept(gt.resolve(t)) == t)
    kept = [t for t in terms if idx.get(t.lower())[0] is not None or imp.get(t.lower())[0] is not None]
    renames = {t: f"{t} process" for t in terms if t not in kept}
    taken = [n for n in renames.values() if n in gt.records or gt.concept(gt.resolve(n)) != n]
    if taken:
        raise SystemExit(f"[followups] new names already in use: {taken}; nothing written")
    print(f"[followups] {len(terms)} process terms end in {END_WORD!r}: {len(renames)} renamed, "
          f"{len(kept)} keep an ontology class's name: {kept}")
    for t in list(renames)[:5]:
        print(f"  ~ {t} -> {renames[t]}")
    placed_before = {t for t, _ in gt.placements()}
    n_placed = len(gt.placements())

    if "--write" not in argv:
        print("[followups] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_pair_followups_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[followups] backed up {live.name} -> {backup.relative_to(ROOT)}")
    rep = gt.apply_renames(renames, by="author", why=f"{ASKED}: 'I would add the end word to infection' -- a process "
                           f"ending in '{END_WORD}' carries 'process' in its name, as Infection process does")
    print(f"[followups] rename report: { {k: v for k, v in rep.items() if v} }")

    o2 = Orchestrator()
    g2 = o2.term_mapper._term_mapping
    bad = []
    c2 = g2.categories()
    for old, new in renames.items():
        if g2.concept(g2.resolve(old)) != new:
            bad.append(f"{old} does not lead to {new}")
        if (c2.get(new) or {}).get("verdict") != "process":
            bad.append(f"{new}: category {c2.get(new)}")
    placed_after = {t for t, _ in g2.placements()}
    lost = {renames[t] for t in placed_before if t in renames} - placed_after
    if lost:
        bad.append(f"placements lost: {sorted(lost)[:5]}")
    if len(g2.placements()) != n_placed:        # counted with Debridement method's already in
        bad.append(f"placements {len(g2.placements())}, expected {n_placed}")
    loops = []
    for t in list(g2.records):
        try:
            g2.concept(g2.resolve(t))
        except RuntimeError:
            loops.append(t)
    if loops:
        bad.append(f"{len(loops)} string(s) in a loop of names: {loops[:5]}")
    if ("Debridement method", WTPS[0]) not in set(g2.placements()):
        bad.append("Debridement method not placed")
    cj = current(g2.records["Aseptic conditions"]["relations"]["has_quality: Aseptic"])
    if (cj["verdict"], cj["by"]) != ("yes", "author"):
        bad.append("Aseptic conditions has_quality")
    if (c2.get("Acute infection disorder") or {}).get("verdict") != "material entity":
        bad.append("Acute infection disorder category")
    if rep.get("category conflicts") or rep.get("target conflicts") or rep.get("locked targets"):
        bad.append(f"rename conflicts: {rep.get('category conflicts')} {rep.get('target conflicts')} "
                   f"{rep.get('locked targets')}")
    print(f"[followups] read back: {len(g2.placements()):,} placements (was {n_placed:,}); problems: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
