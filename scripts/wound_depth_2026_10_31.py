"""How deep a wound reaches, in FMA's layers (2026-10-31).

The curator, on the thesis's outlook ("ich will das vor submission erledigt
haben, nicht offen lassen"): WONT says a wound has a part of the skin and an
injury lies in a subdivision of a cardinal body part, not how deep a wound
reaches. His choices: six layers (epidermis, dermis, subcutis, fascia, muscle,
bone), the classes side by side ("Nebeneinander"), the four burn degrees bound
to them ("Ja, wie ihre Definitionen"), the definitions as drafted ("Alle ok").

`ground_truth_final_2026-10-31i.owl` is `..._2026-10-31h.owl` with:

* `owl:imports` of WONT's FMA module (the OBO FMA 2020-04-13, as OFL) and of
  the part bridge FMA -> OFL -> BFO (`scripts/wont_fma_module_and_bridge_2026_10_31.py`);
* six classes `Wound reaching the <layer>` = Wound and has part some (part of
  some <FMA layer>), the pattern Wound itself uses for Skin. Not nested: a wound
  that reaches the bone need not pass through a fascia (over the anterior border
  of the tibia); the deepest class a wound falls under is its depth;
* First-degree burn wound reaches the epidermis, Second- and Third-degree the
  dermis, Fourth-degree the subcutis -- "at least", as their definitions say
  (confined to the epidermis; into the dermis; through the full thickness of the
  skin; beyond the skin into underlying tissue). "Only so deep" would need
  negation, which EL does not have.

The graph difference is checked to be exactly this.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-31h.owl", GT / "ground_truth_final_2026-10-31i.owl"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
OBO = "http://purl.obolibrary.org/obo/"
IMPORTS = (W + "modules/fma_module.owl", W + "bridges/fma_ofl_bfo_part.owl")
WOUND = W + "WONT_0000380"
SAID = "curator 2026-10-31: \"ich will das vor submission erledigt haben, nicht offen lassen\"; definitions \"Alle ok\""
# id -> (label, FMA layer, its label in the module, definition)
DEPTH = {
    "WONT_120087": ("Wound reaching the epidermis", "FMA_70596", "Epidermis",
                    "A wound that has as part a portion of the epidermis: the damage reaches at least into the epidermis."),
    "WONT_120088": ("Wound reaching the dermis", "FMA_70323", "Dermis",
                    "A wound that has as part a portion of the dermis: the damage reaches at least into the dermis."),
    "WONT_120089": ("Wound reaching the subcutis", "FMA_9630", "Superficial fascia",
                    "A wound that has as part a portion of the subcutis, the superficial fascia: the damage reaches at "
                    "least into the subcutis."),
    "WONT_120090": ("Wound reaching the fascia", "FMA_27935", "Investing fascia",
                    "A wound that has as part a portion of the investing fascia, the deep fascia that invests the "
                    "muscles: the damage reaches at least into the fascia."),
    "WONT_120091": ("Wound reaching the muscle", "FMA_5022", "Muscle organ",
                    "A wound that has as part a portion of a muscle organ: the damage reaches at least into the muscle."),
    "WONT_120092": ("Wound reaching the bone", "FMA_5018", "Bone organ",
                    "A wound that has as part a portion of a bone organ: the damage reaches at least into the bone."),
}
COMMENT = ("One of six depth classes -- epidermis, dermis, subcutis, fascia, muscle, bone, as FMA (release 2020-04-13, "
           "the FMA OFL imports) names them: the deepest of them a wound falls under is how deep it reaches. They are "
           "not nested, since a wound that reaches the bone need not pass through a fascia, as over the anterior border "
           "of the tibia. Added 2026-10-31 (" + SAID + ").")
# burn wound -> (its label, the depth class it reaches at least)
BURNS = {"WONT_0000482": ("First-degree burn wound", "WONT_120087"),
         "WONT_0000483": ("Second-degree burn wound", "WONT_120088"),
         "WONT_0000484": ("Third-degree burn wound", "WONT_120088"),
         "WONT_0000485": ("Fourth-degree burn wound", "WONT_120089")}


def main(argv) -> int:
    import rdflib
    from rdflib import OWL, RDF, RDFS, BNode, Literal, URIRef
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    write = "--write" in argv
    if write and NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    IAO115, IAO118 = URIRef(OBO + "IAO_0000115"), URIRef(OBO + "IAO_0000118")
    HAS_PART, PART_OF = URIRef(OBO + "BFO_0000051"), URIRef(OBO + "BFO_0000050")
    w = lambda i: URIRef(W + i)
    module = rdflib.Graph().parse(GT / "modules" / "wont_fma_module.owl", format="xml")

    old = rdflib.Graph().parse(OLD, format="turtle")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    named, anonymous = set(), 0

    def add(t):
        g.add(t); named.add(t)

    onto = next(old.subjects(RDF.type, OWL.Ontology))
    for iri in IMPORTS:
        if (onto, OWL.imports, URIRef(iri)) in old:
            raise RuntimeError(f"WONT already imports {iri}")
        add((onto, OWL.imports, URIRef(iri)))

    if str(old.value(URIRef(WOUND), RDFS.label)) != "Wound":
        raise RuntimeError(f"{WOUND} is not Wound")
    for i, (label, layer, layer_label, text) in DEPTH.items():
        s = w(i)
        if (s, None, None) in old or (None, None, s) in old:
            raise RuntimeError(f"{i} is already in WONT")
        if any(str(o).lower() == label.lower() for p in (RDFS.label, IAO118) for o in old.objects(None, p)):
            raise RuntimeError(f"another WONT class already answers to {label!r}")
        if str(module.value(URIRef(OBO + layer), RDFS.label)) != layer_label:
            raise RuntimeError(f"{layer} is not {layer_label!r} in the FMA module")
        for t in [(s, RDF.type, OWL.Class), (s, RDFS.label, Literal(label, lang="en")),
                  (s, RDFS.subClassOf, URIRef(WOUND)), (s, IAO115, Literal(text, lang="en")),
                  (s, RDFS.comment, Literal(COMMENT, lang="en"))]:
            add(t)
        # s EquivalentTo Wound and (has part some (part of some layer))
        c, inner, outer, n1, n2 = BNode(), BNode(), BNode(), BNode(), BNode()
        new = [(s, OWL.equivalentClass, c), (c, RDF.type, OWL.Class), (c, OWL.intersectionOf, n1),
               (n1, RDF.first, URIRef(WOUND)), (n1, RDF.rest, n2), (n2, RDF.first, outer), (n2, RDF.rest, RDF.nil),
               (outer, RDF.type, OWL.Restriction), (outer, OWL.onProperty, HAS_PART), (outer, OWL.someValuesFrom, inner),
               (inner, RDF.type, OWL.Restriction), (inner, OWL.onProperty, PART_OF),
               (inner, OWL.someValuesFrom, URIRef(OBO + layer))]
        for t in new:
            g.add(t)
        anonymous += len(new)

    for i, (label, depth) in BURNS.items():
        if str(old.value(w(i), RDFS.label)) != label:
            raise RuntimeError(f"{i} is {old.value(w(i), RDFS.label)!r}, expected {label!r}")
        add((w(i), RDFS.subClassOf, w(depth)))

    _, gone, came = graph_diff(to_isomorphic(old), to_isomorphic(g))
    c_named = {t for t in came if not any(isinstance(x, BNode) for x in t)}
    if set(gone) or c_named != named or len(set(came)) - len(c_named) != anonymous:
        raise RuntimeError(f"{OLD.name}: the difference is not the one meant: {len(set(gone))} gone; named "
                           f"{len(c_named)}/{len(named)}, anonymous {len(set(came)) - len(c_named)}/{anonymous} come")
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef) and str(s).startswith(W)}
    live = {s for s in classes if (s, OWL.deprecated, Literal(True)) not in g}
    defined = {s for s in live if (s, IAO115, None) in g}
    print(f"[depth] {OLD.name}: {len(old):,} triples -> {len(g):,}; nothing gone; named {len(named)} come, "
          f"anonymous {anonymous} come")
    print(f"[depth]   imports: {', '.join(IMPORTS)}; depth classes: {', '.join(v[0] for v in DEPTH.values())}; "
          f"burn degrees bound: {len(BURNS)}")
    print(f"[depth]   WONT classes {len(classes)}, of them not obsolete {len(live)}, with a definition {len(defined)}, "
          f"without {len(live - defined)}")
    if not write:
        print(f"[depth] dry run; --write writes {NEW.name}")
        return 0
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError(f"{NEW.name}: the written file is not the graph meant")
    print(f"[depth] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
