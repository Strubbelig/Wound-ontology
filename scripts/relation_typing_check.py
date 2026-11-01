"""Does a relation's value have the category its relation requires? Its answers go into the term dict.

    python -u scripts/relation_typing_check.py            # dry run: what it would write
    python -u scripts/relation_typing_check.py --write    # the answers into the term dict

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

and the relation is answered like every relation in the term dict (rule 89),
as a judgement of AGENT on `<predicate>: <value>` of the subject:

  both ends ok        -> yes        (no objection; it does not make an axiom,
                                     only the instance reading or the author does)
  an end violates     -> no         (the store view leaves the relation out)
  otherwise           -> undecided  (the check could not tell; never counts)

The first run (2026-10-02) wrote its rows into
`data/review/relation_typing_check_2026-10-02.json`, which the instance reading
took its rows from. Asked whether to write that state into the term dict or to
run the check again on the categories decided since, the curator (2026-10-30):
"neu laufen lassen". The file is kept, as that run's record, in
`data/backup/relation_decision_files_2026-10-30/`.

The check hears its own earlier answers anew (`ConceptStore.reopen`): a
relation it refused comes back into the view it reads. It writes only where
its answer or the categories behind it differ from its own last judgement on
the relation, so a run that finds nothing new writes nothing.
"""
from __future__ import annotations

import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

AGENT = "relation-typing-check"
VERDICT = {"ok": "yes", "violates": "no", "undetermined": "undecided"}
EVIDENCE_CUT = 2                 # abstracts; the instance reading reads relations at or above it

