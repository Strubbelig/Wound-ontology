"""A term decided while looking at where it IS must be applied there.

The contested set decides one TERM at a time, because the 15 families left after
the bulk acceptance are exactly the ones whose terms disagree: `antiseptic drug`
holds three terms pass 2 calls the same class and one it calls broader.

Four of the fifteen were also MOVED by the earlier review -- `subcutaneous layer`
pointed at `subcutaneous tissue` when the page's data was built and points at
`subcutaneous tissues` now. The page shows where the term is, so the sheet must
name that canonical: applying the decision against the pair the family used to
have would refuse a merge that no longer exists and leave the live one standing.
"""

import importlib.util
import json
import pathlib

import pandas as pd
import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _mod():
    spec = importlib.util.spec_from_file_location(
        "review_ui_pull_terms", SCRIPTS / "review_ui_pull_terms.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FAMILIES = [
    {"i": 1, "c": "antiseptic drug", "m": 22, "def": "", "cat": "", "note": "",
     "terms": [{"t": "antiseptics", "mn": 14, "now": "antiseptic drug",
                "p1": "same_class", "r1": "", "p2": "same_class", "r2": ""},
               {"t": "Antiseptics", "mn": 1, "now": "antiseptic drug",
                "p1": "same_class", "r1": "", "p2": "broader", "r2": ""}]},
    {"i": 882, "c": "subcutaneous tissue", "m": 25, "def": "", "cat": "", "note": "",
     "terms": [{"t": "subcutaneous layer", "mn": 1, "now": "subcutaneous tissues",
                "p1": "different", "r1": "", "p2": "", "r2": ""}]},
    {"i": 50, "c": "vitamin (role)", "m": 3, "def": "", "cat": "", "note": "",
     # `now` empty: the term is on the record but maps to nothing right now
     "terms": [{"t": "vitamins", "mn": 3, "now": "",
                "p1": "", "r1": "", "p2": "", "r2": ""}]},
]


def _fixture(tmp_path, docs):
    (tmp_path / "data" / "review").mkdir(parents=True)
    (tmp_path / "data" / "review" / "review_ui_contested_2026-09-25.json").write_text(
        json.dumps({"built": "x", "round": "contested", "families": FAMILIES}))
    src = tmp_path / "decisions"
    src.mkdir()
    for name, body in docs.items():
        (src / (name + ".json")).write_text(json.dumps(body))
    return src


def _run(tmp_path, docs):
    mod = _mod()
    mod.ROOT = tmp_path
    src = _fixture(tmp_path, docs)
    assert mod.main(["prog", str(src)]) == 0
    out = sorted((tmp_path / "data" / "review").glob("mapping_terms_contested_*.csv"))[-1]
    return pd.read_csv(out, keep_default_na=False).fillna("")


# ── the four verdicts ────────────────────────────────────────────────────────

def test_merge_is_an_approval(tmp_path):
    df = _run(tmp_path, {"f1": {"t0": {"v": "merge", "term": "antiseptics", "at": ""}}})
    r = df.iloc[0]
    assert r["term"] == "antiseptics" and r["keep(y/n)"] == "y"
    assert r["corrected canonical"] == ""


def test_split_is_a_refusal(tmp_path):
    df = _run(tmp_path, {"f1": {"t1": {"v": "split", "term": "Antiseptics", "at": ""}}})
    assert df.iloc[0]["keep(y/n)"] == "n"


def test_make_canonical_puts_the_term_in_the_corrected_column(tmp_path):
    df = _run(tmp_path, {"f1": {"t1": {"v": "canonical", "term": "Antiseptics", "at": ""}}})
    r = df.iloc[0]
    assert r["corrected canonical"] == "Antiseptics" == r["term"]


def test_elsewhere_carries_the_typed_label(tmp_path):
    df = _run(tmp_path, {"f1": {"t0": {"v": "elsewhere", "term": "antiseptics",
                                       "to": "antiseptic agent", "at": ""}}})
    assert df.iloc[0]["corrected canonical"] == "antiseptic agent"


# ── a moved term is decided where it now points ──────────────────────────────

def test_a_moved_term_names_its_current_canonical(tmp_path):
    df = _run(tmp_path, {"f882": {"t0": {"v": "merge", "term": "subcutaneous layer",
                                         "at": ""}}})
    assert df.iloc[0]["canonical"] == "subcutaneous tissues"
    assert df.iloc[0]["canonical"] != "subcutaneous tissue"


def test_the_move_is_said_in_the_why_cell(tmp_path):
    df = _run(tmp_path, {"f882": {"t0": {"v": "merge", "term": "subcutaneous layer",
                                         "at": ""}}})
    assert "moved since the review" in df.iloc[0]["why"]


