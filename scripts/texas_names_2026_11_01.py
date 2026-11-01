#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The term dict follows WONT's University of Texas class: its names, and CQ041 retired (2026-11-01).

    python -u scripts/texas_names_2026_11_01.py            # dry run
    python -u scripts/texas_names_2026_11_01.py --write

The curator decided WONT_0000375 is the University of Texas wound
classification ("University of Texas"). The rebuild on WONT 2026-11-01 showed
what the term dict still held:

* "University of Texas wound classification" was named "University of Texas
  wound classification system" (accepted in bulk 2026-09-25, when WONT had no
  such class). An ontology's own label is canonical and never mapped onto
  another (rule 36): it keeps its own name now, and the variants the build had
  minted beside the curated class -- "... system", "University of Texas
  classification", "Texas classification", "University of Texas diabetic wound
  classification system" -- are named as it, so they are the curated class.
* "Wagner and Anderson wound classification (grade)" held his relations on the
  class under its old name (is_about Diabetic foot ulcer, is_about Wound); with
  the name gone the build found their subject only among the candidates. They
  are named as the renamed classes, so the relations follow; a relation that
  makes a Wagner grade part of the Texas classification gets his `no`.
* CQ041 asked "Clean wound according to IWII has_quality Sterile", of the class
  he made obsolete ("Veraltet ohne Ersatz"); it is retired as CQ003 was, its
  premise gone.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

UT, UT_GRADE = "University of Texas wound classification", "University of Texas wound classification grade"
NAMES = {UT: UT,
         "University of Texas wound classification system": UT,
         "University of Texas classification": UT,
         "Texas classification": UT,
         "University of Texas diabetic wound classification system": UT,
         "Wagner and Anderson wound classification": UT,
         "Wagner and Anderson wound classification grade": UT_GRADE}
WHY = ("curator 2026-11-01 (\"University of Texas\"): WONT_0000375 is the University of Texas wound classification "
       "(WONT ground_truth_final_2026-11-01.owl); an ontology's own label is canonical (rule 36), so this name is that "
       "class; applied by Claude")
WHY_NO = ("curator 2026-11-01 (\"University of Texas\"): a Wagner grade is no part of the University of Texas wound "
          "classification")
CQ_FILE = ROOT / "config" / "competency_questions.json"
CQ_REASON = ("Premise gone 2026-11-01 (curator: \"Veraltet ohne Ersatz\"): the IWII wound infection continuum has no "
             "clean or sterile stage, so Clean wound according to IWII is obsolete; a clean wound is the CDC class, "
             "which is not the same thing.")


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current
    gt = Orchestrator().term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    for term, name in NAMES.items():
        if term not in gt.records:
            raise SystemExit(f"[texas] no record {term!r}; nothing written")
        before = current(gt.records[term].get("name"))
        gt._put(term, "name", gt._j(name, "author", WHY))
        print(f"[texas] {term!r}: named {(before or {}).get('verdict')!r} -> {name!r}")
    noes = []
    for c in (UT, UT_GRADE):
        rec = gt.records.get(gt.concept(gt.resolve(c))) or {}
        for key in list((rec.get("relations") or {})):
            pred, _, tgt = key.partition(":")
            if pred.strip() == "has_part" and "wagner" in tgt.lower():
                gt._put(gt.concept(gt.resolve(c)), "relations", gt._j("no", "author", WHY_NO), key)
                noes.append((c, key))
    print(f"[texas] author 'no' on {len(noes)} relation(s) making a Wagner grade part of the Texas class: {noes}")
    for c in (UT, UT_GRADE):
        k = gt.concept(gt.resolve(c))
        print(f"[texas] {c!r} is now the concept {k!r} with relations {sorted((gt.records.get(k) or {}).get('relations') or {})[:12]}")

    q = json.loads(CQ_FILE.read_text(encoding="utf-8"))
    moved = 0
    for th in q["clinical_themes"]:
        keep = []
        for cq in th.get("in_scope", []):
            if cq.get("id") == "CQ041":
                th.setdefault("out_of_scope", []).append(
                    {"id": "CQ041", "question": cq["question"], "reason": CQ_REASON,
                     "retired_triple": cq["example_triple"], "retired": "2026-11-01"})
                moved += 1
            else:
                keep.append(cq)
        th["in_scope"] = keep
    if moved != 1:
        raise SystemExit(f"[texas] CQ041 found {moved} times in scope; nothing written")
    print("[texas] CQ041 retired (out of scope, premise gone)")

    if "--write" not in argv:
        print("[texas] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_texas_names_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    shutil.copy2(CQ_FILE, ROOT / "data" / "backup" / f"competency_questions_before_cq041_{datetime.now():%Y-%m-%d_%H-%M}.json")
    print(f"[texas] backed up {live.name} and {CQ_FILE.name}")
    gt.save()
    CQ_FILE.write_text(json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    g2 = Orchestrator().term_mapper._term_mapping
    bad = [t for t, n in NAMES.items() if g2.concept(g2.resolve(t)) != g2.concept(g2.resolve(n))]
    if bad:
        raise SystemExit(f"[texas] read back: not named as meant: {bad}")
    print("[texas] read back: every name points at the renamed classes; CQ file written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
