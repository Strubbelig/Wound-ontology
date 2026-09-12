"""Surface variation must not mint a duplicate class.

"material entities" and "material entity" are one concept. Matched only on the
exact string, the plural misses BFO_0000040 and gets a fresh WONT id minted for
it -- a second class with the same meaning, no axioms, and no way for the
reasoner to know they are the same.
"""
import pytest
import rdflib

from wound_ontology.utils.label_match import LabelIndex, fold, singularize

A = rdflib.URIRef("http://example.org/A")
B = rdflib.URIRef("http://example.org/B")


@pytest.mark.parametrize("plural,singular", [
    ("wounds", "wound"),
    ("material entities", "material entity"),
    ("therapies", "therapy"),
    ("abscesses", "abscess"),
    ("processes", "process"),
    ("antibiotics", "antibiotic"),
    ("bacteria", "bacterium"),
    ("indices", "index"),
    ("feet", "foot"),
    ("analyses", "analysis"),
    ("diagnoses", "diagnosis"),
])
def test_plurals_fold_onto_their_singular(plural, singular):
    assert fold(plural) == fold(singular)


@pytest.mark.parametrize("word", [
    "sepsis", "dermis", "necrosis", "virus", "abscess", "process", "status",
    "diabetes", "species", "series", "scabies", "herpes", "ascites", "gas",
    "fibrous", "genetics",
])
def test_singular_words_that_look_plural_are_left_alone(word):
    """A clinical vocabulary is full of these; mangling "sepsis" into "sepsi"
    would break a match that currently works."""
    assert singularize(word) == word


def test_only_the_head_noun_is_singularized():
    assert fold("chronic wounds") == "chronic wound"
    assert fold("diseases of the skin") == "diseases of the skin"


def test_punctuation_and_hyphens_fold_too():
    idx = LabelIndex()
    idx.add("full-thickness wound", A)
    assert idx.get("full thickness wounds")[0] == A
    assert idx.get("Diabetic Foot Ulcer (DFU)")[0] is None  # different concept


def test_exact_match_wins_and_is_labelled_exact():
    idx = LabelIndex()
    idx.add("Wound", A)
    assert idx.get("wound") == (A, "exact")
    assert idx.get("WOUND") == (A, "exact")


def test_variant_match_is_reported_as_such():
    idx = LabelIndex()
    idx.add("material entity", A)
    iri, how = idx.get("Material Entities")
    assert (iri, how) == (A, "variant")


def test_two_classes_sharing_a_folded_key_are_refused_not_guessed():
    """193 labels in the real corpus are claimed by two imports at once.
    Picking one attaches every downstream axiom to a coin flip."""
    idx = LabelIndex()
    idx.add("quality", A)
    idx.add("qualities", B)
    iri, how = idx.get("quality")
    assert (iri, how) == (A, "exact"), "an exact hit still resolves"
    iri, how = idx.get("Qualitys")
    assert iri is None and how == "ambiguous"


def test_preferred_labels_beat_synonyms_regardless_of_order():
    idx = LabelIndex()
    idx.add("wound base", A, preferred=False)   # synonym
    idx.add("wound base", B, preferred=True)    # rdfs:label
    assert idx.get("wound base")[0] is B
    idx2 = LabelIndex()
    idx2.add("wound base", B, preferred=True)
    idx2.add("wound base", A, preferred=False)
    assert idx2.get("wound base")[0] is B


def test_update_with_preferred_false_keeps_the_first_claimant():
    """The lexicon merges MILD then modules alphabetically; whoever claims a
    label first keeps it, so resolution does not depend on iteration order."""
    first, second = LabelIndex(), LabelIndex()
    first.add("quality", A)
    second.add("quality", B)
    merged = LabelIndex()
    merged.update(first, preferred=False)
    merged.update(second, preferred=False)
    assert merged.get("quality")[0] is A


