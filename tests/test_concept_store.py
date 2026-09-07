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

    empty_store.normalize(mapper=FakeMapper())
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

    empty_store.normalize(mapper=IdentityMapper())
    # Both should collapse to "Wound"
    for pmid_data in empty_store.dict.values():
        for entity in pmid_data.get("entities", {}):
            assert entity == entity.strip().title()


# ── the BFO category vocabulary survives normalisation ───────────────────────
#
# A category name is a value from a closed vocabulary. normalize_term lowercases
# and smart_title cannot put CamelCase back, so `MaterialEntity` came out of
# normalisation as `Materialentity` -- a string that is not in CATEGORY_PARENT,
# which is what the hierarchy tests to decide whether an edge is a category
# typing. Rule 9's one-term-one-category reconciliation therefore stopped seeing
# those edges: on the 2026-09-07 run 40 classes landed under two disjoint BFO
# branches where 12 had before, and `Surgical Site Infection` came out both a
# disposition and a material entity.

import pytest

from wound_ontology.llm.extraction_models import CATEGORY_PARENT


@pytest.mark.parametrize("category", sorted(CATEGORY_PARENT))
def test_every_category_name_survives_normalization(empty_store, category):
    raw = {"1": {"entities": {"some term": {f"is_a: {category}": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class IdentityMapper:
        mapping = {}

    empty_store.normalize(mapper=IdentityMapper())
    triples = empty_store.dict["1"]["entities"]["Some Term"]
    assert f"is_a: {category}" in triples, triples


def test_normalization_repairs_a_category_already_damaged(empty_store):
    """A store written before the guard carries `Materialentity`; heal it."""
    raw = {"1": {"entities": {"some term": {"is_a: Materialentity": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class IdentityMapper:
        mapping = {}

    empty_store.normalize(mapper=IdentityMapper())
    assert "is_a: MaterialEntity" in empty_store.dict["1"]["entities"]["Some Term"]


def test_a_category_name_is_never_renamed_by_the_mapper(empty_store):
    """The mapping may not redefine a closed vocabulary either."""
    raw = {"1": {"entities": {"some term": {"is_a: MaterialEntity": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class BadMapper:
        mapping = {"MaterialEntity": "Material Thing"}

    empty_store.normalize(mapper=BadMapper())
    assert "is_a: MaterialEntity" in empty_store.dict["1"]["entities"]["Some Term"]


# ── the mapping must be applicable more than once ────────────────────────────
#
# normalize() title-cases the store, so from the second run onwards the store's
# spelling is not the extraction spelling the mapping is keyed by. An exact
# lookup then finds nothing and says nothing: 12 of 3574 live terms were an
# exact key where 68 matched on a normalised one. Every correction made to the
# mapping after the first apply -- a withdrawn merge, a re-pointed canonical --
# was unreachable.

def test_the_mapping_still_applies_after_the_store_was_normalized(empty_store):
    raw = {"1": {"entities": {"diabetic foot ulcers": {"is_a: wound": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class NoMapper:
        mapping = {}

    empty_store.normalize(mapper=NoMapper())          # first pass: title case
    assert "Diabetic Foot Ulcers" in empty_store.dict["1"]["entities"]

    class LateMapper:                                  # mapping corrected later
        mapping = {"diabetic foot ulcers": "diabetic foot ulcer"}

    empty_store.normalize(mapper=LateMapper())
    assert "Diabetic Foot Ulcer" in empty_store.dict["1"]["entities"]
    assert "Diabetic Foot Ulcers" not in empty_store.dict["1"]["entities"]


def test_targets_are_remapped_after_normalization_too(empty_store):
    raw = {"1": {"entities": {"some term": {"is_a: venous leg ulcers": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class NoMapper:
        mapping = {}

    empty_store.normalize(mapper=NoMapper())

    class LateMapper:
        mapping = {"venous leg ulcers": "venous leg ulcer"}

    empty_store.normalize(mapper=LateMapper())
    assert "is_a: Venous Leg Ulcer" in empty_store.dict["1"]["entities"]["Some Term"]


def test_the_exact_key_still_wins_over_the_normalised_one(empty_store):
    raw = {"1": {"entities": {"wound-care practice": {"is_a: wound": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class Mapper:
        mapping = {"wound-care practice": "Wound care practice",
                   "wound care practice": "Something Else"}

    empty_store.normalize(mapper=Mapper())
    assert "Wound Care Practice" in empty_store.dict["1"]["entities"]


def test_a_normalised_key_claimed_twice_is_reported(empty_store, capsys):
    raw = {"1": {"entities": {"x": {"is_a: wound": 1.0}}, "meta_stamp": "s"}}
    empty_store.get_data(raw)

    class Mapper:
        mapping = {"wound-care practice": "A", "wound care practice": "B"}

    empty_store.normalize(mapper=Mapper())
    assert "claim more than one canonical" in capsys.readouterr().out
