"""Apply the spellings the curator typed into the Scope Rulings page's note box.

    python scripts/apply_scope_notes.py <decisions dir> [--write]

The page's note box said "why, or the spelling you want", and 30 of the 722
rulings of 2026-09-28 carry a spelling: `miRNA` -> `microRNA`, `Treg` ->
`Regulatory T-cell`, `bone healing` -> `bone healing process`. Each becomes a
curator mapping term -> that name (or onto the name's own preferred term, if
it has one), recorded as a `same_class` judgement. Terms already mapped onto
the term follow it, so the mapping stays one hop; a mapping that would point
a term at itself is cleared instead (the reversal case, `microRNA -> miRNA`).

Skipped, and printed: a note that is the term's current spelling already, and
a term the curator mapped elsewhere earlier the same day (the naming review),
where the two rulings disagree and a person has to choose.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

#: A typo in a note, corrected to the term the curator plainly meant.
TYPOS = {"immunesuppression": "Immunosuppression"}


def main(argv: list[str]) -> int:
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    write = "--write" in argv
    notes = []
    for f in sorted(Path(argv[1]).glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        d = d.get("data", d)
        if (d.get("note") or "").strip():
            notes.append((d["term"], d["note"].strip()))
    gt = TermMappingAndGate(DataManager(), file_name="term_mapping")
    when = datetime.now().isoformat(timespec="seconds")

    plan, skipped, reverse = [], [], []
    respell: dict[str, str] = {}
    for term, note in notes:
        note = TYPOS.get(note, note)
        cur = gt.resolve(term)
        if note == cur:
            skipped.append((term, note, "already the current spelling"))
            continue
        if gt.is_alias(note) and gt.resolve(note) == cur:
            respell[cur] = note                  # pass 0 spelled it the other way round
            continue
        if gt.data.get(gt.resolve(note)) == cur:
            reverse.append((cur, gt.resolve(note)))   # the note was mapped onto the term
            continue
        target = gt.data.get(gt.resolve(note)) or gt.resolve(note)
        standing = gt.data.get(cur)
        curator = (gt.peek(cur, standing).get("curator") or {}).get("verdict") if standing else None
        if standing and standing != target and curator == "same_class":
            skipped.append((term, note, f"mapped to {standing!r} by the curator earlier today"))
            continue
        plan.append((cur, target, None))
    for cur, target, old in plan:
        print(f"[notes]   {cur!r} -> {target!r}")
    for cur, note in respell.items():
        print(f"[notes]   {cur!r} respelled {note!r} (reverses a pass-0 spelling)")
    for cur, note in reverse:
        print(f"[notes]   {cur!r} -> {note!r} (reverses the mapping {note!r} -> {cur!r})")
    for s in skipped:
        print(f"[notes]   skipped {s[0]!r} (note {s[1]!r}): {s[2]}")
    if not write:
        print("[notes] dry run -- nothing written. Pass --write.")
        return 0

    latest = sorted((ROOT / "data" / "cache").glob("term_mapping_*.json"))[-1]
    shutil.copy2(latest, ROOT / "data" / "backup" / f"term_mapping_before_scope_notes_{date.today()}.json")
    reason = "curator 2026-09-28: spelling typed in the scope review"
    if respell:
        gt.apply_renames(respell, by=reason)
    for cur, note in reverse:
        # The typed spelling is the cluster's name. Without saying so, the
        # next rebuild re-proposes `microRNA -> miRNA` and wins the frequency
        # vote (it did, 2026-09-28); until 2026-10-24 a lock on the backward
        # pair said it, now the name decision does.
        gt.decide_name(note, [cur], by="curator", reason=reason, when=when)
        gt.records[note]["to"] = None
        plan.append((cur, note, None))
    for cur, target, old in plan:
        rec = gt.record(cur)
        gt.judgement(cur, target).pop("refused", None)
        gt.judge(cur, target, curator={"verdict": "same_class", "reason": reason, "when": when})
        rec.update({"to": target, "confidence": 1.0, "method": "curator"})
        rec.pop("retired", None)
        for other, r in gt.records.items():
            if r.get("to") == cur and other != cur:
                r["to"] = None if other == target else target
    # A target that was itself mapped onto the term it now receives
    # (`microRNA -> miRNA` while `miRNA -> microRNA`) is cleared above; make
    # sure no target of this run is left mapped at all.
    for _, target, _ in plan:
        if target and gt.records.get(target, {}).get("to"):
            gt.records[target]["to"] = None
    gt._dirty()
    gt.save()
    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    wrong = [(c, t) for c, t, _ in plan if check.data.get(c) != t]
    wrong += [(c, n) for c, n in respell.items() if check.resolve(c) != n]
    chains = [t for _, t, _ in plan if t and check.data.get(t)]
    if wrong or chains:
        raise RuntimeError(f"[notes] did not read back: {wrong[:5]}; targets still mapped: {chains[:5]}")
    print(f"[notes] written and read back: {len(plan)} mapping(s), {len(respell)} respelling(s), "
          f"{len(skipped)} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
