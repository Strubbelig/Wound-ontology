"""Persistence layer for the term → canonical mapping.

Holds the mapping dict and per-entry metadata in memory.
All mutation methods save to disk automatically via DataManager.
DataManager is the only I/O dependency — this class has no business logic.
"""

from __future__ import annotations

from wound_ontology.data_manager.data_manager import DataManager


class TermMapping:
    """Persistence data class for term → canonical term mapping.

    Layer 2 in the mapper stack:
      DataManager (repo) → TermMapping (persistence) → TermMapper (action) → MappingCleaner (curator)

    Metadata is rebuilt in-memory by TermMapper on each clustering run; it is
    not persisted to disk (only the mapping dict is saved).
    """

    def __init__(self, dm: DataManager, file_name: str = "term_mapping") -> None:
        self._dm        = dm
        self._file_name = file_name
        self._data: dict[str, str]   = dm.load_latest_json(file_name) or {}
        self._metadata: dict[str, dict] = {}

    # ── Read access ───────────────────────────────────────────────────────────

    @property
    def data(self) -> dict[str, str]:
        """The raw mapping dict: original_term → canonical_term."""
        return self._data

    @property
    def metadata(self) -> dict[str, dict]:
        """Per-term metadata (confidence, method). In-memory only."""
        return self._metadata

    @property
    def standards(self) -> list[str]:
        """Unique sorted canonical (target) terms."""
        return sorted(set(self._data.values()))

    @property
    def originals(self) -> list[str]:
        """Sorted list of all raw terms in the mapping."""
        return sorted(self._data.keys())

    def get(self, term: str) -> str:
        """Return canonical form; returns *term* unchanged if not mapped."""
        return self._data.get(term, term)

    def __contains__(self, term: str) -> bool:
        return term in self._data

    def __len__(self) -> int:
        return len(self._data)

    # ── Write access ─────────────────────────────────────────────────────────

    def add(
        self,
        term: str,
        standard: str,
        confidence: float = 1.0,
        method: str = "manual",
    ) -> None:
        """Add or update one entry and save."""
        self._data[term]     = standard
        self._metadata[term] = {"standard": standard, "confidence": confidence,
                                "method": method}
        self.save()

    def add_batch(
        self,
        entries: dict[str, str],
        metadata_batch: dict[str, dict] | None = None,
    ) -> None:
        """Add multiple entries at once; saves once at the end."""
        self._data.update(entries)
        if metadata_batch:
            self._metadata.update(metadata_batch)
        self.save()

    def remove(self, *terms: str) -> int:
        """Remove *terms* from mapping and metadata; saves if anything changed."""
        before = len(self._data)
        for t in terms:
            self._data.pop(t, None)
            self._metadata.pop(t, None)
        removed = before - len(self._data)
        if removed:
            self.save()
        return removed

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """Write current mapping to disk via DataManager."""
        if self._data:
            self._dm.save_as_json(self._data, self._file_name)
