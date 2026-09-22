"""Adjudicate the mapping pairs that chain resolution created.

resolve_chains re-points `A -> B -> C` onto `A -> C`, and that pair has never
been put to the model: the cache holds `A -> B` and `B -> C`. The rule is that
no mapping onto an existing class stands unasked, so the adjudication runs
again over the resolved mapping. Everything already in the cache is answered
from it; only the new pairs cost a call.

Idempotent — run it as often as you like; a second run asks nothing.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
from wound_ontology.orchestrator import Orchestrator


def log(*a):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]", *a, flush=True)


def main() -> None:
    p = Orchestrator(entrez_email=ENTREZ_EMAIL,
                     allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    freq = p._collect_store_terms_with_freq()
    anchors = p.ontology_labels() - set(freq)
    log(f"mapping: {len(p.term_mapper.mapping):,} entries, {len(anchors)} anchors")
    t0 = time.time()
    p._adjudicate_anchor_mappings(anchors)
    log(f"finished in {(time.time()-t0)/60:.1f} min - "
        f"{len(p.term_mapper.mapping):,} entries remain")


if __name__ == "__main__":
    main()
