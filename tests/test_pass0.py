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
from wound_ontology.utils.normalise import canonical_vocabulary, normalise, sentence_case

# Since 2026-10-24 every name is in sentence case (`sentence_case`); the
# expectations below are written as the rules leave the words, and the case
# step is applied to them here rather than spelled into every row.


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
    assert normalise(label).name == sentence_case(expected)


@pytest.mark.parametrize("label,expected", [
    ("lower limb wound", "lower extremity wound"),
    ("LOWER LIMBS", "LOWER EXTREMITIES"),
    ("Bioengineering strategy", "Bioengineering therapy"),
    ("prevention strategies", "prophylaxis"),
    ("fungating wound management", "fungating wound care"),
    ("WOUND-MANAGEMENT STRATEGIES", "WOUND-CARE APPROACHES"),
])
def test_the_curators_preferred_vocabulary(label, expected):
    assert normalise(label).name == sentence_case(expected)


@pytest.mark.parametrize("label,expected", [
    ("dressing technique", "dressing method"),
    ("cutaneous ulcer", "skin wound"),
    ("follow-up evaluation", "follow-up assessment"),
    ("susceptibility testing", "susceptibility test"),
    ("inflammation biomarker", "inflammatory biomarker"),
    ("cellular proliferation", "cell proliferation"),
    ("diabetes foot ulcer", "diabetic foot ulcer"),
    ("infectious process", "infection process"),
    ("surgery duration", "surgical duration"),
    ("biopsy specimen", "biopsy sample"),
    ("CRP value", "CRP level"),
    ("histopathologic alteration", "histopathological change"),
    ("antimicrobial action", "antimicrobial activity"),
    ("demographic feature", "demographic characteristic"),
    ("full debridement", "complete debridement"),
    ("antibiotic usage", "antibiotic use"),
    ("bony consolidation", "bone consolidation"),
    ("bypass operation", "bypass surgery"),
    ("microbiological confirmation", "microbial confirmation"),
    ("pharmacologic agent", "pharmacological agent"),
    ("physiologic response", "physiological response"),
    ("previous amputation", "prior amputation"),
    ("dermatologic complication", "dermatological complication"),
    ("radiologic finding", "radiological finding"),
    ("oncologic outcome", "oncological outcome"),
    ("biologic therapy", "biological therapy"),
    ("Biologic agent", "Biological agent"),
    ("histopathologic pattern", "histopathological pattern"),
    ("numeric rating scale", "numerical rating scale"),
    ("preventative treatment", "preventive treatment"),
    ("post-surgical recovery", "postoperative recovery"),
])
def test_the_thirty_approved_preferred_names(label, expected):
    assert normalise(label).name == sentence_case(expected)


@pytest.mark.parametrize("label", [
    "inflammation in wound",
    "cellular and humoral immunity",
    "diabetes-related wound",
    "infectious or inflammatory disorder",   # "disease" -> "disorder" since 2026-10-02
    "surgery after injury",
    "bony and soft tissue",
])
def test_a_modifier_rule_does_not_rewrite_a_head_or_relation(label):
    assert normalise(label).name == sentence_case(label)


@pytest.mark.parametrize("label,expected", [
    ("Compound Muscle Action Potentials", "Compound Muscle Action Potential"),
    ("action potential", "action potential"),
    ("action-potential duration", "action-potential duration"),
    ("ACTION POTENTIAL", "ACTION POTENTIAL"),
    # the exemption is the phrase, not the word
    ("antimicrobial action and action potential",
     "antimicrobial activity and action potential"),
])
def test_action_potential_is_a_fixed_term(label, expected):
    """Curator, 2026-09-27: `action -> activity` must not reach into
    electrophysiology's `action potential`."""
    assert normalise(label).name == sentence_case(expected)


