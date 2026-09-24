"""Persistence layer for the term → canonical mapping.

Holds one RECORD per term and saves them through DataManager. This class has no
business logic; DataManager is its only I/O dependency.

An entry used to be `term -> canonical` and nothing else, and everything known
*about* it lived somewhere else: the model's verdict in
`mapping_adjudication_*.json`, the second opinion in
`mapping_second_opinion_*.json`, the flags and the curator's marks in a review
CSV. Four artifacts for one fact, and one of them load-bearing in a way nobody
had noticed: **a curator's refusal was a deletion**. `withdraw()` removed the
entry and recorded nothing, so the next `build_from_embeddings` re-proposed the
merge, the adjudication cache answered `same_class` for it again, and the
refusal was gone. The guard's refusals survived a rebuild; the curator's did
not. That is the failure rule 33 states for the store -- a decision is a verdict
in the record, never a deletion -- applied to the mapping at last.

A record is::

    {"to":        "Wound",                     # None once refused
     "method":    "sapbert_cluster",
     "confidence": 0.97,
     "pass1":     {"verdict": "same_class", "reason": "..."},
     "pass2":     {"verdict": "different",  "reason": "..."},
     "curator":   {"verdict": "refused", "reason": "...", "when": "..."},
     "refused":   {"material entity": {"reason": "...", "by": "curator",
                                       "when": "..."}}}

`refused` is per CANONICAL, not per term: refusing `materials -> material
entity` must not stop `materials` ever mapping onto something else.

`data` projects the records back to the `dict[str, str]` every consumer still
expects -- `ConceptStore.normalize`, `DataFrame.rename`, every caller of
`TermMapper.mapping` -- so the format change stops at this class.
"""

from __future__ import annotations

import datetime as _dt

from wound_ontology.data_manager.data_manager import DataManager


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class TermMapping:
    """Persistence data class for term → canonical mapping.

    Layer 2 in the mapper stack:
      DataManager (repo) → TermMapping (persistence) → TermMapper (action) → MappingCleaner (curator)
    """

    def __init__(self, dm: DataManager, file_name: str = "term_mapping") -> None:
        self._dm        = dm
        self._file_name = file_name
        self._records: dict[str, dict] = self._load(dm.load_latest_json(file_name) or {})
        self._flat: dict[str, str] | None = None

    # ── Loading and migration ────────────────────────────────────────────────

    @staticmethod
    def _load(raw: dict) -> dict[str, dict]:
        """Read either format. A flat `term -> canonical` file is migrated in
        memory and written as records the next time anything saves, so no
        separate migration step exists to be forgotten."""
        records: dict[str, dict] = {}
        for term, value in raw.items():
            if isinstance(value, dict):
                rec = dict(value)
                rec.setdefault("to", None)
                rec.setdefault("refused", {})
                records[term] = rec
            else:
                records[term] = {"to": value, "refused": {}}
        return records

    # ── Read access ───────────────────────────────────────────────────────────

    @property
    def data(self) -> dict[str, str]:
        """The mapping every consumer expects: original_term → canonical_term.

        A projection of the records, cached until something writes. Records
        without a live `to` -- refused ones -- are absent, exactly as a deleted
        entry used to be, so nothing downstream can act on a refusal by accident.
        """
        if self._flat is None:
            self._flat = {t: r["to"] for t, r in self._records.items() if r.get("to")}
        return self._flat

    @property
    def records(self) -> dict[str, dict]:
        """The full records, including refused terms. Read-only by convention."""
        return self._records

    def record(self, term: str) -> dict:
        """The record for `term`, created empty if there is none."""
        rec = self._records.setdefault(term, {"to": None, "refused": {}})
        rec.setdefault("refused", {})
        return rec

    def is_refused(self, term: str, canonical: str) -> dict | None:
        """The refusal standing against this exact pair, if there is one."""
        return self._records.get(term, {}).get("refused", {}).get(canonical)

    @property
    def metadata(self) -> dict[str, dict]:
        """Per-term metadata, as the old in-memory dict presented it."""
        return {t: {"standard": r.get("to"),
                    "confidence": r.get("confidence", 1.0),
                    "method": r.get("method", "manual")}
                for t, r in self._records.items() if r.get("to")}

    @property
    def standards(self) -> list[str]:
        """Unique sorted canonical (target) terms."""
        return sorted(set(self.data.values()))

    @property
    def originals(self) -> list[str]:
        """Sorted list of all raw terms in the mapping."""
        return sorted(self.data.keys())

    def get(self, term: str) -> str:
        """Return canonical form; returns *term* unchanged if not mapped."""
        return self.data.get(term, term)

    def __contains__(self, term: str) -> bool:
        return term in self.data

    def __len__(self) -> int:
        return len(self.data)

    # ── Write access ─────────────────────────────────────────────────────────

    def add(
        self,
        term: str,
        standard: str,
        confidence: float = 1.0,
        method: str = "manual",
    ) -> None:
        """Add or update one entry and save."""
        rec = self.record(term)
        rec.update({"to": standard, "confidence": confidence, "method": method})
        self._dirty()
        self.save()

    def add_batch(
        self,
        entries: dict[str, str],
        metadata_batch: dict[str, dict] | None = None,
    ) -> None:
        """Add multiple entries at once; saves once at the end."""
        meta = metadata_batch or {}
        for term, standard in entries.items():
            rec = self.record(term)
            rec["to"] = standard
            m = meta.get(term)
            if m:
                rec["confidence"] = m.get("confidence", rec.get("confidence", 1.0))
                rec["method"] = m.get("method", rec.get("method", "manual"))
        self._dirty()
        self.save()

    def annotate(self, term: str, **fields) -> None:
        """Attach evidence to a term's record without touching what it maps to.

        This is where a model verdict or a curator's note lands, so the entry
        carries its own provenance instead of pointing at a side file that the
        next rebuild will not consult.
        """
        self.record(term).update(fields)
        self.save()

    def refuse(self, term: str, canonical: str, reason: str = "", by: str = "curator") -> None:
        """Record that `term` must NOT map onto `canonical`, and unmap it.

        The pair is remembered, not the term: `materials` refused onto
        `material entity` is still free to map onto something else. A build that
        re-proposes the refused pair has to skip it -- that is the whole point,
        and `TermMapper.build_from_embeddings` enforces it.
        """
        rec = self.record(term)
        rec["refused"][canonical] = {"reason": reason, "by": by, "when": _now()}
        rec["curator"] = {"verdict": "refused", "reason": reason, "when": _now()}
        if rec.get("to") == canonical:
            rec["to"] = None
        self._dirty()
        self.save()

    def remove(self, *terms: str) -> int:
        """Remove *terms* from the file entirely; saves if anything changed.

        For entries that can no longer do anything -- identities, dead targets,
        inert spellings. A DECISION about a pair is `refuse`, which keeps the
        record; removing one forgets it, which is what this class exists to stop.
        """
        before = len(self._records)
        for t in terms:
            self._records.pop(t, None)
        removed = before - len(self._records)
        if removed:
            self._dirty()
            self.save()
        return removed

    # ── Persistence ───────────────────────────────────────────────────────────

    def _dirty(self) -> None:
        self._flat = None

    def save(self) -> None:
        """Write current records to disk via DataManager."""
        if self._records:
            self._dm.save_as_json(self._records, self._file_name)
