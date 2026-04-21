"""
OWLGenerator hierarchy
======================
Generic, ontology-agnostic rdflib graph builders.

    OWLGenerator (abstract base)
    ├── TBoxGenerator  — OWL classes, subClassOf, and property restrictions
    └── ABoxGenerator  — named individuals and property assertions

Both accept an optional ``OWLOntology`` instance for label/IRI lookups.
Neither is tied to any specific ontology vocabulary.

Usage
-----
    from wound_ontology.export.owl_generator import TBoxGenerator, ABoxGenerator
    from rdflib import URIRef

    EX = "http://example.org/onto/"

    # --- TBox ---
    tbox = TBoxGenerator()
    wound    = tbox.add_class(URIRef(EX + "Wound"),        "Wound")
    chronic  = tbox.add_class(URIRef(EX + "ChronicWound"), "Chronic wound", parent=wound)
    part_of  = URIRef("http://purl.obolibrary.org/obo/RO_0001000")
    bed      = URIRef("http://purl.obolibrary.org/obo/FMA_67112")
    tbox.add_some_values_from(chronic, part_of, bed)
    tbox.save("tbox.owl")

    # --- ABox ---
    abox = ABoxGenerator()
    p = abox.add_individual(URIRef(EX + "patient1"), "Patient 1")
    w = abox.add_individual(URIRef(EX + "wound1"),   "Wound of patient 1", chronic)
    abox.add_object_property(w, part_of, URIRef(EX + "bed1"))
    abox.save("abox.owl")
"""
from __future__ import annotations

from abc import ABC
from pathlib import Path

from rdflib import Graph, URIRef, Literal, BNode, RDF, RDFS, OWL, XSD


class OWLGenerator(ABC):
    """
    Abstract base for OWL graph builders.

    Subclasses inherit a shared set of low-level primitives for manipulating
    an rdflib.Graph.  The ``graph`` property exposes it for direct access when
    needed.

    Parameters
    ----------
    graph : rdflib.Graph, optional
        Pre-existing graph to write into.  A fresh empty Graph is created when
        omitted — this is the common case.
    ontology : OWLOntology, optional
        Ontology instance used for label / IRI lookups.  When supplied,
        ``label_of(iri)`` and ``iri_of_label(label)`` delegate to it.
    """

    def __init__(
        self,
        graph: Graph | None = None,
        ontology=None,
    ):
        self._g: Graph = graph if graph is not None else Graph()
        self._onto = ontology  # OWLOntology | None
        self._sparql = None    # SPARQLHelper | None, lazy over _g

    # ── Public interface ───────────────────────────────────────────────────────

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

    # ── Shared low-level primitives ────────────────────────────────────────────

    def _add_label(self, iri: URIRef, label: str, lang: str = "en") -> None:
        self._g.add((iri, RDFS.label, Literal(label, lang=lang)))

    def _add_type(self, iri: URIRef, cls: URIRef) -> None:
        self._g.add((iri, RDF.type, cls))

    def _add_object_property(
        self, subject: URIRef, prop: URIRef, obj: URIRef
    ) -> None:
        self._g.add((subject, prop, obj))

    def _make_restriction(
        self,
        prop: URIRef,
        filler: URIRef | BNode,
        quantifier: URIRef,
    ) -> BNode:
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


