from __future__ import annotations
import asyncio
from pydantic import validate_call, ConfigDict
from wound_ontology.data_manager.data_manager import DataManager


class ExtractionCache:
    """Standalone staging area for all LLM extractions, indexed by PMID."""
    def __init__(self, data_manager, file_name):
        self.dm = data_manager
        self.file_name = file_name
        # Internal dictionary storage: {pmid: {object: [attributes]}}
        self._dict = self.dm.load_latest_json(self.file_name)

    @property
    def dict(self):
        """Access the underlying dictionary."""
        if self._dict is None:
            self._dict = {}
        return self._dict

    @dict.setter
    @validate_call(config=ConfigDict(extra='forbid', arbitrary_types_allowed=True))
    def dict(self, new_data: dict):
        """Updates the cache dictionary by merging new pmid entries."""
        self._dict.update(new_data)
        self.save()

    @property
    def attributes(self) -> list[str]:
        """Returns list of unique medical attributes (excluding meta_)."""
        all_attrs = set()
        for pmid_data in self.dict.values():
            for attr_dict in pmid_data.get("entities", {}).values():
                all_attrs.update(attr_dict.keys())
        return sorted([a for a in all_attrs if not a.startswith("meta_")])

    @property
    def predicates(self) -> list[str]:
        """Extracted predicates from attributes."""
        return [attr.split(':', 1)[0].strip() if ':' in attr else "" for attr in self.attributes]

    @property
    def targets(self) -> list[str]:
        """Extracted targets from attributes."""
        return [attr.split(':', 1)[1].strip() if ':' in attr else attr for attr in self.attributes]



    async def add_llm_extracts(self, df_pubmed, llm, allowed_predicates, batch_size=10, extra_targets=None, predicate_definitions=None):
        """
        Processes abstracts in parallel waves.
        batch_size: How many abstracts to extract simultaneously.
        extra_targets: additional target candidates (e.g. BFO leaf names) appended
                       to the known targets list so the LLM can reuse them.
        """
        meta_col, meta_id = self.dm.get_meta_stamp("llm_extract")
        combined_targets = self.targets + (list(extra_targets) if extra_targets else [])
        current_cache = self.dict

        # 1. Identify which PMIDs actually need processing
        to_process = []
        for _, row in df_pubmed.iterrows():
            pmid = str(int(row['pmid']))
            if pmid not in current_cache:
                to_process.append(row)

        if not to_process:
            print("All abstracts already in cache.")
            return

        print(f"🚀 Parallel Extraction: {len(to_process)} new abstracts in waves of {batch_size}...")

        # 2. The Semaphore (The Traffic Controller)
        sem = asyncio.Semaphore(batch_size)

        async def extract_one(row):
            async with sem:
                pmid = str(int(row['pmid']))
                try:
                    # Step 1: Perform the LLM extraction
                    extracted_response = await llm.extract_entities(
                        row['abstract'],
                        allowed_predicates,
                        combined_targets,
                        self.attributes,
                        predicate_definitions=predicate_definitions,
                    )

                    # Step 2: Build the flattened attribute map
                    # Structure: { Entity: { "predicate: target": 1.0 or 0.0 } }
                    entities_map = {}
                    for ent in extracted_response:
                        attr_logic = {}

                        # Map confirmed attributes to 1.0
                        for a in ent.true_attributes:
                            attr_logic[f"{a.predicate}: {a.target}"] = 1.0

                        # Map denied attributes to 0.0
                        for a in ent.false_attributes:
                            triple = f"{a.predicate}: {a.target}"
                            # Priority: If already marked 1.0 in this abstract, keep it 1.0
                            if triple not in attr_logic:
                                attr_logic[triple] = 0.0

                        # Semantic guard: if is_a: X is confirmed, demote part_of: X —
                        # taxonomic subclass and mereological containment are mutually
                        # exclusive for the same target.
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

                    # Step 3: Return the PMID as the key
                    return pmid, {
                        "entities": entities_map,
                        "meta_stamp": meta_id
                    }

                except Exception as e:
                    print(f"❌ Failed PMID {pmid}: {e}")
                    return pmid, None

        # 3. Fire the tasks
        tasks = [extract_one(row) for row in to_process]

        # 4. Use as_completed so we can update/save as they finish
        for f in asyncio.as_completed(tasks):
            pmid, result = await f
            if result:
                # Direct update to internal dict
                self._dict[pmid] = result
                # Optional: Save every few results to be safe
                self.save()
                print(f"✅ Cached PMID {pmid}")

        print(f"Batch extraction complete. {len(to_process)} abstracts processed.")


    def save(self):
        """Saves the cache directly using the DataManager (JSON)."""
        if self._dict:
            print("Saving new cache dictionary")
            self.dm.save_as_json(self._dict, self.file_name)
        else:
            print("Save skipped: Cache is empty.")
