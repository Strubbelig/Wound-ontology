"""A curator saying "the other one is the right name" is a reversal, not an `n`.

On the 2026-09-24 sheet, 6 of 9 rows marked `n` said so in their `why` cell:
"reverse the mapping", "the process suffix is what i actually want here",
"always prefer the non hyphenated synonym", "stick to american". Marking such a
row `n` refuses the merge and leaves BOTH spellings standing as separate
concepts -- the opposite of the decision being made. The sheet had no way to say
it, so the curator wrote prose, and prose does not apply.

Putting the row's own term in `corrected canonical` now says it.
"""

import pandas as pd
import pytest

from conftest import memory_mapper


def _sheet(**row) -> pd.DataFrame:
    base = {"term": "", "canonical": "", "keep(y/n)": "", "corrected canonical": "",
            "why": ""}
    return pd.DataFrame([{**base, **row}])


def _decisions(df):
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "apply_review_sheet",
        pathlib.Path(__file__).resolve().parents[1] / "scripts" / "apply_review_sheet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.decisions(df)


# ── Reading the sheet ────────────────────────────────────────────────────────

def test_the_term_in_the_corrected_column_is_a_reversal():
    w, r, rev, _k, _, _amb = _decisions(_sheet(term="subcutaneous tissue",
                                     canonical="subcutaneous layer",
                                     **{"corrected canonical": "subcutaneous tissue"}))
    assert rev == {"subcutaneous tissue": "subcutaneous layer"}
    assert w == [] and r == {}


def test_a_reversal_is_read_case_insensitively():
    """A curator typing a name back is matching a concept, not a byte string."""
    _, _, rev, _k, _, _amb = _decisions(_sheet(term="Case", canonical="cases",
                                     **{"corrected canonical": "  case  "}))
    assert rev == {"Case": "cases"}


def test_a_different_label_is_still_a_re_point():
    _, r, rev, _k, _, _amb = _decisions(_sheet(term="fibroblasts", canonical="fibroblast cells",
                                     **{"corrected canonical": "fibroblast"}))
    assert r == {"fibroblasts": "fibroblast"} and rev == {}


def test_the_canonical_typed_back_is_no_decision_at_all():
    w, r, rev, _k, un, _amb = _decisions(_sheet(term="wounds", canonical="Wound",
                                      **{"corrected canonical": "Wound"}))
    assert (w, r, rev) == ([], {}, {})


def test_a_canonical_that_differs_only_in_case_is_read_as_a_restatement():
    """`a -> A` with `A` in the column: a case-insensitive test cannot tell the
    canonical restated from the term typed back, and only one of those two means
    nothing. The exact match on the canonical is checked first."""
    w, r, rev, _k, un, _amb = _decisions(_sheet(term="a", canonical="A",
                                      **{"corrected canonical": "A"}))
    assert (w, r, rev) == ([], {}, {})


def test_the_term_typed_back_still_reverses_when_only_the_case_differs():
    _, _, rev, _k, _, _amb = _decisions(_sheet(term="a", canonical="A",
                                     **{"corrected canonical": "a"}))
    assert rev == {"a": "A"}


def test_n_without_a_correction_is_still_a_plain_withdrawal():
    w, _, rev, _k, _, _amb = _decisions(_sheet(term="Diabetes mellitus", canonical="diabetes",
                                     **{"keep(y/n)": "n"}))
    assert w == ["Diabetes mellitus"] and rev == {}


def test_a_reversal_outranks_an_n_on_the_same_row():
    """Both marks appear together on the real sheet — `n` to reject the
    direction, the term to say which direction is right."""
    w, _, rev, _k, _, _amb = _decisions(_sheet(term="case", canonical="cases",
                                     **{"keep(y/n)": "n", "corrected canonical": "case"}))
    assert rev == {"case": "cases"} and w == []


