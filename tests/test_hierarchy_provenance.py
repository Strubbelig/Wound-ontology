"""Subsumption arrives from three sources; they are not equally trustworthy.

curated (human CSV) > text (asserted in a document) > fca (lattice suggestion).
Before C4 all three landed in the same 0/1 matrix with no record of which
produced an edge, and FCA extents were written straight into class_hier.
"""
import pandas as pd
import pytest

from wound_ontology.hierarchies.base_hierarchy import (
    SOURCE_CURATED,
    SOURCE_FCA,
    SOURCE_RANK,
    SOURCE_TEXT,
)
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy


class MockDM:
    def __init__(self):
        self.saved = {}

    def load_latest_csv(self, name):
        return self.saved.get(name)

    def save_as_csv(self, df, name):
        self.saved[name] = df


@pytest.fixture
def hier():
    return ClassHierarchy(MockDM())


STORE = {
    "1": {"entities": {
        "Chronic Wound": {"is_a: Wound": 1.0},
        "Acute Wound": {"is_a: Wound": 1.0},
    }}
}


class FakeStore:
    dict = STORE


def test_ranking_is_explicit():
    assert SOURCE_RANK[SOURCE_CURATED] > SOURCE_RANK[SOURCE_TEXT] > SOURCE_RANK[SOURCE_FCA]


def test_store_edges_are_text_asserted(hier):
    hier.get_data(FakeStore())
    assert hier.source_of("Chronic Wound", "Wound") == SOURCE_TEXT


def test_curated_outranks_text(hier):
    hier.get_data(FakeStore())
    hier.apply_curated(pd.DataFrame({"Class": ["Chronic Wound"], "Parent class": ["Wound"]}))
    assert hier.source_of("Chronic Wound", "Wound") == SOURCE_CURATED


def test_fca_cannot_overwrite_curated(hier):
    hier._set_edge("Chronic Wound", "Wound", source=SOURCE_CURATED)
    wrote = hier._set_edge("Chronic Wound", "Wound", source=SOURCE_FCA)
    assert wrote is False
    assert hier.source_of("Chronic Wound", "Wound") == SOURCE_CURATED


def test_fca_cannot_overwrite_text(hier):
    hier._set_edge("Chronic Wound", "Wound", source=SOURCE_TEXT)
    assert hier._set_edge("Chronic Wound", "Wound", source=SOURCE_FCA) is False
    assert hier.source_of("Chronic Wound", "Wound") == SOURCE_TEXT


def test_curated_upgrade_is_reported_as_written(hier):
    hier._set_edge("Chronic Wound", "Wound", source=SOURCE_TEXT)
    assert hier._set_edge("Chronic Wound", "Wound", source=SOURCE_CURATED) is True


def test_fca_edges_are_candidates_not_commitments(hier):
    hier.propose_edge("Chronic Wound", "Moist Wound", SOURCE_FCA)
    assert ("Chronic Wound", "Moist Wound") in hier.candidates
    assert "Moist Wound" not in hier.parents_of("Chronic Wound")
    assert hier.source_of("Chronic Wound", "Moist Wound") is None


def test_candidates_can_be_promoted_after_review(hier):
    hier.propose_edge("Chronic Wound", "Moist Wound", SOURCE_FCA)
    assert hier.promote_candidates() == 1
    assert hier.source_of("Chronic Wound", "Moist Wound") == SOURCE_FCA
    assert hier.candidates == {}


def test_selective_promotion(hier):
    hier.propose_edge("A", "B", SOURCE_FCA)
    hier.propose_edge("C", "D", SOURCE_FCA)
    assert hier.promote_candidates(only={("A", "B")}) == 1
    assert ("C", "D") in hier.candidates


def test_already_committed_edge_is_not_proposed(hier):
    hier._set_edge("Chronic Wound", "Wound", source=SOURCE_CURATED)
    hier.propose_edge("Chronic Wound", "Wound", SOURCE_FCA)
    assert hier.candidates == {}


def test_get_data_preserves_curated_attribution(hier):
    """Rebuilding from the store must not silently demote curated edges."""
    hier._set_edge("Chronic Wound", "Wound", source=SOURCE_CURATED)
    hier.get_data(FakeStore())
    assert hier.source_of("Chronic Wound", "Wound") == SOURCE_CURATED
    assert hier.source_of("Acute Wound", "Wound") == SOURCE_TEXT


def test_provenance_round_trips_through_save(hier):
    hier._set_edge("Chronic Wound", "Wound", source=SOURCE_CURATED)
    hier.save()
    reloaded = ClassHierarchy(hier.dm)
    assert reloaded.source_of("Chronic Wound", "Wound") == SOURCE_CURATED


def test_axiom_export_carries_the_source(hier):
    hier._set_edge("Chronic Wound", "Wound", source=SOURCE_CURATED)
    hier.propose_edge("X", "Y", SOURCE_FCA)          # uncommitted, must not export
    axioms = hier.provenance_axioms()
    assert ("Chronic Wound", "rdfs:subClassOf", "Wound", SOURCE_CURATED) in axioms
    assert not any(a[0] == "X" for a in axioms)


def test_summary_counts_by_source(hier):
    hier._set_edge("A", "B", source=SOURCE_CURATED)
    hier._set_edge("C", "D", source=SOURCE_TEXT)
    hier._set_edge("E", "F", source=SOURCE_TEXT)
    assert hier.provenance_summary() == {SOURCE_CURATED: 1, SOURCE_TEXT: 2}
