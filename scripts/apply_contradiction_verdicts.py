#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Apply the Contradiction Queue's verdicts to the record.

    python scripts/apply_contradiction_verdicts.py <dir-of-decision-json> [--write]

The page is https://claude.ai/artifact/9VpYXEKfmQ1zxmgEfidLG4 and it holds two
queues, which land in two different places:

  SCOPE TIE-BREAKS  a `gate_contested` record whose one source answered both
                    `in` and `out` about two spellings of one term, so it was
                    removed and the term has no verdict at all. The curator's
                    answer is written as `gate(curator=...)`, which outranks
                    every pass (rule 40), and the `gate_contested` block stays
                    where it is -- it is the evidence the question was asked.

  MAPPING PAIRS     pass 1 and pass 2 judged one (term, canonical) pair
                    differently. `same_class` confirms the mapping;
                    `narrower`/`broader` say the two are related but not one
                    class, so the mapping is withdrawn and the pair is kept as
                    a subsumption candidate; `different` refuses the pair,
                    which is what stops the next build proposing it again
                    (rule 37).

Dry by default. Nothing is written without `--write`, and after writing it
reads both back off disk and raises if a verdict did not land -- a decision
that silently failed to apply is worse than one never made, because the queue
will not show it again.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

SCOPE = {"in", "out", "unsure"}
PAIR = {"same_class", "narrower", "broader", "different"}


def _load(folder: Path) -> list[dict]:
    """Every decision document the Artifact store handed back."""
    out = []
    for path in sorted(folder.rglob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        rows = body if isinstance(body, list) else [body]
        for row in rows:
            if isinstance(row, dict) and row.get("verdict"):
                out.append(row)
    return out


def classify(rows: list[dict]) -> tuple[list, list, list, list]:
    """`(scope, pairs, held, unrecognised)`.

    Separated from `main` so it can be tested without the store. Anything
    whose queue or verdict is not one this script knows how to apply goes to
    `unrecognised` and is printed -- a decision the curator made and this
    script silently ignored is the worst outcome available, because the queue
    counts it as answered and will not offer it again.
    """
    scope, pairs, held, unknown = [], [], [], []
    for r in rows:
        v = r.get("verdict")
        if r.get("queue") == "contested" and v in SCOPE:
            (held if v == "unsure" else scope).append(r)
        elif r.get("queue") == "pairs" and v in PAIR:
            pairs.append(r)
        else:
            unknown.append(r)
    return scope, pairs, held, unknown


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    folder = Path(sys.argv[1])
    write = "--write" in sys.argv
    rows = _load(folder)
    if not rows:
        raise SystemExit(f"[verdicts] no decisions found under {folder}")

    from wound_ontology.orchestrator import Orchestrator

    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    scope, pairs, held, unknown = classify(rows)

    print(f"[verdicts] {len(rows)} decision(s): {len(scope)} scope, {len(pairs)} pair, "
          f"{len(held)} left open on purpose, {len(unknown)} unrecognised")
    for r in unknown:
        print(f"[verdicts]   UNRECOGNISED {r.get('queue')!r}/{r.get('verdict')!r} "
              f"on {r.get('term')!r}")

    # ── scope ────────────────────────────────────────────────────────────────
    for r in scope:
        term = r["term"]
        print(f"[verdicts]   gate {term!r} -> {r['verdict']}"
              + (f"  ({r['note']})" if r.get("note") else ""))
        if write:
            gt.gate(term, curator={"verdict": r["verdict"],
                                   "reason": r.get("note", ""),
                                   "when": stamp,
                                   "by": "curator via the contradiction queue"})

    # ── pairs ────────────────────────────────────────────────────────────────
    refused, withdrawn, confirmed = [], [], []
    for r in pairs:
        term, canonical, v = r["term"], r.get("canonical"), r["verdict"]
        if not canonical:
            rec = gt.records.get(term) or {}
            canonical = rec.get("to")
        if not canonical:
            unknown.append(r)
            print(f"[verdicts]   NO CANONICAL for {term!r}; skipped")
            continue
        judgement = {"verdict": v, "reason": r.get("note", ""), "when": stamp}
        if write:
            # `judgement` is the one accessor that creates the pair entry if
            # the pair is new, which it can be: the curator may confirm a pair
            # the passes only ever disagreed about.
            gt.judgement(term, canonical)["curator"] = judgement
        if v == "same_class":
            confirmed.append((term, canonical))
        elif v == "different":
            refused.append((term, canonical))
        else:
            withdrawn.append((term, canonical, v))

    print(f"[verdicts]   {len(confirmed)} confirmed, {len(refused)} refused, "
          f"{len(withdrawn)} kept as subsumption candidates")

    if write:
        for term, canonical in refused:
            gt.record(term)["pairs"][canonical]["refused"] = {
                "by": "curator", "reason": "the contradiction queue: different classes",
                "when": stamp}
            if gt.records[term].get("to") == canonical:
                gt.records[term]["to"] = None
        for term, canonical, v in withdrawn:
            if gt.records.get(term, {}).get("to") == canonical:
                gt.records[term]["to"] = None
                gt.records[term]["retired"] = {
                    "reason": f"the contradiction queue: {v}, not the same class",
                    "when": stamp}
        gt._dirty()
        gt.save()

        # Read both back. A verdict that did not land is worse than one never
        # made: the queue has stopped offering it.
        fresh = Orchestrator().term_mapper._term_mapping
        missing = [r["term"] for r in scope
                   if fresh.peek_gate(r["term"]).get("curator", {}).get("verdict")
                   != r["verdict"]]
        lost = [t for t, c in refused if not fresh.is_refused(t, c)]
        if missing or lost:
            raise RuntimeError(
                f"[verdicts] {len(missing)} gate verdict(s) and {len(lost)} refusal(s) "
                f"did not read back from disk: {missing[:3]} {lost[:3]}")
        print(f"[verdicts] written and verified against the file on disk.")
    else:
        print("[verdicts] dry run — nothing written. Pass --write to apply.")


if __name__ == "__main__":
    main()
