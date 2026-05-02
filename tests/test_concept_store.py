import pytest
from wound_ontology.store.concept_store import ConceptStore
import pandas as pd


class MockDM:
    def __init__(self, initial=None):
        self._data = initial
    def load_latest_json(self, _): return self._data
    def save_as_json(self, data, _): self._data = data
    def get_meta_stamp(self, prefix): return f"meta_{prefix}_id", f"{prefix}_1_20260101_0000"


@pytest.fixture
def empty_store():
    return ConceptStore(MockDM(), "concept_store")


@pytest.fixture
def loaded_store():
    data = {
        "123": {
            "entities": {
                "Chronic Wound": {"is_a: Wound": 1.0, "has_quality: Chronic": 1.0},
                "Wound":         {"is_a: Tissue Defect": 1.0}
            },
            "meta_stamp": "llm_extract_1"
        }
    }
    return ConceptStore(MockDM(data), "concept_store")


def test_empty_store_is_dict(empty_store):
    assert isinstance(empty_store.dict, dict)
    assert len(empty_store.dict) == 0


def test_targets_extracted(loaded_store):
    targets = loaded_store.targets
    assert "Wound" in targets
    assert "Chronic" in targets


def test_predicates_extracted(loaded_store):
    preds = loaded_store.predicates
    assert "is_a" in preds
    assert "has_quality" in preds


def test_meta_excluded_from_attributes(loaded_store):
    attrs = loaded_store.attributes
    assert not any(a.startswith("meta_") for a in attrs)


def test_get_data_df(empty_store):
    """get_data with a DataFrame converts edges to is_a triples."""
    df = pd.DataFrame([
        {"Class": "Chronic Wound", "Parent class": "Wound"},
        {"Class": "Acute Wound",   "Parent class": "Wound"},
    ])
    empty_store.get_data(df)
    predefined = empty_store.dict.get("predefined", {})
    entities = predefined.get("entities", {})
    assert entities.get("Chronic Wound", {}).get("is_a: Wound") == 1.0
    assert entities.get("Acute Wound",   {}).get("is_a: Wound") == 1.0


def test_get_data_dict(empty_store):
    """get_data with a dict merges entries directly."""
    raw = {"999": {"entities": {"Biofilm": {"is_a: Wound": 1.0}}, "meta_stamp": "x"}}
    empty_store.get_data(raw)
    assert "999" in empty_store.dict


def test_normalize_applies_mapping(empty_store):
    """normalize() renames entities and targets using the mapper, and Title-cases."""
    raw = {"1": {"entities": {"chronic wound": {"is_a: wound": 1.0}}, "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class FakeMapper:
        mapping = {"chronic wound": "Chronic Wound", "wound": "Wound"}

    empty_store.normalize(entity_mapper=FakeMapper(), target_mapper=FakeMapper())
    entities = empty_store.dict["1"]["entities"]
    assert "Chronic Wound" in entities
    assert entities["Chronic Wound"].get("is_a: Wound") == 1.0
    assert "chronic wound" not in entities


def test_normalize_deduplicates_title_case(empty_store):
    """Two entities that differ only in case should merge after normalization."""
    raw = {
        "1": {"entities": {"wound": {"is_a: tissue defect": 1.0}}, "meta_stamp": "x"},
        "2": {"entities": {"Wound": {"has_quality: chronic": 1.0}}, "meta_stamp": "y"},
    }
    empty_store.get_data(raw)

    class IdentityMapper:
        mapping = {}

    empty_store.normalize(entity_mapper=IdentityMapper())
    # Both should collapse to "Wound"
    for pmid_data in empty_store.dict.values():
        for entity in pmid_data.get("entities", {}):
            assert entity == entity.strip().title()
