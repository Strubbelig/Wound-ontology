"""The context matrix is a view of the ConceptStore, not a second store.

It exists because FCA needs a frame, not a dict. Every value in it is re-derived
from the store on each build, which is what makes a restricted build meaningful:
`run_fca(subtree_root=...)` must analyse that subtree and nothing else.

The old setter concatenated each build onto the previous one and saved the union,
so the restriction narrowed only the printed line while the lattice received
everything ever built, conceptual scaling's closed-world zeros covered only the
new rows, and objects the store no longer contained stayed for good. These tests
pin the replacement contract, and the corollary: anything that must outlive a
build belongs in the store.
"""
import asyncio

import pytest

from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.store.concept_store import ConceptStore


class _DM:
    """Filesystem-free DataManager stand-in."""
    def __init__(self):
        self.csv = None
        self.json = None
        self.n = 0

    def load_latest_csv(self, _): return self.csv
    def save_as_csv(self, df, _): self.csv = df
    def load_latest_json(self, _): return self.json
    def save_as_json(self, d, _): self.json = d

    def get_meta_stamp(self, kind):
        self.n += 1
        return f"meta_{kind}", f"{kind}_{self.n}"


STORE_DATA = {
    "1": {"entities": {
        "Chronic Wound": {"is_a: Wound": 1.0, "has_quality: Slow Healing": 1.0},
        "Wound Bed":     {"part_of: Wound": 1.0},
    }},
    "2": {"entities": {
        "Acute Wound":   {"is_a: Wound": 1.0, "has_quality: Acute": 1.0},
    }},
}


@pytest.fixture
def store():
    dm = _DM()
    dm.json = {k: {"entities": {e: dict(a) for e, a in v["entities"].items()}}
               for k, v in STORE_DATA.items()}
    return ConceptStore(dm, "concept_store")


@pytest.fixture
def matrix():
    return ContextMatrix(_DM(), "context_matrix")


# ── replacement ─────────────────────────────────────────────────────────────

def test_a_narrower_build_replaces_the_wider_one(matrix, store):
    matrix.get_data(store)
    assert len(matrix.df.index) == 3

    matrix.get_data(store, entities={"Chronic Wound"})
    assert list(matrix.df.index) == ["Chronic Wound"], \
        "the wider build was unioned in, so the slice is not a slice"


def test_columns_from_the_wider_build_do_not_linger(matrix, store):
    matrix.get_data(store)
    matrix.get_data(store, predicates=["has_quality"])
    assert all("has_quality" in c for c in matrix.attributes)
    assert not any("part_of" in c for c in matrix.attributes)


def test_replacement_reports_what_left_the_view(matrix, store, capsys):
    """Replacing is the contract, but it is still a change worth stating."""
    matrix.get_data(store)
    capsys.readouterr()
    matrix.get_data(store, entities={"Chronic Wound"})
    out = capsys.readouterr().out
    assert "view replaced" in out
    assert "Nothing is lost" in out


def test_an_empty_slice_clears_the_previous_view(matrix, store, capsys):
    """A stale view would make the next run_fca analyse an older restriction
    while reporting the current one."""
    matrix.get_data(store)
    matrix.get_data(store, entities=set())
    assert matrix.df.empty
    assert "cleared" in capsys.readouterr().out


def test_an_object_the_store_no_longer_holds_leaves_the_view(matrix, store):
    matrix.get_data(store)
    assert "Wound Bed" in matrix.df.index

    del store.dict["1"]["entities"]["Wound Bed"]
    matrix.get_data(store)
    assert "Wound Bed" not in matrix.df.index, \
        "the matrix kept an object the store had dropped"


# ── rebuild ─────────────────────────────────────────────────────────────────

def test_rebuild_re_derives_the_same_slice(matrix, store):
    matrix.get_data(store, entities={"Chronic Wound"})
    before = matrix.df.shape
    matrix.rebuild()
    assert matrix.df.shape == before
    assert list(matrix.df.index) == ["Chronic Wound"]


def test_rebuild_without_a_build_refuses(matrix):
    with pytest.raises(ValueError, match="has not been built from a store"):
        matrix.rebuild()


# ── verdicts are store data ─────────────────────────────────────────────────

class _LLM:
    """Confirms the first missing attribute of each entity, denies the rest."""
    def __init__(self):
        self.asked = []

    async def fill_nan_batch(self, chunk):
        self.asked.append(chunk)
        out = {}
        for entity, missing in chunk.items():
            out[entity] = {"confirmed": missing[:1], "denied": missing[1:]}
        return out


def test_fill_nan_without_a_store_refuses(matrix):
    """A verdict written only into the view is destroyed by the next build."""
    with pytest.raises(ValueError, match="needs the ConceptStore"):
        asyncio.run(matrix.fill_nan(_LLM()))


