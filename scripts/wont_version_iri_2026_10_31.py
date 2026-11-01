"""WONT gets a version IRI, as MILD has one (2026-10-31).

The thesis (relayed by the thesis session, 2026-10-31, the curator's "schick der
pipeline-sitzung die wont-aufgaben") names "die Versions-IRI
https://bioportal.bioontology.org/ontologies/WONT/0.1.0" beside the namespace;
WONT's header had none. MILD's header (`mild_2026-10-30g.ttl`) carries
`owl:versionIRI <https://bioportal.bioontology.org/ontologies/MILD/0.1.0>`;
WONT now carries the same pattern. Nothing else of the header is touched.

`ground_truth_final_2026-10-31c.owl` is `..._2026-10-31b.owl` plus that one
triple; the graph difference is checked to be exactly it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-31b.owl", GT / "ground_truth_final_2026-10-31c.owl"
ONTOLOGY = "https://bioportal.bioontology.org/ontologies/WONT"
VERSION = ONTOLOGY + "/0.1.0"


def main(argv) -> int:
    import rdflib
    from rdflib import OWL, RDF, URIRef
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    old = rdflib.Graph().parse(OLD, format="turtle")
    onto = URIRef(ONTOLOGY)
    if (onto, RDF.type, OWL.Ontology) not in old:
        raise RuntimeError(f"{OLD.name}: no ontology header for {ONTOLOGY}")
    have = list(old.objects(onto, OWL.versionIRI))
    if have:
        raise RuntimeError(f"{OLD.name}: already has a version IRI {have}")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    g.add((onto, OWL.versionIRI, URIRef(VERSION)))
    _, gone, came = graph_diff(to_isomorphic(old), to_isomorphic(g))
    if len(gone) or set(came) != {(onto, OWL.versionIRI, URIRef(VERSION))}:
        raise RuntimeError(f"changed triples: {len(gone)} gone, {len(came)} come; expected the version IRI only")
    print(f"[version] {OLD.name}: {len(old):,} triples -> {len(g):,}; owl:versionIRI <{VERSION}>")
    if "--write" not in argv:
        print(f"[version] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError("the written file is not the graph meant")
    print(f"[version] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
