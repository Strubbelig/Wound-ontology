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
    "BFO_0000008": "BFO_0000003",
    "OGMS_0000045": "BFO_0000040", "IAO_0000030": "BFO_0000031",
}

BFO_LABELS: dict[str, str] = {
    "BFO_0000001": "entity", "BFO_0000002": "continuant", "BFO_0000003": "occurrent",
    "BFO_0000004": "independent continuant", "BFO_0000015": "process",
    "BFO_0000016": "disposition", "BFO_0000017": "realizable entity",
    "BFO_0000019": "quality", "BFO_0000020": "specifically dependent continuant",
    "BFO_0000023": "role", "BFO_0000031": "generically dependent continuant",
    "BFO_0000034": "function", "BFO_0000035": "process boundary",
    "BFO_0000008": "temporal region",
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
    ("BFO_0000015", "BFO_0000008"),   # process / temporal region (BFO 2020)
]


def add_bfo_and_relation_axioms(g: rdflib.Graph, modules) -> dict:
    """BFO's own axioms and the exported relations' domains and ranges, read from
    the import modules into `g` (2026-10-03, rule 66).

    The hand tables above held 13 of BFO's 35 subclass edges and 6 disjointness
    pairs, and no relation had a domain or range, so `Wound has_quality
    material disease entity` clashed with nothing. Now: every subsumption among
    BFO classes, every disjointness among them (AllDisjointClasses expanded
    pairwise), and rdfs:domain / rdfs:range of every property in RELATION_IRI as
    RO / BFO / IAO / OBI declare them. ELK reasons in OWL 2 EL: a named class is
    kept, an intersection keeps its named members (a weaker axiom the source
    entails), a union or complement is left out and counted.
    """
    from rdflib.collection import Collection
    from wound_ontology.llm.extraction_models import RELATION_IRI
    # Nothing withheld. Until 2026-10-03 RO's range of `has disposition` was:
    # WONT bore `wound infecting tendency` by it although MILD makes tendency
    # disjoint from disposition. The curator ruled "separate has tendency
    # relation": MILD_120101 `has tendency` now carries those three axioms.
    withheld: set = set()
    from wound_ontology.utils.rdf_io import parse_graph
    m = rdflib.Graph()
    for path in modules:
        m += parse_graph(Path(path), context="skeleton module")
    bfo = lambda x: isinstance(x, URIRef) and str(x).startswith(OBO + "BFO_")
    rep = {"bfo_subclass": 0, "bfo_disjoint": 0, "domain": 0, "range": 0,
           "weakened_intersection": 0, "skipped_not_EL": [], "no_axiom": []}
    for c, p in m.subject_objects(RDFS.subClassOf):
        if bfo(c) and bfo(p):
            g.add((c, RDF.type, OWL.Class)); g.add((c, RDFS.subClassOf, p)); rep["bfo_subclass"] += 1
            for lab in m.objects(c, RDFS.label):
                if not any(True for _ in g.objects(c, RDFS.label)):
                    g.add((c, RDFS.label, lab))
    for a, b in m.subject_objects(OWL.disjointWith):
        if bfo(a) and bfo(b):
            g.add((a, OWL.disjointWith, b)); rep["bfo_disjoint"] += 1
    for node in m.subjects(RDF.type, OWL.AllDisjointClasses):
        members = [x for x in Collection(m, m.value(node, OWL.members)) if bfo(x)]
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                g.add((a, OWL.disjointWith, b)); rep["bfo_disjoint"] += 1
    for name, iri in sorted(RELATION_IRI.items()):
        prop = URIRef(iri)
        g.add((prop, RDF.type, OWL.ObjectProperty))
        found = False
        for axis, key in ((RDFS.domain, "domain"), (RDFS.range, "range")):
            for x in m.objects(prop, axis):
                found = True
                if (name, key) in withheld:
                    rep.setdefault("withheld", []).append(f"{name} {key}")
                    continue
                if isinstance(x, URIRef):
                    g.add((prop, axis, x)); rep[key] += 1
                elif m.value(x, OWL.intersectionOf) is not None:
                    for part in Collection(m, m.value(x, OWL.intersectionOf)):
                        if isinstance(part, URIRef):
                            g.add((prop, axis, part)); rep[key] += 1; rep["weakened_intersection"] += 1
                else:
                    rep["skipped_not_EL"].append(f"{name} {key}")
        if not found and not any(True for _ in g.objects(prop, RDFS.domain)) \
                and not any(True for _ in g.objects(prop, RDFS.range)):
            rep["no_axiom"].append(name)
    return rep


def build_skeleton(
    ground_truth: str | Path,
    mild: str | Path,
    output: str | Path,
    modules=None,
) -> tuple[Path, int]:
    """Write the skeleton TBox. Returns (path, triple_count). With `modules`
    (the import module files), BFO's own axioms and the relations' domains and
    ranges are added from them (`add_bfo_and_relation_axioms`)."""
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
    if modules is not None:
        report = add_bfo_and_relation_axioms(g, modules)
        print(f"[skeleton] from the import modules: {report}")

    # Declare every property used in a restriction, so the reasoner does not
    # treat it as an undeclared entity.
    for p in set(g.objects(None, OWL.onProperty)):
        if (p, RDF.type, None) not in g:
            g.add((p, RDF.type, OWL.ObjectProperty))

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(out), format="turtle")
    return out, len(g)
