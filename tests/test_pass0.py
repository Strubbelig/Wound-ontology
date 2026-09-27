"""Pass 0 settles what a rule can settle, before a model is asked anything.

The curator's rule of 2026-09-25. On the live store it merged 9,578 spellings
that no embedding should ever have been consulted about -- eight spellings of
`Surgical Site Infection`, seven of `negative pressure wound therapy`, six of
`pressure ulcer`.

Two things it must never do, both of which it did before these tests:

* merge `vitamin (role)` into `vitamin`, because `fold` strips a parenthetical
  and a role class is not the substance;
* choose a different canonical on the second run than on the first, which is
  what `canonical_rank`'s untotal order caused -- 773 groups rewritten on a
  re-run, the winner depending on the process's hash seed.
"""

import pytest

from wound_ontology.mappers.pass0 import pass0_renames
from wound_ontology.utils.normalise import normalise


def _pairs(freq, anchors=(), others=(), declared=()):
    return pass0_renames(dict(freq), set(anchors), tuple(others),
                         declares=(declared.get if isinstance(declared, dict)
                                   else lambda t: t if t in set(declared) else None))


# ── the four deterministic steps ─────────────────────────────────────────────

@pytest.mark.parametrize("label,expected", [
    ("Diabetic Foot Ulcers", "Diabetic Foot Ulcer"),      # singular
    ("Necrotising fasciitis", "Necrotizing fasciitis"),   # british
    ("Caesarean sections", "Cesarean section"),           # both
    ("Statistical Analyses", "Statistical Analysis"),     # singular BEFORE british
    ("wound dressing", "wound dressing"),                 # nothing to do
])
def test_the_preferred_spelling(label, expected):
    assert normalise(label).name == expected


@pytest.mark.parametrize("a,b", [
    ("Surgical Site Infection", "surgical site infections"),
    ("split-thickness skin graft", "Split Thickness Skin Grafts"),
    ("chronic limb-threatening ischaemia", "Chronic Limb-Threatening Ischemia"),
    ("Caesarean section", "cesarean sections"),
])
def test_two_spellings_of_one_thing_share_a_key(a, b):
    assert normalise(a).key == normalise(b).key


def test_two_different_things_do_not_share_a_key():
    assert normalise("venous leg ulcer").key != normalise("arterial leg ulcer").key


# ── the seam: hyphen, space and nothing are one character ────────────────────
#
# The curator, 2026-09-27, handed `intraabdominal complication` ->
# `intra-abdominal complication` to adjudicate by hand: *this should have been
# treated by the dehyphenation.* It was not. `normalize_term` turns a hyphen
# into a space, so the dehyphenated spelling met `intra abdominal` and never
# met `intraabdominal`, and 888 store names sat in 439 groups that a person
# was being asked to reunite one pair at a time.

@pytest.mark.parametrize("a,b", [
    ("intra-abdominal complication", "intraabdominal complication"),
    ("intra-abdominal complication", "intra abdominal complication"),
    ("health care provider", "healthcare provider"),
    ("anti-microbial activity", "antimicrobial activity"),
    ("end point", "endpoint"),
    ("MMP-1", "MMP1"),
    ("re-tear", "re\u2011tear"),              # ASCII hyphen vs U+2011
])
def test_a_seam_written_two_ways_is_one_term(a, b):
    assert normalise(a).key == normalise(b).key
    assert normalise(a).strict == normalise(b).strict


def test_the_seam_closes_after_the_head_noun_is_singularised():
    """Removing the spaces first would leave `singular_spelling` no head."""
    assert normalise("anti-microbial agents").key == normalise("antimicrobial agent").key


def test_a_character_that_is_not_a_seam_still_splits_the_group():
    """`strict` is what stops the wider key from merging two real terms."""
    for a, b in [("p < 0.05", "p > 0.05"), ("Na+", "NA"), ("Phase I/II", "Phase III")]:
        assert normalise(a).key == normalise(b).key, (a, b)
        assert normalise(a).strict != normalise(b).strict, (a, b)


def test_pass0_settles_a_dehyphenation_instead_of_asking_the_curator():
    pairs, _ = _pairs({"intra-abdominal complication": 5,
                       "intraabdominal complication": 2})
    assert pairs == {"intraabdominal complication": "intra-abdominal complication"}


def test_the_language_breaks_a_seam_tie_the_corpus_cannot():
    """Closing the seam handed the election a question it could not answer.

    Both spellings appear in one abstract, so `canonical_rank` fell through
    to WORD COUNT -- and `Cumberl and Ankle Instability Tool` has one word
    more than the instrument's actual name. Pass 0 was about to rename the
    instrument onto the typo.
    """
    pairs, _ = _pairs({"Cumberland Ankle Instability Tool": 1,
                       "Cumberl and Ankle Instability Tool": 1})
    assert pairs == {"Cumberl and Ankle Instability Tool":
                     "Cumberland Ankle Instability Tool"}


