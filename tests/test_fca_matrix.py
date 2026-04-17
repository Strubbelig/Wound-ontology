import pytest
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.store.concept_store import ConceptStore


class MockDM:
    def load_latest_csv(self, _): return None
    def save_as_csv(self, df, _): pass
    def load_latest_json(self, _): return None


STORE_DATA = {
    "1": {"entities": {
        "Chronic Wound": {"is_a: Wound": 1.0, "has_quality: Chronic": 1.0},
        "Wound Bed":     {"part_of: Wound": 1.0, "has_quality: Granulating": 1.0},
    }},
    "2": {"entities": {
        "Acute Wound":   {"is_a: Wound": 1.0, "has_quality: Acute": 1.0},
    }},
}


@pytest.fixture
def store():
    class StoreDM:
        def load_latest_json(self, _): return STORE_DATA
        def save_as_json(self, *a): pass
    return ConceptStore(StoreDM(), "concept_store")


@pytest.fixture
def matrix():
    return ContextMatrix(MockDM(), "context_matrix")


def test_build_all_entities(matrix, store):
    matrix.get_data(store)
    assert "Chronic Wound" in matrix.df.index
    assert "Acute Wound"   in matrix.df.index
    assert "Wound Bed"     in matrix.df.index


def test_filter_by_entities(matrix, store):
    matrix.get_data(store, entities={"Chronic Wound"})
    assert "Chronic Wound" in matrix.df.index
    assert "Acute Wound"   not in matrix.df.index


def test_filter_by_predicates(matrix, store):
    matrix.get_data(store, predicates=["has_quality"])
    cols = list(matrix.df.columns)
    assert all("has_quality" in c for c in cols)
    assert not any("is_a" in c for c in cols)
