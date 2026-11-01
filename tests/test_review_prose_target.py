"""A curator's free text is not a machine input.

The 2026-09-24 review UI had one box for "where does this belong instead", and
the curator typed into it:

    'wound healing' -> 'wound healing is a class in the onto and everything
                        should merge into that'

which is a sentence addressed to whoever reads the sheet. Applied as typed it
would have written a 74-character class name and pointed 995 mentions at it.
Nothing downstream could have caught it: `add` takes any string, and a canonical
nobody recognises looks exactly like a canonical nobody has curated yet.

So the pull refuses a target that does not read as a label, names the family,
and applies the curator's own reading only when it is passed in -- keeping their
original words in the sheet's `why` cell, because the reading is an
interpretation and the record should show it was one.
"""

import importlib.util
import json
import pathlib

import pytest


def _mod():
    spec = importlib.util.spec_from_file_location(
        "review_ui_pull",
        pathlib.Path(__file__).resolve().parents[1] / "scripts" / "review_ui_pull.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── What reads as a label ────────────────────────────────────────────────────

@pytest.mark.parametrize("label", [
    "wound healing",
    "Diabetes mellitus type 2",
    "silver-containing dressing",
    "incidence of surgical site infections",
    "patient-reported outcome measure",
    "NaCl 0.9%",
    "vitamin (role)",
    "wound healing by secondary intention process",
])
def test_a_label_passes(label):
    assert _mod().label_shaped(label) == "", label


@pytest.mark.parametrize("prose", [
    "wound healing is a class in the onto and everything should merge into that",
    "this should be deleted",
    "please merge into wound",
    "I think it is the same",
    "everything here belongs under wound",
    # nine words and not one of them a sentence word: length alone carries it,
    # because a class name that long is a description of the concept, not a name
    "alpha beta gamma delta epsilon zeta theta kappa lambda",
])
def test_prose_is_refused(prose):
    assert _mod().label_shaped(prose) != "", prose


def test_length_alone_refuses_a_target_no_word_of_which_is_suspect():
    m = _mod()
    assert m.label_shaped("alpha beta gamma delta epsilon zeta theta kappa") == ""
    assert "words" in m.label_shaped("alpha beta gamma delta epsilon zeta theta kappa mu")


def test_the_reason_names_what_tripped_it():
    why = _mod().label_shaped("wound healing is a class in the onto")
    assert "is" in why and "sentence" in why


def test_a_short_phrase_holding_a_stop_word_is_still_a_label():
    # `onto` is in the sentence vocabulary, and "onto a class" is prose -- but a
    # two-word name is too short to be a sentence, so the word alone cannot
    # condemn it. The length test is what carries these.
    assert _mod().label_shaped("that wound") == ""


# ── --resolve ────────────────────────────────────────────────────────────────

def test_resolve_reads_a_bare_verdict():
    assert _mod().parse_resolutions(["--resolve", "794=keep"]) == {794: ("keep", "")}


def test_resolve_reads_a_verdict_with_a_target():
    assert _mod().parse_resolutions(["--resolve", "794=repoint:wound healing"]) == {
        794: ("repoint", "wound healing")}


def test_resolve_refuses_an_unknown_verdict():
    with pytest.raises(SystemExit, match="merge"):
        _mod().parse_resolutions(["--resolve", "794=merge"])


def test_resolve_refuses_a_repoint_with_no_target():
    with pytest.raises(SystemExit, match="needs a target"):
        _mod().parse_resolutions(["--resolve", "794=repoint"])


def test_resolve_refuses_a_target_that_is_itself_prose():
    with pytest.raises(SystemExit, match="not a label"):
        _mod().parse_resolutions(
            ["--resolve", "794=repoint:wound healing is a class in the onto"])


def test_resolve_refuses_a_non_numeric_family():
    with pytest.raises(SystemExit, match="not a family index"):
        _mod().parse_resolutions(["--resolve", "wound=keep"])


def test_resolve_needs_its_value():
    with pytest.raises(SystemExit, match="needs INDEX"):
        _mod().parse_resolutions(["--resolve"])


# ── End to end, against a two-family data file ───────────────────────────────

def _fixture(tmp_path, to):
    (tmp_path / "data" / "review").mkdir(parents=True)
    (tmp_path / "data" / "review" / "review_ui_2026-01-01.json").write_text(json.dumps({
        "families": [
            {"i": 0, "c": "wound healing", "n": 2, "m": 995,
             "terms": [{"t": "wound healing"}, {"t": "Wound healing"}]},
            {"i": 1, "c": "scar", "n": 1, "m": 3, "terms": [{"t": "scars"}]},
        ]}))
    src = tmp_path / "decisions"
    src.mkdir()
    (src / "b0.json").write_text(json.dumps({
        "0": {"v": "repoint", "c": "wound healing", "to": to, "at": "2026-01-01T00:00:00Z"},
        "1": {"v": "keep", "c": "scar", "at": "2026-01-01T00:00:00Z"},
    }))
    return src


def _run(tmp_path, argv):
    mod = _mod()
    mod.ROOT = tmp_path
    return mod, mod.main(argv)


PROSE = "wound healing is a class in the onto and everything should merge into that"


def test_the_prose_target_stops_the_run_and_writes_nothing(tmp_path, capsys):
    src = _fixture(tmp_path, PROSE)
    mod = _mod()
    mod.ROOT = tmp_path
    with pytest.raises(SystemExit, match="do not read as a label"):
        mod.main(["prog", str(src)])
    assert not list((tmp_path / "data" / "review").glob("mapping_families_from_ui_*.csv"))


def test_the_refusal_names_the_family_and_the_words(tmp_path):
    src = _fixture(tmp_path, PROSE)
    mod = _mod()
    mod.ROOT = tmp_path
    with pytest.raises(SystemExit) as e:
        mod.main(["prog", str(src)])
    assert "family 0" in str(e.value) and PROSE in str(e.value)
    assert "--resolve 0=keep" in str(e.value)


def test_a_resolved_family_is_applied_as_the_curator_read_it(tmp_path):
    import pandas as pd
    src = _fixture(tmp_path, PROSE)
    mod, rc = _run(tmp_path, ["prog", str(src), "--resolve", "0=keep"])
    assert rc == 0
    out = sorted((tmp_path / "data" / "review").glob("mapping_families_from_ui_*.csv"))[-1]
    df = pd.read_csv(out).fillna("")
    row = df[df["canonical"] == "wound healing"].iloc[0]
    assert row["keep(y/n)"] == "y"
    assert row["corrected canonical"] == ""


def test_the_original_words_survive_into_the_sheet(tmp_path):
    import pandas as pd
    src = _fixture(tmp_path, PROSE)
    _run(tmp_path, ["prog", str(src), "--resolve", "0=keep"])
    out = sorted((tmp_path / "data" / "review").glob("mapping_families_from_ui_*.csv"))[-1]
    why = pd.read_csv(out).fillna("").iloc[0]["why"]
    assert PROSE in why and "read as keep" in why


def test_a_label_target_needs_no_resolution(tmp_path):
    import pandas as pd
    src = _fixture(tmp_path, "wound healing process")
    mod, rc = _run(tmp_path, ["prog", str(src)])
    assert rc == 0
    out = sorted((tmp_path / "data" / "review").glob("mapping_families_from_ui_*.csv"))[-1]
    df = pd.read_csv(out).fillna("")
    assert df[df["canonical"] == "wound healing"].iloc[0]["corrected canonical"] == \
        "wound healing process"


def test_resolve_does_not_swallow_the_source_directory(tmp_path):
    # `--resolve X=y` takes a value, and the value must not be mistaken for the
    # positional argument, nor the directory dropped along with the flag.
    src = _fixture(tmp_path, PROSE)
    mod, rc = _run(tmp_path, ["prog", "--resolve", "0=keep", str(src)])
    assert rc == 0
