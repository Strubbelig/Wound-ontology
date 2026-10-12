from __future__ import annotations
from abc import ABC, abstractmethod
import warnings

import pandas as pd
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.utils.string_utils import smart_title
from wound_ontology.store.concept_store import records_of


# ── Edge provenance (C4) ───────────────────────────────────────────────────
#
# Subsumption reaches this hierarchy from three places, and until now they
# landed in the same 0/1 matrix with no record of which produced an edge:
#
#   curated  human-authored subsumption from WONT + MILD, read by
#            hierarchies/curated_seed.py (it used to be a CSV, until that
#            table was merged into the ontologies themselves)
#   text     asserted in a document, via schema-constrained extraction
#   fca      suggested by the concept lattice
#
# They are not equally trustworthy, so they are ranked. A higher-ranked source
# may overwrite a lower one; a lower-ranked source may never overwrite or
# downgrade a higher one. FCA in particular is a *suggestion*: it is derived
# from co-occurrence, not from anyone asserting the subsumption.

SOURCE_CURATED = "curated"
SOURCE_PLACED = "placed"
SOURCE_TEXT = "text"
SOURCE_FCA = "fca"

# `placed` (2026-10-02): an extracted term put under an existing WONT/MILD
# class by the placement step, read by Claude and kept by the curator's review
# (rule 59). Checked twice, so above what one abstract implied; not authored,
# so below the curated ontology itself.
SOURCE_RANK: dict[str, int] = {
    SOURCE_CURATED: 4,
    SOURCE_PLACED: 3,
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

    def __init__(self, data_manager: 'DataManager', file_name: str | None = None):
        self.dm = data_manager
        # Analysis artifacts are per-analysis (rule 6): an FCA hierarchy built for
        # the Wound subtree must not share a file -- and therefore a reload -- with
        # one built for a different subtree.
        if file_name is not None:
            self.file_name = file_name
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
        self._load_candidates()

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

    # ── Candidates ─────────────────────────────────────────────────────────────
    #
    # Proposed-but-uncommitted edges used to live only in this dict, and the
    # dict died with the Python session. `run_build_hierarchies(commit_fca=False)`
    # printed "Inspect class_hier.candidates, then promote_candidates(...)" --
    # an instruction that silently expired when the notebook closed, so the
    # propose/review/promote path could not actually be completed and 12 of them
    # were lost without a word. They are persisted next to the matrix now.

    @property
    def _cand_file(self) -> str:
        return f"{self.file_name}_candidates"

    def _load_candidates(self) -> None:
        """Load the review queue. Missing is fine; unreadable is not.

        Same discipline as `_load_provenance`: an empty queue and a queue that
        could not be read must never look alike.
        """
        try:
            raw = self.dm.load_latest_csv(self._cand_file)
        except FileNotFoundError:
            raw = None
        except Exception as exc:
            raise RuntimeError(
                f"[{type(self).__name__}] candidate file for {self._cand_file!r} "
                f"exists but could not be read: {exc}. Refusing to continue with "
                "an empty review queue, which would look exactly like having "
                "nothing left to review."
            ) from exc

        if raw is None or raw.empty:
            return

        cols = {c.lower(): c for c in raw.columns}
        missing = [k for k in ("child", "parent", "source") if k not in cols]
        if missing:
            raise ValueError(
                f"[{type(self).__name__}] candidate CSV for {self._cand_file!r} is "
                f"missing column(s) {missing}; found {sorted(cols)}."
            )

        committed = 0
        for _, r in raw.iterrows():
            key = (str(r[cols["child"]]), str(r[cols["parent"]]))
            if key in self._prov:
                committed += 1          # promoted since it was proposed
                continue
            self._candidates[key] = str(r[cols["source"]])
        print(f"[{type(self).__name__}] {len(self._candidates)} candidate edge(s) "
              f"awaiting review"
              + (f"; {committed} already committed since." if committed else "."))

    def save_candidates(self) -> None:
        """Write the review queue, INCLUDING when it is empty.

        `save_provenance` returns early on an empty dict, which is safe there --
        provenance only grows. A queue shrinks: promoting the last candidate
        empties it, and skipping the write would leave the previous file as the
        newest on disk, so the next session would load the promoted edges back
        as though they were still awaiting review.
        """
        out = pd.DataFrame(
            [{"child": c, "parent": p, "source": s}
             for (c, p), s in sorted(self._candidates.items())],
            columns=["child", "parent", "source"],
        )
        self.dm.save_as_csv(out, self._cand_file)

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

    def promote_candidates(self, only: set[tuple[str, str]] | None = None,
                           lattice=None) -> int:
        """Commit reviewed candidates into the matrix. Returns how many landed.

        `lattice` is where the review is *recorded*. The accepted edges form a
        slice of that lattice, and the slice is what get_data reads back as the
        `fca` source on the next build. Without it the promotion lasts only as
        long as this session: the hierarchy is rebuilt from its sources every
        run, and unlike a curated edge, an accepted FCA edge has no ontology to
        be re-read from.

        The acceptance does not go into the ConceptStore. The store holds what
        was extracted from documents; an edge a lattice suggested and a human
        waved through is neither, and writing it there would make the store
        assert something it never saw.
        """
        n = 0
        accepted: list[tuple[str, str]] = []
        for (child, parent), source in list(self._candidates.items()):
            if only is not None and (child, parent) not in only:
                continue
            if self._set_edge(child, parent, source=source):
                accepted.append((child, parent))
            # _set_edge clears the candidate itself; pop defensively so a
            # rejected write (outranked by an existing edge) still de-queues.
            self._candidates.pop((child, parent), None)
            n += 1

        if accepted:
            if lattice is not None:
                lattice.accept(accepted)
            else:
                warnings.warn(
                    f"{len(accepted)} promoted edge(s) were not recorded on a "
                    f"lattice. get_data() rebuilds this hierarchy from its "
                    f"sources, so they will be gone after the next "
                    f"run_build_hierarchies(). Pass lattice=... to keep them.",
                    RuntimeWarning, stacklevel=2,
                )
        # The queue shrank, so make that durable -- otherwise the previous
        # file stays newest on disk and the next session reloads the promoted
        # edges as pending. A hierarchy built detached (`__new__`, no
        # DataManager) has no file to keep in step, so there is nothing to
        # write and nothing lost; that is the only case this skips.
        if n and getattr(self, "dm", None) is not None:
            self.save_candidates()
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
        self.save_candidates()

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

    def get_data(self, store, curated=None, fca=(), reconcile_categories=None,
                 placed=()) -> None:
        """Populate the hierarchy by reading its sources. Rebuilds from scratch.

        This is a *reader*, not a merge point. Each source keeps its own identity
        all the way through, and an edge's provenance is decided by which source
        it came from -- not by anything written into the source beforehand.

        store   – ConceptStore (already normalized). Everything here was asserted
                  by a document, so it is stamped `text`.
        curated – DataFrame with 'Class' and 'Parent class' columns, read straight
                  from WONT and MILD. Stamped `curated`.
        fca     – iterable of accepted lattice slices, each a sequence of
                  (child, parent) pairs. Stamped `fca`.
        placed  – (term, class label) pairs the placement step put under an
                  existing WONT/MILD class and the review kept
                  (`TermMappingAndGate.placements()`). Stamped `placed`.
        reconcile_categories
                – callable(categories) -> category | None, deciding which single
                  BFO category a term typed several ways actually gets. Pass
                  `ReasonerGate.least_common_category` to retreat to the most
                  specific category MILD says subsumes them all.

                  Stage-1 typing runs per abstract, so nothing stops two
                  abstracts typing one term differently: `Necrosis` arrived as
                  `material entity` from one and `process` from two others. Both
                  became edges, BFO makes continuant and occurrent disjoint, and
                  the reasoner had to clean up afterwards -- 42 of 48 quarantined
                  edges were this, across 16 terms. Reconciling here builds a
                  hierarchy that is coherent by construction instead.

                  A term whose typings share no common ancestor gets NO category
                  edge and is recorded in `self.irreconcilable`: `Mortality` as
                  both `Process` and `Tendency` spans continuant and occurrent,
                  and there is no honest category for it. That list is a review
                  queue, not a failure -- usually one label covering several
                  things.

                  The store keeps every abstract's opinion either way. The
                  disagreement is data; what may not survive is an incoherent
                  hierarchy built from it.

        Curated edges used to be pushed *through* the store first, which made the
        store assert 459 edges it had never extracted and required a second pass
        to correct the attribution afterwards. Reading each source in its own
        right removes both. Rank still decides collisions: an edge that is both
        curated and text-asserted is curated; one that is both text and fca is
        text.
        """
        edges: list[tuple[str, str]] = []
        edge_source: dict[tuple[str, str], str] = {}

        def _note(pair, source):
            specific, general = pair
            if not specific or not general or specific == general:
                return
            edges.append(pair)
            prev = edge_source.get(pair)
            if prev is None or SOURCE_RANK[source] > SOURCE_RANK[prev]:
                edge_source[pair] = source

        # Which BFO categories each term was given, across the whole corpus.
        # Collected first so a term's category edge can be decided once, rather
        # than one edge per abstract that happened to mention it.
        from wound_ontology.llm.category_vocab import declared_category
        typings: dict[str, set[str]] = {}
        if reconcile_categories is not None:
            for _, ents in records_of(store):
                for entity, attrs in ents.items():
                    for triple, value in attrs.items():
                        if value != 1.0 or ":" not in triple:
                            continue
                        pred, target = triple.split(":", 1)
                        if pred.strip().lower().replace(" ", "_") not in self._direct_predicates:
                            continue
                        # A category read out of the store is converted to its
                        # declared spelling here, so everything downstream --
                        # reconciliation, the coarse-set subtraction, the gate --
                        # compares declared names only. A cache written under the
                        # old CamelCase spelling reads correctly through this.
                        declared = declared_category(target.strip())
                        if declared is not None:
                            typings.setdefault(smart_title(entity), set()).add(declared)

        self.irreconcilable: dict[str, set[str]] = {}
        agreed: dict[str, str] = {}
        for term, cats in typings.items():
            if len(cats) == 1:
                agreed[term] = next(iter(cats))
                continue
            winner = reconcile_categories(cats)
            if winner is None:
                self.irreconcilable[term] = cats
            else:
                agreed[term] = winner

        source = SOURCE_TEXT
        for _, ents in records_of(store):
            for entity, attrs in ents.items():
                for triple, value in attrs.items():
                    if value != 1.0 or ":" not in triple:
                        continue
                    pred, target = triple.split(":", 1)
                    pred = pred.strip().lower().replace(" ", "_")
                    target = target.strip()
                    if pred in self._direct_predicates:
                        # Category edges for a reconciled term are emitted once,
                        # below. Skipping them here rather than filtering for the
                        # agreed one matters: the agreed category is often one no
                        # abstract proposed -- process and process boundary agree
                        # on Occurrent, which neither of them said.
                        if declared_category(target) and smart_title(entity) in typings:
                            continue
                        _note((smart_title(entity), smart_title(target)), source)
                    elif pred in self._inverse_predicates:
                        _note((smart_title(target), smart_title(entity)), source)

        for term, category in agreed.items():
            _note((term, smart_title(category)), source)
        from_store = len(edges)

        if reconcile_categories is not None:
            merged = sum(len(c) - 1 for c in typings.values() if len(c) > 1)
            if merged or self.irreconcilable:
                print(f"[{self.__class__.__name__}] category reconciliation: "
                      f"{len(typings)} typed term(s); "
                      f"{merged} conflicting category edge(s) collapsed to the "
                      f"category MILD says subsumes them.")
            if self.irreconcilable:
                print(f"[{self.__class__.__name__}] *** {len(self.irreconcilable)} "
                      f"term(s) were typed in ways with NO common ancestor. They get "
                      f"no category edge — there is no honest one — and are listed "
                      f"in .irreconcilable: ***")
                for term, cats in sorted(self.irreconcilable.items())[:15]:
                    print(f"[{self.__class__.__name__}]     {term}: "
                          f"{', '.join(sorted(cats))}")

        if curated is not None and not getattr(curated, "empty", True):
            cols = {c.lower().strip(): c for c in curated.columns}
            child_col, parent_col = cols.get("class"), cols.get("parent class")
            if child_col is None or parent_col is None:
                raise ValueError(
                    f"[{self.__class__.__name__}] curated source needs 'Class' and "
                    f"'Parent class' columns, got {list(curated.columns)}. Silently "
                    f"building without the curated tier would leave FCA free to "
                    f"contradict hand-authored parents."
                )
            for _, row in curated.iterrows():
                child, parent = row[child_col], row[parent_col]
                if pd.isna(child) or pd.isna(parent):
                    continue
                _note((smart_title(str(child)), smart_title(str(parent))),
                      SOURCE_CURATED)
        from_curated = len(edges) - from_store

        for child, parent in placed or ():
            _note((smart_title(str(child)), smart_title(str(parent))), SOURCE_PLACED)
        from_placed = len(edges) - from_store - from_curated

        for accepted in fca or ():
            for child, parent in accepted:
                _note((smart_title(str(child)), smart_title(str(parent))), SOURCE_FCA)
        from_fca = len(edges) - from_store - from_curated - from_placed

        if not edges:
            self._df = pd.DataFrame(dtype=float)
            self._prov = {}
            print(f"[{self.__class__.__name__}] 0 edges from any source.")
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
        # Provenance is rebuilt with the matrix, from the sources themselves.
        # Nothing is carried over: an edge that no source still asserts is gone,
        # which is the point of rebuilding rather than merging.
        self._prov = dict(edge_source)
        counts = {src: sum(1 for v in self._prov.values() if v == src)
                  for src in (SOURCE_CURATED, SOURCE_PLACED, SOURCE_TEXT, SOURCE_FCA)}
        print(f"[{self.__class__.__name__}] {len(self._prov)} edges from "
              f"{from_store} store + {from_curated} curated + {from_placed} placed + "
              f"{from_fca} accepted-FCA "
              f"assertions — after rank: "
              + ", ".join(f"{n} {src}" for src, n in counts.items() if n))

    def concepts_from(self, sources) -> list[str]:
        """Concepts named by at least one edge from one of these sources.

        Lets a consumer ask for the concepts a *particular* source asserts, which
        is not the same question as `concepts`. The FCA view needs it: curated
        concepts must be objects in the context even when no abstract mentions
        them, while concepts known only from FCA must not be, or the analysis
        would be fed its own output.
        """
        wanted = set(sources)
        out: set[str] = set()
        for (specific, general), src in self._prov.items():
            if src in wanted:
                out.add(specific)
                out.add(general)
        return sorted(out)

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

    def ancestors_of(self, concept: str) -> set:
        """All concepts `concept` is transitively specific to, excluding itself.

        The upward mirror of :meth:`subtree_of`. Used for conceptual scaling of
        the FCA context, where an object's superclasses become attributes so the
        lattice cannot order it against the hierarchy.

        A hierarchy is not guaranteed acyclic -- FCA suggestions and text edges
        both write into it -- so the walk carries a visited set rather than
        recursing.

        `concept` is smart_title-normalized first, because the index is: only
        302 of the 4180 entity names in a real store match it verbatim, and
        looking up the other 3878 raw returned "no ancestors" rather than an
        error. In the FCA context that silently scaled 7% of objects and left
        the rest bare, which manufactured order violations instead of removing
        them.
        """
        concept = smart_title(concept)
        visited, queue = set(), list(self.parents_of(concept))
        while queue:
            node = queue.pop()
            if node in visited or node == concept:
                continue
            visited.add(node)
            queue.extend(self.parents_of(node))
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
        # A cycle is not a weak edge, it is an impossible one: `Wound is_a Skin
        # Defect is_a Wound` says both are strict generalisations of the other.
        # Only self-loops were caught before, so a two-step cycle was written and
        # persisted without complaint -- FCA produced one as soon as two distinct
        # lattice concepts were given the same name and collapsed onto one node.
        if specific in self.ancestors_of(general):
            print(f"[{self.__class__.__name__}] refused '{specific} is_a {general}': "
                  f"'{specific}' is already an ancestor of '{general}', so the edge "
                  f"would close a cycle.")
            return False
        self._df.at[specific, general] = 1.0
        if existing is None or SOURCE_RANK.get(source, 0) > SOURCE_RANK.get(existing, 0):
            self._prov[(specific, general)] = source
        self._candidates.pop((specific, general), None)
        return True
