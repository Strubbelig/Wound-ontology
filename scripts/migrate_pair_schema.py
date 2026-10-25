#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Split each pair verdict into cluster membership and the cluster's name.

    python scripts/migrate_pair_schema.py            # dry run, writes the plan only
    python scripts/migrate_pair_schema.py --write    # backup, rewrite, read back

Curator, 2026-10-24: "es sollte zunächst um die cluster formierung gehen. danach
sollte ein term aus dem cluster herausgepickt werden." Until then one curator
verdict carried both questions: `reverse` / `reversed` said "same class, but
the other one is the name", `repointed` "same class as that other term",
`kept` "same class", and the lock `refused` was written for a dozen reasons. In
the new shape (`TermMappingAndGate`, `PAIR_VERDICTS`, `LOCK_CAUSES`, `NAME`):

* a pair verdict answers ONE question -- how does the term stand to the class:
  `same_class` | `narrower` | `broader` | `different`, for every source;
* the name of a cluster is a decision of its own, on the chosen term
  (`name: {by, instead_of, reason, when}`);
* the lock `refused` says "not this cluster" and why, in `cause`;
* the 74 verdicts the restatement check (model + Claude's reading) wrote under
  `curator` move to their own source, `check` (curator, 2026-10-24).

Names. Every EXPLICIT naming act is collected with its date: a reversal
(`reverse`, `reversed`, a lock "reversed by the curator"), a canonical
tie-break, the contradiction queue's "reversed from the other direction", a
spelling the curator typed, and the readings below. Per cluster the latest
one is the decision. If the curator LATER confirmed a pair that points the
chosen name at another term, the two disagree and nothing is decided: the
cluster keeps its current name and is listed for the curator.

A decided name the record does not follow today is given back where the two
terms are still one cluster -- the next `resolve_chains` would do it anyway --
and for the names in `RESTORE`, which the curator chose to give back on
2026-10-24 even where the two were split apart since. An ontology label in the
cluster outranks the decision either way (rule 36).

`placement` folds into `curator` (curator, 2026-10-24: "die beiden kann man
wunderbar zu curator mergen"). Only a placement: it becomes the curator
entry, `iri` and all. Both, and they agree: one entry. Both, and they differ,
or the pair is locked: the curator entry stands and the placement goes to
`curator_history` -- every curator entry there is the later one, except three
bulk approvals of 2026-09-25, which the curator ruled stand too. The four
placements under MILD classes renamed since carry no IRI; `MISSING_IRI` fills
it from mild_2026-10-20.ttl.

A refusal whose reason this script cannot read is listed, never guessed
(rule 66, "no silent failure").
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

SAME = ("same_class", "narrower", "broader", "different")
OLD_SAME = ("kept", "same_class", "reversed", "reverse", "repointed")

#: The refusals whose reason the rules below do not cover, read one by one on
#: 2026-10-24 and approved by the curator that day. Only what the reason SAYS
#: is taken: a direction where it names one, otherwise the lock alone.
READ = {
    ("burn wound", "Burn injury"):                    {"verdict": "narrower", "lock": "curator"},
    ("acute burn wound", "Burn injury"):              {"verdict": "narrower", "lock": "curator"},
    ("Burn injury", "burn wound"):                    {"verdict": "broader", "lock": "curator"},
    ("acute burn injury", "acute burn wound"):        {"verdict": "broader", "lock": "curator"},
    ("second-degree burn injury", "Second-degree burn wound"):
                                                      {"verdict": "broader", "lock": "curator"},
    ("partial-thickness scald", "Second-degree burn wound"):
                                                      {"verdict": "different", "lock": "curator"},
    ("Burn injury", "Thermal wound"):                 {"lock": "curator"},
    ("burn injury treatment", "burn treatment"):      {"lock": "curator"},
    ("Na+", "NA"):                                    {"verdict": "different", "lock": "curator"},
    ("collagen matrix dressing", "collagen dressing"): {"lock": "curator"},
    ("antimicrobial agent", "antimicrobial"):         {"lock": "curator"},
    ("wound healing", "impaired wound healing"):      {"verdict": "broader", "lock": "curator"},
    # naming decisions written as refusals: the term is the name
    ("Second-degree burn wound", "2nd degree burn"):  {"verdict": "same_class", "name": True},
    ("interleukin-18", "IL- 18"):                     {"verdict": "same_class", "name": True},
    ("microRNA", "miRNA"):                            {"verdict": "same_class", "name": True},
}

#: Names the curator chose to give back (2026-10-24), from the fork session's
#: 39 overridden names. Left out: the nine the curator renamed AGAIN later (on
#: the canonical tie-break page or the contradiction queue -- `area of wound`
#: became `wound area` there), the broken `regional tissue oxygen saturation)`,
#: and `wound healing process` / `wound repair process`, a cluster named twice
#: and still open.
RESTORE = frozenset({
    "Joinpoint regression model", "Lower Albumin level", "acute postoperative complication",
    "anatomical region", "anthracycline-associated cardiotoxicity", "antibacterial agent",
    "antimicrobial characteristic", "automatic segmentation method", "emergency care setting",
    "immunodeficiency disorder", "keloid tissue", "laboratory investigation",
    "light chain 3 gene", "logistical", "low-level laser therapy treatment",
    "microbial virulence factor", "oral ulcer", "post-discharge period",
    "preoperative bowel preparation regimen", "prophylaxis", "prospective multicenter trial",
    "rate of wound healing", "receiver operating characteristic curve analysis",
    "silver nanoparticle", "snakebite envenomation", "type 2 diabetes mellitus",
    "wound care approach",
})

#: The class IRIs four placements lost when their MILD class was renamed
#: (read from mild_2026-10-20.ttl on 2026-10-24).
MISSING_IRI = {
    "pathological disorder": "https://bioportal.bioontology.org/ontologies/MILD/MILD_120022",
    "disorder creating disease course process":
        "https://bioportal.bioontology.org/ontologies/MILD/MILD_120053",
}

REVERSAL_LOCK = ("reversed by the curator", "the contradiction queue: reversed")
NAMING_REASONS = ("the canonical tie-breaks", "the contradiction queue: reversed from the other",
                  "spelling typed in the scope review")
_STAMP = re.compile(r"\d{4}-\d\d-\d\d(?:T\d\d:\d\d(?::\d\d)?)?")


def when_of(*entries) -> str | None:
    """The date of a decision: its `when`, else the first stamp in its reason."""
    for e in entries:
        if not e:
            continue
        if e.get("when"):
            return str(e["when"])[:19]
        m = _STAMP.search(e.get("reason") or "")
        if m:
            return m.group(0)
    return None


def lock_cause(lock: dict) -> str:
    by, why = lock.get("by") or "", lock.get("reason") or ""
    if by.startswith("rule 58") or "(rule 58)" in why:
        return "rule 58"
    if "the MILD class is gone" in why:
        return "target removed"
    if by.startswith(("placement review", "judgement queue")) or "refused on the review page" in why \
            or "leave them out" in why:
        return "placement refused"
    return "curator"


def classify(term: str, canonical: str, j: dict) -> dict:
    """The new reading of one pair.

    Returns `verdict` (new curator verdict or None), `lock` (a cause, "drop",
    or None when there is no lock), `name` ((chosen, instead, when) or None),
    `confirms` ((target, when): a plain later confirmation, used only to find
    disagreements) and `read` (why a person has to look).
    """
    cur, lock = j.get("curator") or {}, j.get("refused")
    v, why = cur.get("verdict"), cur.get("reason") or ""
    out: dict = {"verdict": None, "lock": None, "name": None, "confirms": None}
    lock_why = (lock or {}).get("reason") or ""

    if (term, canonical) in READ:
        r = READ[(term, canonical)]
        out["verdict"] = r.get("verdict")
        out["lock"] = "drop" if r.get("name") else (r.get("lock") if lock else None)
        if r.get("name"):
            out["name"] = (term, canonical, when_of(lock, cur))
        return out

    # the old direction of a reversal: one class, and the TERM is the name
    if lock and lock_why.startswith(REVERSAL_LOCK):
        out["lock"] = "drop"
        out["name"] = (term, canonical, when_of(lock))
        out["verdict"] = "same_class"
        if v in ("kept", "same_class", "repointed") and when_of(cur):
            out["confirms"] = (canonical, when_of(cur))     # looked at again later
        return out
    if v == "reverse":
        out["verdict"] = "same_class"
        out["lock"] = "drop" if lock else None
        out["name"] = (term, canonical, when_of(cur, lock))
        return out
    if v == "reversed":                    # the new pair: the canonical is the name
        out["verdict"] = "same_class"
        out["name"] = (canonical, term, when_of(cur))
    elif v in ("kept", "same_class", "repointed"):
        out["verdict"] = "same_class"
        if lock and (when_of(cur) or "") > (when_of(lock) or "~"):
            # confirmed AFTER the lock was written (the contradiction queue of
            # 2026-09-27 over the review UI's withdrawals of 09-25): the lock
            # is the earlier decision, not the standing one
            out["lock"] = "drop"
            return out
        if why.startswith(NAMING_REASONS) or "spelling typed in the scope review" in why:
            out["name"] = (canonical, term, when_of(cur))
        elif when_of(cur):
            out["confirms"] = (canonical, when_of(cur))
    elif v in SAME:
        out["verdict"] = v
    elif v == "refused":
        if "the MILD class is gone" in why or (lock or {}).get("by", "").startswith("rule 58") \
                or "(rule 58)" in why:
            pass                                             # lock only
        elif "adds a qualifier that narrows" in why:
            out["verdict"] = "broader"                       # the canonical is the narrower one
        elif "relatedMatch" in why:
            out["verdict"] = "different"
        elif "a different thing" in why:
            out["verdict"] = "different"
        elif "naming review" in why or lock_cause(lock or {}) == "placement refused":
            pass                                             # "not this cluster", nothing more said
        else:
            out["read"] = f"refused, reason not read: {why[:120]!r}"
    elif v is not None:
        out["read"] = f"unknown curator verdict {v!r}"
    if lock:
        out["lock"] = lock_cause(lock)
    return out


def plan(records: dict, anchors: set[str]) -> dict:
    """Everything the migration would do, without doing it."""
    pairs: dict[tuple[str, str], dict] = {}
    to_read, checks, events, confirms = [], [], [], []
    for term, rec in records.items():
        if not isinstance(rec, dict) or "spelling" in rec:
            continue
        for canonical, j in (rec.get("pairs") or {}).items():
            if not (j.get("curator") or j.get("refused")):
                continue
            cur = j.get("curator") or {}
            if (cur.get("by") or "").startswith("restatement check"):
                checks.append((term, canonical))
                if cur.get("verdict") not in SAME:
                    to_read.append({"term": term, "canonical": canonical,
                                    "why": f"check verdict {cur.get('verdict')!r}"})
                continue
            new = classify(term, canonical, j)
            if new.get("read"):
                to_read.append({"term": term, "canonical": canonical, "why": new["read"]})
                continue
            pairs[(term, canonical)] = new
            if new["name"]:
                events.append({"chosen": new["name"][0], "instead": new["name"][1],
                               "when": new["name"][2], "pair": [term, canonical],
                               "old": cur.get("verdict"), "reason": cur.get("reason") or
                               (j.get("refused") or {}).get("reason", "")})
            if new["confirms"]:
                confirms.append({"term": term, "target": new["confirms"][0],
                                 "when": new["confirms"][1]})

    # clusters: the live mapping plus every pair a naming act names
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for term, rec in records.items():
        if isinstance(rec, dict) and rec.get("to"):
            parent[find(term)] = find(rec["to"])
    for e in events:
        parent[find(e["chosen"])] = find(e["instead"])
    by_cluster: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_cluster[find(e["chosen"])].append(e)
    later_confirms: dict[str, list[dict]] = defaultdict(list)
    for c in confirms:
        later_confirms[find(c["term"])].append(c)

    def head(t: str) -> str:
        seen = set()
        while isinstance(records.get(t), dict) and records[t].get("to") and t not in seen:
            seen.add(t)
            t = records[t]["to"]
        return t

    decisions, undecided = [], []
    for root, evs in by_cluster.items():
        dated = sorted((e for e in evs if e["when"]), key=lambda e: e["when"])
        names = {e["chosen"] for e in evs}
        if not dated and len(names) > 1:
            undecided.append({"names": sorted(names), "why": "several names, no dates"})
            continue
        last = dated[-1] if dated else evs[0]
        chosen = last["chosen"]
        # a later plain confirmation pointing the chosen name somewhere else
        against = [c for c in later_confirms.get(root, [])
                   if c["term"] == chosen and c["target"] != chosen
                   and (not last["when"] or c["when"] > last["when"])]
        if against:
            undecided.append({"names": sorted(names | {c["target"] for c in against}),
                              "chosen then": chosen, "chosen when": last["when"],
                              "confirmed later": [(c["term"], c["target"], c["when"]) for c in against],
                              "why": "a later confirmation points the chosen name elsewhere"})
            continue
        if chosen.count("(") != chosen.count(")") or chosen.count("[") != chosen.count("]"):
            # `regional tissue oxygen saturation)`: a broken string cannot be a
            # name, whoever picked it from a list
            undecided.append({"names": sorted(names), "chosen then": chosen,
                              "chosen when": last["when"],
                              "why": "the chosen name is not a well-formed term"})
            continue
        instead = sorted(({e["instead"] for e in evs} | {e["chosen"] for e in evs}) - {chosen})
        now = head(chosen)
        joined = now != chosen               # the chosen name is mapped into the cluster today
        if now == chosen:
            heads = {head(i) for i in instead} - {chosen}
            now = sorted(heads)[0] if heads else chosen
        beaten = now != chosen and now.lower() in anchors and chosen.lower() not in anchors
        decisions.append({"chosen": chosen, "instead_of": instead, "when": last["when"],
                          "reason": last["reason"], "now": now,
                          "restore": now != chosen and not beaten and (joined or chosen in RESTORE),
                          "joined": joined,
                          "anchor wins": beaten,
                          "earlier choices": sorted(names - {chosen})})
    # The curator's answer for clusters left open above (2026-10-24): give the
    # earlier name back.
    still_open = []
    for u in undecided:
        chosen = [n for n in u["names"] if n in RESTORE]
        if len(chosen) != 1:
            still_open.append(u)
            continue
        chosen = chosen[0]
        instead = sorted(set(u["names"]) - {chosen})
        now = head(chosen)
        joined = now != chosen
        if now == chosen:
            heads = {head(i) for i in instead} - {chosen}
            now = sorted(heads)[0] if heads else chosen
        beaten = now != chosen and now.lower() in anchors and chosen.lower() not in anchors
        decisions.append({"chosen": chosen, "instead_of": instead,
                          "when": datetime.now().isoformat(timespec="seconds"),
                          "reason": "curator 2026-10-24: give the earlier name back",
                          "now": now, "restore": now != chosen and not beaten,
                          "joined": joined, "anchor wins": beaten, "earlier choices": []})
    undecided = still_open
    return {"pairs": pairs, "to_read": to_read, "checks": checks,
            "decisions": decisions, "undecided": undecided, "head": head}


def apply(gt, p: dict) -> dict:
    """Write the plan into the records. Returns what was done."""
    from wound_ontology.mappers.term_mapping_and_gate import NAME
    recs = gt.records
    done = Counter()
    for term, canonical in p["checks"]:
        j = recs[term]["pairs"][canonical]
        j["check"] = j.pop("curator")
        done["check: moved from curator"] += 1
    for (term, canonical), new in p["pairs"].items():
        j = recs[term]["pairs"][canonical]
        old = j.get("curator")
        if old and new["verdict"] != old.get("verdict"):
            if new["verdict"]:
                j["curator"] = {**old, "verdict": new["verdict"], "was": old.get("verdict")}
            else:
                j.setdefault("curator_history", []).append(old)
                del j["curator"]
            done[f"curator {old.get('verdict')} -> {new['verdict'] or '(lock only)'}"] += 1
        elif not old and new["verdict"]:
            j["curator"] = {"verdict": new["verdict"], "when": datetime.now().isoformat(timespec="seconds"),
                            "reason": (j.get("refused") or {}).get("reason", "")}
            done[f"curator (none) -> {new['verdict']}"] += 1
        if new["lock"] == "drop" and j.get("refused"):
            j.setdefault("lock_history", []).append(j.pop("refused"))
            done["lock dropped: a name decision says it now"] += 1
        elif new["lock"] and new["lock"] != "drop" and j.get("refused"):
            j["refused"]["cause"] = new["lock"]
            done[f"lock cause: {new['lock']}"] += 1

    # placement folds into curator
    held = []
    for term, rec in recs.items():
        for canonical, j in (rec.get("pairs") or {}).items():
            pl = j.pop("placement", None)
            if not pl:
                continue
            pl = dict(pl)
            if not pl.get("iri") and canonical in MISSING_IRI:
                pl["iri"] = MISSING_IRI[canonical]
                done["placement: IRI filled from mild.ttl"] += 1
            cur = j.get("curator")
            if j.get("refused"):
                j.setdefault("curator_history", []).append({**pl, "was": "placement"})
                done["placement: locked pair, to history"] += 1
            elif rec.get("to") == canonical and pl["verdict"] == "narrower" and not cur:
                # mapped as one class, placed beneath it: which is it? listed
                j.setdefault("curator_history", []).append({**pl, "was": "placement"})
                held.append((term, canonical))
                done["placement: mapped AND placed beneath, held"] += 1
            elif not cur:
                why = pl.pop("why", None)
                j["curator"] = {**pl, "reason": why or "placed on the curator's review page"}
                done["placement: becomes the curator entry"] += 1
            elif cur.get("verdict") == pl["verdict"]:
                for k, v in pl.items():
                    if k not in ("verdict", "by", "when"):
                        cur.setdefault(k, v)
                done["placement: agrees with curator, one entry"] += 1
            else:
                j.setdefault("curator_history", []).append({**pl, "was": "placement"})
                done["placement: curator stands, placement to history"] += 1

    restored = []
    for d in p["decisions"]:
        gt.decide_name(d["chosen"], d["instead_of"], by="curator", reason=d["reason"][:200],
                       when=d["when"])
        done["name decisions"] += 1
        if not d["restore"]:
            continue
        old_head, chosen = d["now"], d["chosen"]
        moved = []
        for t, r in recs.items():
            if r.get("to") == old_head and t != chosen:
                if (r.get("pairs") or {}).get(chosen, {}).get("refused"):
                    continue                     # a lock says it does not belong
                r["to"] = chosen
                moved.append(t)
        r_old = recs.setdefault(old_head, {"to": None, "pairs": {}})
        if not (r_old.get("pairs") or {}).get(chosen, {}).get("refused"):
            r_old["to"] = chosen
            r_old["method"] = "curator"
            r_old["confidence"] = 1.0
            r_old.pop("retired", None)
            moved.append(old_head)
        recs[chosen]["to"] = None
        recs[chosen].pop("retired", None)
        # The cluster's place in the hierarchy hung on its old name; the name
        # moves, so does the place (`diabetes mellitus type-2` under `Diabetic
        # metabolic disorder` becomes `type 2 diabetes mellitus` under it).
        for cls, j in list((r_old.get("pairs") or {}).items()):
            cur = j.get("curator") or {}
            if cur.get("verdict") == "narrower" and cur.get("iri") and not j.get("refused"):
                target = recs[chosen].setdefault("pairs", {}).setdefault(cls, {})
                if not target.get("curator") and not target.get("refused"):
                    target["curator"] = {**cur, "moved_from": old_head}
                    done["placement moved to the restored name"] += 1
        restored.append({"name": chosen, "was": old_head, "members moved": len(moved)})
        done["names restored"] += 1
    gt._dirty()
    # a lock now stands against a live mapping only where a rename merged them
    for term, target in gt.locked_mappings():
        recs[term]["to"] = None
        done["locked mapping withdrawn"] += 1
        restored.append({"withdrawn": term, "was mapped onto": target})
    gt._dirty()
    return {"done": dict(done), "restored": restored, "held": held}


def verify(gt) -> list[str]:
    """What must hold after the write. Empty when it does."""
    # The lock `refused` and its `cause` are gone since 2026-10-25 (rule 84):
    # what this checked about them, the curator's verdict now carries.
    from wound_ontology.mappers.term_mapping_and_gate import PAIR_SOURCES, PAIR_VERDICTS
    bad = []
    for t, r in gt.records.items():
        for c, j in (r.get("pairs") or {}).items():
            for s in PAIR_SOURCES:
                if s in j and j[s].get("verdict") not in PAIR_VERDICTS:
                    bad.append(f"{t!r} -> {c!r} {s}: {j[s].get('verdict')!r}")
            if "refused" in j:
                bad.append(f"{t!r} -> {c!r}: a lock beside the verdicts")
    bad += [f"{t!r} -> {c!r} is mapped and locked" for t, c in gt.locked_mappings()]
    bad += [f"{t!r} -> {c!r} still has a placement" for t, r in gt.records.items()
            for c, j in (r.get("pairs") or {}).items() if "placement" in j]
    return bad


def main(argv: list[str]) -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from wound_ontology.orchestrator import Orchestrator
    orch = Orchestrator()
    gt = orch.term_mapper._term_mapping
    anchors = {label.lower() for label in orch.ontology_labels()}
    p = plan(gt.records, anchors)

    kinds = Counter()
    for new in p["pairs"].values():
        kinds[("verdict", new["verdict"] or "(lock only)")] += 1
        if new["lock"]:
            kinds[("lock", new["lock"])] += 1
    print(f"[pair schema] {len(p['pairs']):,} pairs with a curator verdict or a lock")
    for (k, v), n in sorted(kinds.items()):
        print(f"    {n:6,}  {k}: {v}")
    print(f"[pair schema] {len(p['checks'])} verdicts move from curator to check")
    rest = [d for d in p["decisions"] if d["restore"]]
    joined = [d for d in rest if d["joined"]]
    print(f"[pair schema] {len(p['decisions'])} name decisions; {len(rest)} come back "
          f"({len(joined)} still one cluster, {len(rest) - len(joined)} re-joined); "
          f"{sum(d['anchor wins'] for d in p['decisions'])} stay under an ontology label")
    for d in rest:
        print(f"    {'' if d['joined'] else '(split) '}{d['now']!r} -> {d['chosen']!r}  ({d['when']})")
    print(f"[pair schema] {len(p['undecided'])} clusters left for the curator:")
    for u in p["undecided"]:
        print(f"    {u}")
    print(f"[pair schema] {len(p['to_read'])} pairs not read:")
    for r in p["to_read"]:
        print(f"    {r}")

    out = ROOT / "data" / "review" / f"pair_schema_plan_{date.today()}.json"
    n = 1
    while out.exists():
        out = out.with_name(f"pair_schema_plan_{date.today()}_{n}.json"); n += 1
    out.write_text(json.dumps({
        "decisions": p["decisions"], "undecided": p["undecided"], "to_read": p["to_read"],
        "checks": p["checks"],
        "pairs": [{"term": t, "canonical": c, **{k: v for k, v in new.items()}}
                  for (t, c), new in p["pairs"].items()]}, ensure_ascii=False, indent=1, default=str))
    print(f"[pair schema] plan -> {out.relative_to(ROOT)}")

    if "--write" not in argv:
        print("[pair schema] dry run; --write to apply")
        return 0
    if p["to_read"]:
        print("[pair schema] refusing to write: pairs are left unread")
        return 1
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"),
               key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_pair_schema_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[pair schema] backed up {live.name} -> {backup.relative_to(ROOT)}")
    result = apply(gt, p)
    gt.save()
    print(f"[pair schema] {result['done']}")
    (out.with_name(out.stem + "_applied.json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=1))

    # Read it back off disk.
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    again = TermMappingAndGate(orch.term_mapper._term_mapping._dm)
    bad = verify(again)
    if bad:
        raise SystemExit(f"[pair schema] {len(bad)} record(s) do not hold after the write: {bad[:10]}")
    missing = [d["chosen"] for d in p["decisions"] if d["chosen"] not in again.named()]
    if missing:
        raise SystemExit(f"[pair schema] {len(missing)} name decision(s) did not land: {missing[:10]}")
    print("[pair schema] read back: every verdict in the four words, every lock with a cause, "
          "no locked mapping, every name decision on record")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
