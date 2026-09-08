# -*- coding: utf-8 -*-
"""The BFO category vocabulary is spelled the way BFO spells it.

Decided 2026-09-08 (INSTRUCTIONS rule 25). The vocabulary was CamelCase, and
CamelCase is the one spelling `normalize_term` cannot express: it lowercases and
turns `-`/`_` into spaces, and CamelCase has no separator to turn, so
`MaterialEntity` came out welded as `materialentity`. Four silent defects came
out of that mismatch.

Two claims are worth pinning, because the whole rename rests on them:

  1. every category name survives normalisation UNCHANGED, so a missed guard
     can at worst change case, never destroy the name;
  2. 14 of the 15 names are BFO's own label for the IRI they declare, so a
     lookup that should never happen still cannot mint a duplicate class. The
     fifteenth, `information entity`, is a name we chose; see NAMED_BY_US.

Everything else here guards the migration: a cache written under the old
spelling must keep reading correctly, or the rename is a silent data loss.
"""
from __future__ import annotations

import pytest

from wound_ontology.llm.category_vocab import (
    category_iri,
    declared_category,
    is_category,
    squash,
)
from wound_ontology.llm.extraction_models import (
    BFOCategory,
    CATEGORY_IRI,
    CATEGORY_PARENT,
    COARSE_CATEGORIES,
)
from wound_ontology.utils.label_match import fold
from wound_ontology.utils.string_utils import normalize_term, smart_title

CATEGORIES = sorted(CATEGORY_PARENT)


# ── the two claims ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", CATEGORIES)
def test_normalisation_leaves_every_category_name_alone(name):
    """The claim the rename exists to make true.

    Under CamelCase this failed for all seven multi-word names:
    `normalize_term('MaterialEntity')` was `'materialentity'`, which is not a
    category, so `target in CATEGORY_PARENT` stopped seeing the typing.
    """
    assert normalize_term(name) == name


@pytest.mark.parametrize("name", CATEGORIES)
def test_folding_leaves_every_category_name_alone(name):
    """`fold` is normalisation plus singularisation -- the exporter's key."""
    assert fold(name) == name


@pytest.mark.parametrize("name", CATEGORIES)
def test_a_category_name_is_lowercase_words_separated_by_spaces(name):
    assert name == name.lower()
    assert "_" not in name and "-" not in name
    assert name.split() == name.split(" ")   # single spaces, no leading/trailing


@pytest.mark.parametrize("name", CATEGORIES)
def test_title_casing_a_category_still_reads_back_as_one(name):
    """The hierarchy holds class labels and title-cases them, so a category
    goes in as `material entity` and comes back as `Material Entity`. It has to
    survive the round trip, or reconciliation loses it on the way home."""
    assert declared_category(smart_title(name)) == name


# ── recognition ────────────────────────────────────────────────────────────
LEGACY = {"".join(w.capitalize() for w in n.split()): n for n in CATEGORIES}


@pytest.mark.parametrize("legacy,declared", sorted(LEGACY.items()))
def test_a_cache_written_under_the_old_spelling_still_reads(legacy, declared):
    """Every store, hierarchy and matrix on disk predates the rename."""
    assert declared_category(legacy) == declared


@pytest.mark.parametrize("name", CATEGORIES)
def test_the_damaged_spelling_still_reads(name):
    """`Materialentity` is what the old `normalize_term` left behind. A store
    normalised before the guard existed still holds it."""
    damaged = smart_title(normalize_term("".join(w.capitalize()
                                                 for w in name.split())))
    assert declared_category(damaged) == name


def test_an_ordinary_term_is_not_a_category():
    for term in ("Wound", "Chronic Wound", "Necrosis", "material", "entity",
                 "Material Entity Wound", ""):
        assert declared_category(term) is None, term
        assert not is_category(term), term


def test_no_two_categories_collapse_to_one_key():
    """Separator-blind matching is only safe while the names stay distinct
    without their separators."""
    assert len({squash(c) for c in CATEGORIES}) == len(CATEGORIES)


