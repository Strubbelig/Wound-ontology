"""`oedema` and `edema` are one word, and no model should be paid to notice.

The curator's rule of 2026-09-25: exhaust the deterministic methods before any
SapBERT or LLM call. These pin the part of that which is about spelling, and in
particular the two guards, because a British-to-American rewrite with no guard
is a wrecking ball: run over this corpus with only "the result occurs somewhere"
behind it, it produced `toe -> te`, `four -> for`, `anaerobic -> anerobic` and
`expertise -> expertize`.
"""

import pytest

from wound_ontology.utils.spelling import american_spelling, american_word


# ── what breame carries ──────────────────────────────────────────────────────

@pytest.mark.parametrize("british,american", [
    ("tumour", "tumor"), ("colour", "color"), ("centre", "center"),
    ("analyse", "analyze"), ("analysed", "analyzed"), ("labelled", "labeled"),
    ("paediatric", "pediatric"), ("orthopaedic", "orthopedic"),
    ("anaemia", "anemia"), ("oesophagus", "esophagus"), ("fibre", "fiber"),
    ("randomised", "randomized"), ("standardised", "standardized"),
])
def test_a_known_pair_is_rewritten(british, american):
    assert american_word(british) == american


# ── what it does not carry, and the patterns do ──────────────────────────────

@pytest.mark.parametrize("british,american", [
    ("oedema", "edema"), ("haematoma", "hematoma"), ("ischaemia", "ischemia"),
    ("ischaemic", "ischemic"), ("epithelialisation", "epithelialization"),
    ("necrotising", "necrotizing"), ("revascularisation", "revascularization"),
    ("haemodynamic", "hemodynamic"), ("oesophageal", "esophageal"),
    ("multicentre", "multicenter"),
])
def test_the_medical_tail_is_rewritten_too(british, american):
    assert american_word(british) == american


# ── the guards ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", ["four", "toe", "toes", "anaerobic", "there",
                                  "more", "acre", "core", "sure", "figure"])
def test_an_ordinary_word_that_ends_like_a_british_one_is_left_alone(word):
    # `our\b`, `oe`, `re\b` and `ae` all fire on these. The core-frequency
    # floor stops `four`, `core`, `sure` and `figure`; the "candidate must be
    # commoner" test stops `toe -> te` and `anaerobic -> anerobic`.
    assert american_word(word) == word


def test_a_core_english_word_is_never_touched_by_a_pattern():
    from wound_ontology.utils.spelling import CORE_ZIPF, zipf
    assert zipf("four") >= CORE_ZIPF
    assert zipf("oedema") < CORE_ZIPF


def test_an_archaic_dictionary_would_have_blocked_a_real_rewrite():
    # `/usr/share/dict/words` is Webster 1934 and lists `oesophageal` as
    # ordinary English, so a dictionary guard refused this one. It is the
    # reason the guard is frequency and not a wordlist.
    assert american_word("oesophageal") == "esophageal"


@pytest.mark.parametrize("word", ["expertise", "exercise", "surprise", "promise",
                                  "comprise", "advertise", "precise", "paradise",
                                  "franchise", "merchandise"])
def test_an_ise_word_that_is_not_a_verb_ending_survives(word):
    # `expertise` is in neither the 1934 dictionary nor breame's pair list, and
    # a typo in one abstract put `expertize` in the corpus. The frequency guard
    # is what stops it: 4.06 against 0.00.
    assert american_word(word) == word


def test_a_rewrite_needs_the_candidate_to_be_the_commoner_word():
    from wound_ontology.utils.spelling import zipf
    assert zipf("edema") > zipf("oedema")
    assert zipf("expertize") < zipf("expertise")


# ── casing and whole labels ──────────────────────────────────────────────────

@pytest.mark.parametrize("label,expected", [
    ("Oedema", "Edema"),
    ("OEDEMA", "EDEMA"),
    ("chronic oedema", "chronic edema"),
    ("Necrotising fasciitis", "Necrotizing fasciitis"),
    ("Tumour Necrosis Factor", "Tumor Necrosis Factor"),
    ("epithelialisation rate", "epithelialization rate"),
])
def test_the_labels_own_casing_survives(label, expected):
    assert american_spelling(label) == expected


