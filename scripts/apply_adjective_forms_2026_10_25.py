#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Leading grades in every form, and the names the hyphen bug cut (2026-10-25).

    python -u scripts/apply_adjective_forms_2026_10_25.py            # dry run
    python -u scripts/apply_adjective_forms_2026_10_25.py --write

The curator, 2026-10-25: "diese ganzen adjektive wie poorer oder severly sollten
eigentlich schon lange gelöscht sein" and "dann lösch neben large auch
large-scale". The rule of 2026-09-28 (`normalise.LEADING_ADJECTIVES`) knew
`poor` and `severe` but not `poorer`, `worst` or `severely`; it now does, and
strips `large-scale` whole.

Found on the way: the same rule cut at a hyphen, so `large-vessel vasculitis`
had become `Vessel vasculitis`, `advanced-stage pressure ulcer` `Stage pressure
ulcer`, `standard-of-care dressing` `Of-care dressing` (81 spellings). The rule
no longer cuts there. This script, in order:

1. Restores each cut name. Where the cut name is itself a string the abstracts
   wrote (`Risk`, `Severity`), its record is that string's and stays; only the
   hyphenated spellings are freed from it. Otherwise the record is renamed.
2. Moves two curator verdicts of this morning to `curator_history`: they kept a
   graded term apart from its base (`Burn patient` broader than `Severely
   burned patient`), which the rule now makes one class.
3. Runs pass 0, which writes the new graded forms as aliases of their base.

