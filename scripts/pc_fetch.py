"""PC — re-run the full query list at a real result cap.

Measured 2026-09-10: every one of the 43 queries in config/pubmed_query_list.py
returned exactly 20 PMIDs (min = median = max = 20), so the corpus was built at
`max_results_per_query=20` — not the 200 the orchestrator defaults to nor the
1000 the connector allows. Same queries, higher cap: no new query writing.

PubmedConnector.database's setter saves after every query, so the CSV in
data/cache/ is durable as the run proceeds. Rows are deduplicated; PMIDs are not
(a paper found by three queries is three rows), and both counts are printed.

    setsid nohup python -u scripts/pc_fetch.py 200 > output/pc_fetch.log 2>&1 &
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

from config.pubmed_query_list import PUBMED_SEARCH
from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
from wound_ontology.orchestrator import Orchestrator


def log(*a):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]", *a, flush=True)


def main(cap: int) -> None:
    pipeline = Orchestrator(entrez_email=ENTREZ_EMAIL,
                            allowed_predicates=ALLOWED_PREDICATES,
                            base_path=BASE_PATH)
    db = pipeline.pubcon.database
    before_rows, before_pmids = len(db), set(db["pmid"].astype(str))
    extracted = set(pipeline.store.document_keys())
    log(f"before: {before_rows:,} rows, {len(before_pmids):,} unique PMIDs; "
        f"{len(extracted):,} extracted")
    log(f"running {len(PUBMED_SEARCH)} queries at max_results_per_query={cap}")

    t0 = time.time()
    pipeline.run_pubmed_search(PUBMED_SEARCH, max_results_per_query=cap)
    db = pipeline.pubcon.database
    after_pmids = set(db["pmid"].astype(str))
    new = after_pmids - before_pmids
    log(f"finished in {(time.time()-t0)/60:.1f} min")
    log(f"after: {len(db):,} rows, {len(after_pmids):,} unique PMIDs "
        f"(+{len(new):,} new)")
    log(f"unextracted now: {len(after_pmids - extracted):,}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
