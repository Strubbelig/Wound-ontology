"""Two runs of the pipeline must choose the same canonical for the same group.

`canonical_rank` ordered by anchor, frequency, word count and length. On a tie
in all four -- `Derived Indices` against `derived indices`, same frequency, two
words each, fifteen characters each -- `max()` over a set returned whichever the
process's hash seed iterated first. Pass 0 found it by failing to converge: a
second run wanted to rewrite 773 groups it had just written, because the winner
had changed underneath it.

A canonical that depends on PYTHONHASHSEED is not a decision.
"""

import random
import subprocess
import sys
import textwrap

import pytest

from wound_ontology.mappers.term_mapper import canonical_rank


TIED = ["Derived Indices", "derived indices"]


def test_a_tie_resolves_the_same_way_whatever_the_iteration_order():
    winners = set()
    for _ in range(20):
        shuffled = list(TIED)
        random.shuffle(shuffled)
        winners.add(max(set(shuffled), key=canonical_rank))
    assert len(winners) == 1


def test_the_order_is_total_over_a_realistic_group():
    group = ["Metabolic Markers", "metabolic markers", "Tryptophan Metabolites",
             "tryptophan metabolites", "Negative Impact", "negative impacts"]
    keys = [canonical_rank(t) for t in group]
    assert len(set(keys)) == len(group), "two terms share a rank, so max() is a coin toss"


def test_the_same_winner_across_separate_processes():
    # the real failure: two RUNS, not two calls. A fresh interpreter has a fresh
    # hash seed, which is what made this invisible inside one test session.
    code = textwrap.dedent("""
        import sys; sys.path.insert(0, "src")
        from wound_ontology.mappers.term_mapper import canonical_rank
        print(max({"Derived Indices", "derived indices"}, key=canonical_rank))
    """)
    seen = {subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True).stdout.strip() for _ in range(5)}
    assert len(seen) == 1, f"different processes chose {seen}"


def test_frequency_still_outranks_the_tiebreak():
    assert max(["zebra term", "aardvark term"],
               key=lambda t: canonical_rank(t, frequencies={"aardvark term": 9})) \
        == "aardvark term"


def test_an_anchor_still_outranks_everything():
    assert max(["common term", "Anchor"],
               key=lambda t: canonical_rank(t, anchors={"Anchor"},
                                            frequencies={"common term": 99})) == "Anchor"


def test_a_longer_label_still_outranks_a_shorter_one_at_equal_frequency():
    assert max(["ulcer", "diabetic foot ulcer"],
               key=canonical_rank) == "diabetic foot ulcer"
