"""Conceptual scaling: the lattice must not contradict the curated hierarchy.

FCA orders objects by attribute-set containment and nothing else. Before this,
the hierarchy only chose which *rows* entered the context, so a curated
subclass relation between two entities that shared no measured attribute was
invisible: the lattice put them side by side and was free to propose a
structure cutting across the taxonomy.

ontology_pipeline_upgrade_plan.md §2A.5 proposes adding each object's
superclasses as attributes. That alone does NOT deliver the guarantee it claims
-- see test_superclass_attributes_alone_do_not_force_the_order -- because a
parent may carry attributes the child lacks. Inheriting the ancestors' own
attributes is what makes the containment hold, and is sound because these are
class-level assertions: an axiom on a superclass holds of every subclass.
"""
import tempfile

import pandas as pd
import pytest

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy


class _Store:
    def __init__(self, entities):
        self.dict = {"1": {"entities": entities}}


@pytest.fixture
def store():
    return _Store({
        "Diabetic Foot Ulcer": {"has_quality: infected": 1.0, "occurs_in: foot": 1.0},
        "Chronic Wound":       {"has_quality: slow healing": 1.0},
        "Acute Wound":         {"has_quality: rapid healing": 1.0},
    })


@pytest.fixture
def hier():
    h = ClassHierarchy.__new__(ClassHierarchy)
    h._df = pd.DataFrame(dtype=float)
    h._prov, h._candidates = {}, {}
    h._prov_loaded = True
    h._set_edge("Diabetic Foot Ulcer", "Chronic Wound")
    h._set_edge("Chronic Wound", "Wound")
    h._set_edge("Acute Wound", "Wound")
    return h


def _context(store, **kwargs):
    cm = ContextMatrix(DataManager(tempfile.mkdtemp()), "ctx")
    cm._df = None
    cm.get_data(store, **kwargs)
    return cm.df.fillna(0.0)


def _attrs(df, entity):
    return set(df.columns[df.loc[entity] == 1.0])


# ── the guarantee ───────────────────────────────────────────────────────────

def test_unscaled_the_lattice_cannot_see_the_hierarchy(store, hier):
    """The state before this change, pinned so the fix cannot silently lapse."""
    df = _context(store)
    assert not _attrs(df, "Chronic Wound") <= _attrs(df, "Diabetic Foot Ulcer")


def test_superclass_attributes_alone_do_not_force_the_order(store, hier):
    """The plan's stated mechanism, on its own, does not deliver its stated
    guarantee: Chronic Wound keeps `has_quality: slow healing`, which DFU has
    not got, so DFU's attributes are still not a superset."""
    df = _context(store, scale_hierarchy=hier, inherit_attributes=False)
    assert "is_a: chronic wound" in df.columns
    assert not _attrs(df, "Chronic Wound") <= _attrs(df, "Diabetic Foot Ulcer")


def test_scaling_with_inheritance_forces_the_curated_order(store, hier):
    df = _context(store, scale_hierarchy=hier)
    assert _attrs(df, "Chronic Wound") <= _attrs(df, "Diabetic Foot Ulcer")


def test_siblings_are_not_collapsed(store, hier):
    """Forcing the order must not flatten everything into one chain: two
    children of Wound stay incomparable."""
    df = _context(store, scale_hierarchy=hier)
    acute, dfu = _attrs(df, "Acute Wound"), _attrs(df, "Diabetic Foot Ulcer")
    assert not acute <= dfu and not dfu <= acute


def test_grandparents_are_inherited_too(store, hier):
    df = _context(store, scale_hierarchy=hier)
    assert "is_a: wound" in _attrs(df, "Diabetic Foot Ulcer")


# ── what scaling must NOT do ────────────────────────────────────────────────

def test_scaling_adds_attributes_never_rows(store, hier):
    """An entity with no store attributes is not an object in the context, and
    scaling must not make it one."""
    hier._set_edge("Unmeasured Wound", "Wound")
    before = _context(store)
    after = _context(store, scale_hierarchy=hier)
    assert set(after.index) == set(before.index)
    assert "Unmeasured Wound" not in after.index


def test_scaling_is_not_subject_to_the_predicate_filter(store, hier):
    """Its purpose is to inject subsumption the filter would exclude."""
    df = _context(store, predicates=["has_quality"], scale_hierarchy=hier)
    assert "is_a: chronic wound" in df.columns
    assert not any(c.startswith("occurs_in") for c in df.columns)


