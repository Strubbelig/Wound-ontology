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
    from conftest import J
    gt.records["venous leg ulcer"]["name"] = [J("Ulcus cruris venosum", "sapbert-clustering")]
    gt._dirty()
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


# ── The author's links between two terms (rule 89, 2026-10-28) ─────────────

def _term_link(gt, child, parent, by="author", verdict="yes"):
    from conftest import J
    for t in (child, parent):
        gt.records.setdefault(t, {})
    gt.records[child].setdefault("is_a", {}).setdefault(parent, []).append(J(verdict, by))
    gt._dirty()


def test_the_authors_link_between_two_terms_is_an_edge():
    gt = make()
    _term_link(gt, "Burn wound", "Burn injury")
    assert gt.term_links() == [("Burn wound", "Burn injury")]
    assert gt.placements() == []


def test_elks_yes_between_two_terms_is_no_link():
    """ELK keeping an edge says it is consistent, not that it holds."""
    gt = make()
    _term_link(gt, "Burn wound", "Burn injury", by="elk")
    assert gt.term_links() == []


def test_a_link_elk_refuses_after_the_author_still_stands():
    gt = make()
    _term_link(gt, "Burn wound", "Burn injury")
    _term_link(gt, "Burn wound", "Burn injury", by="elk", verdict="no")
    assert gt.term_links() == [("Burn wound", "Burn injury")]


def test_a_category_or_a_class_is_no_term_link():
    from conftest import J
    gt = make()
    _term_link(gt, "Burn wound", "material entity")
    gt.records["Burn wound"]["is_a"]["Thermal wound"] = [J("yes", iri=IRI)]
    gt._dirty()
    assert gt.term_links() == []


def test_a_parent_that_is_no_term_is_no_link():
    gt = make()
    _term_link(gt, "Giant-sized", "Sized")
    del gt.records["Sized"]
    assert gt.term_links() == []


def test_a_link_with_an_end_out_of_scope_is_no_edge():
    gt = make()
    _term_link(gt, "Antibiotic", "Drug")
    gt.gate("Drug", curator={"verdict": "out"})
    assert gt.term_links() == []


def test_a_parent_renamed_since_is_named_and_left_out(capsys):
    from conftest import J
    gt = make()
    _term_link(gt, "Hydrocolloid gel dressing", "Hydrocolloid dressing")
    gt.records["Hydrocolloid dressing"]["name"] = [J("Ordinary hydrocolloid dressing")]
    gt.records["Ordinary hydrocolloid dressing"] = {}
    gt._dirty()
    assert gt.term_links() == []
    assert "now 'Ordinary hydrocolloid dressing'" in capsys.readouterr().out
