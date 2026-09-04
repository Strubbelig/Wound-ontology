from __future__ import annotations
import asyncio
import pandas as pd
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.utils.string_utils import smart_title


class ContextMatrix:

    def __init__(self, data_manager, file_name):
        self.dm = data_manager
        self.file_name = file_name
        self._df = self._load()
        # The matrix is a *view* of a ConceptStore, so it records which store it
        # was built from and with which restriction. That is what lets it
        # re-derive itself after the store changes (see rebuild), and it is why
        # nothing here may hold a value the store does not.
        self._store = None
        self._last_build: dict | None = None

    def _load(self):
        """Reload the saved matrix WITH its index restored.

        This used to hand back whatever ``load_latest_csv`` returned, which for
        a saved context is a RangeIndex plus an 'entity' *column* -- the row
        labels demoted to data. The df setter then concatenated that against a
        properly indexed frame, so nothing aligned: a 4114-row matrix reloaded
        and rebuilt came back with 8228 rows, 8227 of them duplicate entities,
        and 'entity' itself as an attribute column. Silent, and only on the
        SECOND run, because the first has no file to reload. BaseHierarchy has
        always restored its index here; this did not.
        """
        raw = self.dm.load_latest_csv(self.file_name)
        if raw is None or raw.empty:
            return raw
        if "Unnamed: 0" in raw.columns:
            raw = raw.drop(columns=["Unnamed: 0"])
        if "entity" in raw.columns:
            raw = raw.set_index("entity")
        elif not raw.columns.empty and raw.index.name is None:
            raw = raw.set_index(raw.columns[0])
        return raw

    @property
    def df(self):
        if self._df is None:
            self._df = pd.DataFrame()
        return self._df

    @df.setter
    def df(self, new_data: pd.DataFrame):
        """Replace the view. The matrix is derived from the store, never a store.

        This used to concatenate new_data onto whatever was reloaded from disk
        and merge the two, so every build was a union with every build before
        it. Three things followed, none of them announced: `entities` and
        `predicates` narrowed only the frame that got printed, while FCA was
        handed the accumulated matrix; conceptual scaling wrote its closed-world
        zeros only for the slice, so carried-over rows arrived as NaN in every
        scaled column and the double-lattice dissolved almost every concept into
        "undecided"; and objects the store no longer contained -- folded away by
        normalization, or rejected by the blocklist -- stayed in the matrix
        permanently.

        Every value here is re-derived from the ConceptStore on each build, so
        replacing discards nothing. Anything that must survive a rebuild belongs
        in the store: that is what fill_nan now does with its verdicts.
        """
        self._df = self.merge(new_data)
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
        scale_hierarchy=None,
        inherit_attributes: bool = True,
    ) -> None:
        """
        Build the FCA context matrix from a ConceptStore (already normalized).

        store      – ConceptStore instance (call normalize() on it first).
        entities   – restrict rows to this set of entity names (None = all).
        predicates – restrict columns to triples with these predicates, e.g.
                     ['has_quality', 'caused_by']. None = all.
        scale_hierarchy
                   – conceptual scaling (Ganter): a BaseHierarchy whose
                     superclasses are added to each object as extra ``is_a:``
                     attributes. FCA orders objects purely by attribute-set
                     containment, so without this the lattice cannot see the
                     taxonomy at all: two entities in a known subclass relation
                     that happen to share no measured attribute come out as
                     unrelated siblings. Adding every ancestor makes a
                     subclass's attribute set a strict superset of its
                     parent's, which forces the lattice into an order
                     consistent with the hierarchy while leaving it free to
                     discover structure *between* asserted edges.

                     Scaling is applied after the `predicates` filter and is
                     deliberately not subject to it -- the whole point is to
                     inject subsumption that filter would otherwise exclude.
                     Only objects that already have store attributes are
                     augmented; scaling adds attributes, never rows.
        inherit_attributes
                   – propagate each ancestor's own attributes down to its
                     subclasses. Required for the guarantee above, and NOT
                     implied by the superclass attributes alone: if the parent
                     carries `has_quality: slow healing` and the child does not,
                     the child's attribute set is not a superset of the parent's
                     however many `is_a:` columns are added, so the lattice is
                     still free to order them the wrong way round. Sound here
                     because these are class-level assertions -- an axiom on a
                     superclass holds of every subclass.
        """
        flat_map: dict[str, dict] = {}

        # Remember what this view is of, before anything can go wrong, so that
        # rebuild() can re-derive exactly this slice once the store changes.
        self._store = store
        self._last_build = {
            "entities": entities,
            "predicates": predicates,
            "scale_hierarchy": scale_hierarchy,
            "inherit_attributes": inherit_attributes,
        }

        # `entities` normally comes from hierarchy.subtree_of(), whose names are
        # smart_title'd; store keys are as extracted. Comparing them raw matched
        # only 302 of 4180 names on a real store, so a subtree restriction
        # silently dropped ~93% of its own subtree -- subtree_root="Wound"
        # returned a one-object context and looked like thin source data.
        if entities is not None:
            entities = {smart_title(e) for e in entities}

        for pmid_data in store.dict.values():
            for entity_name, attrs in pmid_data.get("entities", {}).items():
                if entities is not None and smart_title(entity_name) not in entities:
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

        if scale_hierarchy is not None:
            # Curated edges are no longer pushed through the store -- they are read
            # straight from WONT and MILD -- so a concept the corpus never mentions
            # has no store record at all. Without this it would drop silently out
            # of its own subtree, and a 40-object context would arrive as a
            # 1-object one that merely looked like thin source data. An object
            # with no measured attributes is a true statement about the corpus;
            # an absent object is not.
            #
            # Only CURATED concepts are added. Scaling still may not invent
            # objects of its own: a concept known only from an accepted FCA slice
            # would feed the analysis its own previous output, and one known only
            # from a text edge has a store record already by construction.
            from wound_ontology.hierarchies.base_hierarchy import SOURCE_CURATED
            seen = {smart_title(e) for e in flat_map}
            placed = 0
            for concept in scale_hierarchy.concepts_from({SOURCE_CURATED}):
                name = smart_title(concept)
                if name in seen:
                    continue
                if entities is not None and name not in entities:
                    continue
                flat_map[name] = {}
                seen.add(name)
                placed += 1
            if placed:
                print(f"[ContextMatrix] {placed} object(s) come from the curated "
                      f"source alone — concepts the corpus does not mention. They "
                      f"carry no measured attributes, only scaled ones.")

        if not flat_map:
            # The view must not outlive the slice it claims to be. Keeping the
            # previous frame here would leave the next run_fca analysing an
            # older restriction while reporting this one.
            had = 0 if self._df is None or self._df.empty else len(self._df.index)
            self._df = pd.DataFrame()
            self.save()
            print(f"No matching data in store for this slice"
                  + (f" — the previous view of {had} object(s) was cleared." if had
                     else "."))
            return

        if scale_hierarchy is not None:
            # Snapshot first: inheritance must read each ancestor's OWN
            # attributes, not ones it picked up earlier in this same loop.
            #
            # Keyed by the smart_title form, because that is what the hierarchy
            # returns and what the store does NOT use: a store keyed 'wound'
            # against an ancestor named 'Wound' silently inherits nothing, so
            # every subclass of Wound stays bare and the containment guarantee
            # quietly fails on exactly the edges it exists to protect.
            original: dict[str, dict] = {}
            for entity, attrs in flat_map.items():
                dest = original.setdefault(smart_title(entity), {})
                for attr, value in attrs.items():
                    dest[attr] = max(dest.get(attr, 0.0), value)
            membership = inherited = scaled_objects = 0
            scaled_keys: set[str] = set()
            for entity in list(flat_map):
                ancestors = scale_hierarchy.ancestors_of(entity)
                if not ancestors:
                    continue
                scaled_objects += 1
                for ancestor in ancestors:
                    # Same "pred: target" shape the store uses, so a curated
                    # edge that already came through as an is_a attribute
                    # collapses onto the scaled one instead of duplicating.
                    # merge() lowercases columns, so case cannot split them.
                    key = f"is_a: {smart_title(ancestor)}"
                    scaled_keys.add(key)
                    if key not in flat_map[entity]:
                        flat_map[entity][key] = 1.0
                        membership += 1
                    if not inherit_attributes:
                        continue
                    for attr, value in original.get(smart_title(ancestor), {}).items():
                        prev = flat_map[entity].get(attr)
                        if prev is None:
                            inherited += 1
                        flat_map[entity][attr] = max(prev or 0.0, value)
            # An is_a: column is CLOSED-WORLD: the hierarchy knows, for every
            # concept it holds, exactly which superclasses it has. Leaving the
            # other cells absent makes them NaN, i.e. "undecided", and the
            # lattice then has to be built twice (NaN as true and as false) with
            # only the concepts certain under both surviving. Measured on the
            # Wound subtree that meant 296 undecided cells, 11 pessimistic
            # concepts against 1 optimistic, and NOTHING named -- scaling made
            # the analysis strictly worse than not scaling at all.
            known = {e for e in flat_map
                     if smart_title(e) in scale_hierarchy.concepts}
            closed = 0
            for entity in known:
                for key in scaled_keys:
                    if key not in flat_map[entity]:
                        flat_map[entity][key] = 0.0
                        closed += 1
            print(f"[ContextMatrix] Conceptual scaling: {membership} superclass "
                  f"attributes + {inherited} inherited attributes across "
                  f"{scaled_objects}/{len(flat_map)} objects "
                  f"from {type(scale_hierarchy).__name__}; "
                  f"{closed} cells closed to 0 over {len(known)} placed objects.")
            unplaced = len(flat_map) - len(known)
            if unplaced:
                print(f"[ContextMatrix] {unplaced} object(s) are not in the "
                      f"hierarchy, so their is_a: cells stay undecided rather "
                      f"than being asserted false.")
            if scaled_objects == 0:
                print("[ContextMatrix] WARNING: no object had a known superclass, "
                      "so scaling changed nothing — the lattice is unconstrained "
                      "by the hierarchy. Was run_build_hierarchies() run first?")

        rows = [{"entity": e, **attrs} for e, attrs in flat_map.items()]
        new_data = pd.DataFrame(rows).set_index("entity")

        prev_rows = set() if self._df is None or self._df.empty else set(self._df.index)
        prev_cols = set() if self._df is None or self._df.empty else set(self._df.columns)

        self.df = new_data

        # Replacing is the contract, but it is still a loss of what was on
        # screen a moment ago, so it is stated rather than left to be noticed.
        gone_rows = len(prev_rows - set(self.df.index))
        gone_cols = len(prev_cols - set(self.df.columns))
        if gone_rows or gone_cols:
            print(f"[ContextMatrix] view replaced: {gone_rows} object(s) and "
                  f"{gone_cols} attribute(s) from the previous view are outside "
                  f"this slice. Nothing is lost — the store holds all of it.")

        print(f"FCA matrix built: {len(self.df)} entities × {len(self.attributes)} triples.")

    def rebuild(self) -> None:
        """Re-derive this view from the store it was built from.

        Used after anything writes to the store, so the matrix follows the store
        instead of drifting from it.
        """
        if self._store is None or self._last_build is None:
            raise ValueError(
                "This matrix has not been built from a store yet, so there is "
                "nothing to re-derive. Call get_data(store, ...) first."
            )
        self.get_data(self._store, **self._last_build)

    async def fill_nan(self, llm, store=None, batch_size=20, entity_batch=5):
        """
        Evaluate every undecided cell with batched LLM calls, writing the
        verdicts back into the ConceptStore.

        store        – the ConceptStore these verdicts belong to. Defaults to the
                       one this view was built from.
        batch_size   – concurrent LLM calls in flight at once.
        entity_batch – entities grouped into a single LLM call (reduces total calls ~entity_batch×).

        The verdicts used to be written into the matrix and nowhere else, which
        made them the only values here that were not derived from the store --
        and therefore the only ones a rebuild destroyed. They are store data:
        a human-or-model judgement that "chronic wound has_quality slow healing"
        holds is a fact about the domain, not about one FCA slice. Writing them
        to the store means they survive, they are visible next to the extracted
        material, and they are re-derived into every later view that includes
        the entity -- including views built for a different subtree.
        """
        target = store if store is not None else self._store
        if target is None:
            raise ValueError(
                "fill_nan needs the ConceptStore these verdicts belong to. The "
                "matrix is a view, so a verdict written only here is destroyed by "
                "the next build. Pass store=..., or call get_data(store, ...) "
                "first so the matrix knows which store it is a view of."
            )

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
        verdicts: dict[str, dict[str, float]] = {}
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
                if not confirmed and not denied:
                    continue
                dest = verdicts.setdefault(obj_name, {})
                for attr in confirmed:
                    dest[attr] = 1.0
                    n_conf += 1
                for attr in denied:
                    dest[attr] = 0.0
                    n_deny += 1

        still_undecided = total_nan - n_conf - n_deny
        print(f"  verdicts: {n_conf} confirmed, {n_deny} denied, "
              f"{still_undecided} left undecided"
              + (f" ({failed_chunks} chunk(s) failed)" if failed_chunks else ""))

        if not verdicts:
            print("Nothing to write back; the view is unchanged.")
            return self.df

        verdicts = self._to_store_casing(verdicts, target)
        target.merge_entity_records(verdicts, kind="llm_fill_nan")
        # Follow the store rather than edit the view in place: the verdicts are
        # now store data, so the matrix picks them up the same way it picks up
        # everything else.
        self.rebuild()
        return self.df

    @staticmethod
    def _to_store_casing(verdicts: dict[str, dict[str, float]], store) -> dict:
        """Write verdicts back under the attribute string the store already uses.

        merge() lowercases every column for stable grouping, so a view column
        reads "has_quality: slow healing" where the store holds
        "has_quality: Slow Healing". Writing the lowercased form back would put a
        second spelling of the same attribute into the store. The view would
        still look right -- merge() folds the two columns together -- but it
        folds them with max(), so a denial (0.0) sitting beside a later
        extraction's assertion (1.0) would lose without a word. Restoring the
        store's own casing keeps one attribute where there is one attribute.
        """
        canon: dict[str, str] = {}
        for record in store.dict.values():
            for attrs in record.get("entities", {}).values():
                for triple in attrs:
                    canon.setdefault(str(triple).strip().lower(), str(triple).strip())

        out: dict[str, dict[str, float]] = {}
        restored = 0
        for entity, attrs in verdicts.items():
            dest = out.setdefault(entity, {})
            for triple, value in attrs.items():
                key = canon.get(str(triple).strip().lower(), triple)
                if key != triple:
                    restored += 1
                dest[key] = value
        if restored:
            print(f"[ContextMatrix] {restored} verdict(s) written back under the "
                  f"store's existing spelling of the attribute.")
        return out

    def save(self):
        if not self.df.empty:
            self.dm.save_as_csv(self.df, self.file_name)
        else:
            print("Save skipped: Matrix is currently empty.")
