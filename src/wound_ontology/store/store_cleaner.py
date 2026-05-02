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
            [(t, c, self._score(t)) for t, c in freq.items() if self._score(t) > 0],
            key=lambda x: (-x[2], -x[1]),
        )
        if not ranked:
            print("No suspicious or blocked targets found.")
            return

        to_block: set[str] = set()
        to_whitelist: set[str] = set()

        print(f"\n{'='*80}")
        print(f"  {len(ranked)} suspicious/blocked targets")
        print(f"  ✗ = blocklist  |  ✓ = whitelisted  |  ? = suspicious")
        print(f"  y = in scope → WHITELIST  |  n = out of scope → BLOCKLIST  |  s = skip")
        print(f"{'='*80}\n")

        for target, count, score in ranked:
            tlower = target.strip().lower()
            tbase = re.sub(r"\s*\([^)]*\)\s*$", "", tlower).strip()
            if tlower in self.whitelist or tbase in self.whitelist:
                print(f"  ✓ (freq={count:>4})  '{target}'  — already whitelisted, skipping")
                continue
            flag = "✗" if score == 100.0 else "?"
            answer = input(f"  [{flag}] (freq={count:>4})  '{target}'  in scope? [y/n/s] ").strip().lower()
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

        for predicate in set(store.predicates):
            if predicate and predicate not in self.allowed_predicates:
                stats["rogue_predicates_removed"] += 1
                rogue_pred_counts[predicate] += 1

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
                to_delete = [
                    attr for attr in attrs
                    if ':' in attr and self._is_blocked(attr.split(':', 1)[1].strip())
                ]
                for attr in to_delete:
                    del attrs[attr]
                    stats["blocked_targets_removed"] += 1

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

    def review_susp_entities(self, store) -> None:
        """Review suspicious and blocked entities using keyword scoring — whitelist (y), block (n), or skip (s)."""
        self._reload_lists()
        ranked = [
            (e, c, s, a) for e, c, s, a in self._collect_ranked(store) if s > 0
        ]
        if not ranked:
            print("No suspicious or blocked entities found.")
            return

        to_block: set[str] = set()
        to_whitelist: set[str] = set()

        print(f"\n{'='*80}")
        print(f"  {len(ranked)} suspicious/blocked entities")
        print(f"  ✗ = blocklist  |  ✓ = whitelisted  |  ? = suspicious")
        print(f"  y = in scope → WHITELIST  |  n = out of scope → BLOCKLIST  |  s = skip")
        print(f"{'='*80}\n")

        for entity, count, score, attrs in ranked:
            elower = entity.strip().lower()
            ebase = re.sub(r"\s*\([^)]*\)\s*$", "", elower).strip()
            if elower in self.whitelist or ebase in self.whitelist:
                print(f"  ✓ (freq={count:>4})  '{entity}'  — already whitelisted, skipping")
                continue
            flag = "✗" if score == 100.0 else "?"
            answer = input(f"  [{flag}] (freq={count:>4})  '{entity}'  in scope? [y/n/s] ").strip().lower()
            if answer == "y":
                to_whitelist.add(entity)
            elif answer == "n":
                to_block.add(entity)

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
        # Collect all entities sorted by frequency descending
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
