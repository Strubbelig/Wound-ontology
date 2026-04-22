"""
TBoxGenerator
=============
Builds OWL TBox axioms: classes, subClassOf, property restrictions, and
defined classes.

All methods return the subject IRI / BNode for chaining::

    gen = TBoxGenerator()
    wound   = gen.add_class(URIRef("…/Wound"),   "Wound")
    chronic = gen.add_class(URIRef("…/Chronic"), "Chronic wound", parent=wound)
    gen.add_some_values_from(chronic, part_of_iri, wound_bed_iri)
    gen.save("tbox.owl")
"""
from __future__ import annotations

from rdflib import URIRef, BNode, RDFS, OWL

from wound_ontology.export.owl_generator import OWLGenerator


class TBoxGenerator(OWLGenerator):

    def add_class(
        self,
        iri: URIRef,
        label: str,
        parent: URIRef | None = None,
        lang: str = "en",
    ) -> URIRef:
        """Declare an owl:Class with a label and optional parent."""
        from rdflib import RDF
        self._g.add((iri, RDF.type, OWL.Class))
        self._add_label(iri, label, lang)
        if parent is not None:
            self._g.add((iri, RDFS.subClassOf, parent))
        return iri

    def add_subclass_of(self, child: URIRef, parent: URIRef) -> None:
        """Assert ``child rdfs:subClassOf parent``."""
        self._g.add((child, RDFS.subClassOf, parent))

    def add_some_values_from(self, class_iri: URIRef, prop: URIRef, filler: URIRef) -> BNode:
        """Add ``class_iri ⊑ ∃prop.filler``."""
        r = self._make_restriction(prop, filler, OWL.someValuesFrom)
        self._g.add((class_iri, RDFS.subClassOf, r))
        return r

    def add_all_values_from(self, class_iri: URIRef, prop: URIRef, filler: URIRef) -> BNode:
        """Add ``class_iri ⊑ ∀prop.filler``."""
        r = self._make_restriction(prop, filler, OWL.allValuesFrom)
        self._g.add((class_iri, RDFS.subClassOf, r))
        return r

    def add_has_value(self, class_iri: URIRef, prop: URIRef, value: URIRef) -> BNode:
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
        """Add ``class_iri ⊑ ∃prop.(A ⊔ B ⊔ …)``."""
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

    def add_defined_class(
        self,
        iri: URIRef,
        label: str,
        parent: URIRef,
        prop: URIRef,
        filler: URIRef,
        lang: str = "en",
    ) -> URIRef:
        """
        Declare a fully defined OWL class (necessary and sufficient conditions)::

            C ≡ parent ⊓ ∃prop.filler

        Also asserts ``rdfs:subClassOf parent`` explicitly so non-reasoning
        tools can traverse the hierarchy without inference.
        """
        from rdflib import RDF
        self._g.add((iri, RDF.type, OWL.Class))
        self._add_label(iri, label, lang)
        restr = self._make_restriction(prop, filler, OWL.someValuesFrom)
        inter = BNode()
        self._g.add((inter, OWL.intersectionOf, self._make_rdf_list([parent, restr])))
        self._g.add((iri, OWL.equivalentClass, inter))
        self._g.add((iri, RDFS.subClassOf, parent))
        return iri
