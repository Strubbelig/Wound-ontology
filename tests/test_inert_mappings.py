"""A quarter of the mapping could not change a name, and read as noise.

`ConceptStore.normalize` title-cases every name it keeps, so `Healing ->
healing` and no entry at all both leave `Healing` in the store. Measured
2026-09-23: 3,324 of 14,047 entries were inert in exactly that way — the reason
the file looks like mechanical regex work rather than the ~4,800 decisions it
contains.

Then the curator ruled that the store's name is always singular (2026-09-23),
`normalize` took the rule on, and the 5,072 PLURAL entries became inert too:
`patients -> patient` is what the store now does by itself. That is exactly why
the prune asks `store_name` rather than modelling the store's behaviour
privately — the set of inert entries moves when the store's rules move, and a
private copy would have gone on deleting the wrong ones.

What is still NOT inert: 844 PUNCTUATION entries. The fallback folds punctuation
away, so the entry is the only thing keeping `Povidone-iodine` hyphenated.
Dropping those would silently re-spell thousands of terms.
"""
import pytest

from conftest import memory_mapper

from wound_ontology.orchestrator import Orchestrator


@pytest.fixture
def pipeline(monkeypatch):
    p = Orchestrator.__new__(Orchestrator)          # no I/O; only the mapping matters
    return p


def _with(p, data):
    from wound_ontology.mappers.term_mapper import TermMapper
    p.term_mapper = memory_mapper(data)
    return p


def test_a_case_only_entry_is_inert(pipeline):
    p = _with(pipeline, {"Healing": "healing"})
    assert p.prune_inert_mappings(dry_run=True)["inert"] == 1


def test_a_plural_entry_is_inert_now_that_the_store_singularises(pipeline):
    """It was not, until 2026-09-23. The prune reads the store's own rule, so
    when the rule moved, the answer moved with it — which is the whole reason it
    is not modelled here."""
    p = _with(pipeline, {"patients": "patient"})
    assert p.prune_inert_mappings(dry_run=True)["inert"] == 1


def test_a_punctuation_entry_is_not_inert(pipeline):
    """`normalize_term` strips the hyphen, so without the entry the store says
    `Povidone Iodine`, not `Povidone-Iodine`."""
    p = _with(pipeline, {"Povidone Iodine": "Povidone-iodine"})
    assert p.prune_inert_mappings(dry_run=True)["inert"] == 0


def test_a_content_entry_is_not_inert(pipeline):
    p = _with(pipeline, {"cutaneous wound": "Skin wound"})
    assert p.prune_inert_mappings(dry_run=True)["inert"] == 0


def test_dry_run_keeps_the_entries(pipeline):
    p = _with(pipeline, {"Healing": "healing"})
    p.prune_inert_mappings(dry_run=True)
    assert p.term_mapper.mapping == {"Healing": "healing"}


def test_applying_it_removes_exactly_the_inert_ones(pipeline):
    p = _with(pipeline, {"Healing": "healing",                 # case: inert
                         "patients": "patient",                # plural: inert now
                         "Povidone Iodine": "Povidone-iodine", # punctuation: NOT
                         "cutaneous wound": "Skin wound"})     # content: NOT
    rep = p.prune_inert_mappings(dry_run=False)
    assert rep == {"inert": 2, "kept": 2}
    assert p.term_mapper.mapping == {"Povidone Iodine": "Povidone-iodine",
                                     "cutaneous wound": "Skin wound"}


def test_a_category_name_is_never_counted_as_inert_by_accident(pipeline):
    """A declared category comes out declared whatever the mapping says, so the
    comparison must be made on the declared form on both sides (rule 22)."""
    p = _with(pipeline, {"Material Entity": "material entity"})
    assert p.prune_inert_mappings(dry_run=True)["inert"] == 1
