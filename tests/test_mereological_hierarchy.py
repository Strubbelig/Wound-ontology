import pytest
from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy


class MockDM:
    def load_latest_csv(self, _): return None
    def save_as_csv(self, df, _): pass


@pytest.fixture
def test_hierarchy():
    return MereologicalHierarchy(MockDM())


def test_part_of_direct(test_hierarchy):
    """part_of: stored as-is → row=branch, col=root."""
    cache_mock = type("C", (), {"dict": {
        "1": {"entities": {"Wound Bed": {"part_of: Wound": 1.0}}}
    }})()
    test_hierarchy.get_data(cache_mock)
    assert test_hierarchy.df.at["Wound Bed", "Wound"] == 1.0


def test_part_of_wound_bed(test_hierarchy):
    """Wound Bed part_of Wound — canonical mereological edge."""
    cache_mock = type("C", (), {"dict": {
        "1": {"entities": {"Wound Bed": {"part_of: Wound": 1.0}}}
    }})()
    test_hierarchy.get_data(cache_mock)
    assert test_hierarchy.df.at["Wound Bed", "Wound"] == 1.0


def test_is_a_not_ingested(test_hierarchy):
    """MereologicalHierarchy must ignore is_a predicates."""
    cache_mock = type("C", (), {"dict": {
        "1": {"entities": {"Chronic Wound": {"is_a: Wound": 1.0}}}
    }})()
    test_hierarchy.get_data(cache_mock)
    assert test_hierarchy.df.empty


def test_subtree(test_hierarchy):
    test_hierarchy._set_edge("Wound Bed",   "Wound")
    test_hierarchy._set_edge("Granulation", "Wound Bed")
    subtree = test_hierarchy.subtree_of("Wound")
    assert "Wound Bed"   in subtree
    assert "Granulation" in subtree


def test_get_data(test_hierarchy):
    """Predefined mereological edges piped through a ConceptStore mock."""
    store_mock = type("S", (), {"dict": {
        "predefined": {"entities": {
            "Wound Bed":   {"part_of: Wound": 1.0},
            "Wound Fluid": {"part_of: Wound": 1.0},
        }}
    }})()
    test_hierarchy.get_data(store_mock)
    assert test_hierarchy.df.at["Wound Bed",   "Wound"] == 1.0
    assert test_hierarchy.df.at["Wound Fluid", "Wound"] == 1.0
