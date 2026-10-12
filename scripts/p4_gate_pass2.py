"""Gate pass 2: the model judges scope, one explicit verdict per term.

Two things it does that `review_susp_entities` did not.

**Silence is not a decision.** The old path asked for the out-of-scope names
only and wrote every term the model did not mention to `WHITELIST`
(`llm_kept = [e for e in queue if e not in processed]`), so a short answer for a
batch of 50 was 50 permanent decisions nobody made. `gate_scope_batch` asks for
a verdict per term; a term missing from the answer gets nothing, is counted, and
is asked again on the next run.

**It writes to the record.** Verdict, reason and date land on `gate.pass2`, so a
curator can see what the model thought and why, and disagree with it by name.

`--only blocked` re-asks the terms the gate currently answers `out`: the list was
written by a threshold and an LLM batch with no provenance, and it holds
`silver sulfadiazine`, `photobiomodulation`, `tissue repair` and `vac therapy`.
Asking again is how those surface as disagreements instead of staying invisible.

    python scripts/p4_gate_pass2.py [--apply] [--only blocked|undecided|all]
                                    [--limit N] [--min-mentions N]
                                    [--batch 40] [--concurrency 8]
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))


def _opt(argv: list[str], name: str, default: str) -> str:
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv: list[str]) -> int:
    apply = "--apply" in argv[1:]
    only = _opt(argv, "--only", "undecided")
    limit = int(_opt(argv, "--limit", "0"))
    min_mentions = int(_opt(argv, "--min-mentions", "1"))
    batch_size = int(_opt(argv, "--batch", "25"))
    concurrency = int(_opt(argv, "--concurrency", "8"))
    if only not in ("blocked", "undecided", "all", "unaudited"):
        raise SystemExit(f"[pass2] --only {only!r}: expected "
                         f"blocked|undecided|all|unaudited")

    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator()
    if not p.llm.has_credentials:
        raise SystemExit("[pass2] no OPENROUTER_API_KEY — the model cannot be asked, "
                         "and a scope pass that guesses is the thing being removed.")
    gt = p.term_mapper._term_mapping

    # Rejected terms INCLUDED, not `records_of`: the effective view hides what
    # a previous blocklist run rejected, and those are exactly the terms worth
    # re-asking -- `silver sulfadiazine` is not going to argue for itself from
    # behind the verdict that removed it. Unmapped, because the gate is asked
    # about terms as they are written (rule 51).
    freq: Counter = Counter()
    attrs: dict[str, list[str]] = {}
    for _, ents in p.store.view(mapped=False, include_rejected=True):
        for name, cells in ents.items():
            freq[name] += 1
            if name not in attrs and isinstance(cells, dict):
                attrs[name] = [a for a, v in cells.items() if v == 1.0][:3]

    from wound_ontology.llm.category_vocab import declared_category
    from wound_ontology.utils.label_match import fold as _fold
    curated = {_fold(str(l)) for l in p.ontology_labels()}

    def wanted(term: str) -> bool:
        if freq[term] < min_mentions:
            return False
        if _fold(term) in curated:
            # A class WONT or MILD asserts is in scope by the curator's own
            # hand (rule 26); asked anyway on 2026-09-28, the model put
            # `Planimetry` and `Tissue repair process` out.
            return False
        if declared_category(term) is not None:
            # A BFO category is declared, never gated (rules 20, 22): asked on
            # 2026-09-28, the model called `process` and `material entity`
            # "generic, out", which the view read as removing every typing.
            return False
        if (gt.peek_gate(term).get("pass2") or {}):
            return False                      # already answered; --readjudicate is not this
        verdict, source = gt.gate_verdict(term)
        if only == "blocked":
            # what the BLOCKER currently drops, not what the gate says `out`.
            # Only 150 of the 4,138 blocked store names are blocked by the exact
            # list; 3,988 are blocked by one of the 69 KEYWORDS, and that is
            # where the damage is -- the `pain` keyword alone takes 429 names,
            # `wound pain` and `Severe distal pain` among them, while WONT
            # defines `painful` as a degree of wound pain. A keyword is a rule,
            # so it is not in the gate and cannot be argued with there; a pass2
            # verdict of `in` is how a term gets out from under one.
            return p.cleaner.blocker.is_blocked(term)
        if only == "undecided":
            return not verdict and not p.cleaner.blocker.is_blocked(term)
        return True

    if only == "unaudited":
        # The CONCEPTS excluded on an imported list entry and nothing else. The
        # concept-level gate propagates a verdict to every spelling of its
        # concept, so these 277 spread a decision with no author and no reason
        # across 448 store spellings -- `fibroblast`, `peripheral artery
        # disease`, `inflammatory response`, `time to healing` among them.
        # Judging the canonical replaces unaudited amplification with judged
        # amplification, and it is 12 model calls rather than 3,600.
        by_concept: dict[str, int] = {}
        for term in freq:
            canonical = gt.data.get(term) or term
            by_concept[canonical] = by_concept.get(canonical, 0) + freq[term]
        queue = sorted(
            (c for c, m in by_concept.items()
             if gt.effective_gate_verdict(c) == ("out", "rule")
             and not (gt.peek_gate(c).get("pass2") or {})
             and m >= min_mentions),
            key=lambda c: (-by_concept[c], c.lower()))
        for c in queue:
            freq.setdefault(c, by_concept[c])
    else:
        queue = sorted((t for t in freq if wanted(t)),
                       key=lambda t: (-freq[t], t.lower()))
    if limit:
        queue = queue[:limit]
    print(f"[pass2] {len(queue):,} term(s) to ask ({only}, >= {min_mentions} abstract"
          f"{'s' if min_mentions != 1 else ''}), batches of {batch_size}, "
          f"{concurrency} at a time")
    if not queue:
        return 0
    print(f"[pass2] ~{(len(queue) + batch_size - 1) // batch_size:,} model call(s)")
    if not apply:
        print("[pass2] dry run — nothing asked, nothing written. Re-run with --apply.")
        return 0

    batches = [queue[i:i + batch_size] for i in range(0, len(queue), batch_size)]
    when = f"{date.today()} llm scope pass"
    answered: dict[str, tuple[str, str]] = {}
    silent: list[str] = []
    unplaced: list[str] = []
    failed = 0

    async def run() -> None:
        nonlocal failed
        sem = asyncio.Semaphore(concurrency)
        done = 0

        async def one(batch: list[str]) -> None:
            nonlocal done, failed
            async with sem:
                cand = [(t, freq[t], attrs.get(t, [])) for t in batch]
                try:
                    got, stray = await p.llm.gate_scope_batch(cand)
                except Exception as e:                       # noqa: BLE001
                    failed += 1
                    print(f"[pass2]   batch failed, its {len(batch)} term(s) stay "
                          f"unjudged: {type(e).__name__}: {e}", flush=True)
                    return
                answered.update(got)
                # Onto the record as they arrive, and to disk every 50 batches:
                # a run of thousands of calls that saves only at the end banks
                # nothing when it dies, as the 2026-09-26 adjudication did.
                for term, (verdict, reason) in got.items():
                    gt.gate(term, pass2={"verdict": verdict, "reason": reason[:300],
                                         "when": when})
                silent.extend(t for t in batch if t not in got)
                if stray:
                    unplaced.extend(stray)
                done += 1
                if done % 50 == 0:
                    gt.save()
                    print(f"[pass2]   checkpoint: {len(answered):,} verdicts on disk",
                          flush=True)
                if done % 10 == 0 or done == len(batches):
                    print(f"[pass2]   {done}/{len(batches)} batches, "
                          f"{len(answered):,} answered, {len(silent):,} unanswered, "
                          f"{failed} batch(es) failed", flush=True)

        await asyncio.gather(*(one(b) for b in batches))

    p._run_sync(run())

    gt.save()

    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    landed = sum(1 for t in answered if (check.peek_gate(t).get("pass2") or {}))
    if landed != len(answered):
        raise RuntimeError(f"[pass2] wrote {len(answered):,} verdicts but {landed:,} "
                           f"read back from disk")
    tally = Counter(v for v, _ in answered.values())
    print(f"[pass2] {landed:,} verdicts read back from disk — "
          f"{tally.get('in', 0):,} in, {tally.get('out', 0):,} out")
    print(f"[pass2] {len(silent):,} term(s) the model did not answer — no verdict "
          f"written, they stay in the queue")
    if unplaced:
        print(f"[pass2] {len(unplaced):,} answer(s) named something that was not asked "
              f"and were dropped: {unplaced[:5]}")
    if failed:
        print(f"[pass2] {failed} batch(es) failed outright; re-run to ask them again")
    print(f"[pass2] {len(check.gate_disagreements()):,} gate disagreement(s) now")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
