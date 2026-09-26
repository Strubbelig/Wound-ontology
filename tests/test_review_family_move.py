"""A family decision is about the family, the canonical included.

Two things the 2026-09-24 review would have got wrong, found by rehearsing it
before applying:

1. `silver-containing dressings` gathered 7 spellings and the curator re-pointed
   it to the singular. Moving the 7 members and not the canonical leaves the
   plural standing as its own concept, still holding its own mentions -- the
   decision defeated by the shape of the sheet. 18 of the 19 re-points in that
   review were exactly this: a plural canonical being singularised.

2. `type 2 diabetes` gathers both `Diabetes Mellitus type 2` and `diabetes
   mellitus type 2`, and the curator corrected it to a third spelling,
   `Diabetes mellitus type 2`. Case-insensitively that named BOTH, so both rows
   read themselves as the chosen one and each wrote an inverse entry for the
   same canonical -- the second silently overwriting the first.
"""

import importlib.util
import pathlib
from types import SimpleNamespace

import pandas as pd
import pytest

from conftest import memory_mapper


def _mod():
    spec = importlib.util.spec_from_file_location(
        "apply_review_sheet",
        pathlib.Path(__file__).resolve().parents[1] / "scripts" / "apply_review_sheet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _family(canonical, terms, keep="", corrected=""):
    return pd.DataFrame([{"canonical": canonical, "terms": " ; ".join(terms),
                          "keep(y/n)": keep, "corrected canonical": corrected,
                          "why": ""}])


# ── The canonical joins its own family when the family moves ─────────────────

def test_a_repointed_family_takes_its_canonical_with_it():
    df = _mod().expand_families(
        _family("silver-containing dressings",
                ["silver dressings", "Silver-containing dressings"],
                corrected="silver-containing dressing"))
    assert "silver-containing dressings" in set(df["term"])


def test_the_canonicals_row_carries_the_same_correction():
    df = _mod().expand_families(
        _family("silver-containing dressings", ["silver dressings"],
                corrected="silver-containing dressing"))
    row = df[df["term"] == "silver-containing dressings"].iloc[0]
    assert row["corrected canonical"] == "silver-containing dressing"


def test_the_plural_canonical_is_actually_repointed():
    m = _mod()
    d = m.decisions(m.expand_families(
        _family("silver-containing dressings", ["silver dressings"],
                corrected="silver-containing dressing")))
    assert d.repoint["silver-containing dressings"] == "silver-containing dressing"
    assert d.repoint["silver dressings"] == "silver-containing dressing"


def test_an_approved_family_does_not_add_its_canonical():
    df = _mod().expand_families(_family("Wound", ["wounds"], keep="y"))
    assert set(df["term"]) == {"wounds"}


def test_a_rejected_family_does_not_add_its_canonical():
    df = _mod().expand_families(_family("Wound", ["wounds"], keep="n"))
    assert set(df["term"]) == {"wounds"}


def test_an_unmarked_family_does_not_add_its_canonical():
    df = _mod().expand_families(_family("Wound", ["wounds"]))
    assert set(df["term"]) == {"wounds"}


def test_a_correction_restating_the_canonical_adds_nothing():
    df = _mod().expand_families(_family("Wound", ["wounds"], corrected="Wound"))
    assert set(df["term"]) == {"wounds"}


def test_a_canonical_already_among_its_terms_is_not_duplicated():
    df = _mod().expand_families(
        _family("Wound", ["wounds", "Wound"], corrected="wound"))
    assert list(df["term"]).count("Wound") == 1


def test_a_reversal_moves_the_canonical_onto_the_chosen_term():
    m = _mod()
    d = m.decisions(m.expand_families(
        _family("wounds", ["Wound", "wound"], corrected="Wound")))
    assert d.reverse == {"Wound": "wounds"}
    assert d.repoint["wounds"] == "Wound"          # the canonical follows
    assert d.repoint["wound"] == "Wound"           # and so does the sibling


# ── A correction that names two terms is not a reversal ──────────────────────

DIABETES = _family("type 2 diabetes",
                   ["Diabetes Mellitus type 2", "diabetes mellitus type 2"],
                   corrected="Diabetes mellitus type 2")


def test_a_correction_matching_two_terms_writes_no_reversal():
    m = _mod()
    assert m.decisions(m.expand_families(DIABETES)).reverse == {}


def test_it_is_read_as_a_repoint_onto_what_the_curator_wrote():
    m = _mod()
    d = m.decisions(m.expand_families(DIABETES))
    assert set(d.repoint.values()) == {"Diabetes mellitus type 2"}
    assert set(d.repoint) == {"Diabetes Mellitus type 2", "diabetes mellitus type 2",
                              "type 2 diabetes"}


def test_the_ambiguity_is_reported_once_and_names_both_spellings():
    m = _mod()
    amb = m.decisions(m.expand_families(DIABETES)).ambiguous
    assert len(amb) == 1
    canonical, corrected, matches = amb[0]
    assert canonical == "type 2 diabetes"
    assert corrected == "Diabetes mellitus type 2"
    assert matches == ["Diabetes Mellitus type 2", "diabetes mellitus type 2"]


def test_one_case_insensitive_match_still_reverses():
    m = _mod()
    d = m.decisions(m.expand_families(
        _family("cases", ["Case"], corrected="case")))
    assert d.reverse == {"Case": "cases"}
    assert d.ambiguous == []


def test_a_verbatim_term_wins_over_its_case_variant():
    # the `angiogenesis` case: correcting to a spelling the family holds
    # verbatim reverses THAT row, whatever else matches case-insensitively
    m = _mod()
    d = m.decisions(m.expand_families(
        _family("Angiogenesis process", ["angiogenesis", "Angiogenesis"],
                corrected="angiogenesis")))
    assert d.reverse == {"angiogenesis": "Angiogenesis process"}
    assert d.repoint["Angiogenesis"] == "angiogenesis"
    assert d.ambiguous == []


def test_matching_is_scoped_to_the_family():
    # another family's spelling of the same word cannot make this one ambiguous
    m = _mod()
    df = pd.concat([_family("cases", ["Case"], corrected="case"),
                    _family("other", ["CASE"], keep="y")], ignore_index=True)
    d = m.decisions(m.expand_families(df))
    assert d.reverse == {"Case": "cases"}
    assert d.ambiguous == []


# ── End to end, against a real TermMappingAndGate ───────────────────────────────────

def _apply(mod, tmp_path, df, mapper):
    sheet = tmp_path / "sheet.csv"
    df.to_csv(sheet, index=False)
    mod.Orchestrator = lambda: SimpleNamespace(term_mapper=mapper)
    return mod.main(["prog", str(sheet), "--apply"])


def test_the_plural_canonical_really_leaves_the_mapping(tmp_path):
    mod = _mod()
    mapper = memory_mapper({"silver dressings": "silver-containing dressings",
                            "silver-containing dressings": "silver dressing products"})
    _apply(mod, tmp_path, _family("silver-containing dressings", ["silver dressings"],
                                  corrected="silver-containing dressing"), mapper)
    assert mapper.mapping["silver-containing dressings"] == "silver-containing dressing"
    assert mapper.mapping["silver dressings"] == "silver-containing dressing"


def test_the_two_spellings_land_on_one_canonical(tmp_path):
    mod = _mod()
    mapper = memory_mapper({"Diabetes Mellitus type 2": "type 2 diabetes",
                            "diabetes mellitus type 2": "type 2 diabetes"})
    _apply(mod, tmp_path, DIABETES, mapper)
    assert mapper.mapping["Diabetes Mellitus type 2"] == "Diabetes mellitus type 2"
    assert mapper.mapping["diabetes mellitus type 2"] == "Diabetes mellitus type 2"
    assert mapper.mapping["type 2 diabetes"] == "Diabetes mellitus type 2"