def test_a_digit_is_not_a_word_the_language_failed_to_learn():
    """`POD7` and `POD 7` are one term, and neither of them invents a word.

    Counting the digits into the token makes `pod7` a string no English list
    has ever seen, so the unspaced spelling would look like a typo and lose
    an election for a reason that has nothing to do with English.
    """
    from wound_ontology.mappers.pass0 import invented_words
    assert invented_words("POD7") == invented_words("POD 7") == 0


def test_the_corpus_still_outranks_the_language():
    """The language only speaks where the corpus is silent.

    `antibiofilm` is in no general-English word list, and a medical corpus
    that writes it three times to one `anti-biofilm` is entitled to it.
    """
    pairs, _ = _pairs({"antibiofilm": 3, "anti-biofilm": 1})
    assert pairs == {"anti-biofilm": "antibiofilm"}


# ── what it writes ───────────────────────────────────────────────────────────

def test_every_variant_maps_onto_one_spelling():
    pairs, _ = _pairs({"wound": 9, "Wounds": 2, "wounds": 4})
    assert pairs == {"Wounds": "wound", "wounds": "wound"}


def test_the_most_frequent_spelling_wins():
    pairs, _ = _pairs({"Pressure Ulcer": 1, "pressure ulcers": 20})
    assert set(pairs.values()) == {"pressure ulcer"}


def test_an_ontology_label_wins_and_keeps_its_own_spelling():
    # rule 36: the ontology's label is the canonical, exactly as written
    pairs, _ = _pairs({"surgical site infections": 50, "Surgical site infection": 1},
                      anchors=["Surgical site infection"])
    assert pairs == {"surgical site infections": "Surgical site infection"}


def test_an_ontology_label_is_not_respelled_even_when_it_is_plural():
    # the ontology names its own classes. If a curated label is `Pressure
    # Ulcers`, pass 0 does not answer back with `Pressure Ulcer`: rule 36 says
    # the label IS the canonical, and rule 23a is advice to the curator, not a
    # licence to rewrite what they wrote.
    pairs, report = _pairs({"pressure ulcer": 40, "Pressure Ulcers": 1},
                           anchors=["Pressure Ulcers"])
    assert pairs == {"pressure ulcer": "Pressure Ulcers"}
    assert report["minted"] == 0


def test_a_canonical_can_be_a_spelling_nobody_wrote():
    # the curator's rule is that the canonical is the singular, so `patients`
    # and `Patients` collapse onto `patient` even though no abstract wrote it
    pairs, report = _pairs({"patients": 1500, "Patients": 80})
    assert set(pairs.values()) == {"patient"}
    assert report["minted"] == 1


def test_a_term_with_no_variant_is_respelled_too():
    # the curator's instruction of 2026-09-26: mint the singular there too. A
    # corpus that only ever wrote `wounds` still gets `wound` as the canonical.
    pairs, report = _pairs({"wounds": 9})
    assert pairs == {"wounds": "wound"}
    assert report["respelled"] == 1 and report["groups"] == 0


def test_a_lone_british_spelling_is_americanised_too():
    pairs, _ = _pairs({"Hospitalisation": 4})
    assert pairs == {"Hospitalisation": "Hospitalization"}


def test_a_lone_term_that_needs_nothing_is_left_alone():
    pairs, report = _pairs({"wound dressing": 9})
    assert pairs == {} and report["respelled"] == 0


def test_respelling_a_lone_term_is_counted_apart_from_the_groups():
    # settling a choice BETWEEN spellings and rewriting the only spelling there
    # is are different acts, and the report says which happened
    pairs, report = _pairs({"wounds": 9, "Wound": 2, "patients": 5})
    assert report["groups"] == 1 and report["respelled"] == 1


def test_a_group_of_one_writes_nothing():
    pairs, _ = _pairs({"wound": 9})
    assert pairs == {}


def test_a_string_only_the_mapping_holds_is_normalised_too():
    """The curator, 2026-09-26: pass 0 goes over the store AND the mapping,
    *just to make sure nothing slipped through*. A canonical no abstract ever
    wrote is still a term, and left un-normalised the next apply puts the old
    spelling back into the store."""
    pairs, _ = _pairs({"unrelated": 1}, others=["Tumours"])
    assert pairs == {"Tumours": "Tumor"}


