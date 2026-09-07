from __future__ import annotations
import asyncio
import warnings
import re
import pandas as pd
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.utils.string_utils import normalize_term, smart_title
from config.blocklist import METHODOLOGY_BLOCKLIST as _METHODOLOGY_BLOCKLIST, is_noise_term as _is_noise_term


def _declared_category(term: str) -> str | None:
    """The BFO category `term` names, spelled the one way it is allowed to be.

    A category name is a value from a closed vocabulary, not a piece of prose,
    and normalising it is only ever destructive. `normalize_term` lowercases, and
    `smart_title` cannot put CamelCase back, so `MaterialEntity` came out of
    normalisation as `Materialentity` -- which is not in `CATEGORY_PARENT`, so
    the hierarchy stopped recognising it as a category typing and the one term,
    one category reconciliation silently stopped applying to it. Measured on the
    2026-09-07 run: 40 classes ended up under two disjoint BFO branches, against
    12 before the store was normalised, and `Surgical Site Infection` came out
    both a disposition and a material entity.

    Matching case-insensitively repairs a store that has already been damaged.
    """
    return _CATEGORY_BY_KEY.get(term.strip().lower())


def _category_keys() -> dict[str, str]:
    from wound_ontology.llm.extraction_models import CATEGORY_PARENT

    return {name.strip().lower(): name for name in CATEGORY_PARENT}


