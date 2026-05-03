from __future__ import annotations

import asyncio
from collections import defaultdict
import numpy as np
import pandas as pd

from sklearn.metrics.pairwise import cosine_similarity

from wound_ontology.data_manager.data_manager import DataManager


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

        # ----------------------------
        # TUNING PARAMETERS
        # ----------------------------

        # Below this confidence → send to human review
        self._review_threshold: float = 0.75

        # Above this similarity → auto-map without LLM
        self._similarity_threshold: float = 0.85

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
        """
        Main production method.

        This replaces "re-run everything" with:
            → only process NEW terms

        PIPELINE:

        for each term:
            1. try similarity match (cheap, fast)
            2. if uncertain → call LLM
            3. assign confidence score
            4. store metadata
        """

        new_terms = [t for t in terms if t not in self._mapping]

        if not new_terms:
            print(f"[{self.name}] No new terms to map.")
            return self.mapping

        print(f"[{self.name}] Mapping {len(new_terms)} new terms...")

        # ensure we can compare against standards
        await self._ensure_standard_embeddings(client)

        accumulated = {}

        for term in new_terms:
            try:
                # --- STEP 1: embed the term ---
                emb = np.array((await client.create_embeddings([term]))[0])

                # --- STEP 2: similarity match ---
                best_std, score = self._nearest_standard(emb)

                if best_std and score >= self._similarity_threshold:
                    # HIGH CONFIDENCE → auto accept
                    accumulated[term] = best_std

                    self._metadata[term] = {
                        "standard": best_std,
                        "confidence": float(score),
                        "method": "similarity"
                    }
                    continue

                # --- STEP 3: LLM fallback ---
                # used only when similarity is not strong enough
                result = await client.create_normalization_mapping([term], self.standards)

                if result and term in result:
                    std = result[term]

                    # heuristic confidence (LLMs don't give real scores)
                    confidence = 0.6
                    if std == term:
                        confidence = 0.4  # weak mapping

                    accumulated[term] = std

                    self._metadata[term] = {
                        "standard": std,
                        "confidence": confidence,
                        "method": "llm"
                    }

                    # if LLM invented a NEW standard → embed it
                    if std not in self._standard_embeddings:
                        std_emb = (await client.create_embeddings([std]))[0]
                        self._standard_embeddings[std] = np.array(std_emb)

                else:
                    # completely failed case
                    self._unresolved_terms.append(term)

                    self._metadata[term] = {
                        "standard": None,
                        "confidence": 0.0,
                        "method": "unresolved"
                    }

            except Exception as e:
                print(f"[{self.name}] Failed to map '{term}': {e}")
                self._unresolved_terms.append(term)

        # persist results
        if accumulated:
            self._mapping.update(accumulated)
            self.save()

        print(f"[{self.name}] Mapping complete.")
        print(f"[{self.name}] Unresolved: {len(self._unresolved_terms)}")

        return self.mapping

    # ----------------------------
    # BULK MODE (INITIAL LOAD)
    # ----------------------------

    async def build_mapping(self, terms: list[str], client, batch_size=10, chunk_size=50):
        """
        Build the shared medical-term mapping dictionary.

        Use this ONCE to bootstrap your mapping.
        After that → use map_new_terms()

        This still uses LLM heavily (less efficient).
        """

        terms_to_map = [t for t in terms if t not in self.originals]

        if not terms_to_map:
            print(f"[{self.name}] All terms cached.")
            return self.mapping

        print(f"[{self.name}] Building mappings for {len(terms_to_map)} terms...")

        chunks = [terms_to_map[i:i + chunk_size] for i in range(0, len(terms_to_map), chunk_size)]
        sem = asyncio.Semaphore(batch_size)

        async def process_chunk(chunk, chunk_id):
            async with sem:
                results = await client.create_normalization_mapping(chunk, self.standards)
                print(f"[{self.name}] Chunk {chunk_id + 1}/{len(chunks)} complete.")
                return results

        tasks = [process_chunk(chunk, i) for i, chunk in enumerate(chunks)]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        accumulated = {}

        for result in all_results:
            if not isinstance(result, Exception):
                for term, std in result.items():
                    accumulated[term] = std

                    self._metadata[term] = {
                        "standard": std,
                        "confidence": 0.6,
                        "method": "llm_bulk"
                    }

        if accumulated:
            self._mapping.update(accumulated)
            self.save()

        return self.mapping

    async def get_data(self, terms: list[str], client, batch_size=10, chunk_size=50):
        """Backwards-compatible alias for build_mapping()."""
        return await self.build_mapping(terms, client, batch_size=batch_size, chunk_size=chunk_size)

    # ----------------------------
    # SAPBERT CLUSTERING
    # ----------------------------

    def build_from_embeddings(
        self,
        terms: list[str],
        embedder,
        similarity_threshold: float = 0.92,
        frequencies: dict[str, int] | None = None,
    ) -> dict:
        """
        Build term mapping by SapBERT cosine-similarity clustering (union-find).

        Algorithm:
        1. Embed all unique terms with SapBERT.
        2. Compute pairwise cosine similarity.
        3. Union pairs above similarity_threshold into clusters.
        4. Elect the most frequent term as canonical (tie-break: longest, then alphabetical).

        After this returns, call:
            mapping_cleaner.review_merged_mappings()
            mapping_cleaner.apply(store)
        """
        unique_terms: list[str] = list(dict.fromkeys(terms))

        if not unique_terms:
            print(f"[{self.name}] No terms to cluster.")
            return self._mapping

        freq = frequencies or {}

        print(f"[{self.name}] Embedding {len(unique_terms)} unique terms with SapBERT...")
        embeddings = embedder.embed(unique_terms)   # (N, hidden_size)

        print(f"[{self.name}] Computing pairwise similarity ({len(unique_terms)}×{len(unique_terms)})...")
        sim_matrix = cosine_similarity(embeddings)  # (N, N)

        # ── union-find ────────────────────────────────────────────────────────
        parent = list(range(len(unique_terms)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        n_merges = 0
        n = len(unique_terms)
        for i in range(n):
            for j in range(i + 1, n):
                if sim_matrix[i, j] >= similarity_threshold:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
                        n_merges += 1

        print(f"[{self.name}] Merged {n_merges} pairs (threshold={similarity_threshold}).")

        # ── elect canonical per cluster ───────────────────────────────────────
        clusters: dict[int, list[int]] = defaultdict(list)
        for idx in range(n):
            clusters[find(idx)].append(idx)

        accumulated: dict[str, str] = {}
        n_non_identity = 0

        for members in clusters.values():
            # most frequent → longest → alphabetical (deterministic)
            canonical_idx = min(
                members,
                key=lambda i: (-freq.get(unique_terms[i], 0), -len(unique_terms[i]), unique_terms[i]),
            )
            canonical = unique_terms[canonical_idx]

            for idx in members:
                raw = unique_terms[idx]
                accumulated[raw] = canonical
                self._metadata[raw] = {
                    "standard": canonical,
                    "confidence": 1.0 if raw == canonical else float(sim_matrix[canonical_idx, idx]),
                    "method": "sapbert_cluster",
                }
                if raw != canonical:
                    n_non_identity += 1

        print(f"[{self.name}] {len(clusters)} clusters; {n_non_identity} non-identity mappings.")

        self._mapping.update(accumulated)
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