def test_nothing_a_person_said_about_a_MAPPING_stops_a_respelling():
    """The curator, 2026-09-26: *there is no place for any disagreement with
    the pass 0 renaming.*

    An earlier version skipped any pair a curator had ruled on. On the live
    data that held back 385 pairs, every one of them a pure spelling variant
    — `Aetiology`/`etiology`, `cases`/`case` — because the ruling had been
    about which CONCEPT the term belongs to, and that was read as a veto over
    how the word is written.
    """
    pairs, _ = _pairs({"Aetiology": 9, "aetiologies": 4})
    assert set(pairs) == {"Aetiology", "aetiologies"}
    assert set(pairs.values()) == {"Etiology"}


def test_a_declared_category_keeps_the_spelling_bfo_gives_it():
    """Rule 22. `process` is not elected against, whatever the corpus prefers."""
    pairs, _ = _pairs({"Processes": 40, "process": 1}, declared=["process"])
    assert pairs == {"Processes": "process"}


def test_an_anchor_with_no_store_spelling_writes_nothing():
    pairs, _ = _pairs({"unrelated": 1}, anchors=["Diabetic foot ulcer"])
    assert pairs == {}


# ── the parenthetical guard ──────────────────────────────────────────────────

def test_a_role_class_is_not_merged_into_the_substance():
    """`vitamin (role)` is an ONTOLOGY label: the parenthetical is part of the
    class's official name, and a role class is not the substance."""
    pairs, report = _pairs({"vitamin": 5, "vitamins": 3},
                           anchors=["vitamin (role)"])
    assert "vitamin (role)" not in pairs.values()
    assert report["ontology sense"] == [["vitamin", "vitamin (role)", "vitamins"]]


def test_two_members_declaring_different_categories_are_refused():
    """One fold group whose members declare two different BFO categories is a
    group that should not exist. Electing one of them would put a term under
    the wrong upper class, so it is reported instead."""
    pairs, report = _pairs({"role": 3, "roles": 2},
                           declared={"role": "role", "roles": "disposition"})
    assert pairs == {} and report["declared"] == [["disposition", "role"]]


def test_a_lone_ontology_label_is_not_reported_as_held_back():
    """`CUSA(r) assisted debridement` has no variant to merge with. Listing it
    among the groups a person should look at is noise in a report whose whole
    value is that everything in it needs a decision."""
    _, report = _pairs({"unrelated": 1}, anchors=["CUSA(r) assisted debridement"])
    assert report["ontology sense"] == []


def test_an_abbreviation_gloss_does_not_block_the_group():
    """Most parentheticals are the phrase's own abbreviation, not a sense.

    Refusing every group that held one blocked 84 of 88 groups on the
    2026-09-26 data, `quality of life` among them — seven spellings of it,
    left standing as seven concepts because one of them said `(qol)`.
    """
    pairs, report = _pairs({"quality of life": 40, "Quality of Life": 12,
                            "quality of life (qol)": 1})
    assert report["unsafe"] == [] and report["ontology sense"] == []
    assert pairs["quality of life (qol)"] == "quality of life"


def test_a_group_held_together_by_a_discarded_character_is_not_a_group():
    """`normalize_term` strips all punctuation, so `Na+` meets `NA`. That is a
    defect in the grouping, not a matter of opinion — the only thing that had
    been stopping it was a curator's refusal on record."""
    pairs, report = _pairs({"Na+": 3, "NA": 9})
    assert pairs == {}
    assert report["characters"] == [[["NA"], ["Na+"]]]


def test_a_roman_numeral_phase_is_not_a_spelling_variant():
    pairs, report = _pairs({"Phase I/II": 2, "Phase III": 7})
    assert pairs == {} and report["characters"]


def test_an_acronym_plural_still_merges_with_its_acronym():
    """`DFUs` is an acronym plural only while it still has its capitals. A
    check that lowercased before singularising held 150-odd of these apart —
    `DFU`/`DFUs`, `SSI`/`SSIs`, `ICU`/`ICUs`, `CI`/`CIs`."""
    pairs, report = _pairs({"DFU": 30, "DFUs": 12, "Dfu": 2})
    assert report["characters"] == []
    assert pairs["DFUs"] == "DFU"


def test_an_all_caps_heading_still_merges_with_its_singular():
    """`singular_spelling` leaves all-caps alone (rule 23a), so a check built
    on it would hold `OUTCOME MEASURES` apart from `outcome measure`. The
    corpus is full of structured-abstract headings and they are the same term.
    """
    pairs, report = _pairs({"OUTCOME MEASURES": 3, "outcome measures": 8,
                            "outcome measure": 5})
    assert report["characters"] == []
    assert pairs["OUTCOME MEASURES"] == "outcome measure"


