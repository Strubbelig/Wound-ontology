"""
check_term_mapping.py
---------------------
Re-evaluates every non-identity entry in a term-mapping JSON using the live
SapBERT embedder and flags mappings whose cosine similarity falls below the
0.95 merge threshold — indicating a potentially false merge.

Usage
-----
    python scripts/check_term_mapping.py [PATH_TO_MAPPING_JSON]

If no path is given the most recent data/cache/term_mapping_*.json is used.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from rapidfuzz.fuzz import ratio as fuzz_ratio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wound_ontology.embedding.embedder import Embedder
from wound_ontology.utils.string_utils import normalize_term

MERGE_THRESHOLD = 0.95


def _string_sim(a: str, b: str) -> float:
    return fuzz_ratio(normalize_term(a), normalize_term(b)) / 100.0


def _latest_mapping(cache_dir: Path) -> Path:
    files = sorted(cache_dir.glob("term_mapping_*.json"))
    if not files:
        raise FileNotFoundError(f"No term_mapping_*.json in {cache_dir}")
    return files[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-check term mapping with SapBERT")
    parser.add_argument("mapping", nargs="?", help="Path to term_mapping JSON")
    args = parser.parse_args()

    path = Path(args.mapping) if args.mapping else _latest_mapping(ROOT / "data" / "cache")
    print(f"Mapping file : {path.name}")

    with open(path) as f:
        mapping: dict[str, str] = json.load(f)

    non_id = {term: canonical for term, canonical in mapping.items() if term != canonical}
    print(f"Non-identity : {len(non_id)} entries\n")

    unique = list(dict.fromkeys(t for pair in non_id.items() for t in pair))

    embedder = Embedder()
    print(f"Embedding {len(unique)} unique terms with SapBERT...")
    embs = embedder.embed(unique)
    idx = {t: i for i, t in enumerate(unique)}

    results = []
    for term, canonical in non_id.items():
        cosine = float(np.dot(embs[idx[term]], embs[idx[canonical]]))
        results.append((term, canonical, cosine, _string_sim(term, canonical)))

    flagged = sorted(
        [(t, c, cos, ss) for t, c, cos, ss in results if cos < MERGE_THRESHOLD],
        key=lambda x: x[2],
    )
    clean = len(results) - len(flagged)

    print(f"\n{'─'*72}")
    print(f"FLAGGED  (cosine < {MERGE_THRESHOLD}) : {len(flagged)}")
    print(f"CLEAN    (cosine ≥ {MERGE_THRESHOLD}) : {clean}")
    print(f"{'─'*72}")

    if flagged:
        print()
        for term, canonical, cosine, str_sim in flagged:
            print(f"  cos={cosine:.3f}  str={str_sim:.3f}  {term!r}  →  {canonical!r}")
    else:
        print("\nNo suspicious mappings found.")


if __name__ == "__main__":
    main()
