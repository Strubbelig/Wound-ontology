#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Apply the Contradiction Queue's verdicts to the record.

    python scripts/apply_contradiction_verdicts.py <dir-of-decision-json> \
        [--queue <the queue payload the page was built from>] [--write]

The page is https://claude.ai/artifact/9VpYXEKfmQ1zxmgEfidLG4 and it holds two
queues, which land in two different places:

  SCOPE TIE-BREAKS  a `gate_contested` record whose one source answered both
                    `in` and `out` about two spellings of one term, so it was
                    removed and the term has no verdict at all. The curator's
                    answer is written as `gate(curator=...)`, which outranks
                    every pass (rule 40), and the `gate_contested` block stays
                    where it is -- it is the evidence the question was asked.

  MAPPING PAIRS     pass 1 and pass 2 judged one (term, canonical) pair
                    differently, so the adjudicator withdrew the mapping.
                    `same_class` puts it back -- the verdict alone would
                    leave the pair confirmed and the mapping gone;
                    `narrower`/`broader` say the two are related but not one
                    class, so the mapping is withdrawn and the pair is kept as
                    a subsumption candidate; `different` refuses the pair,
                    which is what stops the next build proposing it again
                    (rule 37); and `reverse` says the two ARE one class but
                    named the wrong way round, which is two writes, not one --
                    the inverse entry AND a refusal on the original pair,
                    because without the refusal the next build proposes the
                    direction the curator just rejected and the cache approves
                    it from memory.

Dry by default. Nothing is written without `--write`, and after writing it
reads both back off disk and raises if a verdict did not land -- a decision
that silently failed to apply is worse than one never made, because the queue
will not show it again.
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

SCOPE = {"in", "out", "unsure"}
PAIR = {"same_class", "narrower", "broader", "reverse", "different"}


