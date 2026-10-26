# -*- coding: utf-8 -*-
"""A term the curated ontology has a class for is not methodology.

`METHODOLOGY_BLOCKLIST` is for study-design vocabulary -- "randomised controlled
trial", "inclusion criteria" -- and `run_clean_store` DELETES what it matches
rather than flagging it (rule 5 quarantines; this list predates it). It had
grown, quietly, to hold 33 terms that WONT or MILD assert a class for: `skin`
(FMA_7163), `gangrene` (HP_0100758), `Staphylococcus aureus` (NCBITaxon_1280),
`Compression therapy` (WONT_0000077), `Malignancy` (WONT_0000465). Nothing
reported it, because a deletion by blocklist looks exactly like a term the
abstracts never mentioned.

The criterion is the ontology's own testimony and nothing softer, which is why
it can be a test rather than a one-off tidy: **if a curated source asserts a
class with this label, the term is domain vocabulary.** Found and moved on
2026-09-08; this is what stops it drifting back.

The whitelist is what does the freeing, not removal from the blocklist alone --
`Blocker.is_blocked` consults it before both the term and keyword lists, and
`pain management`, `patient education` and `painful` are caught by the
KEYWORD_BLOCKLIST entries `pain` and `education` as well. Those keywords stay:
`pain score` and `patient education programme evaluation` really are study
instruments.
"""
from __future__ import annotations

import pytest

from wound_ontology.utils.label_match import fold


@pytest.fixture(scope="module")
def blocker():
    from wound_ontology.store.store_cleaner import StoreCleaner

    c = StoreCleaner([])
    c._reload_lists()
    return c.blocker


@pytest.fixture(scope="module")
def curated_labels() -> dict[str, str]:
    """fold(label) -> label, for every class WONT and MILD assert."""
    from rdflib.namespace import RDFS

    from wound_ontology.hierarchies.curated_seed import default_curated_sources
    from wound_ontology.utils.rdf_io import parse_graph

    sources, _ = default_curated_sources()
    assert sources, "no curated sources found; this test would be vacuous"
    out: dict[str, str] = {}
    for src in sources:
        g = parse_graph(src)
        for _, _, o in g.triples((None, RDFS.label, None)):
            text = str(o).strip()
            if text:
                out.setdefault(fold(text), text)
    assert out, "curated sources carry no rdfs:label at all"
    return out


#: Curated labels the noise regex STILL matches, freed by an explicit WHITELIST
#: entry now that `Blocker.is_blocked` consults the whitelist FIRST.
#:
#: The precedence used to run the other way, which put a guess about a string's
#: shape above a curator's decision about a concept: no whitelist entry could
#: reach these, and the only remedy would have been to weaken the regex for
#: every term in the corpus. Four more labels used to be here -- Wagner and
#: Anderson grades 1D through 4D -- and are gone because the regex itself was
#: narrowed rather than overridden; see `test_a_grade_code_is_not_a_duration`.
#:
#: If one of these stops matching the regex, delete its entry: the gap narrowed.
#: If a THIRD appears, `test_no_curated_class_label_is_blocked_in_effect` fails
#: and names it, which is the point.
NOISE_MATCHED_BUT_WHITELISTED = {
    "NaCl 0.9%": "WONT_0000208",
    "NaCl 10%":  "WONT_0000209",
}


def test_no_curated_class_label_is_blocked_by_a_list(blocker, curated_labels):
    """The invariant, at the level of the two lists alone."""
    blocked = sorted(
        label for label in curated_labels.values()
        if (blocker.block_kw.match(label) or blocker.terms.match(label))
        and not (blocker.white_terms.match(label) or blocker.white_kw.match(label))
    )
    assert blocked == [], (
        "the curated ontology asserts a class for these, so they are domain "
        f"vocabulary, and run_clean_store deletes what it matches: {blocked}"
    )