def test_inheritance_reads_original_attributes_not_mutated_ones(hier):
    """A child must not receive an attribute its parent only acquired earlier in
    the same pass; otherwise the result depends on iteration order."""
    store = _Store({
        "Diabetic Foot Ulcer": {"has_quality: infected": 1.0},
        "Chronic Wound":       {"has_quality: slow healing": 1.0},
        "Acute Wound":         {"has_quality: rapid healing": 1.0},
    })
    df = _context(store, scale_hierarchy=hier)
    # Wound itself is not an object, so nothing may leak sideways from the
    # Acute Wound branch into the Diabetic Foot Ulcer branch.
    assert "has_quality: rapid healing" not in _attrs(df, "Diabetic Foot Ulcer")


def test_a_cycle_does_not_hang(store, hier):
    hier._set_edge("Wound", "Diabetic Foot Ulcer")     # cycle
    df = _context(store, scale_hierarchy=hier)
    assert not df.empty


def test_an_entity_with_no_superclass_is_left_alone(hier):
    store = _Store({"Orphan Term": {"has_quality: odd": 1.0}})
    df = _context(store, scale_hierarchy=hier)
    assert _attrs(df, "Orphan Term") == {"has_quality: odd"}


def test_scaling_is_reported(store, hier, capsys):
    _context(store, scale_hierarchy=hier)
    out = capsys.readouterr().out
    assert "Conceptual scaling" in out
    assert "inherited attributes" in out


def test_no_superclass_anywhere_warns_rather_than_passing_silently(capsys):
    """Scaling that changes nothing means an unconstrained lattice — the caller
    has to hear about it, not read it off a concept count later."""
    empty = ClassHierarchy.__new__(ClassHierarchy)
    empty._df = pd.DataFrame(dtype=float)
    empty._prov, empty._candidates = {}, {}
    empty._prov_loaded = True
    _context(_Store({"A": {"has_quality: x": 1.0}}), scale_hierarchy=empty)
    assert "WARNING" in capsys.readouterr().out


# ── name normalization (found only on real data) ────────────────────────────

def test_store_names_are_normalized_before_the_hierarchy_lookup(hier):
    """The store keys entities as extracted; the hierarchy keys them
    smart_title'd. On a real store only 302 of 4180 names matched verbatim, so
    looking up the rest raw returned "no ancestors" — silently scaling 7% of
    objects and leaving the other 93% bare, which MANUFACTURED order violations
    (29 -> 42) instead of removing them."""
    store = _Store({
        "diabetic foot ulcer": {"has_quality: infected": 1.0},
        "chronic wound":       {"has_quality: slow healing": 1.0},
    })
    df = _context(store, scale_hierarchy=hier)
    assert "is_a: chronic wound" in df.columns, "raw store name found no ancestors"
    assert _attrs(df, "Chronic Wound") <= _attrs(df, "Diabetic Foot Ulcer")


def test_inheritance_finds_an_ancestor_stored_under_a_different_case(hier):
    """The mirror of the above: the ancestor name comes from the hierarchy
    ('Wound'), the snapshot is keyed by store name ('wound'). Missing that,
    every subclass of Wound inherited nothing and the guarantee failed on
    exactly the edges it exists to protect."""
    store = _Store({
        "wound":               {"has_quality: wound area": 1.0},
        "Angiopathic Wound":   {"has_quality: ischaemic": 1.0},
    })
    hier._set_edge("Angiopathic Wound", "Wound")
    df = _context(store, scale_hierarchy=hier)
    assert "has_quality: wound area" in _attrs(df, "Angiopathic Wound")


def test_ancestors_of_normalizes_its_argument(hier):
    assert hier.ancestors_of("diabetic foot ulcer") == {"Chronic Wound", "Wound"}
    assert hier.ancestors_of("Diabetic Foot Ulcer") == {"Chronic Wound", "Wound"}
    # smart_title deliberately preserves all-caps tokens so acronyms survive
    # (MRSA, CUSA, pH), so an all-caps name is a DIFFERENT key — consistently
    # so on both sides, since the store is normalized the same way.
    assert hier.ancestors_of("DIABETIC FOOT ULCER") == set()


# ── ancestors_of ────────────────────────────────────────────────────────────

def test_ancestors_of_is_transitive_and_excludes_self(hier):
    assert hier.ancestors_of("Diabetic Foot Ulcer") == {"Chronic Wound", "Wound"}
    assert hier.ancestors_of("Wound") == set()
    assert hier.ancestors_of("Not In Hierarchy") == set()


def test_ancestors_of_survives_a_cycle(hier):
    hier._set_edge("Wound", "Diabetic Foot Ulcer")
    assert "Wound" in hier.ancestors_of("Diabetic Foot Ulcer")
