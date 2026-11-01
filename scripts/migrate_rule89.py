"""Write the term dict in the form of rule 89, with every judgement dated.

    python -u scripts/migrate_rule89.py            # dry: translate and compare, write nothing
    python -u scripts/migrate_rule89.py --write    # back up, write, read back, compare again

Source: the newest term_mapping file before rule 89 (`SOURCE`). The translation
is `rule89_migration.migrate`, dated by `rule89_dryrun.Dating` (the saved
states and the run logs), with the placement rows of 2026-10-01 and the
author's confirmations of the dry run (unterschiede.csv, unterschiede_2.csv).

The check, before and after writing: the new class reading the new file gives
the same placements, the same decided categories, the same pairs kept apart
and the same scope as the class before rule 89 reading the old file. Every
difference stops the script; the one intended difference -- the name cycle of
Epidermolysis bullosa, broken -- is named and allowed.
"""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from wound_ontology.data_manager.data_manager import DataManager  # noqa: E402
from wound_ontology.mappers.judgements import AGENTS  # noqa: E402
from wound_ontology.mappers.rule89_migration import migrate  # noqa: E402
from wound_ontology.mappers.term_mapping_and_gate import FORMAT, TermMappingAndGate  # noqa: E402
from wound_ontology.mappers.term_mapping_and_gate_v88 import TermMappingAndGate as OldTM  # noqa: E402

SOURCE = ROOT / "data" / "cache" / "term_mapping_2026-10-28_08-08.json"
REVIEW = ROOT / "data" / "review" / "rule89_dryrun_2026-10-28"