def test_no_curated_class_label_is_blocked_in_effect(blocker, curated_labels):
    """The same claim through the public method, and now with NO exceptions.

    This test carried an exclusion list of six until 2026-09-09. It does not any
    more: four were freed by narrowing the noise regex and two by whitelisting
    them, so the claim is finally the flat one it always wanted to be -- the
    curated ontology's own labels all survive the lists.
    """
    blocked = sorted(
        label for label in curated_labels.values() if blocker.is_blocked(label)
    )
    assert blocked == [], f"blocked despite naming a curated class: {blocked}"


@pytest.mark.parametrize("label,iri", sorted(NOISE_MATCHED_BUT_WHITELISTED.items()))
def test_a_whitelist_entry_outranks_the_noise_regex(blocker, label, iri):
    """Freed by a decision, not by the regex having been quietly weakened.

    Both halves matter. If the first assertion starts failing the regex changed
    and the entry should go; if the second fails the precedence regressed.
    """
    assert blocker.is_noise(label), (
        f"{label!r} no longer matches the noise regex; remove it from "
        "NOISE_MATCHED_BUT_WHITELISTED so the exception list stays honest"
    )
    assert blocker.white_terms.match(label), f"{label!r} ({iri}) lost its WHITELIST entry"
    assert not blocker.is_blocked(label)


@pytest.mark.parametrize("grade", ["1D", "2D", "3D", "4D"])
def test_a_grade_code_is_not_a_duration(blocker, grade):
    r"""`\d+d` closed up used to read a grade code as a count of days.

    "Wagner and Anderson grade 1D" (WONT_120068) was deleted as "1 day", and 2D,
    3D and 4D with it. Measured over the 4104 store terms and curated labels,
    the bare `d` alternative matched those four and not one genuine day
    expression, so it now requires a separator from its number.
    """
    assert not blocker.is_noise(f"Wagner and Anderson grade {grade}")
    assert not blocker.is_blocked(f"Wagner and Anderson grade {grade}")


def test_a_separated_day_abbreviation_is_still_noise(blocker):
    """The half of the `d` rule that was worth keeping."""
    for term in ("7 d", "7-d", "14 d", "7 days", "7days", "3 day"):
        assert blocker.is_noise(term), term


def test_the_price_of_narrowing_the_day_rule(blocker):
    """Named so the cost is a decision on the record, not a surprise later.

    "7d" written closed up is no longer read as a duration. Nothing in the
    corpus was written that way, and the asymmetry settles it: a term wrongly
    let through reaches the store and can still be blocked, while
    `run_clean_store` DELETES what the blocklist matches.
    """
    assert not blocker.is_noise("7d")


def test_score_and_is_blocked_agree_about_precedence(blocker):
    """`score` duplicates the ladder in `is_blocked`; it must move in step."""
    for term in ("NaCl 0.9%", "Wagner and Anderson grade 1D", "100 mg",
                 "randomized controlled trial", "granulation tissue"):
        assert (blocker.score(term) == 100.0) is blocker.is_blocked(term), term


def test_the_whitelist_outranks_both_blocklists(blocker):
    """What actually freed the 33, and the reason removal alone was not enough.

    `Patient education` is a WONT class and the KEYWORD_BLOCKLIST holds
    `education`, so taking it out of METHODOLOGY_BLOCKLIST would have left it
    blocked by the keyword. Only the whitelist outranking both frees it.

    This was written against `pain management` and WONT_0000222, which made
    the same point while `pain` was a keyword. The curator ruled the concept
    in scope on 2026-09-26 and it came off KEYWORD_BLOCKLIST, so that term no
    longer exercises the keyword branch — it is kept below, because it must
    still come out unblocked, but the branch needs a term the keyword list
    still catches.
    """
    assert blocker.block_kw.match("Patient education")
    assert blocker.white_terms.match("Patient education")
    assert not blocker.is_blocked("Patient education")

    # the original case: still a WONT class, still not blocked, no longer
    # reached by a keyword at all
    assert not blocker.is_blocked("pain management")


def test_the_methodology_keywords_still_block_methodology(blocker):
    """Freeing the domain terms must not have opened the gate generally."""
    for term in ("randomized controlled trial", "systematic review",
                 "propensity score matching", "machine learning framework",
                 "inter-rater reliability"):
        assert blocker.is_blocked(term), term
