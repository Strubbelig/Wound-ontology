"""The singular the store WRITES is chosen, not guessed.

`singular_candidates` returns two answers for the ambiguous `-es` branch and
says so: `buses -> bus` drops two characters because the singular ends in a
sibilant, `phases -> phase` drops one because it already ends in `e`, and the
surface forms are identical. A lookup can try both. `singularize` takes the
first and documents the guess as harmless *because a key is only ever looked
up*.

On 2026-09-23 that stopped being true: `singular_spelling` began producing the
store's NAMES from `singularize`, and the guess started being written down.
Measured on the 2026-09-24 store, 938 names across 96 head nouns went through
that branch, and the curator found it from the other end -- reviewing
`case -> cases` and noting "canonical is always the singular, this should have
been handled by the regex". It was `cas`.

`naming_singular` is the naming path. `singularize` is unchanged, so every
folded lookup built on it answers exactly what it answered before.
"""

import pytest

from wound_ontology.utils.label_match import (
    fold, naming_singular, singular_candidates, singular_spelling, singularize,
)


# ── The two groups the -es branch actually contains ──────────────────────────

@pytest.mark.parametrize("plural,singular", [
    ("cases", "case"), ("doses", "dose"), ("nurses", "nurse"),
    ("phases", "phase"), ("causes", "cause"), ("diseases", "disease"),
    ("purposes", "purpose"), ("gauzes", "gauze"), ("uses", "use"),
    ("responses", "response"), ("expenses", "expense"), ("bruises", "bruise"),
    ("kinases", "kinase"), ("proteases", "protease"), ("synapses", "synapse"),
])
def test_a_ses_plural_keeps_the_e(plural, singular):
    """The whole 2026-09-24 defect: these were `cas`, `dos`, `nurs`, `caus`."""
    assert naming_singular(plural) == singular


@pytest.mark.parametrize("plural,singular", [
    ("searches", "search"), ("patches", "patch"), ("branches", "branch"),
    ("meshes", "mesh"), ("brushes", "brush"), ("boxes", "box"),
    ("complexes", "complex"), ("indexes", "index"), ("reflexes", "reflex"),
])
def test_a_ches_shes_or_xes_plural_drops_the_es(plural, singular):
    """Here the `-es` is there for pronunciation and the stem is the word."""
    assert naming_singular(plural) == singular


@pytest.mark.parametrize("plural,singular", [
    ("viruses", "virus"), ("sinuses", "sinus"), ("censuses", "census"),
    ("gases", "gas"), ("biases", "bias"), ("boluses", "bolus"),
])
def test_a_stem_that_is_already_a_word_keeps_its_stem(plural, singular):
    """`viruses -> virus`, not `viruse`. No suffix separates these from
    `causes -> cause`: `caus`, `hous` and `abus` all end the same way and all
    want the `e` back. Which strings are words is not a suffix question, so the
    stems are listed."""
    assert naming_singular(plural) == singular


@pytest.mark.parametrize("plural,singular", [
    ("processes", "process"), ("abscesses", "abscess"), ("classes", "class"),
])
def test_a_sses_plural_never_reaches_the_ambiguous_branch(plural, singular):
    assert singular_candidates(plural) == [singular]
    assert naming_singular(plural) == singular


# ── The -sis family, which is open-ended ─────────────────────────────────────

@pytest.mark.parametrize("plural,singular", [
    ("osteosyntheses", "osteosynthesis"), ("sub-analyses", "sub-analysis"),
    ("endoprostheses", "endoprosthesis"), ("microthromboses", "microthrombosis"),
    ("meta‑analyses", "meta‑analysis"),
])
def test_a_compound_takes_the_singular_of_its_tail(plural, singular):
    """`osteosyntheses` will never be a key and neither will the next one. The
    2026-09-24 store had three of these plus a `meta-analyses` spelled with a
    non-breaking hyphen, which no ASCII key can match."""
    assert naming_singular(plural) == singular


@pytest.mark.parametrize("plural,singular", [
    ("noses", "nose"), ("roses", "rose"), ("doses", "dose"),
    ("overdoses", "overdose"), ("glucoses", "glucose"), ("specimens", "specimen"),
])
def test_the_compound_rule_does_not_fire_on_a_word_that_merely_ends_that_way(plural, singular):
    """A general `-ses -> -sis` rule would wreck `roses` and `noses`, which is
    why the family is a list of tails and not a suffix."""
    assert naming_singular(plural) == singular


# ── Acronyms ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("acronym", ["POSAS", "ARDS", "NIRS", "KOOS", "ASES",
                                     "SBSES", "LEFS", "VAS", "GCS"])
def test_an_all_caps_acronym_keeps_its_last_letter(acronym):
    """275 all-caps heads in the store end in S and the suffix rules were eating
    the final letter of seven of them. The ones that survived did so by accident:
    `VAS` and `LOS` are under the four-character floor."""
    assert singular_spelling(acronym) == acronym


