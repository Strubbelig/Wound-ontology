"""Write the curator's judgement-queue decisions into the term dict (rule 72).

    python -u scripts/apply_judgement_queue.py [--write] [--only=SECTION]

Curator, 2026-10-07: "Judgement is done". The page's decisions were read back
with ArtifactData and resolved to classes in
data/review/judgement_queue_decisions_2026-10-07.json; every parent the curator
typed is kept there beside the class it was read as, and the readings that were
not an exact label were confirmed in chat (rule 39). The relations section is
not handled here: build_wont_core.py reads new_class_relation_decisions.json.

* parents, fillers, conflicts with a parent -> the pair gets
  `placement: {verdict: "narrower"}` and a curator mark. For a conflict, every
  other parent the abstracts suggested is refused (the curator named one).
  A conflict's chosen parent was contradicted by the reasoner; placing it does
  not make that go away -- the run lists them, and the build will keep them
  out until whatever else about the term is wrong has been found.
* parents "leave them out" -> nothing is written; their children stay out,
  as before. Likert scale (the curator's note on Categorical Level
  Specification) is placed under Wound classification scale and its pair with
  Categorical Level Specification is refused.
* duplicates "same thing" -> the new term is mapped onto the existing class.
  "different" -> that pair is refused, so no later build re-proposes it.

Reversible: every write is a judgement on a pair, tagged `by: BY`; the backup
is taken first. Reads back after writing, and raises if a decision did not land.
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

DECISIONS = ROOT / "data" / "review" / "judgement_queue_decisions_2026-10-07.json"
BY = "judgement queue (curator page, 2026-10-07)"


def plan_of(decisions: list[dict]) -> list[tuple]:
    """(action, term, class label, info) for every decision that writes something."""
    plan = []
    for e in decisions:
        sec, v, term = e["section"], e["decision"], e["subject"]
        par = e.get("parent")
        info = {"by": BY, "item": e["item_id"], "curator typed": e.get("typed_parent", ""),
                "note": e.get("note", "")}
        if sec in ("parents", "fillers", "conflicts") and v == "yes":
            if not par:
                raise ValueError(f"{term!r}: decided yes with no parent")
            plan.append(("narrower", term, par["label"], {**info, "iri": par["iri"], "why": par["why"]}))
            if sec == "conflicts":
                for other in e.get("item_parents", []):
                    if other.lower() != par["label"].lower():
                        plan.append(("refuse", term, other, {**info, "why": f"curator chose {par['label']!r} instead"}))
            if term == "Likert scale":
                plan.append(("refuse", term, "categorical level specification",
                             {**info, "why": "curator moved it to the other scales"}))
        elif sec == "scope":
            plan.append(("in", term, "", {**info, "why": e["why"]}))
        elif sec == "category":
            plan.append(("category", term, v, {**info, "why": e["why"]}))
        elif sec == "children":
            plan.append(("refuse", term, par["label"], {**info, "why": e["why"]}))
        elif sec == "duplicates":
            m = e["item_matches"]
            if len(m) != 1:
                raise ValueError(f"{term!r}: {len(m)} matches; a duplicate decision needs exactly one")
            m = m[0]
            if v == "yes":
                plan.append(("same", term, m["label"], {**info, "iri": m["iri"], "source": m["source"]}))
            else:
                plan.append(("refuse", term, m["label"], {**info, "why": "curator: a different thing"
                                                          + (f" ({e['note']})" if e.get("note") else "")}))
        elif sec in ("parents",) and v == "no":
            continue
        elif sec in ("parents", "fillers", "conflicts") and v == "no":
            raise NotImplementedError(f"{sec} 'no' for {term!r} has no write defined")
    return plan


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"]
    only = [a.split("=", 1)[1] for a in argv if a.startswith("--only=")]
    plan = plan_of([d for d in decisions if not only or d["section"] in only])
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    when = datetime.now().isoformat(timespec="seconds")
    # The page shows the built class's label ("Cell Process"); the record is keyed
    # by the spelling in the abstracts ("cell process"). Writing under the page's
    # spelling would create an empty record no view reads, so the decision would
    # vanish: match without case, follow aliases, and refuse when there is no
    # record or more than one current spelling.
    lower: dict[str, set] = {}
    for k in gt.records:
        lower.setdefault(k.lower(), set()).add(gt.resolve(k))
    resolved, no_record = [], []
    for a, t, c, i in plan:
        hits = lower.get(t.lower(), set())
        if len(hits) != 1:
            no_record.append((t, sorted(hits)))
            continue
        t = next(iter(hits))
        # The same holds for the class side of a pair: the placement step keyed
        # Likert scale's pair as "categorical level specification", and a refusal
        # written as "Categorical Level Specification" refused a pair nobody reads.
        prs = gt.records[t].get("pairs", {})
        stray = lambda k: set(prs[k]) <= {"refused", "curator"} and (prs[k].get("refused") or {}).get("by") == BY
        same = [k for k in prs if c and a != "category" and k.lower() == c.lower()]
        if len(same) > 1:                    # this script's own refusal under the wrong case is not a rival
            same = [k for k in same if not stray(k)] or same
        if len(same) > 1:
            raise RuntimeError(f"[judgement] {t!r} holds {same}: one class under two spellings; resolve first")
        resolved.append((a, t, same[0] if same else c, i))
    if no_record:
        print(f"[judgement] NOT written -- no single record in the term dict for: {no_record}")
    mapped = [(t, gt.data.get(t)) for a, t, c, _ in resolved if a == "narrower" and gt.data.get(t)]
    if mapped:
        print(f"[judgement] already mapped onto a class, so a parent here would not count: {mapped}")
    plan = resolved
    for a, t, c, i in plan:
        print(f"[judgement] {a:8} {t!r:42} -> {c!r}")
    print(f"[judgement] {dict(Counter(a for a, *_ in plan))}")
    blocked = [(a, t, c) for a, t, c, _ in plan if a in ("narrower", "same") and gt.is_refused(t, c)]
    if blocked:
        raise RuntimeError(f"[judgement] pair(s) already refused in the term dict -- a curator decision "
                           f"would be dropped; resolve first: {blocked}")
    conflicts = sorted(gt.resolve(d["subject"]) for d in decisions if d["section"] == "conflicts" and d["decision"] == "yes")
    if conflicts:
        print(f"[judgement] the reasoner contradicted these placements; they stay out of the build until the "
              f"conflict is found: {conflicts}")
    if "--write" not in argv:
        print("[judgement] dry run; --write to apply")
        return 0

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_judgement_queue_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[judgement] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    for action, term, cls, info in plan:
        if action == "narrower":
            gt.judge(term, cls, placement={"verdict": "narrower", "when": when, **info},
                     curator={"verdict": "narrower", "when": when, "by": BY, "reason": info["why"]})
        elif action == "same":
            rec = gt.record(term)
            rec.update({"to": cls, "confidence": 1.0, "method": "curator"})
            rec.pop("retired", None)
            gt.judge(term, cls, placement={"verdict": "same_class", "when": when, **info},
                     curator={"verdict": "same_class", "when": when, "by": BY,
                              "reason": "same thing as the existing class (judgement queue)"})
        elif action == "refuse":
            gt.refuse(term, cls, reason=info["why"], by=BY)
            # a refusal an earlier run of this script wrote under the wrong case
            pairs = gt.records[term]["pairs"]
            for k in [k for k in pairs if k != cls and k.lower() == cls.lower()]:
                j = pairs[k]
                if set(j) <= {"refused", "curator"} and (j.get("refused") or {}).get("by") == BY:
                    del pairs[k]
                    print(f"[judgement] removed the refusal written under the wrong spelling: {term!r} / {k!r}")
        elif action == "in":
            gt.gate(term, curator={"verdict": "in", "when": when, "by": BY, "reason": info["why"]})
        elif action == "category":
            from wound_ontology.mappers.term_mapping_and_gate import TERM_RULING
            print(f"[judgement] category of {term!r}: {gt.set_category(term, cls, source=TERM_RULING, note=info['why'])}")
    gt._dirty()
    gt.save()
    print(f"[judgement] gate lists re-exported: {p.export_gate_lists()}")

    g2 = Orchestrator().term_mapper._term_mapping
    lost = []
    for action, term, cls, _ in plan:
        j = g2.peek(g2.resolve(term), cls)
        if action == "narrower" and ((j.get("placement") or {}).get("verdict") != "narrower" or j.get("refused")):
            lost.append((action, term, cls))
        elif action == "same" and g2.data.get(g2.resolve(term)) != cls:
            lost.append((action, term, cls))
        elif action == "refuse" and not j.get("refused"):
            lost.append((action, term, cls))
        elif action == "category" and (g2.categories().get(g2.resolve(term)) or {}).get("verdict") != cls:
            lost.append((action, term, cls))
        elif action == "in" and g2.effective_gate_verdict(g2.resolve(term))[0] != "in":
            lost.append((action, term, g2.effective_gate_verdict(g2.resolve(term))))
    if lost:
        raise RuntimeError(f"[judgement] {len(lost)} decision(s) did not land: {lost}")
    placed = set(g2.placements())
    out_of_scope = [(t, c) for a, t, c, _ in plan if a == "narrower" and (g2.resolve(t), c) not in placed]
    if out_of_scope:
        print(f"[judgement] written, but not counted as placements (term out of scope or mapped): {out_of_scope}")
    print(f"[judgement] written and read back: {len(plan)} decisions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
