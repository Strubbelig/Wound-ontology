#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Put back into one cluster what the curator called `same_class` (rule 85).

    python -u scripts/rejoin_confirmed_synonyms.py            # dry run
    python -u scripts/rejoin_confirmed_synonyms.py --write

Curator, 2026-10-25 ("ja, so machen"): the name of a cluster is `to`, and that
a person chose it is their `same_class` on the pair. On that day 237 pairs the
curator had called `same_class` sat in two clusters -- withdrawn later by pass 1
dissent (111), by a prune that did not follow a respelling (73), by spelling
and category sweeps -- so the ontology would have carried `Klebsiella` and
`Klebsiella spp.` as two classes.

Clusters joined by such pairs are merged. The name: an ontology label first,
then a name a person chose, then the corpus count (`canonical_rank`). Held back
and listed for the curator, never guessed:

* two ontology labels in one merge (rule 36: a label is never mapped away);
* two decided categories that differ;
* a pair the curator ALSO keeps apart somewhere in the same merge;
* a sense split (`vitamin` / `vitamin (role)`).

Prints, per merge, the scope before and after: scope is pooled over a cluster,
so a merge can move a term in or out. Nothing is written without --write; then
a backup first, one save, a read-back, and `split_synonyms()` must hold only
the held-back pairs.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
from wound_ontology.mappers.term_mapping_and_gate import split_of  # noqa: E402


def chosen_names(live: Path, gt) -> set[str]:
    """The names a person chose, from the name sections the file still holds on
    disk (rule 85 folds them into pair verdicts on load, and a pair verdict
    only says WHICH name where `to` already points at it)."""
    raw = json.loads(live.read_text())
    return {gt.resolve(t) for t, r in raw.items() if isinstance(r, dict) and r.get("name")}


def plan(gt, anchors: set[str], freq: dict[str, int], chosen: set[str] = frozenset()) -> dict:
    from wound_ontology.mappers.term_mapper import canonical_rank
    split = gt.split_synonyms()
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in split:
        parent[find(a)] = find(b)
    # which curator verdicts join each merge (for its basis: read or bulk)
    edges = defaultdict(list)
    for t, r in gt.records.items():
        if "spelling" in r:
            continue
        for c, j in (r.get("pairs") or {}).items():
            if (j.get("curator") or {}).get("verdict") == "same_class":
                a, b = gt._head(t), gt._head(gt.resolve(c))
                if a != b and a in parent:
                    edges[find(a)].append((t, c))
    comps = defaultdict(set)
    for a, b in split:
        comps[find(a)] |= {a, b}

    # a name a person chose explicitly outranks one only derived from a kept
    # mapping (which includes the bulk approval of 2026-09-25)
    named, heads = set(chosen), gt.heads() | gt.named()
    decided = gt.categories()
    merges, held = [], []
    for comp in comps.values():
        members = sorted(comp)
        labels = [m for m in members if m.lower() in anchors]
        cats = {(decided.get(m) or {}).get("verdict") for m in members} - {None}
        apart = [(x, y) for x in members for y in members
                 if x < y and (gt.is_refused(x, y) or gt.is_refused(y, x))]
        senses = [m for m in members if split_of(gt.records.get(m) or {})
                  or m.endswith(" (role)")]
        why = []
        if len(labels) > 1:
            why.append(f"two ontology labels: {labels}")
        if len(cats) > 1:
            why.append(f"two decided categories: {sorted(cats)}")
        if apart:
            why.append(f"the curator also keeps apart: {apart}")
        if senses:
            why.append(f"a sense split: {senses}")
        if why:
            held.append({"members": members, "why": why})
            continue
        name = max(members, key=lambda t: canonical_rank(t, {m for m in members if m.lower() in anchors},
                                                         freq, named, heads))
        bulk_only = all(str(((gt.records.get(t) or {}).get("pairs", {}).get(c, {}).get("curator") or {})
                            .get("reason", "")).startswith("accepted in bulk")
                        for t, c in edges.get(find(members[0]), []))
        merges.append({"name": name, "joined": [m for m in members if m != name],
                       "basis": "bulk approval 2026-09-25 only" if bulk_only else "read"})
    return {"merges": merges, "held": held, "split_pairs": len(split)}


def apply(gt, p: dict) -> list[dict]:
    """Merge in memory; return the scope of every member before and after."""
    before = {m: gt.effective_gate_verdict(m)
              for mg in p["merges"] for m in [mg["name"], *mg["joined"]]}
    for mg in p["merges"]:
        name = mg["name"]
        for h in mg["joined"]:
            for r in gt.records.values():
                if r.get("to") == h and "spelling" not in r:
                    r["to"] = name
            rec = gt.record(h)
            rec.update({"to": name, "method": "curator", "confidence": 1.0})
            rec.pop("retired", None)
    gt._dirty(); gt._gate_idx = None
    rows = []
    for mg in p["merges"]:
        after = gt.effective_gate_verdict(mg["name"])
        for m in [mg["name"], *mg["joined"]]:
            if before[m][0] != after[0]:
                rows.append({"term": m, "name": mg["name"], "before": before[m], "after": after})
    return rows


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    anchors = {a.lower() for a in o.ontology_labels()}
    freq = Counter()
    for _, ents in o.store.view(mapped=False):
        for name in ents:
            freq[name] += 1
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    p = plan(gt, anchors, freq, chosen_names(live, gt))
    print(f"[rejoin] {p['split_pairs']} confirmed pair(s) in two clusters; "
          f"{len(p['merges'])} merge(s), {sum(len(m['joined']) for m in p['merges'])} name(s) "
          f"joined under another; {len(p['held'])} held for the curator")
    for h in p["held"]:
        print(f"    HELD {h['members']}: {'; '.join(h['why'])}")

    if "--write" in argv:
        backup = ROOT / "data" / "backup" / f"term_mapping_before_rejoin_{datetime.now():%Y-%m-%d_%H-%M}.json"
        shutil.copy2(live, backup)
        print(f"[rejoin] backed up {live.name} -> {backup.relative_to(ROOT)}")
    moved = apply(gt, p)
    print(f"[rejoin] scope changes by the merge: {len(moved)} term(s)")
    for r in moved:
        print(f"    {r['term']!r} (under {r['name']!r}): {r['before'][0] or '-'} ({r['before'][1] or '-'}) "
              f"-> {r['after'][0] or '-'} ({r['after'][1] or '-'})")
    out = ROOT / "data" / "review" / f"rejoin_confirmed_synonyms_{date.today()}.json"
    out.write_text(json.dumps({"merges": p["merges"], "held": p["held"], "scope_changes": moved},
                              ensure_ascii=False, indent=1))
    print(f"[rejoin] plan -> {out.relative_to(ROOT)}")
    if "--write" not in argv:
        print("[rejoin] dry run; --write to apply")
        return 0
    gt.save()
    g2 = Orchestrator().term_mapper._term_mapping
    held_pairs = {tuple(sorted((a, b))) for h in p["held"] for a in h["members"] for b in h["members"] if a < b}
    left = [x for x in g2.split_synonyms() if x not in held_pairs]
    print(f"[rejoin] read back: split pairs left outside the held ones: {left[:10] or 'none'}; "
          f"locked mappings: {g2.locked_mappings() or 'none'}")
    return 1 if left or g2.locked_mappings() else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
