from __future__ import annotations
from abc import ABC, abstractmethod
import pandas as pd
from wound_ontology.data_manager.data_manager import DataManager


class BaseHierarchy(ABC):
    """
    Abstract base for directed concept hierarchies stored as a binary adjacency df.

    Convention:
      rows   = specific concept  (child / branch)
      cols   = general concept   (parent / root)
      value  = 1.0 if the relationship holds

    Subclasses define which ConceptStore predicates to ingest.
    """

    # ── Abstract interface (subclasses must define) ────────────────────────────

    @property
    @abstractmethod
    def file_name(self) -> str:
        """DataManager prefix for persistence."""

    @property
    @abstractmethod
    def _direct_predicates(self) -> set:
        """ConceptStore predicates stored row→col (specific→general) as-is."""

    @property
    @abstractmethod
    def _inverse_predicates(self) -> set:
        """ConceptStore predicates stored col→row (inverted)."""

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(self, data_manager: 'DataManager'):
        self.dm = data_manager
        raw = self.dm.load_latest_csv(self.file_name)
        if raw is not None:
            if "Unnamed: 0" in raw.columns:
                raw = raw.drop(columns=["Unnamed: 0"])
            raw = raw.set_index(raw.columns[0])
            self._df = raw.apply(pd.to_numeric, errors='coerce').fillna(0.0)
        else:
            self._df = pd.DataFrame(dtype=float)

    def save(self) -> None:
        if not self._df.empty:
            out = self._df.copy().reset_index().rename(columns={"index": "concept"})
            self.dm.save_as_csv(out, self.file_name)

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    @df.setter
    def df(self, new_df: pd.DataFrame) -> None:
        """Assign a hierarchy DataFrame, enforcing Title Case on all labels."""
        new_df = new_df.copy()
        new_df.index   = new_df.index.astype(str).str.strip().str.title()
        new_df.columns = new_df.columns.astype(str).str.strip().str.title()
        self._df = new_df.apply(pd.to_numeric, errors='coerce').fillna(0.0)

    @property
    def concepts(self) -> set:
        """All concept names appearing in any position."""
        return set(self._df.index) | set(self._df.columns)

    @property
    def roots(self) -> list:
        """Concepts that appear as parents but never as children (top-level nodes)."""
        all_parents  = set(self._df.columns[self._df.max() == 1.0]) if not self._df.empty else set()
        all_children = set(self._df.index[self._df.max(axis=1) == 1.0]) if not self._df.empty else set()
        return sorted(all_parents - all_children)

    # ── Public methods ─────────────────────────────────────────────────────────

    def get_data(self, store) -> None:
        """Populate the hierarchy from a ConceptStore (already normalized)."""
        added = 0
        for pmid_data in store.dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                for triple, value in attrs.items():
                    if value != 1.0 or ":" not in triple:
                        continue
                    pred, target = triple.split(":", 1)
                    pred   = pred.strip().lower().replace(" ", "_")
                    target = target.strip()
                    if pred in self._direct_predicates:
                        self._set_edge(entity, target)
                        added += 1
                    elif pred in self._inverse_predicates:
                        self._set_edge(target, entity)
                        added += 1
        print(f"[{self.__class__.__name__}] {added} edges added from store.")

    def parents_of(self, concept: str) -> list:
        """Direct general concepts of `concept` (its row)."""
        if concept not in self._df.index:
            return []
        row = self._df.loc[concept]
        return list(row[row == 1.0].index)

    def children_of(self, concept: str) -> list:
        """Direct specific concepts under `concept` (its column)."""
        if concept not in self._df.columns:
            return []
        col = self._df[concept]
        return list(col[col == 1.0].index)

    def subtree_of(self, root: str) -> set:
        """
        All concepts that are (transitively) specific to `root`.
        Returns a set of concept names including root itself.
        """
        visited, queue = set(), [root]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(self.children_of(node))
        return visited

    # ── Private methods ────────────────────────────────────────────────────────

    def _set_edge(self, specific: str, general: str) -> None:
        """Set df[specific][general] = 1.0, expanding index/columns as needed."""
        specific = specific.strip().title()
        general  = general.strip().title()
        if specific == general:
            return  # skip self-loops
        if general not in self._df.columns:
            self._df[general] = 0.0
        if specific not in self._df.index:
            new_row = pd.DataFrame(
                [[0.0] * len(self._df.columns)],
                index=[specific],
                columns=self._df.columns,
            )
            self._df = pd.concat([self._df, new_row])
        self._df.at[specific, general] = 1.0
