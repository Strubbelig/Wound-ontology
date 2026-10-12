"""Run only the reasoner check of the store's relations (p4_derive step 2).

    python -u scripts/run_relation_check.py > output/relation_check_<date>.log 2>&1

For after a curator's decisions on relations: the check lifts its own verdicts
and re-tests every relation, so held-back statements whose cause the curator
removed come back. The class tree, concept analysis and WONT addition are not
rebuilt here; the next full p4_derive.py run picks the change up.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")


def main() -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    p.build_reasoner_skeleton()
    p.run_gate_store_relations(apply=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
