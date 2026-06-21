"""KnowledgeGraphRepository — load a KnowledgeGraph from an OWL/RDF file."""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph

from .model import KnowledgeGraph


class KnowledgeGraphRepository:
    """Persistence layer for KnowledgeGraph: load from file."""

    def load(self, path: str | Path) -> KnowledgeGraph:
        """Parse an OWL/RDF-XML file into a KnowledgeGraph.

        Accepts local file paths (.owl, .rdf, .ttl, .xml) — format is
        detected from the file extension.
        """
        p   = Path(path).resolve()
        fmt = _detect_format(p)
        g   = Graph()
        g.parse(str(p), format=fmt)
        print(f"[KnowledgeGraphRepository] Loaded {len(g):,} triples from {p.name}")
        return KnowledgeGraph(g)


def _detect_format(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".ttl":  "turtle",
        ".n3":   "n3",
        ".nt":   "nt",
        ".trig": "trig",
        ".nq":   "nquads",
        ".jsonld": "json-ld",
    }.get(ext, "xml")