@pytest.mark.parametrize("preferred,variant", [
    ("chronic lower extremity wound", "chronic lower-limb wound"),
    ("bioengineering therapy", "bioengineering strategy"),
    ("fungating wound care", "fungating wound management"),
    ("dressing method", "dressing technique"),
    ("skin ulcer", "cutaneous ulcer"),
    ("inflammatory biomarker", "inflammation biomarker"),
    ("cell proliferation", "cellular proliferation"),
    ("diabetic foot ulcer", "diabetes foot ulcer"),
    ("postoperative recovery", "post-surgical recovery"),
])
def test_preferred_vocabulary_shares_both_group_keys(preferred, variant):
    assert normalise(preferred).key == normalise(variant).key
    assert normalise(preferred).strict == normalise(variant).strict


def test_preferred_vocabulary_wins_even_when_the_old_name_is_more_frequent():
    pairs, _ = _pairs({"chronic lower-limb wound": 20,
                       "chronic lower extremity wound": 1,
                       "bioengineering strategy": 12,
                       "bioengineering approach": 1,
                       "fungating wound management": 21,
                       "fungating wound care": 1})
    assert pairs["chronic lower-limb wound"] == "Chronic lower-extremity wound"
    assert pairs["bioengineering strategy"] == "Bioengineering therapy"
    assert pairs["fungating wound management"] == "Fungating wound care"


def test_preferred_vocabulary_does_not_rewrite_unrelated_management():
    assert normalise("pain management strategy").name == "Pain management approach"
    assert normalise("case management").name == "Case management"
    assert normalise("limbic system").name == "Limbic system"


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
    assert pairs == {"intraabdominal complication": "Intra-abdominal complication",
                     "intra-abdominal complication": "Intra-abdominal complication"}


def test_the_language_breaks_a_seam_tie_the_corpus_cannot():
    """Closing the seam handed the election a question it could not answer.

    Both spellings appear in one abstract, so `canonical_rank` fell through
    to WORD COUNT -- and `Cumberl and Ankle Instability Tool` has one word
    more than the instrument's actual name. Pass 0 was about to rename the
    instrument onto the typo.
    """
    pairs, _ = _pairs({"Cumberland Ankle Instability Tool": 1,
                       "Cumberl and Ankle Instability Tool": 1})
    assert set(pairs.values()) == {"Cumberland ankle instability tool"}


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
    assert set(pairs.values()) == {"Antibiofilm"}


# ── what it writes ───────────────────────────────────────────────────────────

def test_every_variant_maps_onto_one_spelling():
    pairs, _ = _pairs({"wound": 9, "Wounds": 2, "wounds": 4})
    assert pairs == {"Wounds": "Wound", "wounds": "Wound", "wound": "Wound"}


def test_the_most_frequent_spelling_wins():
    pairs, _ = _pairs({"Pressure Ulcer": 1, "pressure ulcers": 20})
    assert set(pairs.values()) == {"Pressure ulcer"}


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


def test_two_ontology_labels_are_both_immutable():
    """Imported ontologies can give the same label different case.

    Neither source label lives in the mutable store, so reporting one as a
    rename creates permanent phantom work on every fixed-point check.
    """
    pairs, report = _pairs({}, anchors=["Abscess", "abscess"])
    assert pairs == {}
    assert report["to write"] == 0


def test_a_canonical_can_be_a_spelling_nobody_wrote():
    # the curator's rule is that the canonical is the singular, so `patients`
    # and `Patients` collapse onto `patient` even though no abstract wrote it
    pairs, report = _pairs({"patients": 1500, "Patients": 80})
    assert set(pairs.values()) == {"Patient"}
    assert report["minted"] == 1


def test_a_term_with_no_variant_is_respelled_too():
    # the curator's instruction of 2026-09-26: mint the singular there too. A
    # corpus that only ever wrote `wounds` still gets `wound` as the canonical.
    pairs, report = _pairs({"wounds": 9})
    assert pairs == {"wounds": "Wound"}
    assert report["respelled"] == 1 and report["groups"] == 0


def test_a_lone_british_spelling_is_americanised_too():
    pairs, _ = _pairs({"Hospitalisation": 4})
    assert pairs == {"Hospitalisation": "Hospitalization"}


def test_a_lone_term_that_needs_nothing_is_left_alone():
    pairs, report = _pairs({"Wound dressing": 9})
    assert pairs == {} and report["respelled"] == 0


