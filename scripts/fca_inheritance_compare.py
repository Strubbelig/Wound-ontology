"""Which ancestor attributes should pass down in FCA? Measured, not guessed (rule 65).

    python -u scripts/fca_inheritance_compare.py [--root Wound]

Curator, 2026-10-02: "class level only inheritance and everything inheritance,
that I don't make a guess but a data driven choice". Builds the Wound-subtree
context and lattice once per mode -- inherit "all", "class_level", "universal"
(rule 88), "none" --
closed world, `min_support=2`, no naming (no model calls), and measures for
each:

* inherited cells, and how many of them the object itself states in at least
  one abstract (corroborated) -- the precision of inheritance;
* hierarchy edges whose order the context contradicts (the parent states an
  attribute the child does not have) -- what inheritance exists to prevent;
* concepts, and *new groupings*: concepts whose extent is not one existing
  class's subtree (with or without that class), does not contain the root,
  and has >= 2 maximal members (no member a subclass of another member) --
  the superclass candidates FCA exists to find;
* for the new groupings, the share of (member, intent attribute) cells the
  member states itself rather than inherits: a grouping resting on inherited
  cells is the hierarchy talking, not the abstracts.

Writes `data/review/fca_inheritance_comparison_<date>.json`, read back (the
2026-10-02 one is rule 65's, the 2026-10-27 one rule 88's).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

OUT = ROOT / "data" / "review" / f"fca_inheritance_comparison_{date.today()}.json"
PREDICATES = ["has_quality", "part_of", "has_participant", "has_disposition", "inheres_in"]
MIN_SUPPORT = 2
MODES = ("all", "class_level", "universal", "none")


def _opt(argv, flag, default):
    return argv[argv.index(flag) + 1] if flag in argv else default


def main(argv: list[str]) -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.store.concept_store import records_of
    from wound_ontology.utils.string_utils import smart_title

    root = _opt(argv, "--root", "Wound")
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    hier = p.class_hier

    # each object's own statements: support per (object, attribute)
    support: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for _, ents in records_of(p.store):
        for e, attrs in ents.items():
            for t, v in attrs.items():
                if v != 1.0 or ":" not in str(t):
                    continue
                pr, tg = t.split(":", 1)
                pr = pr.strip().lower()
                if pr in PREDICATES:
                    support[smart_title(e)][f"{pr}: {tg.strip()}".lower()] += 1

    result = {"root": root, "predicates": PREDICATES, "min_support": MIN_SUPPORT, "modes": {}}
    for mode in MODES:
        print(f"\n===== inherit={mode} =====", flush=True)
        p.run_fca(subtree_root=root, predicates=PREDICATES, min_support=MIN_SUPPORT,
                  inherit=mode, unknown="absent", name=False)
        df = p.context_matrix.df
        attrs = [a for a in p.context_matrix.attributes if not a.startswith("is_a:")]
        objs = list(df.index)
        own = {o: {a for a, n in support.get(smart_title(o), {}).items() if n >= MIN_SUPPORT} for o in objs}
        once = {o: {a for a, n in support.get(smart_title(o), {}).items() if n >= 1} for o in objs}
        inherited = corroborated = 0
        for o in objs:
            row = df.loc[o, attrs]
            for a in row.index[row == 1.0]:
                if a not in own[o]:
                    inherited += 1
                    corroborated += a in once[o]
        subtrees = set()
        oset = set(objs)
        below = {o: {smart_title(a) for a in hier.ancestors_of(o)} for o in objs}
        for c in hier.subtree_of(root):
            full = frozenset(smart_title(d) for d in hier.subtree_of(c)) & oset
            subtrees.add(full)
            subtrees.add(full - {smart_title(c)})
        # the order the lattice owes the hierarchy: an edge child < parent is
        # violated when the parent's measured attributes are not all the child's
        violations = 0
        edges = 0
        for o in objs:
            mine = set(df.columns[df.loc[o] == 1.0])
            for par in hier.parents_of(o):
                par = smart_title(par)
                if par in oset:
                    edges += 1
                    theirs = {a for a in df.columns[df.loc[par] == 1.0] if not a.startswith("is_a:")}
                    violations += not theirs <= mine
        lattice = p.lattice.lattice or []
        groupings = []
        for c in lattice:
            ext = frozenset(c.extent)
            measured = [a for a in c.intent if not a.startswith("is_a:")]
            maximal = [o for o in ext if not (below[o] & ext)]
            if (len(ext) < 2 or ext in subtrees or not measured
                    or smart_title(root) in ext or len(maximal) < 2):
                continue
            cells = [(o, a) for o in ext for a in measured]
            own_cells = sum(1 for o, a in cells if a in own[o])
            groupings.append({"extent": sorted(ext), "maximal": sorted(maximal), "intent": sorted(measured),
                              "is_a": sorted(a for a in c.intent if a.startswith("is_a:")),
                              "own_share": own_cells / len(cells),
                              "all_members_state_one": all(any(a in own[o] for a in measured) for o in ext)})
        backed = [g for g in groupings if g["all_members_state_one"]]
        m = {
            "objects": len(objs), "measured_attributes": len(attrs),
            "inherited_cells": inherited,
            "inherited_corroborated": corroborated,
            "hierarchy_edges": edges, "order_violations": violations,
            "concepts": len(lattice),
            "new_groupings": len(groupings),
            "new_groupings_every_member_states_one_intent_attribute": len(backed),
            "mean_own_share": (sum(g["own_share"] for g in groupings) / len(groupings)) if groupings else None,
            "class_level_tests": p.context_matrix.inheritance_tests if mode in ("class_level", "universal") else None,
            "groupings": sorted(groupings, key=lambda g: (-g["own_share"], -len(g["extent"]))),
        }
        result["modes"][mode] = m
        print(f"[compare] {mode}: {m['objects']} objects x {m['measured_attributes']} measured attributes; "
              f"{inherited:,} inherited cells ({corroborated:,} stated by the object itself once); "
              f"{violations}/{edges} hierarchy edges contradicted; "
              f"{m['concepts']} concepts; {m['new_groupings']} new groupings, "
              f"{len(backed)} with every member stating one intent attribute itself; "
              f"mean own share {m['mean_own_share'] if m['mean_own_share'] is None else round(m['mean_own_share'], 3)}",
              flush=True)

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(OUT.read_text(encoding="utf-8"))
    if set(back["modes"]) != set(MODES):
        raise RuntimeError(f"[compare] read-back lost modes: {set(back['modes'])}")
    print(f"\n[compare] written and read back: {OUT.relative_to(ROOT)}")
    for mode in MODES:
        m = back["modes"][mode]
        print(f"  {mode:12} inherited {m['inherited_cells']:6,}  corroborated {m['inherited_corroborated']:5,}  "
              f"order violations {m['order_violations']:4}/{m['hierarchy_edges']}  "
              f"concepts {m['concepts']:4}  new groupings {m['new_groupings']:4}  "
              f"member-backed {m['new_groupings_every_member_states_one_intent_attribute']:4}  "
              f"own share {m['mean_own_share']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
