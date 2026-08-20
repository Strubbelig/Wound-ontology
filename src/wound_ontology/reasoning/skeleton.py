# -*- coding: utf-8 -*-
"""Build the skeleton TBox the per-batch reasoner gate reasons over (C7).

Reasoning over the full import closure is possible but useless as a gate: the
imported modules carry **54 pre-existing unsatisfiable classes** (conflicts
inside CHEBI/GO/DOID/HP/UBERON, where a term is a phenotype on one branch and a
material entity on another). A gate that fires on every batch gets switched off.

The skeleton is MILD + WONT's own axioms plus an explicit BFO backbone, with
`owl:imports` stripped. Measured on the current files: **0 unsatisfiable
classes**, ~3s under ELK. So anything the gate reports is, by construction,
caused by the batch — no baseline bookkeeping, no noise to filter.

What this deliberately gives up: conflicts that only appear against imported
axioms. Those are the business of the on-demand HermiT check over the full
merge, not of a fast per-batch gate.
"""
from __future__ import annotations

from pathlib import Path

import rdflib
from rdflib import OWL, RDF, RDFS, URIRef

OBO = "http://purl.obolibrary.org/obo/"

# BFO's backbone is not present in any imported module, so state it explicitly
# rather than silently failing to detect cross-category errors.
BFO_SKELETON: dict[str, str] = {
    "BFO_0000004": "BFO_0000002", "BFO_0000020": "BFO_0000002",
    "BFO_0000031": "BFO_0000002", "BFO_0000040": "BFO_0000004",
    "BFO_0000141": "BFO_0000004", "BFO_0000015": "BFO_0000003",
    "BFO_0000017": "BFO_0000020", "BFO_0000019": "BFO_0000020",
    "BFO_0000016": "BFO_0000017", "BFO_0000023": "BFO_0000017",
    "BFO_0000034": "BFO_0000016", "BFO_0000035": "BFO_0000003",
    "OGMS_0000045": "BFO_0000040", "IAO_0000030": "BFO_0000031",
}

BFO_LABELS: dict[str, str] = {
    "BFO_0000001": "entity", "BFO_0000002": "continuant", "BFO_0000003": "occurrent",
    "BFO_0000004": "independent continuant", "BFO_0000015": "process",
    "BFO_0000016": "disposition", "BFO_0000017": "realizable entity",
    "BFO_0000019": "quality", "BFO_0000020": "specifically dependent continuant",
    "BFO_0000023": "role", "BFO_0000031": "generically dependent continuant",
    "BFO_0000034": "function", "BFO_0000035": "process boundary",
    "BFO_0000040": "material entity", "BFO_0000141": "immaterial entity",
    "OGMS_0000045": "disorder", "IAO_0000030": "information content entity",
}

# The disjointness that makes the gate bite. Without these a cross-category
# assertion is merely odd; with them it is unsatisfiable and gets caught.
BFO_DISJOINT: list[tuple[str, str]] = [
    ("BFO_0000002", "BFO_0000003"),   # continuant / occurrent
    ("BFO_0000004", "BFO_0000020"),   # independent / specifically dependent
    ("BFO_0000004", "BFO_0000031"),   # independent / generically dependent
    ("BFO_0000020", "BFO_0000031"),
    ("BFO_0000019", "BFO_0000017"),   # quality / realizable
]


def build_skeleton(
    ground_truth: str | Path,
    mild: str | Path,
    output: str | Path,
) -> tuple[Path, int]:
    """Write the skeleton TBox. Returns (path, triple_count)."""
    g = rdflib.Graph()
    for src in (ground_truth, mild):
        tmp = rdflib.Graph()
        tmp.parse(str(src), format="turtle")
        for t in tmp:
            if t[1] == OWL.imports:
                continue                       # the whole point: no closure
            g += [t]

    for child, parent in BFO_SKELETON.items():
        g.add((URIRef(OBO + child), RDFS.subClassOf, URIRef(OBO + parent)))
    for iri, label in BFO_LABELS.items():
        u = URIRef(OBO + iri)
        g.add((u, RDF.type, OWL.Class))
        if not any(True for _ in g.objects(u, RDFS.label)):
            g.add((u, RDFS.label, rdflib.Literal(label)))
    for a, b in BFO_DISJOINT:
        g.add((URIRef(OBO + a), OWL.disjointWith, URIRef(OBO + b)))

    # Declare every property used in a restriction, so the reasoner does not
    # treat it as an undeclared entity.
    for p in set(g.objects(None, OWL.onProperty)):
        if (p, RDF.type, None) not in g:
            g.add((p, RDF.type, OWL.ObjectProperty))

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(out), format="turtle")
    return out, len(g)
