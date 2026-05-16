from __future__ import annotations

import asyncio
import re
from collections import defaultdict
import numpy as np
import pandas as pd

from rapidfuzz.fuzz import ratio as _fuzz_ratio
from sklearn.metrics.pairwise import cosine_similarity

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.utils.string_utils import normalize_term

# ---------------------------------------------------------------------------
# Module-level helpers for synonym merging
# ---------------------------------------------------------------------------

_GENERIC_TERMS: frozenset[str] = frozenset({
    "wound", "pain", "skin", "patient", "female", "male",
    "chronic", "acute", "severe", "infection", "tissue",
    "leg", "foot", "scar", "burn", "ulcer", "sore",
    "symptom", "complication", "deformity", "crystal",
    "vagina", "pathogen", "geriatric", "hand", "valid",
})


def _string_sim(a: str, b: str) -> float:
    """Normalized edit-distance similarity on canonicalized strings."""
    return _fuzz_ratio(normalize_term(a), normalize_term(b)) / 100.0


def _is_generic(term: str) -> bool:
    return normalize_term(term) in _GENERIC_TERMS


def _is_abbreviation_pair(a: str, b: str) -> bool:
    """True if one term is an acronym / parenthetical abbreviation of the other."""
    def _check(abbr: str, phrase: str) -> bool:
        abbr_up = re.sub(r'[^A-Z0-9]', '', abbr.upper())
        if not abbr_up:
            return False
        # Parenthetical: "Diabetic Foot Ulcer (DFU)" contains "(DFU)"
        paren = re.search(r'\(([A-Z0-9]+)\)', phrase)
        if paren and paren.group(1).upper() == abbr_up:
            return True
        # Initial-letter acronym: DFU → Diabetic Foot Ulcer
        words = re.sub(r'[^\w\s]', ' ', phrase).split()
        initials = ''.join(w[0].upper() for w in words if w)
        return abbr_up == initials

    return _check(a, b) or _check(b, a)


