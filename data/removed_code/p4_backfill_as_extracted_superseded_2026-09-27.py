"""Give every existing abstract its `as_extracted` book (rule 50). One-time.

New extractions write the book at ingestion, with the extractor's literal
strings. The 6,029 abstracts already in the store were ingested before that,
and their literal strings were never kept -- ingestion cleaned them first. The
earliest spelling that survives is the 2026-09-22 snapshot taken before the
first mapping apply, so that is what the book is seeded with, and each such
document says so in `as_extracted_from`. A reader can tell a literal string
from a snapshot spelling; nothing pretends to be the extractor's output.

Each snapshot name is aligned to a name the document holds NOW:

1. by following the store's own `renamed` book to its end, then
2. where that does not land -- a target renamed before target renames were
   recorded -- by pass 0's spelling key, accepted only when exactly one name
   in the same document carries it.

Anything else is reported and left out of the book, never guessed. Measured
2026-09-27: 215,819 by the book, 1,808 by the key, 0 ambiguous, 0 unaligned;
every one of the 214,813 current names received an origin.

    python scripts/p4_backfill_as_extracted.py [--write]
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

SNAPSHOT = ROOT / "data" / "backup" / "concept_store_pre_mapping_2026-09-22.json"
SOURCE = ("snapshot 2026-09-22 (concept_store_pre_mapping_2026-09-22.json): the "
          "earliest spelling kept; the extractor's literal strings were not "
          "stored before 2026-09-27")


def names_of(doc: dict) -> set[str]:
    ents = doc.get("entities", {})
    out = set(ents)
    for attrs in ents.values():
        out.update(t.split(":", 1)[1].strip() for t in attrs if ":" in t)
    return out


def books(snapshot: dict, current: dict, renamed: dict, key) -> tuple[dict, Counter, list]:
    """`({doc: book}, counts, problems)`. Pure, so it is testable without files."""
    def chain(name: str) -> str:
        seen: set[str] = set()
        while name in renamed and name not in seen:
            seen.add(name)
            name = renamed[name]["to"]
        return name

    out: dict = {}
    counts: Counter = Counter()
    problems: list = []
    for doc, rec in current.items():
        if doc not in snapshot:
            counts["documents not in the snapshot"] += 1
            continue
        now = names_of(rec)
        book: dict[str, list[str]] = {}
        for old in sorted(names_of(snapshot[doc])):
            end = chain(old)
            if end in now:
                counts["aligned by the rename book"] += 1
                book.setdefault(end, []).append(old)
                continue
            hits = [n for n in now if key(n) in (key(old), key(end))]
            if len(hits) == 1:
                counts["aligned by spelling key"] += 1
                book.setdefault(hits[0], []).append(old)
            else:
                counts["ambiguous" if hits else "unaligned"] += 1
                problems.append((doc, old, end, sorted(hits)[:3]))
        counts["current names without an origin"] += len(now - set(book))
        out[doc] = book
    return out, counts, problems


def main(argv: list[str]) -> int:
    from datetime import date

    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.store.concept_store import AS_EXTRACTED
    from wound_ontology.utils.normalise import normalise

    write = "--write" in argv
    p = Orchestrator()
    store = p.store
    current = {k: v for k, v in store.dict.items()
               if k != store.DECISIONS and isinstance(v, dict) and "entities" in v
               and k not in ("predefined",) and not k.startswith("llm_fill")}
    already = [k for k, v in current.items() if AS_EXTRACTED in v]
    if already:
        raise SystemExit(f"[backfill] {len(already)} document(s) already carry a book; "
                         f"this is a one-time seed and will not overwrite them: {already[:3]}")
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    cache: dict[str, str] = {}

    def key(x: str) -> str:
        if x not in cache:
            cache[x] = normalise(x).key
        return cache[x]

    seeded, counts, problems = books(snapshot, current, store.decisions()["renamed"], key)
    for k, v in counts.most_common():
        print(f"[backfill] {k}: {v:,}")
    for doc, old, end, hits in problems[:20]:
        print(f"[backfill]   {doc}: {old!r} (-> {end!r}) matched {hits}")
    if not write:
        print("[backfill] dry run -- nothing written. Pass --write.")
        return 0

    backup = ROOT / "data" / "backup" / f"concept_store_before_as_extracted_{date.today()}.json"
    latest = sorted((ROOT / "data" / "cache").glob("concept_store_*.json"))[-1]
    shutil.copy2(latest, backup)
    print(f"[backfill] backed up {latest.name} -> {backup.name}")
    for doc, book in seeded.items():
        store.dict[doc][AS_EXTRACTED] = book
        store.dict[doc]["as_extracted_from"] = SOURCE
    store.save()

    fresh = Orchestrator().store
    wrong = [d for d, b in seeded.items() if fresh.dict[d].get(AS_EXTRACTED) != b]
    bare = [d for d in seeded if not names_of(fresh.dict[d]) <= set(fresh.dict[d][AS_EXTRACTED])]
    if wrong or bare:
        raise RuntimeError(f"[backfill] {len(wrong)} book(s) did not read back and "
                           f"{len(bare)} document(s) hold a name with no origin: "
                           f"{wrong[:3]} {bare[:3]}")
    print(f"[backfill] {len(seeded):,} book(s) written and read back from disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