@pytest.mark.parametrize("plural,singular", [("DFUs", "DFU"), ("SSIs", "SSI"),
                                             ("PJIs", "PJI")])
def test_an_acronym_with_a_lower_case_plural_s_still_loses_it(plural, singular):
    """`DFUs` is an acronym wearing an English plural; `ARDS` is not."""
    assert singular_spelling(plural) == singular


# ── Naming and lookup are separate ───────────────────────────────────────────

def test_the_lookup_singular_is_deliberately_unchanged():
    """`singularize` and everything folded on it must answer what they always
    answered, or the change reaches clustering, the store's folded lookup and
    every mapping built on them."""
    assert singularize("cases") == "cas"
    assert singularize("viruses") == "virus"
    assert singular_candidates("cases") == ["cas", "case"]


def test_the_fold_gains_only_the_pairs_it_should():
    """Measured over 96,916 store names and mapping terms: 20 fold differently
    and 4 groups merge that did not before — each a real singular/plural pair."""
    assert fold("headaches") == fold("headache")
    assert fold("actinic keratoses") == fold("actinic keratosis")
    assert fold("roses") != fold("rosis")


def test_the_name_is_stable_when_applied_twice():
    for label in ("Diabetic Foot Ulcers", "cases", "POSAS", "viruses",
                  "osteosyntheses", "Pressure Ulcer"):
        once = singular_spelling(label)
        assert singular_spelling(once) == once, label


def test_the_words_that_only_look_plural_are_still_safe():
    for label in ("diabetes", "series", "necrosis", "sepsis", "lens", "species"):
        assert singular_spelling(label) == label


def test_the_curators_row():
    """`case -> cases` is what started this."""
    assert singular_spelling("cases") == "case"


def test_a_genitive_is_not_a_plural():
    """`naming_singular` read the final s of `patient's` as a plural and
    answered `patient'` — a name nobody would ever write. The same shape
    covers a quoted phrase, whose head is `'wound'`. 17 store names on the
    2026-09-26 corpus."""
    from wound_ontology.utils.label_match import singular_spelling
    for label in ["patient's", "fibroblasts'", "growth factors'",
                  "'machine learning'", "'wound'"]:
        assert singular_spelling(label) == label


def test_a_latin_species_epithet_is_not_a_plural():
    """`albicans`, `marcescens`, `perfringens` end -ans/-ens exactly as
    `clinicians`, `pathogens` and `specimens` do, and no suffix rule separates
    them. Every one of these was in the store being turned into a word that
    does not exist — `Candida albican`, `Serratia marcescen`."""
    from wound_ontology.utils.label_match import singular_spelling
    for label in ["Candida albicans", "Serratia marcescens",
                  "Clostridium perfringens", "Eikenella corrodens",
                  "thromboangiitis obliterans", "Achromobacter xylosoxidans",
                  "Mycobacterium ulcerans", "Homo sapiens", "Pseudomonas",
                  "erysipelas", "glans", "dens"]:
        assert singular_spelling(label) == label, label


def test_more_latin_and_invariant_words_keep_their_s():
    """Found 2026-10-25 behind `Streptococcus pyogene`: epithets in -es,
    genera in -monas/-myces/-oides, and anatomy whose singular ends in -s. The
    last part of a hyphenated word counts too (`risk-of-bias`), but an -ics
    word there is a real plural (`C-statistics`)."""
    from wound_ontology.utils.label_match import singular_spelling
    for label in ["Streptococcus pyogenes", "Cutibacterium acnes", "Bacteroides",
                  "Stenotrophomonas", "Actinomyces", "Mycosis fungoides",
                  "pancreas", "iliopsoas", "Single-cell atlas", "hypospadias",
                  "risk-of-bias", "Type-2-diabetes", "Texas"]:
        assert singular_spelling(label) == label, label
    assert singular_spelling("C-statistics") == "C-statistic"


def test_a_real_plural_with_the_same_ending_still_singularises():
    """The list must not swallow the ordinary words that share the ending."""
    from wound_ontology.utils.label_match import singular_spelling
    for plural, single in [("clinicians", "clinician"), ("pathogens", "pathogen"),
                           ("specimens", "specimen"), ("regimens", "regimen"),
                           ("N-glycans", "N-glycan"), ("antigens", "antigen")]:
        assert singular_spelling(plural) == single


def test_an_internal_capital_is_not_ours_to_normalise():
    """A token with an internal capital is an acronym or a chemical name. The
    round trip through the lowercase `naming_singular` was destroying it:
    `miRNAs` came back `mirna` and `iGAS` came back `iga` — in the store, from
    2026-09-26, because ingestion normalises."""
    from wound_ontology.utils.label_match import singular_spelling
    assert singular_spelling("miRNAs") == "miRNA"
    assert singular_spelling("microRNAs") == "microRNA"
    # a trailing CAPITAL S is part of the acronym, not a plural
    assert singular_spelling("iGAS") == "iGAS"
    assert singular_spelling("PrUMS") == "PrUMS"
