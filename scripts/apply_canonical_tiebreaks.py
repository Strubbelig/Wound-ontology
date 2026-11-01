#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Apply the Canonical Tie-Breaks: one class, several names, one of them wins.

    python scripts/apply_canonical_tiebreaks.py <dir-of-decision-json> [--write]

The page is https://claude.ai/artifact/7U8LSVMuQspKoieS2sUYVM and it holds the
30 rows of the Contradiction Queue that could not be written, gathered into 28
conflicts. Every one of them has the same shape: two or three spellings that
are one class, and no ruling on which spelling the class keeps. The curator
taps the winner; every other spelling maps onto it.

Each decision carries the spellings it was asked about, so this script needs
nothing but the folder. The queue before it stored only the term and not the
question, and 634 of its 695 answers could not be applied until the question
was dug back out of the payload the page had been built from.

Dry by default. After writing it reads the mapping back off disk and raises if
a verdict did not land, because the page has stopped offering it.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

NOT_ONE_CLASS = "not_one_class"


def load(folder: Path) -> list[dict]:
    """Every decision document, with the document id stamped on from its name."""
    out = []
    for path in sorted(folder.rglob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        for row in (body if isinstance(body, list) else [body]):
            if isinstance(row, dict) and row.get("verdict"):
                row.setdefault("id", path.stem)
                out.append(row)
    return out


def plan(decisions, standing):
    """`(writes, held, clashes)` -- what to write, what to leave, what to name.

    `writes` is `[(loser, winner)]`: every spelling that is not the winner
    maps onto the one that is. `standing(term)` is what a term maps to today.

    Four things stop a decision being written, and each is named rather than
    guessed at:

    * `not_one_class` -- the curator looked and said these are not one thing.
      Nothing to write; it is an answer, not a failure, so it is `held`.
    * the verdict is not one of the spellings the question offered. That can
      only mean the page and this script disagree about the question.
    * one conflict's winner is another's loser. Writing both would make a
      spelling the name of its class and a synonym of something else at once.
    * a spelling maps to a term OUTSIDE the conflict. Overwriting it would
      drop a mapping nobody in this queue was asked about -- the same rule
      the pair queue applies, for the same reason.
    * two conflicts send one spelling to two different winners.

    Two conflicts may send one spelling to the SAME winner -- `areas under
    the receiver operating characteristic curve` is a loser in both ROC
    rows -- and that is one write, not two.
    """
    writes: list[tuple[str, str]] = []
    held: list[dict] = []
    clashes: dict[str, str] = {}

    winners = {d["id"]: d["verdict"] for d in decisions
               if d["verdict"] != NOT_ONE_CLASS}
    losers: dict[str, list[str]] = defaultdict(list)
    for d in decisions:
        if d["verdict"] == NOT_ONE_CLASS:
            continue
        for s in d.get("spellings", []):
            if s != d["verdict"]:
                losers[s].append(d["id"])

    for d in decisions:
        i, winner, spellings = d["id"], d["verdict"], list(d.get("spellings", []))
        if winner == NOT_ONE_CLASS:
            held.append(d)
            continue
        if winner not in spellings:
            clashes[i] = (f"the verdict {winner!r} is not one of the spellings the "
                          f"question offered ({spellings})")
            continue
        if winner in losers:
            clashes[i] = (f"{winner!r} is the winner here and a loser in "
                          f"{', '.join(sorted(set(losers[winner])))}")
            continue
        outside = [s for s in spellings
                   if standing(s) is not None and standing(s) not in spellings]
        if outside:
            clashes[i] = (f"{outside[0]!r} maps to {standing(outside[0])!r}, which is "
                          f"not one of the spellings in this conflict")
            continue
        writes.extend((s, winner) for s in spellings if s != winner)

    # One spelling, one target. Two conflicts agreeing is one write; two
    # conflicts disagreeing is a contradiction, and neither is written.
    to: dict[str, set[str]] = defaultdict(set)
    for loser, winner in writes:
        to[loser].add(winner)
    torn = {loser for loser, ws in to.items() if len(ws) > 1}
    for d in decisions:
        shared = torn.intersection(d.get("spellings", []))
        if shared:
            name = sorted(shared)[0]
            clashes[d["id"]] = (f"{name!r} is sent to more than one name "
                                f"({', '.join(sorted(map(repr, to[name])))})")
    writes = [(l, w) for l, w in writes if l not in torn]

    seen: set[tuple[str, str]] = set()
    return [p for p in writes if not (p in seen or seen.add(p))], held, clashes


def apply_writes(record, writes, stamp, decide_name=None) -> set[str]:
    """Point every loser at its winner, make every winner a name. `{winners}`.

    `record(term)` hands back that term's record, creating it if it is new.
    The winners are cleared FIRST and as a group: a winner that was itself
    pointing at one of its losers -- `ulcer area` at `area of ulcer`, and
    three more two-cycles like it -- has to stop before the loser is turned
    round, or the pair ends up pointing at each other.

    `decide_name` (`TermMappingAndGate.decide_name`) records each winner as the
    curator's choice of name for its cluster (2026-10-24), so the next
    election reads it instead of the corpus count.
    """
    from scripts.apply_contradiction_verdicts import record_curator

    named = {w for _, w in writes}
    losers: dict[str, list[str]] = defaultdict(list)
    for loser, winner in writes:
        losers[winner].append(loser)
    for winner in sorted(named):
        if decide_name is not None:
            decide_name(winner, losers[winner], by="curator", when=stamp,
                        reason="the canonical tie-breaks: this spelling names the class")
        rec = record(winner)
        rec["to"] = None                      # it is the name now, not a synonym
        rec.pop("retired", None)
        rec["method"] = "curator"
    for loser, winner in writes:
        rec = record(loser)
        rec["to"] = winner
        rec["method"] = "curator"
        rec["confidence"] = 1.0
        rec.pop("retired", None)
        record_curator(
            rec.setdefault("pairs", {}).setdefault(winner, {}),
            {"verdict": "same_class",
             "reason": "the canonical tie-breaks: this spelling names the class",
             "when": stamp})
    return named


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    folder = Path(sys.argv[1])
    write = "--write" in sys.argv
    decisions = load(folder)
    if not decisions:
        raise SystemExit(f"[canonical] no decisions found under {folder}")

    from wound_ontology.orchestrator import Orchestrator

    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def standing(term: str):
        rec = gt.records.get(term) or {}
        return None if rec.get("retired") else rec.get("to")

    writes, held, clashes = plan(decisions, standing)
    print(f"[canonical] {len(decisions)} decision(s): {len(writes)} spelling(s) to "
          f"repoint, {len(held)} left as not one class, {len(clashes)} not written")
    for i, why in sorted(clashes.items()):
        print(f"[canonical]   CLASH {i}: {why}")
    for loser, winner in writes:
        print(f"[canonical]   {loser!r} -> {winner!r}")

    if not write:
        print("[canonical] dry run — nothing written. Pass --write to apply.")
        return

    named = apply_writes(gt.record, writes, stamp, decide_name=gt.decide_name)
    gt._dirty()
    gt.save()

    fresh = Orchestrator().term_mapper._term_mapping
    lost = [f"{loser} -> {winner}" for loser, winner in writes
            if (fresh.records.get(loser) or {}).get("to") != winner
            or (fresh.records.get(loser) or {}).get("retired")]
    unnamed = [w for w in sorted(named)
               if (fresh.records.get(w) or {}).get("to") is not None]
    if lost or unnamed:
        raise SystemExit(
            f"[canonical] {len(lost)} repointing(s) and {len(unnamed)} canonical(s) "
            f"did not read back from disk: {lost[:3]} {unnamed[:3]}")
    print("[canonical] written and verified against the file on disk.")


if __name__ == "__main__":
    main()
