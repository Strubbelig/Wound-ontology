"""The store's name is singular, and that is a rule about the NAME, not a
decision recorded per term.

Rule 23 asked the mapping for it and could only deliver where the corpus
happened to contain a singular spelling; everything else stayed plural, and
5,072 mapping entries existed to say `patients -> patient` — a regex, written
down 5,072 times in a file of decisions. The curator's rule of 2026-09-23 —
"I always want the singular" — moves it to where it belongs:
`ConceptStore.normalize` singularises the head noun of every name it keeps,
after the mapping has had its say, so a plural canonical cannot reintroduce one.

The exemption is the one rule 22 already states: a declared BFO category is
never normalised, so `process` does not become `proces` and the fifteen
category names keep their exact spelling.
"""
import pytest

from wound_ontology.store.concept_store import ConceptStore
from wound_ontology.utils.label_match import singular_spelling


class _Mapper:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}


def _store(tmp_path, entities):
    st = ConceptStore.__new__(ConceptStore)
    st._dict = {"1": {"entities": entities}}
    st.dm = None
    st.save = lambda: None
    return st


def test_a_plural_entity_becomes_singular(tmp_path):
    st = _store(tmp_path, {"patients": {"is_a: material entity": 1.0}})
    st.normalize(mapper=_Mapper())
    assert list(st._dict["1"]["entities"]) == ["Patient"]


def test_a_plural_target_becomes_singular_too(tmp_path):
    st = _store(tmp_path, {"wound": {"has_part: granulation tissues": 1.0}})
    st.normalize(mapper=_Mapper())
    assert list(st._dict["1"]["entities"]["Wound"]) == ["has_part: Granulation Tissue"]


def test_a_plural_canonical_cannot_reintroduce_a_plural(tmp_path):
    """The mapping has its say first; the singular rule applies to the result."""
    st = _store(tmp_path, {"thermal burns": {"is_a: material entity": 1.0}})
    st.normalize(mapper=_Mapper({"thermal burns": "thermal burn injuries"}))
    assert list(st._dict["1"]["entities"]) == ["Thermal Burn Injury"]


def test_a_declared_category_is_untouched(tmp_path):
    """Rule 22: a category is declared, never normalised — and `process` must
    not be singularised into something that is no longer a category name."""
    st = _store(tmp_path, {"process": {"is_a: process": 1.0}})
    st.normalize(mapper=_Mapper())
    assert list(st._dict["1"]["entities"]) == ["process"]


def test_two_spellings_collapse_onto_one_record(tmp_path):
    st = _store(tmp_path, {"Wounds": {"is_a: material entity": 1.0},
                           "wound": {"has_quality: chronic": 1.0}})
    st.normalize(mapper=_Mapper())
    assert list(st._dict["1"]["entities"]) == ["Wound"]
    assert set(st._dict["1"]["entities"]["Wound"]) == {"is_a: material entity",
                                                       "has_quality: Chronic"}


@pytest.mark.parametrize("plural, singular", [
    ("Diabetic Foot Ulcers", "Diabetic Foot Ulcer"),
    ("DFUs", "DFU"),                       # an acronym plural, invisible to suffix rules
    ("SSIs", "SSI"),
    ("analyses", "analysis"),
    ("fistulae", "fistula"),
])
def test_the_speller_keeps_the_label_s_own_spelling(plural, singular):
    assert singular_spelling(plural) == singular


@pytest.mark.parametrize("word", [
    "Diabetes", "sepsis", "necrosis", "osteomyelitis", "fasciitis",
    "MRSA", "series", "bias", "Wound",
])
def test_the_speller_leaves_medical_singulars_alone(word):
    """-sis, -itis, -us and acronyms are where a naive `rstrip('s')` maims a
    vocabulary: `diabetes` must not become `diabete`."""
    assert singular_spelling(word) == word
