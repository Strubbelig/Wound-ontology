"""Three rules the mapping's canonicals have to follow, and could not.

1. THE ONTOLOGY'S OWN LABEL WINS (curator, 2026-09-23). 22 live entries
   canonicalised a class under a spelling the class does not use --
   `Necrosis Process -> necrosis` where WONT spells it `Necrosis`. Downstream
   that mints a twin of a class that already exists.

2. THE CATEGORY GUARD HAD NEVER SEEN THE CASE IT WAS WRITTEN FOR. It is
   consulted only for ANCHORS, and anchors are the ontology labels that are NOT
   also store terms -- so it went quiet exactly when a class label was common
   enough to be extracted. `Necrosis Process` [process] -> `Necrosis`
   [material entity] went through unchecked; measured, 5 such merges did.
   Rule 1 is what fixes it: re-spelling the canonical to the label turns a
   store-to-store merge into the anchor mapping it always was.

3. A BLOCKED CANONICAL IS REPORTED, NOT REPAIRED. `patients` is not on the
   methodology blocklist, `patient` is, and rule 23 makes the canonical
   singular -- so the mapping renames the survivor back onto the blocked name:
   462 store names arrived that way carrying 7,201 mentions, all queued for
   deletion by `run_clean_store` together with whatever had merged into them.
   Withdrawing the entry is not the fix (the variant would stand as its own
   concept and the noise leaks back in under a plural); whether the list or the
   merge is wrong is a `review_lists` decision, so the pass reports and leaves
   the mapping alone.
"""
import pytest

from conftest import memory_mapper


def _mapper(data):
    """The real TermMapping over an in-memory file — see tests/conftest.py."""
    return memory_mapper(data)


LABELS = {"necrosis": "Necrosis", "surgical debridement": "Surgical debridement"}


def test_the_ontology_spelling_replaces_the_store_spelling():
    m = _mapper({"debridement surgery": "surgical debridement"})
    rep = m.enforce_canonical_policy(label_spellings=LABELS)
    assert rep["respelled"] == 1
    assert m.mapping == {"debridement surgery": "Surgical debridement"}


def test_a_canonical_that_is_not_a_label_is_left_alone():
    m = _mapper({"wounded area": "wound area"})
    rep = m.enforce_canonical_policy(label_spellings=LABELS)
    assert rep["respelled"] == 0
    assert m.mapping == {"wounded area": "wound area"}


def test_re_spelling_puts_the_merge_in_front_of_the_category_guard():
    """The whole point of rule 1: a store-spelled label hid the identity claim
    from the guard, and `Necrosis Process -> Necrosis` is the claim it exists to
    refuse."""
    seen = []

    def accept(term, canonical):
        seen.append((term, canonical))
        return canonical != "Necrosis"

    m = _mapper({"Necrosis Process": "necrosis"})
    rep = m.enforce_canonical_policy(label_spellings=LABELS, accept_mapping=accept)
    assert ("Necrosis Process", "Necrosis") in seen, "the guard was never asked"
    assert rep["refused"] == 1
    assert m.mapping == {}


def test_an_accepted_mapping_onto_a_label_still_goes_through():
    m = _mapper({"necrotic tissue": "necrosis"})
    m.enforce_canonical_policy(label_spellings=LABELS, accept_mapping=lambda t, c: True)
    assert m.mapping == {"necrotic tissue": "Necrosis"}


def test_a_blocked_canonical_is_reported_and_the_mapping_left_alone():
    """`patients` is not on the list and `patient` is; the singular rule walks
    the survivor back onto the blocked name. Withdrawing would leave `Patients`
    standing as its own concept, so the pass reports instead of acting."""
    m = _mapper({"Patients": "patient", "wounds": "wound"})
    rep = m.enforce_canonical_policy(blocked={"patient"})
    assert rep["blocked_canonical"] == 1
    assert rep["blocked_entries"] == [("Patients", "patient")]
    assert m.mapping == {"Patients": "patient", "wounds": "wound"}


def test_the_block_is_case_insensitive_on_both_sides():
    """The extraction filter lowercases the NAME and relies on the list being
    lowercase throughout. A capitalised entry would silently stop blocking, so
    this side folds too."""
    m = _mapper({"Patients": "Patient"})
    assert m.enforce_canonical_policy(blocked={"patient"})["blocked_canonical"] == 1
    m2 = _mapper({"follow-ups": "follow-up"})
    assert m2.enforce_canonical_policy(blocked={"Follow-Up"})["blocked_canonical"] == 1


def test_a_policy_that_changes_nothing_says_so(capsys):
    m = _mapper({"wounds": "Wound"})
    rep = m.enforce_canonical_policy(label_spellings={}, blocked=set())
    assert rep["respelled"] == rep["refused"] == rep["blocked_canonical"] == 0
    assert "already follows the policy" in capsys.readouterr().out


def test_an_entry_that_re_spelling_turns_into_an_identity_is_dropped():
    """`Wound -> wound` re-spells to `Wound -> Wound`: a term mapped onto its own
    name. That is an identity for rule 19 to remove, not a refusal, and the guard
    must not be asked about it."""
    asked = []
    m = _mapper({"Wound": "wound"})
    rep = m.enforce_canonical_policy(
        label_spellings={"wound": "Wound"},
        accept_mapping=lambda t, c: asked.append((t, c)) or False,
    )
    assert rep["identities"] == 1 and rep["refused"] == 0
    assert asked == [], "the guard was asked about a term mapped onto itself"
    assert m.mapping == {}


def test_dry_run_writes_nothing():
    m = _mapper({"debridement surgery": "surgical debridement"})
    rep = m.enforce_canonical_policy(label_spellings=LABELS, dry_run=True)
    assert rep["respelled"] == 1
    assert m.mapping == {"debridement surgery": "surgical debridement"}


def test_a_write_that_does_not_land_raises():
    m = _mapper({"debridement surgery": "surgical debridement"})
    m._term_mapping.add_batch = lambda entries, metadata_batch=None: []   # the write goes nowhere
    with pytest.raises(RuntimeError, match="did not land"):
        m.enforce_canonical_policy(label_spellings=LABELS)


def test_only_a_content_difference_is_put_to_the_guard():
    """`Pressure ulcers -> Pressure ulcer` is an inflection of the class's own
    label, not a claim about what kind of thing it is. Asking the guard about it
    refuses good entries whenever the store's typing of the plural happens to be
    contradictory — which is exactly what happened: 22 refusals, 19 of them
    inflections."""
    asked = []

    def accept(term, canonical):
        asked.append((term, canonical))
        return False                       # a guard that refuses everything

    m = _mapper({"Pressure ulcers": "pressure ulcer"})
    rep = m.enforce_canonical_policy(
        label_spellings={"pressure ulcer": "Pressure ulcer"}, accept_mapping=accept)
    assert asked == [], "the guard was asked about an inflection of the label"
    assert rep["refused"] == 0
    assert m.mapping == {"Pressure ulcers": "Pressure ulcer"}

    # ...while a real word changing is still a claim, and is still checked
    m2 = _mapper({"Necrosis Process": "necrosis"})
    rep2 = m2.enforce_canonical_policy(
        label_spellings={"necrosis": "Necrosis"}, accept_mapping=accept)
    assert rep2["refused"] == 1 and m2.mapping == {}