BFO = {  # node -> parent
    "Entity": None, "Continuant": "Entity", "Occurrent": "Entity",
    "Independent Continuant": "Continuant", "Specifically Dependent Continuant": "Continuant",
    "Generically Dependent Continuant": "Continuant",
    "Material Entity": "Independent Continuant", "Immaterial Entity": "Independent Continuant",
    "Site": "Immaterial Entity", "Spatial Region": "Immaterial Entity",
    "Material Disease Entity": "Material Entity", "Disorder": "Material Entity",
    "Quality": "Specifically Dependent Continuant", "Realizable Entity": "Specifically Dependent Continuant",
    "Disposition": "Realizable Entity", "Function": "Disposition", "Role": "Realizable Entity",
    # MILD states tendency a subclass of disposition (MILD_120005 rdfs:subClassOf
    # BFO_0000016); asked whether MILD or this check should give way, the curator
    # (2026-10-30): "MILD bleibt, Prüfung folgt". Under realizable entity, as
    # here until then, every tendency had two disjoint ancestors and 211
    # relations with a tendency at one end could not be decided.
    "Tendency": "Disposition",
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


def same_tree(H) -> None:
    """The fixed tree must say what the hierarchy's curated top (BFO and MILD) says, or the check stops.

    It is fixed because the hierarchy's top was patchy; it must not differ
    from it. It did, unseen, for tendency: MILD put it under disposition, the
    tree under realizable entity, and the check called every tendency
    conflicting (2026-10-30)."""
    differ = []
    for n, parent in BFO.items():
        if parent is None:
            continue
        have = {a for a in H.ancestors_of(n) if a in BFO}
        if have != set(chain(n)) - {n}:
            differ.append(f"{n}: tree {sorted(set(chain(n)) - {n})}, hierarchy {sorted(have)}")
    if differ:
        raise RuntimeError("the typing check's BFO tree differs from the class hierarchy's: " + "; ".join(differ))


def check_view(p) -> list[dict]:
    """One row per relation of the store view: both ends checked, the verdict, the abstracts."""
    from wound_ontology.utils.string_utils import smart_title
    H = p.class_hier
    same_tree(H)
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

    rows = []
    for (s, pr, tg), keys in support.items():
        rule = RULES.get(pr)
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
        rows.append({"subject": s, "predicate": pr, "value": tg, "abstracts": len(keys),
                     "subject_check": list(v_s), "value_check": list(v_o), "verdict": verdict})
    return rows


def why(r: dict) -> tuple[str, str]:
    """(the check, the check with its evidence): a rerun compares the first."""
    rule = RULES.get(r["predicate"])
    need = ("both ends of one kind" if rule == "SAME" else f"needs {rule[0].lower()} -> {rule[1].lower()}"
            if rule else "no domain/range known")
    (sv, sc), (vv, vc) = r["subject_check"], r["value_check"]
    core = f"{r['predicate']} {need}; subject {sv} ({sc.lower()}); value {vv} ({vc.lower()})"
    return core, f"{core}; in {r['abstracts']} abstract(s)"


def main(argv) -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.mappers.judgements import RELATION_READER, current
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    gt = p.term_mapper._term_mapping
    if p.store.terms is not gt:
        raise RuntimeError("the store reads another term dict than the term mapper")
    p.class_hier                                    # built first: building it resets `reopen`
    p.store.reopen = (AGENT, "relations")           # its own refusals are heard again
    rows = check_view(p)
    p.store.reopen = None

    def cell(r):
        return ((gt.records.get(r["subject"]) or {}).get("relations") or {}).get(f"{r['predicate']}: {r['value']}") or []

    def axioms():
        return {(s, k, t) for s, k, t, ax, _ in gt.read_relations(RELATION_READER) if ax}

    axioms_before = axioms()
    by_pred, tally, changed, no_record = defaultdict(Counter), defaultdict(Counter), [], []
    for r in rows:
        n = "(>=2)" if r["abstracts"] >= EVIDENCE_CUT else "(1)"
        by_pred[r["predicate"]][r["verdict"]] += 1
        by_pred[r["predicate"]][f"{r['verdict']} {n}"] += 1
        js = cell(r)
        core, full = why(r)
        mine = [j for j in js if j["by"] == AGENT]
        v = VERDICT[r["verdict"]]
        if mine and mine[-1]["verdict"] == v and mine[-1]["why"].rsplit("; in ", 1)[0] == core:
            tally[f"unchanged {n}"][v] += 1
            continue
        if r["subject"] not in gt.records:
            no_record.append(r)
        before = current(js)
        gt._put(r["subject"], "relations", gt._j(v, AGENT, full), f"{r['predicate']}: {r['value']}")
        changed.append((r, before, current(cell(r))))
        tally[f"written {n}"][v] += 1
    axioms_after = axioms()

    refused = [(r, b) for r, b, a in changed if (a or {}).get("verdict") == "no" and (b or {}).get("verdict") != "no"]
    # read under any spelling of the value counts (`relation_cells`, 2026-10-30)
    to_read = [r for r in rows if r["verdict"] == "ok" and r["abstracts"] >= EVIDENCE_CUT
               and not any(j["by"] == RELATION_READER
                           for o, k in gt.relation_cells([r["subject"]], r["predicate"], r["value"])
                           for j in ((gt.records.get(o) or {}).get("relations") or {}).get(k) or [])]
    total = Counter(r["verdict"] for r in rows)
    strong = Counter(r["verdict"] for r in rows if r["abstracts"] >= EVIDENCE_CUT)
    print(f"[typing] {len(rows):,} relations in the store view; {dict(total)}")
    print(f"[typing] in >= {EVIDENCE_CUT} abstracts: {sum(strong.values()):,}; {dict(strong)}")
    print(f"[typing] {'predicate':38} {'ok':>6} {'viol.':>6} {'undet.':>6}   at >=2 abstracts: ok / viol. / undet.")
    for pr, c in sorted(by_pred.items(), key=lambda kv: -sum(kv[1][x] for x in ("ok", "violates", "undetermined"))):
        print(f"[typing] {pr:38} {c['ok']:6} {c['violates']:6} {c['undetermined']:6}   "
              f"{c['ok (>=2)']:5} / {c['violates (>=2)']:5} / {c['undetermined (>=2)']:5}")
    for k in sorted(tally):
        print(f"[typing] {k}: {dict(tally[k])}")
    print(f"[typing] newly left out of the store view: {len(refused):,} relation(s), "
          f"{sum(r['abstracts'] >= EVIDENCE_CUT for r, _ in refused)} of them in >= {EVIDENCE_CUT} abstracts")
    for r, b in sorted(refused, key=lambda x: -x[0]["abstracts"])[:12]:
        print(f"[typing]     {r['subject']} | {r['predicate']} | {r['value']} ({r['abstracts']}): {why(r)[0]}"
              + (f" [counted before: {b['by']} {b['verdict']}]" if b else ""))
    gone, new = axioms_before - axioms_after, axioms_after - axioms_before
    print(f"[typing] axioms (instance reading or author): {len(axioms_before)} -> {len(axioms_after)}")
    if gone or new:
        print(f"[typing] *** axioms changed by the check: gone {sorted(gone)[:10]}, new {sorted(new)[:10]} ***")
    print(f"[typing] passing, in >= {EVIDENCE_CUT} abstracts, never read by the instance reading: {len(to_read)} "
          f"(scripts/claude_read_universality.py --unread)")
    if no_record:
        print(f"[typing] {len(no_record)} relation(s) on a subject without a record (it is created): "
              + "; ".join(f"{r['subject']} {r['predicate']} {r['value']}" for r in no_record))
    if "--write" not in argv:
        print("[typing] dry run; --write saves")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_typing_check_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[typing] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()
    print(f"[typing] written: {len(changed):,} judgement(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