`--after` (run once after `--write`, 2026-10-25): pass 0 merged `Excess wound
fluid` into `Wound fluid` and `Potentially pathogenic microorganism` into
`Pathogenic microorganism`, and the curator's placement of the graded form
(`narrower`) displaced the base form's mapping. Without the grade they are the
same term, so the placement goes to `curator_history` and the mapping comes
back. And `Care` came to point through `Standard of care` at `Standard of
patient care`, where the curator had put it: the chain is closed.
"""
from __future__ import annotations

import collections
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

BY = "curator 2026-10-25: a hyphenated modifier is not a leading grade"
WHEN = "2026-10-25T22:00:00"

# where `normalise` cannot give the right name from the old spellings
OVERRIDE = {
    "Intensity physical activity": "Moderate-intensity physical activity",   # PA spelled out
    "Stage pressure ulcer": "Advanced-stage pressure ulcer",
}

# this morning's verdicts the adjective rule supersedes
SUPERSEDED = [("Burn patient", "Severely burned patient"),
              ("Inflammation", "Excess inflammation")]


def raw_strings(store) -> set[str]:
    """Every entity and target string as the abstracts wrote it."""
    out = set()
    for rec in store._dict.values():
        for e, attrs in (rec.get("entities") or {}).items():
            out.add(e)
            out.update(t.split(":", 1)[1].strip() for t in attrs if ":" in t)
    return out


def plan(gt, raw: set[str]) -> tuple[dict, dict, list]:
    from wound_ontology.utils.normalise import LEADING_ADJECTIVES, normalise
    by_target = collections.defaultdict(list)
    for t, r in gt.records.items():
        if isinstance(r.get("spelling"), dict):
            by_target[r["spelling"]["to"]].append(t)
    renames, freed, unclear = {}, {}, []
    for cut, olds in by_target.items():
        if cut not in gt.records or gt.is_alias(cut):
            continue
        hyph, names = [], set()
        for o in olds:
            m = re.match(r"^([A-Za-z]+)[-‐‑](\S+)", o)
            if not m or m.group(1).lower() not in LEADING_ADJECTIVES:
                continue
            tail = o[m.start(2):].lower()
            if not (tail == cut.lower() or tail.startswith(cut.lower()[:-1].split()[0])):
                continue
            name = OVERRIDE.get(cut) or normalise(o).name
            if name != cut:
                hyph.append(o); names.add(name)
        if not hyph:
            continue
        if len(names) != 1:
            unclear.append((cut, sorted(names)))
            continue
        name = names.pop()
        # the cut name is a string of its own when the abstracts wrote it, or a
        # spelling of it that is not one of the hyphenated ones
        own = [s for s in [cut, *olds] if s in raw and s not in hyph and normalise(s).name == cut]
        if own:
            freed[cut] = (name, hyph)
        else:
            renames[cut] = name
    return renames, freed, unclear


AFTER = [("Wound fluid", "Wound exudate"), ("Pathogenic microorganism", "Pathogen")]


def after() -> int:
    from wound_ontology.orchestrator import Orchestrator
    gt = Orchestrator().term_mapper._term_mapping
    for t, c in AFTER:
        j = gt.judgement(t, c)
        cur = j.get("curator") or {}
        if cur.get("verdict") == "narrower":
            j.setdefault("curator_history", []).append(
                {**j.pop("curator"), "superseded": "placed the graded form; without the grade it is this term",
                 "superseded when": WHEN})
            j["curator"] = {"verdict": "same_class", "by": BY, "when": WHEN,
                            "reason": "the mapping the curator had kept before the graded form merged in"}
        gt.record(t).update({"to": c, "method": "curator", "confidence": 1.0})
    gt.record("Care")["to"] = gt._head("Standard of care")
    gt._dirty(); gt.save()
    g2 = Orchestrator().term_mapper._term_mapping
    chains = [(t, r["to"]) for t, r in g2.records.items()
              if r.get("to") and "spelling" not in r and (g2.records.get(r["to"]) or {}).get("to")]
    print(f"[adjectives] after: split pairs {g2.split_synonyms()}; chains {chains or 'none'}; "
          f"locked mappings {g2.locked_mappings() or 'none'}")
    return 1 if chains or g2.locked_mappings() else 0


def main(argv: list[str]) -> int:
    if "--after" in argv:
        return after()
    from wound_ontology.orchestrator import Orchestrator
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    renames, freed, unclear = plan(gt, raw_strings(o.store))
    print(f"[adjectives] cut names: {len(renames)} renamed, {len(freed)} kept as their own "
          f"string with the hyphenated spellings freed, {len(unclear)} unclear")
    for cut, name in sorted(renames.items()):
        print(f"    {cut!r} -> {name!r}")
    for cut, (name, hyph) in sorted(freed.items()):
        print(f"    {cut!r} stays; {hyph} -> {name!r}")
    for u in unclear:
        print(f"    UNCLEAR {u}")
    if unclear:
        return 1
    if "--write" not in argv:
        print("[adjectives] dry run; --write to apply (then pass 0 runs)")
        return 0

    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_adjective_forms_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[adjectives] backed up {live.name} -> {backup.relative_to(ROOT)}")

    for t, c in SUPERSEDED:
        j = gt.judgement(t, c)
        if j.get("curator"):
            j.setdefault("curator_history", []).append(
                {**j.pop("curator"), "superseded": "the leading-grade rule makes them one class",
                 "superseded when": WHEN})
    for cut, (name, hyph) in freed.items():
        for h in hyph:
            rec = gt.records[h]
            rec.setdefault("spelling_reversed", []).append(rec.pop("spelling"))
            rec.setdefault("to", None); rec.setdefault("pairs", {})
    gt._dirty(); gt.save()
    # a freed spelling is now a name of its own; respell it to the restored form
    respell = {h: name for cut, (name, hyph) in freed.items() for h in hyph if h != name}
    report = o.store.apply_renames({**renames, **respell}, by=BY)
    print(f"[adjectives] {report.get('keys renamed', 0)} key(s) renamed, "
          f"{report.get('spellings reversed', 0)} alias(es) reversed, "
          f"{report.get('records merged', 0)} record(s) merged; "
          f"locked targets {report.get('locked targets') or 'none'}")

    o2 = Orchestrator()
    o2.run_pass0_normalise(dry_run=False)
    g3 = Orchestrator().term_mapper._term_mapping
    left = [c for c in renames if c in g3.records and not g3.is_alias(c)]
    print(f"[adjectives] read back: cut names still live: {left or 'none'}; "
          f"split pairs: {g3.split_synonyms()}; locked mappings: {g3.locked_mappings() or 'none'}")
    return 1 if left or g3.locked_mappings() else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
