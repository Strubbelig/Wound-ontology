"""One build writes a forest; the FILE is not one build.

`build_from_embeddings` asserts that every canonical maps to itself, so no
single run can produce `A -> B -> C`. The mapping file accumulates across runs,
and a term this build makes a canonical may be a term an earlier build already
mapped somewhere else. Measured on the 2026-09-21 build: 735 chains whose second
hop really renames and 408 two-cycles that are not case variants.

`ConceptStore.normalize` follows exactly one hop, so both shapes fail without
saying anything:

  * a chain half-lands the merge — `thermal burns -> thermal burn` next to
    `thermal burn -> thermal burn injuries` leaves the store holding
    `Thermal Burn` AND `Thermal Burn Injuries`;
  * a cycle undoes itself — `CFU -> CFUs` with `CFUs -> CFU` renames each onto
    the other and nothing merges.

That is the standing no-silent-failure rule, so resolve_chains verifies its own
write and raises rather than leaving the file in that state.
"""
import pytest

from conftest import memory_mapper
from wound_ontology.mappers.term_mapper import canonical_rank


def _mapper(data):
    """The real TermMapping over an in-memory file — see tests/conftest.py."""
    return memory_mapper(data)


def test_a_chain_collapses_onto_its_terminal():
    m = _mapper({"thermal burns": "thermal burn",
                 "thermal burn": "thermal burn injuries"})
    rep = m.resolve_chains()
    assert rep["repointed"] == 1
    assert m.mapping == {"thermal burns": "thermal burn injuries",
                         "thermal burn": "thermal burn injuries"}


def test_a_long_chain_collapses_in_one_pass():
    m = _mapper({"A": "B", "B": "C", "C": "D"})
    m.resolve_chains()
    assert m.mapping == {"A": "D", "B": "D", "C": "D"}


def test_a_cycle_is_broken_in_favour_of_the_more_frequent_term():
    """Both spellings survived a cycle because each was renamed onto the other."""
    m = _mapper({"CFU": "CFUs", "CFUs": "CFU"})
    rep = m.resolve_chains(frequencies={"CFU": 1, "CFUs": 2})
    assert rep["cycles"] == 1
    assert m.mapping == {"CFU": "CFUs"}


def test_the_cycle_winner_is_the_anchor_however_rare_it_is():
    """An ontology label outranks any store term — the same rule that picks a
    cluster's canonical, so the winner is the one the build itself would pick."""
    m = _mapper({"Skin wound": "cutaneous wounds", "cutaneous wounds": "Skin wound"})
    m.resolve_chains(frequencies={"cutaneous wounds": 99, "Skin wound": 0},
                     anchors={"Skin wound"})
    assert m.mapping == {"cutaneous wounds": "Skin wound"}


def test_a_chain_into_a_cycle_lands_on_the_cycle_winner():
    m = _mapper({"A": "X", "X": "Y", "Y": "X"})
    m.resolve_chains(frequencies={"X": 1, "Y": 5})
    assert m.mapping == {"A": "Y", "X": "Y"}


def test_a_chain_ending_at_a_refused_anchor_is_withdrawn_not_walked():
    """The category guard refused `wound dehiscence -> Wound dehiscence process`
    for a reason. Resolution must not deliver through the back door what the
    guard turned away at the front — and must not leave the term on a name this
    same pass renames away either, so the entry goes."""
    m = _mapper({"wound dehiscence": "dehiscence",
                 "dehiscence": "Wound dehiscence process"})
    rep = m.resolve_chains(
        anchors={"Wound dehiscence process"},
        accept_mapping=lambda t, c: t != "wound dehiscence",
    )
    assert rep["withdrawn"] == 1
    assert m.mapping == {"dehiscence": "Wound dehiscence process"}


def test_a_forest_is_left_alone():
    m = _mapper({"wounds": "Wound", "wound": "Wound"})
    rep = m.resolve_chains()
    assert rep == {"cycles": 0, "repointed": 0, "dropped": 0, "withdrawn": 0}
    assert m.mapping == {"wounds": "Wound", "wound": "Wound"}


def test_dry_run_reports_without_writing():
    m = _mapper({"A": "B", "B": "C"})
    rep = m.resolve_chains(dry_run=True)
    assert rep["repointed"] == 1
    assert m.mapping == {"A": "B", "B": "C"}


def test_a_write_that_does_not_land_raises():
    """The verification is the point: a resolution that did not reach a fixed
    point leaves exactly the silent half-merge the method exists to end."""
    def _deafen(mapper):
        mapper._term_mapping.add_batch = lambda e, metadata_batch=None: []
        return mapper                             # the write goes nowhere

    m = _deafen(_mapper({"A": "B", "B": "C"}))
    with pytest.raises(RuntimeError, match="fixed point"):
        m.resolve_chains()

    # and the same check has to see a chain that only the fold reveals,
    # or it passes a file the store will still walk one hop further
    folded = _deafen(_mapper({"a term": "a-canonical", "A-canonical": "the end"}))
    with pytest.raises(RuntimeError, match="fixed point"):
        folded.resolve_chains()


def test_one_canonicality_rule_serves_both_callers():
    """build_from_embeddings and resolve_chains must not drift apart about which
    spelling of a concept is its name."""
    freq = {"ulcers": 9, "ulcer": 2}
    assert canonical_rank("ulcers", frozenset(), freq) > canonical_rank("ulcer", frozenset(), freq)
    assert canonical_rank("Skin wound", {"Skin wound"}, freq) > canonical_rank("ulcers", frozenset(), freq)


def test_a_chain_that_only_exists_once_the_labels_are_folded():
    """The store looks a term up by its exact spelling and THEN by
    `normalize_term`, so a hyphen is enough to hide a chain from an exact-string
    walk — and not enough to hide it from the store, which found this one on the
    next apply."""
    # the live pair, spelled as the file spells it: the second entry's key
    # differs from the first entry's canonical by one capital letter
    m = _mapper({"deep partial thickness skin burns": "deep partial-thickness burns",
                 "Deep partial-thickness burns": "deep partial-thickness burn wounds"})
    rep = m.resolve_chains()
    assert rep["repointed"] == 1
    assert m.mapping["deep partial thickness skin burns"] == "deep partial-thickness burn wounds"


def test_two_spellings_of_one_folded_name_are_left_as_they_are():
    """Folding FINDS the chain; it never rewrites the label at the end of one.
    `Povidone Iodine -> Povidone-iodine` is the mapping choosing a spelling, and
    dropping it would hand the store the unhyphenated fallback instead."""
    m = _mapper({"Povidone Iodine": "Povidone-iodine"})
    rep = m.resolve_chains()
    assert rep == {"cycles": 0, "repointed": 0, "dropped": 0, "withdrawn": 0}
    assert m.mapping == {"Povidone Iodine": "Povidone-iodine"}
