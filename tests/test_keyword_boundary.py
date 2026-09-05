"""A keyword may not fire from inside another word.

The keyword lists match by substring on purpose — `wound` should whitelist
"wound bed" — but a three-character entry turns that into a wildcard. `cti`
matched "pra*cti*ces", "mortality predi*cti*on" and "Antibacterial
fun*cti*onality": 287 store terms exempted from the blocklist by coincidence.
Measured on the live store, 1191 of 3725 terms were keyword-whitelisted and 288
of those only through a mid-word hit.

Requiring a word boundary at the start keeps what the lists are for and closes
the wildcard. Twenty other entries of four characters or fewer carried the same
hazard: `male` matched "female", `race` matched "traceability".
"""
import pytest

from wound_ontology.store.term_lists import _starts_a_word


@pytest.mark.parametrize("keyword,text", [
    ("burn", "burn wound"),
    ("burn", "burns"),                 # a trailing plural still matches
    ("wound", "chronic wound"),        # mid-phrase, but at a word start
    ("male", "male patient"),
    ("gel", "gel dressing"),
])
def test_a_keyword_at_a_word_start_matches(keyword, text):
    assert _starts_a_word(keyword, text)


@pytest.mark.parametrize("keyword,text", [
    ("cti", "practices"),
    ("cti", "mortality prediction"),
    ("cti", "antibacterial functionality"),
    ("male", "female"),
    ("race", "traceability"),
    ("burn", "sunburn"),
])
def test_a_keyword_inside_a_word_does_not(keyword, text):
    assert not _starts_a_word(keyword, text)


def test_a_later_occurrence_still_counts():
    """The first hit may be mid-word while a real one follows."""
    assert _starts_a_word("cti", "practices ctible")


def test_the_cti_entry_is_gone_from_the_whitelist():
    """Both fixes were asked for: the bad entry, and the rule that let it do
    this much damage."""
    from config.whitelist import KEYWORD_WHITELIST
    assert "cti" not in KEYWORD_WHITELIST


def test_practices_is_blocked_again():
    from wound_ontology.store.blocker import Blocker
    b = Blocker()
    assert b.is_blocked("practices")
    assert b.is_blocked("mortality prediction")


def test_the_deliberate_whitelist_entries_still_hold():
    """Two terms were kept in scope on purpose and must survive both fixes."""
    from wound_ontology.store.blocker import Blocker
    b = Blocker()
    assert not b.is_blocked("amputation-free survival")
    assert not b.is_blocked("wound area reduction")
