"""Graph utilities for knowledge representation and SPARQL handling."""
# ABox is imported lazily to avoid pulling in the cross-project ofl_constants
# dependency at module load time.
from wound_ontology.tbox_abox_reasoner.for_rdflib.sparql.sparql_helper import SPARQLHelper

__all__ = ["ABox", "SPARQLHelper"]


def __getattr__(name: str):
    if name == "ABox":
        from wound_ontology.tbox_abox_reasoner.for_rdflib.abox import ABox
        return ABox
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