def test_a_non_breaking_hyphen_is_still_a_hyphen():
    """`re\u2011tear` carries U+2011, which is invisible in a diff and is not
    the ASCII hyphen."""
    pairs, report = _pairs({"re\u2011tear": 2, "retears": 6})
    assert report["characters"] == [] and pairs


def test_one_odd_member_does_not_hold_the_rest_of_the_group_back():
    """`patient's` is a different string. `Patients`, `patient` and `patients`
    are not, and used to be stopped from merging by the apostrophe sitting
    next to them — 1,132 groups held back on live data, nearly all of them
    plain plurals caught in the blast radius of one odd member."""
    pairs, report = _pairs({"Patients": 3, "patient": 40, "patients": 12,
                            "patient's": 1})
    assert pairs == {"Patients": "patient", "patients": "patient"}
    assert report["characters"] == [[["Patients", "patient", "patients"],
                                     ["patient's"]]]


def test_two_different_parentheticals_still_refuse_the_group():
    pairs, report = _pairs({"cold (temperature)": 3, "cold (disease)": 2})
    assert pairs == {} and report["unsafe"]


def test_a_singular_and_plural_abbreviation_are_one_gloss():
    """`(prom)` and `(proms)` are the same acronym. Compared raw they read as
    two senses and refused the group; folded, they are one."""
    pairs, report = _pairs({"patient-reported outcome measure (prom)": 2,
                            "patient-reported outcome measures (proms)": 5,
                            "patient-reported outcome measure": 9})
    assert report["unsafe"] == []
    assert len(set(pairs.values())) == 1


def test_matching_parentheticals_still_merge():
    pairs, report = _pairs({"ulcer (DFU)": 3, "Ulcers (DFU)": 1})
    assert report["unsafe"] == [] and pairs


# ── reproducibility ──────────────────────────────────────────────────────────

def test_a_tied_group_chooses_the_same_canonical_every_time():
    # `Derived Indices` and `derived indices`: same frequency, two words each,
    # fifteen characters each. `max()` over a set returned whichever the hash
    # seed iterated first, and a second pass 0 run rewrote 773 such groups.
    freq = {"Derived Indices": 3, "derived indices": 3}
    winners = {tuple(sorted(_pairs(freq)[0].items())) for _ in range(20)}
    assert len(winners) == 1


def test_running_it_twice_changes_nothing_the_second_time():
    """Idempotent, because it runs after extraction and again before matching.

    The store is renamed in place, so the second run sees the spellings the
    first one chose: it must find nothing left to do.
    """
    freq = {"wound": 9, "Wounds": 2, "wounds": 4, "patients": 5, "Patients": 1}
    first, _ = _pairs(freq)
    renamed: dict[str, int] = {}
    for term, n in freq.items():
        renamed[first.get(term, term)] = renamed.get(first.get(term, term), 0) + n
    second, _ = _pairs(renamed)
    assert second == {}


def test_a_tied_group_chooses_the_same_canonical_on_a_fresh_interpreter():
    # Same as the tie test above, but the point here is the ORDER of the input:
    # a dict iterating the other way must not change the winner.
    freq = {"Derived Indices": 3, "derived indices": 3}
    flipped = dict(reversed(list(freq.items())))
    assert _pairs(freq)[0] == _pairs(flipped)[0]


@pytest.mark.xfail(reason="known gap: a title-cased acronym plural does not "
                          "fold onto the acronym. `singularize('dfus')` is "
                          "'dfus' -- the stem is not a word, so no suffix rule "
                          "recognises it, and `Dfus` cannot reach `DFU`. The "
                          "extractor title-cases acronyms, so the corpus holds "
                          "both spellings.", strict=True)
def test_a_title_cased_acronym_plural_folds_onto_the_acronym():
    assert normalise("Dfus").key == normalise("DFUs").key


# ── what the next build must not undo ────────────────────────────────────────

def test_a_minted_canonical_outranks_the_spelling_it_replaced():
    """The clustering picks a canonical by `canonical_rank`, which reads
    frequency. A minted canonical has no mentions of its own -- no abstract
    wrote `wound` -- so unless it inherits the frequency of everything pointing
    at it, the next build re-canonicalises onto `wounds` and undoes pass 0.
    """
    from wound_ontology.mappers.term_mapper import canonical_rank
    freq = {"wounds": 40, "Wounds": 5}
    inherited = sum(freq.values())
    assert canonical_rank("wound", frequencies={**freq, "wound": inherited}) > \
        canonical_rank("wounds", frequencies={**freq, "wound": inherited})
