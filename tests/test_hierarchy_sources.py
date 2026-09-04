"""get_data reads its sources; nothing is injected into any of them.

An edge's provenance is decided by which source it came from, at read time.
Two things used to violate that:

  * Curated edges were pushed through the ConceptStore first, so the store
    asserted 459 edges it had never extracted and a second pass had to correct
    the attribution afterwards.
  * A promoted FCA edge lived only in the hierarchy CSV, so the next rebuild
    discarded it along with the review that produced it. Writing it into the
    store instead only moved the problem: the store would then assert something
    no document said, and a lookup table was needed to un-launder the rank.

Now the class hierarchy reads three sources — the store (`text`), the curated
ontologies (`curated`), and accepted slices of FCA lattices (`fca`) — and rank
decides collisions.
"""
import inspect
import warnings

import pandas as pd
import pytest

from wound_ontology.hierarchies.base_hierarchy import (
    SOURCE_CURATED, SOURCE_FCA, SOURCE_TEXT,
)
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.store.concept_store import ConceptStore


class _DM:
    def __init__(self):
        self.json = None

    def load_latest_json(self, _): return self.json
    def save_as_json(self, d, _): self.json = d
    def load_latest_csv(self, _): return None
    def save_as_csv(self, *a): pass


class _Lattice:
    """Stands in for ConceptLattice; records the accepted slice."""
    def __init__(self):
        self.accepted = set()

    def accept(self, pairs):
        self.accepted |= {tuple(p) for p in pairs}
        return len(self.accepted)


@pytest.fixture
def store():
    dm = _DM()
    dm.json = {"1": {"entities": {"Chronic Wound": {"is_a: Wound": 1.0}}}}
    return ConceptStore(dm, "concept_store")


def _hier():
    h = ClassHierarchy.__new__(ClassHierarchy)
    h._df = pd.DataFrame(dtype=float)
    h._prov, h._candidates = {}, {}
    h._prov_loaded = True
    return h


CURATED = pd.DataFrame([{"Class": "Chronic Wound", "Parent class": "Ulcer"}])


# ── sources ─────────────────────────────────────────────────────────────────

def test_store_edges_are_text(store):
    h = _hier()
    h.get_data(store)
    assert h._prov[("Chronic Wound", "Wound")] == SOURCE_TEXT


def test_curated_is_read_as_its_own_source(store):
    h = _hier()
    h.get_data(store, curated=CURATED)
    assert h._prov[("Chronic Wound", "Ulcer")] == SOURCE_CURATED


def test_an_accepted_slice_is_read_as_fca(store):
    h = _hier()
    h.get_data(store, fca=[[("Chronic Wound", "Injury")]])
    assert "Injury" in h.parents_of("Chronic Wound")
    assert h._prov[("Chronic Wound", "Injury")] == SOURCE_FCA


def test_rank_decides_when_two_sources_claim_one_edge(store):
    """An edge a paper asserts is text-asserted even if a lattice also found it;
    one a human curated is curated even if a paper also says it."""
    h = _hier()
    h.get_data(store, curated=CURATED, fca=[[("Chronic Wound", "Wound"),
                                             ("Chronic Wound", "Ulcer")]])
    assert h._prov[("Chronic Wound", "Wound")] == SOURCE_TEXT
    assert h._prov[("Chronic Wound", "Ulcer")] == SOURCE_CURATED


def test_a_malformed_curated_source_raises(store):
    """Building silently without the curated tier would leave FCA free to
    contradict hand-authored parents."""
    with pytest.raises(ValueError, match="Parent class"):
        _hier().get_data(store, curated=pd.DataFrame([{"child": "a", "parent": "b"}]))


def test_an_edge_no_source_still_asserts_is_gone(store):
    h = _hier()
    h.get_data(store, fca=[[("Chronic Wound", "Injury")]])
    assert ("Chronic Wound", "Injury") in h._prov

    h.get_data(store)          # same store, review withdrawn
    assert ("Chronic Wound", "Injury") not in h._prov
    assert "Injury" not in h.parents_of("Chronic Wound")


# ── promotion records a slice, not a store record ───────────────────────────

def test_promoting_without_a_lattice_warns():
    h = _hier()
    h.propose_edge("Chronic Wound", "Ulcer", SOURCE_FCA)
    with pytest.warns(RuntimeWarning, match="not recorded on a lattice"):
        assert h.promote_candidates() == 1


def test_promoting_records_the_edge_on_the_lattice():
    h = _hier()
    lat = _Lattice()
    h.propose_edge("Chronic Wound", "Ulcer", SOURCE_FCA)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        h.promote_candidates(lattice=lat)
    assert ("Chronic Wound", "Ulcer") in lat.accepted


def test_the_accepted_slice_survives_a_rebuild(store):
    h = _hier()
    lat = _Lattice()
    h.propose_edge("Chronic Wound", "Ulcer", SOURCE_FCA)
    h.promote_candidates(lattice=lat)

    rebuilt = _hier()
    rebuilt.get_data(store, fca=[sorted(lat.accepted)])
    assert "Ulcer" in rebuilt.parents_of("Chronic Wound")
    assert rebuilt._prov[("Chronic Wound", "Ulcer")] == SOURCE_FCA


def test_nothing_is_written_into_the_store():
    """The store holds what documents asserted. Neither a curated edge nor a
    reviewed FCA edge is that."""
    import wound_ontology.orchestrator as orch

    src = inspect.getsource(orch.Orchestrator.run_build_hierarchies)
    assert "store.get_data(" not in src
    promote = inspect.getsource(ClassHierarchy.promote_candidates)
    assert "merge_entity_records" not in promote
