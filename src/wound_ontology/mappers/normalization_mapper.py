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

    async def get_data(self, terms: list[str], llm, batch_size=5):
        """
        Normalizes medical terms in parallel waves.
        batch_size: How many chunks of 30 to process simultaneously.
        """
        terms_to_map = [t for t in terms if t not in self.originals]

        if not terms_to_map:
            print(f"[{self.name}] All {len(terms)} terms found in cache.")
            return self.mapping

        chunks = [terms_to_map[i:i + 30] for i in range(0, len(terms_to_map), 30)]
        print(f"[{self.name}] Found {len(terms_to_map)} new terms. Processing {len(chunks)} async chunks...")

        sem = asyncio.Semaphore(batch_size)

        async def process_chunk(chunk, chunk_id):
            async with sem:
                results = await llm.create_normalization_mapping(chunk, self.standards)
                print(f"[{self.name}] Chunk {chunk_id+1} complete.")
                return results

        tasks = [process_chunk(chunk, i) for i, chunk in enumerate(chunks)]

        for f in asyncio.as_completed(tasks):
            try:
                batch_results = await f
                self.mapping = batch_results
            except Exception as e:
                print(f"[{self.name}] Chunk failed ({type(e).__name__}): {e} — skipping.")

        print(f"[{self.name}] Normalization complete. Total terms in cache: {len(self.originals)}")
        return self.mapping


class TermMapper(NormalizationMapper):
    """
    Single mapper for all ontology terms — entities and targets share one
    normalization table so the same concept maps to the same standard regardless
    of whether it appears as an object or as the target of a predicate.
    """
    def __init__(self, data_manager: DataManager):
        super().__init__(
            mapper_name="Term mapper (entities + targets)",
            data_manager=data_manager,
            file_name="term_mapping",
        )
