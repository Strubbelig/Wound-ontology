"""The curator's definitions for the undefined WONT classes, the immunodeficiency class, merges, an obsoletion and renames (2026-10-31).

Relayed by the thesis session, his words: "all ok, merge 18 and 19" -- to its
list of drafts for the classes still without a definition; option B for the
immune disorder approved with its definition. `ground_truth_final_2026-10-31g.owl`
is `..._2026-10-31f.owl` with:

* 16 definitions, word for word, without a draft marker (they are approved);
* WONT_0003586 "Immunodeficiency disorder", a material disease entity (MILD_120020),
  with its definition. The IRI is the one the pipeline minted for the term
  (`data/registry/wont_ids.json`); the class is curated from now on, and the
  extension resolves the term to it by its label;
* Redness (WONT_0000257) merged into reddened (WONT_0000456), Thread size 1-0
  (WONT_0000318) into Thread size 0 (WONT_0000316), which gets "1-0" as a
  synonym -- WONT states synonyms as IAO_0000118. Both obsolete in MILD's form,
  as Aseptic cuticle plan specification is.
* wound signaling function (WONT_120001) obsolete without replacement ("20
  obsolete": its author cannot say what it means). MILD's obsolete form without
  "term replaced by" and without a reason: none of IAO's reasons says a term's
  meaning is unclear, and the comment says so;
* the first and second wound dressing layer functions get their definitions
  ("21/22 ok");
* four renames, IRIs kept ("rename all four"): Bepanthen ointment is
  Dexpanthenol ointment and Voltaren gel is Diclofenac gel, each keeping the
  brand name as a related synonym (oboInOwl:hasRelatedSynonym: a brand names a
  product, not the class); Wound fabric adhesive and Wound staple plastering
  plan specification are Wound tissue adhesive and Wound closure strip plan
  specification, with no synonym, since the old names mistranslate
  "Gewebekleber" and "Klammerpflaster" -- the synonyms "Wound Fabric adhesive"
  and "Wound staple plastering" carry the same mistranslations and go too;
* "Redness" as a synonym of reddened ("yes to redness synonym"), so the
  pipeline's terms placed under Redness find reddened instead of minting it anew;
* URGE scale (WONT_0000352) is "Wound assessment scheme of surroundings, edge,
  base and exudate", with his original term "URGE scheme" (Umgebung, Rand,
  Grund, Exsudat) as a synonym and its definition ("URGE ok").

Labels stay as they are. The graph difference is checked to be exactly this.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-31f.owl", GT / "ground_truth_final_2026-10-31g.owl"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
MILD_NS = "https://bioportal.bioontology.org/ontologies/MILD/"
OBO = "http://purl.obolibrary.org/obo/"
SAID = "curator 2026-10-31, relayed by the thesis session: \"all ok, merge 18 and 19\""
SAID_LAST = "curator 2026-10-31, relayed by the thesis session: \"yes to redness synonym, URGE ok\""
SAID_LATER = "curator 2026-10-31, relayed by the thesis session: \"21/22 ok, 20 obsolete, rename all four\""

# id -> (label it must carry, definition)
DEFINITIONS = {
    "WONT_0000004": ("Acidity impact process in wound development",
                     "An acidity impact process that is a wound development subprocess."),
    "WONT_0000140": ("Heat impact process in wound development",
                     "A heat impact process that is a wound development subprocess."),
    "WONT_0000245": ("Pressure impact process in wound development",
                     "A pressure impact process that is a wound development subprocess."),
    "WONT_0000138": ("Hand disinfection plan specification",
                     "An aseptic conditions plan specification that prescribes that the hands of those treating the "
                     "wound be disinfected with an antiseptic agent before they touch the wound or sterile material."),
    "WONT_0000297": ("Surface disinfection plan specification",
                     "An aseptic conditions plan specification that prescribes that the surfaces on which instruments "
                     "and materials for the wound treatment are laid out be disinfected beforehand."),
    "WONT_0000427": ("Wound-integrating wound dressing",
                     "A wound dressing that is made to remain in the wound bed, where it is resorbed or becomes "
                     "incorporated into the newly formed tissue."),
    "WONT_0000430": ("Wounds classified according to Tscherne and Oestern",
                     "A wound with accompanying fracture that is a skin wound whose accompanying soft-tissue damage is "
                     "graded by the Tscherne and Oestern wound classification."),
    "WONT_120018": ("wound infecting tendency",
                    "A tendency that inheres in a microorganism and is realized in processes in which the "
                    "microorganism invades and multiplies in the tissue of a wound."),
    "WONT_0000037": ("Bepanthen ointment",
                     "A wound gel/ointment/cream that is an ointment with dexpanthenol as its active ingredient."),
    "WONT_0000358": ("Voltaren gel",
                     "A wound gel/ointment/cream that is a gel with diclofenac as its active ingredient."),
    "WONT_0000043": ("Bismuth III bromide",
                     "An antiseptic metal ion that is trivalent bismuth, applied as the compound bismuth(III) bromide."),
    "WONT_0000236": ("Planimetry",
                     "A wound size measurement process in which the outline of the wound is traced or photographed "
                     "and the area it encloses is determined."),
    "WONT_0000375": ("Wagner and Anderson wound classification",
                     "A wound classification scale that grades a diabetic foot wound by combining a depth grade from 1 "
                     "to 4 with a stage from A to D that records whether neither, infection, ischaemia or both are "
                     "present."),
    "WONT_0000405": ("Wound fabric adhesive plan specification",
                     "A wound closure technique plan specification that prescribes closing the wound by applying a "
                     "tissue adhesive that bonds the approximated wound edges."),
    "WONT_0000421": ("Wound staple plastering plan specification",
                     "A wound closure technique plan specification that prescribes holding the approximated wound "
                     "edges together with adhesive skin closure strips placed across the wound."),
    "WONT_120002": ("first wound dressing layer function",
                    "A wound dressing layer function that is borne by a layer of a wound dressing made to lie directly "
                    "on the wound, and that is realized when the layer is placed there."),
    "WONT_120003": ("second wound dressing layer function",
                    "A wound dressing layer function that is borne by a layer of a wound dressing made to lie over a "
                    "layer that lies directly on the wound, and that is realized when the layer is placed there."),
    "WONT_0000352": ("URGE scale",
                     "A wound classification scale that structures the assessment of a wound into four features "
                     "recorded in turn: the skin surrounding the wound, the wound edge, the wound base and the exudate."),
    "WONT_0000417": ("Wound pocket",
                     "A material entity that is part of a wound and consists of the tissue enclosing a space that "
                     "extends from the wound bed under the wound edge or into deeper tissue."),
}
NEW_CLASS = ("WONT_0003586", "Immunodeficiency disorder", MILD_NS + "MILD_120020",
             "A material disease entity in which components of the immune system (immune cells, antibodies or "
             "lymphoid tissue) are missing, reduced in number or abnormally built.")
RETIRED = ("WONT_120001", "wound signaling function",
           "Made obsolete without replacement: what it means could not be said, not even by its author ("
           + "{said}). No obsolescence reason is given, since none of IAO's (failed exploratory term, placeholder "
           "removed, terms merged, term imported, term split, out of scope) says that a term's meaning is unclear.")
# id -> (old label, new label, related synonym kept or None, synonyms that go with the old label)
RENAMES = {
    "WONT_0000037": ("Bepanthen ointment", "Dexpanthenol ointment", "Bepanthen ointment", ()),
    "WONT_0000358": ("Voltaren gel", "Diclofenac gel", "Voltaren gel", ()),
    "WONT_0000405": ("Wound fabric adhesive plan specification", "Wound tissue adhesive plan specification", None,
                     ("Wound Fabric adhesive",)),
    "WONT_0000421": ("Wound staple plastering plan specification", "Wound closure strip plan specification", None,
                     ("Wound staple plastering",)),
    "WONT_0000352": ("URGE scale", "Wound assessment scheme of surroundings, edge, base and exudate", None, ()),
}
# id -> synonym (IAO_0000118) it gains
EXACT = {"WONT_0000456": "Redness", "WONT_0000352": "URGE scheme"}
OLD_NAMES = ("bepanthen", "voltaren", "fabric adhesive", "staple plastering", "signaling function", "urge scale")
# obsolete id -> (its label, merged into, that one's label, synonym the survivor gets or None)
MERGES = {
    "WONT_0000257": ("Redness", "WONT_0000456", "reddened", None),
    "WONT_0000318": ("Thread size 1-0", "WONT_0000316", "Thread size 0", "1-0"),
}


def main(argv) -> int:
    import rdflib
    from rdflib import OWL, RDF, RDFS, Literal, URIRef
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    write = "--write" in argv
    if write and NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    IAO115, IAO118, IAO119 = URIRef(OBO + "IAO_0000115"), URIRef(OBO + "IAO_0000118"), URIRef(OBO + "IAO_0000119")
    REPLACED_BY, REASON, TERMS_MERGED = URIRef(OBO + "IAO_0100001"), URIRef(OBO + "IAO_0000231"), URIRef(OBO + "IAO_0000227")
    w = lambda i: URIRef(W + i)

    old = rdflib.Graph().parse(OLD, format="turtle")
    gone, came = set(), set()

    for i, (label, text) in DEFINITIONS.items():
        if str(old.value(w(i), RDFS.label)) != label:
            raise RuntimeError(f"{i}: labelled {old.value(w(i), RDFS.label)!r}, expected {label!r}")
        if (w(i), IAO115, None) in old or (w(i), IAO119, None) in old:
            raise RuntimeError(f"{i} {label}: already has a definition or a draft marker")
        came.add((w(i), IAO115, Literal(text, lang="en")))

    i, label, parent, text = NEW_CLASS
    if (w(i), None, None) in old or (None, None, w(i)) in old:
        raise RuntimeError(f"{i} is already in WONT")
    if any(str(o).lower() == label.lower() for o in old.objects(None, RDFS.label)) or \
            any(str(o).lower() == label.lower() for o in old.objects(None, IAO118)):
        raise RuntimeError(f"another WONT class already answers to {label!r}")
    came |= {(w(i), RDF.type, OWL.Class), (w(i), RDFS.label, Literal(label, lang="en")),
             (w(i), RDFS.subClassOf, URIRef(parent)), (w(i), IAO115, Literal(text, lang="en"))}

    for gone_id, (label, into, into_label, synonym) in MERGES.items():
        if str(old.value(w(gone_id), RDFS.label)) != label or str(old.value(w(into), RDFS.label)) != into_label:
            raise RuntimeError(f"{gone_id} -> {into}: labels are not {label!r} and {into_label!r}")
        if list(old.subject_predicates(w(gone_id))):
            raise RuntimeError(f"{gone_id} {label}: something in WONT refers to it; the merge does not cover that")
        own = set(old.triples((w(gone_id), None, None)))
        if any(isinstance(o, rdflib.BNode) for _, _, o in own) or (w(gone_id), IAO115, None) in old:
            raise RuntimeError(f"{gone_id} {label}: has a definition or an anonymous axiom; read it before obsoleting")
        lab = old.value(w(gone_id), RDFS.label)
        gone |= {t for t in own if t[1] != RDF.type}
        note = f"Merged into {into} {into_label}" + (f", which carries '{synonym}' as a synonym" if synonym else "") + f" ({SAID})."
        came |= {(w(gone_id), RDFS.label, Literal("obsolete " + str(lab), lang=lab.language)),
                 (w(gone_id), OWL.deprecated, Literal(True)),
                 (w(gone_id), REASON, TERMS_MERGED),
                 (w(gone_id), REPLACED_BY, w(into)),
                 (w(gone_id), RDFS.comment, Literal(note, lang="en"))}
        if synonym:
            came.add((w(into), IAO118, Literal(synonym, lang="en")))
    i, label, note = RETIRED
    if str(old.value(w(i), RDFS.label)) != label or list(old.subject_predicates(w(i))):
        raise RuntimeError(f"{i}: not {label!r}, or something in WONT refers to it")
    own = set(old.triples((w(i), None, None)))
    if any(isinstance(o, rdflib.BNode) for _, _, o in own) or (w(i), IAO115, None) in old:
        raise RuntimeError(f"{i} {label}: has a definition or an anonymous axiom; read it before obsoleting")
    lab = old.value(w(i), RDFS.label)
    gone |= {t for t in own if t[1] != RDF.type}
    came |= {(w(i), RDFS.label, Literal("obsolete " + str(lab), lang=lab.language)),
             (w(i), OWL.deprecated, Literal(True)),
             (w(i), RDFS.comment, Literal(note.format(said=SAID_LATER), lang="en"))}

    RELATED = URIRef("http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym")
    for i, (was, now, related, dropped) in RENAMES.items():
        lab = old.value(w(i), RDFS.label)
        if str(lab) != was:
            raise RuntimeError(f"{i}: labelled {lab!r}, expected {was!r}")
        gone.add((w(i), RDFS.label, lab))
        came.add((w(i), RDFS.label, Literal(now, lang=lab.language)))
        if related:
            came.add((w(i), RELATED, Literal(related, lang="en")))
        syns = {str(o): o for o in old.objects(w(i), IAO118)}
        if set(syns) != set(dropped):
            raise RuntimeError(f"{i}: synonyms {sorted(syns)}, expected {sorted(dropped)}")
        gone |= {(w(i), IAO118, syns[s]) for s in dropped}
    for i, syn in EXACT.items():
        if (w(i), IAO118, Literal(syn, lang="en")) in old:
            raise RuntimeError(f"{i} already carries {syn!r}")
        came.add((w(i), IAO118, Literal(syn, lang="en")))

    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        if t not in gone:
            g.add(t)
    for t in came:
        g.add(t)
    _, really_gone, really_came = graph_diff(to_isomorphic(old), to_isomorphic(g))
    if set(really_gone) != gone or set(really_came) != came:
        raise RuntimeError(f"{OLD.name}: the difference is not the one meant ({len(really_gone)} gone, {len(really_came)} come)")

    quoting = [(str(s)[len(W):], str(p).rsplit("/", 1)[-1], str(o)) for s, p, o in g
               if isinstance(o, Literal) and any(n in str(o).lower() for n in OLD_NAMES)
               and not (p == RELATED or (p == RDFS.label and str(o).startswith("obsolete ")))]
    if quoting:
        raise RuntimeError(f"text still quoting an old name: {quoting}")
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef) and str(s).startswith(W)}
    live = {s for s in classes if (s, OWL.deprecated, Literal(True)) not in g}
    defined = {s for s in live if (s, IAO115, None) in g}
    print(f"[defs] {OLD.name}: {len(old):,} triples -> {len(g):,}; {len(gone)} gone, {len(came)} come"
          f"; synonyms gained: {EXACT}")
    print(f"[defs]   definitions written: {len(DEFINITIONS) + 1}; new class {NEW_CLASS[0]}; obsolete: {', '.join([*MERGES, RETIRED[0]])}; "
          f"renamed: {', '.join(RENAMES)}; no other text quotes an old name")
    print(f"[defs]   WONT classes {len(classes)}, of them not obsolete {len(live)}, with a definition {len(defined)}, "
          f"without {len(live - defined)}; draft markers {len(set(g.subjects(IAO119, None)))}")
    print("[defs]   without a definition: " + "; ".join(sorted(f"{str(s)[len(W):]} {g.value(s, RDFS.label)}" for s in live - defined)))

    if not write:
        print(f"[defs] dry run; --write writes {NEW.name}")
        return 0
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError(f"{NEW.name}: the written file is not the graph meant")
    print(f"[defs] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
