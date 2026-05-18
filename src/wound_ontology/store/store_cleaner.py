from __future__ import annotations
import asyncio
import re
from collections import Counter, defaultdict

from wound_ontology.store.base_cleaner import BaseCleaner


class StoreCleaner(BaseCleaner):
    """
    Removes out-of-scope entities and invalid predicates from a ConceptStore.

    Two cleaning operations:
      - Entity blocklist  : removes methodology/study-design entities by name.
      - Predicate filter  : strips attributes whose predicate is not in allowed_predicates.
      - Empty-entity prune: removes entities left with zero true attributes after the above.

    Usage::

        cleaner = StoreCleaner(allowed_predicates=ALLOWED_PREDICATES)
        report  = cleaner.clean(store)
        cleaner.print_report(report)
    """

    # ── Main entry point ──────────────────────────────────────────────────────

    def clean_entities(self, store) -> dict:
        """
        Finds all entities blocked by keyword search and removes them from the store.

        Returns a report dict with counts of what was removed.
        """
        self._reload_lists()
        stats: dict[str, int] = defaultdict(int)
        blocked_entity_examples: list[str] = []
        blocked: set[str] = set()

        for entity in store.entities:
            if self._is_blocked(entity):
                blocked.add(entity)
                stats["blocked_entities"] += 1
                if len(blocked_entity_examples) < 20:
                    blocked_entity_examples.append(entity)

        if blocked:
            store.entities = [e for e in store.entities if e not in blocked]

        return {
            **dict(stats),
            "blocked_entity_examples": blocked_entity_examples,
        }

    def list_blocked(self, store) -> list[str]:
        """Print and return all entities in the store that are currently blocked."""
        self._reload_lists()
        blocked = sorted(e for e in store.entities if self._is_blocked(e))
        print(f"{len(blocked)} blocked entities:")
        for e in blocked:
            print(f"  {e}")
        return blocked

    def list_blocked_targets(self, store) -> list[str]:
        """Print and return all attribute targets in the store that are currently blocked."""
        self._reload_lists()
        blocked = sorted(set(t for t in store.targets if self._is_blocked(t)))
        print(f"{len(blocked)} blocked targets:")
        for t in blocked:
            print(f"  {t}")
        return blocked

    # ── Interactive review methods ────────────────────────────────────────────

    def review_blocked_entities(self, store) -> None:
        """Review blocked entities in the store — keep blocked (n) or move to WHITELIST (y)."""
        self._reload_lists()
        blocked = sorted(e for e in store.entities if self._is_blocked(e))
        if not blocked:
            print("No blocked entities in store.")
            return
        self._review_to_whitelist(blocked, label="entity")

    def review_blocked_targets(self, store) -> None:
        """Review blocked targets in the store — keep blocked (n) or move to WHITELIST (y)."""
        self._reload_lists()
        blocked = sorted(set(t for t in store.targets if self._is_blocked(t)))
        if not blocked:
            print("No blocked targets in store.")
            return
        self._review_to_whitelist(blocked, label="target")

    def review_susp_targets(self, store) -> None:
        """Review suspicious and blocked targets — whitelist (y), block (n), or skip (s)."""
        self._reload_lists()

        freq: Counter = Counter()
        for pmid_data in store._dict.values():
            for _, attrs in pmid_data.get("entities", {}).items():
                for attr in attrs:
                    if ':' in attr:
                        freq[attr.split(':', 1)[1].strip()] += 1

        ranked = sorted(
            [(t, c, self._score(t)) for t, c in freq.items() if 0 < self._score(t) < 100],
            key=lambda x: (-x[2], -x[1]),
        )
        if not ranked:
            print("No suspicious targets found.")
            return

        to_block: set[str] = set()
        to_whitelist: set[str] = set()

        print(f"\n{'='*80}")
        print(f"  {len(ranked)} suspicious targets (already-blocked excluded)")
        print(f"  y = in scope → WHITELIST  |  n = out of scope → BLOCKLIST  |  s = skip  |  ESC = exit")
        print(f"{'='*80}\n")

        for target, count, score in ranked:
            tlower = target.strip().lower()
            tbase = re.sub(r"\s*\([^)]*\)\s*$", "", tlower).strip()
            if tlower in self.whitelist or tbase in self.whitelist:
                print(f"  ✓ (freq={count:>4})  '{target}'  — already whitelisted, skipping")
                continue
            answer = self._prompt(f"  [?] (freq={count:>4})  '{target}'  in scope? [y/n/s] ").strip().lower()
            if answer == "esc":
                print("  Exiting review.")
                break
            if answer == "y":
                to_whitelist.add(target)
            elif answer == "n":
                to_block.add(target)

        self._save_review_results(to_block, to_whitelist, apply_hint="clean_targets")

    def review_good_entities(self, store) -> None:
        """Review whitelisted entities present in the store — keep (y) or move to BLOCKLIST (n)."""
        self._reload_lists()
        store_entities = {e.strip().lower() for e in store.entities}
        good = sorted(e for e in self.whitelist if e in store_entities)
        if not good:
            print("No whitelisted entities found in store.")
            return
        self._review_to_blocklist(good, label="entity")

    def review_good_targets(self, store) -> None:
        """Review whitelisted targets present in the store — keep (y) or move to BLOCKLIST (n)."""
        self._reload_lists()
        store_targets = {t.strip().lower() for t in store.targets}
        good = sorted(t for t in self.whitelist if t in store_targets)
        if not good:
            print("No whitelisted targets found in store.")
            return
        self._review_to_blocklist(good, label="target")

    def clean_predicates(self, store) -> dict:
        """
        Remove attributes whose predicate is not in allowed_predicates.

        Returns a report dict with counts of what was removed.
        """
        stats: dict[str, int] = defaultdict(int)
        rogue_pred_counts: dict[str, int] = defaultdict(int)

        # Count all predicates that are not allowed before mutating the store.
        for predicate in set(store.predicates):
            if predicate and predicate not in self.allowed_predicates:
                stats["rogue_predicates_removed"] += 1
                rogue_pred_counts[predicate] += 1

        # Replace the store's predicate set with only allowed predicates.
        store.predicates = list(self.allowed_predicates)

        return {
            **dict(stats),
            "rogue_predicate_breakdown": dict(rogue_pred_counts),
        }

    def clean_targets(self, store) -> dict:
        """
        Remove attributes whose target is in the blocklist.

        Returns a report dict with counts of what was removed.
        """
        self._reload_lists()
        stats: dict[str, int] = defaultdict(int)

        for pmid_data in store._dict.values():
            for _, attrs in pmid_data.get("entities", {}).items():
                # Identify any attribute whose target part is blocked.
                to_delete = [
                    attr for attr in attrs
                    if ':' in attr and self._is_blocked(attr.split(':', 1)[1].strip())
                ]
                for attr in to_delete:
                    del attrs[attr]
                    stats["blocked_targets_removed"] += 1

        # Save only if there were modifications.
        store.save()
        return dict(stats)

    def prune_empty_entities(self, store) -> dict:
        """
        Remove entities that have no confirmed (value == 1.0) attributes.

        Returns a report dict with counts of what was removed.
        """
        stats: dict[str, int] = defaultdict(int)

        for pmid_data in store._dict.values():
            entities = pmid_data.get("entities", {})
            to_delete = [
                entity for entity, attrs in entities.items()
                if not any(v == 1.0 for v in attrs.values())
            ]
            for entity in to_delete:
                del entities[entity]
                stats["empty_entities_pruned"] += 1

        store.save()
        return dict(stats)

    def clean_attributes(self, store) -> dict:
        """Remove rogue predicates, blocked targets, then prune emptied entities."""
        pred_report   = self.clean_predicates(store)
        target_report = self.clean_targets(store)
        prune_report  = self.prune_empty_entities(store)
        return {**pred_report, **target_report, **prune_report}

    def clean(self, store) -> dict:
        """Run all cleaning steps: entities, predicates, blocked targets, empty-entity pruning."""
        entity_report = self.clean_entities(store)
        attr_report   = self.clean_attributes(store)
        return {**entity_report, **attr_report}

    # ── Candidate scanning ────────────────────────────────────────────────────

    def _collect_ranked(self, store) -> list[tuple[str, int, float, list[str]]]:
        """
        Return all unique entities sorted by (score desc, freq desc).
        Each tuple: (entity_name, pmid_count, score, sample_true_attrs).
        """
        freq: Counter = Counter()
        sample_attrs: dict[str, list[str]] = {}

        for pmid_data in store._dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                freq[entity] += 1
                if entity not in sample_attrs:
                    sample_attrs[entity] = [
                        a for a, v in attrs.items() if v == 1.0
                    ][:4]

        ranked = [
            (entity, count, self._score(entity), sample_attrs.get(entity, []))
            for entity, count in freq.items()
        ]
        ranked.sort(key=lambda x: (-x[2], -x[1]))
        return ranked

    def _check_list_exclusivity(self, embedder, threshold: float) -> None:
        """Warn if any whitelist term is semantically similar to a blocklist term."""
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        wl_terms = sorted(self.whitelist)
        bl_terms = sorted(self.blocked_entities)
        if not wl_terms or not bl_terms:
            print("  (Skipping exclusivity check — one or both lists are empty.)")
            return

        print(f"\n[StoreCleaner] Checking list exclusivity "
              f"({len(wl_terms)} whitelist × {len(bl_terms)} blocklist terms)...")
        wl_embs = embedder.embed(wl_terms)
        bl_embs = embedder.embed(bl_terms)
        sim = cosine_similarity(wl_embs, bl_embs)   # (W, B)

        conflicts: list[tuple[str, str, float]] = []
        for wi, wt in enumerate(wl_terms):
            max_bi  = int(sim[wi].argmax())
            max_sim = float(sim[wi, max_bi])
            if max_sim >= threshold:
                conflicts.append((wt, bl_terms[max_bi], max_sim))

        if not conflicts:
            print(f"  ✓ Lists are exclusive (no overlap above {threshold}).")
            return

        print(f"\n  ⚠ {len(conflicts)} whitelist terms match a blocklist term "
              f"(cos ≥ {threshold}) — whitelist takes priority:")
        for wt, bt, s in sorted(conflicts, key=lambda x: -x[2]):
            print(f"    cos={s:.3f}  whitelist='{wt}'  ≈  blocklist='{bt}'")
        print("  Review config/blocklists.py manually to remove the redundant blocklist entries.")

    def review_susp_entities(
        self,
        store,
        embedder=None,
        similarity_threshold: float = 0.92,
    ) -> None:
        """Review suspicious (not yet decided) entities.

        Without embedder: shows all keyword-suspicious entities for manual review.
        With embedder: first checks blocklist/whitelist exclusivity, then uses
        SapBERT cosine similarity to pre-classify each suspicious entity:
          - cosine ≥ threshold to blocklist only  → auto-block (not shown)
          - cosine ≥ threshold to whitelist only  → auto-whitelist (not shown)
          - fits neither or both                  → shown for manual review
        """
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        self._reload_lists()
        ranked = [
            (e, c, s, a) for e, c, s, a in self._collect_ranked(store) if 0 < s < 100
        ]
        if not ranked:
            print("No suspicious entities found.")
            return

        to_block: set[str] = set()
        to_whitelist: set[str] = set()

        if embedder is None:
            # ── Keyword-only path ────────────────────────────────────────────
            print(f"\n{'='*80}")
            print(f"  {len(ranked)} suspicious entities (already-blocked excluded)")
            print(f"  y = in scope → WHITELIST  |  n = out of scope → BLOCKLIST  |  s = skip  |  ESC = exit")
            print(f"{'='*80}\n")
            for entity, count, score, attrs in ranked:
                elower = entity.strip().lower()
                ebase = re.sub(r"\s*\([^)]*\)\s*$", "", elower).strip()
                if elower in self.whitelist or ebase in self.whitelist:
                    continue
                answer = self._prompt(
                    f"  [?] (freq={count:>4})  '{entity}'  in scope? [y/n/s] "
                ).strip().lower()
                if answer == "esc":
                    print("  Exiting review.")
                    break
                if answer == "y":
                    to_whitelist.add(entity)
                elif answer == "n":
                    to_block.add(entity)
            self._save_review_results(to_block, to_whitelist, apply_hint="clean_entities")
            return

        # ── SapBERT-assisted path ────────────────────────────────────────────
        self._check_list_exclusivity(embedder, similarity_threshold)

        entities = [e for e, _, _, _ in ranked]
        entity_idx = {e: i for i, e in enumerate(entities)}
        bl_terms = sorted(self.blocked_entities)
        wl_terms = sorted(self.whitelist)

        print(f"\n[StoreCleaner] Embedding {len(entities)} suspicious entities...")
        ent_embs = embedder.embed(entities)

        if bl_terms:
            print(f"[StoreCleaner] Embedding {len(bl_terms)} blocklist terms...")
            bl_embs  = embedder.embed(bl_terms)
            bl_sim   = cosine_similarity(ent_embs, bl_embs)   # (E, B)
            bl_max_s = bl_sim.max(axis=1)
            bl_max_i = bl_sim.argmax(axis=1)
        else:
            bl_max_s = np.zeros(len(entities))
            bl_max_i = np.zeros(len(entities), dtype=int)
            bl_terms = []

        if wl_terms:
            print(f"[StoreCleaner] Embedding {len(wl_terms)} whitelist terms...")
            wl_embs  = embedder.embed(wl_terms)
            wl_sim   = cosine_similarity(ent_embs, wl_embs)   # (E, W)
            wl_max_s = wl_sim.max(axis=1)
            wl_max_i = wl_sim.argmax(axis=1)
        else:
            wl_max_s = np.zeros(len(entities))
            wl_max_i = np.zeros(len(entities), dtype=int)
            wl_terms = []

        auto_blocked: list[tuple[str, float, str]] = []
        auto_wl:      list[tuple[str, float, str]] = []
        for_review:   list[tuple[str, int, float, list, float, str, float, str]] = []

        for entity, count, score, attrs in ranked:
            elower = entity.strip().lower()
            ebase  = re.sub(r"\s*\([^)]*\)\s*$", "", elower).strip()
            if elower in self.whitelist or ebase in self.whitelist:
                continue  # already explicit — skip

            idx    = entity_idx[entity]
            bl_s   = float(bl_max_s[idx])
            wl_s   = float(wl_max_s[idx])
            near_bl = bl_terms[bl_max_i[idx]] if bl_terms else "—"
            near_wl = wl_terms[wl_max_i[idx]] if wl_terms else "—"
            fits_bl = bl_s >= similarity_threshold
            fits_wl = wl_s >= similarity_threshold

            if fits_wl and not fits_bl:
                auto_wl.append((entity, wl_s, near_wl))
            elif fits_bl and not fits_wl:
                auto_blocked.append((entity, bl_s, near_bl))
            else:
                for_review.append((entity, count, score, attrs, bl_s, near_bl, wl_s, near_wl))

        if auto_blocked:
            print(f"\n  Auto-blocking {len(auto_blocked)} entities "
                  f"(cos ≥ {similarity_threshold} to blocklist only):")
            for e, s, n in sorted(auto_blocked, key=lambda x: -x[1]):
                print(f"    cos={s:.3f}  '{e}'  ≈  '{n}'")
            to_block.update(e.strip().lower() for e, _, _ in auto_blocked)

        if auto_wl:
            print(f"\n  Auto-whitelisting {len(auto_wl)} entities "
                  f"(cos ≥ {similarity_threshold} to whitelist only):")
            for e, s, n in sorted(auto_wl, key=lambda x: -x[1]):
                print(f"    cos={s:.3f}  '{e}'  ≈  '{n}'")
            to_whitelist.update(e.strip().lower() for e, _, _ in auto_wl)

        if for_review:
            print(f"\n{'='*80}")
            print(f"  {len(for_review)} ambiguous entities (fit neither list clearly)")
            print(f"  y = in scope → WHITELIST  |  n = out of scope → BLOCKLIST  |  s = skip  |  ESC = exit")
            print(f"{'='*80}\n")
            for entity, count, score, attrs, bl_s, near_bl, wl_s, near_wl in for_review:
                context = f"bl={bl_s:.3f}(≈'{near_bl}'), wl={wl_s:.3f}(≈'{near_wl}')"
                answer = self._prompt(
                    f"  [?] (freq={count:>4}, {context})  '{entity}'  in scope? [y/n/s] "
                ).strip().lower()
                if answer == "esc":
                    print("  Exiting review.")
                    break
                if answer == "y":
                    to_whitelist.add(entity)
                elif answer == "n":
                    to_block.add(entity)
        else:
            print("\n  All suspicious entities auto-classified — no manual review needed.")

        self._save_review_results(to_block, to_whitelist, apply_hint="clean_entities")

    def llm_scan_entities(
        self,
        store,
        llm,
        top_n: int = 1000,
        llm_batch_size: int = 150,
        display_batch_size: int = 500,
        threshold_pct: float = 20.0,
    ) -> None:
        """
        Use the LLM to evaluate the ``top_n`` most frequent entities and flag those
        inappropriate for a wound ontology.

        Only the top_n entities by PMID frequency are sent to the LLM — this focuses
        evaluation on the terms that have the most impact on the ontology.
        Entities already in the blocklist are pre-flagged without an LLM call.
        If more than ``threshold_pct`` % of a display batch are flagged, the next
        batch is shown automatically.

        After reviewing, purge with::

            pipeline.run_clean_store(extra_blocked_entities={"term1", "term2", ...})
        """
        self._reload_lists()
        # Collect all entities sorted by frequency descending; this is the candidate pool
        # for the LLM scope scan. Entities present more often in the store are
        # prioritized because they have greater influence on the ontology.
        ranked_raw = self._collect_ranked(store)
        by_freq = sorted(ranked_raw, key=lambda x: -x[1])
        total_entities = len(by_freq)

        # Separate blocked from non-blocked before selecting top_n
        # so the top_n quota is filled exclusively by non-blocked entities
        pre_blocked = [r for r in by_freq if r[2] == 100.0]
        non_blocked = [r for r in by_freq if r[2] < 100.0]

        candidates = non_blocked[:top_n]
        rest       = non_blocked[top_n:]

        print(f"[StoreCleaner] Evaluating top {len(candidates)} most frequent "
              f"non-blocked entities (of {total_entities} total) via LLM "
              f"(batches of {llm_batch_size})...")
        print(f"  Pre-blocked (in blocklist)      : {len(pre_blocked)}")
        print(f"  Sending to LLM                  : {len(candidates)}")
        print(f"  Below top {top_n}, not evaluated: {len(rest)}")

        # Load cached eval if available
        llm_flagged: set[str] = set()
        dm = getattr(store, "dm", None)
        cached_eval: dict = {}
        if dm is not None:
            cached_eval = dm.load_latest_json("scope_eval") or {}

        # Entities already evaluated in a previous scan — skip LLM call for them
        already_evaluated: set[str] = set(cached_eval.keys())
        llm_flagged = {e for e, v in cached_eval.items() if v}
        # Only send entities to the LLM that haven't been evaluated before.
        to_evaluate = [r for r in candidates if r[0] not in already_evaluated]

        if already_evaluated:
            print(f"  Reusing cached eval for {len(already_evaluated)} entities "
                  f"({len(to_evaluate)} new to evaluate).")

        # LLM evaluation for new entities — saves after every batch
        async def _run_llm():
            n_batches = (len(to_evaluate) + llm_batch_size - 1) // llm_batch_size
            for i in range(0, len(to_evaluate), llm_batch_size):
                chunk = to_evaluate[i : i + llm_batch_size]
                batch_num = i // llm_batch_size + 1
                batch_input = [(e, c, a) for e, c, _, a in chunk]
                try:
                    flagged = await llm.classify_scope_batch(batch_input)
                    flagged_set = set(flagged)
                    llm_flagged.update(flagged_set)
                    for entity, _, _, _ in chunk:
                        cached_eval[entity] = entity in flagged_set
                    done = min(i + llm_batch_size, len(to_evaluate))
                    print(f"  LLM batch {batch_num}/{n_batches}: "
                          f"{done}/{len(to_evaluate)} evaluated, "
                          f"{len(flagged)} flagged in this batch.")
                except Exception as exc:
                    print(f"  LLM batch {batch_num}/{n_batches} failed ({exc}) — skipped.")
                finally:
                    if dm is not None:
                        dm.save_as_json(cached_eval, "scope_eval")

        asyncio.get_event_loop().run_until_complete(_run_llm())
        print(f"  Eval saved ({len(cached_eval)} entities total).")

        # Build final ranked list:
        #   tier0 — blocklist hits (definitely out)
        #   tier1 — LLM-confirmed inappropriate from top_n
        #   tier2 — LLM-cleared from top_n (evaluated, passed)
        #   tier3 — below top_n (not evaluated)
        tier0 = sorted(pre_blocked,                                      key=lambda x: -x[1])
        tier1 = sorted([r for r in candidates if r[0] in llm_flagged],  key=lambda x: -x[1])
        tier2 = sorted([r for r in candidates if r[0] not in llm_flagged], key=lambda x: -x[1])
        tier3 = sorted(rest,                                             key=lambda x: -x[1])
        ranked = tier0 + tier1 + tier2 + tier3

        flagged_total = len(tier0) + len(tier1)
        print(f"\n[StoreCleaner] Total flagged as inappropriate: "
              f"{flagged_total} / {total_entities} "
              f"({100 * flagged_total / max(total_entities, 1):.1f}%)")

        # Display in batches
        for start in range(0, len(ranked), display_batch_size):
            batch = ranked[start : start + display_batch_size]
            batch_num = start // display_batch_size + 1

            print(f"\n{'='*80}")
            print(f"  SCOPE SCAN — Batch {batch_num}  "
                  f"(#{start + 1}–{start + len(batch)} of {len(ranked)})")
            print(f"  ✗ = blocklist  |  ! = LLM flagged  |  ✓ = whitelisted  |  · = clean")
            print(f"{'='*80}")
            print(f"  {'#':>5}  {'Freq':>4}  {'Flag':4}  Entity  →  sample true attributes")
            print(f"  {'-'*5}  {'-'*4}  {'-'*4}  {'-'*62}")

            n_flagged_in_batch = 0
            for rank, (entity, freq, score, attrs) in enumerate(batch, start=start + 1):
                elower = entity.strip().lower()
                ebase = re.sub(r"\s*\([^)]*\)\s*$", "", elower).strip()
                if score == 100.0:
                    flag, n_flagged_in_batch = " ✗ ", n_flagged_in_batch + 1
                elif elower in self.whitelist or ebase in self.whitelist:
                    flag = " ✓  "
                elif entity in llm_flagged:
                    flag, n_flagged_in_batch = " !  ", n_flagged_in_batch + 1
                else:
                    flag = " ·  "
                attr_str = ", ".join(attrs) if attrs else "—"
                print(f"  {rank:>5}  {freq:>4}  {flag}  {entity}  →  {attr_str}")

            flagged_pct = 100 * n_flagged_in_batch / len(batch)
            print(f"\n  Flagged in this batch: {n_flagged_in_batch}/{len(batch)} ({flagged_pct:.1f}%)")

            if start + display_batch_size >= len(ranked):
                print("  [End of store — all entities shown]")
                break

            if flagged_pct > threshold_pct:
                print(f"  > {threshold_pct:.0f}% flagged → showing next batch automatically...\n")
            else:
                print(f"  ≤ {threshold_pct:.0f}% flagged — stopping. "
                      "Call review_susp_entities() again to see more.")
                break

        # Per-entity interactive review
        # Exclude entities already whitelisted (LLM cache may still flag them)
        new_to_review = sorted(
            e for e, _, _, _ in tier1
            if e.strip().lower() not in self.whitelist
            and re.sub(r"\s*\([^)]*\)\s*$", "", e.strip().lower()).strip() not in self.whitelist
        )
        if not new_to_review:
            print("\nNo new entities to review — all flagged terms are already classified.")
            return

        to_block: set[str] = set()
        to_whitelist: set[str] = set()

        print(f"\n{'='*80}")
        print(f"  Reviewing {len(new_to_review)} LLM-flagged entities one by one.")
        print(f"  y = valid wound ontology concept → WHITELIST")
        print(f"  n = out of scope                 → BLOCKLIST")
        print(f"  s = skip (decide later)")
        print(f"{'='*80}\n")

        for entity in new_to_review:
            answer = input(f"  '{entity}' in scope? [y/n/s] ").strip().lower()
            if answer == "y":
                to_whitelist.add(entity)
            elif answer == "n":
                to_block.add(entity)

        if to_block:
            added = self._append_to_blocklist(to_block)
            print(f"\n  ✓ {added} new terms written to METHODOLOGY_BLOCKLIST.")
        if to_whitelist:
            added = self._append_to_whitelist(to_whitelist)
            print(f"  ✓ {added} new terms written to WHITELIST.")
        if to_block or to_whitelist:
            print("  Run pipeline.run_clean_store() to apply blocklist changes.")
        skipped = len(new_to_review) - len(to_block) - len(to_whitelist)
        if skipped:
            print(f"  {skipped} entities skipped (not yet classified).")

    # ── SapBERT blocklist similarity scan ────────────────────────────────────

    def sapbert_blocklist_scan(
        self,
        store,
        embedder,
        similarity_threshold: float = 0.92,
    ) -> None:
        """
        Compare store entities against blocklist terms via SapBERT cosine similarity.

        Entities above similarity_threshold to any blocklist term are presented
        for interactive review. Run AFTER mapping has been applied so entity names
        are in their canonical form.

        y = out of scope → BLOCKLIST  |  n = keep → WHITELIST  |  s = skip  |  ESC = exit

        After review, call pipeline.run_clean_store() to purge newly blocked entities.
        """
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        self._reload_lists()

        entities = list(store.entities)
        if not entities:
            print("[StoreCleaner] sapbert_blocklist_scan: store has no entities.")
            return

        blocklist_terms = sorted(self.blocked_entities)
        if not blocklist_terms:
            print("[StoreCleaner] sapbert_blocklist_scan: blocklist is empty.")
            return

        print(f"[StoreCleaner] Embedding {len(entities)} store entities...")
        entity_embs = embedder.embed(entities)          # (E, H)

        print(f"[StoreCleaner] Embedding {len(blocklist_terms)} blocklist terms...")
        block_embs  = embedder.embed(blocklist_terms)   # (B, H)

        print("[StoreCleaner] Computing similarity matrix...")
        sim = cosine_similarity(entity_embs, block_embs)  # (E, B)

        max_sims = sim.max(axis=1)     # (E,)
        max_idxs = sim.argmax(axis=1)  # (E,)

        # Collect flagged entities (skip those already explicitly classified)
        flagged: list[tuple[str, float, str]] = []
        for i, entity in enumerate(entities):
            if max_sims[i] < similarity_threshold:
                continue
            elower = entity.strip().lower()
            ebase  = re.sub(r"\s*\([^)]*\)\s*$", "", elower).strip()
            if elower in self.blocked_entities or ebase in self.blocked_entities:
                continue
            if elower in self.whitelist or ebase in self.whitelist:
                continue
            flagged.append((entity, float(max_sims[i]), blocklist_terms[max_idxs[i]]))

        flagged.sort(key=lambda x: -x[1])

        if not flagged:
            print(f"  No store entities exceeded similarity threshold {similarity_threshold}.")
            return

        print(f"\n{'='*80}")
        print(f"  SapBERT Blocklist Scan — {len(flagged)} entities flagged (threshold={similarity_threshold})")
        print(f"  y = out of scope → BLOCKLIST  |  n = keep → WHITELIST  |  s = skip  |  ESC = exit")
        print(f"{'='*80}\n")

        to_block:     set[str] = set()
        to_whitelist: set[str] = set()

        for entity, sim_score, nearest in flagged:
            answer = self._prompt(
                f"  (sim={sim_score:.3f}, nearest='{nearest}')  '{entity}'  out of scope? [y/n/s] "
            ).strip().lower()
            if answer == "esc":
                print("  Exiting scan.")
                break
            if answer == "y":
                to_block.add(entity.strip().lower())
            elif answer == "n":
                to_whitelist.add(entity.strip().lower())

        self._save_review_results(to_block, to_whitelist, apply_hint="clean_entities")

    # ── Reporting ─────────────────────────────────────────────────────────────

    @staticmethod
    def print_report(report: dict) -> None:
        print("[StoreCleaner] Cleaning complete")
        print(f"  Blocked entities removed   : {report.get('blocked_entities', 0)}")
        print(f"  Rogue predicates stripped  : {report.get('rogue_predicates_removed', 0)}")
        print(f"  Empty entities pruned      : {report.get('empty_entities_pruned', 0)}")
        breakdown = report.get("rogue_predicate_breakdown", {})
        if breakdown:
            top = sorted(breakdown.items(), key=lambda x: -x[1])[:10]
            print(f"  Rogue predicate breakdown  : {dict(top)}")
        examples = report.get("blocked_entity_examples", [])
        if examples:
            print(f"  Blocked entity examples    : {examples[:10]}")
