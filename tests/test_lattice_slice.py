"""A lattice analysis is per-subtree, and its reviewed slice is what leaves it.

FCA output is a suggestion. The review that turns some of it into hierarchy
edges is recorded as a slice of the lattice it came from, and that slice is the
`fca` source ClassHierarchy.get_data reads. Nothing about the review reaches the
ConceptStore, which holds what documents asserted.
"""
import tempfile

import pytest

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.fca.concept_lattice import ConceptLattice
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.hierarchies.fca_hierarchy import FCAHierarchy


@pytest.fixture
def dm():
    return DataManager(tempfile.mkdtemp())


def _lattice(dm, name):
    return ConceptLattice(dm, ContextMatrix(dm, "context_matrix"), name)


def test_accepting_edges_records_them(dm):
    lat = _lattice(dm, "concept_lattice_wound")
    assert lat.accept([("Chronic Wound", "Wound")]) == 1
    assert ("Chronic Wound", "Wound") in lat.accepted


def test_the_slice_is_reloaded_in_a_later_session(dm):
    _lattice(dm, "concept_lattice_wound").accept([("Chronic Wound", "Wound")])
    reopened = _lattice(dm, "concept_lattice_wound")
    assert reopened.slice() == [("Chronic Wound", "Wound")]


def test_two_subtrees_do_not_share_a_slice(dm):
    """One lattice instance was reused for every analysis, so a Wound run was
    still present while another subtree was being analysed."""
    _lattice(dm, "concept_lattice_wound").accept([("Chronic Wound", "Wound")])
    other = _lattice(dm, "concept_lattice_dressing")
    assert other.slice() == []


def test_accepted_names_are_normalised(dm):
    lat = _lattice(dm, "concept_lattice_wound")
    lat.accept([("chronic wound", "wound")])
    assert ("Chronic Wound", "Wound") in lat.accepted


def test_accepting_the_same_edge_twice_adds_nothing(dm):
    lat = _lattice(dm, "concept_lattice_wound")
    lat.accept([("Chronic Wound", "Wound")])
    assert lat.accept([("Chronic Wound", "Wound")]) == 0


def test_the_fca_hierarchy_rebuilds_rather_than_accumulating(dm):
    """FCAHierarchy.get_data looped calling _set_edge without ever clearing, so
    the saved CSV was the union of every analysis ever run."""
    class _C:
        def __init__(self, name, uppers=()):
            self.name = name
            self.upper_neighbors = uppers

    wound = _C("Wound")
    first = [_C("Chronic Wound", (wound,)), wound]
    dressing = _C("Dressing")
    second = [_C("Foam Dressing", (dressing,)), dressing]

    h = FCAHierarchy(dm, "fca_hierarchy_wound")
    h.get_data(first)
    assert "Chronic Wound" in h.concepts

    h.get_data(second)
    assert "Foam Dressing" in h.concepts
    assert "Chronic Wound" not in h.concepts, "edges from the previous analysis remain"


def test_a_per_analysis_hierarchy_has_its_own_file(dm):
    assert FCAHierarchy(dm, "fca_hierarchy_wound").file_name == "fca_hierarchy_wound"
    assert FCAHierarchy(dm).file_name == "fca_hierarchy"


def test_an_edge_can_be_withdrawn_from_the_slice(dm):
    """A review can be wrong. The inverse of accept has to exist, or the only
    way back is deleting a cache file by hand."""
    lat = _lattice(dm, "concept_lattice_wound")
    lat.accept([("Traumatic Wound", "Traumatic Wound Healing Disorder"),
                ("Chronic Wound", "Wound")])
    assert lat.withdraw([("Traumatic Wound", "Traumatic Wound Healing Disorder")]) == 1
    assert lat.slice() == [("Chronic Wound", "Wound")]


def test_the_withdrawal_is_persisted(dm):
    lat = _lattice(dm, "concept_lattice_wound")
    lat.accept([("Chronic Wound", "Wound"), ("Acute Wound", "Wound")])
    lat.withdraw([("Acute Wound", "Wound")])
    assert _lattice(dm, "concept_lattice_wound").slice() == [("Chronic Wound", "Wound")]


def test_withdrawing_something_never_accepted_says_so(dm, capsys):
    lat = _lattice(dm, "concept_lattice_wound")
    lat.accept([("Chronic Wound", "Wound")])
    assert lat.withdraw([("Nothing", "Nowhere")]) == 0
    assert "could not be withdrawn" in capsys.readouterr().out


def test_a_cycle_is_refused_by_the_hierarchy(dm):
    """Two lattice concepts named the same collapsed onto one node, and the
    lattice's own order edges became `Wound is_a Skin Defect is_a Wound`."""
    from wound_ontology.hierarchies.fca_hierarchy import FCAHierarchy

    class _C:
        def __init__(self, name, uppers=()):
            self.name = name
            self.upper_neighbors = uppers

    top = _C("Wound")
    mid = _C("Skin Defect", (top,))
    top.upper_neighbors = (mid,)          # the cycle

    h = FCAHierarchy(dm, "fca_hierarchy_cycle")
    h.get_data([mid, top])
    assert "Wound" in h.parents_of("Skin Defect")
    assert "Skin Defect" not in h.parents_of("Wound")


def test_fca_edges_are_stamped_fca(dm):
    """Every edge here is lattice-derived; they used to record themselves as
    `text`, i.e. as something a paper asserted."""
    from wound_ontology.hierarchies.base_hierarchy import SOURCE_FCA
    from wound_ontology.hierarchies.fca_hierarchy import FCAHierarchy

    class _C:
        def __init__(self, name, uppers=()):
            self.name = name
            self.upper_neighbors = uppers

    wound = _C("Wound")
    h = FCAHierarchy(dm, "fca_hierarchy_stamp")
    h.get_data([_C("Bite Wound", (wound,)), wound])
    assert h.source_of("Bite Wound", "Wound") == SOURCE_FCA
