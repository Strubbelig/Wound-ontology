"""
ABoxGenerator
=============
Builds OWL ABox axioms: named individuals and property assertions.

Usage::

    gen = ABoxGenerator()
    pat = gen.add_individual(URIRef("…/p1"), "Patient 1")
    w   = gen.add_individual(URIRef("…/w1"), "Wound of patient 1",
                             URIRef("…/Wound"))
    gen.add_object_property(w, URIRef("…/has_patient"), pat)
    gen.save("abox.owl")
"""
from __future__ import annotations

from rdflib import URIRef, Literal, RDF, OWL

from wound_ontology.export.owl_generator import OWLGenerator


class ABoxGenerator(OWLGenerator):

    def add_individual(
        self,
        iri: URIRef,
        label: str,
        *types: URIRef,
        lang: str = "en",
    ) -> URIRef:
        """Declare an owl:NamedIndividual with a label and zero or more types."""
        self._g.add((iri, RDF.type, OWL.NamedIndividual))
        self._add_label(iri, label, lang)
        for cls in types:
            self._g.add((iri, RDF.type, cls))
        return iri

    def add_type(self, individual: URIRef, cls: URIRef) -> None:
        """Assert ``individual rdf:type cls``."""
        self._add_type(individual, cls)

    def add_object_property(self, subject: URIRef, prop: URIRef, obj: URIRef) -> None:
        """Assert ``subject prop obj``."""
        self._add_object_property(subject, prop, obj)

    def add_data_property(
        self,
        subject: URIRef,
        prop: URIRef,
        value,
        datatype: URIRef | None = None,
    ) -> None:
        """Assert ``subject prop value^^datatype``."""
        lit = Literal(value, datatype=datatype) if datatype else Literal(value)
        self._g.add((subject, prop, lit))
