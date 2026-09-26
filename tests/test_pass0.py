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

from wound_ontology.mappers.pass0 import group_key, normalised_label, pass0_pairs


def _pairs(freq, anchors=(), mapping=None, curated=()):
    return pass0_pairs(dict(freq), set(anchors), dict(mapping or {}),
                       is_curated=lambda t, c: (t, c) in set(curated))


# ── the four deterministic steps ─────────────────────────────────────────────

@pytest.mark.parametrize("label,expected", [
    ("Diabetic Foot Ulcers", "Diabetic Foot Ulcer"),      # singular
    ("Necrotising fasciitis", "Necrotizing fasciitis"),   # british
    ("Caesarean sections", "Cesarean section"),           # both
    ("Statistical Analyses", "Statistical Analysis"),     # singular BEFORE british
    ("wound dressing", "wound dressing"),                 # nothing to do
])
def test_the_preferred_spelling(label, expected):
    assert normalised_label(label) == expected


@pytest.mark.parametrize("a,b", [
    ("Surgical Site Infection", "surgical site infections"),
    ("split-thickness skin graft", "Split Thickness Skin Grafts"),
    ("chronic limb-threatening ischaemia", "Chronic Limb-Threatening Ischemia"),
    ("Caesarean section", "cesarean sections"),
])
def test_two_spellings_of_one_thing_share_a_key(a, b):
    assert group_key(a) == group_key(b)


def test_two_different_things_do_not_share_a_key():
    assert group_key("venous leg ulcer") != group_key("arterial leg ulcer")


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


def test_a_pair_already_mapped_that_way_is_not_rewritten():
    pairs, report = _pairs({"wound": 9, "wounds": 4}, mapping={"wounds": "wound"})
    assert pairs == {} and report["already"] == 1


def test_a_pair_the_curator_ruled_on_is_left_alone():
    pairs, report = _pairs({"wound": 9, "wounds": 4},
                           curated=[("wounds", "wound")])
    assert pairs == {} and report["curated"] == [("wounds", None)]


def test_an_anchor_with_no_store_spelling_writes_nothing():
    pairs, _ = _pairs({"unrelated": 1}, anchors=["Diabetic foot ulcer"])
    assert pairs == {}


# ── the parenthetical guard ──────────────────────────────────────────────────

def test_a_role_class_is_not_merged_into_the_substance():
    pairs, report = _pairs({"vitamin": 5, "vitamins": 3, "vitamin (role)": 1})
    assert pairs == {}
    assert report["unsafe"] == [["vitamin", "vitamin (role)", "vitamins"]]


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


def test_running_it_twice_writes_nothing_the_second_time():
    freq = {"wound": 9, "Wounds": 2, "wounds": 4, "patients": 5, "Patients": 1}
    first, _ = _pairs(freq)
    second, report = _pairs(freq, mapping=first)
    assert second == {}
    assert report["already"] == len(first)


# ── never leave a chain or a loop behind ─────────────────────────────────────

def test_the_target_is_followed_to_its_end():
    # The best spelling in the group is already mapped onward by a curator.
    # Writing `member -> that spelling` makes a chain, and `normalize` follows
    # exactly one hop, so the merge half-lands.
    pairs, _ = _pairs({"Wounds": 2, "wounds": 9}, mapping={"wound": "Wound"})
    assert pairs == {"Wounds": "Wound", "wounds": "Wound"}


@pytest.mark.xfail(reason="known gap: a title-cased acronym plural does not "
                          "fold onto the acronym. `singularize('dfus')` is "
                          "'dfus' -- the stem is not a word, so no suffix rule "
                          "recognises it, and `Dfus` cannot reach `DFU`. The "
                          "extractor title-cases acronyms, so the corpus holds "
                          "both spellings.", strict=True)
def test_a_title_cased_acronym_plural_folds_onto_the_acronym():
    assert group_key("Dfus") == group_key("DFUs")


def test_a_chain_two_deep_is_followed_all_the_way():
    pairs, _ = _pairs({"a term": 1, "A Term": 9},
                      mapping={"A Term": "b term", "b term": "c term"})
    assert set(pairs.values()) == {"c term"}
    assert set(pairs) == {"a term", "A Term"}


def test_a_group_whose_target_is_inside_a_loop_is_refused_and_named():
    # `_final` only returns a mapped term when it walked into a loop, and there
    # were 52 of those in the live data. Merging into a loop puts the merge
    # somewhere `resolve_chains` is about to break.
    pairs, report = _pairs({"Wounds": 4}, mapping={"wound": "Wound",
                                                   "Wound": "wound"})
    assert pairs == {}
    assert report["cyclic"]


def test_a_loop_already_in_the_data_does_not_hang():
    pairs, _ = _pairs({"a": 1, "A": 1}, mapping={"a": "A", "A": "a"})
    assert isinstance(pairs, dict)


def test_pass0_never_writes_a_chain():
    freq = {"Dfus": 2, "DFUs": 9, "Ssis": 1, "SSIs": 5}
    pairs, _ = _pairs(freq, mapping={"DFUs": "DFU", "SSIs": "SSI"})
    combined = {**{"DFUs": "DFU", "SSIs": "SSI"}, **pairs}
    assert not [t for t, c in combined.items() if c in combined]
