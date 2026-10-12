"""Gate pass 1: a term that IS a term already decided inherits its verdict.

For each undecided term, embed it and compare with the terms the gate already
answers `out` and the terms it answers `in`. The nearer side wins -- but only
when it wins by a margin AND the winning similarity clears an absolute floor,
because without the floor this is not a scope judgement at all.

Measured on a 3,000-term sample of the 90,358 undecided store names:

    >= 0.95     4.8%      nearest neighbour is the same term in another
                          inflection: `Gram-negative infections` ~
                          `gram-negative infection`, `transcriptomic analyses` ~
                          `transcriptomic analysis`
    0.90-0.95   6.6%
    0.85-0.90   9.9%
    < 0.85     78.7%      `aldehyde dehydrogenase 2` ~ `azole resistance` (0.430),
                          `miR-206` ~ `microrna` (0.479), `mg/dl` ~ `grade`
                          (0.492), `topical esmolol` ~ `topical prp` (0.469)

A margin-only rule decided all of them: 65% out, 25% in, 10% too close --
~58,700 store names marked out of scope on coin flips, and under rule 40 one
pass alone decides, so all 58,700 would have changed what `Blocker` does with
nothing left for pass 2 to weigh in on. The old cascade was cruder and had the
thing this lacked: an absolute floor.

So the floor is 0.95 and what pass 1 claims at that similarity is narrow and
true -- this string is another spelling of one already decided, and it inherits
that decision. `near` records which. Everything below stays undecided, which is
an answer, and it is pass 2's to make.

What this replaces. `review_susp_entities` did the same cosine comparison and
then EDITED `config/blocklist.py`: `>= 0.92` blocked, `< 0.40` whitelisted, no
score kept, no nearest neighbour kept, no date, no author. That is why the list
holds `silver sulfadiazine` with nothing to say whether a person or a threshold
put it there. Here the score and the neighbour go on the record with the verdict,
so the next reader can see how thin the call was.

    python scripts/p4_gate_pass1.py [--apply] [--floor 0.95] [--margin 0.03] [--limit N]
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str]) -> int:
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity

    apply = "--apply" in argv[1:]
    margin = float(_opt(argv, "--margin", "0.03"))
    floor = float(_opt(argv, "--floor", "0.95"))
    limit = int(_opt(argv, "--limit", "0"))

    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    store = p.store

    from collections import Counter
    freq: Counter = Counter()
    from wound_ontology.store.concept_store import records_of
    for _, ents in store.view(mapped=False):
        for name in ents:
            freq[name] += 1

    # Only AUTHORED decisions are inherited: a curator's or the model's, each
    # with a reason. On 2026-09-28, 1,275 of the first run's 1,598 verdicts
    # had copied an imported list entry with no author ("provenance unknown")
    # onto a neighbour -- the unaudited amplification the `unaudited` queue of
    # pass 2 exists to undo, done again one hop further out.
    def authored(pool: dict[str, str]) -> list[str]:
        # nor an inherited one: a copy of a copy is two hops from anyone
        # who looked at the term.
        return sorted(t for t, src in pool.items() if src not in ("rule", "pass1"))

    out_terms = authored(gt.gated("out"))
    in_terms = authored(gt.gated("in"))
    undecided = sorted((t for t in freq if not gt.gate_verdict(t)[0]),
                       key=lambda t: (-freq[t], t.lower()))
    if limit:
        undecided = undecided[:limit]
    print(f"[pass1] {len(undecided):,} undecided store names, "
          f"{len(out_terms):,} known out, {len(in_terms):,} known in, "
          f"floor {floor}, margin {margin}")
    if not undecided:
        return 0

    emb = p._ensure_embedder()
    # Through the vector store: ~88,000 of these terms are already embedded,
    # and embedding them again is most of an hour on a CPU.
    vectors = p.term_mapper._embeddings_for
    print("[pass1] embedding the two decided sides…", flush=True)
    o = np.asarray(vectors(out_terms, emb))
    i = np.asarray(vectors(in_terms, emb))

    # Chunked, because the full matrix is not a thing that fits: 77,317 x 10,441
    # float32 is 3.2 GB, and the machine would swap or the process would die
    # partway through with a third of the verdicts written and no way to tell
    # which third.
    CHUNK = 2000
    when = f"{date.today()} sapbert nearest-neighbour"
    tally = {"out": 0, "in": 0, "too close": 0, "below the floor": 0}
    for start in range(0, len(undecided), CHUNK):
        block = undecided[start:start + CHUNK]
        u = np.asarray(vectors(block, emb))
        so, si = cosine_similarity(u, o), cosine_similarity(u, i)
        for k, term in enumerate(block):
            jo, ji = int(so[k].argmax()), int(si[k].argmax())
            co, ci = float(so[k][jo]), float(si[k][ji])
            if max(co, ci) < floor:
                tally["below the floor"] += 1
                continue
            if abs(co - ci) < margin:
                tally["too close"] += 1
                continue
            verdict = "out" if co > ci else "in"
            tally[verdict] += 1
            if apply:
                gt.gate(term, pass1={"verdict": verdict,
                                     "score": round(max(co, ci), 4),
                                     "margin": round(abs(co - ci), 4),
                                     "near": (out_terms[jo] if verdict == "out"
                                              else in_terms[ji]),
                                     "reason": "inherited from a near-identical "
                                               "term already decided",
                                     "when": when})
        print(f"[pass1]   {min(start + CHUNK, len(undecided)):>6,}/{len(undecided):,}"
              f"  out {tally['out']:,}  in {tally['in']:,}  "
              f"too close {tally['too close']:,}  "
              f"below the floor {tally['below the floor']:,}", flush=True)
    print(f"[pass1] {tally['out']:,} out, {tally['in']:,} in; no verdict for "
          f"{tally['too close']:,} too close to call and "
          f"{tally['below the floor']:,} below the {floor} floor")
    if not apply:
        print("[pass1] dry run — nothing written. Re-run with --apply.")
        return 0
    gt.save()

    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    landed = sum(1 for t in undecided if (check.peek_gate(t).get("pass1") or {}))
    expected = tally["out"] + tally["in"]
    if landed != expected:
        raise RuntimeError(f"[pass1] wrote {expected:,} verdicts but {landed:,} "
                           f"read back from disk")
    print(f"[pass1] {landed:,} verdicts read back from disk; "
          f"{len(check.gate_disagreements()):,} gate disagreement(s) now")
    return 0


def _opt(argv: list[str], name: str, default: str) -> str:
    return argv[argv.index(name) + 1] if name in argv else default


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
