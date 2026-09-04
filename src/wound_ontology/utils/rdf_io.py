from __future__ import annotations
"""Reading ontology files whose serialization the filename does not reveal.

``ground_truth_final.owl`` is Turtle carrying a ``.owl`` extension, while the
import modules are genuine RDF/XML under the same extension. Neither the suffix
nor a try-Turtle-first fallback is safe: rdflib's Turtle parser does not reject
an XML document outright, it ingests the header as malformed URIs and returns a
graph full of garbage, warning about serialization but raising nothing. A wrong
guess therefore costs silent corruption rather than an exception, so the format
is read off the file's first bytes.
"""
from pathlib import Path

import rdflib

_XML_HEADS = (b"<?xml", b"<rdf:RDF", b"<!DOCTYPE")


def sniff_format(path: Path | str) -> str:
    """``"xml"`` or ``"turtle"``, decided by content rather than suffix."""
    with Path(path).open("rb") as fh:
        head = fh.read(4096).lstrip()
    return "xml" if head.startswith(_XML_HEADS) else "turtle"


def parse_graph(path: Path | str, *, context: str = "ontology") -> rdflib.Graph:
    """Parse `path`, or raise. A source is never skipped in silence."""
    path = Path(path)
    fmt = sniff_format(path)
    g = rdflib.Graph()
    try:
        g.parse(str(path), format=fmt)
    except Exception as exc:
        raise RuntimeError(
            f"{context} {path} could not be parsed as {fmt} ({exc}). Refusing to "
            f"continue: skipping it would change what is built and report only a "
            f"smaller count."
        ) from exc
    return g