def test_respelling_a_lone_term_is_counted_apart_from_the_groups():
    # settling a choice BETWEEN spellings and rewriting the only spelling there
    # is are different acts, and the report says which happened
    pairs, report = _pairs({"wounds": 9, "Wound": 2, "patients": 5})
    assert report["groups"] == 1 and report["respelled"] == 1


def test_a_group_of_one_writes_nothing():
    pairs, _ = _pairs({"Wound": 9})
    assert pairs == {}


def test_a_string_only_the_mapping_holds_is_normalised_too():
    """The curator, 2026-09-26: pass 0 goes over the store AND the mapping,
    *just to make sure nothing slipped through*. A canonical no abstract ever
    wrote is still a term, and left un-normalised the next apply puts the old
    spelling back into the store."""
    pairs, _ = _pairs({"Unrelated": 1}, others=["Tumours"])
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
    pairs, _ = _pairs({"Unrelated": 1}, anchors=["Diabetic foot ulcer"])
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
    assert pairs["quality of life (qol)"] == "Quality of life"


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
    assert pairs["OUTCOME MEASURES"] == "Outcome measure"


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
    assert {k: v for k, v in pairs.items() if k != "patient's"} == \
        {"Patients": "Patient", "patients": "Patient", "patient": "Patient"}
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


@pytest.mark.parametrize("label, expected", [
    # -ical is the preferred form (curator, 2026-09-28), and already-preferred
    # names are left alone -- `biological` must not become `biologicalal`.
    ("pharmacological agent", "pharmacological agent"),
    ("biological therapy", "biological therapy"),
    ("biological process", "biological process"),
    ("BIOLOGIC", "BIOLOGICAL"),
])
def test_ical_is_the_preferred_form(label, expected):
    assert normalise(label).name == sentence_case(expected)


def test_biologics_in_the_plural_become_biologicals():
    assert canonical_vocabulary("regenerative biologics") == "regenerative biologicals"


def test_a_product_name_keeps_its_biologic():
    """`XCM BIOLOGIC Tissue Matrix` is a brand, not the adjective."""
    assert canonical_vocabulary("XCM BIOLOGIC Tissue Matrix") == "XCM BIOLOGIC Tissue Matrix"


@pytest.mark.parametrize("label, expected", [
    # Curator, 2026-09-28: VAC and vacuum therapy are negative pressure wound
    # therapy. The abbreviations are expanded inside compounds as well, so a
    # `VAC dressing` and an `NPWT dressing` are one name.
    ("NPWT", "negative pressure wound therapy"),
    ("VAC", "negative pressure wound therapy"),
    ("V.A.C. therapy", "negative pressure wound therapy"),
    ("vacuum therapy", "negative pressure wound therapy"),
    ("Vacuum therapy", "Negative pressure wound therapy"),
    ("vacuum-assisted closure", "negative pressure wound therapy"),
    ("vacuum assisted closure therapy", "negative pressure wound therapy"),
    ("VAC dressing", "negative pressure wound therapy dressing"),
    ("incisional NPWT", "incisional negative pressure wound therapy"),
    ("NPWT therapy", "negative pressure wound therapy"),
    ("negative pressure therapy", "negative pressure wound therapy"),
    ("Negative-pressure treatment", "Negative pressure wound therapy"),
    ("negative pressure wound therapy", "negative pressure wound therapy"),
])
def test_vac_and_vacuum_therapy_are_npwt(label, expected):
    assert canonical_vocabulary(label) == expected


@pytest.mark.parametrize("label", [
    "endoscopic vacuum-assisted closure",     # a gastrointestinal leak procedure
    "Endoluminal vacuum therapy",
    "vacuum",                                 # the physical condition alone
    "vacuum sealing drainage",                # not ruled on
])
def test_what_is_not_npwt_keeps_its_name(label):
    assert canonical_vocabulary(label) == label