def test_an_unmapped_term_falls_back_to_the_family_canonical(tmp_path):
    # `now` is empty when the term maps to nothing; the decision is then about
    # the pair the family proposes, and the column must say so rather than blank
    df = _run(tmp_path, {"f50": {"t0": {"v": "merge", "term": "vitamins", "at": ""}}})
    assert df.iloc[0]["canonical"] == "vitamin (role)"


def test_a_term_that_has_not_moved_keeps_the_family_canonical(tmp_path):
    df = _run(tmp_path, {"f1": {"t0": {"v": "merge", "term": "antiseptics", "at": ""}}})
    assert df.iloc[0]["canonical"] == "antiseptic drug"
    assert "moved since" not in df.iloc[0]["why"]


# ── refusals ─────────────────────────────────────────────────────────────────

def test_an_unknown_verdict_stops_the_run(tmp_path):
    mod = _mod(); mod.ROOT = tmp_path
    src = _fixture(tmp_path, {"f1": {"t0": {"v": "maybe", "term": "antiseptics"}}})
    with pytest.raises(SystemExit, match="maybe"):
        mod.main(["prog", str(src)])


def test_a_decision_naming_a_different_term_stops_the_run(tmp_path):
    mod = _mod(); mod.ROOT = tmp_path
    src = _fixture(tmp_path, {"f1": {"t0": {"v": "merge", "term": "Antiseptics"}}})
    with pytest.raises(SystemExit, match="do not apply this"):
        mod.main(["prog", str(src)])


def test_an_unknown_family_stops_the_run(tmp_path):
    mod = _mod(); mod.ROOT = tmp_path
    src = _fixture(tmp_path, {"f999": {"t0": {"v": "merge", "term": "x"}}})
    with pytest.raises(SystemExit, match="not in the data file"):
        mod.main(["prog", str(src)])


def test_a_term_index_past_the_family_stops_the_run(tmp_path):
    mod = _mod(); mod.ROOT = tmp_path
    src = _fixture(tmp_path, {"f1": {"t9": {"v": "merge", "term": "antiseptics"}}})
    with pytest.raises(SystemExit, match="no term 9"):
        mod.main(["prog", str(src)])


def test_elsewhere_with_no_label_stops_the_run(tmp_path):
    mod = _mod(); mod.ROOT = tmp_path
    src = _fixture(tmp_path, {"f1": {"t0": {"v": "elsewhere", "term": "antiseptics",
                                            "to": "  "}}})
    with pytest.raises(SystemExit, match="half-decided"):
        mod.main(["prog", str(src)])


def test_a_prose_target_stops_the_run(tmp_path):
    mod = _mod(); mod.ROOT = tmp_path
    src = _fixture(tmp_path, {"f1": {"t0": {
        "v": "elsewhere", "term": "antiseptics",
        "to": "this should be merged into the antiseptic class instead"}}})
    with pytest.raises(SystemExit, match="do not read as a label"):
        mod.main(["prog", str(src)])


def test_a_decision_with_no_term_stops_the_run(tmp_path):
    mod = _mod(); mod.ROOT = tmp_path
    src = _fixture(tmp_path, {"f1": {"t0": {"v": "merge"}}})
    with pytest.raises(SystemExit, match="names no term"):
        mod.main(["prog", str(src)])


def test_a_document_that_is_not_a_family_is_ignored(tmp_path):
    df = _run(tmp_path, {"f1": {"t0": {"v": "merge", "term": "antiseptics", "at": ""}},
                         "state": {"t0": {"v": "merge", "term": "nonsense"}}})
    assert len(df) == 1


# ── the sheet the applier takes ──────────────────────────────────────────────

def test_the_sheet_has_the_columns_the_applier_needs(tmp_path):
    df = _run(tmp_path, {"f1": {"t0": {"v": "merge", "term": "antiseptics", "at": ""}}})
    for col in ("term", "canonical", "keep(y/n)", "corrected canonical"):
        assert col in df.columns


def test_the_applier_reads_it_as_a_row_sheet(tmp_path):
    df = _run(tmp_path, {"f1": {"t0": {"v": "merge", "term": "antiseptics", "at": ""},
                                "t1": {"v": "split", "term": "Antiseptics", "at": ""}}})
    spec = importlib.util.spec_from_file_location(
        "apply_review_sheet", SCRIPTS / "apply_review_sheet.py")
    ars = importlib.util.module_from_spec(spec); spec.loader.exec_module(ars)
    d = ars.decisions(df)
    assert d.kept == ["antiseptics"] and d.withdraw == ["Antiseptics"]
    assert d.unmarked == 0
