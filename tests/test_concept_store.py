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


def _view(store) -> dict:
    """{key: {entity: {triple: value}}} as downstream reads it (rule 51)."""
    return dict(store.records())


def test_normalize_applies_mapping(empty_store):
    """normalize() applies the mapping THROUGH THE VIEW; the evidence keeps
    what the abstract said (rule 51)."""
    raw = {"1": {"entities": {"chronic wound": {"is_a: wound": 1.0}}, "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class FakeMapper:
        mapping = {"chronic wound": "Chronic Wound", "wound": "Wound"}

    empty_store.normalize(mapper=FakeMapper())
    entities = _view(empty_store)["1"]
    assert entities == {"Chronic Wound": {"is_a: Wound": 1.0}}
    assert empty_store.dict["1"]["entities"] == {"chronic wound": {"is_a: wound": 1.0}}


def test_case_variants_merge_once_a_spelling_is_recorded(empty_store):
    """Title-casing in `normalize` used to merge `wound` and `Wound`; pass 0
    elects one spelling and records it now, and the view merges on it."""
    raw = {
        "1": {"entities": {"wound": {"is_a: tissue defect": 1.0}}, "meta_stamp": "x"},
        "2": {"entities": {"Wound": {"has_quality: chronic": 1.0}}, "meta_stamp": "y"},
    }
    empty_store.get_data(raw)
    empty_store.apply_renames({"Wound": "wound"}, by="pass0")
    assert {e for ents in _view(empty_store).values() for e in ents} == {"wound"}
    assert "Wound" in empty_store.dict["2"]["entities"]            # as written


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
    triples = _view(empty_store)["1"]["some term"]
    assert f"is_a: {category}" in triples, triples


def test_normalization_repairs_a_category_already_damaged(empty_store):
    """A store written before the guard carries `Materialentity`; heal it."""
    raw = {"1": {"entities": {"some term": {"is_a: Materialentity": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class IdentityMapper:
        mapping = {}

    empty_store.normalize(mapper=IdentityMapper())
    assert "is_a: material entity" in _view(empty_store)["1"]["some term"]


def test_a_category_name_is_never_renamed_by_the_mapper(empty_store):
    """The mapping may not redefine a closed vocabulary either."""
    raw = {"1": {"entities": {"some term": {"is_a: material entity": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class BadMapper:
        mapping = {"material entity": "Material Thing"}

    empty_store.normalize(mapper=BadMapper())
    assert "is_a: material entity" in _view(empty_store)["1"]["some term"]


def test_a_term_that_maps_onto_a_category_gets_the_declared_spelling(empty_store):
    """The other direction of rule 22, and the one the rename created.

    The live mapping holds `roles -> Role`. `Role` was the category spelling
    until 2026-09-08 and is now just a title-cased string, so without declaring
    the RESULT of a mapping the store would carry `Role` for the mapped term and
    `role` for the bare one -- two spellings of the one category, which is
    exactly the split the rename exists to end.
    """
    raw = {"1": {"entities": {"roles": {"is_a: process": 1.0},
                              "Role": {"is_a: process": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class RolesMapper:
        mapping = {"roles": "Role"}

    empty_store.normalize(mapper=RolesMapper())
    names = set(_view(empty_store)["1"])
    assert names == {"role"}, names


def test_a_mapped_target_is_declared_too(empty_store):
    """Targets go through the same door as entities, and are what the category
    reconciliation actually reads."""
    raw = {"1": {"entities": {"some term": {"is_a: roles": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class RolesMapper:
        mapping = {"roles": "Role"}

    empty_store.normalize(mapper=RolesMapper())
    assert "is_a: role" in _view(empty_store)["1"]["some term"]


# ── a correction to the mapping always reaches the store ─────────────────────
#
# When normalize() rewrote the store, the store's spelling drifted from the
# extraction spelling the mapping is keyed by, and an exact lookup found
# nothing: 12 of 3574 live terms were an exact key where 68 matched on a
# normalised one, and every correction made after the first apply was
# unreachable. The view reads the evidence, which never drifts (rule 51), and
# still falls back to the folded key for mappings written against other
# spellings.

def test_a_later_correction_to_the_mapping_reaches_the_view(empty_store):
    raw = {"1": {"entities": {"diabetic foot ulcers": {"is_a: wound": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class FirstMapper:
        mapping = {"diabetic foot ulcers": "Diabetic foot ulcer"}

    empty_store.normalize(mapper=FirstMapper())
    assert "Diabetic foot ulcer" in _view(empty_store)["1"]

    class LateMapper:                                  # mapping corrected later
        mapping = {"diabetic foot ulcers": "Diabetic wound"}

    empty_store.normalize(mapper=LateMapper())
    assert set(_view(empty_store)["1"]) == {"Diabetic wound"}


def test_a_target_is_mapped_through_the_folded_key(empty_store):
    raw = {"1": {"entities": {"some term": {"is_a: Venous Leg Ulcers": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class Mapper:
        mapping = {"venous leg ulcers": "venous leg ulcer"}

    empty_store.normalize(mapper=Mapper())
    assert "is_a: venous leg ulcer" in _view(empty_store)["1"]["some term"]


def test_the_exact_key_still_wins_over_the_normalised_one(empty_store):
    raw = {"1": {"entities": {"wound-care practice": {"is_a: wound": 1.0}},
                 "meta_stamp": "x"}}
    empty_store.get_data(raw)

    class Mapper:
        mapping = {"wound-care practice": "Wound care practice",
                   "wound care practice": "Something Else"}

    empty_store.normalize(mapper=Mapper())
    assert "Wound care practice" in _view(empty_store)["1"]


def test_a_normalised_key_claimed_twice_is_reported(empty_store, capsys):
    raw = {"1": {"entities": {"x": {"is_a: wound": 1.0}}, "meta_stamp": "s"}}
    empty_store.get_data(raw)

    class Mapper:
        mapping = {"wound-care practice": "A", "wound care practice": "B"}

    empty_store.normalize(mapper=Mapper())
    assert "claim more than one canonical" in capsys.readouterr().out
