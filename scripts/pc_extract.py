"""PC — extract every fetched abstract the concept store has not seen.

Roadmap phase PC, lane B. `add_llm_extracts` keys the store by PMID and skips
one it has already seen, so this is resumable: run it again and it continues
from wherever it stopped. The store is written to data/cache/ as it goes.

Measured 2026-09-10 at first launch: 606 unique PMIDs fetched, 142 extracted,
464 to do. The run was cut off at 371 when the session ended; relaunched
2026-09-11 for the remaining 235.

Run detached so a closed terminal does not kill it:
    ( nohup python -u scripts/pc_extract.py 5 data/cache/pubmed_abstracts_2026-08-24_17-39.csv \
        > output/pc_extract.log 2>&1 < /dev/null & )
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
from wound_ontology.orchestrator import Orchestrator


def log(*a):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]", *a, flush=True)


def distinct_entities(store) -> int:
    return len(store.entities)   # standing entities, rejected ones excluded


def main(batch_size: int = 10, only_pmids_in: str | None = None) -> None:
    log("constructing Orchestrator")
    pipeline = Orchestrator(entrez_email=ENTREZ_EMAIL,
                            allowed_predicates=ALLOWED_PREDICATES,
                            base_path=BASE_PATH)
    db = pipeline.pubcon.database
    if only_pmids_in:
        # The connector always loads the NEWEST abstract CSV. After the cap-200
        # fetch that is 6,031 PMIDs, and a relaunch meant for the last 137 of
        # the original 606 started on all 5,562 instead (2026-09-11 17:37,
        # killed after one PMID). Restrict to an earlier CSV's PMIDs when the
        # big batch is not yet authorised. _database is set directly because
        # the public setter merges and saves.
        import pandas as pd
        keep = set(pd.read_csv(only_pmids_in)["pmid"].astype(str))
        db = db[db["pmid"].astype(str).isin(keep)].reset_index(drop=True)
        pipeline.pubcon._database = db
        log(f"restricted to the {len(keep):,} PMIDs in {Path(only_pmids_in).name}")
    fetched = set(db["pmid"].astype(str))
    before = set(pipeline.store.document_keys())
    todo = fetched - before
    log(f"abstract database: {len(db):,} rows, {len(fetched):,} unique PMIDs")
    log(f"store before: {len(before):,} PMIDs, {distinct_entities(pipeline.store):,} entities")
    log(f"to extract: {len(todo):,}")
    if not todo:
        log("nothing to do")
        return

    t0 = time.time()
    pipeline.run_extract_to_store(batch_size=batch_size, normalize_every=1000)
    after = set(pipeline.store.document_keys())
    mins = (time.time() - t0) / 60
    log(f"finished in {mins:.1f} min — store after: {len(after):,} PMIDs "
        f"(+{len(after - before):,}), {distinct_entities(pipeline.store):,} entities")
    missed = todo - after
    if missed:
        # Rule: nothing drops quietly. The extractor prints per-abstract failures;
        # this is the count that survived every retry.
        log(f"NOT EXTRACTED after retries: {len(missed):,} PMIDs — "
            f"{sorted(missed)[:10]}{' …' if len(missed) > 10 else ''}")


if __name__ == "__main__":
    # usage: pc_extract.py [batch_size] [only_pmids_in.csv]
    main(batch_size=int(sys.argv[1]) if len(sys.argv) > 1 else 10,
         only_pmids_in=sys.argv[2] if len(sys.argv) > 2 else None)
