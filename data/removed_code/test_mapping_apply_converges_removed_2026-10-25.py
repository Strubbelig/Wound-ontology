"""Applying the mapping once was not applying it.

`ConceptStore.normalize` maps a name and THEN title-cases it, so the name a
pass produces can itself be a mapping key — or fold onto one — that the same
pass has already walked past. Measured 2026-09-23 on the 6,029-abstract store:
pass 1 collapsed 12,912 names, pass 2 another 1,191, pass 3 one more, pass 4
none. The run reported a completed apply after pass 1 with 1,192 merges still
undone, which is the shape of every serious defect in this project: quiet.
"""
import pytest

from wound_ontology.mappers.mapping_cleaner import MappingCleaner


class _Mapper:
    name = "test mapper"
    mapping: dict[str, str] = {}


class _Store:
    """A store that keeps collapsing for `rounds` passes, then holds still."""

    def __init__(self, rounds: int, *, forever: bool = False):
        self.rounds = rounds
        self.forever = forever
        self.passes = 0
        self._names = 100

    def normalize(self, mapper=None):
        self.passes += 1
        if self.forever or self.passes <= self.rounds:
            self._names -= 1

    @property
    def entities(self):
        return list(range(self._names))


def _cleaner():
    return MappingCleaner(_Mapper())


def test_it_keeps_applying_until_the_store_stops_changing():
    store = _Store(rounds=3)
    settled = _cleaner().apply(store)
    assert settled == 3                 # three passes changed something
    assert store.passes == 4            # plus the one that proved it had stopped


def test_a_store_that_never_moves_is_one_pass():
    store = _Store(rounds=0)
    assert _cleaner().apply(store) == 1
    assert store.passes == 2


def test_a_mapping_that_never_settles_raises_rather_than_stopping_anywhere():
    store = _Store(rounds=0, forever=True)
    with pytest.raises(RuntimeError, match="still changing after"):
        _cleaner().apply(store, max_passes=4)
    assert store.passes == 4


def test_the_extra_rounds_are_reported(capsys):
    _cleaner().apply(_Store(rounds=3))
    assert "would have left" in capsys.readouterr().out
