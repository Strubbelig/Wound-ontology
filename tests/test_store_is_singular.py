"""The store's name is singular, and that is a rule about the NAME, not a
decision recorded per term.

Rule 23 asked the mapping for it and could only deliver where the corpus
happened to contain a singular spelling; everything else stayed plural, and
5,072 mapping entries existed to say `patients -> patient` — a regex, written
down 5,072 times in a file of decisions. The curator's rule of 2026-09-23 —
"I always want the singular" — moves it to where it belongs:
`ConceptStore.normalize` singularises the head noun of every name it keeps,
after the mapping has had its say, so a plural canonical cannot reintroduce one.

Rule 51 (2026-09-27) moved where the rule is applied, not the rule. The store
keeps what each abstract said; a new string's singular is recorded as its
SPELLING at ingestion (`_spell_ingested`), and pass 0 respells the mapping's
canonicals, so a plural canonical cannot reintroduce a plural either. The view
reads both. The tests below check the name the view gives.

The exemption is the one rule 22 already states: a declared BFO category is
never normalised, so `process` does not become `proces` and the fifteen
category names keep their exact spelling.
"""
import pytest

from wound_ontology.store.concept_store import ConceptStore
from wound_ontology.utils.label_match import singular_spelling


def _ingested(entities, mapping=None):
    """A store that received `entities` through ingestion's spelling step."""
    class _DM:
        def load_latest_json(self, _): return {}
        def save_as_json(self, *_): pass
    st = ConceptStore(_DM(), "concept_store")
    st._dict = {"1": {"entities": entities}}
    st._spell_ingested(st._dict["1"], set())
    if mapping is not None:
        class _M:
            pass
        m = _M()
        m.mapping = mapping
        st.normalize(mapper=m)
    return st


def _view(st):
    return dict(st.records())["1"]


def test_a_plural_entity_reads_singular():
    st = _ingested({"patients": {"is_a: material entity": 1.0}})
    assert list(_view(st)) == ["Patient"]
    assert list(st.dict["1"]["entities"]) == ["patients"], "the evidence is as written"


def test_a_plural_target_reads_singular_too():
    st = _ingested({"wound": {"has_part: granulation tissues": 1.0}})
    assert list(_view(st)["Wound"]) == ["has_part: Granulation tissue"]


def test_a_plural_canonical_cannot_reintroduce_a_plural():
    """Pass 0 respells the canonical in the mapping itself (rule 43), so the
    view never meets the plural."""
    st = _ingested({"thermal burns": {"is_a: material entity": 1.0}})
    st.terms.add("thermal burn", "thermal burn injuries", confidence=1.0, method="manual")
    st.terms.apply_renames({"thermal burn injuries": "thermal burn injury"}, by="pass0")
    st._live_mapping = True
    assert list(_view(st)) == ["thermal burn injury"]


def test_a_declared_category_is_untouched():
    """Rule 22: a category is declared, never normalised — and `process` must
    not be singularised into something that is no longer a category name."""
    st = _ingested({"process": {"is_a: process": 1.0}})
    assert list(_view(st)) == ["process"]
    assert not st.terms.aliases()


def test_two_spellings_collapse_onto_one_record():
    """Ingestion singularises and, since 2026-10-24, puts the name in sentence
    case, so two spellings differing in number and case are one record at once."""
    st = _ingested({"Wounds": {"is_a: material entity": 1.0},
                    "wound": {"has_quality: chronic": 1.0}})
    assert _view(st) == {"Wound": {"is_a: material entity": 1.0,
                                   "has_quality: Chronic": 1.0}}


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