def test_empty_and_missing_terms_are_safe():
    idx = LabelIndex()
    idx.add("", A)
    assert len(idx) == 0
    assert idx.get("")[0] is None
    assert idx.get("nothing here")[0] is None


def test_it_still_behaves_like_the_dict_it_replaced():
    idx = LabelIndex()
    idx.add("Wound", A)
    assert idx["wound"] is A
    assert dict(idx.items()) == {"wound": A}
    assert list(idx.values()) == [A]
    assert "wound" in idx


# ── the -es branch is ambiguous, so it must not guess ────────────────────────
#
# Measured 2026-09-10 on the live store: 45 of 3536 terms have a head noun that
# takes the `-es` branch, and 31 of them were mis-singularised, because the rule
# strips two characters whenever the STEM ends in a sibilant -- true of both
# `bus`+`es` and `phase`+`s`, which are indistinguishable by suffix.

@pytest.mark.parametrize("plural,candidates", [
    ("phases",     ["phas", "phase"]),
    ("nurses",     ["nurs", "nurse"]),
    ("cases",      ["cas", "case"]),
    ("responses",  ["respons", "response"]),
    ("buses",      ["bus", "buse"]),
    ("approaches", ["approach", "approache"]),
])
def test_an_es_plural_offers_both_singulars(plural, candidates):
    from wound_ontology.utils.label_match import singular_candidates
    assert singular_candidates(plural) == candidates


@pytest.mark.parametrize("singular,plural", [
    ("Inflammatory phase", "Inflammatory Phases"),
    ("Proliferative phase", "Proliferative Phases"),
    ("Nurse", "Nurses"),
    ("Case", "Cases"),
    ("Response", "Responses"),
    ("Database", "Databases"),
    ("Disease", "Diseases"),
    ("Endoprotease", "Endoproteases"),
])
def test_an_es_plural_reaches_a_singular_that_keeps_its_e(singular, plural):
    """The 31 the old single guess could never find."""
    idx = LabelIndex()
    idx.add(singular, A)
    assert idx.get(plural) == (A, "variant")


@pytest.mark.parametrize("singular,plural", [
    ("approach", "Approaches"),
    ("process", "Processes"),
    ("lens", "Lenses"),
    ("bypass", "Bypasses"),
    ("census", "Censuses"),
    ("stress", "Stresses"),
])
def test_the_es_rule_still_wins_where_it_was_already_right(singular, plural):
    """The other 14. Offering a second candidate must not cost the first."""
    idx = LabelIndex()
    idx.add(singular, A)
    assert idx.get(plural) == (A, "variant")


def test_orthoses_reaches_orthosis():
    """No suffix candidate spans a Greek -sis/-ses pair, so it is listed."""
    idx = LabelIndex()
    idx.add("Orthosis", A)
    assert idx.get("Orthoses") == (A, "variant")


def test_an_ambiguous_candidate_does_not_hide_a_clean_one():
    """Two classes collide on the first candidate; the second still resolves,
    and refusing on the first collision would throw away a real match."""
    idx = LabelIndex()
    idx.add("cas", A)          # claims the strip-two key
    idx.add("cas ", B)         # ... twice over, so it is ambiguous
    idx.add("case", A)
    iri, how = idx.get("cases")
    assert (iri, how) == (A, "variant")


def test_ambiguity_is_still_refused_when_nothing_resolves():
    idx = LabelIndex()
    idx.add("phase", A)
    idx.add("phasE", B)        # same folded key, different class
    iri, how = idx.get("phases")
    assert iri is None and how == "ambiguous"


def test_fold_is_still_the_first_candidate():
    """fold() and singularize() are unchanged, so every existing caller is."""
    from wound_ontology.utils.label_match import fold_candidates, singular_candidates
    for term in ["phases", "wounds", "material entities", "abscesses", "bacteria"]:
        assert fold(term) == fold_candidates(term)[0]
        assert singularize(term) == singular_candidates(term)[0]
