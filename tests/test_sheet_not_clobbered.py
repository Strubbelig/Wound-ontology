"""A review sheet becomes a curated file the moment somebody writes in it.

`mapping_review_sheet.py` names its output by today's date, so running it twice
in a day wrote over the morning's file. On 2026-09-24 it wrote over one holding
173 of the curator's marks — recoverable only because they had been committed
and applied minutes earlier. The standing rule is that the pipeline never writes
over a curated file; a sheet with marks in it is one.
"""

import importlib.util
import pathlib

import pandas as pd
import pytest

SHEET = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "mapping_review_sheet.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("mapping_review_sheet", SHEET)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _write(path, keep="", corrected=""):
    pd.DataFrame([{"term": "a", "canonical": "A",
                   "keep(y/n)": keep, "corrected canonical": corrected}]).to_csv(path, index=False)


def test_a_new_name_is_used_as_is(mod, tmp_path):
    p = tmp_path / "mapping_review_2026-09-24.csv"
    assert mod._free_path(p) == p


def test_an_unmarked_sheet_is_regenerated_in_place(mod, tmp_path):
    p = tmp_path / "mapping_review_2026-09-24.csv"
    _write(p)
    assert mod._free_path(p) == p


def test_a_marked_sheet_is_left_alone(mod, tmp_path):
    p = tmp_path / "mapping_review_2026-09-24.csv"
    _write(p, keep="n")
    assert mod._free_path(p) == tmp_path / "mapping_review_2026-09-24_2.csv"
    assert pd.read_csv(p).fillna("")["keep(y/n)"].iloc[0] == "n"   # untouched


def test_a_correction_counts_as_a_mark(mod, tmp_path):
    p = tmp_path / "s.csv"
    _write(p, corrected="wound healing process")
    assert mod._free_path(p) != p


def test_the_counter_keeps_going_past_the_first_alternative(mod, tmp_path):
    p = tmp_path / "s.csv"
    _write(p, keep="y")
    _write(tmp_path / "s_2.csv", keep="y")
    assert mod._free_path(p) == tmp_path / "s_3.csv"


def test_an_unreadable_sheet_is_treated_as_precious(mod, tmp_path):
    """If it cannot be parsed, it cannot be shown to be safe to destroy."""
    p = tmp_path / "s.csv"
    p.write_bytes(b"\x00\x01 not a csv at all \xff")
    assert mod._free_path(p) != p