def _load(folder: Path) -> list[dict]:
    """Every decision document the Artifact store handed back.

    The row id is the DOCUMENT id, which the store carries as the file name
    and not as a field, so it is stamped on here. It is what `_with_queue`
    matches a decision to the question it answers.
    """
    out = []
    for path in sorted(folder.rglob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        rows = body if isinstance(body, list) else [body]
        for row in rows:
            if isinstance(row, dict) and row.get("verdict"):
                row.setdefault("id", path.stem)
                out.append(row)
    return out


def _with_queue(rows: list[dict], payload: Path) -> list[dict]:
    """Fill each decision's `canonical` from the queue it was asked about.

    The page stores what the CURATOR said -- term, verdict, note -- and not
    the question, so a pair decision arrives without its canonical. Reading
    it back off the live mapping is not enough: most of these pairs are ones
    the adjudicator WITHDREW, so the term has no live `to` at all, and 634 of
    the 695 pair decisions resolved to nothing on the first run.

    The queue payload the page was built from has it, keyed by the same row
    id. The term is checked as well as read: the ids are positional, so a
    payload regenerated against a different queue would line every decision
    up against the wrong question, and that must stop the run rather than
    write 695 wrong verdicts.
    """
    body = json.loads(payload.read_text(encoding="utf-8"))
    asked = {r["id"]: r for group in body.values() for r in group if r.get("id")}
    missing, mismatched = [], []
    for row in rows:
        question = asked.get(row.get("id"))
        if question is None:
            missing.append(row.get("id"))
            continue
        if question.get("term") != row.get("term"):
            mismatched.append((row.get("id"), question.get("term"), row.get("term")))
            continue
        row.setdefault("canonical", question.get("canonical"))
    if mismatched:
        raise SystemExit(
            f"[verdicts] {len(mismatched)} decision(s) answer a DIFFERENT term "
            f"than the queue asked about -- the payload is not the one the page "
            f"was built from, and applying it would file every verdict against "
            f"the wrong pair: {mismatched[:3]}")
    if missing:
        print(f"[verdicts] {len(missing)} decision(s) have no row in the queue "
              f"payload: {missing[:5]}")
    return rows


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


def record_curator(pair: dict, judgement: dict) -> None:
    """Write the curator's verdict on a pair, keeping the one it supersedes.

    660 of the 695 pairs in the 2026-09-27 queue already carried a curator
    verdict, from the phone review of 2026-09-25 and in that review's own
    vocabulary -- `kept`, `refused`, `repointed`. 79 said `refused` where the
    queue now says `reverse`, and 48 said `refused` where it now says
    `same_class`: the same person looking again, with the two passes'
    reasoning in front of them this time. The new verdict is the standing
    one. The old one is still something a person decided, so it moves to
    `curator_history` instead of being overwritten out of existence (rule
    33). Precedence does not change -- `curator` is what the gate and the
    mapping read.
    """
    standing = pair.get("curator")
    if standing and standing != judgement:
        pair.setdefault("curator_history", []).append(standing)
    pair["curator"] = judgement


def confirmation_clashes(confirmed, standing) -> dict[tuple[str, str], str]:
    """Which confirmations must NOT be written, and why. `{(term, canonical): why}`.

    A confirmation is not a note, it is a mapping. These pairs are in the
    queue precisely because the two passes disagreed and the adjudicator
    WITHDREW the mapping, so `same_class` has to put it back -- writing only
    the verdict leaves the pair confirmed and the mapping gone. On the first
    run of the 2026-09-27 queue that is what happened to 135 of the 499
    confirmations.

    Two confirmations cannot be written:

    * the pair names one term twice, so there is no mapping to make;
    * the term already maps to a THIRD term, live. `diabetes mellitus
      patient` maps to `diabetic patient` and the queue confirmed it against
      `patients with diabetes`; both may well be one class, but which of them
      is the canonical is a question nobody in this queue was asked.
    """
    out: dict[tuple[str, str], str] = {}
    for term, canonical in confirmed:
        if term == canonical:
            out[(term, canonical)] = "the pair names one term twice"
            continue
        already = standing(term)
        if already not in (None, canonical):
            out[(term, canonical)] = f"it already maps to {already!r}"
    return out


def cycles_closed(added, cleared, standing) -> set[tuple[str, str]]:
    """Which of `added` would close a cycle. `{(source, target)}`.

    A mapping has to bottom out in a name. `A -> B -> A` bottoms out nowhere:
    neither spelling is the canonical, and applying the mapping either loops
    or picks whichever the walk reached first.

    The other clash checks ask whether the SOURCE of a new edge is spoken
    for. That misses the target: `orthopedics -> orthopedic` was standing,
    the queue confirmed `orthopedic -> orthopedics`, the source was free, and
    writing it closed a two-cycle. **26 of them, on the 2026-09-27 queue.**

    `added` is every edge the batch will write, `cleared` every term whose
    arrow it will remove, and `standing(term)` what a term maps to now --
    together they are the graph as it will be, which is the only graph worth
    asking the question of.
    """
    ahead = dict(added)

    def target(term):
        if term in ahead:
            return ahead[term]
        return None if term in cleared else standing(term)

    out = set()
    for source, first in added:
        seen, at = {source}, first
        while at is not None and at not in seen:
            seen.add(at)
            at = target(at)
        if at == source:
            out.add((source, first))
    return out


def reversal_clashes(reversed_, standing) -> dict[tuple[str, str], str]:
    """Which reversals must NOT be written, and why. `{(term, canonical): why}`.

    A reverse points the canonical at the term, so a canonical that is
    already spoken for cannot take it. Two ways that happens:

    * it maps somewhere else ALREADY -- writing would overwrite a live
      decision that nobody in this queue was asked about;
    * two verdicts in THIS batch both claim it. That needs its own check,
      because `standing` reads the mapping as it was before the batch, where
      neither has written yet. On the 2026-09-27 queue two pairs did exactly
      this -- `inflammation level` and `inflammatory level` both reversing
      onto `levels of inflammation`, `near-infrared radiation` and
      `near-infrared light` both onto `near-infrared`. Neither canonical was
      mapped beforehand, both passed, and the second write replaced the
      first: of 179 reversals 177 landed. The read-back caught the 2; the
      point of this check is that the read-back should have nothing to catch.

    Neither claim wins a collision. Which of two spellings a canonical should
    point at is a question for the curator, not for whichever verdict the
    file system handed over last.
    """
    out: dict[tuple[str, str], str] = {}
    for term, canonical in reversed_:
        already = standing(canonical)
        if already not in (None, term):
            out[(term, canonical)] = f"it already maps to {already!r}"
    claimed: dict[str, list[str]] = defaultdict(list)
    for term, canonical in reversed_:
        claimed[canonical].append(term)
    for canonical, terms in claimed.items():
        if len(terms) > 1:
            named = ", ".join(repr(t) for t in sorted(terms))
            for term in terms:
                out[(term, canonical)] = (
                    f"{len(terms)} verdicts claim it ({named}) and a canonical "
                    f"can only point at one term")
    return out


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    folder = Path(sys.argv[1])
    write = "--write" in sys.argv
    rows = _load(folder)
    if not rows:
        raise SystemExit(f"[verdicts] no decisions found under {folder}")
    if "--queue" in sys.argv:
        rows = _with_queue(rows, Path(sys.argv[sys.argv.index("--queue") + 1]))

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
    refused, withdrawn, confirmed, reversed_ = [], [], [], []
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
            record_curator(gt.judgement(term, canonical), judgement)
        if v == "same_class":
            confirmed.append((term, canonical))
        elif v == "different":
            refused.append((term, canonical))
        elif v == "reverse":
            reversed_.append((term, canonical))
        else:
            withdrawn.append((term, canonical, v))

    print(f"[verdicts]   {len(confirmed)} confirmed, {len(refused)} refused, "
          f"{len(withdrawn)} kept as subsumption candidates, "
          f"{len(reversed_)} reversed")

    def _standing(term: str) -> str | None:
        return (gt.records.get(term) or {}).get("to")

    held_back = confirmation_clashes(confirmed, _standing)
    for (term, canonical), why in sorted(held_back.items()):
        print(f"[verdicts]   CLASH confirming {term!r} -> {canonical!r}: "
              f"{why}; not written")
    confirmed = [p for p in confirmed if p not in held_back]

    clashing = reversal_clashes(reversed_, _standing)
    for (term, canonical), why in sorted(clashing.items()):
        print(f"[verdicts]   CLASH reversing {term!r} onto {canonical!r}: "
              f"{why}; not written")
    reversed_ = [p for p in reversed_ if p not in clashing]

    # Everything the batch will do to the arrows, asked of the graph as it
    # will BE rather than as it is. An edge that closes a cycle is one more
    # thing a canonical cannot be, and it goes back to the curator as the
    # question it really is: which of these two spellings is the name?
    cleared = {t for t, c in refused if _standing(t) == c}
    cleared |= {t for t, c in reversed_ if _standing(t) == c}
    cleared |= {t for t, c, _ in withdrawn if _standing(t) == c}
    added = [(t, c) for t, c in confirmed] + [(c, t) for t, c in reversed_]
    looping = cycles_closed(added, cleared, _standing)
    for source, target_ in sorted(looping):
        print(f"[verdicts]   CLASH {source!r} -> {target_!r}: it would close a cycle, "
              f"and a mapping has to bottom out in a name; not written")
    confirmed = [(t, c) for t, c in confirmed if (t, c) not in looping]
    reversed_ = [(t, c) for t, c in reversed_ if (c, t) not in looping]
    for term, canonical in reversed_:
        print(f"[verdicts]   reverse {term!r} -> {canonical!r}  becomes  "
              f"{canonical!r} -> {term!r}")

    if write:
        for term, canonical in confirmed:
            # The mapping, not just the verdict. `retired` is the status the
            # adjudicator left behind when it withdrew the pair; the curator
            # has now overruled that, and why it was withdrawn is still on
            # the pair, in `pass1` and `pass2`.
            rec = gt.record(term)
            rec["to"] = canonical
            rec["method"] = "curator"
            rec["confidence"] = 1.0
            rec.pop("retired", None)
        for term, canonical in refused:
            gt.record(term)["pairs"][canonical]["refused"] = {
                "by": "curator", "reason": "the contradiction queue: different classes",
                "when": stamp}
            if gt.records[term].get("to") == canonical:
                gt.records[term]["to"] = None
        for term, canonical in reversed_:
            # Both writes, together. The inverse alone leaves the original
            # direction free to come back on the next build.
            gt.record(term)["pairs"].setdefault(canonical, {})["refused"] = {
                "by": "curator",
                "reason": "the contradiction queue: reversed, the canonical is the term",
                "when": stamp}
            if gt.records[term].get("to") == canonical:
                gt.records[term]["to"] = None
            inverse = gt.record(canonical)
            inverse["to"] = term
            inverse["method"] = "curator"
            inverse["confidence"] = 1.0
            # As for a confirmation: the entry is live again, so a `retired`
            # stamp left from an earlier withdrawal is false. 51 live entries
            # carried one after the 2026-09-27 queues.
            inverse.pop("retired", None)
            record_curator(
                inverse.setdefault("pairs", {}).setdefault(term, {}),
                {"verdict": "same_class",
                 "reason": "the contradiction queue: reversed from the other direction",
                 "when": stamp})
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
        # Through the alias: a term renamed since the queue was built (pass 0,
        # rule 51) had its verdict written to the current spelling, and
        # reading the old string reported 27 landed verdicts as lost
        # (2026-09-28). Two rows that now name ONE concept with opposite
        # rulings are a real conflict, reported separately.
        by_name: dict[str, set[str]] = {}
        for r in scope:
            by_name.setdefault(fresh.resolve(r["term"]), set()).add(r["verdict"])
        clashes = sorted(n for n, vs in by_name.items() if len(vs) > 1)
        missing = [r["term"] for r in scope
                   if fresh.resolve(r["term"]) not in clashes
                   and fresh.peek_gate(fresh.resolve(r["term"])).get("curator", {}).get("verdict")
                   != r["verdict"]]
        if clashes:
            print(f"[verdicts] {len(clashes)} concept(s) got opposite rulings under two "
                  f"old spellings; the later write stands: "
                  + ", ".join(f"{n!r} now {fresh.peek_gate(n).get('curator', {}).get('verdict')}"
                              for n in clashes))
        lost = [t for t, c in refused if not fresh.is_refused(t, c)]
        unmapped = [f"{t} -> {c}" for t, c in confirmed
                    if fresh.records.get(t, {}).get("to") != c
                    or fresh.records.get(t, {}).get("retired")]
        unmapped += [f"{t} -x-> {c}" for t, c, _ in withdrawn
                     if fresh.records.get(t, {}).get("to") == c]
        unflipped = [f"{c} -> {t}" for t, c in reversed_
                     if fresh.records.get(c, {}).get("to") != t
                     or not fresh.is_refused(t, c)]
        if missing or lost or unflipped or unmapped:
            raise RuntimeError(
                f"[verdicts] {len(missing)} gate verdict(s), {len(lost)} refusal(s), "
                f"{len(unflipped)} reversal(s) and {len(unmapped)} confirmation(s) "
                f"did not read back from disk: "
                f"{missing[:3]} {lost[:3]} {unflipped[:3]} {unmapped[:3]}")
        print(f"[verdicts] written and verified against the file on disk.")
        if scope:
            # The two exact lists are a VIEW of the gate (rule 40.7). A scope
            # verdict written here without re-exporting left `whitelist.py`
            # one term behind the record on 2026-09-27, and only
            # test_the_live_files_and_the_live_gate_agree noticed.
            Orchestrator().export_gate_lists()
    else:
        print("[verdicts] dry run — nothing written. Pass --write to apply.")


if __name__ == "__main__":
    main()
