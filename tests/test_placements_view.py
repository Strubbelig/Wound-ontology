"""`TermMappingAndGate.placements()`: the `placed` source of the class hierarchy.

A kept placement is the curator's `narrower` on the pair with the class `iri`
(a `placement` source of its own until 2026-10-24). It counts unless refused,
unless the term is out of scope, and unless the term is mapped onto a class
(then it IS that class, not beneath it).
"""
import pytest

from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

IRI = "https://bioportal.bioontology.org/ontologies/WONT/WONT_0000426"
PLACED = {"verdict": "narrower", "iri": IRI}


class DM:
    def load_latest_json(self, name):
        return None

    def save_as_json(self, data, name):
        pass


def make():
    return TermMappingAndGate(DM(), file_name="term_mapping")


def test_a_kept_placement_is_an_edge():
    gt = make()
    gt.judge("venous stasis ulcer", "Ulcus cruris venosum", curator=PLACED)
    assert gt.placements() == [("venous stasis ulcer", "Ulcus cruris venosum")]


def test_a_refused_placement_is_not():
    gt = make()
    gt.judge("tissue fibrosis", "material disease entity", curator=PLACED)
    gt.refuse("tissue fibrosis", "material disease entity", reason="test")
    assert gt.placements() == []


def test_an_excluded_term_has_no_edge():
    gt = make()
    gt.judge("clinical method", "planned process", curator=PLACED)
    gt.gate("clinical method", curator={"verdict": "out"})
    assert gt.placements() == []


def test_a_mapped_term_is_its_class_not_beneath_it():
    gt = make()
    gt.judge("venous leg ulcer", "Ulcus cruris venosum", curator=PLACED)
    gt.record("venous leg ulcer")["to"] = "Ulcus cruris venosum"
    assert gt.placements() == []


def test_a_same_class_placement_is_no_edge():
    gt = make()
    gt.judge("stasis ulcer", "Ulcus cruris venosum", curator={"verdict": "same_class", "iri": IRI})
    assert gt.placements() == []


def test_a_narrower_without_the_class_iri_is_a_note_not_a_place():
    """The naming review of 2026-09-28 noted subtypes in passing; folded into
    the hierarchy they put `reducing Pressure ulcer` under `Pressure ulcer`."""
    gt = make()
    gt.judge("reducing Pressure ulcer", "Pressure ulcer", curator={"verdict": "narrower"})
    assert gt.placements() == []


def test_the_placement_source_is_gone():
    with pytest.raises(ValueError, match="curator"):
        make().judge("a", "b", placement={"verdict": "narrower"})
