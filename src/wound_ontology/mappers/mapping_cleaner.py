from __future__ import annotations
import re
from wound_ontology.store.base_cleaner import BaseCleaner


class MappingCleaner(BaseCleaner):
    """
    Reviews and cleans the shared medical-term mapper.

    Usage::

        cleaner = MappingCleaner(pipeline.term_mapper)
        cleaner.list_suspicious_mappings()
        cleaner.review_mappings()
        cleaner.apply(pipeline.store)
    """

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
        """Print all mapping entries with scope flags."""
        self._reload_lists()
        mapping = self.term_mapper.mapping
        print(f"\n[Term mapper — {len(mapping)} entries]")
        print(f"  {'':4}  {'Raw term':<45}  →  Standardized")
        print(f"  {'─'*4}  {'─'*45}     {'─'*30}")
        for raw, std in sorted(mapping.items()):
            score = self._score(raw)
            flag = " ✗  " if score == 100.0 else (" ?  " if score > 0 else " ·  ")
            print(f"  {flag}  {raw:<45}  →  {std}")

    def list_suspicious_mappings(self) -> None:
        """Print only mapping entries whose raw term is blocked or suspicious."""
        self._reload_lists()
        suspicious = sorted(
            [(raw, std) for raw, std in self.term_mapper.mapping.items() if self._score(raw) > 0],
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

    def review_mappings(self) -> None:
        """
        Per-entry review of suspicious mapping entries.
        y = keep  |  n = delete from mapper  |  s = skip
        """
        self._reload_lists()
        any_reviewed = False

        print(f"\n{'='*80}")
        print(f"  Review suspicious mapping entries")
        print(f"  y = keep  |  n = delete entry from mapper  |  s = skip")
        print(f"{'='*80}")

        suspicious = sorted(
            [(raw, std) for raw, std in self.term_mapper.mapping.items() if self._score(raw) > 0],
            key=lambda x: -self._score(x[0]),
        )
        if not suspicious:
            print("\n  [Term mapper] No suspicious entries — skipping.")
        else:
            to_delete: set[str] = set()
            print(f"\n  [Term mapper — {len(suspicious)} suspicious entries]")
            for raw, std in suspicious:
                elower = raw.strip().lower()
                # Strip parenthetical suffixes (e.g. "term (study)") before whitelist matching.
                ebase = re.sub(r"\s*\([^)]*\)\s*$", "", elower).strip()
                if elower in self.whitelist or ebase in self.whitelist:
                    print(f"  ✓  '{raw}' → '{std}'  — whitelisted, skipping")
                    continue
                flag = "✗" if self._score(raw) == 100.0 else "?"
                answer = input(f"  [{flag}]  '{raw}' → '{std}'  keep? [y/n/s] ").strip().lower()
                if answer == "n":
                    to_delete.add(raw)
                any_reviewed = True

            if to_delete:
                removed = self._delete_mapper_entries(self.term_mapper, to_delete)
                print(f"  Removed {removed} entries from Term mapper.")

        if any_reviewed:
            print("\n  Done. Run pipeline.mapping_cleaner.apply(pipeline.store) to apply approved mappings.")
        else:
            print("\n  Nothing to review.")

    # ── Cleaning ──────────────────────────────────────────────────────────────

    def clean_mappings(self) -> dict:
        """Auto-remove entries whose raw term is in the blocklist. Returns a report dict."""
        self._reload_lists()
        stats: dict[str, int] = {}
        to_delete = {raw for raw in self.term_mapper.mapping if self._is_blocked(raw)}
        if to_delete:
            removed = self._delete_mapper_entries(self.term_mapper, to_delete)
            stats["term_mapper_entries_removed"] = removed
            print(f"  term_mapper: removed {removed} blocked entries.")
        else:
            print("  term_mapper: no blocked entries found.")
        return stats

    # ── Apply ─────────────────────────────────────────────────────────────────

    def apply(self, store) -> None:
        """Apply the shared term mapper to entity names and attribute targets."""
        store.normalize(mapper=self.term_mapper)

    # ── Internal helper ───────────────────────────────────────────────────────

    @staticmethod
    def _delete_mapper_entries(mapper, keys: set[str]) -> int:
        """Directly remove entries from mapper._mapping (bypasses update-only setter)."""
        before = len(mapper._mapping)
        mapper._mapping = {k: v for k, v in mapper._mapping.items() if k not in keys}
        removed = before - len(mapper._mapping)
        if removed:
            mapper.save()
        return removed
