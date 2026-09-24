"""Fold the two adjudication caches onto the mapping records. Run once.

`mapping_adjudication_*.json` (pass 1) and `mapping_second_opinion_*.json`
(pass 2) were the model's memory across builds, keyed `term \\x1f canonical`.
They were also a SECOND home for a fact the record already carried, with
nothing keeping the two equal — a `pass1` copied onto the entry while the file
stayed authoritative is a drift waiting to happen, and 2,548 of the terms they
judged were not in the mapping at all, so their verdicts were reachable only by
opening a cache file nobody downstream reads.

After this, `TermMapping.pass_cache` is the cache: it reads and writes the
records in place. The files stay on disk as a historical artifact; nothing
loads them again.

Verifies by reading back from disk, not from memory. A fold that did not land
would lose several thousand model verdicts and quietly re-spend the credits.

    python scripts/p4_fold_caches.py            # dry run
    python scripts/p4_fold_caches.py --apply
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from config.settings import BASE_PATH                        # noqa: E402
from wound_ontology.data_manager.data_manager import DataManager   # noqa: E402
from wound_ontology.mappers.term_mapping import KEY_SEP, TermMapping  # noqa: E402

PASSES = {"pass1": "mapping_adjudication", "pass2": "mapping_second_opinion"}


def main() -> int:
    apply = "--apply" in sys.argv
    dm = DataManager(base_path=BASE_PATH)
    caches = {name: (dm.load_latest_json(prefix) or {})
              for name, prefix in PASSES.items()}
    for name, cache in caches.items():
        print(f"[fold] {name}: {len(cache):,} verdict(s) in "
              f"{PASSES[name]}_*.json")

    gt = TermMapping(dm)
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

    for name, cache in caches.items():
        rep = gt.import_pass(name, cache)
        print(f"[fold] {name}: {rep['added']:,} added, "
              f"{rep['already_on_record']:,} already there, "
              f"{rep['new_records']:,} term(s) had no record at all, "
              f"{rep['conflicts']:,} conflict(s)")
        for clash in rep["clashes"]:
            print(f"[fold]     CONFLICT {clash}")

    # Read back from DISK. Everything in each cache file must be on a record,
    # with the same verdict, or the fold did not happen and the files are still
    # the only copy.
    reloaded = TermMapping(DataManager(base_path=BASE_PATH))
    problems: list[str] = []
    for name, cache in caches.items():
        on_record = reloaded.verdicts(name)
        for key, want in cache.items():
            got = on_record.get(key)
            if got is None:
                problems.append(f"{name} {key.replace(KEY_SEP, ' -> ')}: missing")
            elif got.get("verdict") != want.get("verdict"):
                problems.append(f"{name} {key.replace(KEY_SEP, ' -> ')}: "
                                f"{got.get('verdict')!r} != {want.get('verdict')!r}")
        print(f"[fold] read back: {name} {len(on_record):,} verdict(s) on record "
              f"(file had {len(cache):,})")
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
