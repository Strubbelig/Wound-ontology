"""One-time: fold the two EXACT curation lists into the gate. SPENT -- run
2026-09-25: 10,441 rule verdicts written, records 9,304 -> 19,318, read back
from disk, and the Blocker verified to condemn exactly the same 4,138 of the
store's 96,243 names as before. Kept for the record of what the fold did.

`METHODOLOGY_BLOCKLIST` (7,757 entries) and `WHITELIST` (2,684) are per-term
decisions about whether the ontology carries a concept. They were written into
Python source files by a cosine threshold and an LLM batch, and they carry no
verdict, no reason, no date and no author -- so nothing distinguishes an
auto-block at cos 0.921 from a decision the curator meant. Measured on
2026-09-25: the list holds `silver sulfadiazine`, `photobiomodulation`,
`tissue repair`, `bone healing`, `collagen synthesis` and `vac therapy`, and
**201 of the 1,612 families the curator had just reviewed by hand had a canonical
the blocklist already rejects** -- 167 of them approved, because nothing in front
of them said so.

Each entry lands as `gate.rule`, labelled for what it is: imported, provenance
unknown. That is not a hedge. It is the honest verdict, and it is what lets a
pass or a curator overturn an entry later without arguing with a decision nobody
can account for.

The two KEYWORD lists are not imported and never will be. A keyword matches
strings nobody has seen yet -- `Blocker` applies the 69 of them to all 96,243
store names -- so it cannot be a per-term record. Rule 29.

    python scripts/p4_fold_lists_into_gate.py [--apply]
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from config.blocklist import METHODOLOGY_BLOCKLIST                # noqa: E402
from config.whitelist import WHITELIST                            # noqa: E402
from wound_ontology.data_manager.data_manager import DataManager  # noqa: E402
from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate  # noqa: E402

WHEN = f"imported {date.today()} from the list; provenance unknown"


def main(argv: list[str]) -> int:
    apply = "--apply" in argv[1:]

    blocked = {t.strip() for t in METHODOLOGY_BLOCKLIST if t and t.strip()}
    kept    = {t.strip() for t in WHITELIST if t and t.strip()}

    # Rule 3 of the list rules: nothing is on a whitelist and a blocklist at
    # once. A term in both has no rule verdict to import -- the two literals
    # contradict each other and neither says which was meant -- so the run stops
    # rather than picking one.
    both = sorted(blocked & kept)
    if both:
        raise SystemExit(
            f"[gate] {len(both)} term(s) are on BOTH exact lists, so there is no "
            f"rule verdict to import for them: {both[:10]}. Resolve them in the "
            f"config files first.")

    print(f"[gate] {len(blocked):,} blocked, {len(kept):,} whitelisted, "
          f"{len(blocked | kept):,} rule verdicts to write")

    dm = DataManager()
    gt = TermMappingAndGate(dm, file_name="term_mapping")
    before = len(gt.records)
    already = sum(1 for t in (blocked | kept) if (gt.peek_gate(t).get("rule") or {}))
    print(f"[gate] {before:,} records now; {already:,} of the entries already "
          f"carry a rule verdict and will be left alone")

    if not apply:
        print("[gate] dry run — nothing written. Re-run with --apply.")
        return 0

    written = 0
    for verdict, terms, source in (("out", blocked, "METHODOLOGY_BLOCKLIST"),
                                   ("in", kept, "WHITELIST")):
        for term in sorted(terms):
            if (gt.peek_gate(term).get("rule") or {}):
                continue                      # never overwrite what is there
            gt.gate(term, rule={"verdict": verdict, "by": source, "when": WHEN})
            written += 1
    gt.save()

    # Read it back off the file, the way the fold of the pass caches did: a
    # migration that reports success from memory has verified nothing.
    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    out, kept_v = check.gated("out"), check.gated("in")
    missing = [t for t in blocked if t not in out] + [t for t in kept if t not in kept_v]
    if missing:
        raise RuntimeError(
            f"[gate] {len(missing)} entr(ies) did not read back: {missing[:5]}")
    print(f"[gate] {written:,} rule verdicts written; records {before:,} -> "
          f"{len(check.records):,}")
    print(f"[gate] read back from disk: {len(out):,} out, {len(kept_v):,} in, "
          f"{len(check.gate_disagreements()):,} disagreement(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