def test_fill_nan_writes_verdicts_into_the_store(matrix, store):
    matrix.get_data(store)
    assert matrix.undecided_count > 0, "fixture must have undecided cells"

    asyncio.run(matrix.fill_nan(_LLM()))

    assert "llm_fill_nan" in store.dict
    written = store.dict["llm_fill_nan"]["entities"]
    assert written, "verdicts reached neither the store nor anywhere else"


def test_a_verdict_survives_a_rebuild(matrix, store):
    """The whole point: the old code kept verdicts only in the frame, so the
    next get_data silently discarded paid LLM work."""
    matrix.get_data(store)
    asyncio.run(matrix.fill_nan(_LLM()))
    filled = matrix.undecided_count

    matrix.get_data(store)
    assert matrix.undecided_count == filled, \
        "rebuilding the view lost the verdicts"


def test_a_verdict_reaches_a_differently_sliced_view(matrix, store):
    """Store data is not tied to the slice that produced it."""
    matrix.get_data(store)
    asyncio.run(matrix.fill_nan(_LLM()))

    narrow = ContextMatrix(_DM(), "context_matrix")
    narrow.get_data(store, entities={"Chronic Wound"})
    row = narrow.df.loc["Chronic Wound"]
    assert row.notna().any()


def test_write_back_uses_the_stores_spelling(matrix, store):
    """merge() lowercases columns; writing that form back would put a second
    spelling of one attribute into the store, and max() would later swallow a
    denial without a word."""
    matrix.get_data(store)
    asyncio.run(matrix.fill_nan(_LLM()))

    written = store.dict["llm_fill_nan"]["entities"]
    all_attrs = {a for attrs in written.values() for a in attrs}
    assert "has_quality: Slow Healing" in all_attrs
    assert "has_quality: slow healing" not in all_attrs


# ── merging verdicts ────────────────────────────────────────────────────────

def test_verdicts_merge_instead_of_overwriting(store):
    store.merge_entity_records({"Chronic Wound": {"is_a: Ulcer": 1.0}}, kind="llm_fill")
    store.merge_entity_records({"Acute Wound": {"is_a: Injury": 1.0}}, kind="llm_fill")

    entities = store.dict["llm_fill"]["entities"]
    assert "Chronic Wound" in entities and "Acute Wound" in entities, \
        "the second fill replaced the first one's verdicts"


def test_a_changed_verdict_is_reported(store, capsys):
    store.merge_entity_records({"Chronic Wound": {"is_a: Ulcer": 1.0}}, kind="llm_fill")
    capsys.readouterr()
    store.merge_entity_records({"Chronic Wound": {"is_a: Ulcer": 0.0}}, kind="llm_fill")

    assert "overwrote an earlier" in capsys.readouterr().out
    assert store.dict["llm_fill"]["entities"]["Chronic Wound"]["is_a: Ulcer"] == 0.0


# ── objects the corpus never mentions ───────────────────────────────────────

class _Hier:
    """Minimal hierarchy stand-in: knows concepts, ancestors, and sources."""
    def __init__(self, parents, curated=()):
        self._parents = parents
        self._curated = set(curated)

    @property
    def concepts(self):
        return sorted(set(self._parents) | {p for p in self._parents.values() if p})

    def concepts_from(self, sources):
        return sorted(self._curated) if "curated" in set(sources) else []

    def ancestors_of(self, name):
        out, cur = [], self._parents.get(name)
        while cur:
            out.append(cur)
            cur = self._parents.get(cur)
        return out


def test_a_curated_concept_the_corpus_never_mentions_still_gets_a_row(matrix, store):
    """Curated edges are no longer pushed through the store, so a concept only
    WONT knows about has no store record. Dropping it would shrink a subtree to
    the handful of terms the abstracts happen to discuss, and look like thin
    source data rather than a missing source."""
    hier = _Hier({"Chronic Wound": "Wound", "Venous Ulcer": "Wound"},
                 curated=["Venous Ulcer", "Wound"])
    matrix.get_data(store, scale_hierarchy=hier)

    assert "Venous Ulcer" in matrix.df.index, \
        "a curated concept dropped out of its own subtree"
    assert "Chronic Wound" in matrix.df.index


def test_those_rows_are_still_restricted_by_the_slice(matrix, store):
    hier = _Hier({"Chronic Wound": "Wound", "Venous Ulcer": "Wound"},
                 curated=["Venous Ulcer", "Wound"])
    matrix.get_data(store, entities={"Chronic Wound"}, scale_hierarchy=hier)
    assert list(matrix.df.index) == ["Chronic Wound"]


def test_a_concept_known_only_from_fca_is_not_made_an_object(matrix, store):
    """Otherwise the analysis is fed its own previous output: an accepted FCA
    superclass would become a context object, and the next lattice would find
    structure it had itself proposed."""
    hier = _Hier({"Chronic Wound": "Wound", "Injury": None}, curated=[])
    matrix.get_data(store, scale_hierarchy=hier)
    assert "Injury" not in matrix.df.index