@pytest.mark.parametrize("label, expected", [
    # Curator, 2026-09-28: a treatment approach, strategy or intervention is a therapy.
    ("biomaterial-based approach", "biomaterial-based therapy"),
    ("regenerative strategies", "regenerative therapy"),
    ("surgical intervention", "surgical therapy"),
    ("Interventions", "Therapy"),
    ("therapeutic strategies", "therapy"),
    ("treatment approach", "therapy"),
    ("novel treatment strategy", "therapy"),         # adjective stripped too
    ("prevention strategies", "prophylaxis"),
    ("preventive interventions", "prophylaxis"),
    # ...and where the word means something else, it stays.
    ("search strategy", "search approach"),            # rule 48 still applies
    ("coping strategies", "coping approach"),
    ("GRADE approach", "GRADE approach"),
    ("surgical approach", "surgical approach"),
    ("minimally invasive approach", "minimally invasive approach"),
    ("post-intervention", "post-intervention"),
    ("pain management strategy", "pain management approach"),
    ("intervention group", "intervention group"),
    ("diagnostic strategies", "diagnostic approach"),
])
def test_a_treatment_approach_is_a_therapy(label, expected):
    assert normalise(label).name == sentence_case(expected)


@pytest.mark.parametrize("label", [
    "diabetes mellitus", "Diabetes Mellitus type 2", "gestational diabetes mellitus",
    "central diabetes insipidus"])
def test_diabetes_mellitus_is_a_name_not_a_modifier(label):
    """Rule 49's `diabetes -> diabetic` is for `diabetes foot ulcer`; applied to
    `diabetes mellitus` it wrote `diabetic mellitus` (28 names, 259 mentions)."""
    assert canonical_vocabulary(label) == label


@pytest.mark.parametrize("label, expected", [
    # Curator, 2026-09-28: leading grades and praise are not part of the name.
    ("massive rotator cuff tears", "rotator cuff tear"),
    ("Severe Sepsis", "Sepsis"),
    ("severe, extensive burns", "burn"),
    ("advanced wound care", "wound care"),
    ("key predictors", "predictor"),
    # ...never a one-word name, never before a function word,
    ("mild", "mild"),
    ("standard of care", "standard of care"),
    # never a curator's exception or a fixed name,
    ("major amputation", "major amputation"),
    ("Large wound", "Large wound"),
    ("moderate to severe pain", "moderate to severe pain"),
    ("standard deviation", "standard deviation"),
    ("multiple sclerosis", "multiple sclerosis"),
    # and never a word the curator left alone.
    ("small wounds", "small wound"),
    ("giant cell", "giant cell"),
])
def test_a_leading_grade_or_praise_is_stripped(label, expected):
    assert normalise(label).name == sentence_case(expected)


@pytest.mark.parametrize("label", ["blunt trauma", "head trauma", "trauma"])
def test_trauma_is_not_renamed_injury(label):
    """Rule 49's `trauma -> injury` was withdrawn by the curator, 2026-09-28."""
    assert normalise(label).name == sentence_case(label)


# ── 2026-10-02: pressure ulcer, and disorder for its five synonyms ──────────

@pytest.mark.parametrize("label, expected", [
    ("sacral pressure injury", "sacral pressure ulcer"),
    ("Pressure injuries", "Pressure ulcers"),
    ("hospital-acquired pressure injury", "hospital-acquired pressure ulcer"),
    ("pressure injury risk assessment", "pressure ulcer risk assessment"),
])
def test_pressure_injury_is_pressure_ulcer_inside_every_name(label, expected):
    assert canonical_vocabulary(label) == expected


@pytest.mark.parametrize("label, expected", [
    ("skin disease", "skin disorder"),
    ("skin dysfunction", "skin disorder"),
    ("skin pathology", "skin disorder"),
    ("skin condition", "skin disorder"),
    ("respiratory illness", "respiratory disorder"),
    ("cardiovascular diseases", "cardiovascular disorders"),
    ("chronic illnesses", "chronic disorders"),
    ("disease-free survival", "disorder-free survival"),
])
def test_disorder_wins_over_its_synonyms(label, expected):
    assert canonical_vocabulary(label) == expected