class TermMapper:
    def __init__(
        self,
        data_manager: DataManager,
        file_name: str = "term_mapping",
        mapper_name: str | None = None,
    ):
        """
        This mapper evolves the simple dictionary-based mapper into a:

        - semantic matcher (via embeddings)
        - incremental learner (handles new terms without recomputing everything)
        - human-in-the-loop system (via CSV review)

        IMPORTANT:
        self._mapping is the final truth:
            term → standard
        """

        self.name = mapper_name or "Term mapper"
        self.dm = data_manager
        self.file_name = file_name
        self._mapping = self.dm.load_latest_json(self.file_name) or {}

        # ----------------------------
        # NEW INTERNAL STATE
        # ----------------------------

        # Cache: standard term → embedding vector
        # avoids recomputing embeddings every time
        self._standard_embeddings: dict[str, np.ndarray] = {}

        # Metadata per term (confidence, method, etc.)
        # This is NOT required for mapping, but critical for:
        # - auditing
        # - human review
        self._metadata: dict[str, dict] = {}

        # Terms we failed to confidently map
        self._unresolved_terms: list[str] = []

        # Below this confidence → send to human review
        self._review_threshold: float = 0.75

    # ----------------------------
    # EXISTING API (unchanged)
    # ----------------------------

    @property
    def mapping(self) -> dict:
        """Access the underlying mapping dictionary."""
        return self._mapping

    @mapping.setter
    def mapping(self, new_data: dict):
        """Updates the mapping and automatically triggers a save."""
        if not isinstance(new_data, dict):
            raise TypeError("mapping must be updated with a dict")
        self._mapping.update(new_data)
        self.save()

    def save(self):
        """Persist the mapping state via DataManager."""
        if self._mapping:
            print(f"[{self.name}] Saving updated mapping...")
            self.dm.save_as_json(self._mapping, self.file_name)

    @property
    def standards(self) -> list[str]:
        """
        Unique list of all canonical terms (targets of mapping).
        """
        return sorted(list(set(self._mapping.values())))

    @property
    def originals(self) -> list[str]:
        """
        All raw terms we've already seen.
        """
        return sorted(list(self._mapping.keys()))

    def map(self, term: str) -> str:
        """
        Simple lookup.
        If term not found → return it unchanged.
        """
        return self._mapping.get(term, term)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply mapping to a dataframe (index + columns).
        """
        return df.rename(index=self._mapping, columns=self._mapping)

    # ----------------------------
    # EMBEDDING UTILITIES
    # ----------------------------

    async def _ensure_standard_embeddings(self, client):
        """
        Make sure every standard has an embedding.

        WHY:
        We compare new terms to standards using vector similarity.
        So every standard must have a vector representation.

        Only computes missing ones (important for performance).
        """
        missing = [s for s in self.standards if s not in self._standard_embeddings]

        if not missing:
            return

        print(f"[{self.name}] Embedding {len(missing)} new standards...")

        embeddings = await client.create_embeddings(missing)

        for s, emb in zip(missing, embeddings):
            self._standard_embeddings[s] = np.array(emb)

    def _nearest_standard(self, emb: np.ndarray):
        """
        Given a term embedding, find the closest standard.

        RETURNS:
            (best_standard, similarity_score)

        HOW:
        - stack all standard embeddings into a matrix
        - compute cosine similarity
        - pick the highest score

        cosine similarity:
            1.0 = identical meaning
            0.0 = unrelated
        """
        if not self._standard_embeddings:
            return None, 0.0

        standards = list(self._standard_embeddings.keys())
        matrix = np.vstack([self._standard_embeddings[s] for s in standards])

        sims = cosine_similarity([emb], matrix)[0]
        idx = int(np.argmax(sims))

        return standards[idx], float(sims[idx])

    # ----------------------------
    # INCREMENTAL MAPPING (CORE LOGIC)
    # ----------------------------

    async def map_new_terms(self, terms: list[str], client):
        """Disabled — LLM mapping removed. Use build_from_embeddings() instead."""
        raise NotImplementedError(
            "LLM-based mapping is disabled. Use build_from_embeddings(terms, embedder) instead."
        )

    # ----------------------------
    # BULK MODE (INITIAL LOAD)
    # ----------------------------

    async def build_mapping(self, terms: list[str], client, batch_size=10, chunk_size=50):
        """Disabled — LLM mapping removed. Use build_from_embeddings() instead."""
        raise NotImplementedError(
            "LLM-based mapping is disabled. Use build_from_embeddings(terms, embedder) instead."
        )

    async def get_data(self, terms: list[str], client, batch_size=10, chunk_size=50):
        """Disabled — LLM mapping removed. Use build_from_embeddings() instead."""
        raise NotImplementedError(
            "LLM-based mapping is disabled. Use build_from_embeddings(terms, embedder) instead."
        )

    # ----------------------------
    # SAPBERT CLUSTERING
    # ----------------------------

    # ── Main clustering method ────────────────────────────────────────────────

    def build_from_embeddings(
        self,
        terms: list[str],
        embedder,
        similarity_threshold: float = 0.95,
        string_threshold: float = 0.92,
        frequencies: dict[str, int] | None = None,
    ) -> dict:
        """
        High-precision synonym clustering via SapBERT + dual-threshold guard.

        MERGE CONDITION — applied in order:
          0. normalize_term(a) == normalize_term(b)  (pure string, no SapBERT)
             — collapses case/hyphen/abbreviation variants before any embedding,
               e.g. "Systemic Sclerosis" ↔ "Systemic Sclerosis (SSc)"
          1. cosine_similarity >= similarity_threshold  (default 0.95)
          2. string_sim(a, b) >= string_threshold       (default 0.92)
             — ensures only near-identical surface forms merge,
               e.g. "Wound Healing" ↔ "wound healing" but NOT
               "full thickness" ↔ "full thickness burn"
          3. EXCEPTION: known abbreviation pairs bypass string check
             e.g. "DFU" ↔ "Diabetic Foot Ulcer (DFU)"
          4. Generic single-word terms (wound, pain, skin…) require
             string_sim >= 0.90 regardless of cosine score.

        Clustering uses Union-Find (connected components) so transitivity
        is preserved within the above strict guards.
        """
        unique_terms: list[str] = list(dict.fromkeys(terms))

        if not unique_terms:
            print(f"[{self.name}] No terms to cluster.")
            return self._mapping

        freq = frequencies or {}

        # ── Step 0: pre-merge by normalized form (no SapBERT) ─────────────────
        # Groups terms that are identical after normalize_term (strips trailing
        # abbreviations, lowercases, collapses hyphens/whitespace) into one
        # canonical before any embedding is computed.
        norm_groups: dict[str, list[str]] = defaultdict(list)
        for t in unique_terms:
            norm_groups[normalize_term(t)].append(t)

        pre_merged: dict[str, str] = {}   # non-canonical orig → pre-merge canonical
        embed_terms: list[str] = []
        for members in norm_groups.values():
            canonical = max(members, key=lambda t: (freq.get(t, 0), len(t.split()), -len(t)))
            embed_terms.append(canonical)
            for t in members:
                if t != canonical:
                    pre_merged[t] = canonical

        if pre_merged:
            print(f"[{self.name}] Pre-merged {len(pre_merged)} terms by normalized form.")

        print(f"[{self.name}] Embedding {len(embed_terms)} terms with SapBERT...")
        emb = embedder.embed(embed_terms)  # (N, H), L2-normalized in embedder

        # Cosine similarity = dot product when embeddings are L2-normalized
        sim_matrix: np.ndarray = emb @ emb.T

        n = len(embed_terms)
        term_to_idx = {t: i for i, t in enumerate(embed_terms)}

        # --- Union-Find ---
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Vectorized: only check pairs that exceed the cosine threshold
        rows, cols = np.where(sim_matrix >= similarity_threshold)
        candidate_pairs = [(int(i), int(j)) for i, j in zip(rows, cols) if i < j]

        print(f"[{self.name}] {len(candidate_pairs)} candidate pairs above cosine {similarity_threshold}...")

        for i, j in candidate_pairs:
            a, b = embed_terms[i], embed_terms[j]

            # Generic terms: require near-identical strings
            if _is_generic(a) or _is_generic(b):
                if _string_sim(a, b) < 0.90:
                    continue

            # Abbreviation pairs bypass string-sim check
            elif _is_abbreviation_pair(a, b):
                pass  # merge unconditionally

            # Standard dual threshold
            elif _string_sim(a, b) < string_threshold:
                continue

            union(i, j)

        # Build clusters from union-find
        clusters: dict[int, list[str]] = defaultdict(list)
        for i, term in enumerate(embed_terms):
            clusters[find(i)].append(term)

        # Canonical = highest frequency, then most words, then shortest string
        assignment: dict[str, str] = {}
        for members in clusters.values():
            canonical = max(
                members,
                key=lambda t: (freq.get(t, 0), len(t.split()), -len(t)),
            )
            for t in members:
                assignment[t] = canonical

        # Validation
        n_non_identity = sum(1 for t, c in assignment.items() if t != c)
        cluster_sizes = [len(v) for v in clusters.values()]
        max_size = max(cluster_sizes)

        print(f"[{self.name}] {len(clusters)} clusters; "
              f"{n_non_identity} non-identity mappings; "
              f"max cluster size: {max_size}")

        if max_size >= 20:
            raise AssertionError(
                f"Max cluster size {max_size} ≥ 20 — threshold is too low, "
                "spurious merges detected. Raise similarity_threshold."
            )

        assert all(assignment[c] == c for c in assignment.values()), \
            "Canonical terms must map to themselves"

        # Resolve pre-merged terms through the cluster assignment and record metadata
        for orig, pre_canon in pre_merged.items():
            final = assignment.get(pre_canon, pre_canon)
            assignment[orig] = final
            self._metadata[orig] = {"standard": final, "confidence": 1.0, "method": "string_norm"}

        # Update metadata for terms that went through SapBERT clustering
        for term, canonical in assignment.items():
            if term in pre_merged:
                continue
            idx_t = term_to_idx[term]
            idx_c = term_to_idx[canonical]
            self._metadata[term] = {
                "standard": canonical,
                "confidence": float(sim_matrix[idx_t, idx_c]),
                "method": "sapbert_cluster",
            }

        self._mapping.update(assignment)
        self.save()
        return self._mapping

    # ----------------------------
    # HUMAN-IN-THE-LOOP
    # ----------------------------

    def export_review_csv(self, path: str):
        """
        Export LOW-CONFIDENCE mappings for human review.

        Human fills:
            reviewed_standard
            notes
        """

        rows = []

        for term, meta in self._metadata.items():
            if meta["confidence"] < self._review_threshold:
                rows.append({
                    "term": term,
                    "suggested_standard": meta["standard"],
                    "confidence": meta["confidence"],
                    "method": meta["method"],
                    "reviewed_standard": "",
                    "notes": ""
                })

        df = pd.DataFrame(rows)
        df.to_csv(path, index=False)

        print(f"[{self.name}] Exported {len(rows)} rows → {path}")

    def import_review_csv(self, path: str):
        """
        Re-ingest human-reviewed decisions.

        Any filled 'reviewed_standard' overrides the system.
        """

        df = pd.read_csv(path)

        updates = 0

        for _, row in df.iterrows():
            term = row["term"]
            reviewed = row.get("reviewed_standard")

            if pd.notna(reviewed) and str(reviewed).strip():
                reviewed = str(reviewed).strip()

                self._mapping[term] = reviewed

                self._metadata[term] = {
                    "standard": reviewed,
                    "confidence": 1.0,
                    "method": "manual"
                }

                updates += 1

        self.save()
        print(f"[{self.name}] Applied {updates} human-reviewed mappings.")

    # ----------------------------
    # UNRESOLVED RETRY
    # ----------------------------

    async def resolve_unresolved(self, client):
        """
        Retry unresolved terms in batch.

        Useful after standards improve.
        """

        if not self._unresolved_terms:
            print(f"[{self.name}] No unresolved terms.")
            return

        print(f"[{self.name}] Resolving {len(self._unresolved_terms)} terms...")

        results = await client.create_normalization_mapping(
            self._unresolved_terms,
            self.standards
        )

        for term, std in results.items():
            self._mapping[term] = std

            self._metadata[term] = {
                "standard": std,
                "confidence": 0.7,
                "method": "llm_retry"
            }

        self._unresolved_terms = []
        self.save()
