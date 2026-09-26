"""`NA` is a term, not a missing value.

The mapping holds `N/A -> NA` and `Na+ -> NA`. Pandas reads `NA`, `N/A`, `None`,
`null`, `nan` and a dozen other spellings as missing by default, so the family
sheet showed row 3200 with no canonical and no terms, the review UI showed an
empty family, and `.fillna("")` then turned the term into the empty string --
a decision on that row would have been applied to `""`.

A sheet cell says what it says. Every script that reads one passes
`keep_default_na=False`, and this pins that: it is one keyword argument, it is
invisible when right, and nothing else in the pipeline would notice it going.
"""

import importlib.util
import pathlib
import re

import pandas as pd
import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
READERS = ["apply_review_sheet.py", "mapping_review_sheet.py", "review_ui_data.py"]


def _mod(name):
    spec = importlib.util.spec_from_file_location(name[:-3], SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("script", READERS)
def test_every_sheet_reader_keeps_na_strings(script):
    src = (SCRIPTS / script).read_text()
    calls = re.findall(r"pd\.read_csv\([^)]*\)", src)
    assert calls, f"{script} reads no CSV any more — has it moved?"
    for call in calls:
        assert "keep_default_na=False" in call, f"{script}: {call}"


@pytest.mark.parametrize("value", ["NA", "N/A", "None", "null", "nan", "NULL", "<NA>"])
def test_a_term_spelled_like_a_missing_value_survives_the_round_trip(tmp_path, value):
    sheet = tmp_path / "s.csv"
    pd.DataFrame([{"canonical": value, "terms": f"{value} ; x",
                   "keep(y/n)": "", "corrected canonical": "wound", "why": ""}]
                 ).to_csv(sheet, index=False)
    df = pd.read_csv(sheet, keep_default_na=False).fillna("")
    assert df.iloc[0]["canonical"] == value
    assert df.iloc[0]["terms"] == f"{value} ; x"


def test_the_decision_reaches_the_term_and_not_the_empty_string(tmp_path):
    mod = _mod("apply_review_sheet.py")
    sheet = tmp_path / "s.csv"
    pd.DataFrame([{"canonical": "NA", "terms": "N/A ; Na+", "keep(y/n)": "",
                   "corrected canonical": "not applicable", "why": ""}]
                 ).to_csv(sheet, index=False)
    df = pd.read_csv(sheet, keep_default_na=False).fillna("")
    d = mod.decisions(mod.expand_families(df))
    assert d.repoint == {"N/A": "not applicable", "Na+": "not applicable",
                         "NA": "not applicable"}
    assert "" not in d.repoint


def test_an_empty_cell_is_still_empty(tmp_path):
    # keep_default_na=False must not turn a genuinely blank cell into something
    sheet = tmp_path / "s.csv"
    pd.DataFrame([{"canonical": "wound", "terms": "wounds", "keep(y/n)": "y",
                   "corrected canonical": "", "why": ""}]).to_csv(sheet, index=False)
    df = pd.read_csv(sheet, keep_default_na=False).fillna("")
    assert df.iloc[0]["corrected canonical"] == ""
    mod = _mod("apply_review_sheet.py")
    assert mod.decisions(mod.expand_families(df)).kept == ["wounds"]
