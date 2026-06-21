"""Quality-control check for term mappings: flag potentially false merges via SapBERT."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from wound_ontology.embedding.embedder import Embedder

MERGE_THRESHOLD = 0.95


def load_latest_mapping(cache_dir: Path) -> tuple[Path, dict[str, str]]:
    """Return (path, mapping_dict) for the most recent term_mapping_*.json in cache_dir."""
    files = sorted(cache_dir.glob("term_mapping_*.json"))
    if not files:
        raise FileNotFoundError(f"No term_mapping_*.json found in {cache_dir}")
    path = files[-1]
    with open(path, encoding="utf-8") as f:
        return path, json.load(f)


def _string_sim(a: str, b: str) -> float:
    from rapidfuzz.fuzz import ratio
    from wound_ontology.utils.string_utils import normalize_term
    return ratio(normalize_term(a), normalize_term(b)) / 100.0


def check_mapping(
    mapping: dict[str, str],
    embedder: "Embedder",
    threshold: float = MERGE_THRESHOLD,
) -> list[dict]:
    """Embed every (term, canonical) pair and return entries where cosine < threshold.

    Each returned dict has keys: term, canonical, cosine, string_sim.
    """
    non_id = {term: canonical for term, canonical in mapping.items() if term != canonical}
    if not non_id:
        return []

    unique = list(dict.fromkeys(t for pair in non_id.items() for t in pair))
    embs   = embedder.embed(unique)
    idx    = {t: i for i, t in enumerate(unique)}

    flagged = []
    for term, canonical in non_id.items():
        cosine = float(np.dot(embs[idx[term]], embs[idx[canonical]]))
        if cosine < threshold:
            flagged.append({
                "term":       term,
                "canonical":  canonical,
                "cosine":     round(cosine, 4),
                "string_sim": round(_string_sim(term, canonical), 4),
            })

    flagged.sort(key=lambda x: x["cosine"])
    return flagged


def print_report(
    flagged: list[dict],
    total_non_id: int,
    threshold: float = MERGE_THRESHOLD,
    mapping_name: str = "",
) -> None:
    clean = total_non_id - len(flagged)
    label = f"  [{mapping_name}]" if mapping_name else ""
    print(f"\n{'─' * 72}{label}")
    print(f"FLAGGED  (cosine < {threshold}) : {len(flagged)}")
    print(f"CLEAN    (cosine ≥ {threshold}) : {clean}")
    print(f"{'─' * 72}")
    if flagged:
        print()
        for entry in flagged:
            print(
                f"  cos={entry['cosine']:.3f}  "
                f"str={entry['string_sim']:.3f}  "
                f"{entry['term']!r}  →  {entry['canonical']!r}"
            )
    else:
        print("\nNo suspicious mappings found.")