class TBoxGenerator(OWLGenerator):
    """
    Builds OWL TBox axioms: classes, subClassOf, and property restrictions.

    All methods return the subject IRI / BNode so calls can be chained::

        gen = TBoxGenerator()
        wound   = gen.add_class(URIRef("…/Wound"),   "Wound")
        chronic = gen.add_class(URIRef("…/Chronic"), "Chronic wound", parent=wound)
        gen.add_some_values_from(chronic, part_of_iri, wound_bed_iri)
    """

    def add_class(
        self,
        iri: URIRef,
        label: str,
        parent: URIRef | None = None,
        lang: str = "en",
    ) -> URIRef:
        """
        Declare an ``owl:Class`` with an ``rdfs:label`` and optional parent.

        Returns
        -------
        URIRef
            The class IRI (for chaining).
        """
        self._g.add((iri, RDF.type, OWL.Class))
        self._add_label(iri, label, lang)
        if parent is not None:
            self._g.add((iri, RDFS.subClassOf, parent))
        return iri

    def add_subclass_of(self, child: URIRef, parent: URIRef) -> None:
        """Assert ``child rdfs:subClassOf parent``."""
        self._g.add((child, RDFS.subClassOf, parent))

    def add_some_values_from(
        self, class_iri: URIRef, prop: URIRef, filler: URIRef
    ) -> BNode:
        """
        Add ``class_iri ⊑ ∃prop.filler``.

        Returns the restriction BNode.
        """
        r = self._make_restriction(prop, filler, OWL.someValuesFrom)
        self._g.add((class_iri, RDFS.subClassOf, r))
        return r

    def add_all_values_from(
        self, class_iri: URIRef, prop: URIRef, filler: URIRef
    ) -> BNode:
        """Add ``class_iri ⊑ ∀prop.filler``."""
        r = self._make_restriction(prop, filler, OWL.allValuesFrom)
        self._g.add((class_iri, RDFS.subClassOf, r))
        return r

    def add_has_value(
        self, class_iri: URIRef, prop: URIRef, value: URIRef
    ) -> BNode:
        """Add ``class_iri ⊑ prop value filler``."""
        r = self._make_restriction(prop, value, OWL.hasValue)
        self._g.add((class_iri, RDFS.subClassOf, r))
        return r

    def add_union_restriction(
        self,
        class_iri: URIRef,
        prop: URIRef,
        filler_iris: list[URIRef],
        restriction_type: str = "some",
    ) -> BNode:
        """
        Add ``class_iri ⊑ ∃prop.(A ⊔ B ⊔ …)``.

        Parameters
        ----------
        restriction_type : str
            ``"some"`` (default, ``owl:someValuesFrom``) or ``"all"``
            (``owl:allValuesFrom``).

        Returns
        -------
        BNode
            The outermost restriction node.
        """
        rdf_list = self._make_rdf_list(filler_iris)
        union_bn = BNode()
        self._g.add((union_bn, OWL.unionOf, rdf_list))
        quantifier = OWL.someValuesFrom if restriction_type == "some" else OWL.allValuesFrom
        r = self._make_restriction(prop, union_bn, quantifier)
        self._g.add((class_iri, RDFS.subClassOf, r))
        return r

    def add_intersection_restriction(
        self,
        class_iri: URIRef,
        prop: URIRef,
        filler_iris: list[URIRef],
        restriction_type: str = "some",
    ) -> BNode:
        """Add ``class_iri ⊑ ∃prop.(A ⊓ B ⊓ …)``."""
        rdf_list = self._make_rdf_list(filler_iris)
        inter_bn = BNode()
        self._g.add((inter_bn, OWL.intersectionOf, rdf_list))
        quantifier = OWL.someValuesFrom if restriction_type == "some" else OWL.allValuesFrom
        r = self._make_restriction(prop, inter_bn, quantifier)
        self._g.add((class_iri, RDFS.subClassOf, r))
        return r


class ABoxGenerator(OWLGenerator):
    """
    Builds OWL ABox axioms: named individuals and property assertions.

    Usage::

        gen = ABoxGenerator()
        pat = gen.add_individual(URIRef("…/p1"), "Patient 1")
        w   = gen.add_individual(URIRef("…/w1"), "Wound of patient 1",
                                 URIRef("…/Wound"))
        gen.add_object_property(w, URIRef("…/has_patient"), pat)
        gen.save("abox.owl")
    """

    def add_individual(
        self,
        iri: URIRef,
        label: str,
        *types: URIRef,
        lang: str = "en",
    ) -> URIRef:
        """
        Declare an ``owl:NamedIndividual`` with a label and zero or more types.

        Returns
        -------
        URIRef
            The individual IRI (for chaining).
        """
        self._g.add((iri, RDF.type, OWL.NamedIndividual))
        self._add_label(iri, label, lang)
        for cls in types:
            self._g.add((iri, RDF.type, cls))
        return iri

    def add_type(self, individual: URIRef, cls: URIRef) -> None:
        """Assert ``individual rdf:type cls``."""
        self._add_type(individual, cls)

    def add_object_property(
        self, subject: URIRef, prop: URIRef, obj: URIRef
    ) -> None:
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
