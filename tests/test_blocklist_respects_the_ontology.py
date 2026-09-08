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


#: Curated labels the NOISE REGEX still rejects, and why each is a false
#: positive. This is a different mechanism from the two lists: `is_noise` runs
#: BEFORE the whitelist in `Blocker.is_blocked`, so whitelisting cannot free
#: them -- a heuristic currently outranks an explicit human decision. Latent
#: rather than active: 0 live store terms match the noise regex today, and none
#: of these six is in the store. Listed so the gap is named rather than found
#: again later.
NOISE_FALSE_POSITIVES = {
    "NaCl 0.9%":                    "the % rule; a saline concentration is a real class",
    "NaCl 10%":                     "the % rule",
    "Wagner and Anderson grade 1D": "the `\\d+ ... d|day|days` rule fires on the D of 1D",
    "Wagner and Anderson grade 2D": "same",
    "Wagner and Anderson grade 3D": "same",
    "Wagner and Anderson grade 4D": "same",
}


def test_no_curated_class_label_is_blocked_by_a_list(blocker, curated_labels):
    """The invariant. The noise regex is excluded and pinned separately below."""
    blocked = sorted(
        label for label in curated_labels.values()
        if label not in NOISE_FALSE_POSITIVES
        and (blocker.block_kw.match(label) or blocker.terms.match(label))
        and not (blocker.white_terms.match(label) or blocker.white_kw.match(label))
    )
    assert blocked == [], (
        "the curated ontology asserts a class for these, so they are domain "
        f"vocabulary, and run_clean_store deletes what it matches: {blocked}"
    )


def test_no_curated_class_label_is_blocked_in_effect(blocker, curated_labels):
    """The same claim through the public method, so precedence is covered too."""
    blocked = sorted(
        label for label in curated_labels.values()
        if label not in NOISE_FALSE_POSITIVES and blocker.is_blocked(label)
    )
    assert blocked == [], f"blocked despite naming a curated class: {blocked}"


@pytest.mark.parametrize("label", sorted(NOISE_FALSE_POSITIVES))
def test_the_known_noise_false_positives_are_still_exactly_those(blocker, label):
    """If one starts passing, delete its entry — the gap narrowed.

    If a SEVENTH appears, the test above fails and names it, which is the point.
    """
    assert blocker.is_noise(label), (
        f"{label!r} is no longer rejected by the noise regex; remove it from "
        "NOISE_FALSE_POSITIVES so the exception list stays honest"
    )


def test_the_whitelist_outranks_both_blocklists(blocker):
    """What actually freed the 33, and the reason removal alone was not enough.

    `pain management` is a WONT class (WONT_0000222) and the KEYWORD_BLOCKLIST
    holds `pain`, so taking it out of METHODOLOGY_BLOCKLIST would have left it
    blocked by the keyword.
    """
    assert blocker.block_kw.match("pain management")
    assert blocker.white_terms.match("pain management")
    assert not blocker.is_blocked("pain management")


def test_the_methodology_keywords_still_block_methodology(blocker):
    """Freeing the domain terms must not have opened the gate generally."""
    for term in ("randomized controlled trial", "systematic review",
                 "propensity score matching", "machine learning framework",
                 "inter-rater reliability"):
        assert blocker.is_blocked(term), term