def test_punctuation_and_digits_are_untouched():
    assert american_spelling("NaCl 0.9% (colour-coded)") == "NaCl 0.9% (color-coded)"


def test_a_label_with_nothing_to_change_comes_back_identical():
    for label in ("wound dressing", "diabetic foot ulcer", "Staphylococcus aureus"):
        assert american_spelling(label) == label


def test_it_is_safe_to_run_twice():
    once = american_spelling("Necrotising oedema of the centre")
    assert american_spelling(once) == once


def test_an_empty_label_is_not_an_error():
    assert american_spelling("") == ""


# ── two ways the rewrite went wrong on real corpus terms ─────────────────────

@pytest.mark.parametrize("word", ["iraes", "aes", "oed", "toed", "paed"])
def test_a_short_token_is_not_mined_for_a_latin_root(word):
    # `irAEs` (immune-related adverse events) reaches the store title-cased as
    # `Iraes`, the acronym already lost, and `ae -> e` turned it into `Ires`.
    # `ae` and `oe` are the only patterns that match inside a word, so they are
    # the only ones that can fire on something that is not a word.
    assert american_word(word) == word


@pytest.mark.parametrize("word,expected", [
    ("oedema", "edema"), ("anaemia", "anemia"), ("ischaemia", "ischemia"),
    ("caesarean", "cesarean"),
])
def test_a_long_enough_root_still_converts(word, expected):
    assert american_word(word) == expected


@pytest.mark.parametrize("word", ["analyses", "paralyses", "dialyses", "hydrolyses"])
def test_the_plural_of_ysis_is_not_a_british_verb(word):
    # breame reads `analyses` as the verb and answers `analyzes`; in abstracts
    # it is the noun. `Statistical Analyses` became `Statistical Analyzes`,
    # which then singularises to `analyze` instead of `analysis`.
    assert american_word(word) == word


def test_the_verb_form_still_converts():
    assert american_word("analyse") == "analyze"
    assert american_word("analysed") == "analyzed"


# ── where breame is wrong about medical English ──────────────────────────────

@pytest.mark.parametrize("word", ["disc", "discs", "aesthetic", "aesthetics",
                                  "gases", "gauge", "fillet"])
def test_a_word_breame_gets_wrong_for_medicine_is_held_back(word):
    # Found by listing all 144 conversions the corpus triggers and reading
    # them. `disc diffusion` is the standard susceptibility method and American
    # medicine writes disc; the American Society for Aesthetic Plastic Surgery
    # spells it that way; `gasses` is a verb and `gage` is archaic.
    assert american_word(word) == word


def test_the_exception_list_does_not_leak_into_similar_words():
    assert american_word("discolouration") == "discoloration"
    assert american_word("anaesthetic") == "anesthetic"


@pytest.mark.parametrize("british,american", [
    ("discolouration", "discoloration"), ("tumourigenesis", "tumorigenesis"),
    ("colourimetric", "colorimetric"), ("neighbourhood", "neighborhood"),
])
def test_our_inside_a_word_converts_too(british, american):
    # the word-final rule cannot see these, and `discolouration` is wound
    # vocabulary
    assert american_word(british) == american


@pytest.mark.parametrize("word", ["four", "hour", "your", "source", "resource",
                                  "course", "journal", "flour", "pour", "tour",
                                  "flourish", "nourish", "bourbon", "encourage"])
def test_an_ordinary_our_word_survives_the_unanchored_rule(word):
    assert american_word(word) == word


def test_a_rename_reaches_the_sense_labels_of_a_two_senses_ruling():
    """2026-10-02: `biopsy` was split into `biopsy` and `biopsy specimen`; the
    rename `biopsy specimen -> biopsy sample` (specimen -> sample) left the
    sense label in the old spelling, and the view kept writing it."""
    from conftest import memory_mapping
    gt = memory_mapping({"biopsy": {"to": {"process": "biopsy procedure",
                                           "material entity": "biopsy specimen"},
                                    "pairs": {}}})
    rep = gt.apply_renames({"biopsy specimen": "biopsy sample"}, by="test")
    assert gt.records["biopsy"]["to"]["material entity"] == "biopsy sample"
    assert rep["sense labels renamed"] == 1
