"""Does a relation's value have the category its relation requires? Read-only.

    python -u scripts/relation_typing_check.py

Curator, 2026-10-02: "check if the typing of the term and the typing of the
attribute which happen to be the same word are equal. Has quality
contamination, which might be a material entity, makes no sense
ontologically ... I'd rather take little nodes and edges and add them to the
onto than bad ones."

Every relation in the store view (subject, predicate, value; is_a aside) is
checked on both ends: the term's OWN category (its most specific BFO ancestor
in the class hierarchy, read against a fixed BFO tree, because the hierarchy's
top is patchy -- Disposition and Function have no parent there and Role sits
under Quality) against what the predicate requires (RO/BFO domain and range).
Each end is

  ok            the term's category is the required one or below it
  violates      the term's category is disjoint from the required one
  undetermined  the term's category is above the required one (e.g. only
                `Continuant` where a quality is needed), unknown, or
                conflicting (two disjoint BFO ancestors)

Writes `data/review/relation_typing_check_2026-10-02.json`, read back.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

OUT = ROOT / "data" / "review" / "relation_typing_check_2026-10-02.json"

BFO = {  # node -> parent
    "Entity": None, "Continuant": "Entity", "Occurrent": "Entity",
    "Independent Continuant": "Continuant", "Specifically Dependent Continuant": "Continuant",
    "Generically Dependent Continuant": "Continuant",
    "Material Entity": "Independent Continuant", "Immaterial Entity": "Independent Continuant",
    "Site": "Immaterial Entity", "Spatial Region": "Immaterial Entity",
    "Material Disease Entity": "Material Entity", "Disorder": "Material Entity",
    "Quality": "Specifically Dependent Continuant", "Realizable Entity": "Specifically Dependent Continuant",
    "Disposition": "Realizable Entity", "Function": "Disposition", "Role": "Realizable Entity",
    "Tendency": "Realizable Entity",
    "Information Entity": "Generically Dependent Continuant",
    "Information Content Entity": "Generically Dependent Continuant",
    "Process": "Occurrent", "Process Boundary": "Occurrent", "Temporal Region": "Occurrent",
}

# predicate -> (domain, range); "SAME" = both ends of one kind (part-hood)
RULES = {
    "has_quality": ("Independent Continuant", "Quality"),
    "has_disposition": ("Independent Continuant", "Disposition"),
    "has_tendency": ("Independent Continuant", "Tendency"),     # MILD_120101, rule 68
    "has_function": ("Independent Continuant", "Function"),
    "has_role": ("Independent Continuant", "Role"),
    "inheres_in": ("Specifically Dependent Continuant", "Independent Continuant"),
    "has_a_material_basis": ("Disposition", "Material Entity"),
    "participates_in": ("Continuant", "Occurrent"),
    "has_participant": ("Occurrent", "Continuant"),
    "has_input": ("Occurrent", "Continuant"), "has_output": ("Occurrent", "Continuant"),
    "has_specified_input": ("Occurrent", "Continuant"), "has_specified_output": ("Occurrent", "Continuant"),
    "output_of": ("Continuant", "Occurrent"), "is_specified_output_of": ("Continuant", "Occurrent"),
    "is_specified_input_of": ("Continuant", "Occurrent"),
    "realizes": ("Occurrent", "Realizable Entity"), "has_realization": ("Realizable Entity", "Occurrent"),
    "is_about": ("Generically Dependent Continuant", "Entity"),
    "has_as_process_boundary_at_start": ("Occurrent", "Process Boundary"),
    "has_as_process_boundary_at_end": ("Occurrent", "Process Boundary"),
    "immediately_causally_downstream_of": ("Occurrent", "Occurrent"),
    "part_of": "SAME", "has_part": "SAME",
}
KINDS = ("Independent Continuant", "Specifically Dependent Continuant",
         "Generically Dependent Continuant", "Occurrent")


def chain(n):
    out = []
    while n:
        out.append(n); n = BFO[n]
    return out


def depth(n):
    return len(chain(n))


def main(argv) -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import smart_title
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    H = p.class_hier
    memo = {}

    def category(term):
        """(most specific BFO node or None, 'conflicting' flag)."""
        t = smart_title(term)
        if t in memo:
            return memo[t]
        nodes = [n for n in ({smart_title(a) for a in H.ancestors_of(t)} | {t}) if n in BFO]
        if not nodes:
            memo[t] = (None, False); return memo[t]
        deepest = max(nodes, key=depth)
        conflict = any(n not in chain(deepest) and deepest not in chain(n) for n in nodes)
        memo[t] = (deepest, conflict)
        return memo[t]

    def judge(term, required):
        cat, conflict = category(term)
        if conflict:
            return "undetermined", "conflicting categories"
        if cat is None:
            return "undetermined", "no category"
        if required in chain(cat):
            return "ok", cat
        if cat in chain(required):
            return "undetermined", f"only {cat}"
        return "violates", cat

    def kind(term):
        cat, conflict = category(term)
        if conflict or cat is None:
            return None
        for k in KINDS:
            if k in chain(cat):
                return k
        return None

    support = defaultdict(set)
    for key, ents in p.store.view():
        for s, attrs in ents.items():
            for t, v in attrs.items():
                if v != 1.0 or ":" not in t:
                    continue
                pr, tg = (x.strip() for x in t.split(":", 1))
                if pr != "is_a" and tg:
                    support[(s, pr, tg)].add(key)

    rows, tally = [], defaultdict(Counter)
    for (s, pr, tg), keys in support.items():
        rule = RULES.get(pr)
        n = len(keys)
        if rule is None:
            v_s = v_o = ("undetermined", "predicate has no domain/range here")
        elif rule == "SAME":
            ks, ko = kind(s), kind(tg)
            if ks is None or ko is None:
                v_s = v_o = ("undetermined", "no single kind")
            elif ks == ko:
                v_s = v_o = ("ok", ks)
            else:
                v_s, v_o = ("violates", ks), ("violates", ko)
        else:
            v_s, v_o = judge(s, rule[0]), judge(tg, rule[1])
        verdict = ("violates" if "violates" in (v_s[0], v_o[0])
                   else "ok" if v_s[0] == v_o[0] == "ok" else "undetermined")
        rows.append({"subject": s, "predicate": pr, "value": tg, "abstracts": n,
                     "subject_check": list(v_s), "value_check": list(v_o), "verdict": verdict})
        tally[pr][verdict] += 1
        tally[pr][verdict + (" (>=2)" if n >= 2 else " (1)")] += 1

    total = Counter(r["verdict"] for r in rows)
    strong = Counter(r["verdict"] for r in rows if r["abstracts"] >= 2)
    result = {"triples": len(rows), "verdicts": dict(total), "verdicts_at_2_abstracts": dict(strong),
              "by_predicate": {k: dict(v) for k, v in tally.items()},
              "rows": sorted(rows, key=lambda r: (r["verdict"], -r["abstracts"]))}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(OUT.read_text(encoding="utf-8"))
    assert back["triples"] == len(rows)
    print(f"[typing] {len(rows):,} relations; {dict(total)}")
    print(f"[typing] with >= 2 abstracts: {sum(strong.values()):,}; {dict(strong)}")
    print(f"[typing] {'predicate':38} {'ok':>6} {'viol.':>6} {'undet.':>6}   at >=2 abstracts: ok / viol. / undet.")
    for pr, c in sorted(tally.items(), key=lambda kv: -sum(kv[1][x] for x in ('ok', 'violates', 'undetermined'))):
        print(f"[typing] {pr:38} {c['ok']:6} {c['violates']:6} {c['undetermined']:6}   "
              f"{c['ok (>=2)']:5} / {c['violates (>=2)']:5} / {c['undetermined (>=2)']:5}")
    print(f"[typing] written and read back: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
