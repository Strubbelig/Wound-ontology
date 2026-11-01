#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The author's answers to the seven ELK conflicts of 2026-10-29, as author judgements.

    python -u scripts/apply_conflict_decisions_2026_10_29.py            # dry run
    python -u scripts/apply_conflict_decisions_2026_10_29.py --write

ELK over the author's own is_a links (`scripts/elk_author_conflicts.py`) found
seven terms that would have to be two kinds of thing BFO keeps apart. The
author decided each on the conflict page (claude.ai/artifact/XFtBnAuXGJHsFTW4PArTkP):

* Burn area keeps Area ("the size of the burn"): Immaterial anatomical entity goes.
* Burn wound surface keeps Thermal wound: Immaterial anatomical entity goes.
* Recurrence of wound is the moment the wound comes back: disease
  perpetuation process goes, process boundary stays.
* Infection, both senses: Infection keeps IDO's sense (the infected part of
  the body, a material entity); the process sense is `Infection process`,
  already its own term under GO biological process. Infection's process
  category and its biological process superclass go.
* Scarring, both senses ("Scarring process as wont class and leave scarring
  under HP"): Scarring stays HP's phenotypic abnormality, a quality; the
  process is WONT's `Scarring process`, which takes the process category.
* Lower extremity injury, both ("there is the injury but also the injuring
  process"): the injury stays a material entity; `Lower extremity injury
  process` (named the way a split names a sense: term + category) takes the
  superclass Trauma process.
* Pressure ulcer therapy, both ("Pressure ulcer therapy plan specification and
  Pressure ulcer therapy process"): split by category (rule 87); each sense
  takes what was decided for it. The split term keeps its own process
  category: the view judges a split mention by the split term's verdicts too,
  so a `no` there rejects the very typing that sends a mention to the process
  sense (first run, 07:37: the one process mention dropped out of the view).

Nothing is deleted: a withdrawn link is a later `no` by the author on the same
key, so the history stays on the record (rule 89).
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

PAGE = "conflict page (author, 2026-10-29)"
PUT_SENSES = {"process": "Pressure ulcer therapy process",
              "information entity": "Pressure ulcer therapy plan specification"}
LEI_PROCESS = "Lower extremity injury process"
#: Every name whose records or mentions this touches, for the read-back.
WATCH = ("Burn area", "Burn wound surface", "Recurrence of wound", "Infection", "Infection process",
         "Scarring", "Scarring process", "Lower extremity injury", LEI_PROCESS,
         "Pressure ulcer therapy", *PUT_SENSES.values())


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current
    from wound_ontology.mappers.term_mapping_and_gate import TERM_RULING, split_of
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    n_cats, n_placed = len(gt.categories()), len(gt.placements())
    print(f"[conflicts] {live.name}: {n_cats:,} decided categories, {n_placed:,} placements")

    def standing(term: str, key: str) -> dict:
        js = ((gt.records.get(term) or {}).get("is_a") or {}).get(key)
        cj = current(js)
        if not cj or cj["verdict"] != "yes":
            raise SystemExit(f"[conflicts] {term!r} is_a {key!r} does not stand yes ({cj}); nothing written")
        return cj

    def withdraw(term: str, key: str, why: str) -> None:
        cj = standing(term, key)
        iri = gt.placement_iri(term, key) if cj.get("iri") else None
        gt._put(term, "is_a", gt._j("no", "author", f"{PAGE}: {why}", iri=iri), key)
        print(f"  - {term} is_a {key}" + (f"  ({iri.rsplit('/', 1)[-1]})" if iri else "  (category)"))

    def place(term: str, key: str, iri: str, why: str) -> None:
        gt._put(term, "is_a", gt._j("yes", "author", f"{PAGE}: {why}", iri=iri), key)
        print(f"  + {term} is_a {key}  ({iri.rsplit('/', 1)[-1]})")

    def category(term: str, cat: str, why: str) -> None:
        out = gt.set_category(term, cat, source=TERM_RULING, note=f"{PAGE}: {why}")
        print(f"  + {term} category {cat}  ({out})")

    print("[conflicts] Burn area")
    withdraw("Burn area", "Immaterial anatomical entity", "keeps Area, the size of the burn")
    print("[conflicts] Burn wound surface")
    withdraw("Burn wound surface", "Immaterial anatomical entity", "keeps Thermal wound")
    print("[conflicts] Recurrence of wound")
    withdraw("Recurrence of wound", "disease perpetuation process",
             "the moment the wound comes back: a process boundary, not a process that takes time")

    print("[conflicts] Infection")
    withdraw("Infection", "biological_process",
             "Infection keeps IDO's sense, the infected part of the body; the process is Infection process")
    category("Infection", "material entity", "Infection keeps IDO's sense, the infected part of the body")
    category("Infection process", "process", "the process sense of Infection; Infection keeps IDO's sense")

    print("[conflicts] Scarring")
    category("Scarring", "quality", "left under HP: Scarring is HP's phenotypic abnormality; "
                                    "the process is WONT's Scarring process")
    category("Scarring process", "process", "the process sense of Scarring, as WONT's class")

    print("[conflicts] Lower extremity injury")
    trauma = standing("Lower extremity injury", "Trauma process")["iri"]
    withdraw("Lower extremity injury", "Trauma process",
             f"the injury stays a material entity; the injuring process is {LEI_PROCESS}")
    place(LEI_PROCESS, "Trauma process", trauma, "the injuring process of Lower extremity injury")
    category(LEI_PROCESS, "process", "the injuring process of Lower extremity injury")
    gt.gate(LEI_PROCESS, curator={"verdict": "in", "by": "author",
                                  "reason": f"{PAGE}: the injuring process of Lower extremity injury"})

    print("[conflicts] Pressure ulcer therapy")
    plan = standing("Pressure ulcer therapy", "Wound treatment plan specification")["iri"]
    withdraw("Pressure ulcer therapy", "Wound treatment plan specification",
             f"split: the plan is {PUT_SENSES['information entity']}")
    gt.split_by_category("Pressure ulcer therapy", PUT_SENSES, method="author")
    print(f"  = Pressure ulcer therapy split {PUT_SENSES}")
    category(PUT_SENSES["process"], "process", "the process sense of Pressure ulcer therapy")
    category(PUT_SENSES["information entity"], "information entity",
             "the plan sense of Pressure ulcer therapy")
    place(PUT_SENSES["information entity"], "Wound treatment plan specification", plan,
          "the plan sense of Pressure ulcer therapy")
    gt._dirty()

    if "--write" not in argv:
        print("[conflicts] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_conflict_decisions_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[conflicts] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()

    o2 = Orchestrator()
    g2 = o2.term_mapper._term_mapping
    cats = g2.categories()
    placed = set(g2.placements())
    bad = []
    want_cats = {"Infection": "material entity", "Infection process": "process", "Scarring": "quality",
                 "Scarring process": "process", LEI_PROCESS: "process", "Lower extremity injury": "material entity",
                 PUT_SENSES["process"]: "process", PUT_SENSES["information entity"]: "information entity",
                 "Recurrence of wound": "process boundary"}
    for t, c in want_cats.items():
        if (cats.get(t) or {}).get("verdict") != c:
            bad.append(f"category {t}: {cats.get(t)}")
    gone = [("Burn area", "Immaterial anatomical entity"), ("Burn wound surface", "Immaterial anatomical entity"),
            ("Recurrence of wound", "disease perpetuation process"), ("Infection", "biological_process"),
            ("Lower extremity injury", "Trauma process"),
            ("Pressure ulcer therapy", "Wound treatment plan specification")]
    bad += [f"still placed: {e}" for e in gone if e in placed]
    kept = [("Burn area", "Area"), ("Burn wound surface", "Thermal wound"), ("Infection process", "biological_process"),
            (LEI_PROCESS, "Trauma process"), (PUT_SENSES["information entity"], "Wound treatment plan specification")]
    bad += [f"not placed: {e}" for e in kept if e not in placed]
    if (cats.get("Pressure ulcer therapy") or {}).get("verdict") != "process":
        bad.append(f"Pressure ulcer therapy lost its process category: {cats.get('Pressure ulcer therapy')}")
    if split_of(g2.records.get("Pressure ulcer therapy") or {}) != PUT_SENSES:
        bad.append("split of Pressure ulcer therapy")
    if g2.gate_verdict(LEI_PROCESS)[0] != "in":
        bad.append(f"scope of {LEI_PROCESS}: {g2.gate_verdict(LEI_PROCESS)}")
    print(f"[conflicts] read back: {len(cats):,} decided categories (was {n_cats:,}), "
          f"{len(placed):,} placements (was {n_placed:,}); problems: {bad or 'none'}")
    abstracts: dict[str, set] = {}
    for key, ents in o2.store.view():
        for e in ents:
            if e in WATCH:
                abstracts.setdefault(e, set()).add(key)
    print("[conflicts] abstracts naming each term in the cleaned store:")
    for t in WATCH:
        print(f"  {t}: {len(abstracts.get(t, ()))}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
