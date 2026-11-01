"""The author's own is_a edges that ELK cannot keep together, for the author to decide.

    python -u scripts/elk_author_conflicts.py

Rule 89: an edge the author made or confirmed -- WONT and MILD, an accepted
placement, a decided category -- ranks as the author's, and the edge check
never drops one; two that contradict each other stop the run. This asks ELK
about those edges alone (the same set `run_gate_hierarchy_edges` ranks as the
author's) and writes, for every term ELK finds empty, all of its own edges and
where each comes from, so the author can say which one goes.

Writes data/review/elk_author_conflicts_<date>/conflicts.csv and .json. Writes
nothing the pipeline reads.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")


def main() -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.hierarchies.base_hierarchy import SOURCE_CURATED
    from wound_ontology.mappers.judgements import AUTHOR, rank
    from wound_ontology.orchestrator import Orchestrator

    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    p.build_reasoner_skeleton()
    hier = p.refresh_class_hierarchy(include_rejected=True)
    df = hier.df
    edges = [(str(c), str(q)) for c in df.index for q in df.columns if df.at[c, q] == 1.0 and str(c) != str(q)]
    said = p._is_a_judgements()
    kind = {}
    for e in edges:
        cj = said.get(e)
        if hier._prov.get(e) == SOURCE_CURATED:
            kind[e] = "curated (WONT, MILD, a module or BFO)"
        elif cj and rank(cj) == AUTHOR and cj["verdict"] == "yes":
            kind[e] = ("placement the author accepted" if cj.get("iri") else "category the author decided")
    author = sorted(kind)
    print(f"[conflicts] {len(edges):,} edges in the view; {len(author):,} are the author's", flush=True)
    t = time.time()
    result = p.reasoner_gate.check_edges(author, sources={e: SOURCE_CURATED for e in author})
    print(f"[conflicts] ELK over the author's edges: {result.summary()} ({time.time() - t:.0f} s)", flush=True)
    bad = {tuple(e) for e in result.quarantined}
    children = sorted({c for c, _ in bad})
    rows = []
    for c in children:
        for e in sorted(e for e in author if e[0] == c):
            cj = said.get(e) or {}
            rows.append({"term": c, "parent": e[1], "kind": kind[e],
                         "ELK drops it": "yes" if e in bad else "",
                         "who": cj.get("by", "curated"), "why": (cj.get("why") or "")[:200],
                         "when": cj.get("when", ""),
                         "ELK's reason": result.why.get(e, "")})
    out = ROOT / "data" / "review" / f"elk_author_conflicts_{time.strftime('%Y-%m-%d')}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "conflicts.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["term"])
        w.writeheader()
        w.writerows(rows)
    (out / "conflicts.json").write_text(json.dumps({"made": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                    "unsatisfiable": result.unsatisfiable,
                                                    "explanation": result.explanation,
                                                    "rows": rows}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print(f"[conflicts] {len(children)} term(s), {len(bad)} edge(s) ELK drops -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
