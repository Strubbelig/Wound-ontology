import pytest
from wound_ontology.store.extraction_cache import ExtractionCache


class MockDM:
    def __init__(self, initial=None):
        self._data = initial
    def load_latest_json(self, _): return self._data
    def save_as_json(self, data, _): self._data = data
    def get_meta_stamp(self, prefix): return f"meta_{prefix}_id", f"{prefix}_1_20260101_0000"


@pytest.fixture
def empty_cache():
    return ExtractionCache(MockDM(), "extraction_cache")


@pytest.fixture
def loaded_cache():
    data = {
        "123": {
            "entities": {
                "Chronic Wound": {"is_a: Wound": 1.0, "has_quality: Chronic": 1.0},
                "Wound":         {"is_a: Tissue Defect": 1.0}
            },
            "meta_stamp": "llm_extract_1"
        }
    }
    return ExtractionCache(MockDM(data), "extraction_cache")


def test_empty_cache_is_dict(empty_cache):
    assert isinstance(empty_cache.dict, dict)
    assert len(empty_cache.dict) == 0


def test_targets_extracted(loaded_cache):
    targets = loaded_cache.targets
    assert "Wound" in targets
    assert "Chronic" in targets


def test_predicates_extracted(loaded_cache):
    preds = loaded_cache.predicates
    assert "is_a" in preds
    assert "has_quality" in preds


def test_meta_excluded_from_attributes(loaded_cache):
    attrs = loaded_cache.attributes
    assert not any(a.startswith("meta_") for a in attrs)
