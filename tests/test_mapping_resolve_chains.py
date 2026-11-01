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

from conftest import J, memory_mapper, rule89_file
from wound_ontology.mappers.term_mapper import canonical_rank


def _mapper(data):
    """The real TermMappingAndGate over an in-memory file — see tests/conftest.py."""
    return memory_mapper(data)


def _cycle(links):
    """A mapping that holds a cycle. An old file's cycle is broken when it is
    translated (rule 89), so a cycle the chain step has to break is written in
    the new form: one SapBERT name per string."""
    return memory_mapper(rule89_file({t: {"name": [J(c, "sapbert-clustering")]} for t, c in links.items()}))


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
    m = _cycle({"CFU": "CFUs", "CFUs": "CFU"})
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
    m = _cycle({"A": "X", "X": "Y", "Y": "X"})
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
    assert rep == {"cycles": 0, "repointed": 0, "dropped": 0, "withdrawn": 0,
                   "contested": []}
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
    assert rep == {"cycles": 0, "repointed": 0, "dropped": 0, "withdrawn": 0,
                   "contested": []}
    assert m.mapping == {"Povidone Iodine": "Povidone-iodine"}


# ── transitivity, and the shape that follows from it ─────────────────────────

def test_a_chain_whose_first_hop_folds_to_one_node_is_resolved():
    """The case the walk could not see and the check could.

    `Subcutaneous Tissues -> subcutaneous tissues` folds to a single node, so
    an exact-string walk skipped it as "one node, two spellings" and the raw
    mapping kept a two-hop chain. `normalize` follows one hop, so the merge
    half-landed. 2,206 entries on 2026-09-26, and `resolve_chains` raised
    rather than finishing.
    """
    m = _mapper({"Subcutaneous Tissues": "subcutaneous tissues",
                 "subcutaneous tissues": "subcutaneous tissue"})
    m.resolve_chains()
    assert m.mapping["Subcutaneous Tissues"] == "subcutaneous tissue"
    assert m.mapping["subcutaneous tissues"] == "subcutaneous tissue"


def test_a_curators_entry_follows_its_target_when_the_target_moves():
    """Transitivity. `A -> B` and `B -> C` say A, B and C are one concept, so
    A goes to C. A curator writing `A -> B` said those two are one thing; if B
    has moved, following it is what honours that."""
    m = _mapper({"adjunctive therapy": "Adjunct Therapy",
                 "Adjunct Therapy": "adjunct therapy"})
    m.resolve_chains()
    assert m.mapping["adjunctive therapy"] == "adjunct therapy"


def test_everything_lands_in_one_hop():
    m = _mapper({"a": "b", "b": "c", "c": "d", "X": "b", "Y": "c"})
    m.resolve_chains()
    assert not [t for t, c in m.mapping.items() if c in m.mapping]


def test_two_branches_of_one_component_meet_at_the_same_canonical():
    m = _mapper({"a": "mid", "b": "mid", "mid": "end"})
    m.resolve_chains()
    assert set(m.mapping.values()) == {"end"}


def test_a_refused_pair_leaves_the_component_instead_of_being_written():
    m = _mapper({"a term": "mid term", "mid term": "end term"})
    m._term_mapping.refuse("a term", "end term", reason="not the same thing")
    rep = m.resolve_chains()
    assert rep["withdrawn"] == 1
    assert "a term" not in m.mapping


def test_resolving_twice_changes_nothing_the_second_time():
    m = _mapper({"a": "b", "b": "c", "P": "Q", "Q": "P"})
    m.resolve_chains()
    before = dict(m.mapping)
    rep = m.resolve_chains()
    assert rep["repointed"] == 0 and rep["dropped"] == 0
    assert m.mapping == before


