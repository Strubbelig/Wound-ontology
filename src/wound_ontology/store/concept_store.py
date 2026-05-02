from __future__ import annotations
import asyncio
import pandas as pd
from pydantic import validate_call, ConfigDict
from wound_ontology.data_manager.data_manager import DataManager
from config.blocklists import METHODOLOGY_BLOCKLIST as _METHODOLOGY_BLOCKLIST


class ConceptStore:
    """
    Single staging area for all concept data — LLM extractions and predefined edges alike.

    Internal format (same as the old ExtractionCache):
      {
        "<pmid>": { "entities": { "<entity>": { "<pred>: <target>": 1.0 | 0.0 } }, "meta_stamp": "..." },
        "predefined": { "entities": { ... }, "meta_stamp": "predefined" },
      }

    Normalization (mapper + Title Case) is applied via normalize() after both LLM
    extraction and predefined ingestion are complete, so all downstream consumers
    (hierarchies, FCA matrix) receive clean, deduplicated names.
    """

    def __init__(self, data_manager: DataManager, file_name: str):
        self.dm = data_manager
        self.file_name = file_name
        self._dict = self.dm.load_latest_json(self.file_name)

    # ── Core storage ──────────────────────────────────────────────────────────

    @property
    def dict(self) -> dict:
        if self._dict is None:
            self._dict = {}
        return self._dict

    @dict.setter
    @validate_call(config=ConfigDict(extra='forbid', arbitrary_types_allowed=True))
    def dict(self, new_data: dict):
        self.dict.update(new_data)
        self.save()

    # ── Derived views ─────────────────────────────────────────────────────────

    @property
    def attributes(self) -> list[str]:
        """Unique predicate:target strings across all stored entities."""
        all_attrs: set[str] = set()
        for pmid_data in self.dict.values():
            for attr_dict in pmid_data.get("entities", {}).values():
                all_attrs.update(attr_dict.keys())
        return sorted([a for a in all_attrs if not a.startswith("meta_")])

    def top_attributes(self, n: int) -> list[str]:
        """Return the n most frequently occurring predicate:target strings (by entity count)."""
        from collections import Counter
        counts: Counter = Counter()
        for pmid_data in self.dict.values():
            for attr_dict in pmid_data.get("entities", {}).values():
                for attr, val in attr_dict.items():
                    if not attr.startswith("meta_") and val == 1.0:
                        counts[attr] += 1
        return [attr for attr, _ in counts.most_common(n)]

    @property
    def predicates(self) -> list[str]:
        return [a.split(':', 1)[0].strip() if ':' in a else "" for a in self.attributes]

    @predicates.setter
    def predicates(self, keep: list[str]) -> None:
        """Keep only attributes whose predicate is in `keep`, removing all others."""
        keep_set = set(keep)
        for pmid_data in self.dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                pmid_data["entities"][entity] = {
                    attr: val for attr, val in attrs.items()
                    if ':' not in attr or attr.split(':', 1)[0].strip() in keep_set
                }
        self.save()
        print(f"[ConceptStore] Predicates filtered — {len(keep_set)} allowed.")

    @property
    def targets(self) -> list[str]:
        return [a.split(':', 1)[1].strip() if ':' in a else a for a in self.attributes]

    @targets.setter
    def targets(self, keep: list[str]) -> None:
        """Keep only attributes whose target is in `keep`, removing all others."""
        keep_set = set(keep)
        for pmid_data in self.dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                pmid_data["entities"][entity] = {
                    attr: val for attr, val in attrs.items()
                    if ':' not in attr or attr.split(':', 1)[1].strip() in keep_set
                }
        self.save()
        print(f"[ConceptStore] Targets filtered — {len(keep_set)} allowed.")

    @property
    def entities(self) -> list[str]:
        """Unique entity names across the store."""
        all_entities: set[str] = set()
        for pmid_data in self.dict.values():
            all_entities.update(pmid_data.get("entities", {}).keys())
        return sorted(all_entities)

    @entities.setter
    def entities(self, keep: list[str]) -> None:
        """Keep only the listed entity names, removing all others from the store."""
        keep_set = set(keep)
        for pmid_data in self.dict.values():
            old = pmid_data.get("entities", {})
            pmid_data["entities"] = {k: v for k, v in old.items() if k in keep_set}
        self.save()
        print(f"[ConceptStore] Entities filtered — {len(keep_set)} kept.")

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def get_data(
        self,
        source,
        child_col: str = "Class",
        parent_col: str = "Parent class",
    ) -> None:
        """
        Ingest data into the store.

        source : pd.DataFrame
            Predefined edges with ``child_col`` and ``parent_col`` columns.
            Each row is converted to an ``is_a`` triple and stored under the
            key ``"predefined"``.
        source : dict
            Raw concept dict in the internal ``{ pmid: { entities: {...} } }``
            format — merged directly into the store.

        Call this *before* normalize() so all names are covered by the same
        mapping pass as the LLM extractions.
        """
        # Ensure _dict is initialised before writing
        _ = self.dict

        if isinstance(source, pd.DataFrame):
            pairs = source[[child_col, parent_col]].dropna().drop_duplicates()
            entities_map: dict[str, dict] = {}
            for _, row in pairs.iterrows():
                child  = str(row[child_col]).strip()
                parent = str(row[parent_col]).strip()
                entities_map.setdefault(child, {})[f"is_a: {parent}"] = 1.0
            self._dict["predefined"] = {"entities": entities_map, "meta_stamp": "predefined"}
            self.save()
            print(f"[ConceptStore] {len(pairs)} predefined edges stored.")
        elif isinstance(source, dict):
            self._dict.update(source)
            self.save()
            print(f"[ConceptStore] {len(source)} entries merged from dict.")
        else:
            raise TypeError(f"source must be a DataFrame or dict, got {type(source).__name__}")

    def normalize(self, entity_mapper=None, target_mapper=None) -> None:
        """
        Apply term mapping and Title Case to every entity name and predicate target
        stored in the ConceptStore — in-place.

        entity_mapper – TermMapper for entity names (None = title-case only).
        target_mapper – TermMapper for predicate targets (None = title-case only).

        Call this after both add_llm_extracts() and add_predefined() are complete,
        and after the mappers have been trained on the full term lists.
        """
        entity_map = entity_mapper.mapping if entity_mapper else {}
        target_map = target_mapper.mapping if target_mapper else {}

        def clean_entity(term: str) -> str:
            return entity_map.get(term, term).strip().title()

        def clean_target(term: str) -> str:
            return target_map.get(term, term).strip().title()

        normalized: dict = {}
        for key, pmid_data in self._dict.items():
            entities = pmid_data.get("entities", {})
            new_entities: dict[str, dict] = {}
            for entity, attrs in entities.items():
                new_entity = clean_entity(entity)
                merged: dict[str, float] = {}
                for triple, value in attrs.items():
                    if ":" in triple:
                        pred, tgt = triple.split(":", 1)
                        new_triple = f"{pred.strip()}: {clean_target(tgt.strip())}"
                    else:
                        new_triple = triple
                    merged[new_triple] = max(merged.get(new_triple, 0.0), float(value))
                # Merge when Title-casing collapses two variants to the same name
                if new_entity in new_entities:
                    for triple, value in merged.items():
                        new_entities[new_entity][triple] = max(
                            new_entities[new_entity].get(triple, 0.0), value
                        )
                else:
                    new_entities[new_entity] = merged
            normalized[key] = {**pmid_data, "entities": new_entities}

        self._dict = normalized
        self.save()
        n_entities = sum(len(d["entities"]) for d in self._dict.values())
        print(f"[ConceptStore] Normalization applied — {n_entities} entity records updated.")

    async def add_llm_extracts(
        self,
        df_pubmed,
        llm,
        allowed_predicates,
        batch_size: int = 10,
        extra_targets=None,
        predicate_definitions=None,
        max_consecutive_failures: int = 20,
        max_vocab_hints: int = 300,
        milestone_every: int = 0,
        on_milestone=None,
    ) -> None:
        """
        Extract entities from PubMed abstracts in parallel waves and store results.

        extra_targets            – additional target candidates (e.g. BFO anchor names) passed
                                   to the LLM alongside already-known targets.
        max_consecutive_failures – circuit breaker: abort and raise if this many results in a
                                   row are permanent failures (all retries exhausted).
        max_vocab_hints          – cap on how many targets/attributes are sent per prompt.
                                   Uses the most frequent entries to keep prompt size bounded.
        milestone_every          – trigger on_milestone after every N new entity mentions.
                                   0 = disabled.
        on_milestone             – async callable(store) invoked at each milestone.
                                   Safe to call: _dict writes only happen in this loop,
                                   which is paused during the await.
        """
        meta_col, meta_id = self.dm.get_meta_stamp("llm_extract")
        top_attrs = self.top_attributes(max_vocab_hints)
        top_targets = list({a.split(':', 1)[1].strip() for a in top_attrs if ':' in a})
        combined_targets = top_targets + (list(extra_targets) if extra_targets else [])
        current = self.dict

        to_process = [
            row for _, row in df_pubmed.iterrows()
            if str(int(row['pmid'])) not in current
        ]

        if not to_process:
            print("All abstracts already in store.")
            return

        print(f"Parallel Extraction: {len(to_process)} new abstracts in waves of {batch_size}...")
        sem = asyncio.Semaphore(batch_size)
        abort = asyncio.Event()
        llm.abort_event = abort
        llm._consec_errors = 0
        llm._max_consec_errors = max_consecutive_failures

        async def extract_one(row):
            if abort.is_set():
                return str(int(row['pmid'])), None
            async with sem:
                if abort.is_set():
                    return str(int(row['pmid'])), None
                pmid = str(int(row['pmid']))
                try:
                    extracted = await llm.extract_entities(
                        row['abstract'],
                        allowed_predicates,
                        combined_targets,
                        top_attrs,
                        predicate_definitions=predicate_definitions,
                    )

                    allowed_set = set(allowed_predicates)
                    entities_map: dict[str, dict] = {}
                    for ent in extracted:
                        if ent.object.strip().lower() in _METHODOLOGY_BLOCKLIST:
                            continue
                        attr_logic: dict[str, float] = {}
                        for a in ent.true_attributes:
                            if a.predicate in allowed_set:
                                attr_logic[f"{a.predicate}: {a.target}"] = 1.0
                        for a in ent.false_attributes:
                            if a.predicate in allowed_set:
                                triple = f"{a.predicate}: {a.target}"
                                if triple not in attr_logic:
                                    attr_logic[triple] = 0.0

                        # Semantic guard: is_a and part_of are mutually exclusive for the same target
                        is_a_targets = {
                            k.split(": ", 1)[1]
                            for k, v in attr_logic.items()
                            if k.startswith("is_a: ") and v == 1.0
                        }
                        for target in is_a_targets:
                            mereological = f"part_of: {target}"
                            if attr_logic.get(mereological) == 1.0:
                                attr_logic[mereological] = 0.0

                        entities_map[ent.object] = attr_logic

                    return pmid, {"entities": entities_map, "meta_stamp": meta_id}

                except Exception as e:
                    print(f"Failed PMID {pmid}: {e}")
                    return pmid, None

        tasks = [asyncio.create_task(extract_one(row)) for row in to_process]
        succeeded = 0
        entities_since_milestone = 0

        try:
            for f in asyncio.as_completed(tasks):
                pmid, result = await f
                if result:
                    self._dict[pmid] = result
                    self.save()
                    print(f"Cached PMID {pmid}")
                    succeeded += 1
                    if milestone_every > 0 and on_milestone:
                        entities_since_milestone += len(result.get("entities", {}))
                        if entities_since_milestone >= milestone_every:
                            print(f"\n[ConceptStore] Milestone: ~{entities_since_milestone} new entities "
                                  f"({succeeded}/{len(to_process)} PMIDs). Running normalization...")
                            await on_milestone(self)
                            entities_since_milestone = 0
                            # Refresh vocab hints so subsequent extractions use updated terms
                            top_attrs[:] = self.top_attributes(max_vocab_hints)
                            top_targets[:] = list({a.split(':', 1)[1].strip() for a in top_attrs if ':' in a})
                            combined_targets[:] = top_targets + (list(extra_targets) if extra_targets else [])
                            print("[ConceptStore] Vocab hints refreshed. Resuming extraction.\n")
                if abort.is_set():
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise RuntimeError(
                        f"[Circuit breaker] Aborted after {llm._consec_errors} consecutive failures. "
                        f"{succeeded}/{len(to_process)} abstracts saved."
                    )
        finally:
            llm.abort_event = None
            llm._max_consec_errors = 0

        print(f"Batch extraction complete. {succeeded}/{len(to_process)} abstracts processed.")

    async def fill_missing_attributes(
        self,
        llm,
        batch_size: int = 20,
        entity_batch: int = 5,
        max_entities: int | None = None,
        max_attrs_per_entity: int = 80,
    ) -> None:
        """
        For each unique entity, evaluate attributes that are not yet in its record.

        After normalize(), the store may have entity X with some attributes from
        one PMID but missing others that exist for different entities.  This step
        asks the LLM to confirm/deny every unseen (pred: target) pair so the store
        is fully populated before ContextMatrix and FCA run.

        batch_size          – concurrent LLM calls in flight.
        entity_batch        – entities grouped into one LLM call (reduces total calls).
        max_entities        – cap how many entities are filled (None = all). Useful for testing.
        max_attrs_per_entity – cap attributes sent per entity to keep prompts within token limits.
        """
        all_attrs = self.attributes  # all known pred:target pairs across the store

        if not all_attrs:
            print("[ConceptStore] No attributes found — skipping fill.")
            return

        # Build flat merged view: entity → {attr: value} across all PMIDs
        flat: dict[str, dict[str, float]] = {}
        for pmid_data in self._dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                merged = flat.setdefault(entity, {})
                for attr, val in attrs.items():
                    merged[attr] = max(merged.get(attr, 0.0), float(val))

        # Identify missing (never evaluated) attributes per entity, capped per entity
        entity_missing: dict[str, list[str]] = {}
        for entity, known_attrs in flat.items():
            missing = [a for a in all_attrs if a not in known_attrs]
            if missing:
                entity_missing[entity] = missing[:max_attrs_per_entity]

        # Optionally cap total entities processed
        if max_entities is not None:
            entity_missing = dict(list(entity_missing.items())[:max_entities])

        total_missing = sum(len(m) for m in entity_missing.values())
        if total_missing == 0:
            print("[ConceptStore] All entity–attribute pairs already evaluated.")
            return

        print(f"[ConceptStore] Filling {total_missing} missing pairs across "
              f"{len(entity_missing)} entities "
              f"(batch={entity_batch}, concurrency={batch_size})...")

        chunks = [
            dict(list(entity_missing.items())[i:i + entity_batch])
            for i in range(0, len(entity_missing), entity_batch)
        ]
        sem = asyncio.Semaphore(batch_size)

        async def process_chunk(chunk: dict[str, list[str]], chunk_id: int):
            async with sem:
                try:
                    result = await llm.fill_nan_batch(chunk)
                    print(f"  Chunk {chunk_id + 1}/{len(chunks)} done ({len(chunk)} entities).")
                    return result
                except Exception as e:
                    print(f"  Chunk {chunk_id + 1}/{len(chunks)} failed ({type(e).__name__}) — skipping.")
                    return {}

        tasks = [process_chunk(chunk, i) for i, chunk in enumerate(chunks)]
        batch_results = await asyncio.gather(*tasks)

        # Write confirmed → 1.0, unconfirmed → 0.0 back into the store
        # We add a synthetic "fill" key so provenance is clear
        fill_entities: dict[str, dict] = {}
        for batch in batch_results:
            if not batch:
                continue
            for entity, confirmed_list in batch.items():
                if entity not in entity_missing:
                    continue
                attr_dict = fill_entities.setdefault(entity, {})
                for attr in entity_missing[entity]:
                    attr_dict[attr] = 1.0 if attr in confirmed_list else 0.0

        if fill_entities:
            meta_col, meta_id = self.dm.get_meta_stamp("llm_fill")
            self._dict["llm_fill"] = {"entities": fill_entities, "meta_stamp": meta_id}
            self.save()
            confirmed_total = sum(
                sum(1 for v in d.values() if v == 1.0) for d in fill_entities.values()
            )
            print(f"[ConceptStore] Fill complete — {confirmed_total} new confirmed attributes. "
                  f"Stamp: {meta_id}")

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        if self._dict:
            self.dm.save_as_json(self._dict, self.file_name)
        else:
            print("Save skipped: Store is empty.")
