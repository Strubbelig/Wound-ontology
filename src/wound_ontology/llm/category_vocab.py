# -*- coding: utf-8 -*-
"""The BFO category vocabulary, and the one way to recognise a name in it.

Hand-written on purpose. `extraction_models.py` is generated and holds the
vocabulary as data; the single rule for matching a string against it lives here,
so regenerating the schema never clobbers the rule and the rule has exactly one
implementation.

The vocabulary is spelled the way BFO spells it -- lowercase, words separated by
spaces: `material entity`, `process boundary`, `specifically dependent
continuant`. It was CamelCase until 2026-09-08, and CamelCase is the one
spelling `normalize_term` cannot express: it lowercases and turns `-` and `_`
into spaces, and CamelCase has no separator to turn, so `MaterialEntity` came
out welded as `materialentity` rather than split as `material entity`. Four
silent defects came out of that single mismatch -- 1770 exported classes with no
path to BFO, 98 unreported class merges, a category reconciler blind to half the
corpus, and a term mapping that could only ever be applied once.

In this spelling normalisation is idempotent, so the worst a missed guard can do
is change case, and the name is identical to the label BFO itself carries, so a
lookup that should never happen cannot mint a duplicate class even when it does.

A category is DECLARED, never matched (INSTRUCTIONS rules 20, 22, 25). Nothing
here fuzzy-matches a term against the vocabulary: `declared_category` answers
only for a string that already IS one of the fifteen names, under any separator
or casing. That tolerance is not fuzziness -- it is what lets a cache written
under the old CamelCase spelling still read correctly today.
"""
from __future__ import annotations

import re

from wound_ontology.llm.extraction_models import CATEGORY_IRI, CATEGORY_PARENT

_SEPARATORS = re.compile(r"[^a-z0-9]")


def squash(name: str) -> str:
    """The separator-blind key for a category name.

    `MaterialEntity`, `Material Entity`, `material_entity`, `material entity`
    and the damaged `Materialentity` all collapse to `materialentity`.
    """
    return _SEPARATORS.sub("", name.strip().lower())


#: squashed key -> the one declared spelling.
_BY_KEY: dict[str, str] = {squash(name): name for name in CATEGORY_PARENT}

if len(_BY_KEY) != len(CATEGORY_PARENT):
    raise RuntimeError(
        "two BFO categories collapse to the same separator-blind key; "
        "declared_category could not tell them apart"
    )


def declared_category(name: str) -> str | None:
    """The declared spelling of `name`, or None if it is not a category at all."""
    return _BY_KEY.get(squash(name))


def is_category(name: str) -> bool:
    """True when `name` is one of the fifteen, however it is spelled."""
    return squash(name) in _BY_KEY


def category_iri(name: str) -> str | None:
    """The BFO/MILD IRI this category names, read off the declaration.

    None when `name` is not a category. It is never looked up in a label index:
    a closed vocabulary with a known IRI has nothing to gain from matching and
    everything to lose from it.
    """
    declared = declared_category(name)
    return None if declared is None else CATEGORY_IRI[declared]