# ── the declaration ────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", CATEGORIES)
def test_every_category_declares_an_iri(name):
    assert category_iri(name) == CATEGORY_IRI[name]
    assert str(CATEGORY_IRI[name]).startswith("http")


def test_the_enum_value_is_the_vocabulary_and_the_member_is_only_an_identifier():
    """`BFOCategory.MaterialEntity` is a Python name; `'material entity'` is the
    value that reaches the store. Only the value is ever compared."""
    assert BFOCategory.MaterialEntity.value == "material entity"
    assert BFOCategory.ProcessBoundary.value == "process boundary"
    assert {c.value for c in BFOCategory} == set(CATEGORIES)


def test_the_tree_is_closed_over_the_declared_names():
    """Every parent named in the tree is itself a declared category."""
    for child, parent in CATEGORY_PARENT.items():
        assert declared_category(child) == child
        if parent is not None:
            assert declared_category(parent) == parent, (child, parent)
    assert COARSE_CATEGORIES <= set(CATEGORIES)


# ── the ontology agrees ────────────────────────────────────────────────────
#: The one category whose name is NOT the ontology's label for its IRI, and why.
#: BFO_0000031 is `generically dependent continuant`; the pipeline calls it
#: `information entity` because that is what the extractor is being asked to
#: recognise, and a model asked to pick "generically dependent continuant" for a
#: measurement datum will not. The consequence is narrow and worth naming: for
#: this one category the "even a lookup would find it" safety net does not
#: apply, so the declaration in rule 20 is the only thing placing it.
NAMED_BY_US = {"information entity": "generically dependent continuant"}


def test_a_category_name_is_the_label_the_ontology_carries():
    """The second claim: a category's name IS the label its IRI carries.

    That is what makes the exporter's minted-duplicate bug impossible rather
    than merely guarded — even a lookup finds the right class. It holds for 14
    of the 15; the exception is declared above, and this fails if a sixteenth
    appears or if the exception ever silently becomes the rule.
    """
    import rdflib
    from rdflib.namespace import RDFS

    from config.settings import (GROUND_TRUTH_TTL, MILD_MODULES_DIR, MILD_TTL)

    g = rdflib.Graph()
    g.parse(str(GROUND_TRUTH_TTL), format="turtle")
    g.parse(str(MILD_TTL), format="turtle")
    modules = sorted(MILD_MODULES_DIR.glob("*_module.owl"))
    assert modules, f"no MILD modules found under {MILD_MODULES_DIR}"
    broken = []
    for module in modules:
        try:
            g.parse(str(module))
        except Exception as exc:               # noqa: BLE001 -- re-raised below
            broken.append(f"{module.name}: {type(exc).__name__}: {exc}")
    if broken:
        raise RuntimeError(
            "MILD modules failed to parse, so a category IRI could look "
            "unlabelled when it is merely unloaded and this test would pass by "
            "checking fewer of them:\n  " + "\n  ".join(broken)
        )

    agree, differ, unlabelled = [], {}, []
    for name, iri in CATEGORY_IRI.items():
        labels = [str(o) for o in g.objects(rdflib.URIRef(iri), RDFS.label)]
        if not labels:
            unlabelled.append(name)
        elif any(declared_category(lab) == name for lab in labels):
            agree.append(name)
        else:
            differ[name] = sorted(labels)

    assert unlabelled == [], f"category IRI carries no label at all: {unlabelled}"
    assert set(differ) == set(NAMED_BY_US), (
        f"name/label agreement changed. differs now: {differ}, "
        f"declared exceptions: {NAMED_BY_US}")
    for name, labels in differ.items():
        assert NAMED_BY_US[name] in labels, (name, labels)
    assert len(agree) == len(CATEGORY_IRI) - len(NAMED_BY_US)


def test_the_one_name_we_chose_ourselves_still_declares_the_right_iri():
    """`information entity` is ours, so nothing else can vouch for it."""
    assert category_iri("information entity") == \
        "http://purl.obolibrary.org/obo/BFO_0000031"
