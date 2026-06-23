"""Action layer for term-synonym clustering and mapping lookup.

Takes a TermMapping (persistence layer) and operates on it.
Has no file I/O — all persistence goes through TermMapping.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd
from rapidfuzz.fuzz import ratio as _fuzz_ratio

from wound_ontology.mappers.term_mapping import TermMapping
from wound_ontology.utils.string_utils import normalize_term

_GENERIC_TERMS: frozenset[str] = frozenset({
    "wound", "pain", "skin", "patient", "female", "male",
    "chronic", "acute", "severe", "infection", "tissue",
    "leg", "foot", "scar", "burn", "ulcer", "sore",
    "symptom", "complication", "deformity", "crystal",
    "vagina", "pathogen", "geriatric", "hand", "valid",
})


def _string_sim(a: str, b: str) -> float:
    return _fuzz_ratio(normalize_term(a), normalize_term(b)) / 100.0


def _is_generic(term: str) -> bool:
    return normalize_term(term) in _GENERIC_TERMS


class TermMapper:
    """Action layer: synonym clustering and mapping lookup.

    Layer 3 in the mapper stack:
      DataManager (repo) → TermMapping (persistence) → TermMapper (action) → MappingCleaner (curator)
    """

    def __init__(self, term_mapping: TermMapping, name: str = "Term mapper") -> None:
        self.name          = name
        self._term_mapping = term_mapping
        self._standard_embeddings: dict[str, np.ndarray] = {}
        self._review_threshold: float = 0.75

    # ── Mapping access (dict-compatible) ─────────────────────────────────────

    @property
    def mapping(self) -> dict[str, str]:
        """The raw mapping dict — read-only view of TermMapping.data."""
        return self._term_mapping.data

    @property
    def standards(self) -> list[str]:
        return self._term_mapping.standards

    @property
    def originals(self) -> list[str]:
        return self._term_mapping.originals

    def map(self, term: str) -> str:
        """Single-term lookup; returns term unchanged if not mapped."""
        return self._term_mapping.get(term)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply mapping to a DataFrame (index + column labels)."""
        return df.rename(index=self._term_mapping.data,
                         columns=self._term_mapping.data)

    def save(self) -> None:
        """Explicit save — delegates to TermMapping."""
        self._term_mapping.save()

    # ── SapBERT clustering ────────────────────────────────────────────────────

    def build_from_embeddings(
        self,
        terms: list[str],
        embedder,
        similarity_threshold: float = 0.95,
        frequencies: dict[str, int] | None = None,
    ) -> dict[str, str]:
        """Synonym clustering via SapBERT cosine similarity + complete-linkage.

        MERGE CONDITION — a pair (a, b) is valid iff:
          0. normalize_term(a) == normalize_term(b)  (string-only pre-merge)
          1. cosine_similarity >= similarity_threshold  (default 0.95)

        Generic single-word terms additionally require string_sim >= 0.90 to
        prevent common biomedical context words from absorbing unrelated terms.

        CLUSTERING: complete-linkage — two clusters merge only when EVERY
        cross-cluster pair independently passes the merge condition, preventing
        transitive false merges.
        """
        unique_terms: list[str] = list(dict.fromkeys(terms))

        if not unique_terms:
            print(f"[{self.name}] No terms to cluster.")
            return self._term_mapping.data

        freq = frequencies or {}

        # ── Step 0: pre-merge by normalized form (no SapBERT) ────────────────
        norm_groups: dict[str, list[str]] = defaultdict(list)
        for t in unique_terms:
            norm_groups[normalize_term(t)].append(t)

        pre_merged: dict[str, str] = {}
        embed_terms: list[str] = []
        for members in norm_groups.values():
            canonical = max(
                members,
                key=lambda t: (freq.get(t, 0), len(normalize_term(t).split()), -len(t)),
            )
            embed_terms.append(canonical)
            for t in members:
                if t != canonical:
                    pre_merged[t] = canonical

        if pre_merged:
            print(f"[{self.name}] Pre-merged {len(pre_merged)} terms by normalized form.")

        print(f"[{self.name}] Embedding {len(embed_terms)} terms with SapBERT...")
        emb: np.ndarray = embedder.embed(embed_terms)
        sim_matrix: np.ndarray = emb @ emb.T

        n = len(embed_terms)
        term_to_idx = {t: i for i, t in enumerate(embed_terms)}

        # ── Step 1: valid pairs ───────────────────────────────────────────────
        rows, cols = np.where(sim_matrix >= similarity_threshold)
        valid: set[tuple[int, int]] = set()
        for i, j in zip(rows.tolist(), cols.tolist()):
            if i >= j:
                continue
            a, b = embed_terms[i], embed_terms[j]
            if (_is_generic(a) or _is_generic(b)) and _string_sim(a, b) < 0.90:
                continue
            valid.add((i, j))

        print(f"[{self.name}] {len(valid)} valid pairs "
              f"(cosine ≥ {similarity_threshold}) …")

        # ── Step 2: complete-linkage clustering ───────────────────────────────
        cluster_of: list[int]          = list(range(n))
        cl_members: dict[int, set[int]] = {i: {i} for i in range(n)}

        for i, j in sorted(valid, key=lambda p: sim_matrix[p[0], p[1]], reverse=True):
            ci, cj = cluster_of[i], cluster_of[j]
            if ci == cj:
                continue
            if all(
                (min(a, b), max(a, b)) in valid
                for a in cl_members[ci]
                for b in cl_members[cj]
            ):
                for k in cl_members[cj]:
                    cluster_of[k] = ci
                cl_members[ci] |= cl_members[cj]
                del cl_members[cj]

        clusters: dict[int, list[str]] = defaultdict(list)
        for idx, term in enumerate(embed_terms):
            clusters[cluster_of[idx]].append(term)

        # ── Step 3: pick canonical per cluster ───────────────────────────────
        assignment: dict[str, str] = {}
        for members in clusters.values():
            canonical = max(
                members,
                key=lambda t: (freq.get(t, 0), len(normalize_term(t).split()), -len(t)),
            )
            for t in members:
                assignment[t] = canonical

        n_non_identity = sum(1 for t, c in assignment.items() if t != c)
        max_size       = max(len(v) for v in clusters.values())
        print(f"[{self.name}] {len(clusters)} clusters; "
              f"{n_non_identity} non-identity mappings; "
              f"max cluster size: {max_size}")

        assert all(assignment[c] == c for c in assignment.values()), \
            "Canonical terms must map to themselves"

        # ── Step 4: resolve pre-merged terms and build metadata ───────────────
        metadata_batch: dict[str, dict] = {}

        for orig, pre_canon in pre_merged.items():
            final = assignment.get(pre_canon, pre_canon)
            assignment[orig] = final
            metadata_batch[orig] = {"standard": final, "confidence": 1.0,
                                    "method": "string_norm"}

        for term, canonical in assignment.items():
            if term in pre_merged:
                continue
            idx_t = term_to_idx[term]
            idx_c = term_to_idx[canonical]
            metadata_batch[term] = {
                "standard": canonical,
                "confidence": float(sim_matrix[idx_t, idx_c]),
                "method": "sapbert_cluster",
            }

        self._term_mapping.add_batch(assignment, metadata_batch)
        return self._term_mapping.data
