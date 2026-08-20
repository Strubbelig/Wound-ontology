from __future__ import annotations
import asyncio
import pandas as pd
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.utils.string_utils import smart_title


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
        # Rows are formal object names and should look nicer in title case.
        # Columns are predicates/targets and are normalized to lower case for stable grouping.
        df.index = df.index.astype(str).map(smart_title)
        df.columns = df.columns.astype(str).str.strip().str.lower()

        # 2. Separate attribute and metadata columns
        is_meta = df.columns.str.startswith("meta_")
        attr_df = df.loc[:, ~is_meta].copy()
        meta_df = df.loc[:, is_meta].copy()

        # 3. Process attributes (strictly numeric)
        if not attr_df.empty:
            # Coerce any non-numeric values to NaN and collapse duplicates by max.
            attr_df = attr_df.apply(lambda x: pd.to_numeric(x, errors='coerce'))
            attr_df = attr_df.T.groupby(level=0).max().T
            attr_df = attr_df.groupby(level=0).max()

        # 4. Process metadata (strictly string)
        if not meta_df.empty:
            # Keep the first metadata value when duplicate rows are merged.
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

    # ── Undecided cells ────────────────────────────────────────────────────────
    #
    # A NaN in this matrix means "not decided", which is NOT the same as "false"
    # and emphatically not the same as "true". It must never reach the FCA
    # Context: `concepts` coerces each cell with bool(), and bool(float('nan'))
    # is True, so every undecided cell would silently assert that the attribute
    # holds — manufacturing shared intents and therefore invented superclasses.

    UNKNOWN_ABSENT = "absent"     # pessimistic: undecided -> attribute does not hold
    UNKNOWN_PRESENT = "present"   # optimistic:  undecided -> attribute holds

    def tuples(self, unknown: str = UNKNOWN_ABSENT):
        """Boolean rows for FCA, with an explicit policy for undecided cells.

        `unknown` must be UNKNOWN_ABSENT or UNKNOWN_PRESENT. There is
        deliberately no default that lets NaN through.
        """
        if unknown not in (self.UNKNOWN_ABSENT, self.UNKNOWN_PRESENT):
            raise ValueError("unknown must be %r or %r, got %r"
                             % (self.UNKNOWN_ABSENT, self.UNKNOWN_PRESENT, unknown))
        fill = 1.0 if unknown == self.UNKNOWN_PRESENT else 0.0
        block = self.df.loc[:, self.attributes].fillna(fill)
        rows = [tuple(bool(v) for v in row) for row in block.values]
        assert not any(v is None for r in rows for v in r)
        return rows

    @property
    def bool_tuples(self):
        """Pessimistic boolean rows. Undecided cells are treated as ABSENT.

        Kept for callers that want a single lattice. Prefer `tuples()` with an
        explicit policy, or ConceptLattice's dual-lattice build, which keeps
        undecided cells undecided instead of guessing.
        """
        n = self.undecided_count
        if n:
            print(f"[ContextMatrix] {n} undecided cells treated as ABSENT for this "
                  f"lattice ({self.undecided_density:.1%} of the matrix). "
                  f"Use ConceptLattice's dual build to see what they would change.")
        return self.tuples(self.UNKNOWN_ABSENT)

    @property
    def undecided_count(self) -> int:
        """Number of undecided (NaN) attribute cells."""
        if self.df.empty or not self.attributes:
            return 0
        return int(self.df.loc[:, self.attributes].isna().sum().sum())

    @property
    def undecided_density(self) -> float:
        if self.df.empty or not self.attributes:
            return 0.0
        total = len(self.df.index) * len(self.attributes)
        return (self.undecided_count / total) if total else 0.0

    def undecided_cells(self) -> list[tuple[str, str]]:
        """Every (object, attribute) pair whose value is undecided."""
        if self.df.empty or not self.attributes:
            return []
        block = self.df.loc[:, self.attributes]
        return [
            (str(block.index[i]), str(block.columns[j]))
            for i, j in zip(*block.isna().values.nonzero())
        ]

    def nan_report(self, top: int = 10) -> None:
        """Print where the undecided cells actually are."""
        n = self.undecided_count
        if not n:
            print("[ContextMatrix] no undecided cells.")
            return
        block = self.df.loc[:, self.attributes]
        by_attr = block.isna().sum().sort_values(ascending=False)
        by_obj  = block.isna().sum(axis=1).sort_values(ascending=False)
        print(f"[ContextMatrix] {n} undecided cells "
              f"({self.undecided_density:.1%} of {len(block.index)}x{len(self.attributes)})")
        print("  worst attributes:")
        for a, c in by_attr.head(top).items():
            if c: print(f"    {int(c):5d}  {a}")
        print("  worst objects:")
        for o, c in by_obj.head(top).items():
            if c: print(f"    {int(c):5d}  {o}")

    @property
    def predicates(self) -> list[str]:
        return [col.split(':', 1)[0].strip() if ':' in col else "" for col in self.attributes]

    @property
    def targets(self) -> list[str]:
        return [col.split(':', 1)[1].strip() if ':' in col else col for col in self.attributes]

    def get_data(
        self,
        store,
        entities: set | None = None,
        predicates: list | None = None,
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

    async def fill_nan(self, llm, batch_size=20, entity_batch=5):
        """
        Evaluates all NaNs using batched LLM calls.

        batch_size   – concurrent LLM calls in flight at once.
        entity_batch – entities grouped into a single LLM call (reduces total calls ~entity_batch×).
        """
        valid_attributes = self.attributes
        total_nan = self.df[valid_attributes].isna().sum().sum()

        if total_nan == 0:
            print("No medical NaNs found.")
            return self.df

        # Pre-filter: only rows that actually have NaNs
        nan_entities = [
            obj for obj in self.df.index
            if self.df.loc[obj, valid_attributes].isna().any()
        ]
        print(f"Starting batched scrutiny: {total_nan} NaNs across "
              f"{len(nan_entities)} entities (batch={entity_batch}, concurrency={batch_size})...")

        # Build per-entity missing attribute lists
        entity_missing: dict[str, list[str]] = {
            obj: self.df.loc[obj, valid_attributes][self.df.loc[obj, valid_attributes].isna()].index.tolist()
            for obj in nan_entities
        }

        # Group entities into chunks for batched LLM calls
        chunks = [
            dict(list(entity_missing.items())[i:i + entity_batch])
            for i in range(0, len(entity_missing), entity_batch)
        ]

        sem = asyncio.Semaphore(batch_size)

        failed_chunks = 0

        async def process_chunk(chunk: dict[str, list[str]], chunk_id: int):
            nonlocal failed_chunks
            async with sem:
                try:
                    result = await llm.fill_nan_batch(chunk)
                except Exception as e:
                    failed_chunks += 1
                    print(f"  Chunk {chunk_id + 1}/{len(chunks)} FAILED ({type(e).__name__}: {e}) "
                          f"— {sum(len(v) for v in chunk.values())} cells stay undecided.")
                    return {}
                print(f"  Chunk {chunk_id + 1}/{len(chunks)} done ({len(chunk)} entities).")
                return result

        tasks = [process_chunk(chunk, i) for i, chunk in enumerate(chunks)]
        batch_results = await asyncio.gather(*tasks)

        # Three-way write-back. Only an explicit verdict changes a cell; anything
        # the model did not rule on stays NaN. Writing 0 for "not mentioned"
        # would record uncertainty as a definite "does not hold".
        current_df = self.df.copy()
        n_conf = n_deny = 0
        for batch in batch_results:
            if not batch:
                continue
            for obj_name, verdict in batch.items():
                if obj_name not in entity_missing:
                    continue
                asked = set(entity_missing[obj_name])
                confirmed = asked & set(verdict.get("confirmed", ()))
                denied    = asked & set(verdict.get("denied", ())) - confirmed
                for attr in confirmed:
                    current_df.at[obj_name, attr] = 1
                    n_conf += 1
                for attr in denied:
                    current_df.at[obj_name, attr] = 0
                    n_deny += 1

        still_undecided = total_nan - n_conf - n_deny
        print(f"  verdicts: {n_conf} confirmed, {n_deny} denied, "
              f"{still_undecided} left undecided"
              + (f" ({failed_chunks} chunk(s) failed)" if failed_chunks else ""))

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
