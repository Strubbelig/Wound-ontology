"""Ontology TBox/ABox reasoning package."""

from wound_ontology.tbox_abox_reasoner.for_owl.tbox import TBox
from wound_ontology.tbox_abox_reasoner.for_rdflib.abox import ABox
from wound_ontology.tbox_abox_reasoner.reasoner.reasoner import Reasoner

__all__: list[str] = ["TBox", "ABox", "Reasoner"]
