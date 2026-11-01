"""Every injury, and so every wound, has a place in FMA (2026-10-30).

The curator: "es müssen noch die aussagen rein, dass jede wunde und jede
injury einen ort hat mit verweist auf die FMA. Ich glaube subdivision of
cardinal body part war die klasse die ich immer verwendet habe."

    Class: Injury
        SubClassOf: 'located in' some 'Subdivision of cardinal body part'

`located in` is RO_0001025, the relation WONT's own location axioms use (Skin
wound, Foot wound); Subdivision of cardinal body part is FMA_67504, which
holds every region (rule 90). Wound is a subclass of Injury and inherits it.
`ground_truth_final_2026-10-30c.owl` is `..._2026-10-30b.owl` with this one
axiom; the graphs are compared.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-30b.owl", GT / "ground_truth_final_2026-10-30c.owl"
W, OBO = "https://bioportal.bioontology.org/ontologies/WONT/", "http://purl.obolibrary.org/obo/"
INJURY, LOCATED_IN, REGION = W + "WONT_0007817", OBO + "RO_0001025", OBO + "FMA_67504"


def main(argv) -> int:
    import rdflib
    from rdflib import BNode, OWL, RDF, RDFS, URIRef
    from rdflib.compare import isomorphic
    old = rdflib.Graph().parse(OLD, format="turtle")
    injury = URIRef(INJURY)
    if str(old.value(injury, RDFS.label)) != "Injury":
        raise RuntimeError("WONT_0007817 is not Injury")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    r = BNode()
    g.add((r, RDF.type, OWL.Restriction))
    g.add((r, OWL.onProperty, URIRef(LOCATED_IN)))
    g.add((r, OWL.someValuesFrom, URIRef(REGION)))
    g.add((injury, RDFS.subClassOf, r))
    print(f"[location] {OLD.name}: {len(old):,} triples -> {len(g):,}; Injury SubClassOf 'located in' some "
          f"'Subdivision of cardinal body part'")
    if "--write" not in argv:
        print(f"[location] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError("the written file is not the graph meant")
    print(f"[location] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
