"""The curator's definition review and superclass decisions go into WONT; MILD's modified date (2026-10-31).

Relayed by the thesis session, his words: "i have accepted all definitions";
"i agree with 1,2,3,4,5 … i agree with 7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24";
on #6: "B, and yes set MILD's modified date".

`ground_truth_final_2026-10-31f.owl` is `..._2026-10-31e.owl` with:

* the draft marker IAO_0000119 taken off the 275 classes whose draft he
  accepted. The answers are read back from the review page's database
  (`data/review/definition_review_2026-10-31/answers/drafts/`, one document per
  class, saved 2026-10-31 19:50-20:01): each must say "accept", carry no text of
  his own, and show the draft that WONT holds today. The page's `missing`
  collection is empty, so the classes without a definition stay without one.
* #1-3: Acidity, Heat and Pressure impact process in wound development get
  their named parent (Acidity, Heat, Pressure impact process) beside the
  equivalence they keep, as their sibling Angiopathic disease process in
  wound development has.
* #4: Aseptic cuticle plan specification, a mistranslation of "aseptische
  Kautelen", is merged into Aseptic conditions plan specification. Its three
  children move there; it is made obsolete in MILD's form (label "obsolete
  ...", owl:deprecated, obsolescence reason "terms merged", term replaced by,
  a comment saying so, no logical axiom, no synonym). Wearing sterile gloves
  plan specification's accepted definition named the obsolete class as its
  genus; it now names the class it was merged into, the rest word for word.
* #5: Bismuth III bromide is an Antiseptic metal ion, no longer directly a
  Material used for wound treatment; its antiseptic drug role stays.
* #6: Immunosuppression is a disease predisposition (MILD_120023), no longer a
  material disease entity (MILD_120020), with the definition he chose ("B").

`mild_2026-10-31b.ttl` is `mild_2026-10-31.ttl` with dcterms:modified
"2026-10-31" for "2026-07-06", edited as text so the Protégé layout stays.

Each graph difference is checked to be exactly what is listed here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-31e.owl", GT / "ground_truth_final_2026-10-31f.owl"
MILD_OLD, MILD_NEW = (ROOT.parent / "Disease ontologies" / "mild_2026-10-31.ttl",
                      ROOT.parent / "Disease ontologies" / "mild_2026-10-31b.ttl")
ANSWERS = ROOT / "data" / "review" / "definition_review_2026-10-31" / "answers"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
MILD_NS = "https://bioportal.bioontology.org/ontologies/MILD/"
OBO = "http://purl.obolibrary.org/obo/"
MILD_MODIFIED_OLD = 'dcterms:modified "2026-07-06"^^xsd:date ;'
MILD_MODIFIED_NEW = 'dcterms:modified "2026-10-31"^^xsd:date ;'

NAMED_PARENT = {"WONT_0000004": "WONT_0000517", "WONT_0000140": "WONT_0000518", "WONT_0000245": "WONT_0000519"}
MERGED, INTO = "WONT_0000030", "WONT_0000029"
MERGED_CHILDREN = {"WONT_0000138", "WONT_0000297", "WONT_0000378"}
GENUS_OLD, GENUS_NEW = "An aseptic cuticle plan specification that ", "An aseptic conditions plan specification that "
MERGED_COMMENT = ("Merged into WONT_0000029 Aseptic conditions plan specification: 'aseptic cuticle' is a "
                  "mistranslation of the German 'aseptische Kautelen', aseptic conditions (curator 2026-10-31, "
                  "relayed by the thesis session: \"i agree with 1,2,3,4,5\").")
REPARENT = {"WONT_0000043": (W + "WONT_0000188", W + "WONT_0000022"),        # Bismuth III bromide
            "WONT_0000161": (MILD_NS + "MILD_120020", MILD_NS + "MILD_120023")}  # Immunosuppression
IMMUNOSUPPRESSION_DEF = ("A disease predisposition that inheres in a patient whose immune response is weaker than "
                         "normal, whether through a disorder of the immune system or through drugs given to suppress it.")


def read_answers(g, IAO115, IAO119, URIRef):
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ANSWERS / "drafts").glob("*.json"))]
    missing = list((ANSWERS / "missing").glob("*.json")) if (ANSWERS / "missing").exists() else []
    if missing:
        raise RuntimeError(f"{len(missing)} answers for classes without a definition; this script applies none")
    marked = {str(s)[len(W):] for s in g.subjects(IAO119, None)}
    ids = {d["id"] for d in docs}
    if len(docs) != 275 or ids != marked:
        raise RuntimeError(f"{len(docs)} answers for {len(marked)} drafts; answered and marked differ by {len(ids ^ marked)}")
    for d in docs:
        if d.get("choice") != "accept" or (d.get("text") or "").strip():
            raise RuntimeError(f"{d['id']}: answer {d.get('choice')!r} with text {d.get('text')!r}; only acceptances are applied here")
        if str(g.value(URIRef(W + d["id"]), IAO115)) != d.get("draft"):
            raise RuntimeError(f"{d['id']}: the draft he saw is not the definition WONT holds")
    return ids


def main(argv) -> int:
    import rdflib
    from rdflib import OWL, RDF, RDFS, Literal, URIRef, XSD
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    write = "--write" in argv
    for p in (NEW, MILD_NEW):
        if write and p.exists():
            raise RuntimeError(f"{p} exists; not overwritten")
    IAO115, IAO118, IAO119 = URIRef(OBO + "IAO_0000115"), URIRef(OBO + "IAO_0000118"), URIRef(OBO + "IAO_0000119")
    REPLACED_BY, REASON, TERMS_MERGED = URIRef(OBO + "IAO_0100001"), URIRef(OBO + "IAO_0000231"), URIRef(OBO + "IAO_0000227")
    w = lambda i: URIRef(W + i)

    old = rdflib.Graph().parse(OLD, format="turtle")
    accepted = read_answers(old, IAO115, IAO119, URIRef)
    gone, came = set(), set()

    # the 275 acceptances: the marker goes, the definition stays
    for i in accepted:
        gone |= set(old.triples((w(i), IAO119, None)))

    # #1-3: the named parent beside the equivalence it already states
    for c, parent in NAMED_PARENT.items():
        eq = list(old.objects(w(c), OWL.equivalentClass))
        members = {m for e in eq for lst in old.objects(e, OWL.intersectionOf)
                   for m in rdflib.collection.Collection(old, lst)}
        if w(parent) not in members or (w(c), RDFS.subClassOf, None) in old:
            raise RuntimeError(f"{c}: expected an equivalence naming {parent} and no stated parent")
        came.add((w(c), RDFS.subClassOf, w(parent)))

    # #4: the merge
    children = {str(s)[len(W):] for s in old.subjects(RDFS.subClassOf, w(MERGED))}
    if children != MERGED_CHILDREN:
        raise RuntimeError(f"{MERGED}: children {sorted(children)}, expected {sorted(MERGED_CHILDREN)}")
    for ch in children:
        gone.add((w(ch), RDFS.subClassOf, w(MERGED)))
        came.add((w(ch), RDFS.subClassOf, w(INTO)))
    elsewhere = [t for t in old.triples((None, None, w(MERGED))) if t[0] not in {w(ch) for ch in children}]
    if elsewhere:
        raise RuntimeError(f"{MERGED} is used by {len(elsewhere)} more triples; the merge does not cover them")
    own = set(old.triples((w(MERGED), None, None)))
    if any(isinstance(o, rdflib.BNode) for _, _, o in own) or (w(MERGED), IAO115, None) in old:
        raise RuntimeError(f"{MERGED}: has a definition or an anonymous axiom; read it before obsoleting")
    label = old.value(w(MERGED), RDFS.label)
    gone |= {t for t in own if t[1] != RDF.type}
    came |= {(w(MERGED), RDFS.label, Literal("obsolete " + str(label), lang=label.language)),
             (w(MERGED), OWL.deprecated, Literal(True)),
             (w(MERGED), REASON, TERMS_MERGED),
             (w(MERGED), REPLACED_BY, w(INTO)),
             (w(MERGED), RDFS.comment, Literal(MERGED_COMMENT, lang="en"))}
    gloves = w("WONT_0000378")
    d = old.value(gloves, IAO115)
    defs_naming_it = [s for s, o in old.subject_objects(IAO115) if "cuticle" in str(o).lower()]
    if defs_naming_it != [gloves] or not str(d).startswith(GENUS_OLD):
        raise RuntimeError(f"definitions naming the aseptic cuticle: {defs_naming_it}; expected only the gloves' genus")
    gone.add((gloves, IAO115, d))
    came.add((gloves, IAO115, Literal(GENUS_NEW + str(d)[len(GENUS_OLD):], lang=d.language)))

    # #5, #6: a new direct parent
    for c, (was, now) in REPARENT.items():
        if (w(c), RDFS.subClassOf, URIRef(was)) not in old:
            raise RuntimeError(f"{c}: not a direct child of {was}")
        gone.add((w(c), RDFS.subClassOf, URIRef(was)))
        came.add((w(c), RDFS.subClassOf, URIRef(now)))
    if not any(isinstance(o, rdflib.BNode) for o in old.objects(w("WONT_0000043"), RDFS.subClassOf)):
        raise RuntimeError("WONT_0000043: its antiseptic drug role is missing")
    if (w("WONT_0000161"), IAO115, None) in old:
        raise RuntimeError("WONT_0000161 already has a definition")
    came.add((w("WONT_0000161"), IAO115, Literal(IMMUNOSUPPRESSION_DEF, lang="en")))

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

    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef) and str(s).startswith(W)}
    live = {s for s in classes if (s, OWL.deprecated, Literal(True)) not in g}
    defined = {s for s in live if (s, IAO115, None) in g}
    print(f"[review] {OLD.name}: {len(old):,} triples -> {len(g):,}; {len(gone)} gone, {len(came)} come")
    print(f"[review]   draft markers taken off: {len(accepted)}; left in WONT: {len(set(g.subjects(IAO119, None)))}")
    print(f"[review]   named parents added: {len(NAMED_PARENT)}; moved to {INTO}: {len(children)}; obsolete: {MERGED}")
    print(f"[review]   WONT classes {len(classes)}, of them not obsolete {len(live)}, with a definition {len(defined)}, "
          f"without {len(live - defined)}")
    print("[review]   without a definition: " + "; ".join(sorted(str(g.value(s, RDFS.label)) for s in live - defined)))

    # MILD: the modified date, as text
    text = MILD_OLD.read_text(encoding="utf-8")
    if text.count(MILD_MODIFIED_OLD) != 1:
        raise RuntimeError(f"{MILD_OLD.name}: the modified date found {text.count(MILD_MODIFIED_OLD)} times")
    new_text = text.replace(MILD_MODIFIED_OLD, MILD_MODIFIED_NEW)
    m_old = rdflib.Graph().parse(data=text, format="turtle")
    m_new = rdflib.Graph().parse(data=new_text, format="turtle")
    onto = URIRef("https://bioportal.bioontology.org/ontologies/MILD")
    mod = URIRef("http://purl.org/dc/terms/modified")
    _, m_gone, m_came = graph_diff(to_isomorphic(m_old), to_isomorphic(m_new))
    if set(m_gone) != {(onto, mod, Literal("2026-07-06", datatype=XSD.date))} or \
            set(m_came) != {(onto, mod, Literal("2026-10-31", datatype=XSD.date))}:
        raise RuntimeError(f"{MILD_OLD.name}: the difference is not the modified date alone")
    print(f"[review] {MILD_OLD.name}: dcterms:modified 2026-07-06 -> 2026-10-31, nothing else")

    if not write:
        print(f"[review] dry run; --write writes {NEW.name} and {MILD_NEW.name}")
        return 0
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError(f"{NEW.name}: the written file is not the graph meant")
    MILD_NEW.write_text(new_text, encoding="utf-8")
    if not isomorphic(rdflib.Graph().parse(MILD_NEW, format="turtle"), m_new):
        raise RuntimeError(f"{MILD_NEW.name}: the written file is not the graph meant")
    print(f"[review] written {NEW.relative_to(ROOT)} and {MILD_NEW} (both read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
