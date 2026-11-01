"""Every judgement in its question's own answers, by translation, not by asking again (2026-10-30).

Asked whether the placement reading had to be asked again in the term dict's
answers, the curator: "Warum neu fragen, kannst du nicht einfach die Antworten
mappen". The placement reading was already written in them (is_a yes/no, pairs
same_class/different); reading it through found three kinds of judgement
outside or beside what was answered:

1. `claude-opus-5-5_placement`, 23: the proposal "same class as X", the answer
   "a kind of X" (the same class, as parent). The writer put `different` on the
   pair; the answer says `narrower`.
2. `deepseek-v4-flash_top_15`, 117: the proposal "same class as X" stood in the
   is_a cell as `same_class` (rule 89 migration of the old placement trail).
   It is a pair judgement: moved to the pair, at its own time.
3. `deepseek-v4-flash_single`, 32: the yes/no statement "means exactly the same
   thing as X" answered `no` on the pair. The old question's `no` covered false,
   partly true, part-of and too vague; the nearest pair answer is `different`,
   and the note says what was asked.

The author has the last word on every cell of 2 and 3, and the placement
reading's `is_a yes` on X already carries 1, so no view the core is built from
may change; the script compares them before and after and writes nothing if
one does. Raw answers stay in `data/llm_runs/` and `data/review/`.
"""
from __future__ import annotations

import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

PLACEMENT = "claude-opus-5-5_placement"
TOP15 = "deepseek-v4-flash_top_15"
SINGLE = "deepseek-v4-flash_single"
NOTE = "mapped 2026-10-30"


def views(gt):
    """Everything the core and its checks read from the term dict."""
    from wound_ontology.mappers.judgements import RELATION_READER
    gt._dirty()
    per_term = {t: (gt.concept(t), gt.gate_verdict(t)[0]) for t in gt.records}
    cells = {(t, k): (gt.peek(t, k), gt.is_refused(t, k))
             for t, r in gt.records.items() for q in ("pairs", "is_a") for k in (r.get(q) or {})}
    return {"placements": sorted(gt.placements()), "term_links": gt.term_links(),
            "categories": gt.categories(), "relations": sorted(map(str, gt.read_relations(RELATION_READER))),
            "terms": per_term, "cells": cells}


def pair_key(rec: dict, key: str, iri: str | None) -> str:
    """The pair key that already names this class (the same IRI), else `key`."""
    for k, js in (rec.get("pairs") or {}).items():
        if iri and any(j.get("iri") == iri for j in js):
            return k
    return key


def translate(gt) -> Counter:
    from wound_ontology.mappers.judgements import ordered
    done = Counter()
    for t, rec in gt.records.items():
        # 1. the placement reading: "same as X" answered "a kind of X"
        for k, js in (rec.get("pairs") or {}).items():
            for j in js:
                if j["by"] == PLACEMENT and j["verdict"] == "different" and any(
                        i["by"] == PLACEMENT and i["verdict"] == "yes" and i.get("iri") == j.get("iri")
                        and i["when"] == j["when"] for ijs in (rec.get("is_a") or {}).values() for i in ijs):
                    j["verdict"] = "narrower"
                    j["why"] += f" [{NOTE}: the answer chose a kind of this class, so the pair is narrower; first written as different]"
                    done["placement reading: different -> narrower"] += 1
                # 3. the old yes/no statement on a pair
                elif j["by"] == SINGLE and j["verdict"] == "no":
                    j["verdict"] = "different"
                    j["why"] += (f" [{NOTE}: answered no to 'means exactly the same thing'; that no covered false, "
                                 f"partly true, part-of and too vague; the nearest pair answer is different]")
                    done["yes/no statement: no -> different"] += 1
        # 2. the model's proposal "same class" in the is_a cell
        for k, js in list((rec.get("is_a") or {}).items()):
            moved = [j for j in js if j["by"] == TOP15 and j["verdict"] == "same_class"]
            if not moved:
                continue
            js[:] = [j for j in js if j not in moved]
            for j in moved:
                pk = pair_key(rec, k, j.get("iri"))
                j["why"] += f" [{NOTE}: a pair judgement, moved from the is_a cell of {k!r}]"
                lst = rec.setdefault("pairs", {}).setdefault(pk, [])
                lst[:] = gt._capped(ordered(lst + [j]))
                done["proposal same_class: is_a cell -> pair"] += 1
            if not js:
                del rec["is_a"][k]
    return done


def main(argv) -> int:
    from wound_ontology.orchestrator import Orchestrator
    gt = Orchestrator().term_mapper._term_mapping
    before = views(gt)
    done = translate(gt)
    after = views(gt)
    changed = [n for n in before if before[n] != after[n]]
    print(f"[map-verdicts] translated: {dict(done)}")
    if changed:
        for n in changed:
            if isinstance(before[n], dict):
                diff = [k for k in set(before[n]) | set(after[n]) if before[n].get(k) != after[n].get(k)]
                print(f"[map-verdicts] *** {n}: {len(diff)} differ, e.g. "
                      f"{[(k, before[n].get(k), after[n].get(k)) for k in diff[:3]]} ***")
            else:
                print(f"[map-verdicts] *** {n} differ ***")
        print("[map-verdicts] *** a view the core is built from changed; nothing written ***")
        return 1
    print("[map-verdicts] every view the core is built from is unchanged")
    if "--write" not in argv:
        print("[map-verdicts] dry run; --write saves")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_mapped_verdicts_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[map-verdicts] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt._dirty()
    gt.save()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
