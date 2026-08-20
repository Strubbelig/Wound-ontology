"""Undecided (NaN) cells must never be read as 'attribute holds'.

`concepts.Context` coerces every cell with bool(), and bool(float('nan')) is
True. Handing raw NaN to it silently asserts that undecided attributes hold,
which manufactures shared intents and therefore invented superclasses.
"""
import numpy as np
import pandas as pd
import pytest

from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.fca.concept_lattice import ConceptLattice


class MockDM:
    def load_latest_csv(self, _): return None
    def save_as_csv(self, df, _): pass
    def load_latest_pickle(self, _): return None
    def save_as_pickle(self, *a): pass
    def get_meta_stamp(self, tag): return ("meta_" + tag, "stamp")


@pytest.fixture
def matrix():
    """A and C share 'deep' only because that cell is undecided in both."""
    cm = ContextMatrix(MockDM(), "t")
    cm._df = pd.DataFrame(
        [[1.0, np.nan, 0.0],
         [1.0, 0.0,    0.0],
         [0.0, np.nan, 1.0]],
        index=["Wound A", "Wound B", "Wound C"],
        columns=["has_quality: red", "has_quality: deep", "part_of: skin"],
    )
    return cm


def test_nan_is_true_in_python():
    """The upstream behaviour this whole module defends against."""
    assert bool(float("nan")) is True


def test_tuples_never_emit_nan(matrix):
    for policy in (matrix.UNKNOWN_ABSENT, matrix.UNKNOWN_PRESENT):
        for row in matrix.tuples(policy):
            for v in row:
                assert isinstance(v, bool)


def test_tuples_policies_differ(matrix):
    absent = matrix.tuples(ContextMatrix.UNKNOWN_ABSENT)
    present = matrix.tuples(ContextMatrix.UNKNOWN_PRESENT)
    assert absent[0][1] is False
    assert present[0][1] is True


def test_tuples_rejects_unknown_policy(matrix):
    with pytest.raises(ValueError):
        matrix.tuples("whatever")


def test_bool_tuples_is_pessimistic(matrix):
    """The back-compat property must not let an undecided cell read as True."""
    assert matrix.bool_tuples == matrix.tuples(ContextMatrix.UNKNOWN_ABSENT)


def test_undecided_accounting(matrix):
    assert matrix.undecided_count == 2
    assert matrix.undecided_cells() == [
        ("Wound A", "has_quality: deep"),
        ("Wound C", "has_quality: deep"),
    ]
    assert 0 < matrix.undecided_density < 1


def test_spurious_concept_is_a_candidate_not_certain(matrix):
    """{deep} exists only if both undecided cells happen to be true."""
    cl = ConceptLattice(MockDM(), matrix)
    cl.get_data_and_run_fca()
    spurious = frozenset({"has_quality: deep"})
    assert spurious not in cl.certain_intents
    assert spurious in cl.candidate_intents


def test_no_undecided_means_no_candidates():
    cm = ContextMatrix(MockDM(), "t2")
    cm._df = pd.DataFrame(
        [[1.0, 0.0], [1.0, 1.0]], index=["X", "Y"], columns=["a: 1", "b: 2"]
    )
    cl = ConceptLattice(MockDM(), cm)
    cl.get_data_and_run_fca()
    assert cl.candidate_intents == set()
    assert cl.certain_intents


def test_is_certain_defaults_open_without_a_dual_build(matrix):
    """A lattice loaded from pickle has no dual build; don't withhold everything."""
    cl = ConceptLattice(MockDM(), matrix)

    class C:
        intent = ("has_quality: red",)
    assert cl.is_certain(C()) is True
