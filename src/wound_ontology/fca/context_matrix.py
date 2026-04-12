from __future__ import annotations
import asyncio
import pandas as pd
from pydantic import validate_call, ConfigDict
from wound_ontology.data_manager.data_manager import DataManager


class ContextMatrix:

    def __init__(self, data_manager, file_name):
        self.dm = data_manager
        self.file_name = file_name
        self._df = self.dm.load_latest_csv(self.file_name)

    @property
    def df(self):
        if self._df is None:
            self._df = pd.DataFrame()
        return self._df

    @df.setter
    @validate_call(config=ConfigDict(extra='forbid', arbitrary_types_allowed=True))
    def df(self, new_data: pd.DataFrame):
        """Adds new data and triggers a global merge."""
        if self._df is None or self._df.empty:
            combined = new_data
        else:
            combined = pd.concat([self._df, new_data], sort=False)

        self._df = self.merge(combined)
        self.save()

    def merge(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardizes, sanitizes, and collapses mixed-type data safely."""
        if df is None or df.empty:
            return df

        # 1. Standardize casings
        df.index = df.index.astype(str).str.strip().str.title()
        df.columns = df.columns.astype(str).str.strip().str.lower()

        # 2. Separate attribute and metadata columns
        is_meta = df.columns.str.startswith("meta_")
        attr_df = df.loc[:, ~is_meta].copy()
        meta_df = df.loc[:, is_meta].copy()

        # 3. Process attributes (strictly numeric)
        if not attr_df.empty:
            attr_df = attr_df.apply(lambda x: pd.to_numeric(x, errors='coerce'))
            attr_df = attr_df.T.groupby(level=0).max().T
            attr_df = attr_df.groupby(level=0).max()

        # 4. Process metadata (strictly string)
        if not meta_df.empty:
            meta_df = meta_df.T.groupby(level=0).first().T
            meta_df = meta_df.groupby(level=0).first()

        # 5. Recombine
        if not meta_df.empty and not attr_df.empty:
            return pd.concat([attr_df, meta_df], axis=1)
        elif not attr_df.empty:
            return attr_df
        else:
            return meta_df

    @property
    def objects(self):
        """Row names (formal objects)."""
        return list(self.df.index)

    @property
    def attributes(self):
        """Column names excluding metadata columns."""
        return [col for col in self.df.columns if not col.startswith("meta_")]

    @property
    def bool_tuples(self):
        return [tuple(row) for row in self.df.loc[:, self.attributes].values]

    @property
    def predicates(self) -> list[str]:
        return [col.split(':', 1)[0].strip() if ':' in col else "" for col in self.attributes]

    @property
    def targets(self) -> list[str]:
        return [col.split(':', 1)[1].strip() if ':' in col else col for col in self.attributes]

    def get_data(
        self,
        store,
        entities: set = None,
        predicates: list = None,
    ) -> None:
        """
        Build the FCA context matrix from a ConceptStore (already normalized).

        store      – ConceptStore instance (call normalize() on it first).
        entities   – restrict rows to this set of entity names (None = all).
        predicates – restrict columns to triples with these predicates, e.g.
                     ['has_quality', 'caused_by']. None = all.
        """
        flat_map: dict[str, dict] = {}

        for pmid_data in store.dict.values():
            for entity_name, attrs in pmid_data.get("entities", {}).items():
                if entities is not None and entity_name not in entities:
                    continue
                if entity_name not in flat_map:
                    flat_map[entity_name] = {}
                for triple, value in attrs.items():
                    if ":" not in str(triple):
                        continue
                    pred, tgt = triple.split(":", 1)
                    pred  = pred.strip().lower()
                    tgt   = tgt.strip()
                    triple = f"{pred}: {tgt}"
                    if predicates is not None and pred not in predicates:
                        continue
                    flat_map[entity_name][triple] = max(
                        flat_map[entity_name].get(triple, 0.0), value
                    )

        if not flat_map:
            print("No matching data in store for this slice.")
            return

        rows = [{"entity": e, **attrs} for e, attrs in flat_map.items()]
        new_data = pd.DataFrame(rows).set_index("entity")
        self.df = new_data

        print(f"FCA matrix built: {len(new_data)} entities × {len(new_data.columns)} triples.")

    async def fill_nan(self, llm, batch_size=10):
        """Evaluates all NaNs in parallel waves."""
        valid_attributes = self.attributes
        total_nan = self.df[valid_attributes].isna().sum().sum()

        if total_nan == 0:
            print("No medical NaNs found.")
            return self.df

        print(f"Starting parallel scrutiny for {total_nan} NaNs across {len(self.df)} objects...")

        sem = asyncio.Semaphore(batch_size)

        async def process_row(object_name):
            async with sem:
                row = self.df.loc[object_name, valid_attributes]
                missing = row[row.isna()].index.tolist()
                if not missing:
                    return object_name, [], []
                confirmed = await llm.fill_nan(object_name, missing)
                return object_name, confirmed, missing

        tasks = [process_row(obj) for obj in self.df.index]
        results = await asyncio.gather(*tasks)

        current_df = self.df.copy()
        for res in results:
            if res is None:
                continue
            obj_name, confirmed_list, original_missing = res
            for attr in original_missing:
                current_df.at[obj_name, attr] = 1 if attr in confirmed_list else 0

        meta_col, meta_id = self.dm.get_meta_stamp("llm_fill_nan")
        current_df[meta_col] = meta_id

        self._df = self.merge(current_df)
        self.save()

        print(f"Parallel evaluation complete. Stamp: {meta_id}")
        return self.df

    def save(self):
        if not self.df.empty:
            self.dm.save_as_csv(self.df, self.file_name)
        else:
            print("Save skipped: Matrix is currently empty.")
