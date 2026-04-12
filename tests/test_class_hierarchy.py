import pytest
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy


class MockDM:
    def load_latest_csv(self, _): return None
    def save_as_csv(self, df, _): pass


@pytest.fixture
def test_hierarchy():
    return ClassHierarchy(MockDM())


def test_get_data(test_hierarchy):
    """Predefined edges piped through a ConceptStore mock."""
    store_mock = type("S", (), {"dict": {
        "predefined": {"entities": {
            "Chronic Wound": {"is_a: Wound": 1.0},
            "Acute Wound":   {"is_a: Wound": 1.0},
        }}
    }})()
    test_hierarchy.get_data(store_mock)
    assert test_hierarchy.df.at["Chronic Wound", "Wound"] == 1.0
    assert test_hierarchy.df.at["Acute Wound",   "Wound"] == 1.0


def test_subtree(test_hierarchy):
    test_hierarchy._set_edge("Venous Ulcer",  "Chronic Wound")
    test_hierarchy._set_edge("Chronic Wound", "Wound")
    subtree = test_hierarchy.subtree_of("Wound")
    assert "Venous Ulcer"  in subtree
    assert "Chronic Wound" in subtree
    assert "Wound"         in subtree


def test_roots(test_hierarchy):
    test_hierarchy._set_edge("Chronic Wound", "Wound")
    assert "Wound" in test_hierarchy.roots


def test_children_of(test_hierarchy):
    test_hierarchy._set_edge("Chronic Wound", "Wound")
    test_hierarchy._set_edge("Acute Wound",   "Wound")
    children = test_hierarchy.children_of("Wound")
    assert "Chronic Wound" in children
    assert "Acute Wound"   in children


def test_part_of_not_ingested(test_hierarchy):
    """ClassHierarchy must ignore part_of predicates from cache."""
    cache_mock = type("C", (), {"dict": {
        "1": {"entities": {"Wound Bed": {"part_of: Wound": 1.0}}}
    }})()
    test_hierarchy.get_data(cache_mock)
    assert test_hierarchy.df.empty


def test_is_a_ingested_from_cache(test_hierarchy):
    cache_mock = type("C", (), {"dict": {
        "1": {"entities": {"Chronic Wound": {"is_a: Wound": 1.0}}}
    }})()
    test_hierarchy.get_data(cache_mock)
    assert test_hierarchy.df.at["Chronic Wound", "Wound"] == 1.0


def test_false_values_not_ingested(test_hierarchy):
    """Only value==1.0 entries should create edges."""
    cache_mock = type("C", (), {"dict": {
        "1": {"entities": {"Chronic Wound": {"is_a: Wound": 0.0}}}
    }})()
    test_hierarchy.get_data(cache_mock)
    assert test_hierarchy.df.empty
