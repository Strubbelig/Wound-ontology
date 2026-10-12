from __future__ import annotations
import asyncio
import re
from collections import Counter, defaultdict
from typing import Any

from wound_ontology.store.base_cleaner import BaseCleaner
from wound_ontology.store.concept_store import records_of

class StoreCleaner(BaseCleaner):
    """
    Rejects out-of-scope entities and invalid predicates in a ConceptStore.

    Scope -- is a term, or a relation's target, out of the ontology? -- is not
    written into the store at all since 2026-09-28: the store's view asks the
    gate live, through this cleaner's `_is_blocked` (rule 51). `clean_entities`
    and `clean_targets` REPORT what the gate blocks and write nothing; the
    verdicts they used to write froze the lists as they stood on the day of the
    run.

    Two operations are still verdicts (``by`` names the rule, so it can be
    lifted and re-applied):
      - Predicate filter  : rejects cells whose predicate is not allowed        (by="predicate_filter")
      - Empty-entity prune: rejects entities left with no standing true cell   (by="prune")

    None of these deletes. Until 2026-09-12 all three did, so a term blocked by
    a list entry that was later withdrawn stayed gone, and the 278 entities
    the blocklist removed during the 606-abstract extraction left no trace in
    the store. `clean()` first lifts its own earlier verdicts, so every run
    reflects the lists as they are now -- un-blocking a term works.

    Usage::

        cleaner = StoreCleaner(allowed_predicates=ALLOWED_PREDICATES)
        report  = cleaner.clean(store)
        cleaner.print_report(report)
    """

    # ── Main entry point ──────────────────────────────────────────────────────

    def clean_entities(self, store) -> dict:
        """Count the entities the gate puts out of scope. Writes nothing.

        The view excludes them live (rule 51), so a report is all that is left
        to do here: which names, and how many.
        """
        self._reload_lists()
        names = {e for _, ents in store.view(include_rejected=True) for e in ents}
        blocked = sorted(e for e in names if self._is_blocked(e))
        return {"blocked_entities": len(blocked),
                "blocked_entity_examples": blocked[:20]}

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
        """Review entities blocked by automatic rules (keyword/noise) — not explicit blocklist entries.

        Only surfaces false-positive candidates: entities in the store that are blocked
        solely because they matched KEYWORD_BLOCKLIST or the noise filter, not because
        they were explicitly added to METHODOLOGY_BLOCKLIST.
        """
        self._reload_lists()
        auto_blocked = sorted(
            e for e in store.entities
            if self._is_blocked(e)
            and not (e.strip().lower() in self.blocked_entities
                     or re.sub(r"\s*\([^)]*\)\s*$", "", e.strip().lower()).strip()
                     in self.blocked_entities)
        )
        if not auto_blocked:
            print("No auto-blocked entities to review.")
            return
        self._review_to_whitelist(auto_blocked, label="entity")

    def review_blocked_targets(self, store) -> None:
        """Review blocked targets in the store — keep blocked (n) or move to WHITELIST (y)."""
        self._reload_lists()
        blocked = sorted(set(t for t in store.targets if self._is_blocked(t)))
        if not blocked:
            print("No blocked targets in store.")
            return
        self._review_to_whitelist(blocked, label="target")

    def review_susp_targets(
        self,
        store,
        embedder=None,
        high_threshold: float = 0.92,
        low_threshold: float = 0.40,
        save_skipped: bool = False,
        llm=None,
        llm_batch_size: int = 50,
        run_sync=None,
    ) -> None:
        """
        Review undecided targets by SapBERT similarity to the nearest blocklist term.

          score ≥ high_threshold → auto-block
          score < low_threshold  → silently skip (saved to WHITELIST if save_skipped=True)
          zone (between)         → LLM batch filter if llm provided, then manual for remainder
        """
        if self._abort_review:
            return
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        self._reload_lists()
        seen: set[str] = self._load_seen()

        freq: Counter = Counter()
        for _, ents in records_of(store):
            for _, attrs in ents.items():
                for attr in attrs:
                    if ':' in attr:
                        freq[attr.split(':', 1)[1].strip()] += 1

        undecided: list[str] = []
        for target in freq:
            if self._score(target) == 100.0:
                continue
            tlower = target.strip().lower()
            tbase  = re.sub(r"\s*\([^)]*\)\s*$", "", tlower).strip()
            if (tlower not in self.whitelist and tbase not in self.whitelist
                    and not self.blocker.white_kw.match(target)
                    and tlower not in seen and tbase not in seen):
                undecided.append(target)

        if not undecided or not embedder:
            print("No undecided targets found.")
            return

        store_blocked = {t.strip().lower() for t in freq if self._is_blocked(t)}
        bl_terms = sorted(self.blocked_entities | store_blocked)
        if not bl_terms:
            print("Blocklist is empty — skipping.")
            return

        print(f"[StoreCleaner] Embedding {len(undecided)} targets...")
        tgt_embs = np.array(embedder.embed(undecided))   # (U, H)
        tgt_idx  = {t: i for i, t in enumerate(undecided)}
        print(f"[StoreCleaner] Embedding {len(bl_terms)} blocklist terms "
              f"({len(store_blocked)} from store keywords)...")
        bl_embs  = np.array(embedder.embed(bl_terms))    # (B, H)

        sim = cosine_similarity(tgt_embs, bl_embs)       # (U, B)
        scores: dict[str, tuple[float, str]] = {
            t: (float(sim[i].max()), bl_terms[int(sim[i].argmax())])
            for i, t in enumerate(undecided)
        }

        processed: set[str] = set()

        auto_blocked = [t for t in undecided if scores[t][0] >= high_threshold]
        if auto_blocked:
            print(f"\n  Auto-blocking {len(auto_blocked)} targets (cos ≥ {high_threshold}):")
            for t in sorted(auto_blocked, key=lambda t: -scores[t][0]):
                s, n = scores[t]
                print(f"    cos={s:.3f}  '{t}'  ≈  '{n}'")
            ab_lower = {t.strip().lower() for t in auto_blocked}
            self._append_to_blocklist(ab_lower)
            self._remove_from_whitelist(ab_lower)
            self._reload_lists()
            processed.update(auto_blocked)

        skipped_list = [t for t in undecided if scores[t][0] < low_threshold]
        if skipped_list:
            if save_skipped:
                self._append_to_whitelist(set(skipped_list))
                self._reload_lists()
                print(f"  {len(skipped_list)} in-scope targets (cos < {low_threshold}) saved to WHITELIST.")
            else:
                print(f"  Silently skipping {len(skipped_list)} targets with cos < {low_threshold}.")

        def _queue():
            return sorted(
                [t for t in undecided
                 if t not in processed and low_threshold <= scores[t][0] < high_threshold],
                key=lambda t: -scores[t][0],
            )

        queue = _queue()
        if not queue:
            if not auto_blocked:
                print("  No targets in the review zone — nothing to do.")
            return

        # ── LLM batch filter ──────────────────────────────────────────────────
        if llm and run_sync and queue:
            print(f"\n  Running LLM scope filter on {len(queue)} zone targets "
                  f"(batches of {llm_batch_size})...")

            async def _llm_filter():
                flagged: list[str] = []
                for i in range(0, len(queue), llm_batch_size):
                    batch = queue[i:i + llm_batch_size]
                    candidates = [(t, freq[t], []) for t in batch]
                    flagged.extend(await llm.classify_scope_batch(candidates))
                return flagged

            llm_blocked = run_sync(_llm_filter())
            llm_blocked_set = {t.strip().lower() for t in llm_blocked}

            if llm_blocked:
                print(f"  LLM flagged {len(llm_blocked)} targets as out of scope → BLOCKLIST")
                self._append_to_blocklist(llm_blocked_set)
                self._remove_from_whitelist(llm_blocked_set)
                self._reload_lists()
                processed.update(llm_blocked)

            llm_kept = [t for t in queue if t not in processed]
            if llm_kept:
                self._append_to_whitelist(set(llm_kept))
                self._reload_lists()
                print(f"  LLM kept {len(llm_kept)} targets as in scope → WHITELIST")
                processed.update(llm_kept)

            queue = _queue()

        if not queue:
            return

        print(f"\n{'='*80}")
        print(f"  {len(queue)} targets for manual review (cos {low_threshold}–{high_threshold})")
        print(f"  y = in scope → WHITELIST  |  n = out of scope → BLOCKLIST  |  s = skip  |  q = quit all")
        print(f"{'='*80}\n")

        while queue:
            target = queue.pop(0)
            if target in processed:
                continue
            score, nearest = scores[target]
            answer = self._prompt(
                f"  [?] (freq={freq[target]:>4}, cos={score:.3f} ≈ '{nearest}')  '{target}'  in scope? [y/n/s/q] "
            ).strip().lower()
            if answer in ("esc", "q"):
                self._abort_review = True
                print("  Exiting review.")
                break
            if answer == "y":
                self._append_to_whitelist({target})
                self._remove_from_blocklist({target})
                self._reload_lists()
                processed.add(target)
                seen.add(target.strip().lower()); self._save_seen(seen)
            elif answer == "n":
                tl = target.strip().lower()
                self._append_to_blocklist({tl})
                self._remove_from_whitelist({tl})
                self._reload_lists()
                processed.add(target)
                seen.add(tl); self._save_seen(seen)
                # ── Incremental update ────────────────────────────────────────
                new_emb  = tgt_embs[tgt_idx[target]].reshape(1, -1)
                remaining = [t for t in undecided if t not in processed]
                if remaining:
                    r_idx    = [tgt_idx[t] for t in remaining]
                    new_sims = cosine_similarity(tgt_embs[r_idx], new_emb).ravel()
                    newly_auto: list[str] = []
                    for t, ns in zip(remaining, new_sims):
                        if ns > scores[t][0]:
                            scores[t] = (float(ns), target)
                        if scores[t][0] >= high_threshold:
                            newly_auto.append(t)
                    if newly_auto:
                        print(f"\n  → {len(newly_auto)} target(s) now above threshold:")
                        for t in sorted(newly_auto, key=lambda t: -scores[t][0]):
                            s, n = scores[t]
                            print(f"    cos={s:.3f}  '{t}'  ≈  '{n}'")
                        na_lower = {t.strip().lower() for t in newly_auto}
                        self._append_to_blocklist(na_lower)
                        self._remove_from_whitelist(na_lower)
                        self._reload_lists()
                        processed.update(newly_auto)
                    queue = _queue()
            elif answer == "s":
                seen.add(target.strip().lower()); self._save_seen(seen)

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

        doomed = [(e, t) for _, e, t, _ in store.assertions()
                  if ':' in t and t.split(':', 1)[0].strip() not in self.allowed_predicates]
        store.reject_cells(doomed, by="predicate_filter",
                           note=f"predicate not in {sorted(self.allowed_predicates)}")

        return {
            **dict(stats),
            "rogue_predicate_breakdown": dict(rogue_pred_counts),
        }

    def clean_targets(self, store) -> dict:
        """Count the relations whose target the gate puts out of scope. Writes
        nothing: the view drops them live (rule 51)."""
        self._reload_lists()
        n = sum(1 for _, ents in store.view(include_rejected=True)
                for attrs in ents.values() for t in attrs
                if ':' in t and self._is_blocked(t.split(':', 1)[1].strip()))
        return {"blocked_targets_removed": n}

    def prune_empty_entities(self, store) -> dict:
        """
        Remove entities that have no confirmed (value == 1.0) attributes.

        Returns a report dict with counts of what was removed.
        """
        stats: dict[str, int] = defaultdict(int)

        # An entity is empty when NO standing cell anywhere asserts it -- per
        # store, not per abstract. The old per-abstract deletion removed a term
        # from the one abstract that only denied it while keeping it elsewhere,
        # which was a partial record dressed as a prune.
        standing: set[str] = set()
        for _, entity, _, value in store.assertions():
            if value == 1.0:
                standing.add(entity)
        empty = [e for e in store.entities if e not in standing]
        stats["empty_entities_pruned"] = store.reject_entities(
            empty, by="prune", note="no standing true attribute")
        return dict(stats)

    def clean_attributes(self, store) -> dict:
        """Remove rogue predicates, blocked targets, then prune emptied entities."""
        pred_report   = self.clean_predicates(store)
        target_report = self.clean_targets(store)
        prune_report  = self.prune_empty_entities(store)
        return {**pred_report, **target_report, **prune_report}

    AUTHORS = ("blocklist", "predicate_filter", "prune")

    def clean(self, store) -> dict:
        """Run all cleaning steps: entities, predicates, blocked targets, empty-entity pruning.

        Its own earlier verdicts are lifted first, so the result is the lists
        as they stand now, not the union of every list that ever stood."""
        lifted = 0
        for by in self.AUTHORS:
            got = store.lift_decisions(by)
            lifted += len(got["entity_verdicts"]) + sum(len(c) for c in got["cell_verdicts"].values())
        entity_report = self.clean_entities(store)
        attr_report   = self.clean_attributes(store)
        return {**entity_report, **attr_report, "verdicts_lifted": lifted}

    # ── Candidate scanning ────────────────────────────────────────────────────

    def _collect_ranked(
        self,
        store,
        embedder=None,
    ) -> list[tuple[str, int, float, list[str], str]]:
        """
        Return entities sorted by descending out-of-scope likelihood.

        Tuple: (entity, pmid_freq, score, sample_attrs, nearest_bl_term)
          score = 100.0  : explicitly blocked or noise
          score = 0.0    : whitelisted or no blocklist similarity
          score ∈ (0, 1) : SapBERT cosine similarity to nearest blocklist term
        """
        from sklearn.metrics.pairwise import cosine_similarity

        freq: Counter = Counter()
        sample_attrs: dict[str, list[str]] = {}
        for _, ents in records_of(store):
            for entity, attrs in ents.items():
                freq[entity] += 1
                if entity not in sample_attrs:
                    sample_attrs[entity] = [a for a, v in attrs.items() if v == 1.0][:4]

        entities = list(freq.keys())
        decided: dict[str, tuple[float, str]] = {}
        undecided: list[str] = []
        for entity in entities:
            s = self._score(entity)
            if s == 100.0:
                decided[entity] = (100.0, "")
            else:
                lower = entity.strip().lower()
                base = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
                if lower in self.whitelist or base in self.whitelist:
                    decided[entity] = (0.0, "")
                else:
                    undecided.append(entity)

        sapbert: dict[str, tuple[float, str]] = {}
        bl_terms = sorted(self.blocked_entities)
        if embedder and undecided and bl_terms:
            print(f"[StoreCleaner] Embedding {len(undecided)} entities for SapBERT ranking...")
            ent_embs = embedder.embed(undecided)
            bl_embs  = embedder.embed(bl_terms)
            sim      = cosine_similarity(ent_embs, bl_embs)
            max_sims = sim.max(axis=1)
            max_idxs = sim.argmax(axis=1)
            for i, entity in enumerate(undecided):
                sapbert[entity] = (float(max_sims[i]), bl_terms[int(max_idxs[i])])
        else:
            for entity in undecided:
                sapbert[entity] = (0.0, "")

        result: list[tuple[str, int, float, list[str], str]] = []
        for entity in entities:
            sc, nb = decided.get(entity) or sapbert[entity]
            result.append((entity, freq[entity], sc, sample_attrs.get(entity, []), nb))
        result.sort(key=lambda x: (-x[2], -x[1]))
        return result

    def _check_list_exclusivity(self, embedder, threshold: float) -> None:
        """Warn if any whitelist term is semantically similar to a blocklist term."""
        if self._abort_review:
            return
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        wl_terms = sorted(self.whitelist)
        bl_terms = sorted(self.blocked_entities)
        if not wl_terms or not bl_terms:
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

        # Deduplicate: one question per unique blocklist term (highest-sim pair shown).
        seen: dict[str, tuple[str, float]] = {}
        for wt, bt, s in conflicts:
            if bt not in seen or s > seen[bt][1]:
                seen[bt] = (wt, s)
        deduped = sorted(
            [(wt, bt, s) for bt, (wt, s) in seen.items()],
            key=lambda x: -x[2],
        )

        print(f"\n  ⚠ {len(deduped)} conflict(s) between whitelist and blocklist (cos ≥ {threshold}).")
        print(f"  w = WHITELIST wins → move blocklist term to whitelist")
        print(f"  b = BLOCKLIST wins → move whitelist term to blocklist")
        print(f"  s = skip  |  q = quit\n")

        resolved = 0
        for wt, bt, s in deduped:
            answer = self._prompt(
                f"  cos={s:.3f}  WL='{wt}'  ≈  BL='{bt}'  [w/b/s/q] "
            ).strip().lower()
            if answer in ("esc", "q"):
                self._abort_review = True
                print("  Exiting.")
                break
            if answer == "w":
                self._append_to_whitelist({bt})
                self._remove_from_blocklist({bt})
                self._reload_lists()
                resolved += 1
                print(f"    ✓ '{bt}' → WHITELIST.")
            elif answer == "b":
                self._append_to_blocklist({wt})
                self._remove_from_whitelist({wt})
                self._reload_lists()
                resolved += 1
                print(f"    ✓ '{wt}' → BLOCKLIST.")

        skipped = len(deduped) - resolved
        if skipped:
            print(f"  {skipped} conflict(s) skipped.")

    def review_susp_entities(
        self,
        store,
        embedder=None,
        high_threshold: float = 0.92,
        low_threshold: float = 0.40,
        save_skipped: bool = False,
        llm=None,
        llm_batch_size: int = 50,
        run_sync=None,
    ) -> None:
        """
        Review undecided entities by SapBERT similarity to the nearest blocklist term.

          score ≥ high_threshold → auto-block
          score < low_threshold  → silently skip (saved to WHITELIST if save_skipped=True)
          zone (between)         → LLM batch filter if llm provided, then manual for remainder
        """
        if self._abort_review:
            return
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        self._reload_lists()
        seen: set[str] = self._load_seen()

        freq: Counter = Counter()
        sample_attrs: dict[str, list[str]] = {}
        for _, ents in records_of(store):
            for entity, attrs in ents.items():
                freq[entity] += 1
                if entity not in sample_attrs:
                    sample_attrs[entity] = [a for a, v in attrs.items() if v == 1.0][:3]

        undecided: list[str] = []
        for entity in freq:
            if self._score(entity) == 100.0:
                continue
            lower = entity.strip().lower()
            base  = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
            if (lower not in self.whitelist and base not in self.whitelist
                    and not self.blocker.white_kw.match(entity)
                    and lower not in seen and base not in seen):
                undecided.append(entity)

        if not undecided or not embedder:
            print("No undecided entities found.")
            return

        store_blocked = {e.strip().lower() for e in freq if self._is_blocked(e)}
        bl_terms = sorted(self.blocked_entities | store_blocked)
        if not bl_terms:
            print("Blocklist is empty — skipping.")
            return

        print(f"[StoreCleaner] Embedding {len(undecided)} entities...")
        ent_embs = np.array(embedder.embed(undecided))   # (U, H)
        ent_idx  = {e: i for i, e in enumerate(undecided)}
        print(f"[StoreCleaner] Embedding {len(bl_terms)} blocklist terms "
              f"({len(store_blocked)} from store keywords)...")
        bl_embs  = np.array(embedder.embed(bl_terms))    # (B, H)

        sim = cosine_similarity(ent_embs, bl_embs)       # (U, B)
        scores: dict[str, tuple[float, str]] = {
            e: (float(sim[i].max()), bl_terms[int(sim[i].argmax())])
            for i, e in enumerate(undecided)
        }

        processed: set[str] = set()

        auto_blocked = [e for e in undecided if scores[e][0] >= high_threshold]
        if auto_blocked:
            print(f"\n  Auto-blocking {len(auto_blocked)} entities (cos ≥ {high_threshold}):")
            for e in sorted(auto_blocked, key=lambda e: -scores[e][0]):
                s, n = scores[e]
                print(f"    cos={s:.3f}  '{e}'  ≈  '{n}'")
            ab_lower = {e.strip().lower() for e in auto_blocked}
            self._append_to_blocklist(ab_lower)
            self._remove_from_whitelist(ab_lower)
            self._reload_lists()
            processed.update(auto_blocked)

        skipped_list = [e for e in undecided if scores[e][0] < low_threshold]
        if skipped_list:
            if save_skipped:
                self._append_to_whitelist(set(skipped_list))
                self._reload_lists()
                print(f"  {len(skipped_list)} in-scope entities (cos < {low_threshold}) saved to WHITELIST.")
            else:
                print(f"  Silently skipping {len(skipped_list)} entities with cos < {low_threshold}.")

        def _queue():
            return sorted(
                [e for e in undecided
                 if e not in processed and low_threshold <= scores[e][0] < high_threshold],
                key=lambda e: -scores[e][0],
            )

        queue = _queue()
        if not queue:
            if not auto_blocked:
                print("  No entities in the review zone — nothing to do.")
            return

        # ── LLM batch filter ──────────────────────────────────────────────────
        if llm and run_sync and queue:
            print(f"\n  Running LLM scope filter on {len(queue)} zone entities "
                  f"(batches of {llm_batch_size})...")

            async def _llm_filter():
                flagged: list[str] = []
                total = (len(queue) + llm_batch_size - 1) // llm_batch_size
                for i in range(0, len(queue), llm_batch_size):
                    batch = queue[i:i + llm_batch_size]
                    batch_n = i // llm_batch_size + 1
                    print(f"  [LLM] batch {batch_n}/{total} "
                          f"({len(flagged)} flagged so far)...", flush=True)
                    candidates = [(e, freq[e], sample_attrs.get(e, [])) for e in batch]
                    flagged.extend(await llm.classify_scope_batch(candidates))
                return flagged

            llm_blocked = run_sync(_llm_filter())
            llm_blocked_set = {e.strip().lower() for e in llm_blocked}

            if llm_blocked:
                print(f"  LLM flagged {len(llm_blocked)} entities as out of scope → BLOCKLIST")
                self._append_to_blocklist(llm_blocked_set)
                self._remove_from_whitelist(llm_blocked_set)
                self._reload_lists()
                processed.update(llm_blocked)

            llm_kept = [e for e in queue if e not in processed]
            if llm_kept:
                self._append_to_whitelist(set(llm_kept))
                self._reload_lists()
                print(f"  LLM kept {len(llm_kept)} entities as in scope → WHITELIST")
                processed.update(llm_kept)

            queue = _queue()

        if not queue:
            return

        print(f"\n{'='*80}")
        print(f"  {len(queue)} entities for manual review (cos {low_threshold}–{high_threshold})")
        print(f"  y = in scope → WHITELIST  |  n = out of scope → BLOCKLIST  |  s = skip  |  q = quit all")
        print(f"{'='*80}\n")

        while queue:
            entity = queue.pop(0)
            if entity in processed:
                continue
            score, nearest = scores[entity]
            answer = self._prompt(
                f"  [?] (freq={freq[entity]:>4}, cos={score:.3f} ≈ '{nearest}')  '{entity}'  in scope? [y/n/s/q] "
            ).strip().lower()
            if answer in ("esc", "q"):
                self._abort_review = True
                print("  Exiting review.")
                break
            if answer == "y":
                self._append_to_whitelist({entity})
                self._remove_from_blocklist({entity})
                self._reload_lists()
                processed.add(entity)
                seen.add(entity.strip().lower()); self._save_seen(seen)
            elif answer == "n":
                el = entity.strip().lower()
                self._append_to_blocklist({el})
                self._remove_from_whitelist({el})
                self._reload_lists()
                processed.add(entity)
                seen.add(el); self._save_seen(seen)
                # ── Incremental update ────────────────────────────────────────
                new_emb   = ent_embs[ent_idx[entity]].reshape(1, -1)
                remaining = [e for e in undecided if e not in processed]
                if remaining:
                    r_idx    = [ent_idx[e] for e in remaining]
                    new_sims = cosine_similarity(ent_embs[r_idx], new_emb).ravel()
                    newly_auto: list[str] = []
                    for e, ns in zip(remaining, new_sims):
                        if ns > scores[e][0]:
                            scores[e] = (float(ns), entity)
                        if scores[e][0] >= high_threshold:
                            newly_auto.append(e)
                    if newly_auto:
                        print(f"\n  → {len(newly_auto)} entity(ies) now above threshold:")
                        for e in sorted(newly_auto, key=lambda e: -scores[e][0]):
                            s, n = scores[e]
                            print(f"    cos={s:.3f}  '{e}'  ≈  '{n}'")
                        na_lower = {e.strip().lower() for e in newly_auto}
                        self._append_to_blocklist(na_lower)
                        self._remove_from_whitelist(na_lower)
                        self._reload_lists()
                        processed.update(newly_auto)
                    queue = _queue()
            elif answer == "s":
                seen.add(entity.strip().lower()); self._save_seen(seen)

    # ── Reporting ─────────────────────────────────────────────────────────────

    @staticmethod
    def print_report(report: dict) -> None:
        print("[StoreCleaner] Cleaning complete (verdicts written to the store, nothing deleted)")
        print(f"  Earlier verdicts lifted    : {report.get('verdicts_lifted', 0)}")
        print(f"  Blocked entities rejected  : {report.get('blocked_entities', 0)}")
        print(f"  Blocked targets rejected   : {report.get('blocked_targets_removed', 0)}")
        print(f"  Rogue predicates rejected  : {report.get('rogue_predicates_removed', 0)}")
        print(f"  Empty entities rejected    : {report.get('empty_entities_pruned', 0)}")
        breakdown = report.get("rogue_predicate_breakdown", {})
        if breakdown:
            top = sorted(breakdown.items(), key=lambda x: -x[1])[:10]
            print(f"  Rogue predicate breakdown  : {dict(top)}")
        examples = report.get("blocked_entity_examples", [])
        if examples:
            print(f"  Blocked entity examples    : {examples[:10]}")

