"""P4 step 2c - apply the reviewed term mapping to the store.

Renames every entity name and predicate target in the store to its canonical
form, title-cases the result, and merges the records that land on one name.
The store's rename log records every rename the MAPPING made (`by="mapping"`),
so what this did is readable afterwards.

Repeatable (INSTRUCTIONS rule 24): a correction made to the mapping later still
reaches the store on a second run. What a second run cannot do is split a merge
that has already happened - for that, restore data/backup/.
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
    before_terms = len(p._collect_store_terms_with_freq())
    before_ents = sum(len(d.get("entities", {}))
                      for k, d in p.store._dict.items() if k != p.store.DECISIONS)
    log(f"before: {before_terms:,} distinct terms, {before_ents:,} entity records, "
        f"{len(p.term_mapper.mapping):,} mapping entries")
    t0 = time.time()
    p.run_apply_mapping()
    after_terms = len(p._collect_store_terms_with_freq())
    after_ents = sum(len(d.get("entities", {}))
                     for k, d in p.store._dict.items() if k != p.store.DECISIONS)
    log(f"after : {after_terms:,} distinct terms ({before_terms - after_terms:,} names "
        f"collapsed), {after_ents:,} entity records")
    log(f"finished in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
