"""
OWLGenerator
============
Abstract base class for OWL graph builders.

Subclasses (TBoxGenerator, ABoxGenerator) inherit shared low-level primitives
for manipulating an rdflib.Graph.

Neither this class nor its subclasses are tied to any specific ontology
vocabulary — all IRI constants belong in config.
"""
from __future__ import annotations

from abc import ABC
from pathlib import Path

from rdflib import Graph, URIRef, Literal, BNode, RDF, RDFS, OWL


class OWLGenerator(ABC):
    """
    Abstract base for OWL graph builders.

    Parameters
    ----------
    graph : rdflib.Graph, optional
        Pre-existing graph to write into.  A fresh empty Graph is created when
        omitted.
    ontology : TBox, optional
        TBox instance used for label / IRI lookups.
    """

    def __init__(self, graph: Graph | None = None, ontology=None):
        self._g: Graph = graph if graph is not None else Graph()
        self._onto = ontology
        self._sparql = None  # SPARQLHelper | None, lazy over _g

    @property
    def graph(self) -> Graph:
        """The underlying rdflib.Graph."""
        return self._g

    def save(self, output_file: str) -> None:
        """Serialize the graph to RDF/XML."""
        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._g.serialize(destination=str(out), format="xml")
        print(f"[{self.__class__.__name__}] Saved → {out}  ({out.stat().st_size:,} bytes)")

    def label_of(self, iri: URIRef, lang: str = "en") -> str | None:
        """
        Return the rdfs:label for *iri*.

        Checks the associated OWLOntology first (if any), then falls back to
        querying this generator's own graph via a cached SPARQLHelper.
        """
        if self._onto is not None:
            lbl = self._onto.label_of(iri, lang=lang)
            if lbl is not None:
                return lbl
        if self._sparql is None:
            from wound_ontology.graph.sparql_helper import SPARQLHelper
            self._sparql = SPARQLHelper(self._g)
        return self._sparql.label_of(str(iri), lang=lang)

    # ── Low-level primitives ──────────────────────────────────────────────────

    def _add_label(self, iri: URIRef, label: str, lang: str = "en") -> None:
        self._g.add((iri, RDFS.label, Literal(label, lang=lang)))

    def _add_type(self, iri: URIRef, cls: URIRef) -> None:
        self._g.add((iri, RDF.type, cls))

    def _add_object_property(self, subject: URIRef, prop: URIRef, obj: URIRef) -> None:
        self._g.add((subject, prop, obj))

    def _make_restriction(self, prop: URIRef, filler: URIRef | BNode, quantifier: URIRef) -> BNode:
        """Create an owl:Restriction blank node (not yet attached to a class)."""
        r = BNode()
        self._g.add((r, RDF.type, OWL.Restriction))
        self._g.add((r, OWL.onProperty, prop))
        self._g.add((r, quantifier, filler))
        return r

    def _make_rdf_list(self, items: list) -> URIRef | BNode:
        """Build an rdf:List from *items* and return the head node."""
        if not items:
            return RDF.nil
        head = BNode()
        current = head
        for i, item in enumerate(items):
            self._g.add((current, RDF.first, item))
            if i < len(items) - 1:
                nxt = BNode()
                self._g.add((current, RDF.rest, nxt))
                current = nxt
            else:
                self._g.add((current, RDF.rest, RDF.nil))
        return head
