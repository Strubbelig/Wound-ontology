"""`TermMappingAndGate.placements()`: the `placed` source of the class hierarchy.

A kept placement is a pair judgement `placement: {verdict: narrower}`. It
counts unless refused, unless the term is out of scope, and unless the term is
mapped onto a class (then it IS that class, not beneath it).
"""
from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate


class DM:
    def load_latest_json(self, name):
        return None

    def save_as_json(self, data, name):
        pass


def make():
    return TermMappingAndGate(DM(), file_name="term_mapping")


def test_a_kept_placement_is_an_edge():
    gt = make()
    gt.judge("venous stasis ulcer", "Ulcus cruris venosum", placement={"verdict": "narrower"})
    assert gt.placements() == [("venous stasis ulcer", "Ulcus cruris venosum")]


def test_a_refused_placement_is_not():
    gt = make()
    gt.judge("tissue fibrosis", "material disease entity", placement={"verdict": "narrower"})
    gt.refuse("tissue fibrosis", "material disease entity", reason="test")
    assert gt.placements() == []


def test_an_excluded_term_has_no_edge():
    gt = make()
    gt.judge("clinical method", "planned process", placement={"verdict": "narrower"})
    gt.gate("clinical method", curator={"verdict": "out"})
    assert gt.placements() == []


def test_a_mapped_term_is_its_class_not_beneath_it():
    gt = make()
    gt.judge("venous leg ulcer", "Ulcus cruris venosum", placement={"verdict": "narrower"})
    gt.record("venous leg ulcer")["to"] = "Ulcus cruris venosum"
    assert gt.placements() == []


def test_a_same_class_placement_is_no_edge():
    gt = make()
    gt.judge("stasis ulcer", "Ulcus cruris venosum", placement={"verdict": "same_class"})
    assert gt.placements() == []