def test_two_spellings_of_one_folded_name_pointing_different_ways_elect():
    """A component can hold two CLAIMED canonicals.

    `patient-reported outcomes -> patient-reported outcome` beside
    `Patient-Reported Outcomes -> patient-reported outcome measure`: the two
    terms fold to one name, so transitivity makes all four one concept, and it
    cannot have two names. They elect, and the losers are reported -- if the
    two really are different concepts, the fix is to refuse one of the edges
    that joined them, not to leave a chain.
    """
    m = _mapper({"patient-reported outcomes": "patient-reported outcome",
                 "Patient-Reported Outcomes": "patient-reported outcome measure"})
    rep = m.resolve_chains()
    assert len(rep["contested"]) == 1
    winner, losers = rep["contested"][0]
    assert winner == "patient-reported outcome measure"    # the longer label
    assert losers == ["patient-reported outcome"]
    assert set(m.mapping.values()) == {"patient-reported outcome measure"}


def test_an_uncontested_component_reports_nothing_contested():
    m = _mapper({"a": "b", "b": "c"})
    assert m.resolve_chains()["contested"] == []


def test_a_cycle_between_two_spellings_of_one_folded_name_is_broken():
    """The component pass cannot see these: it only draws an edge when the
    folds DIFFER, so `Co-assembly <-> co-assembly` is a single node with an
    internal loop. 874 of them after pass 0, every one a capitalisation."""
    m = _mapper({"Co-assembly": "co-assembly", "co-assembly": "Co-assembly"})
    m.resolve_chains()
    assert len(m.mapping) == 1
    assert not [t for t, c in m.mapping.items() if c in m.mapping]


def test_a_one_way_entry_between_two_spellings_is_not_a_cycle():
    m = _mapper({"Povidone Iodine": "Povidone-iodine"})
    m.resolve_chains()
    assert m.mapping == {"Povidone Iodine": "Povidone-iodine"}


def test_a_three_spelling_cycle_of_one_folded_name_is_broken():
    m = _mapper({"a-b": "A-B", "A-B": "A-b", "A-b": "a-b"})
    m.resolve_chains()
    assert len(set(m.mapping.values())) == 1
    assert not [t for t, c in m.mapping.items() if c in m.mapping]


def test_a_chain_inside_one_folded_name_flattens():
    """Three spellings of one name, and the store follows one hop.

    Not a cycle, so the cycle breaker leaves it; not a cross-fold edge, so the
    component pass never sees it. The last chained entry in the live mapping
    after everything else resolved.

    The hyphen is U+2011, a NON-BREAKING hyphen, which is what the abstract
    actually contained. `normalize_term` strips it as punctuation, so
    `IL\u201110` folds to `il10`; with an ordinary hyphen it folds to `il 10`
    instead, the edge becomes cross-fold, and the component pass handles it.
    An ASCII hyphen here tests a different code path and passes either way.
    """
    m = _mapper({"IL\u201110": "Il10", "Il10": "il10"})
    m.resolve_chains()
    assert m.mapping["IL\u201110"] == "il10"
    assert not [t for t, c in m.mapping.items() if c in m.mapping]


def test_the_same_chain_with_an_ordinary_hyphen_also_flattens():
    # the cross-fold route to the same place: `il 10` -> `il10`
    m = _mapper({"IL-10": "Il10", "Il10": "il10"})
    m.resolve_chains()
    assert m.mapping["IL-10"] == "il10"


def test_a_cycle_elects_the_curators_target_over_the_commoner_spelling():
    """2026-09-28: the curator made `microRNA` the name (`miRNA -> microRNA`);
    the rebuild re-proposed `microRNA -> miRNA`, the two formed a cycle, and the
    election by frequency retired the curator's entry as "spelling of its own
    canonical". A curator's same_class verdict on the live pair decides."""
    m = _cycle({"miRNA": "microRNA", "microRNA": "miRNA"})
    m._term_mapping.judge("miRNA", "microRNA", curator={"verdict": "same_class"})
    m.resolve_chains(frequencies={"miRNA": 50, "microRNA": 2})
    assert m.mapping == {"miRNA": "microRNA"}
