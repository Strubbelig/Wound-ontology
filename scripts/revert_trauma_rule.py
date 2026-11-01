"""Undo what rule 49's `trauma -> injury` wrote. One-time, 2026-09-28.

    python scripts/revert_trauma_rule.py [--write]

The curator withdrew the rule ("Trauma into injury is wrong"). Removing it from
`utils.normalise` stops new renames but does not repair the old ones: pass 0
normalises the CURRENT spelling, and `head injury` holds nothing the rule
touches any more (the same shape as the `diabetic mellitus` repair, rule 53).

Every string the abstracts wrote with `trauma` in it and that now resolves to
a name with `injury` in it is given its own name back, `normalise(string)`
under the rules as they now stand:

* a name built ONLY from trauma strings (`psychological injury`, from
  `psychological trauma`) is renamed, so its decisions -- scope, mappings --
  move with it (`apply_renames`, which leaves the old spelling as an alias);
* a name that ALSO holds genuine injury strings (`head injury` from `head
  trauma` and `head injury`) keeps them; only the trauma strings are pointed
  at their own name, which starts with no decisions of its own.
"""
from __future__ import annotations

import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

TRAUMA = re.compile(r"\btraumas?\b", re.IGNORECASE)
INJURY = re.compile(r"\binjur(?:y|ies)\b", re.IGNORECASE)
BY = "revert 2026-09-28: rule 49's trauma -> injury withdrawn by the curator"


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import SPELLING, TermMappingAndGate
    from wound_ontology.utils.normalise import normalise

    write = "--write" in argv
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    raw: Counter = Counter()
    for rec in p.store.dict.values():
        for name, attrs in rec.get("entities", {}).items():
            raw[name] += 1
            for triple in attrs:
                if ":" in triple and not triple.startswith("is_a"):
                    raw[triple.split(":", 1)[1].strip()] += 1

    groups: dict[str, list[list[str]]] = defaultdict(lambda: [[], []])
    for s in raw:
        t = gt.resolve(s)
        if not INJURY.search(t):
            continue
        groups[t][0 if (TRAUMA.search(s) and not INJURY.search(s)) else 1].append(s)
    pure = {t: g[0] for t, g in groups.items() if g[0] and not g[1]}
    mixed = {t: g[0] for t, g in groups.items() if g[0] and g[1]}

    def own_name(strings: list[str]) -> str:
        return normalise(max(strings, key=lambda s: (raw[s], s))).name

    renames = {t: own_name(ss) for t, ss in pure.items()}
    renames = {t: n for t, n in renames.items() if n != t}
    repoint = {s: normalise(s).name for ss in mixed.values() for s in ss}
    print(f"[trauma] {len(pure)} name(s) built only from trauma strings -> renamed; "
          f"{len(mixed)} mixed with genuine injury strings -> {len(repoint)} trauma "
          f"string(s) re-pointed")
    for t, n in list(renames.items())[:6]:
        print(f"[trauma]   rename {t!r} -> {n!r}")
    for s, n in list(repoint.items())[:6]:
        print(f"[trauma]   {s!r} now {n!r} (was {gt.resolve(s)!r})")
    if not write:
        print("[trauma] dry run -- nothing written. Pass --write.")
        return 0

    latest = sorted((ROOT / "data" / "cache").glob("term_mapping_*.json"))[-1]
    shutil.copy2(latest, ROOT / "data" / "backup" / f"term_mapping_before_trauma_revert_{date.today()}.json")
    # A destination that is itself an alias of ANOTHER name (`Acute hand
    # trauma` -> `hand injury` while `acute hand injury` -> `Acute hand trauma`)
    # would be renamed away and onto at once: it becomes its own name first.
    for t, n in renames.items():
        rec = gt.records.get(n)
        if rec and SPELLING in rec:
            gt.records[n] = {"to": None, "pairs": {}, "spelling_reversed": [rec[SPELLING]]}
    gt._dirty()
    report = p.store.apply_renames(renames, by=BY)
    print(f"[trauma] renamed: {report['keys renamed']} key(s), "
          f"{report.get('spellings reversed', 0)} spelling(s) reversed, "
          f"{report['records merged']} merged")
    for s, n in repoint.items():
        if s == n:
            # The string is its own name again: drop the alias, keep it as history.
            rec = gt.records.get(s)
            if rec and SPELLING in rec:
                gt.records[s] = {"to": None, "pairs": {},
                                 "spelling_reversed": [rec[SPELLING]]}
            continue
        target = gt.records.get(n)
        if target and SPELLING in target:
            gt.records[n] = {"to": None, "pairs": {}, "spelling_reversed": [target[SPELLING]]}
        rec = gt.records.get(s)
        if rec is not None and SPELLING not in rec:
            continue                         # a decision record; leave it be
        prior = (rec or {}).get(SPELLING)
        entry = {"to": n, "by": BY}
        if prior:
            entry["history"] = prior.pop("history", []) + [prior]
        gt.records[s] = {SPELLING: entry}
    gt._dirty()
    gt.save()

    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    left = sorted(s for s in raw if TRAUMA.search(s) and not INJURY.search(s)
                  and INJURY.search(check.resolve(s)))
    if left:
        raise RuntimeError(f"[trauma] {len(left)} trauma string(s) still resolve to an "
                           f"injury name: {left[:8]}")
    print("[trauma] written and read back: no trauma string resolves to an injury name.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
