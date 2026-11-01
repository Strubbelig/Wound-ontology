"""WONT's header names its creator, its dates and its preferred prefix, as MILD's does (2026-10-31).

The curator, relayed by the thesis session: "ja, trag die vier angaben in wont
ein". `ground_truth_final_2026-10-31e.owl` is `..._2026-10-31d.owl` plus, on the
ontology IRI, MILD's header properties in MILD's form:

* dcterms:creator -- both values MILD gives (the ORCID IRI and the name), read
  from MILD's header so the two cannot drift apart;
* dcterms:created "2026-06-15"^^xsd:date -- the earliest record of a WONT file:
  `data/ground truth/ground_truth.properties`, the companion file Protégé writes
  beside an ontology it saves, was created 2026-06-15 14:15 for `ground_truth.owl`.
  The same kind of companion file of `ground_truth_2606171253.ttl` was created
  2026-06-17 12:54, a minute after the time in that file's name, so these creation
  times hold. (`Ground_truth.csv`, 2026-06-13, is the table of curated edges
  WONT was first built from, not an ontology.)
* dcterms:modified "2026-10-31"^^xsd:date;
* vann:preferredNamespacePrefix "WONT" and vann:preferredNamespaceUri
  "https://bioportal.bioontology.org/ontologies/WONT/".

WONT declares none of its header properties itself; MILD, which it imports,
declares all of these. The graph difference is checked to be exactly these
triples.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-31d.owl", GT / "ground_truth_final_2026-10-31e.owl"
MILD = ROOT.parent / "Disease ontologies" / "mild_2026-10-31.ttl"
WONT_IRI, MILD_IRI = "https://bioportal.bioontology.org/ontologies/WONT", "https://bioportal.bioontology.org/ontologies/MILD"
CREATED = "2026-06-15"   # ground_truth.properties, created 2026-06-15 14:15 (see above)
MODIFIED = "2026-10-31"


def main(argv) -> int:
    import rdflib
    from rdflib import DCTERMS, OWL, RDF, Literal, Namespace, URIRef, XSD
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    VANN = Namespace("http://purl.org/vocab/vann/")
    write = "--write" in argv
    if write and NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")

    old = rdflib.Graph().parse(OLD, format="turtle")
    onto = URIRef(WONT_IRI)
    if (onto, RDF.type, OWL.Ontology) not in old:
        raise RuntimeError(f"{OLD.name}: no ontology header")
    props = (DCTERMS.creator, DCTERMS.created, DCTERMS.modified,
             VANN.preferredNamespacePrefix, VANN.preferredNamespaceUri)
    for p in props:
        if (onto, p, None) in old:
            raise RuntimeError(f"{OLD.name}: the header already has {p}")

    mild = rdflib.Graph().parse(MILD, format="turtle")
    creators = set(mild.objects(URIRef(MILD_IRI), DCTERMS.creator))
    if len(creators) != 2 or sum(isinstance(c, URIRef) for c in creators) != 1:
        raise RuntimeError(f"{MILD.name}: expected one ORCID IRI and one name as creator, found {creators}")
    for p in props:   # every property MILD uses for these, in MILD's form
        if (URIRef(MILD_IRI), p, None) not in mild:
            raise RuntimeError(f"{MILD.name}: the header has no {p}; nothing to follow")
    if mild.value(URIRef(MILD_IRI), VANN.preferredNamespaceUri).datatype is not None:
        raise RuntimeError(f"{MILD.name}: preferredNamespaceUri is not a plain string; form changed")

    added = {(onto, DCTERMS.creator, c) for c in creators} | {
        (onto, DCTERMS.created, Literal(CREATED, datatype=XSD.date)),
        (onto, DCTERMS.modified, Literal(MODIFIED, datatype=XSD.date)),
        (onto, VANN.preferredNamespacePrefix, Literal("WONT")),
        (onto, VANN.preferredNamespaceUri, Literal(WONT_IRI + "/")),
    }
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    g.bind("vann", VANN)
    for t in old:
        g.add(t)
    for t in added:
        g.add(t)
    _, gone, came = graph_diff(to_isomorphic(old), to_isomorphic(g))
    if len(gone) or set(came) != added:
        raise RuntimeError(f"{OLD.name}: {len(gone)} triples gone, {len(came)} come; expected the {len(added)} header triples")
    print(f"[header] {OLD.name}: {len(old):,} triples -> {len(g):,}")
    for _, p, o in sorted(added, key=lambda t: (str(t[1]), str(t[2]))):
        print(f"[header]   {g.namespace_manager.normalizeUri(p)} {o.n3(g.namespace_manager)}")

    if not write:
        print(f"[header] dry run; --write writes {NEW.name}")
        return 0
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError(f"{NEW.name}: the written file is not the graph meant")
    print(f"[header] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
