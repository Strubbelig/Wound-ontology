"""A curator's mark either reaches the mapping or is reported as unmarked.

The 2026-09-10 sheet was applied by a script that no longer exists, so the same
work was done twice. This one lives in `scripts/`, and these tests pin the part
that can lose a decision quietly: reading the two columns that are the
curator's.
"""
import importlib.util
import pathlib

import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location(
    "apply_review_sheet",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "apply_review_sheet.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _sheet(rows):
    return pd.DataFrame(rows, columns=["term", "canonical", "keep(y/n)",
                                       "corrected canonical"]).fillna("")


def test_n_withdraws_and_y_keeps():
    df = _sheet([["a", "A", "n", ""], ["b", "B", "y", ""]])
    withdraw, repoint, unmarked = mod.decisions(df)
    assert withdraw == ["a"]
    assert repoint == {} and unmarked == 0


def test_a_correction_outranks_a_refusal():
    """Saying where a term belongs is stronger than saying it does not belong
    here — so `n` beside a corrected canonical re-points, it does not withdraw."""
    df = _sheet([["a", "A", "n", "C"]])
    withdraw, repoint, _ = mod.decisions(df)
    assert withdraw == [] and repoint == {"a": "C"}


def test_a_correction_that_restates_the_canonical_changes_nothing():
    df = _sheet([["a", "A", "", "A"]])
    assert mod.decisions(df) == ([], {}, 0)


def test_an_unmarked_row_is_counted_not_guessed():
    df = _sheet([["a", "A", "", ""], ["b", "B", "  ", ""], ["c", "C", "maybe", ""]])
    withdraw, repoint, unmarked = mod.decisions(df)
    assert (withdraw, repoint) == ([], {})
    assert unmarked == 3


def test_whitespace_and_case_do_not_hide_a_decision():
    df = _sheet([["a", "A", " N ", ""], ["b", "B", "Y", ""], ["c", "C", "", "  D  "]])
    withdraw, repoint, unmarked = mod.decisions(df)
    assert withdraw == ["a"] and repoint == {"c": "D"} and unmarked == 0