def test_an_empty_correction_read_back_as_the_string_nan_is_not_a_decision():
    """`decisions` must hold on its own, not on its caller's housekeeping.

    pandas reads a blank cell as NaN and `str()` makes it the truthy string
    'nan'. `main` happens to `.fillna("")` first, so this has never fired in
    anger -- but the guard belongs in the function that reads the column, not in
    one of the two places that call it.
    """
    df = pd.read_csv(pd.io.common.StringIO(
        "term,canonical,keep(y/n),corrected canonical,why\na,A,,,\nb,B,,b,\n"))
    w, r, rev, _k, un, _amb = _decisions(df)
    assert r == {} and rev == {"b": "B"} and un == 1


# ── Writing it ───────────────────────────────────────────────────────────────

def test_a_reversal_refuses_the_pair_and_writes_the_other_direction():
    m = memory_mapper({"subcutaneous tissue": "subcutaneous layer"})
    tm = m._term_mapping
    tm.refuse("subcutaneous tissue", "subcutaneous layer", reason="reversed", by="curator")
    tm.add("subcutaneous layer", "subcutaneous tissue")
    assert tm.data == {"subcutaneous layer": "subcutaneous tissue"}
    assert tm.is_refused("subcutaneous tissue", "subcutaneous layer")


def test_the_refusal_half_is_what_stops_the_next_build_undoing_it():
    """Without it the rebuild re-proposes the merge in the old direction and the
    pass-1 verdict on record approves it again."""
    m = memory_mapper({"case": "cases"})
    tm = m._term_mapping
    tm.judge("case", "cases", pass1={"verdict": "same_class", "reason": "plural"})
    tm.refuse("case", "cases", reason="reversed", by="curator")
    tm.add("cases", "case")
    with pytest.raises(ValueError, match="stands refused"):
        tm.add("case", "cases")


# ── An approval is a decision ────────────────────────────────────────────────

def test_a_y_is_collected_as_a_decision_not_counted_as_unmarked():
    """164 rows were approved on the 2026-09-24 sheet and the mapping could not
    tell them from the 4,486 nobody had opened, because `y` writes no mapping.
    It writes no mapping and it is still a verdict."""
    w, r, rev, kept, un, _amb = _decisions(_sheet(term="wounds", canonical="Wound",
                                            **{"keep(y/n)": "y"}))
    assert kept == ["wounds"] and un == 0
    assert (w, r, rev) == ([], {}, {})


def test_a_blank_is_still_not_a_decision():
    w, r, rev, kept, un, _amb = _decisions(_sheet(term="wounds", canonical="Wound"))
    assert kept == [] and un == 1


def test_only_the_row_that_carries_the_correction_verbatim_reverses():
    """A family can hold two spellings of one word. `Angiogenesis process`
    gathers `angiogenesis` and `Angiogenesis`; reversing onto `angiogenesis`
    made both rows think they were chosen, writing two inverse entries for one
    canonical where the second overwrote the first."""
    df = pd.DataFrame([
        {"term": "tissue angiogenesis", "canonical": "Angiogenesis process",
         "keep(y/n)": "", "corrected canonical": "angiogenesis", "why": ""},
        {"term": "angiogenesis", "canonical": "Angiogenesis process",
         "keep(y/n)": "", "corrected canonical": "angiogenesis", "why": ""},
        {"term": "Angiogenesis", "canonical": "Angiogenesis process",
         "keep(y/n)": "", "corrected canonical": "angiogenesis", "why": ""},
    ])
    w, r, rev, kept, un, _amb = _decisions(df)
    assert rev == {"angiogenesis": "Angiogenesis process"}
    assert r == {"tissue angiogenesis": "angiogenesis",
                 "Angiogenesis": "angiogenesis"}


def test_a_hand_typed_name_still_reverses_when_no_row_matches_exactly():
    """The fallback stays: a curator typing `case` at a row whose term is `Case`
    is matching a concept, and no other row carries `case` verbatim."""
    df = pd.DataFrame([{"term": "Case", "canonical": "cases", "keep(y/n)": "n",
                        "corrected canonical": "case", "why": ""}])
    _, _, rev, _, _, _amb = _decisions(df)
    assert rev == {"Case": "cases"}
