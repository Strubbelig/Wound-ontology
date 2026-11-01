"""Apply ONLY rule 4 of the canonical policy: a WONT/MILD label is never mapped away.

    python -u scripts/apply_label_restore.py [--write]

Found 2026-10-01 while asking why placement `same` answers had slipped the
mapping: 18 labels pointed at a store spelling (`Wound treatment process ->
wound therapy`). `scripts/p4_canonical_policy.py --apply` would fix them but
would also apply rules 1-3's other pending changes (5 guard refusals, 1
re-spelling) that no one has decided on, so this applies rule 4's entries alone.

Dry by default. With `--write`: the term dict is backed up, the labels are
unmapped (`retired`, reason on record) and the store spelling plus everything
mapped onto it is mapped onto the label (`method: ontology_label`); then a
fresh Orchestrator reads the file back and every entry is checked.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
from wound_ontology.orchestrator import Orchestrator  # noqa: E402


def main(argv: list[str]) -> int:
    p = Orchestrator()
    rep = p.term_mapper.enforce_canonical_policy(
        label_spellings=p.ontology_label_spellings(),
        accept_mapping=p._category_compatible_mapping(p.ontology_labels()),
        dry_run=True)
    restored, moves = rep["restored_entries"], rep["moved_entries"]
    print(f"[labels] {len(restored)} label(s) to turn round, {len(moves)} entr(ies) onto the label; "
          f"held for the curator: {rep['held_entries']}; guard-refused: {rep['unmapped_entries']}")
    if rep["unmapped_entries"]:
        raise SystemExit("[labels] a turned-round claim is refused by the guard; decide it first")
    if "--write" not in argv:
        print("[labels] dry run; --write to apply")
        return 0

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_label_restore_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[labels] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    gt = p.term_mapper._term_mapping
    gt.retire(*restored, reason="rule 36: the ontology's own label is the canonical, never mapped away "
                                "(rule 4 of the canonical policy, 2026-10-01)")
    skipped = gt.add_batch(moves, {t: {"confidence": 1.0, "method": "ontology_label"} for t in moves})
    if skipped:
        raise SystemExit(f"[labels] {len(skipped)} move(s) stand refused and were not written: {skipped}")

    data = Orchestrator().term_mapper._term_mapping.data
    wrong = [l for l in restored if data.get(l)] + [t for t, l in moves.items() if data.get(t) != l]
    if wrong:
        raise SystemExit(f"[labels] read back: {len(wrong)} entr(ies) did not land: {wrong}")
    print(f"[labels] written and read back: {len(restored)} labels are canonical again, "
          f"{len(moves)} entries map onto them")
    for t, l in sorted(moves.items(), key=lambda x: x[1]):
        print(f"[labels]     {t!r} -> {l!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