_CATEGORY_BY_KEY: dict[str, str] = _category_keys()


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

    @staticmethod
    def clean_entity_str(term: str) -> str:
        """String-only cleaning: strip parenthetical abbreviations, preserve original casing.

        'Systemic Sclerosis (SSc)' -> 'Systemic Sclerosis'
        Applied at ingestion time — before any mapper or title-casing.
        """
        return re.sub(r'\s*\([^)]*\)', '', term).strip()

    @staticmethod
    def clean_target_str(term: str) -> str:
        """String-only cleaning: strip parenthetical abbreviations, preserve original casing.

        Applied at ingestion time — before any mapper or title-casing.
        """
        return re.sub(r'\s*\([^)]*\)', '', term).strip()

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

    def normalize(self, mapper=None) -> None:
        """
        Apply term mapping and Title Case to every entity name and predicate target
        stored in the ConceptStore — in-place.

        mapper – shared TermMapper for all medical terms, whether they appear as
                 entity names or predicate targets (None = title-case only).

        Call this after both add_llm_extracts() and add_predefined() are complete,
        and after the mapper has been trained on the full term list.
        """
        term_map = mapper.mapping if mapper else {}

        # This method title-cases the store, so from the second run onwards the
        # store's spelling is no longer the extraction spelling the mapping is
        # keyed by, and an exact lookup silently stops finding anything: 12 of
        # 3574 live terms were an exact key where 68 matched on a normalised one.
        # The mapping could therefore only ever be applied ONCE, and every later
        # correction to it -- a withdrawn merge, a re-pointed canonical -- was
        # unreachable. Rule 13: normalise both sides, never one.
        folded_map: dict[str, str] = {}
        collisions: dict[str, set[str]] = {}
        for k, v in term_map.items():
            key = normalize_term(k)
            prev = folded_map.setdefault(key, v)
            if prev != v:
                collisions.setdefault(key, {prev}).add(v)
        if collisions:
            shown = "; ".join(f"{k!r}->{sorted(v)}" for k, v in
                              sorted(collisions.items())[:3])
            print(f"[ConceptStore] WARNING: {len(collisions)} normalised mapping "
                  f"key(s) claim more than one canonical; the first is used. {shown}")

        def canonical_of(term: str) -> str | None:
            """The mapping's answer for `term`, whatever spelling it arrived in."""
            if term in term_map:
                return term_map[term]
            return folded_map.get(normalize_term(term))

        def clean_entity(term: str) -> str:
            declared = _declared_category(term)
            if declared is not None:
                return declared
            hit = canonical_of(term)
            if hit is not None:
                return smart_title(hit)
            return smart_title(normalize_term(self.clean_entity_str(term)))

        def clean_target(term: str) -> str:
            declared = _declared_category(term)
            if declared is not None:
                return declared
            hit = canonical_of(term)
            if hit is not None:
                return smart_title(hit)
            return smart_title(normalize_term(self.clean_target_str(term)))

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
                # Merge when Title-casing collapses two variants to the same name.
                # If the same normalized entity appears twice, keep the strongest
                # evidence (max value) for every attribute triple.
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
        schema_constrained: bool = True,
    ) -> None:
        """
        Extract entities from PubMed abstracts in parallel waves and store results.

        extra_targets            – additional target candidates (e.g. BFO anchor names) passed
                                   to the LLM alongside already-known targets.
                                   DEPRECATED free-text path only: the schema-constrained
                                   path sends the generated category tree instead and
                                   ignores this, saying so on stdout when it is supplied.
        max_consecutive_failures – circuit breaker: abort and raise if this many results in a
                                   row are permanent failures (all retries exhausted).
        max_vocab_hints          – cap on how many targets/attributes are sent per prompt.
                                   Uses the most frequent entries to keep prompt size bounded.
                                   DEPRECATED free-text path only; see extra_targets.
        milestone_every          – trigger on_milestone after every N new entity mentions.
                                   0 = disabled.
        on_milestone             – async callable(store) invoked at each milestone.
                                   Safe to call: _dict writes only happen in this loop,
                                   which is paused during the await.
        schema_constrained       – use the two-stage path driven by the MILD/WONT-derived
                                   schema (config/extraction_schema.yaml). Terms are typed
                                   to one BFO category, grounded by exact-label lookup
                                   rather than by the model emitting IRIs, and relations
                                   are filtered against the category pairs the ontologies
                                   license. Set False for the legacy single free-text
                                   prompt, which is kept only for comparison.
        """
        meta_col, meta_id = self.dm.get_meta_stamp("llm_extract")
        if schema_constrained:
            # The two-stage prompts carry the generated category tree (and, when
            # with_definitions is on, the grounding table). They never carry store
            # vocabulary, so computing hints here would be dead work and accepting
            # them silently would advertise an effect this path does not have.
            if extra_targets or allowed_predicates or predicate_definitions:
                print("[ConceptStore] schema_constrained=True: vocabulary hints are NOT "
                      "sent to the model - the generated schema is the vocabulary. "
                      "extra_targets, allowed_predicates, predicate_definitions and "
                      "max_vocab_hints apply to the deprecated free-text path only.")
            top_attrs, top_targets, combined_targets = [], [], []
        else:
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
                    if schema_constrained:
                        return pmid, await _extract_schema_constrained(
                            llm, row['abstract'], meta_id
                        )
                    # DEPRECATED path. The model picks relations off a free-text
                    # list and emits its own identifiers, so nothing is typed to
                    # a BFO category and nothing is checked against the pairs
                    # MILD/WONT license. Kept for comparison against the
                    # schema-constrained path, not for production runs.
                    warnings.warn(
                        "schema_constrained=False uses the legacy free-text "
                        "extraction prompt: terms are not typed to a BFO "
                        "category, grounding is a generated identifier rather "
                        "than a label lookup, and relations are not filtered "
                        "against the category pairs the ontologies license. "
                        "Kept only for comparison.",
                        DeprecationWarning, stacklevel=2,
                    )
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
                        entity_name = ConceptStore.clean_entity_str(ent.object.strip())
                        if entity_name.lower() in _METHODOLOGY_BLOCKLIST or _is_noise_term(entity_name):
                            continue
                        attr_logic: dict[str, float] = {}
                        for a in ent.true_attributes:
                            if a.predicate in allowed_set:
                                target = ConceptStore.clean_target_str(a.target)
                                attr_logic[f"{a.predicate}: {target}"] = 1.0
                        for a in ent.false_attributes:
                            if a.predicate in allowed_set:
                                target = ConceptStore.clean_target_str(a.target)
                                triple = f"{a.predicate}: {target}"
                                if triple not in attr_logic:
                                    attr_logic[triple] = 0.0

                        # Semantic guard: is_a and part_of are mutually exclusive for the same target.
                        # If the model asserted both relations for the same target, keep is_a and
                        # mark part_of as false so the store remains logically coherent.
                        is_a_targets = {
                            k.split(": ", 1)[1]
                            for k, v in attr_logic.items()
                            if k.startswith("is_a: ") and v == 1.0
                        }
                        for target in is_a_targets:
                            mereological = f"part_of: {target}"
                            if attr_logic.get(mereological) == 1.0:
                                attr_logic[mereological] = 0.0

                        entities_map[entity_name] = attr_logic

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
                            if schema_constrained:
                                # Nothing to refresh: this path sends no vocab hints.
                                print("[ConceptStore] Normalization applied. Resuming extraction.\n")
                            else:
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

    @staticmethod
    def _category_phrase(category: str) -> str:
        """`MaterialEntity` -> `Material Entity`, for use inside a class label."""
        import re as _re
        return _re.sub(r"(?<!^)(?=[A-Z])", " ", category)

    def split_irreconcilable_terms(self, resolve_conflict) -> dict:
        """One label typed several irreconcilable ways is several classes.

        `Necrosis` arrived as `MaterialEntity` from one abstract and `Process`
        from two others. That is not one class typed badly: necrosis genuinely is
        a pathological process, and a material entity, and arguably a disposition
        of tissue realised by trauma. Forcing one category loses a sense; forcing
        none — which is what the reconciler does when the typings share no
        ancestor — loses the term.

        So each mention is renamed to `<Term> <Category>` using the category THAT
        abstract gave it: `Necrosis Process`, `Necrosis Material Entity`. Every
        resulting term then carries exactly one category by construction, and the
        relations an abstract asserted stay attached to the sense it meant. The
        label says which superclass it belongs under, which is also how a reader
        tells the two apart.

        Only irreconcilable terms are split. A conflict with an honest common
        ancestor (`Process` and `ProcessBoundary` agree on `Occurrent`) is
        reconciled instead — there is one concept there, described at two
        granularities.

        Returns a report: {split: {term: {category: new_label}}, mentions: n,
        unsensed: {term: count}}.
        """
        from wound_ontology.llm.extraction_models import (
            COARSE_CATEGORIES, CATEGORY_PARENT,
        )
        from wound_ontology.utils.string_utils import smart_title

        typings: dict[str, set[str]] = {}
        for rec in self.dict.values():
            for entity, attrs in rec.get("entities", {}).items():
                for triple, value in attrs.items():
                    if value != 1.0 or ":" not in triple:
                        continue
                    pred, target = triple.split(":", 1)
                    if pred.strip().lower().replace(" ", "_") not in ("is_a", "subclass_of"):
                        continue
                    target = target.strip()
                    if target in CATEGORY_PARENT:
                        # Group by the NORMALISED name, as the hierarchy does.
                        # Grouping by the raw store key hid every conflict whose
                        # mentions differed in case: "granulation" carried
                        # MaterialEntity and "Granulation" carried Process, so
                        # each looked consistent here while the hierarchy — which
                        # smart_titles — saw one term typed two irreconcilable
                        # ways. Rule 13: normalise both sides of a comparison.
                        typings.setdefault(smart_title(entity.strip()), set()).add(target)

        # A coarse category is the model declining to answer, not a sense. Splitting
        # on one produced `complications Continuant` and `complications Occurrent`
        # beside three real senses -- classes that assert nothing. Drop them first
        # and judge the term on what it was actually typed as.
        typings = {t: (c - COARSE_CATEGORIES) or c for t, c in typings.items()}

        splittable = {t: c for t, c in typings.items()
                      if len(c) > 1 and resolve_conflict(c) is None}
        report: dict = {"split": {}, "mentions": 0, "unsensed": {}}
        if not splittable:
            print("[ConceptStore] no irreconcilable terms to split.")
            return report

        for term, cats in splittable.items():
            # smart_title on the whole label: store keys arrive in whatever case
            # the abstract used, so without it one term yields "necrosis Material
            # Entity" and another "Necrosis Material Entity" -- two classes for
            # one sense.
            report["split"][term] = {
                c: smart_title(f"{term} {self._category_phrase(c)}")
                for c in sorted(cats)
            }

        def renamed(label: str, sense: dict) -> str:
            return sense.get(smart_title(label.strip()), label)

        for rec in self.dict.values():
            entities = rec.get("entities", {})
            # Which sense each splittable term carries IN THIS abstract.
            sense: dict[str, str] = {}
            for entity, attrs in entities.items():
                key = smart_title(entity.strip())
                if key not in splittable:
                    continue
                here = {t.split(":", 1)[1].strip()
                        for t, v in attrs.items()
                        if v == 1.0 and ":" in t
                        and t.split(":", 1)[0].strip().lower().replace(" ", "_")
                        in ("is_a", "subclass_of")
                        and t.split(":", 1)[1].strip() in CATEGORY_PARENT}
                chosen = next(iter(here)) if len(here) == 1 else None
                target = report["split"][key].get(chosen) if chosen else None
                if target is not None:
                    sense[key] = target
                else:
                    # No category here, two at once, or only a coarse one — which
                    # is not a sense and so has no split to map to. The mention is
                    # left alone rather than guessed at.
                    report["unsensed"][key] = report["unsensed"].get(key, 0) + 1

            if not sense:
                continue
            rebuilt: dict[str, dict] = {}
            for entity, attrs in entities.items():
                new_entity = renamed(entity, sense)
                if new_entity != entity:
                    report["mentions"] += 1
                dest = rebuilt.setdefault(new_entity, {})
                for triple, value in attrs.items():
                    if ":" in triple:
                        # split(":", 1) leaves the separator's space on the
                        # target, so strip before re-joining or the rebuilt key
                        # is "is_a:  Process" and no longer matches anything.
                        pred, target = triple.split(":", 1)
                        triple = f"{pred.strip()}: {renamed(target.strip(), sense)}"
                    dest[triple] = max(dest.get(triple, 0.0), value)
            rec["entities"] = rebuilt

        self.save()
        print(f"[ConceptStore] split {len(report['split'])} irreconcilable term(s) "
              f"into {sum(len(v) for v in report['split'].values())} sense(s) "
              f"across {report['mentions']} mention(s).")
        for term, senses in sorted(report["split"].items()):
            print(f"[ConceptStore]     {term} -> {', '.join(sorted(senses.values()))}")
        if report["unsensed"]:
            print(f"[ConceptStore] {len(report['unsensed'])} term(s) were mentioned "
                  f"without a category in some abstract and left unsplit there: "
                  f"{dict(sorted(report['unsensed'].items())[:8])}")
        return report

    def merge_entity_records(self, entities: dict[str, dict[str, float]], *, kind: str) -> int:
        """Merge derived entity records into a synthetic store record.

        Everything downstream -- the hierarchies, the FCA view -- is rebuilt from
        this store, so anything that must survive a rebuild has to arrive here.
        This is the door for the things that are not extracted from an abstract:
        LLM verdicts on undecided cells ("llm_fill", "llm_fill_nan") and FCA
        edges a human promoted ("fca_promoted"). `kind` becomes the record key,
        so their provenance stays visible beside the PMIDs.

        This used to be a plain assignment, so a second fill replaced the first
        one's verdicts wholesale and said nothing. Merging keeps both. The one
        way a value can still be lost -- the same (entity, attribute) decided
        differently on two runs -- is counted and reported instead of happening
        quietly.

        Returns the number of verdicts written.
        """
        if not entities:
            return 0
        record = self._dict.get(kind) or {}
        existing = dict(record.get("entities", {}))
        written = changed = 0
        for entity, attrs in entities.items():
            dest = dict(existing.get(entity, {}))
            for triple, value in attrs.items():
                if triple in dest and dest[triple] != value:
                    changed += 1
                dest[triple] = value
                written += 1
            existing[entity] = dest

        _, meta_id = self.dm.get_meta_stamp(kind)
        self._dict[kind] = {"entities": existing, "meta_stamp": meta_id}
        self.save()
        if changed:
            print(f"[ConceptStore] {changed} verdict(s) overwrote an earlier and "
                  f"different verdict for the same attribute.")
        print(f"[ConceptStore] {written} verdict(s) merged into '{kind}' "
              f"across {len(existing)} entities. Stamp: {meta_id}")
        return written

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

        # Three-way write-back: confirmed → 1.0, explicitly denied → 0.0, and
        # anything the model did not rule on is simply NOT written, so it stays
        # unevaluated rather than being recorded as a definite "does not hold".
        # We add a synthetic "fill" key so provenance is clear.
        fill_entities: dict[str, dict] = {}
        n_conf = n_deny = 0
        for batch in batch_results:
            if not batch:
                continue
            for entity, verdict in batch.items():
                if entity not in entity_missing:
                    continue
                asked = set(entity_missing[entity])
                confirmed = asked & set(verdict.get("confirmed", ()))
                denied    = asked & set(verdict.get("denied", ())) - confirmed
                if not confirmed and not denied:
                    continue
                attr_dict = fill_entities.setdefault(entity, {})
                for attr in confirmed:
                    attr_dict[attr] = 1.0
                    n_conf += 1
                for attr in denied:
                    attr_dict[attr] = 0.0
                    n_deny += 1
        print(f"[ConceptStore] verdicts: {n_conf} confirmed, {n_deny} denied, "
              f"{total_missing - n_conf - n_deny} left unevaluated.")

        if fill_entities:
            self.merge_entity_records(fill_entities, kind="llm_fill")
            confirmed_total = sum(
                sum(1 for v in d.values() if v == 1.0) for d in fill_entities.values()
            )
            # The stamp is printed by merge_entity_records, which owns it now.
            print(f"[ConceptStore] Fill complete — {confirmed_total} new confirmed attributes.")

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        if self._dict:
            self.dm.save_as_json(self._dict, self.file_name)
        else:
            print("Save skipped: Store is empty.")

