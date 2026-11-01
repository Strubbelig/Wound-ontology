"""Let ELK judge again after the move to rule 89, then extend WONT.

    python -u scripts/rule89_elk.py edges        # is_a edges of the hierarchy view, then extend + CQs
    python -u scripts/rule89_elk.py relations    # the store's relations (about 8 h), then extend + CQs

Rule 89 (2026-10-28): ELK writes its verdicts into the term dict, each with its
own reason, and only where its own last word changes; the 1,126 edge verdicts
of the file before rule 89 were not carried over (curator, 2026-10-28), so the
first edge check writes them anew. The two checks are independent -- one
judges relations, the other is_a edges -- and run separately so the short one
answers first. The extension and the competency questions follow each, as in
p4_derive.py; the accepted FCA slice on disk is used, as with --export-only.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")


def log(*a):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]", *a, flush=True)


def step(name, fn):
    log("START", name)
    t = time.time()
    out = fn()
    log(f"END   {name} ({time.time() - t:.0f} s)")
    return out


def _end_word_names(p) -> None:
    """Name, loudly, every concept the end-word naming rule would rename and
    nobody has (config/category_head_rules.HEAD_NAME_SUFFIX, 2026-10-29)."""
    from config.category_head_rules import HEAD_NAME_SUFFIX
    from wound_ontology.owl.extend import ontology_label_test
    from apply_category_rulings import head
    left = p.term_mapper._term_mapping.end_word_renames(HEAD_NAME_SUFFIX, ontology_label_test(), head=head)
    if left:
        log(f"*** {len(left)} term(s) carry a category their name should say and do not: "
            f"{list(left.items())[:5]} -- scripts/apply_category_rulings.py renames them ***")
    else:
        log("every term the end-word naming rule covers is named by it")


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which not in ("edges", "relations"):
        raise SystemExit("say which check: edges or relations")
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES,
                     base_path=BASE_PATH)
    out = ROOT / "output" / "owl" / "wont_extended.ttl"
    step("names the end-word rule asks for", lambda: _end_word_names(p))
    step("reasoner skeleton", p.build_reasoner_skeleton)
    if which == "relations":
        step("reasoner check of store relations (ELK)", lambda: p.run_gate_store_relations(apply=True))
    else:
        step("reasoner check of is_a edges on the class hierarchy view (ELK)", p.run_gate_hierarchy_edges)
    step("extend WONT", lambda: p.run_extend_ground_truth(output_file=str(out), include_fca=True))
    step("competency questions", lambda: p.run_competency_check(ontology_file=str(out)))
    log("ALL DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
