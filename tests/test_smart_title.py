"""Label normalisation must not destroy acronyms, units or roman numerals.

`str.title()` was the normalisation key everywhere, so "MRSA infection" became
"Mrsa Infection" and "CO2 bath wound therapy" became "Co2 Bath Wound Therapy".
That mangled form was then the key used for matching and for label grounding.
"""
import pytest

from wound_ontology.utils.string_utils import smart_title


@pytest.mark.parametrize("raw,expected", [
    ("CO2 bath wound therapy", "CO2 Bath Wound Therapy"),
    ("MRSA infection", "MRSA Infection"),
    ("NPWT dressing", "NPWT Dressing"),
    ("pH value", "pH Value"),
    ("type II diabetes", "Type II Diabetes"),
    ("CUSA(r) assisted debridement", "CUSA(r) Assisted Debridement"),
    ("V.A.C. therapy", "V.A.C. Therapy"),
])
def test_case_bearing_terms_survive(raw, expected):
    assert smart_title(raw) == expected


@pytest.mark.parametrize("raw", [
    "chronic wound",
    "wound bed preparation",
    "full-thickness wound",
    "deep-partial thickness",
    "wound gel/ointment/cream",
])
def test_ordinary_terms_match_str_title(raw):
    """No gratuitous divergence: plain lowercase phrases behave as before."""
    assert smart_title(raw) == raw.title()


def test_capitalises_across_slash_and_hyphen():
    assert smart_title("gel/ointment/cream") == "Gel/Ointment/Cream"
    assert smart_title("full-thickness") == "Full-Thickness"


def test_is_idempotent():
    for s in ["MRSA infection", "chronic wound", "CO2 bath", "wound gel/ointment/cream"]:
        once = smart_title(s)
        assert smart_title(once) == once


def test_strips_and_preserves_internal_spacing():
    assert smart_title("  chronic wound  ") == "Chronic Wound"


def test_empty_and_degenerate_input():
    assert smart_title("") == ""
    assert smart_title("   ") == ""