def _dryrun():
    spec = importlib.util.spec_from_file_location("rule89_dryrun", ROOT / "scripts" / "rule89_dryrun.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _old_class(records: dict) -> OldTM:
    tm = OldTM.__new__(OldTM)
    tm._dm, tm._file_name, tm._records = None, SOURCE.stem, records
    tm._flat = tm._gate_idx = tm._members_idx = None
    return tm


def _new_class(records: dict) -> TermMappingAndGate:
    tm = TermMappingAndGate.__new__(TermMappingAndGate)
    tm._dm, tm._file_name, tm._records = None, "term_mapping", records
    tm._dirty()
    return tm


def compare(old: OldTM, new: TermMappingAndGate, cycles: set[str] = frozenset()) -> dict:
    """What each class answers, side by side; every key a difference. A string
    whose old end lies on a name cycle the migration broke (`cycles`, the one
    intended difference) may end elsewhere now."""
    out = {}
    po, pn = set(old.placements()), set(new.placements())
    out["placements"] = {"old": len(po), "new": len(pn), "only old": sorted(po - pn)[:20],
                         "only new": sorted(pn - po)[:20]}
    co = {t: v["verdict"] for t, v in old.categories().items()}
    cn = {t: v["verdict"] for t, v in new.categories().items()}
    out["categories"] = {"old": len(co), "new": len(cn),
                         "differ": sorted((t, co.get(t), cn.get(t)) for t in set(co) | set(cn)
                                          if co.get(t) != cn.get(t))[:20]}
    names_o = old.data

    def end_o(t):                      # where a string ends before rule 89: its spelling, then its name
        x = old.resolve(t)
        return names_o.get(x, x)

    differ = sorted(t for t in set(old.records) | set(new.records)
                    if end_o(t) != new.concept(t) and end_o(t) not in cycles)
    out["names"] = {"differ": len(differ), "examples": [(t, end_o(t), new.concept(t)) for t in differ[:20]]}
    scope_diff = []
    for t in new.records:
        if new.is_alias(t) or new._target(t):
            continue
        o, n = old.effective_gate_verdict(t)[0], new.gate_verdict(t)[0]
        if (o if o in ("in", "out") else "") != (n if n in ("in", "out") else ""):
            scope_diff.append((t, o, n))
    out["scope"] = {"differ": len(scope_diff), "examples": scope_diff[:20]}
    return out


def clean(rep: dict) -> bool:
    return (not rep["placements"]["only old"] and not rep["placements"]["only new"]
            and not rep["categories"]["differ"] and not rep["names"]["differ"]
            and not rep["scope"]["differ"])


def main() -> int:
    write = "--write" in sys.argv
    newest = sorted((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"))[-1]
    if newest != SOURCE:
        raise SystemExit(f"[rule89] the newest term dict is {newest.name}, not {SOURCE.name}: "
                         f"someone wrote after the dry run. Run the dry run on it first.")
    print(f"[rule89] reading {SOURCE.name}", flush=True)
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    if raw.get("format") == FORMAT:
        raise SystemExit("[rule89] the source is already in the form of rule 89")
    dry = _dryrun()
    with contextlib.redirect_stdout(io.StringIO()):
        old_records = OldTM._load(raw)
    dating = dry.Dating(old_records)
    rows = json.loads((ROOT / "data" / "review" / "placement_merged_2026-10-01.json").read_text())["rows"]
    confirmations = []
    for name in ("unterschiede.csv", "unterschiede_2.csv"):
        confirmations += list(csv.DictReader((REVIEW / name).open(encoding="utf-8")))
    undecided = [r["Nr"] for r in confirmations if not (r.get("Entscheidung (leer = wie heute)") or "").strip()]
    if undecided:
        raise SystemExit(f"[rule89] {len(undecided)} difference(s) without the author's decision: {undecided[:10]}")
    new_records, rep, notes = migrate(old_records, dating, rows, confirmations)
    print(f"[rule89] translated: {rep['records']:,} records; {rep['confirmed by the author as before']} "
          f"confirmation(s) of the author applied", flush=True)
    for k in ("refused placement: term not found", "confirmation: term not found",
              "confirmation: no verdict holds today", "confirmation: row without a decision"):
        if rep.get(k):
            print(f"[rule89] *** {rep[k]} {k}: {notes[k][:10]} ***", flush=True)

    old = _old_class(old_records)
    cycles = {n for pair in notes.get("name cycle broken", []) for n in pair}
    print(f"[rule89] name cycle(s) broken, allowed to end elsewhere: {sorted(cycles)}", flush=True)
    before = compare(old, _new_class(new_records), cycles)
    print("[rule89] before writing: " + json.dumps(before, ensure_ascii=False, default=str)[:3000], flush=True)
    if not clean(before):
        raise SystemExit("[rule89] the new reading differs from the old one -- nothing written")
    if not write:
        print("[rule89] dry: nothing written. Run with --write to switch.")
        return 0

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup = ROOT / "data" / "backup" / f"term_mapping_before_rule89_{stamp}.json"
    shutil.copy2(SOURCE, backup)
    if backup.read_bytes() != SOURCE.read_bytes():
        raise SystemExit(f"[rule89] the backup {backup} does not match the source")
    print(f"[rule89] backup: {backup.relative_to(ROOT)}", flush=True)

    dm = DataManager()                                  # data/cache, where the pipeline reads it
    tm = _new_class(new_records)
    tm._dm = dm
    tm.save()
    written = sorted((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"))[-1]
    back = json.loads(written.read_text(encoding="utf-8"))
    if back.get("format") != FORMAT or back.get("agents") != json.loads(json.dumps(AGENTS)) or back.get("terms") != json.loads(json.dumps(new_records)):
        raise SystemExit(f"[rule89] {written.name} does not read back as written")
    print(f"[rule89] written and read back: {written.relative_to(ROOT)}", flush=True)

    with contextlib.redirect_stdout(io.StringIO()):
        live = TermMappingAndGate(dm)
    after = compare(old, live, cycles)
    print("[rule89] after writing, read by the new class: "
          + json.dumps(after, ensure_ascii=False, default=str)[:3000], flush=True)
    if not clean(after):
        raise SystemExit(f"[rule89] *** the written file reads differently; restore {backup.name} ***")
    print("[rule89] switched: the term dict is in the form of rule 89.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
