"""Disease names are diagnoses: 22 WONT classes move from material disease entity to disease diagnostic result (2026-10-31).

The curator, in this session: "wir müssen alle krankheitsnamen unter diagnose
schieben. die vaskulitis ist die diagnose, nicht die krankheit." -- MILD's own
rule (editor note on MILD_120020): a disease name may stand for a material
disease entity only when it names one pathological thing in the patient, not a
diagnostic category. His four choices: only the 22 disease names move (what one
can point at -- wounds, necrosis, hematoma, abscess, seroma, lymphocele,
fistulas, blisters, hypergranulation, dehiscence, neoplasm, malignancy -- stays
material); labels stay; the two disease courses get a material participant each,
a new class the diagnosis is about. The drafts: "alles ok, schreib die neue datei".

`ground_truth_final_2026-10-31h.owl` is `..._2026-10-31g.owl` with:

* 20 classes reparented from MILD_120020 to MILD_120024, Mucous membrane
  pemphigoid to Autoimmune tissue disorder; Microangiopathy and Peripheral
  arterial occlusive disease follow Angiopathy;
* their 22 definitions: 17 keep the accepted text after a new start ("A disease
  diagnostic result that is about a material disease entity ..."), five are new;
* WONT_120085 Narrowed limb artery and WONT_120086 Insufficient limb vein,
  material disease entities, defined by the texts Peripheral arterial occlusive
  disease and Venous insufficiency disorder had;
* Mucous membrane pemphigoid is about some Mucosal blister (was: has part some
  (Autoimmune tissue disorder and Mucosal blister)); MRSA infection is about some
  (material disease entity and has part some Staphylococcus aureus) (was: has part
  some Staphylococcus aureus); Venous insufficiency disorder and Peripheral
  arterial occlusive disease are about the new classes, which replace them as the
  participants of their disease processes;
* five comments that called the class the material disease entity itself, and
  the pemphigoid's editor note on its old axiom, rewritten; a dated note on all 22.

The graph difference is checked to be exactly this.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-31g.owl", GT / "ground_truth_final_2026-10-31h.owl"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
MILD_NS = "https://bioportal.bioontology.org/ontologies/MILD/"
OBO = "http://purl.obolibrary.org/obo/"
MDE, DDR = MILD_NS + "MILD_120020", MILD_NS + "MILD_120024"
START = "A disease diagnostic result that is about a"

# id -> (label, new named parent or None when the parent stays, new definition or None for the rule-based start)
MOVED = {
    "WONT_0000013": ("ANCA-associated Vasculitis", DDR, None),
    "WONT_0000466": ("Angiopathy", DDR, None),
    "WONT_0000201": ("Microangiopathy", None,
                     "An angiopathy that is about an abnormal structure of the wall or lumen of small blood vessels, "
                     "namely arterioles, capillaries or venules."),
    "WONT_0000229": ("Peripheral arterial occlusive disease", None, "An angiopathy that is about a narrowed limb artery."),
    "WONT_0000469": ("Autoimmune tissue disorder", DDR, None),
    "WONT_0000049": ("Bullosis diabeticorum", DDR, None),
    "WONT_0000050": ("Bullous impetigo", DDR, None),
    "WONT_0000467": ("Diabetic metabolic disorder", DDR, None),
    "WONT_0000443": ("Erysipelas", DDR,
                     "A disease diagnostic result that is about a superficial bacterial skin infection, characteristically "
                     "caused by Streptococcus pyogenes, involving the upper dermis and superficial lymphatics."),
    "WONT_0000111": ("Fixed drug exanthema", DDR, None),
    "WONT_0000115": ("Fournier's gangrene", DDR, None),
    "WONT_0003586": ("Immunodeficiency disorder", DDR, None),
    "WONT_0000173": ("Linear IgA dermatosis", DDR, None),
    "WONT_0000174": ("Livedovasculopathy", DDR, None),
    "WONT_0000447": ("MRSA infection", DDR, None),
    "WONT_0000446": ("Mucous membrane pemphigoid", W + "WONT_0000469",
                     "An autoimmune tissue disorder that is about one or more mucosal blisters."),
    "WONT_0000559": ("Osteomyelitis", DDR, None),
    "WONT_0000233": ("Phlegmon", DDR, None),
    "WONT_0000558": ("Sepsis", DDR, None),
    "WONT_0000550": ("Surgical site infection", DDR, None),
    "WONT_0000468": ("Venous insufficiency disorder", DDR, "A disease diagnostic result that is about an insufficient limb vein."),
    "WONT_0000408": ("Wound healing disorder", DDR, None),
}
# new id -> (label, definition, the diagnosis about it, the disease process it takes part in, the participant it replaces)
NEW_CLASSES = {
    "WONT_120085": ("Narrowed limb artery",
                    "A material disease entity consisting in one or more arteries supplying an extremity whose lumen is "
                    "narrowed or occluded, such that perfusion of the tissue of the affected limb is reduced.",
                    "WONT_0000229", "WONT_0000542"),
    "WONT_120086": ("Insufficient limb vein",
                    "A material disease entity consisting in one or more veins of a limb whose valves or walls are "
                    "abnormally structured, such that venous return from that limb against gravity is impaired.",
                    "WONT_0000468", "WONT_0000540"),
}
# id -> (text that must occur exactly once in its comment, what it becomes)
COMMENT_FIX = {
    "WONT_0000469": ("whereas this class is the material disease entity itself.",
                     "whereas this class is a diagnostic result, an information content entity."),
    "WONT_0000467": ("whereas this class is the material disease entity itself.",
                     "whereas this class is a diagnostic result, an information content entity."),
    "WONT_0000468": ("whereas this class is the material disease entity itself.",
                     "whereas this class is a diagnostic result, an information content entity."),
    "WONT_0000446": ("whereas this class is the material disease entity itself;",
                     "whereas this class is a diagnostic result, an information content entity;"),
    "WONT_0000447": ("WONT-owned material disease counterpart of HP_0032326",
                     "WONT-owned diagnostic counterpart of HP_0032326"),
}
PEMPHIGOID_NOTE_START = "Reparented from ns1:DOID_0080841 pemphigoid to mild:MILD_120020 material disease entity."
PEMPHIGOID_NOTE = ("This class had no BFO anchor while its only parent was ns1:DOID_0080841 pemphigoid. It is now an "
                   "autoimmune tissue disorder, a disease diagnostic result, and is about the blisters in the mucosa it "
                   "groups; no causal claim is made between the autoimmunity and the blistering (MILD model commitment 4).")
MOVE_NOTE = ("Moved from material disease entity to disease diagnostic result (curator, 2026-10-31): the name denotes a "
             "diagnostic classification, not one material disease entity; the material disease entity is what the "
             "diagnosis is about.")
# Present-tense claims the move makes false; none may be left on a moved class.
STALE = ("material disease entity itself", "material disease counterpart", "that is now what the axiom says")


def main(argv) -> int:
    import rdflib
    from rdflib import OWL, RDF, RDFS, BNode, Literal, URIRef
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    write = "--write" in argv
    if write and NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    IAO115, IAO116, IAO118 = (URIRef(OBO + i) for i in ("IAO_0000115", "IAO_0000116", "IAO_0000118"))
    IS_ABOUT, HAS_PART, HAS_PARTICIPANT = URIRef(OBO + "IAO_0000136"), URIRef(OBO + "BFO_0000051"), URIRef(OBO + "RO_0000057")
    w = lambda i: URIRef(W + i)

    old = rdflib.Graph().parse(OLD, format="turtle")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    named_gone, named_came = set(), set()
    bnode_gone, bnode_came = 0, 0

    def closure(b):
        """Every triple of an anonymous class expression, lists included."""
        out, stack = set(), [b]
        while stack:
            n = stack.pop()
            for t in old.triples((n, None, None)):
                out.add(t)
                if isinstance(t[2], BNode):
                    stack.append(t[2])
        return out

    def drop_restriction(s, prop):
        nonlocal bnode_gone
        rs = [o for o in old.objects(s, RDFS.subClassOf) if isinstance(o, BNode) and old.value(o, OWL.onProperty) == prop]
        if len(rs) != 1:
            raise RuntimeError(f"{s}: {len(rs)} restrictions on {prop}, expected one")
        cl = closure(rs[0]) | {(s, RDFS.subClassOf, rs[0])}
        for t in cl:
            g.remove(t)
        bnode_gone += len(cl)
        return rs[0]

    def some(prop, filler, new):
        """The anonymous class (prop some filler), its triples appended to `new`; filler a URIRef,
        a (prop, filler) pair for a nested restriction, or a list of those (an intersection)."""
        r = BNode()
        new += [(r, RDF.type, OWL.Restriction), (r, OWL.onProperty, prop)]
        new.append((r, OWL.someValuesFrom, expr(filler, new)))
        return r

    def expr(x, new):
        if isinstance(x, URIRef):
            return x
        if isinstance(x, tuple):
            return some(x[0], x[1], new)
        c = BNode()
        items = [BNode() for _ in x]
        new += [(c, RDF.type, OWL.Class), (c, OWL.intersectionOf, items[0])]
        for k, (node, member) in enumerate(zip(items, x)):
            new += [(node, RDF.first, expr(member, new)), (node, RDF.rest, items[k + 1] if k + 1 < len(items) else RDF.nil)]
        return c

    def add_some(s, prop, filler):
        """s subClassOf (prop some filler)."""
        nonlocal bnode_came
        new = []
        new.append((s, RDFS.subClassOf, some(prop, filler, new)))
        for t in new:
            g.add(t)
        bnode_came += len(new)

    def swap(t_old, t_new):
        if t_old not in old:
            raise RuntimeError(f"not in {OLD.name}: {t_old}")
        g.remove(t_old); g.add(t_new)
        named_gone.add(t_old); named_came.add(t_new)

    # -- the 22 moved classes: parent, definition, dated note
    for i, (label, parent, text) in MOVED.items():
        s = w(i)
        if str(old.value(s, RDFS.label)) != label:
            raise RuntimeError(f"{i}: labelled {old.value(s, RDFS.label)!r}, expected {label!r}")
        named = {o for o in old.objects(s, RDFS.subClassOf) if isinstance(o, URIRef)}
        expected = {URIRef(MDE)} if parent else {w("WONT_0000466")}
        if named != expected:
            raise RuntimeError(f"{i} {label}: named parents {sorted(map(str, named))}, expected {sorted(map(str, expected))}")
        if parent:
            swap((s, RDFS.subClassOf, URIRef(MDE)), (s, RDFS.subClassOf, URIRef(parent)))
        defs = list(old.objects(s, IAO115))
        if len(defs) != 1:
            raise RuntimeError(f"{i} {label}: {len(defs)} definitions")
        d = defs[0]
        if text is None:
            if not str(d).startswith("A material disease entity "):
                raise RuntimeError(f"{i} {label}: definition does not start 'A material disease entity': {d!r}")
            text = START + str(d)[1:]
        swap((s, IAO115, d), (s, IAO115, Literal(text, lang=d.language)))
        g.add((s, IAO116, Literal(MOVE_NOTE, lang="en"))); named_came.add((s, IAO116, Literal(MOVE_NOTE, lang="en")))

    # -- the two new material classes, and the diagnoses and disease processes that point at them
    for i, (label, text, diagnosis, process) in NEW_CLASSES.items():
        s = w(i)
        if (s, None, None) in old or (None, None, s) in old:
            raise RuntimeError(f"{i} is already in WONT")
        if any(str(o).lower() == label.lower() for p in (RDFS.label, IAO118) for o in old.objects(None, p)):
            raise RuntimeError(f"another WONT class already answers to {label!r}")
        for t in [(s, RDF.type, OWL.Class), (s, RDFS.label, Literal(label, lang="en")),
                  (s, RDFS.subClassOf, URIRef(MDE)), (s, IAO115, Literal(text, lang="en"))]:
            g.add(t); named_came.add(t)
        r = drop_restriction(w(process), HAS_PARTICIPANT)
        if old.value(r, OWL.someValuesFrom) != w(diagnosis):
            raise RuntimeError(f"{process}: participant is {old.value(r, OWL.someValuesFrom)}, expected {diagnosis}")
        add_some(w(process), HAS_PARTICIPANT, s)
        add_some(w(diagnosis), IS_ABOUT, s)

    # -- Mucous membrane pemphigoid: is about its blisters, no longer has them as parts
    r = drop_restriction(w("WONT_0000446"), HAS_PART)
    members = set(old.items(old.value(old.value(r, OWL.someValuesFrom), OWL.intersectionOf)))
    if members != {w("WONT_0000469"), w("WONT_0000473")}:
        raise RuntimeError(f"pemphigoid's has-part filler is {members}")
    add_some(w("WONT_0000446"), IS_ABOUT, w("WONT_0000473"))
    # -- MRSA infection: the bacteria are part of the tissue the diagnosis is about
    r = drop_restriction(w("WONT_0000447"), HAS_PART)
    aureus = old.value(r, OWL.someValuesFrom)
    if aureus != URIRef(OBO + "NCBITaxon_1280"):
        raise RuntimeError(f"MRSA infection's has-part filler is {aureus}, not NCBITaxon_1280 Staphylococcus aureus")
    add_some(w("WONT_0000447"), IS_ABOUT, [URIRef(MDE), (HAS_PART, aureus)])

    # -- comments and the pemphigoid's note
    for i, (was, now) in COMMENT_FIX.items():
        cs = [c for c in old.objects(w(i), RDFS.comment) if was in str(c)]
        if len(cs) != 1 or str(cs[0]).count(was) != 1:
            raise RuntimeError(f"{i}: {len(cs)} comments contain {was!r}")
        swap((w(i), RDFS.comment, cs[0]), (w(i), RDFS.comment, Literal(str(cs[0]).replace(was, now), lang=cs[0].language)))
    ns_ = [n for n in old.objects(w("WONT_0000446"), IAO116) if str(n).startswith(PEMPHIGOID_NOTE_START)]
    if len(ns_) != 1:
        raise RuntimeError(f"pemphigoid: {len(ns_)} notes start {PEMPHIGOID_NOTE_START!r}")
    swap((w("WONT_0000446"), IAO116, ns_[0]), (w("WONT_0000446"), IAO116, Literal(PEMPHIGOID_NOTE, lang=ns_[0].language or "en")))

    # -- the difference must be exactly this
    _, really_gone, really_came = graph_diff(to_isomorphic(old), to_isomorphic(g))
    rg_named = {t for t in really_gone if not any(isinstance(x, BNode) for x in t)}
    rc_named = {t for t in really_came if not any(isinstance(x, BNode) for x in t)}
    rg_b, rc_b = len(set(really_gone)) - len(rg_named), len(set(really_came)) - len(rc_named)
    if rg_named != named_gone or rc_named != named_came or rg_b != bnode_gone or rc_b != bnode_came:
        raise RuntimeError(f"{OLD.name}: the difference is not the one meant: named {len(rg_named)}/{len(named_gone)} gone, "
                           f"{len(rc_named)}/{len(named_came)} come; anonymous {rg_b}/{bnode_gone} gone, {rc_b}/{bnode_came} come")

    stale = [(str(s)[len(W):], str(o)[:90]) for s in map(w, MOVED) for p in (RDFS.comment, IAO116)
             for o in g.objects(s, p) if any(x in str(o).lower() for x in STALE)]
    if stale:
        raise RuntimeError(f"a moved class still says it is material: {stale}")
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef) and str(s).startswith(W)}
    live = {s for s in classes if (s, OWL.deprecated, Literal(True)) not in g}
    defined = {s for s in live if (s, IAO115, None) in g}
    print(f"[dx] {OLD.name}: {len(old):,} triples -> {len(g):,}; named {len(named_gone)} gone, {len(named_came)} come; "
          f"anonymous {bnode_gone} gone, {bnode_came} come")
    print(f"[dx]   moved to diagnosis: {len(MOVED)}; new material classes: {', '.join(NEW_CLASSES)}; comments fixed: {len(COMMENT_FIX)}")
    print(f"[dx]   WONT classes {len(classes)}, of them not obsolete {len(live)}, with a definition {len(defined)}, without {len(live - defined)}")

    if not write:
        print(f"[dx] dry run; --write writes {NEW.name}")
        return 0
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError(f"{NEW.name}: the written file is not the graph meant")
    print(f"[dx] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
