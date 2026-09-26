"""Fold the two adjudication caches onto the mapping records. Run once — SPENT.

    Run and verified on 2026-09-24: 7,423 pass-1 and 4,813 pass-2 verdicts are
    on the records, and the cache files were deleted afterwards. Kept because it
    is the record of how the migration was done and what it checked, and because
    it still runs correctly against nothing (0 files, 0 added). Rule 14.


`mapping_adjudication_*.json` (pass 1) and `mapping_second_opinion_*.json`
(pass 2) were the model's memory across builds, keyed `term \\x1f canonical`.
They were also a SECOND home for a fact the record already carried, with
nothing keeping the two equal — a `pass1` copied onto the entry while the file
stayed authoritative is a drift waiting to happen, and 2,548 of the terms they
judged were not in the mapping at all, so their verdicts were reachable only by
opening a cache file nobody downstream reads.

After this, `TermMappingAndGate.pass_cache` is the cache: it reads and writes the
records in place. The files stay on disk as a historical artifact; nothing
loads them again.

EVERY file of each prefix is folded, not just the newest. `load_latest_json`
reads one file, and the first run of this script used it -- which left 7 verdicts
from the 2026-09-06 builds on disk and nowhere else: 5 pairs nothing has proposed
since, and 2 the model later answered differently. They only showed up because
the check before deleting the files read all of them.

Newest first, and `import_pass` never overwrites: a verdict already on the
record was written by a later, better-evidenced ask, so an older file may add
what is missing but never argue with what is there. The 2 conflicts are reported
and left alone.

Verifies by reading back from disk, not from memory. A fold that did not land
would lose several thousand model verdicts and quietly re-spend the credits.

    python scripts/p4_fold_caches.py            # dry run
    python scripts/p4_fold_caches.py --apply
"""
from __future__ import annotations

import glob
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from config.settings import BASE_PATH                        # noqa: E402
from wound_ontology.data_manager.data_manager import DataManager   # noqa: E402
from wound_ontology.mappers.term_mapping_and_gate import KEY_SEP, TermMappingAndGate  # noqa: E402

PASSES = {"pass1": "mapping_adjudication", "pass2": "mapping_second_opinion"}


def main() -> int:
    apply = "--apply" in sys.argv
    dm = DataManager(base_path=BASE_PATH)
    # Newest first. See the module docstring: an older file may fill a gap, never
    # overrule an answer a later ask already put on the record.
    caches: dict[str, list[tuple[str, dict]]] = {}
    for name, prefix in PASSES.items():
        files = sorted(glob.glob(str(Path(BASE_PATH) / f"{prefix}_*.json")), reverse=True)
        caches[name] = [(f, json.load(open(f, encoding="utf-8"))) for f in files]
        total = len({k for _, c in caches[name] for k in c})
        print(f"[fold] {name}: {total:,} distinct verdict(s) across "
              f"{len(files)} {prefix}_*.json file(s)")

    gt = TermMappingAndGate(dm)
    print(f"[fold] {len(gt.records):,} record(s), {len(gt.data):,} live; "
          f"already on record: "
          + ", ".join(f"{n} {gt.judged(n):,}" for n in PASSES))

    if not apply:
        print("[fold] dry run — nothing written. Re-run with --apply.")
        return 0

    # The mapping file is the ground truth now; back it up before rewriting it.
    latest = dm._find_latest_path("term_mapping", "json")
    if latest:
        backup = ROOT / "data" / "backup" / f"term_mapping_before_fold_{time.strftime('%Y-%m-%d_%H-%M')}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(latest, backup)
        print(f"[fold] backed up {Path(latest).name} → {backup.relative_to(ROOT)}")

    for name, files in caches.items():
        for path, cache in files:
            rep = gt.import_pass(name, cache)
            if not (rep["added"] or rep["conflicts"]):
                continue
            print(f"[fold] {name} {Path(path).name}: {rep['added']:,} added, "
                  f"{rep['already_on_record']:,} already there, "
                  f"{rep['new_records']:,} term(s) had no record at all, "
                  f"{rep['conflicts']:,} conflict(s)")
            for clash in rep["clashes"]:
                print(f"[fold]     KEPT THE RECORD, file overruled — {clash}")

    # Read back from DISK. Everything in each cache file must be on a record,
    # with the same verdict, or the fold did not happen and the files are still
    # the only copy.
    reloaded = TermMappingAndGate(DataManager(base_path=BASE_PATH))
    problems: list[str] = []
    for name, files in caches.items():
        on_record = reloaded.verdicts(name)
        seen, superseded = set(), 0
        for path, cache in files:
            for key, want in cache.items():
                seen.add(key)
                got = on_record.get(key)
                if got is None:
                    problems.append(f"{name} {key.replace(KEY_SEP, ' -> ')}: missing")
                elif got.get("verdict") != want.get("verdict"):
                    superseded += 1          # an older file, answered again later
        print(f"[fold] read back: {name} {len(on_record):,} verdict(s) on record; "
              f"{len(seen):,} distinct in the files, {superseded} of them an older "
              f"answer the record has since superseded")
    if problems:
        raise RuntimeError(
            f"[fold] the fold did NOT land — {len(problems)} verdict(s) are not "
            f"on the records:\n  " + "\n  ".join(problems[:10]))

    live_before = json.loads(Path(latest).read_text()) if latest else {}
    print(f"[fold] {len(reloaded.records):,} record(s) now "
          f"(was {len(live_before):,}), {len(reloaded.data):,} live mapping(s), "
          f"{len(reloaded.subsumption_candidates()):,} subsumption candidate(s), "
          f"{len(reloaded.disagreements()):,} pass disagreement(s).")
    print("[fold] verified. The cache files are history; pass_cache is the cache now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
