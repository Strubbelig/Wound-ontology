"""Carry the curator's review-page decisions over to the rebuilt page. Sandbox only.

    python -u scripts/carry_review_decisions.py <old page html> <new page html> <out writes json>

The superclass/synonym review page (`superclass_review_page.py`) keeps one
decision document per class group: `all` (a whole-group accept or refuse) and
`items` (per term, keyed `"i" + sha1(term)[:10]`). After the page was used,
names were renamed (rule 61, rule 62) and placed again, so terms and groups
moved. A decision stays the curator's only for what the curator saw:

* the old page's own payload says which terms each group held when it was
  decided; an `all` is expanded into one decision per term it covered;
* each old term is followed to its current name (`resolve`, the aliases
  rule 51 keeps) and its old class through `one_class` (rule 63);
* where that current name sits in the rebuilt page under the same kind and
  class, the decision is written for it; anything new in a group stays
  undecided -- an `all` is never carried, so it cannot accept what it never
  covered.

Writes the documents to store (one per rebuilt group that receives a decision,
and an empty one for every old group id that would otherwise keep an `all`)
and prints what did not carry and why.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

DECISIONS = ROOT / "data" / "review" / "superclass_review_decisions_2026-10-02"


def payload(html: str) -> list[dict]:
    m = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))["groups"]


def iid(term: str) -> str:
    return "i" + hashlib.sha1(term.encode("utf-8")).hexdigest()[:10]


def main(argv: list[str]) -> int:
    from merge_placement_checks import label_index
    from wound_ontology.orchestrator import Orchestrator
    old = {g["id"]: g for g in payload(Path(argv[1]).read_text(encoding="utf-8"))}
    new = payload(Path(argv[2]).read_text(encoding="utf-8"))
    gt = Orchestrator().term_mapper._term_mapping
    _, same_as = label_index()

    where = {}                                   # (kind, current term) -> (new group, item id)
    for g in new:
        for it in g["items"]:
            where[(g["k"], it[1])] = (g, it[0])
    decided = {}
    for coll in ("synonym", "subclass"):
        for f in sorted((DECISIONS / coll).glob("*.json")):
            decided[f.stem] = (coll, json.loads(f.read_text(encoding="utf-8")))

    out = defaultdict(dict)                      # new group id -> {item id: {v, term}}
    why = Counter()
    lost = []
    for gid, (coll, d) in decided.items():
        g = old.get(gid)
        if g is None:
            why["decided group not on the old page"] += 1
            continue
        per = {it[0]: (d["all"], it[1]) for it in g["items"]} if d.get("all") else {}
        for k, v in (d.get("items") or {}).items():
            term = v.get("term") or next((it[1] for it in g["items"] if it[0] == k), None)
            per[k] = (v["v"], term)
        iri = same_as.get(g["iri"], g["iri"])
        for k, (verdict, term) in per.items():
            cur = gt.resolve(term) if term else None
            hit = where.get((g["k"], cur))
            if hit is None:
                why[f"{verdict}: term no longer in a {g['k']} group"] += 1
                lost.append((verdict, g["p"], term, cur))
                continue
            ng, nid = hit
            if same_as.get(ng["iri"], ng["iri"]) != iri:
                why[f"{verdict}: term now under another class"] += 1
                lost.append((verdict, g["p"], term, f"{cur} -> {ng['p']}"))
                continue
            out[ng["id"]][nid] = {"v": verdict, "term": cur}
            why[f"{verdict}: carried"] += 1

    when = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    byid = {g["id"]: g for g in new}
    writes = []
    for gid, items in out.items():
        g = byid[gid]
        writes.append({"collection": "synonym" if g["k"] == "syn" else "subclass", "doc_id": gid,
                       "data": {"kind": g["k"], "parent": g["p"], "iri": g["iri"], "all": None,
                                "items": items, "when": when}})
    for gid, (coll, d) in decided.items():         # an old `all` must not stay on a group id
        if gid not in out:
            g = byid.get(gid) or old.get(gid) or {}
            writes.append({"collection": coll, "doc_id": gid,
                           "data": {"kind": g.get("k", d.get("kind")), "parent": g.get("p", d.get("parent")),
                                    "iri": g.get("iri", d.get("iri")), "all": None, "items": {}, "when": when}})
    Path(argv[3]).write_text(json.dumps(writes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[carry] {dict(why)}")
    print(f"[carry] {len(writes)} document(s) to write -> {argv[3]}")
    for x in lost:
        print(f"[carry]   not carried: {x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