async def _extract_schema_constrained(llm, text, meta_id):
    """One abstract through the MILD/WONT-derived schema.

    Returns the same {"entities": ..., "meta_stamp": ...} payload the legacy path
    produces, so the store, FCA matrix and hierarchies are unaffected. What is
    different is upstream: the model made one categorical choice per term instead
    of picking relations off a 7-item free-text list, grounding was a lookup
    rather than a generated identifier, and every relation was checked against
    the category pairs MILD/WONT actually license.
    """
    from wound_ontology.llm import extraction_adapter as _ad

    result, report = await llm.extract_two_stage(text)
    entities_map = {}
    for label, attrs in _ad.result_to_store_entities(result).items():
        name = ConceptStore.clean_entity_str(label.strip())
        if not name or name.lower() in _METHODOLOGY_BLOCKLIST or _is_noise_term(name):
            continue
        cleaned = {}
        for triple, value in attrs.items():
            pred, target = triple.split(":", 1)
            cleaned[f"{pred}: {ConceptStore.clean_target_str(target)}"] = value
        entities_map[name] = cleaned

    payload = {"entities": entities_map, "meta_stamp": meta_id}
    if any(report.get(k) for k in ("rejected_terms", "rejected_relations",
                                   "unknown_predicates")):
        payload["schema_report"] = report
    return payload
