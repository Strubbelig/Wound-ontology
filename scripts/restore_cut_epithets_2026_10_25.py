#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Give back the final -s the singular rule cut off Latin and invariant words.

    python -u scripts/restore_cut_epithets_2026_10_25.py            # dry run
    python -u scripts/restore_cut_epithets_2026_10_25.py --write

Found 2026-10-25 behind `Streptococcus pyogene`: pass 0 had written names that
do not exist -- `pyogene`, `Bacteroide`, `Pancrea`, `Atla`, `Risk-of-bia`. The
rule is fixed (`label_match._INVARIANT`, and the last part of a hyphenated word
is checked against it); this restores the names already written. Each row is a
current name and the name `normalise` now gives the spellings that were cut to
it; the cut name becomes an alias of the restored one, the old alias gives way
(`spelling_reversed`), and the decisions move with the record
(`TermMappingAndGate.apply_renames`).

Only the names the fix is about. Aliases that `normalise` now answers
differently for another reason (`RESULTS` -> `Result`, `ADLS` -> `ADL`, a
trailing hyphen) are left alone: they are other decisions.
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

BY = "curator 2026-10-25: Latin and invariant words keep their final s"

RESTORE = {
    "Streptococcus pyogene": "Streptococcus pyogenes",
    "Group A Streptococcus pyogene": "Group A Streptococcus pyogenes",
    "S. pyogene": "S. pyogenes",
    "Cutibacterium acne": "Cutibacterium acnes",
    "Shewanella putrefacien": "Shewanella putrefaciens",
    "Mycosis fungoide": "Mycosis fungoides",
    "Myositis ossifican": "Myositis ossificans",
    "Actinomyce": "Actinomyces",
    "Apophysomyce": "Apophysomyces",
    "Aeromona": "Aeromonas",
    "Brevundimona": "Brevundimonas",
    "Stenotrophomona": "Stenotrophomonas",
    "Bacteroide": "Bacteroides",
    "Parabacteroide": "Parabacteroides",
    "Pancrea": "Pancreas",
    "Murine pancrea": "Murine pancreas",
    "Healthy human pancrea": "Healthy human pancreas",
    "Iliopsoa": "Iliopsoas",
    "Hypospadia": "Hypospadias",
    "Proximal hypospadia": "Proximal hypospadias",
    "Atla": "Atlas",
    "Single-cell atla": "Single-cell atlas",
    "Single-cell transcriptional atla": "Single-cell transcriptional atlas",
    "The cancer genome atla": "The cancer genome atlas",
    "Risk-of-bia": "Risk-of-bias",
    "Low-bia": "Low-bias",
    "Cochrane's risk-of-bia": "Cochrane's risk-of-bias",
    "Type-2-diabete": "Type-2-diabetes",
    "Kruskal-walli": "Kruskal-wallis",
    "Preferred reporting items for systematic reviews and meta-analysi":
        "Preferred reporting items for systematic reviews and meta-analysis",
    "Texa": "Texas",
    "America": "Americas",
    "Las vega": "Las vegas",
    "Evan": "Evans",
}


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.normalise import normalise
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    # every row must be what the fixed rule now says, and a live name today
    bad = [(cut, full) for cut, full in RESTORE.items()
           if cut not in gt.records or gt.is_alias(cut)
           or not any(not gt.records[a].get("spelling") is None and gt.records[a]["spelling"]["to"] == cut
                      and normalise(a).name == full for a in gt.records)]
    if bad:
        print(f"[restore] {len(bad)} row(s) are not a live cut name the rule now restores: {bad}")
        return 1
    for cut, full in RESTORE.items():
        print(f"  {cut!r} -> {full!r}" + ("  (merges into an existing record)" if full in gt.records else ""))
    if "--write" not in argv:
        print(f"[restore] {len(RESTORE)} name(s); dry run, --write to apply")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_restore_epithets_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[restore] backed up {live.name} -> {backup.relative_to(ROOT)}")
    report = o.store.apply_renames(RESTORE, by=BY)
    print(f"[restore] {report.get('keys renamed', 0)} key(s) renamed, "
          f"{report.get('spellings reversed', 0)} alias(es) reversed, "
          f"{report.get('records merged', 0)} record(s) merged; "
          f"locked targets {report.get('locked targets') or 'none'}")
    g2 = Orchestrator().term_mapper._term_mapping
    left = [c for c in RESTORE if c in g2.records and not g2.is_alias(c)]
    wrong = [f for f in RESTORE.values() if f not in g2.records or g2.is_alias(f)]
    print(f"[restore] read back: cut names still live: {left or 'none'}; "
          f"restored names missing: {wrong or 'none'}; split pairs: {len(g2.split_synonyms())}; "
          f"locked mappings: {g2.locked_mappings() or 'none'}")
    return 1 if left or wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
