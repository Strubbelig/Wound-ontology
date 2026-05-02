from __future__ import annotations
import asyncio
import pandas as pd
from wound_ontology.mappers.base_mapper import BaseMapper
from wound_ontology.data_manager.data_manager import DataManager


class NormalizationMapper(BaseMapper):
    def __init__(self, mapper_name, data_manager: DataManager, file_name):
        super().__init__(
            mapper_name=mapper_name,
            data_manager=data_manager,
            file_name=file_name
        )

    @property
    def standards(self) -> list[str]:
        """Read-only unique list of the 'clean' ontology terms."""
        return sorted(list(set(self._mapping.values())))

    @property
    def originals(self) -> list[str]:
        """Read-only list of all raw terms we have already processed."""
        return sorted(list(self._mapping.keys()))

    def map(self, term: str) -> str:
        """Map a single term, returning it unchanged if not in the mapping."""
        return self._mapping.get(term, term)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the mapping to both index and columns (unmapped entries kept as-is)."""
        return df.rename(index=self._mapping, columns=self._mapping)

    async def get_data(self, terms: list[str], llm, batch_size=10, chunk_size=50):
        """
        Normalizes medical terms in parallel waves.

        batch_size  – concurrent LLM calls in flight at once.
        chunk_size  – terms per LLM call (larger = fewer calls).
        """
        terms_to_map = [t for t in terms if t not in self.originals]

        if not terms_to_map:
            print(f"[{self.name}] All {len(terms)} terms found in cache.")
            return self.mapping

        chunks = [terms_to_map[i:i + chunk_size] for i in range(0, len(terms_to_map), chunk_size)]
        print(f"[{self.name}] Found {len(terms_to_map)} new terms → "
              f"{len(chunks)} chunks (size={chunk_size}, concurrency={batch_size})...")

        sem = asyncio.Semaphore(batch_size)

        async def process_chunk(chunk, chunk_id):
            async with sem:
                results = await llm.create_normalization_mapping(chunk, self.standards)
                print(f"[{self.name}] Chunk {chunk_id + 1}/{len(chunks)} complete.")
                return results

        tasks = [process_chunk(chunk, i) for i, chunk in enumerate(chunks)]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge all results in memory, then save once
        accumulated = {}
        for i, result in enumerate(all_results):
            if isinstance(result, Exception):
                print(f"[{self.name}] Chunk {i + 1} failed ({type(result).__name__}): {result} — skipping.")
            else:
                accumulated.update(result)

        if accumulated:
            self._mapping.update(accumulated)
            self.save()

        print(f"[{self.name}] Normalization complete. Total terms in cache: {len(self.originals)}")
        return self.mapping


class TermMapper(NormalizationMapper):
    """
    Normalization mapper for ontology terms — can be used for entity names,
    predicate targets, or both (the legacy single-mapper mode).
    """
    def __init__(
        self,
        data_manager: DataManager,
        file_name: str = "term_mapping",
        mapper_name: str | None = None,
    ):
        super().__init__(
            mapper_name=mapper_name or "Term mapper (entities + targets)",
            data_manager=data_manager,
            file_name=file_name,
        )
