"""The context matrix must agree with the hierarchy about entity names.

The store keys entities as extracted ('chronic wound'); hierarchies key them
smart_title'd ('Chronic Wound'). On a real store only 302 of 4180 names matched
verbatim, and every place that compared the two raw failed silently — returning
a smaller context rather than an error, which reads as thin source data.
"""
import tempfile

import pandas as pd
import pytest

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy


class _Store:
    def __init__(self, entities):
        self.dict = {"1": {"entities": entities}}


@pytest.fixture
def hier():
    h = ClassHierarchy.__new__(ClassHierarchy)
    h._df = pd.DataFrame(dtype=float)
    h._prov, h._candidates = {}, {}
    h._prov_loaded = True
    h._set_edge("Chronic Wound", "Wound")
    h._set_edge("Acute Wound", "Wound")
    return h


@pytest.fixture
def store():
    # as extracted: lower case, exactly what the LLM produced
    return _Store({
        "chronic wound": {"has_quality: slow healing": 1.0},
        "acute wound":   {"has_quality: rapid healing": 1.0},
        "unrelated":     {"has_quality: other": 1.0},
    })


def _matrix(store, **kw):
    cm = ContextMatrix(DataManager(tempfile.mkdtemp()), "ctx")
    cm._df = None
    cm.get_data(store, **kw)
    return cm.df


def test_a_subtree_restriction_keeps_its_whole_subtree(store, hier):
    """subtree_of() returns smart_title names; the store does not. Compared
    raw, a 40-entity Wound subtree yielded a ONE-object context and looked
    like a corpus-coverage problem."""
    df = _matrix(store, entities=hier.subtree_of("Wound"))
    assert set(df.index) == {"Chronic Wound", "Acute Wound"}
    assert "Unrelated" not in df.index, "the restriction must still restrict"


def test_an_empty_restriction_still_means_nothing_matches(store, hier):
    df = _matrix(store, entities=set())
    assert df.empty


def test_no_restriction_keeps_everything(store):
    df = _matrix(store)
    assert len(df.index) == 3


# ── persistence ─────────────────────────────────────────────────────────────

def test_a_reloaded_matrix_does_not_double_on_the_next_run(store, hier):
    """__init__ used to hand back a RangeIndex with 'entity' as a column, so the
    df setter concatenated misaligned frames: 4114 rows became 8228, 8227 of
    them duplicates, with 'entity' itself as an attribute column. Silent, and
    only on the SECOND run."""
    d = tempfile.mkdtemp()
    first = ContextMatrix(DataManager(d), "context_matrix")
    first._df = None
    first.get_data(store, scale_hierarchy=hier)
    rows, cols = first.df.shape

    second = ContextMatrix(DataManager(d), "context_matrix")   # reloads from disk
    assert second.df.index.name == "entity"
    assert "entity" not in second.df.columns
    second.get_data(store, scale_hierarchy=hier)
    assert second.df.shape == (rows, cols), "rebuilding duplicated every row"
    assert not second.df.index.duplicated().any()
