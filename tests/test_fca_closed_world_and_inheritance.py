"""Rule 65: FCA reads an unstated property as absent, and an ancestor's
attribute passes down only when its own descendants corroborate it."""
import tempfile

import numpy as np
import pandas as pd
import pytest

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.fca.concept_lattice import ConceptLattice
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy


class MockDM:
    def load_latest_csv(self, _): return None
    def save_as_csv(self, df, _): pass
    def load_latest_pickle(self, _): return None
    def save_as_pickle(self, *a): pass
    def get_meta_stamp(self, tag): return ("meta_" + tag, "stamp")


@pytest.fixture
def matrix():
    cm = ContextMatrix(MockDM(), "t")
    cm._df = pd.DataFrame(
        [[1.0, np.nan, 0.0],
         [1.0, 0.0,    0.0],
         [0.0, np.nan, 1.0]],
        index=["Wound A", "Wound B", "Wound C"],
        columns=["has_quality: red", "has_quality: deep", "part_of: skin"],
    )
    return cm


def test_closed_world_builds_one_lattice_and_everything_is_certain(matrix):
    cl = ConceptLattice(MockDM(), matrix, "t")
    lat = cl.get_data_and_run_fca(unknown="absent")
    assert cl.candidate_intents == set()
    assert all(cl.is_certain(c) for c in lat)
    # 'deep' is stated of nobody, so no concept groups A and C on it
    assert not any(set(c.extent) == {"Wound A", "Wound C"} for c in lat)


def test_closed_world_rejects_an_unknown_policy(matrix):
    with pytest.raises(ValueError):
        ConceptLattice(MockDM(), matrix, "t").get_data_and_run_fca(unknown="maybe")


def test_open_world_stays_the_lattice_default(matrix):
    cl = ConceptLattice(MockDM(), matrix, "t")
    cl.get_data_and_run_fca()
    assert cl.candidate_intents        # the dual build still runs


# ── class-level inheritance ────────────────────────────────────────────────

class _Store:
    def __init__(self, abstracts):
        self.dict = {str(i): {"entities": e} for i, e in enumerate(abstracts)}


@pytest.fixture
def hier():
    h = ClassHierarchy.__new__(ClassHierarchy)
    h._df = pd.DataFrame(dtype=float)
    h._prov, h._candidates = {}, {}
    h._prov_loaded = True
    for child in ("Ulcer One", "Ulcer Two", "Ulcer Three", "Ulcer Four"):
        h._set_edge(child, "Chronic Wound")
    h._set_edge("Chronic Wound", "Wound")
    h._set_edge("Lonely Wound", "Quiet Wound")
    h._set_edge("Quiet Wound", "Wound")
    return h


@pytest.fixture
def store():
    parent = {"Chronic Wound": {"has_quality: slow healing": 1.0, "has_quality: itchy": 1.0},
              "Quiet Wound": {"has_quality: odd": 1.0}}
    kids = {f"Ulcer {n}": {"has_quality: slow healing": 1.0} for n in ("One", "Two", "Three")}
    kids["Ulcer Four"] = {"has_quality: deep": 1.0}
    kids["Lonely Wound"] = {}          # named, nothing stated of it
    outside = {f"Bone {i}": {"has_quality: hard": 1.0} for i in range(10)}
    return _Store([{**parent, **kids, **outside}, dict(parent)])


def _context(store, **kw):
    cm = ContextMatrix(DataManager(tempfile.mkdtemp()), "ctx")
    cm._df = None
    cm.get_data(store, **kw)
    return cm, cm.df.fillna(0.0)


def _has(df, entity, attr):
    return df.loc[entity, attr] == 1.0


def test_class_level_passes_a_corroborated_attribute_only(store, hier):
    cm, df = _context(store, scale_hierarchy=hier, inherit="class_level", min_support=2)
    assert _has(df, "Ulcer Four", "has_quality: slow healing")     # 3 of 4 siblings state it
    assert not _has(df, "Ulcer Four", "has_quality: itchy")        # no descendant does
    passed = {(t["ancestor"], t["attribute"]) for t in cm.inheritance_tests if t["class_level"]}
    assert passed == {("Chronic Wound", "has_quality: slow healing")}


def test_class_level_does_not_inherit_what_nothing_can_corroborate(store, hier):
    """Quiet Wound's only descendant has no measured attribute: untestable, not inherited."""
    cm, df = _context(store, scale_hierarchy=hier, inherit="class_level", min_support=2)
    assert "Lonely Wound" in df.index
    assert "has_quality: odd" not in df.columns or not _has(df, "Lonely Wound", "has_quality: odd")


def test_all_inherits_both(store, hier):
    _, df = _context(store, scale_hierarchy=hier, inherit="all", min_support=2)
    assert _has(df, "Ulcer Four", "has_quality: itchy")
    assert _has(df, "Lonely Wound", "has_quality: odd")


def test_old_switch_still_maps(store, hier):
    _, df = _context(store, scale_hierarchy=hier, inherit_attributes=False, min_support=2)
    assert not _has(df, "Ulcer Four", "has_quality: itchy")


def test_inherit_rejects_unknown_mode(store, hier):
    with pytest.raises(ValueError):
        _context(store, scale_hierarchy=hier, inherit="some")


def test_min_support_drops_one_abstract_remarks(store, hier):
    """The siblings' slow healing rests on one abstract each: gone at 2, kept at 1."""
    _, df2 = _context(store, min_support=2)
    _, df1 = _context(store, min_support=1)
    assert "Ulcer One" not in df2.index or not _has(df2, "Ulcer One", "has_quality: slow healing")
    assert _has(df1, "Ulcer One", "has_quality: slow healing")
    assert _has(df2, "Chronic Wound", "has_quality: slow healing")   # two abstracts
