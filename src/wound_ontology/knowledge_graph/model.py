"""KnowledgeGraph — domain model wrapping an rdflib.Graph for inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL

if TYPE_CHECKING:
    pass


@dataclass
class KnowledgeGraph:
    """An OWL/RDF graph loaded for inspection and SPARQL queries.

    Immutable wrapper — all query operations live in KnowledgeGraphQuerier.
    The underlying graph can be accessed via .graph when needed.
    """

    graph: Graph = field(default_factory=Graph)

    # ── Convenience inspection methods ────────────────────────────────────────

    def stats(self) -> dict:
        """Triple count and rdf:type distribution."""
        type_counts: dict[str, int] = {}
        for _, _, rdf_type in self.graph.triples((None, RDF.type, None)):
            key = str(rdf_type).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
            type_counts[key] = type_counts.get(key, 0) + 1
        return {"triples": len(self.graph), "type_counts": type_counts}

    def find(self, label: str) -> list[tuple[str, str]]:
        """Return (iri, label) pairs whose rdfs:label contains *label* (case-insensitive)."""
        lower = label.lower()
        return [
            (str(s), str(o))
            for s, _, o in self.graph.triples((None, RDFS.label, None))
            if lower in str(o).lower()
        ]

    def neighbours(self, iri: str) -> dict:
        """All outgoing and incoming (predicate, node) pairs for a given IRI."""
        node = URIRef(iri)
        return {
            "outgoing": [(str(p), str(o)) for p, o in self.graph.predicate_objects(node)],
            "incoming": [(str(p), str(s)) for s, p in self.graph.subject_predicates(node)],
        }

    def filter_by_namespace(self, prefix: str) -> "KnowledgeGraph":
        """Return a new KnowledgeGraph with only triples whose subject IRI starts with prefix."""
        filtered = Graph()
        for s, p, o in self.graph:
            if isinstance(s, URIRef) and str(s).startswith(prefix):
                filtered.add((s, p, o))
        return KnowledgeGraph(filtered)

    @property
    def sparql(self) -> "KnowledgeGraphQuerier":
        """Return a KnowledgeGraphQuerier bound to this graph."""
        from .querier import KnowledgeGraphQuerier
        return KnowledgeGraphQuerier(self)

    def print_stats(self) -> None:
        s = self.stats()
        print(f"[KnowledgeGraph] {s['triples']:,} triples")
        for t, count in sorted(s["type_counts"].items(), key=lambda x: -x[1])[:10]:
            print(f"  {t}: {count:,}")
