"""P4 step 1-2 - the skeleton and the term mapping, against the final store.
Roadmap P4, the single derived rebuild. Runs build_reasoner_skeleton() (it
rebuilds on its own when WONT or MILD is newer) and run_build_term_mapping(),
which embeds every store term with SapBERT, anchors on the WONT + MILD labels,
and has the LLM adjudicate every anchor and store-to-store pair whose labels
differ by more than case, punctuation or plural. Verdicts are read from and
written to the mapping records themselves (rule 38), so nothing it has already
asked is asked again and nothing has to consult a side file.
Then review_mapping() by hand, then run_apply_mapping().
Run detached:
    ( nohup python -u scripts/p4_mapping.py > output/p4_mapping.log 2>&1 < /dev/null & )
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


def main() -> None:
    log("constructing Orchestrator")
    pipeline = Orchestrator(entrez_email=ENTREZ_EMAIL,
                            allowed_predicates=ALLOWED_PREDICATES,
                            base_path=BASE_PATH)
    log(f"store: {len(pipeline.store.document_keys()):,} PMIDs, "
        f"{len(pipeline.store.entities):,} entities")
    t0 = time.time()
    log("step 1: reasoner skeleton")
    log(f"  {pipeline.build_reasoner_skeleton()}")
    log("step 2: term mapping (SapBERT + LLM adjudication)")
    mapping = pipeline.run_build_term_mapping()
    non_identity = sum(1 for t, c in mapping.items() if t != c)
    log(f"finished in {(time.time() - t0) / 60:.1f} min - mapping: {len(mapping):,} entries, "
        f"{non_identity:,} non-identity")


if __name__ == "__main__":
    main()
