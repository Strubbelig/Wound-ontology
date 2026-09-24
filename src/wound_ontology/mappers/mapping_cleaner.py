"""Curator layer for the term mapping.

Inspects, reviews, and cleans the TermMapping.  The only layer that knows
about blocklists, interactive prompts, and CSV review workflows.

Layer 4 in the mapper stack:
  DataManager (repo) → TermMapping (persistence) → TermMapper (action) → MappingCleaner (curator)
"""

from __future__ import annotations

import re

import pandas as pd

from wound_ontology.store.base_cleaner import BaseCleaner


class MappingCleaner(BaseCleaner):
    """Inspect, review, and clean the shared medical-term mapper."""

    def __init__(
        self,
        term_mapper,
        allowed_predicates: list[str] | None = None,
        extra_blocked_entities: set[str] | None = None,
    ):
        super().__init__(allowed_predicates or [], extra_blocked_entities)
        self.term_mapper = term_mapper

    # ── Inspection ────────────────────────────────────────────────────────────

    def list_mappings(self) -> None:
        """Print all mapping entries with blocklist / suspicious flags."""
        self._reload_lists()
        mapping = self.term_mapper.mapping
        print(f"\n[Term mapper — {len(mapping)} entries]")
        print(f"  {'':4}  {'Raw term':<45}  →  Standardized")
        print(f"  {'─'*4}  {'─'*45}     {'─'*30}")
        for raw, std in sorted(mapping.items()):
            score = self._score(raw)
            flag  = " ✗  " if score == 100.0 else (" ?  " if score > 0 else " ·  ")
            print(f"  {flag}  {raw:<45}  →  {std}")

    def list_suspicious_mappings(self) -> None:
        """Print only entries whose raw term is blocked or suspicious."""
        self._reload_lists()
        suspicious = sorted(
            [(raw, std) for raw, std in self.term_mapper.mapping.items()
             if self._score(raw) > 0],
            key=lambda x: -self._score(x[0]),
        )
        if not suspicious:
            print("No suspicious mapping entries found.")
            return
        print(f"\n[Term mapper — {len(suspicious)} suspicious entries]")
        print(f"  ✗ = blocklist  |  ? = suspicious keyword match")
        for raw, std in suspicious:
            flag = "✗" if self._score(raw) == 100.0 else "?"
            print(f"  [{flag}]  '{raw}'  →  '{std}'")

    # ── Interactive review ────────────────────────────────────────────────────

    def review_merged_mappings(self) -> None:
        """Per-entry review of all non-identity SapBERT cluster merges.

        y = keep merge  |  n = restore as independent concept  |  s = skip
        """
        mapping      = self.term_mapper.mapping
        non_identity = sorted(
            [(raw, std) for raw, std in mapping.items()
             if raw.strip().lower() != std.strip().lower()],
            key=lambda x: x[1].lower(),
        )

        print(f"\n{'='*80}")
        print(f"  Review SapBERT cluster mappings — {len(non_identity)} non-identity entries")
        print(f"  y = keep  |  n = restore as separate concept  |  s = skip  |  ESC = exit")
        print(f"{'='*80}\n")

        if not non_identity:
            print("  No non-identity mappings to review.")
            return

        to_delete: set[str] = set()
        for raw, std in non_identity:
            answer = self._prompt(f"  '{raw}'  →  '{std}'  keep? [y/n/s] ").strip().lower()
            if answer == "esc":
                print("  Exiting review.")
                break
            if answer == "n":
                to_delete.add(raw)

        if to_delete:
            removed = self._remove_entries(to_delete)
            print(f"\n  Restored {removed} terms as independent concepts.")
        else:
            print("\n  No entries removed.")

        print("  Done. Run pipeline.mapping_cleaner.apply(pipeline.store) when satisfied.")

    def review_mappings(self) -> None:
        """Per-entry review of suspicious mapping entries.

        y = keep  |  n = delete from mapper  |  s = skip
        """
        self._reload_lists()
        any_reviewed = False

        print(f"\n{'='*80}")
        print(f"  Review suspicious mapping entries")
        print(f"  y = keep  |  n = delete  |  s = skip")
        print(f"{'='*80}")

        suspicious = sorted(
            [(raw, std) for raw, std in self.term_mapper.mapping.items()
             if self._score(raw) > 0],
            key=lambda x: -self._score(x[0]),
        )
        if not suspicious:
            print("\n  [Term mapper] No suspicious entries — skipping.")
        else:
            to_delete: set[str] = set()
            print(f"\n  [Term mapper — {len(suspicious)} suspicious entries]")
            for raw, std in suspicious:
                elower = raw.strip().lower()
                ebase  = re.sub(r"\s*\([^)]*\)\s*$", "", elower).strip()
                if elower in self.whitelist or ebase in self.whitelist:
                    print(f"  ✓  '{raw}' → '{std}'  — whitelisted, skipping")
                    continue
                flag   = "✗" if self._score(raw) == 100.0 else "?"
                answer = input(f"  [{flag}]  '{raw}' → '{std}'  keep? [y/n/s] ").strip().lower()
                if answer == "n":
                    to_delete.add(raw)
                any_reviewed = True

            if to_delete:
                removed = self._remove_entries(to_delete)
                print(f"  Removed {removed} entries from Term mapper.")

        if any_reviewed:
            print("\n  Done. Run pipeline.mapping_cleaner.apply(pipeline.store) to apply.")
        else:
            print("\n  Nothing to review.")

    # ── CSV review workflow ───────────────────────────────────────────────────

    def export_review_csv(self, path: str) -> None:
        """Export low-confidence mappings for human review.

        Produces a CSV with columns: term, suggested_standard, confidence,
        method, reviewed_standard (to fill), notes (to fill).
        """
        metadata = self.term_mapper._term_mapping.metadata
        rows = [
            {
                "term":               term,
                "suggested_standard": meta["standard"],
                "confidence":         meta["confidence"],
                "method":             meta["method"],
                "reviewed_standard":  "",
                "notes":              "",
            }
            for term, meta in metadata.items()
            if meta["confidence"] < self.term_mapper._review_threshold
        ]
        pd.DataFrame(rows).to_csv(path, index=False)
        print(f"[Term mapper] Exported {len(rows)} low-confidence rows → {path}")

    def import_review_csv(self, path: str) -> None:
        """Re-ingest human-reviewed decisions from a review CSV.

        Any non-empty 'reviewed_standard' column value overrides the current
        mapping entry and is recorded with confidence=1.0, method='manual'.
        """
        df      = pd.read_csv(path)
        updates = 0
        for _, row in df.iterrows():
            reviewed = row.get("reviewed_standard")
            if pd.notna(reviewed) and str(reviewed).strip():
                self.term_mapper._term_mapping.add(
                    term=row["term"],
                    standard=str(reviewed).strip(),
                    confidence=1.0,
                    method="manual",
                )
                updates += 1
        print(f"[Term mapper] Applied {updates} human-reviewed mappings.")

    # ── Auto-cleaning ─────────────────────────────────────────────────────────

    def clean_mappings(self) -> dict[str, int]:
        """Auto-remove entries whose raw term is in the blocklist."""
        self._reload_lists()
        to_delete = {raw for raw in self.term_mapper.mapping if self._is_blocked(raw)}
        if to_delete:
            removed = self._remove_entries(to_delete)
            print(f"  term_mapper: removed {removed} blocked entries.")
            return {"term_mapper_entries_removed": removed}
        print("  term_mapper: no blocked entries found.")
        return {}

    # ── Apply ─────────────────────────────────────────────────────────────────

    def apply(self, store, *, max_passes: int = 10) -> int:
        """Apply the mapping to the store, and keep applying until it stops
        changing. Returns how many passes that took.

        One pass was never enough, and the shortfall was silent.
        `ConceptStore.normalize` maps a name and THEN title-cases it, so the
        name a pass produces can itself be a mapping key — or fold onto one —
        that the same pass has already walked past. Measured 2026-09-23 on the
        6,029-abstract store: pass 1 collapsed 12,912 names, pass 2 another
        **1,191**, pass 3 one more, pass 4 none. Stopping after pass 1 left
        1,192 merges undone and reported a completed apply.

        Applying is idempotent once it has converged (rule 24), so the extra
        passes cost a rewrite of the store and nothing else. Not converging is
        a failure, not a result: it means the mapping is still moving names
        around after ten rewrites, and the raise says so rather than leaving
        the store wherever the last pass happened to stop.
        """
        previous: int | None = None
        for attempt in range(1, max_passes + 1):
            store.normalize(mapper=self.term_mapper)
            names = len(store.entities)
            if names == previous:
                if attempt > 2:
                    print(f"  term_mapper: the store settled after {attempt - 1} "
                          f"pass(es); a single pass would have left "
                          f"{attempt - 2} round(s) of merges undone.")
                return attempt - 1
            previous = names
        raise RuntimeError(
            f"[{self.term_mapper.name}] the store is still changing after {max_passes} "
            f"passes of the mapping ({previous} distinct entity names at the "
            f"last one). The mapping is moving names in a loop; it was NOT "
            f"applied completely."
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _remove_entries(self, keys: set[str]) -> int:
        """Remove entries from TermMapping (saves automatically)."""
        return self.term_mapper._term_mapping.remove(*keys)
