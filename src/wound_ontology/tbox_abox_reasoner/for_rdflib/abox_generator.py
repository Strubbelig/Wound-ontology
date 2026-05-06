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

from rdflib import Graph, URIRef, Literal, BNode, RDF, RDFS, OWL


class ABoxGenerator:

    def __init__(self, graph: Graph | None = None):
        self._g = graph if graph is not None else Graph()

    @property
    def graph(self) -> Graph:
        return self._g

    def save(self, path: str) -> None:
        self._g.serialize(destination=path, format="xml")

    def _add_label(self, iri: URIRef, label: str, lang: str = "en") -> None:
        self._g.add((iri, RDFS.label, Literal(label, lang=lang)))

    def _add_type(self, subject: URIRef, cls: URIRef) -> None:
        self._g.add((subject, RDF.type, cls))

    def _add_object_property(self, subject: URIRef, prop: URIRef, obj: URIRef) -> None:
        self._g.add((subject, prop, obj))

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
