"""Three points from the thesis read-through, decided by the curator (2026-11-01).

The thesis session found three modelling points; the curator chose:

* "Grad 3 bis Subkutis": Third-degree burn wound reaches the subcutis. Its
  definition says so ("... through the full thickness of the skin into the
  subcutis"); it keeps reaching the dermis (the depth classes are not nested).
* "University of Texas": WONT_0000375, with its 16 grades 1A-4D, is the
  University of Texas wound classification (depth grade 0-3 x stage A-D), not
  "Wagner and Anderson" (Wagner has six grades, 0-5; Wagner-Armstrong 24 cells).
  The class, its grade class and the 16 grade individuals are renamed, IRIs
  kept; the grades become 0A-3D. No synonym keeps the old name: it named no
  existing scheme.
* "Veraltet ohne Ersatz": Clean wound according to IWII (WONT_0000527) is
  obsolete -- the IWII wound infection continuum has no clean stage; the clean
  wound is the CDC class. MILD's obsolete form without a reason (none of IAO's
  fits "not in the scheme it cites"), the comment says why. Its parent no
  longer lists "sterile" among the IWII qualities, in definition and axiom.

`ground_truth_final_2026-11-01.owl` is `..._2026-10-31i.owl` with this and
dcterms:modified 2026-11-01. The graph difference is checked to be exactly this.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-31i.owl", GT / "ground_truth_final_2026-11-01.owl"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
OBO = "http://purl.obolibrary.org/obo/"
SAID = "curator 2026-11-01, on the thesis read-through"
THIRD = ("WONT_0000484", "Third-degree burn wound",
         "A thermal wound in which the injury extends through the full thickness of the skin.",
         "A thermal wound in which the injury extends through the full thickness of the skin into the subcutis.",
         "WONT_120089")
UT = {"WONT_0000375": ("Wagner and Anderson wound classification", "University of Texas wound classification",
                       "A wound classification scale that grades a diabetic foot wound by combining a depth grade from "
                       "0 to 3 with a stage from A to D that records whether neither, infection, ischaemia or both are "
                       "present."),
      "WONT_0000376": ("Wagner and Anderson wound classification grade", "University of Texas wound classification grade",
                       "A wound classification grade that is a category of the University of Texas wound classification.")}
GRADES = {f"WONT_{120065 + 4 * (d - 1) + s}": (f"Wagner and Anderson grade {d}{'ABCD'[s]}",
                                                 f"University of Texas grade {d - 1}{'ABCD'[s]}")
          for d in range(1, 5) for s in range(4)}
IWII_CLEAN, IWII = "WONT_0000527", "WONT_0000481"
STERILE_ID = "WONT_0000486"   # the quality sterile, a WONT class
IWII_DEF_OLD = ("A wound whose microbial burden is assessed on the IWII wound infection continuum: it bears the "
                "quality sterile, contaminated, colonized or infected.")
IWII_DEF_NEW = ("A wound whose microbial burden is assessed on the IWII wound infection continuum: it bears the "
                "quality contaminated, colonized or infected.")
RETIRED_NOTE = ("Made obsolete without replacement (" + SAID + ": \"Veraltet ohne Ersatz\"): the IWII wound infection "
                "continuum has no clean or sterile stage; a clean wound is the CDC class, Clean wound according to CDC "
                "(WONT_0000068), which is not the same thing. No obsolescence reason is given, since none of IAO's "
                "says that a class is not in the scheme it cites.")


def main(argv) -> int:
    import rdflib
    from rdflib import OWL, RDF, RDFS, BNode, Literal, URIRef, DCTERMS, XSD
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    write = "--write" in argv
    if write and NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    IAO115 = URIRef(OBO + "IAO_0000115")
    w = lambda i: URIRef(W + i)
    STERILE = w(STERILE_ID)
    old = rdflib.Graph().parse(OLD, format="turtle")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    named_gone, named_came, bn_gone, bn_came = set(), set(), 0, 0

    def swap(a, b):
        if a not in old:
            raise RuntimeError(f"not in {OLD.name}: {a}")
        g.remove(a); g.add(b); named_gone.add(a); named_came.add(b)

    def closure(b):
        out, st = set(), [b]
        while st:
            n = st.pop()
            for t in old.triples((n, None, None)):
                out.add(t)
                if isinstance(t[2], BNode):
                    st.append(t[2])
        return out

    onto = next(old.subjects(RDF.type, OWL.Ontology))
    mod = [o for o in old.objects(onto, DCTERMS.modified)]
    if [str(o) for o in mod] != ["2026-10-31"]:
        raise RuntimeError(f"dcterms:modified is {mod}")
    swap((onto, DCTERMS.modified, mod[0]), (onto, DCTERMS.modified, Literal("2026-11-01", datatype=XSD.date)))

    i, label, was, now, depth = THIRD
    if str(old.value(w(i), RDFS.label)) != label:
        raise RuntimeError(f"{i} is not {label}")
    d = old.value(w(i), IAO115)
    if str(d) != was:
        raise RuntimeError(f"{i}: definition is {d!r}")
    swap((w(i), IAO115, d), (w(i), IAO115, Literal(now, lang=d.language)))
    g.add((w(i), RDFS.subClassOf, w(depth))); named_came.add((w(i), RDFS.subClassOf, w(depth)))

    for i, (was, now, text) in UT.items():
        lab = old.value(w(i), RDFS.label)
        if str(lab) != was:
            raise RuntimeError(f"{i}: labelled {lab!r}, expected {was!r}")
        swap((w(i), RDFS.label, lab), (w(i), RDFS.label, Literal(now, lang=lab.language)))
        d = old.value(w(i), IAO115)
        swap((w(i), IAO115, d), (w(i), IAO115, Literal(text, lang=d.language)))
    for i, (was, now) in GRADES.items():
        lab = old.value(w(i), RDFS.label)
        if str(lab) != was or (w(i), RDF.type, w("WONT_0000376")) not in old:
            raise RuntimeError(f"{i}: {lab!r}, expected {was!r} typed as the grade class")
        swap((w(i), RDFS.label, lab), (w(i), RDFS.label, Literal(now, lang=lab.language)))

    c = w(IWII_CLEAN)
    if str(old.value(c, RDFS.label)) != "Clean wound according to IWII" or list(old.subject_predicates(c)):
        raise RuntimeError(f"{IWII_CLEAN}: not the IWII clean wound, or something refers to it")
    lab = old.value(c, RDFS.label)
    for t in list(old.triples((c, None, None))):
        if t[1] == RDF.type:
            continue
        if isinstance(t[2], BNode):
            cl = closure(t[2]) | {t}
            for x in cl:
                g.remove(x)
            bn_gone += len(cl)
        else:
            g.remove(t); named_gone.add(t)
    for t in [(c, RDFS.label, Literal("obsolete " + str(lab), lang=lab.language)), (c, OWL.deprecated, Literal(True)),
              (c, RDFS.comment, Literal(RETIRED_NOTE, lang="en"))]:
        g.add(t); named_came.add(t)

    p = w(IWII)
    d = old.value(p, IAO115)
    if str(d) != IWII_DEF_OLD:
        raise RuntimeError(f"{IWII}: definition is {d!r}")
    swap((p, IAO115, d), (p, IAO115, Literal(IWII_DEF_NEW, lang=d.language)))
    eqs = list(old.objects(p, OWL.equivalentClass))
    if len(eqs) != 1:
        raise RuntimeError(f"{IWII}: {len(eqs)} equivalences")
    inter = list(old.items(old.value(eqs[0], OWL.intersectionOf)))
    restr = [m for m in inter if isinstance(m, BNode)]
    union = list(old.items(old.value(old.value(restr[0], OWL.someValuesFrom), OWL.unionOf)))
    if str(old.value(STERILE, RDFS.label)) != "sterile":
        raise RuntimeError(f"{STERILE} is not the quality sterile")
    cl = closure(eqs[0]) | {(p, OWL.equivalentClass, eqs[0])}
    for x in cl:
        g.remove(x)
    bn_gone += len(cl)
    has_quality = old.value(restr[0], OWL.onProperty)
    keep = [m for m in union if m != STERILE]
    if len(keep) != len(union) - 1:
        raise RuntimeError(f"{IWII}: the union {union} does not hold the sterile quality {STERILE} once")
    e, r, u = BNode(), BNode(), BNode()
    new = [(p, OWL.equivalentClass, e), (e, RDF.type, OWL.Class)]
    nodes = [BNode() for _ in range(2)]
    new += [(e, OWL.intersectionOf, nodes[0]), (nodes[0], RDF.first, w("WONT_0000380")), (nodes[0], RDF.rest, nodes[1]),
            (nodes[1], RDF.first, r), (nodes[1], RDF.rest, RDF.nil),
            (r, RDF.type, OWL.Restriction), (r, OWL.onProperty, has_quality), (r, OWL.someValuesFrom, u),
            (u, RDF.type, OWL.Class)]
    un = [BNode() for _ in keep]
    new.append((u, OWL.unionOf, un[0]))
    for k, (node, m) in enumerate(zip(un, keep)):
        new += [(node, RDF.first, m), (node, RDF.rest, un[k + 1] if k + 1 < len(un) else RDF.nil)]
    if inter[0] != w("WONT_0000380"):
        raise RuntimeError(f"{IWII}: the intersection does not start with Wound: {inter}")
    for t in new:
        g.add(t)
    bn_came += len(new)

    _, gone, came = graph_diff(to_isomorphic(old), to_isomorphic(g))
    gn = {t for t in gone if not any(isinstance(x, BNode) for x in t)}
    cn = {t for t in came if not any(isinstance(x, BNode) for x in t)}
    # The rebuilt IWII axiom shares its unchanged pieces (the tail of the union list, the Wound
    # conjunct) with the old one, so the comparison drops them on both sides alike: what is left
    # of the anonymous part must be the same number smaller on each side.
    shared = bn_gone - (len(set(gone)) - len(gn))
    if gn != named_gone or cn != named_came or shared < 0 or bn_came - (len(set(came)) - len(cn)) != shared:
        raise RuntimeError(f"the difference is not the one meant: named {len(gn)}/{len(named_gone)} gone, "
                           f"{len(cn)}/{len(named_came)} come; anonymous {len(set(gone)) - len(gn)}/{bn_gone} gone, "
                           f"{len(set(came)) - len(cn)}/{bn_came} come")
    stale = [(str(s)[len(W):], str(o)[:80]) for s, _, o in g if isinstance(o, Literal)
             and ("Wagner and Anderson" in str(o) or ("IWII" in str(o) and "sterile" in str(o)))
             and s != c]   # the retired class's own label and note say why it went
    if stale:
        raise RuntimeError(f"text still names the old scheme or IWII's sterile stage: {stale}")
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef) and str(s).startswith(W)}
    live = {s for s in classes if (s, OWL.deprecated, Literal(True)) not in g}
    defined = {s for s in live if (s, IAO115, None) in g}
    print(f"[review] {OLD.name}: {len(old):,} -> {len(g):,} triples; named {len(named_gone)} gone, {len(named_came)} "
          f"come; anonymous {bn_gone} gone, {bn_came} come")
    print(f"[review]   WONT classes {len(classes)}, not obsolete {len(live)}, defined {len(defined)}, "
          f"without {len(live - defined)}")
    if not write:
        print(f"[review] dry run; --write writes {NEW.name}")
        return 0
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError(f"{NEW.name}: the written file is not the graph meant")
    print(f"[review] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
