"""A wound is an injury of which a part is skin; every such injury is a wound (2026-10-30).

The curator, on the thesis's description of Wound: "da fehlt noch dass eine
wunde auf jeden fall eine hautschädigung betrifft die in continuitatem auch
eine schädigung von faszie muskle knochen etc. sein kann. aber ohne einen
hautschaden ist eine wunde keine wunde. nekrotisches gewebe der haut ist auch
schon eine wunde auch wenn es noch anhänglich ist. daher sind alle wunden auch
injuries ... deswegen gibt es brandwunden die immer brandverletzungen sind und
brandverletzungen der inneren atemwege die wiederum keine wunden sind." Asked
whether skin damage should also be enough: "wenn injury AND ein teil der
injury ist haut ist es sicher eine Wunde".

So Wound (WONT_0000380) is defined, in his words:

    Class: Wound
        EquivalentTo: Injury and ('has part' some ('part of' some Skin))

(`has part` BFO_0000051, `part of` BFO_0000050, Skin FMA_7163, as WONT's Skin
wound already names it); its other axioms stay, and its definition says it.
`ground_truth_final_2026-10-30b.owl` is `..._2026-10-30.owl` with that one
equivalence and the new definition; the graphs are compared.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-30.owl", GT / "ground_truth_final_2026-10-30b.owl"
W, OBO = "https://bioportal.bioontology.org/ontologies/WONT/", "http://purl.obolibrary.org/obo/"
WOUND, INJURY, SKIN = W + "WONT_0000380", W + "WONT_0007817", OBO + "FMA_7163"
DEF_OLD = "A material disease entity that is the output of a wound development process."
DEF_NEW = ("An injury that has as part a portion of the skin, alone or in continuity with damaged deeper tissue such "
           "as fascia, muscle or bone, and that is the output of a wound development process. Damaged skin tissue is "
           "a wound even while it is still attached, such as necrotic skin; an injury that involves no skin, such as "
           "a burn of the inner airways, is no wound.")


def main(argv) -> int:
    import rdflib
    from rdflib import BNode, Literal, OWL, RDF, URIRef
    from rdflib.collection import Collection
    old = rdflib.Graph().parse(OLD, format="turtle")
    wound, iao = URIRef(WOUND), URIRef(OBO + "IAO_0000115")
    if (wound, iao, Literal(DEF_OLD, lang="en")) not in old:
        raise RuntimeError("Wound's definition is not the one expected")
    if any(True for _ in old.objects(wound, OWL.equivalentClass)):
        raise RuntimeError("Wound already has an equivalent class")
    if (URIRef(SKIN), None, None) not in old and (None, None, URIRef(SKIN)) not in old:
        raise RuntimeError("WONT does not name Skin (FMA_7163)")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    g.remove((wound, iao, Literal(DEF_OLD, lang="en")))
    g.add((wound, iao, Literal(DEF_NEW, lang="en")))
    part_of_skin, has_part, eq, lst = BNode(), BNode(), BNode(), BNode()
    g.add((part_of_skin, RDF.type, OWL.Restriction))
    g.add((part_of_skin, OWL.onProperty, URIRef(OBO + "BFO_0000050")))
    g.add((part_of_skin, OWL.someValuesFrom, URIRef(SKIN)))
    g.add((has_part, RDF.type, OWL.Restriction))
    g.add((has_part, OWL.onProperty, URIRef(OBO + "BFO_0000051")))
    g.add((has_part, OWL.someValuesFrom, part_of_skin))
    Collection(g, lst, [URIRef(INJURY), has_part])
    g.add((eq, RDF.type, OWL.Class))
    g.add((eq, OWL.intersectionOf, lst))
    g.add((wound, OWL.equivalentClass, eq))
    print(f"[wound] {OLD.name}: {len(old):,} triples -> {len(g):,}; Wound EquivalentTo Injury and "
          f"('has part' some ('part of' some Skin)); definition replaced")
    if "--write" not in argv:
        print(f"[wound] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    g.serialize(NEW, format="turtle")
    back = rdflib.Graph().parse(NEW, format="turtle")
    from rdflib.compare import isomorphic
    if not isomorphic(back, g):
        raise RuntimeError("the written file is not the graph meant")
    print(f"[wound] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
