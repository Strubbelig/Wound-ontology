"""A proposed FCA edge must not reach the OWL until it is promoted.

`commit_fca=False` makes a named lattice concept a *review candidate*: FCA
observes that terms share attributes, which is evidence for a superclass rather
than an assertion of one. The integration test that covered this asserted the
opposite — that every named FCA superclass appears in the exported OWL — and
survived only because concept naming is a live LLM call, so most runs produced
no name to check. This pins the contract without an LLM in the loop.
"""
import warnings

import pandas as pd
import pytest

from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.owl import OWLOntology, OntologyCurator


@pytest.fixture
def hier():
    h = ClassHierarchy.__new__(ClassHierarchy)
    h._df = pd.DataFrame(dtype=float)
    h._prov, h._candidates = {}, {}
    h._prov_loaded = True
    h._set_edge("Chronic Wound", "Wound")
    h.propose_edge("Chronic Wound", "Injury", "fca")
    return h


def _export(h):
    onto = OWLOntology.create(iri="http://test.org/candidate_export/")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        OntologyCurator(onto).from_hierarchies(class_hierarchy=h)
    return {v.lower() for v in onto.labels}


def test_committed_edges_are_exported(hier):
    labels = _export(hier)
    assert "wound" in labels and "chronic wound" in labels


def test_a_candidate_parent_is_not_exported(hier):
    """If it appeared, unreviewed FCA edges would be entering the ontology."""
    assert ("Chronic Wound", "Injury") in hier.candidates
    assert "injury" not in _export(hier)


def test_promoting_the_candidate_puts_it_in_the_owl(hier):
    """The candidate is held back, not discarded — review is what releases it."""
    assert hier.promote_candidates() == 1
    assert hier.candidates == {}
    assert "injury" in _export(hier)
