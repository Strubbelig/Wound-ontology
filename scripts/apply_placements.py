"""Write the checked superclasses and synonyms into the term dict (rule 59).

    python -u scripts/apply_placements.py [--write]

Curator, 2026-10-02: "If i go on looking through the 10k terms, this will take
ages. can you go on with what we have now". So the review page's decisions as
they stand are applied, and whatever the page left undecided follows its own
stated default:

* superclass (`placed` in data/review/placement_merged_2026-10-01.json) ->
  the pair gets `placement: {verdict: "narrower"}` unless the curator refused
  it. The page said so from the start: "everything here counts as accepted
  unless you refuse a term or a whole group". It becomes the hierarchy's
  `placed` source (`TermMappingAndGate.placements()`).
* synonym -> mapped onto the class (`to`, a curator `same_class`) only when
  the curator accepted it. An undecided synonym is NOT mapped (the page:
  "nothing here is accepted until you say so"); its pair keeps the placement
  as a `same_class` judgement for later, and the run lists it.
* refused -> the pair is refused (`refuse`), as the page's refusal says.
* excluded -> the term goes out of scope (curator gate verdict), whatever its
  class.

Reversible: every write is a judgement on a pair or a gate verdict, tagged
`by: BY`; the backup is taken first. Reads back after writing.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

MERGED = ROOT / "data" / "review" / "placement_merged_2026-10-01.json"
DECISIONS = ROOT / "data" / "review" / "superclass_review_decisions_2026-10-02_final"
BY = "placement review (curator page, 2026-10-02)"


def iid(term):
    import hashlib
    return "i" + hashlib.sha1(term.encode("utf-8")).hexdigest()[:10]


def gid(kind, iri):
    import hashlib
    return "g" + hashlib.sha1(f"{kind}|{iri}".encode("utf-8")).hexdigest()[:12]


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    rows = json.loads(MERGED.read_text(encoding="utf-8"))["rows"]
    dec = {}
    for coll in ("synonym", "subclass"):
        for f in (DECISIONS / coll).glob("*.json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            dec[f.stem] = d.get("data", d) if "data" in d and isinstance(d.get("data"), dict) else d

    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    when = datetime.now().isoformat(timespec="seconds")
    plan, why = [], Counter()
    for r in rows:
        if r["outcome"] not in ("placed", "synonym"):
            continue
        kind = "syn" if r["outcome"] == "synonym" else "sub"
        d = dec.get(gid(kind, r["parent iri"])) or {}
        v = ((d.get("items") or {}).get(iid(r["term"])) or {}).get("v") or d.get("all")
        term = gt.resolve(r["term"])
        if v == "exclude":
            plan.append(("exclude", term, r)); why["excluded by the curator"] += 1
        elif v == "refuse":
            plan.append(("refuse", term, r)); why[f"{kind}: refused by the curator"] += 1
        elif kind == "sub":
            plan.append(("narrower", term, r)); why["superclass kept" + (" (accepted)" if v == "accept" else " (page default)")] += 1
        elif v == "accept":
            plan.append(("same", term, r)); why["synonym accepted -> mapped"] += 1
        else:
            plan.append(("same_open", term, r)); why["synonym undecided -> recorded, not mapped"] += 1
    for k, n in sorted(why.items()):
        print(f"[apply] {n:6,}  {k}")
    blocked = [(a, t, r) for a, t, r in plan if a in ("narrower", "same") and gt.is_refused(t, r["parent"])]
    if blocked:
        print(f"[apply] {len(blocked)} pair(s) already refused in the term dict, skipped: "
              f"{[(t, r['parent']) for _, t, r in blocked[:5]]}")
    plan = [x for x in plan if x not in blocked]
    open_syn = [(t, r["parent"]) for a, t, r in plan if a == "same_open"]
    if open_syn:
        print(f"[apply] undecided synonyms (not mapped): {open_syn}")
    if "--write" not in argv:
        print("[apply] dry run; --write to apply")
        return 0

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_placements_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[apply] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    for action, term, r in plan:
        info = {"iri": r["parent iri"], "check": r.get("check"), "by": BY, "when": when}
        if action == "exclude":
            gt.gate(term, curator={"verdict": "out", "when": when, "by": BY,
                                   "reason": f"excluded on the review page (was under {r['parent']!r})"})
        elif action == "refuse":
            gt.refuse(term, r["parent"], reason="refused on the review page", by=BY)
        elif action == "narrower":
            gt.judge(term, r["parent"], curator={"verdict": "narrower", **info})
        elif action == "same":
            rec = gt.record(term)
            rec.update({"to": r["parent"], "confidence": 1.0, "method": "curator"})
            rec.pop("retired", None)
            gt.judge(term, r["parent"], curator={"verdict": "same_class", **info,
                                                 "reason": "synonym accepted on the review page"})
        else:
            # An undecided synonym. Until 2026-10-24 it was kept as a
            # `placement` proposal; that source is now the curator's, and the
            # curator did not accept this one, so nothing is written. (The
            # 2026-10-02 run left no such pair behind.)
            print(f"[apply] undecided synonym, not written: {term!r} = {r['parent']!r}")
    gt._dirty()
    gt.save()

    g2 = Orchestrator().term_mapper._term_mapping
    lost = []
    # one current name can carry two rows (`refractory Venous leg ulcer` placed
    # under Ulcus cruris venosum, its alias `refractory venous leg ulcer`
    # accepted as its synonym): the accepted synonym wins, the pair says so
    mapped_now = {gt.resolve(t) for a, t, r in plan if a == "same"}
    for action, term, r in plan:
        if action == "narrower" and gt.resolve(term) in mapped_now:
            continue
        j = g2.peek(g2.resolve(term), r["parent"])
        if action == "narrower" and (j.get("curator") or {}).get("verdict") != "narrower":
            lost.append(term)
        elif action == "same" and g2.data.get(g2.resolve(term)) != r["parent"]:
            lost.append(term)
        elif action == "refuse" and not j.get("refused"):
            lost.append(term)
        elif action == "exclude" and g2.peek_gate(g2.resolve(term)).get("curator", {}).get("verdict") != "out":
            lost.append(term)
    if lost:
        raise RuntimeError(f"[apply] {len(lost)} decision(s) did not land: {lost[:10]}")
    print(f"[apply] written and read back: {len(plan):,} decisions; "
          f"{len(g2.placements()):,} placement edge(s) now in the term dict")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
