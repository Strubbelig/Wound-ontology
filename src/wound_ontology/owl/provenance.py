# -*- coding: utf-8 -*-
"""Stamp exported subsumption axioms with the source that produced them (C4).

The curator writes bare ``rdfs:subClassOf`` triples via owlready2. OWL carries
axiom-level metadata through reification — an ``owl:Axiom`` node pointing at the
subject, predicate and object — which is what ROBOT, Protégé and the OBO tools
read. This module applies that to an already-saved ontology file, so nothing in
the owlready2 export path has to change.

Result, per edge::

    [] a owl:Axiom ;
       owl:annotatedSource   <child> ;
       owl:annotatedProperty rdfs:subClassOf ;
       owl:annotatedTarget   <parent> ;
       oboInOwl:source       "curated" .

A consumer can then tell a human-authored edge from one an abstract implied or a
lattice suggested — which was impossible while all three shared a 0/1 matrix.
"""
from __future__ import annotations

from pathlib import Path

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef

from wound_ontology.hierarchies.base_hierarchy import PROVENANCE_ANNOTATION

SOURCE_PROP = URIRef(PROVENANCE_ANNOTATION)


def _label_index(g: Graph) -> dict[str, URIRef]:
    """Map label text -> IRI for classes in the graph."""
    idx: dict[str, URIRef] = {}
    for s, o in g.subject_objects(RDFS.label):
        if isinstance(s, URIRef):
            idx.setdefault(str(o).strip(), s)
    return idx


def annotate_file(
    path: str | Path,
    hierarchies,
    output: str | Path | None = None,
    fmt: str | None = None,
) -> dict[str, int]:
    """Add provenance annotations to the subsumption axioms in `path`.

    hierarchies – one BaseHierarchy, or an iterable of them.
    output      – defaults to overwriting `path`.

    Returns {source: count} for the annotations actually written, plus an
    "unmatched" count for edges whose labels are not in the file.
    """
    if not isinstance(hierarchies, (list, tuple, set)):
        hierarchies = [hierarchies]

    path = Path(path)
    g = Graph()
    g.parse(str(path), format=fmt)
    idx = _label_index(g)

    written: dict[str, int] = {}
    unmatched = 0

    for hier in hierarchies:
        for child, _pred, parent, source in hier.provenance_axioms():
            c_iri, p_iri = idx.get(child), idx.get(parent)
            if c_iri is None or p_iri is None:
                unmatched += 1
                continue
            if (c_iri, RDFS.subClassOf, p_iri) not in g:
                unmatched += 1
                continue
            if _already_annotated(g, c_iri, p_iri):
                continue
            node = BNode()
            g.add((node, RDF.type, OWL.Axiom))
            g.add((node, OWL.annotatedSource, c_iri))
            g.add((node, OWL.annotatedProperty, RDFS.subClassOf))
            g.add((node, OWL.annotatedTarget, p_iri))
            g.add((node, SOURCE_PROP, Literal(source)))
            written[source] = written.get(source, 0) + 1

    if written:
        g.add((SOURCE_PROP, RDF.type, OWL.AnnotationProperty))

    out = Path(output) if output else path
    g.serialize(destination=str(out), format=fmt or _guess_format(out))
    written["unmatched"] = unmatched
    return written


def _already_annotated(g: Graph, child: URIRef, parent: URIRef) -> bool:
    for node in g.subjects(RDF.type, OWL.Axiom):
        if (node, OWL.annotatedSource, child) in g and \
           (node, OWL.annotatedTarget, parent) in g and \
           (node, OWL.annotatedProperty, RDFS.subClassOf) in g:
            return True
    return False


def _guess_format(p: Path) -> str:
    return {".ttl": "turtle", ".nt": "nt", ".owl": "xml", ".rdf": "xml"}.get(
        p.suffix.lower(), "xml"
    )


def read_provenance(path: str | Path, fmt: str | None = None) -> list[tuple[str, str, str]]:
    """Read back (child_iri, parent_iri, source) triples from an annotated file."""
    g = Graph()
    g.parse(str(path), format=fmt)
    out = []
    for node in g.subjects(RDF.type, OWL.Axiom):
        if (node, OWL.annotatedProperty, RDFS.subClassOf) not in g:
            continue
        src = g.value(node, SOURCE_PROP)
        if src is None:
            continue
        out.append((str(g.value(node, OWL.annotatedSource)),
                    str(g.value(node, OWL.annotatedTarget)),
                    str(src)))
    return sorted(out)
