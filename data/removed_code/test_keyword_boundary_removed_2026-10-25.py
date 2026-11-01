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
    """The term is `practice` now, not `practices`.

    Pass 0 made the store singular (rule 43) and the curation lists are
    generated from the gate, so both sides carry the singular. `TermList.match`
    folds case and punctuation but deliberately does NOT singularise — see
    `test_the_matcher_does_not_singularise_and_that_is_measured` below.
    """
    from wound_ontology.store.blocker import Blocker
    b = Blocker()
    assert b.is_blocked("practice")
    assert b.is_blocked("mortality prediction")


def test_the_matcher_does_not_singularise_and_that_is_measured():
    """It is the obvious next step after rule 44, and it is wrong.

    Making `TermList.match` compare on `normalise(...).key` would let a list
    entry catch both spellings, which sounds strictly better. Measured on the
    86,489 names of the 2026-09-26 store it blocks **74 more**, and they are
    not methodology: `Head and neck squamous cell carcinoma`, `CD8 T cell`,
    `Incompetent perforator vein`, `Primary closure`, `NLRP3-deficient mouse`,
    `antimicrobial ion`. Singular forms of blocklist entries collide with
    clinical content in a way the plural forms did not.

    The store is singular now, so the list and the names it is matched against
    already agree; folding harder buys nothing and costs those 74.
    """
    from wound_ontology.store.term_lists import BlockList
    lst = BlockList()
    assert lst.match("caregiving practice"), "the list moved; pick another entry"
    assert not lst.match("caregiving practices"), (
        "the matcher started singularising; re-measure before allowing it — "
        "it blocked 74 clinical terms last time, including "
        "'Head and neck squamous cell carcinoma'")


def test_the_deliberate_whitelist_entries_still_hold():
    """Two terms were kept in scope on purpose and must survive both fixes."""
    from wound_ontology.store.blocker import Blocker
    b = Blocker()
    assert not b.is_blocked("amputation-free survival")
    assert not b.is_blocked("wound area reduction")


def test_a_list_nobody_loaded_does_not_answer_no():
    """`BlockList().match(...)` used to return False for everything.

    A list that has never read its file holds the empty set, so every question
    got a confident "not on the list" about terms that are on it. An empty
    list is a legitimate state, so emptiness cannot be the signal — whether
    `load` has run is.
    """
    from wound_ontology.store.term_lists import BlockKeywordList, BlockList
    assert BlockList().match("caregiving practice")
    assert BlockKeywordList().match("randomized trial")
