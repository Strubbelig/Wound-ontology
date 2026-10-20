"""P4 steps 3-7: reasoner checks, hierarchies, FCA, extension of WONT, competency questions.

    python -u scripts/p4_derive.py > output/p4_derive_<date>.log 2>&1
    python -u scripts/p4_derive.py --skip-fca ...   # no concept naming: the last run's
        proposals are judged again by the current head-word rule (rule 79), before
        the hierarchy is built, so the edge check reasons over what it licenses

Runs after the mapping build and the reviews. Each step is timed and logged;
any exception stops the run (no silent continuation, rule 1).

Deliberately NOT run: `run_store_fill`. It asks the model to fill "missing"
attributes and writes them into the concept store, which rule 51 reserves for
what the abstracts said -- derived content is never injected into the evidence
(rule 3). `run_matrix_nan_fill` is also left out of this pass: it spends a
model call per undecided FCA cell and is only worth it once the lattice has
been looked at.
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
    log(f"START {name}")
    t0 = time.time()
    out = fn()
    log(f"END   {name} ({time.time() - t0:.0f} s)")
    return out


def rejudge_last_proposals(p) -> int:
    """Every proposal of the newest output/fca_head_rule_*.json, judged again (rule 79)."""
    import json
    from wound_ontology.fca.concept_lattice import ConceptLattice
    reports = sorted((ROOT / "output").glob("fca_head_rule_*.json"))
    if not reports:
        raise RuntimeError("--skip-fca needs an output/fca_head_rule_*.json from an earlier run; there is none")
    # every report, not the newest only: a re-judged report holds only what it
    # was given, and an edge open today may be licensed by tomorrow's ruling
    pairs = set()
    for f in reports:
        rep = json.loads(f.read_text(encoding="utf-8"))
        pairs |= {(r["child"], r["parent"]) for k in ("licensed", "refused", "synonym", "open", "between_names") for r in rep.get(k, [])}
    pairs = sorted(pairs)
    print(f"[p4] {len(pairs)} proposal(s) from {len(reports)} report(s), newest {reports[-1].name}")
    p.lattice = ConceptLattice(p.dm, p.context_matrix, "concept_lattice_wound")
    return p._judge_fca_proposals(pairs)


def main() -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.orchestrator import Orchestrator

    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES,
                     base_path=BASE_PATH)
    skip_fca = "--skip-fca" in sys.argv
    step("reasoner skeleton", p.build_reasoner_skeleton)
    step("reasoner check of store relations (ELK)", lambda: p.run_gate_store_relations(apply=True))
    if skip_fca:
        step("head-word rule on the last run's proposals (no concept naming)", lambda: rejudge_last_proposals(p))
    step("build hierarchies", p.run_build_hierarchies)
    step("reasoner check of is_a edges (ELK)", p.run_gate_hierarchy_edges)
    if not skip_fca:
        step("formal concept analysis (wound subtree)", lambda: p.run_fca(
            subtree_root="Wound",
            predicates=["has_quality", "part_of", "has_participant", "has_disposition", "inheres_in"]))
        # rule 79: the edges the head-word rule promoted are checked like every other is_a edge
        step("reasoner check of is_a edges after the concept analysis (ELK)", p.run_gate_hierarchy_edges)
    out = ROOT / "output" / "owl" / "wont_extended.ttl"
    # rule 79: the FCA edges in the hierarchy are the ones the head-word rule licensed
    step("extend WONT", lambda: p.run_extend_ground_truth(output_file=str(out), include_fca=True))
    step("competency questions", lambda: p.run_competency_check(ontology_file=str(out)))
    log("ALL DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