@pytest.mark.parametrize("label", [
    "wound condition", "hypoxic condition", "culture condition",          # a state
    "Crohn's disease", "Buerger disease", "Paget's disease",               # eponyms
    "multiple organ dysfunction syndrome", "critical illness polyneuropathy",
    "illness perception", "surgical pathology", "pathology report",        # fixed / discipline
])
def test_what_is_not_a_disorder_synonym_keeps_its_word(label):
    assert canonical_vocabulary(label) == label


def test_variants_share_one_key():
    keys = {normalise(t).key for t in ("skin disease", "skin condition", "skin pathology",
                                        "skin dysfunction", "Skin disorder")}
    assert len(keys) == 1


@pytest.mark.parametrize("label", [
    "Centers for Disease Control and Prevention",
    "Global Burden of Disease 2021",
    "International Classification of Diseases, 10th Revision code",
    "Infectious Diseases Society of America",
    "National Institute of Diabetes and Digestive and Kidney Diseases",
    "Ocular Surface Disease Index",
    "classification of Periodontal and Peri-Implant Diseases and Conditions",
    "biological disease-modifying antirheumatic drug",
    "recent coronavirus disease 2019 infection",
])
def test_a_proper_name_keeps_its_disease(label):
    # only the disease word is under test (`infectious -> infection` is an
    # older modifier rule that also reaches into the society's name)
    out = canonical_vocabulary(label)
    assert "isease" in out and "isorder" not in out


# ── 2026-10-04: leg is lower extremity; ulceration is ulcer; ulcer and wound are one term ──

@pytest.mark.parametrize("label,expected", [
    ("chronic leg ulcer", "chronic lower extremity wound"),
    ("Chronic Lower Leg Wound", "Chronic Lower Extremity Wound"),
    ("recurrent lower-leg ulcers", "recurrent lower-extremity wounds"),
    ("both legs", "both lower extremities"),
    ("venous leg ulceration", "venous lower extremity wound"),
    # fixed names and the thigh stay as written
    ("upper leg", "upper leg"),
    ("single-leg hop", "single-leg hop"),
    ("time to straight leg raise", "time to straight leg raise"),
    ("Face, Legs, Activity, Cry, Consolability score", "Face, Legs, Activity, Cry, Consolability score"),
    ("Leg Ulcer Measurement Tool", "Leg Ulcer Measurement Tool"),
    ("community leg club", "community leg club"),
    ("colleague", "colleague"),
])
def test_leg_is_lower_extremity_inside_names(label, expected):
    from wound_ontology.utils.normalise import canonical_vocabulary
    assert canonical_vocabulary(label) == expected


@pytest.mark.parametrize("a,b", [
    ("Chronic Leg Ulcer", "Chronic Lower-Extremity Wound"),
    ("Diabetic foot ulcer", "Diabetic Foot Wound"),
    ("Hard-To-Heal Ulcer", "hard-to-heal wounds"),
])
def test_ulcer_and_wound_share_a_key(a, b):
    from wound_ontology.utils.normalise import normalise
    assert normalise(a).key == normalise(b).key
    assert normalise(a).strict == normalise(b).strict


def test_a_lone_ulcer_keeps_its_word():
    """The equivalence groups spellings; it never renames one."""
    from wound_ontology.utils.normalise import canonical_vocabulary
    assert canonical_vocabulary("gastric ulcer") == "gastric ulcer"


def test_pass0_elects_the_ontology_label_across_ulcer_and_wound():
    from wound_ontology.mappers.pass0 import pass0_renames
    renames, _ = pass0_renames({"Diabetic Foot Wound": 12, "diabetic foot ulcer": 595},
                               anchors={"Diabetic foot ulcer"})
    assert renames["Diabetic Foot Wound"] == "Diabetic foot ulcer"
    renames, _ = pass0_renames({"chronic leg ulcer": 11, "Chronic Leg Wound": 6,
                                "Chronic Lower Extremity Wound": 10, "Chronic Lower-Extremity Ulcer": 4},
                               anchors=set())
    assert len(set(renames.values())) == 1          # one term
    assert "leg" not in next(iter(renames.values())).lower()
