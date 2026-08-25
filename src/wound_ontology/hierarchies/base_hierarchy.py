from __future__ import annotations
from abc import ABC, abstractmethod
import pandas as pd
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.utils.string_utils import smart_title


# ── Edge provenance (C4) ───────────────────────────────────────────────────
#
# Subsumption reaches this hierarchy from three places, and until now they
# landed in the same 0/1 matrix with no record of which produced an edge:
#
#   curated  a human-authored CSV (data/raw/predefined_concept_hierarchy.csv)
#   text     asserted in a document, via schema-constrained extraction
#   fca      suggested by the concept lattice
#
# They are not equally trustworthy, so they are ranked. A higher-ranked source
# may overwrite a lower one; a lower-ranked source may never overwrite or
# downgrade a higher one. FCA in particular is a *suggestion*: it is derived
# from co-occurrence, not from anyone asserting the subsumption.

SOURCE_CURATED = "curated"
SOURCE_TEXT = "text"
SOURCE_FCA = "fca"

SOURCE_RANK: dict[str, int] = {
    SOURCE_CURATED: 3,
    SOURCE_TEXT: 2,
    SOURCE_FCA: 1,
}

# OWL annotation property used when exporting provenance onto the axiom.
# oboInOwl:source is the OBO convention for "where this axiom came from".
# (IAO_0000119 is *definition* source and would be a misuse here.)
PROVENANCE_ANNOTATION = "http://www.geneontology.org/formats/oboInOwl#source"


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
        # (child, parent) -> source. Persisted next to the matrix.
        self._prov: dict[tuple[str, str], str] = {}
        #: False until provenance is actually loaded. Consulted by
        #: provenance_summary() so "no conflicts" can never be confused
        #: with "precedence was never in force".
        self._prov_loaded: bool = False
        # Edges proposed but not committed, e.g. FCA suggestions awaiting review.
        self._candidates: dict[tuple[str, str], str] = {}
        self._load_provenance()

    # ── Provenance ─────────────────────────────────────────────────────────────

    @property
    def _prov_file(self) -> str:
        return f"{self.file_name}_provenance"

    def _load_provenance(self) -> None:
        """Load edge provenance, or say clearly that it is not in force.

        This used to swallow every exception into ``raw = None`` and return on a
        column mismatch without a word. The consequence was not "no provenance
        metadata" -- it was that ``source_of`` returned None for every edge, so
        the rank check in ``_set_edge`` never fired and FCA-suggested edges could
        overwrite curated ones. The whole curated > text > fca guarantee switched
        itself off and every run still looked normal.

        A missing file is fine and expected on a first run. A file that exists
        and cannot be read is not, and raises.
        """
        try:
            raw = self.dm.load_latest_csv(self._prov_file)
        except FileNotFoundError:
            raw = None
        except Exception as exc:
            raise RuntimeError(
                f"[{type(self).__name__}] provenance file for {self._prov_file!r} "
                f"exists but could not be read: {exc}. Refusing to continue with "
                "provenance silently disabled — the curated > text > fca precedence "
                "would not be enforced."
            ) from exc

        if raw is None or raw.empty:
            self._prov_loaded = False
            print(f"[{type(self).__name__}] no provenance for {self._prov_file!r}; "
                  "edge precedence is NOT in force until edges are stamped.")
            return

        cols = {c.lower(): c for c in raw.columns}
        need = ("child", "parent", "source")
        missing = [k for k in need if k not in cols]
        if missing:
            raise ValueError(
                f"[{type(self).__name__}] provenance CSV for {self._prov_file!r} is "
                f"missing column(s) {missing}; found {sorted(cols)}. Refusing to "
                "continue with provenance silently disabled."
            )

        unknown = 0
        for _, r in raw.iterrows():
            source = str(r[cols["source"]])
            if source not in SOURCE_RANK:
                unknown += 1
            self._prov[(str(r[cols["child"]]), str(r[cols["parent"]]))] = source
        self._prov_loaded = True
        if unknown:
            print(f"[{type(self).__name__}] WARNING: {unknown} provenance row(s) name a "
                  f"source outside {sorted(SOURCE_RANK)}; those edges cannot be ranked.")
        print(f"[{type(self).__name__}] provenance loaded: {len(self._prov)} edge(s).")

    def save_provenance(self) -> None:
        if not self._prov:
            return
        out = pd.DataFrame(
            [{"child": c, "parent": p, "source": s} for (c, p), s in sorted(self._prov.items())]
        )
        self.dm.save_as_csv(out, self._prov_file)

    def source_of(self, specific: str, general: str) -> str | None:
        """Which source produced this edge, if any."""
        return self._prov.get((smart_title(specific), smart_title(general)))

    def edges_by_source(self, source: str) -> list[tuple[str, str]]:
        return sorted(k for k, v in self._prov.items() if v == source)

    def provenance_summary(self) -> dict[str, int]:
        """Edge counts per source.

        An empty dict is ambiguous on its own -- it means either "no edges are
        stamped" or "provenance never loaded, so precedence is not enforced".
        The ``_unstamped`` key makes the second case visible rather than letting
        a caller read silence as health.
        """
        counts: dict[str, int] = {}
        for v in self._prov.values():
            counts[v] = counts.get(v, 0) + 1
        stamped = sum(counts.values())
        total = int((self.df == 1.0).to_numpy().sum()) if not self.df.empty else 0
        if total > stamped:
            counts["_unstamped"] = total - stamped
        return counts

    @property
    def candidates(self) -> dict[tuple[str, str], str]:
        """Proposed but uncommitted edges, keyed (child, parent) -> source."""
        return dict(self._candidates)

    def propose_edge(self, specific: str, general: str, source: str) -> None:
        """Record an edge as a review candidate WITHOUT writing it into the matrix."""
        specific = smart_title(specific)
        general = smart_title(general)
        if specific == general:
            return
        if (specific, general) in self._prov:
            return                      # already committed by some source
        self._candidates[(specific, general)] = source

    def promote_candidates(self, only: set[tuple[str, str]] | None = None) -> int:
        """Commit reviewed candidates into the matrix. Returns how many landed."""
        n = 0
        for (child, parent), source in list(self._candidates.items()):
            if only is not None and (child, parent) not in only:
                continue
            self._set_edge(child, parent, source=source)
            # _set_edge clears the candidate itself; pop defensively so a
            # rejected write (outranked by an existing edge) still de-queues.
            self._candidates.pop((child, parent), None)
            n += 1
        return n

    def provenance_axioms(self) -> list[tuple[str, str, str, str]]:
        """(child, 'rdfs:subClassOf', parent, source) for every committed edge.

        Intended for the OWL writer: each subsumption axiom can carry its source
        as an axiom annotation, so a downstream consumer can tell a curated edge
        from one a lattice suggested.
        """
        return [(c, "rdfs:subClassOf", p, s) for (c, p), s in sorted(self._prov.items())]

    def save(self) -> None:
        if not self._df.empty:
            out = self._df.copy().reset_index().rename(columns={"index": "concept"})
            self.dm.save_as_csv(out, self.file_name)
        self.save_provenance()

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    @df.setter
    def df(self, new_df: pd.DataFrame) -> None:
        """Assign a hierarchy DataFrame, enforcing Title Case on all labels."""
        new_df = new_df.copy()
        new_df.index   = new_df.index.astype(str).map(smart_title)
        new_df.columns = new_df.columns.astype(str).map(smart_title)
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
        """Populate the hierarchy from a ConceptStore (already normalized).
        Always rebuilds from scratch so stale persisted data does not bleed in."""
        edges: list[tuple[str, str]] = []

        for pmid_data in store.dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                for triple, value in attrs.items():
                    if value != 1.0 or ":" not in triple:
                        continue
                    pred, target = triple.split(":", 1)
                    pred = pred.strip().lower().replace(" ", "_")
                    target = target.strip()
                    if pred in self._direct_predicates:
                        edges.append((
                            smart_title(entity),
                            smart_title(target),
                        ))
                    elif pred in self._inverse_predicates:
                        edges.append((
                            smart_title(target),
                            smart_title(entity),
                        ))

        if not edges:
            self._df = pd.DataFrame(dtype=float)
            print(f"[{self.__class__.__name__}] 0 edges added from store.")
            return

        # Build the full index/column sets first, then allocate once
        rows = sorted({s for s, _ in edges})
        cols = sorted({g for _, g in edges})
        df = pd.DataFrame(0.0, index=rows, columns=cols)
        for specific, general in edges:
            if specific != general:
                df.at[specific, general] = 1.0

        self._df = df
        # get_data rebuilds from scratch, so provenance is rebuilt with it.
        # Everything reaching the store from documents is text-asserted; curated
        # edges are re-stamped afterwards by apply_curated(), which outranks this.
        kept_curated = {k: v for k, v in self._prov.items() if v == SOURCE_CURATED}
        self._prov = {}
        for specific, general in edges:
            if specific != general:
                self._prov[(specific, general)] = SOURCE_TEXT
        self._prov.update(kept_curated)
        print(f"[{self.__class__.__name__}] {len(edges)} edges added from store.")

    def apply_curated(self, predefined_df) -> int:
        """Overlay human-authored edges, outranking anything already present.

        `predefined_df` needs 'Class' and 'Parent class' columns. These edges are
        also fed through the ConceptStore so the FCA matrix sees them, which means
        get_data() has already ingested them as text-asserted; this pass corrects
        the attribution and makes them immune to being overwritten.
        """
        if predefined_df is None or predefined_df.empty:
            return 0
        cols = {c.lower().strip(): c for c in predefined_df.columns}
        child_col = cols.get("class")
        parent_col = cols.get("parent class")
        if child_col is None or parent_col is None:
            print(f"[{self.__class__.__name__}] curated overlay skipped: "
                  f"need 'Class' and 'Parent class' columns.")
            return 0
        n = 0
        for _, row in predefined_df.iterrows():
            child, parent = row[child_col], row[parent_col]
            if pd.isna(child) or pd.isna(parent):
                continue
            if self._set_edge(str(child), str(parent), source=SOURCE_CURATED):
                n += 1
        print(f"[{self.__class__.__name__}] {n} edges attributed to '{SOURCE_CURATED}'.")
        return n

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

    def _set_edge(self, specific: str, general: str,
                  source: str = SOURCE_TEXT) -> bool:
        """Set df[specific][general] = 1.0, expanding index/columns as needed.

        Returns True if the edge was written or its provenance upgraded.
        A lower-ranked source never overwrites a higher-ranked one, so an FCA
        suggestion cannot quietly replace a curated assertion.
        """
        specific = smart_title(specific)
        general  = smart_title(general)
        existing = self._prov.get((specific, general))
        if existing is not None and \
                SOURCE_RANK.get(source, 0) < SOURCE_RANK.get(existing, 0):
            return False
        # Always register both concepts so the entity exists even without a valid parent
        if general not in self._df.columns:
            new_col = pd.DataFrame(
                {general: 0.0}, index=self._df.index if not self._df.empty else pd.Index([])
            )
            self._df = pd.concat([self._df, new_col], axis=1)
        if specific not in self._df.index:
            new_row = pd.DataFrame(
                [[0.0] * len(self._df.columns)],
                index=[specific],
                columns=self._df.columns,
            )
            self._df = pd.concat([self._df, new_row])
        if specific == general:
            return False  # self-loop: entity registered but no edge written
        self._df.at[specific, general] = 1.0
        if existing is None or SOURCE_RANK.get(source, 0) > SOURCE_RANK.get(existing, 0):
            self._prov[(specific, general)] = source
        self._candidates.pop((specific, general), None)
        return True
