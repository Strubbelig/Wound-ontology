"""Names are in sentence case: lowercase, capital first letter, abbreviations and names kept.

Curator, 2026-10-24. See `utils.normalise.sentence_case`.
"""
import pytest

from wound_ontology.utils.normalise import normalise, sentence_case


@pytest.mark.parametrize("label, name", [
    # Title Case and lowercase meet in one spelling
    ("Diabetic Foot Ulcers", "Diabetic foot ulcer"),
    ("surgical site infections", "Surgical site infection"),
    ("Wound Care Practitioner", "Wound care practitioner"),
    # abbreviations, symbols and inner capitals are left as written
    ("MRSA Infection", "MRSA infection"),
    ("IL-6 Levels", "IL-6 level"),
    ("mRNA expression", "mRNA expression"),
    ("T Cell", "T cell"),
    ("vitamin C", "Vitamin C"),
    ("the 5 Ps", "The 5 Ps"),
    ("Zn Supplementation", "Zn supplementation"),
    ("TaqMan Real-time RT-PCR analysis", "TaqMan real-time RT-PCR analysis"),
    ("BAX/Bcl-2/Cleaved Caspase-3 expression", "BAX/Bcl-2/cleaved caspase-3 expression"),
    # the first letter is raised only on a plain lowercase ASCII word
    ("pH level", "pH level"),
    ("β-lactam antibiotics", "β-lactam antibiotic"),
    ("x-ray", "X-ray"),
    # names inside a name keep their capital
    ("Methicillin-Resistant Staphylococcus Aureus", "Methicillin-resistant Staphylococcus aureus"),
    ("Fournier's Gangrene", "Fournier's gangrene"),
    ("Gustilo and Anderson wound classification", "Gustilo and Anderson wound classification"),
    ("Kaplan-Meier Analysis", "Kaplan-Meier analysis"),
    ("Colour Doppler Ultrasound", "Color Doppler ultrasound"),
])
def test_name_is_in_sentence_case(label, name):
    assert normalise(label).name == name


@pytest.mark.parametrize("label", ["processes", "Material Entity", "key role", "Quality"])
def test_a_category_keeps_the_spelling_bfo_gives_it(label):
    """Rule 22: `material entity`, not `Material entity` -- also when only the
    singular rule makes the label a category."""
    from wound_ontology.llm.category_vocab import declared_category
    name = normalise(label).name
    assert declared_category(name) == name and name == name.lower()


@pytest.mark.parametrize("label", ["is", "as", "vs", "dermal Micrograft", "family Aerococcaceae",
                                   "Aboriginal and Torres Strait Islander", "DFUs", "the 5 Ps"])
def test_idempotent(label):
    once = normalise(label).name
    assert normalise(once).name == once
    assert sentence_case(sentence_case(label)) == sentence_case(label)


def test_a_capitalised_short_word_is_not_an_acronym_plural():
    """`Is` is a word, `DFUs` an acronym plural; only the second loses its s."""
    from wound_ontology.utils.label_match import singular_spelling
    assert singular_spelling("Is") == "Is"
    assert singular_spelling("DFUs") == "DFU"


def test_case_does_not_change_the_key():
    """Two spellings that differ in case alone still group together."""
    assert normalise("Diabetic Foot Ulcer").key == normalise("diabetic foot ulcers").key
