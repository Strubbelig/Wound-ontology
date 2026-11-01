#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The curator's answers to the rejoin dry run of 2026-10-25 (rule 85).

    python -u scripts/apply_rejoin_decisions_2026_10_25.py            # dry run
    python -u scripts/apply_rejoin_decisions_2026_10_25.py --write

The dry run of `rejoin_confirmed_synonyms.py` would have merged 211 pairs of
clusters. Claude read them and found 17 wrong; the curator, 2026-10-25: "ja,
alles so machen; Wound symptom als spec dependent continuant". Run this BEFORE
the rejoin, so the rejoin no longer sees the wrong joins.

The wrong step was not always the pair the curator called `same_class`: often
that pair was right (`Gram-negative bacilli` = `Gram-negative bacillus`) and a
mapping beside it was wrong (`Gram-negative bacillus` -> `Bacillus species`).
So each row names the link that is wrong, with the verdict that replaces it;
a mapping on that link is undone. A standing curator verdict moves to
`curator_history` -- nothing is deleted.
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

BY = "curator 2026-10-25, rejoin review"
WHEN = "2026-10-25T21:00:00"

# (term, canonical, verdict, why) -- the verdict says what `term` is to `canonical`
VERDICTS = [
    # the 17 wrong joins
    ("Acute trauma wound", "Acute wound", "narrower", "a traumatic acute wound is one kind of acute wound"),
    ("Gram-negative bacillus", "Bacillus species", "different", "Bacillus is gram-positive"),
    ("Burn patient", "Severely burned patient", "broader", "not every burn patient is severely burned"),
    ("Higher BMI", "obesity", "different", "a measured value is not the disease"),
    ("Outcome", "Improvement in outcome", "different", "an outcome is not its improvement"),
    ("Improvement in outcome", "Outcome", "different", "an outcome is not its improvement"),
    ("PLGA", "poly(ethylene oxide)", "different", "two different polymers"),
    ("Extremity injury", "Traumatic extremity injury", "broader", "not every extremity injury is traumatic"),
    ("Traumatic extremity injury", "Extremity injury", "narrower", "not every extremity injury is traumatic"),
    ("Burn wound", "Severity burn", "different", "a wound is not its severity"),
    ("Inflammation", "Excess inflammation", "broader", "excess inflammation is one kind of inflammation"),
    ("Hydrocolloid dressing", "Hydrocolloid gel dressing", "broader", "a gel dressing is one kind of hydrocolloid dressing"),
    ("P < 0.001", "P = 0.001", "different", "a bound is not a value"),
    ("Postoperative poor healing", "Postoperative wound healing", "narrower", "poor healing is one course of healing"),
    ("Vascularization", "Vascularity", "different", "a process is not a quality"),
    ("Standardized perioperative protocol", "Perioperative protocol", "narrower", "one kind of perioperative protocol"),
    ("High-risk patient", "High-risk patient group", "different", "a person is not a group"),
    ("Deep partial-thickness burn wound", "Deep partial-thickness thermal burn injury", "broader",
     "a burn need not be thermal"),
    ("Dressing adhesive", "Adhesive dressing", "different", "the glue is not the dressing"),
    # the 9 held cases
    ("Antioxidative activity", "Antioxidative property", "different",
     "the curator keeps effect and property apart; activity was read as the effect"),
    ("Traumatic dental injury", "Dental injury", "narrower", "not every dental injury is traumatic"),
    ("Elderly person", "Elderly population", "different", "a person is not a group"),
    ("Extremity salvage method", "Extremity-salvage therapy", "different", "a method is not the treatment"),
    ("Extremity-salvage therapy", "Extremity salvage method", "different", "a method is not the treatment"),
    ("Therapy", "Treatment method", "different", "a treatment is not its method"),
    ("Debridement method", "Debridement", "different", "a method is not the procedure"),
    ("vitamin (role)", "vitamin", "different", "two senses, kept apart on purpose"),
]

# term rulings: one cluster has one category
CATEGORIES = [
    ("Wound-related symptom", "specifically dependent continuant",
     "same class as Wound symptom (curator 2026-10-25)"),
    ("Therapy", "process", "joined under Treatment (curator 2026-10-25)"),
]

# (chosen, instead_of)
NAMES = [
    ("Candida albicans", "Candida albican"),           # the singular rule cut the epithet
    ("Outcome measurement", "OUTCOMES AND MEASURE"),   # an abstract heading is not a name
    ("Treatment", "Therapy"),
    ("Poly (lactic-co-glycolic acid)", "PLGA"),         # no abbreviations (rule 58)
]


def set_verdict(gt, term: str, canonical: str, verdict: str, why: str) -> str:
    """`refuse` without its save: the curator's verdict on the pair, the
    standing one into `curator_history`, the mapping undone if it is this pair."""
    if term not in gt.records:
        raise KeyError(f"{term!r} is not in the term dict")
    standing = gt.peek(term, canonical).get("curator")
    if standing and standing.get("verdict") == verdict and standing.get("by") == BY:
        return "already"                       # a second run changes nothing
    j = gt.judgement(term, canonical)
    if standing:
        j.setdefault("curator_history", []).append(standing)
    gt.judge(term, canonical, curator={"verdict": verdict, "reason": why, "by": BY, "when": WHEN})
    rec = gt.record(term)
    if rec.get("to") == canonical:
        rec["to"] = None
        return "unmapped"
    return "pair only"


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    if "--write" in argv:
        backup = ROOT / "data" / "backup" / f"term_mapping_before_rejoin_decisions_{datetime.now():%Y-%m-%d_%H-%M}.json"
        shutil.copy2(live, backup)
        print(f"[decisions] backed up {live.name} -> {backup.relative_to(ROOT)}")
    for t, c, v, why in VERDICTS:
        before = gt.peek(t, c).get("curator") or {}
        what = set_verdict(gt, t, c, v, why)
        print(f"  {t!r} -> {c!r}: {before.get('verdict') or '-'} -> {v} ({what})")
    for t, cat, note in CATEGORIES:
        print(f"  category {t!r}: {gt.set_category(t, cat, source='term ruling', by=BY, note=note)} {cat}")
    for chosen, instead in NAMES:
        gt.decide_name(chosen, instead, by=BY, when=WHEN, reason=f"chose {chosen!r} as the name")
        print(f"  name {chosen!r} over {instead!r}: head now {gt._head(chosen)!r}")
    gt._dirty(); gt._gate_idx = None
    print(f"[decisions] split pairs now: {len(gt.split_synonyms())}; locked mappings: "
          f"{gt.locked_mappings() or 'none'}")
    if "--write" not in argv:
        print("[decisions] dry run; --write to apply")
        return 0
    gt.save()
    g2 = Orchestrator().term_mapper._term_mapping
    bad = [(t, c) for t, c, v, _ in VERDICTS if (g2.peek(t, c).get("curator") or {}).get("verdict") != v]
    print(f"[decisions] read back: verdicts not as written: {bad or 'none'}; "
          f"locked mappings: {g2.locked_mappings() or 'none'}")
    return 1 if bad or g2.locked_mappings() else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
