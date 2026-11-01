"""The superseded export and extraction paths warn, and still work.

They are kept because stored outputs, notebooks and tests reference them; the
warning is what stops a new run from quietly using the wrong one.
"""
import warnings

import pandas as pd
import pytest

from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.owl import OWLOntology, OntologyCurator


def _hier():
    h = ClassHierarchy.__new__(ClassHierarchy)
    h._df = pd.DataFrame(dtype=float)
    h._prov, h._candidates = {}, {}
    h._prov_loaded = True
    h._set_edge("Chronic Wound", "Wound")
    return h


class _Tripwire(Exception):
    """Raised from the first line of export machinery, to prove the warning
    fired before any of it ran."""


def test_export_to_owl_warns_before_it_does_any_work(tmp_path, monkeypatch):
    """The warning has to reach the caller ahead of the export, not after it —
    otherwise a run learns it used the wrong path only once the file is written.

    The tripwire is deliberately a named exception caught by pytest.raises: a
    bare ``except Exception: pass`` here would hide a genuine failure inside
    export_to_owl and make the assertion meaningless.
    """
    import wound_ontology.orchestrator as orch

    def _tripwire(*a, **kw):
        raise _Tripwire

    monkeypatch.setattr(orch.OWLOntology, "create", staticmethod(_tripwire))

    pipeline = orch.Orchestrator.__new__(orch.Orchestrator)
    pipeline.class_hier = _hier()
    pipeline.fca_hier = None
    pipeline.store = None
    pipeline.dm = None

    with pytest.warns(DeprecationWarning, match="run_extend_ground_truth"):
        with pytest.raises(_Tripwire):
            pipeline.export_to_owl(output_file=str(tmp_path / "out.owl"))


def test_the_deprecated_export_still_functions():
    """Deprecated is not removed: existing callers must keep working."""
    onto = OWLOntology.create(iri="http://test.org/deprecation_check/")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        OntologyCurator(onto).from_hierarchies(class_hierarchy=_hier())
    labels = {v.lower() for v in onto.labels}
    assert "wound" in labels and "chronic wound" in labels


def test_from_hierarchies_documents_its_replacement():
    doc = OntologyCurator.from_hierarchies.__doc__
    assert ".. deprecated::" in doc
    assert "extend_ground_truth" in doc


def test_export_to_owl_documents_its_replacement():
    import wound_ontology.orchestrator as orch
    doc = orch.Orchestrator.export_to_owl.__doc__
    assert ".. deprecated::" in doc
    assert "run_extend_ground_truth" in doc


def test_legacy_free_text_extraction_warns():
    """schema_constrained=False skips BFO typing, label grounding and the
    category-pair filter. It must not be chosen by accident."""
    import inspect

    from wound_ontology.store.concept_store import ConceptStore

    src = inspect.getsource(ConceptStore.add_llm_extracts)
    assert "DeprecationWarning" in src
    assert "schema_constrained=False" in src
    # ...and the default stays on the schema-constrained path.
    sig = inspect.signature(ConceptStore.add_llm_extracts)
    assert sig.parameters["schema_constrained"].default is True
