"""WONT's class names say no "causing" (2026-10-31).

The curator, on the thesis's pattern for the wound development classes: "hier
auch wieder causing … gefällt mir gar nicht"; offered options, he chose "Nur
umbenennen" and "Wound dehiscence with suture insufficiency" (relayed by the
thesis session, 2026-10-31). Only labels and definition texts change; IRIs and
axioms stay.

* Wound causing process (WONT_0000418) is Wound development subprocess; every
  Wound causing X process is X process in wound development.
* Wound dehiscence causally related to suture insufficiency (WONT_0000379) is
  Wound dehiscence with suture insufficiency; its definition says the sutures
  fail, not that the failure caused the process.
* WONT's own definitions that said "wound causing (X) process" name the class by
  its new name, or, where the wound development process that has it as part is
  already named, the process alone ("has as part a process of the course of a
  diabetic metabolic disorder"). The history note on WONT_0000384 keeps its
  words: it quotes an earlier label. Imported definitions are not touched.
* The term dict: every placement, pair and name that names one of the old
  labels moves to the new one (`apply_renames`, by the author, his words in
  the reason); the old label stays as a name pointing to the new one, so the
  abstracts' own wording ("Wound causing process") still reaches the class.

`ground_truth_final_2026-10-31.owl` is `..._2026-10-30d.owl` with these texts;
the graphs are compared and every changed triple is a label or a definition of
one of these classes. The term dict is backed up before it is saved; the
placements are compared class by class (by IRI) before and after.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-30d.owl", GT / "ground_truth_final_2026-10-31.owl"
W, OBO = "https://bioportal.bioontology.org/ontologies/WONT/", "http://purl.obolibrary.org/obo/"
WORDS = ("curator, 2026-10-31, relayed by the thesis session: 'hier auch wieder causing … gefällt mir gar "
         "nicht'; chose 'Nur umbenennen' and 'Wound dehiscence with suture insufficiency'")

LABELS = {   # WONT id -> (old label, new label)
    "0000418": ("Wound causing process", "Wound development subprocess"),
    "0000004": ("Wound causing acidity impact process", "Acidity impact process in wound development"),
    "0000537": ("Wound causing angiopathic disease process", "Angiopathic disease process in wound development"),
    "0000538": ("Wound causing autoimmune disease process", "Autoimmune disease process in wound development"),
    "0000539": ("Wound causing diabetes mellitus disease process",
                "Diabetes mellitus disease process in wound development"),
    "0000587": ("Wound causing foreign body process", "Foreign body process in wound development"),
    "0000140": ("Wound causing heat impact process", "Heat impact process in wound development"),
    "0000515": ("Wound causing malignant process", "Malignant process in wound development"),
    "0000560": ("Wound causing neuropathic disease process", "Neuropathic disease process in wound development"),
    "0000543": ("Wound causing peripheral arterial occlusive disease process",
                "Peripheral arterial occlusive disease process in wound development"),
    "0000245": ("Wound causing pressure impact process", "Pressure impact process in wound development"),
    "0000516": ("Wound causing trauma process", "Trauma process in wound development"),
    "0000541": ("Wound causing venous insufficiency disease process",
                "Venous insufficiency disease process in wound development"),
    "0000379": ("Wound dehiscence causally related to suture insufficiency",
                "Wound dehiscence with suture insufficiency"),
}
_SUB = "that is a wound causing process.", "that is a wound development subprocess."
_COURSE = "has as part a wound causing process of the course of", "has as part a process of the course of"
DEFINITIONS = {   # WONT id -> (old text, new text), each matched whole
    **{k: (f"{a} {_SUB[0]}", f"{a} {_SUB[1]}") for k, a in {
        "0000537": "An angiopathic disease process", "0000538": "An autoimmune disease process",
        "0000539": "A diabetes mellitus disease process", "0000515": "A malignant process",
        "0000560": "A neuropathic disease process", "0000543": "A peripheral arterial occlusive disease process",
        "0000516": "A trauma process", "0000541": "A venous insufficiency disease process"}.items()},
    "0000587": ("A wound causing process in which a foreign body participates.",
                "A wound development subprocess in which a foreign body participates."),
    **{k: (f"A wound that is the output of a wound development process that {_COURSE[0]} {d}. No claim is made "
           f"that the disorder caused the wound.",
           f"A wound that is the output of a wound development process that {_COURSE[1]} {d}. No claim is made "
           f"that the disorder caused the wound.") for k, d in {
        "0000088": "a diabetic metabolic disorder", "0000033": "an autoimmune tissue disorder",
        "0000015": "an angiopathy", "0000384": "a venous insufficiency disorder",
        "0000510": "a peripheral arterial occlusive disease"}.items()},
    "0000534": ("A wound that is the output of a wound development process that has as part a wound causing "
                "pressure impact process.",
                "A wound that is the output of a wound development process that has as part a pressure impact "
                "process."),
    "0000554": ("A wound that is the output of a wound development process that has as part a wound causing "
                "foreign body process.",
                "A wound that is the output of a wound development process that has as part a foreign body "
                "process."),
    "0000044": ("A traumatic wound that is the output of a wound causing trauma process in which the teeth of a "
                "human or an animal penetrate, tear or crush the tissue.",
                "A traumatic wound that is the output of a trauma process in wound development in which the "
                "teeth of a human or an animal penetrate, tear or crush the tissue."),
    "0000310": ("A traumatic wound that is the output of a wound causing heat impact process, in which tissue is "
                "damaged by the action of excessive heat.",
                "A traumatic wound that is the output of a heat impact process in wound development, in which "
                "tissue is damaged by the action of excessive heat."),
    "0000339": ("A wound that is the output of a wound causing trauma process.",
                "A wound that is the output of a trauma process in wound development."),
    "0000426": ("A traumatic wound that is the output of a wound causing trauma process which also has as output "
                "a fracture of a bone in the same body region.",
                "A traumatic wound that is the output of a trauma process in wound development which also has "
                "as output a fracture of a bone in the same body region."),
    "0000379": ("A wound dehiscence that is the output of a wound dehiscence process caused by the failure of the "
                "sutures holding the wound edges together to keep them approximated.",
                "A wound dehiscence that is the output of a wound dehiscence process in which the sutures "
                "holding the wound edges together fail to keep them approximated."),
}
KEPT_NOTE = "WONT_0000384"   # its history note quotes the earlier label 'Wound causally related to ...'


def wont(old):
    import rdflib
    from rdflib import Literal, RDFS, URIRef
    iao = URIRef(OBO + "IAO_0000115")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    for k, (a, b) in LABELS.items():
        s = URIRef(W + "WONT_" + k)
        have = [l for l in old.objects(s, RDFS.label)]
        if [str(l) for l in have] != [a]:
            raise RuntimeError(f"WONT_{k}: label {[str(l) for l in have]}, expected [{a!r}]")
        g.remove((s, RDFS.label, have[0]))
        g.add((s, RDFS.label, Literal(b, lang=have[0].language)))
    for k, (a, b) in DEFINITIONS.items():
        s = URIRef(W + "WONT_" + k)
        have = [d for d in old.objects(s, iao)]
        if [str(d) for d in have] != [a]:
            raise RuntimeError(f"WONT_{k}: definition {[str(d)[:80] for d in have]}, expected {a[:80]!r}")
        g.remove((s, iao, have[0]))
        g.add((s, iao, Literal(b, lang=have[0].language)))
    return g


def check(old, g) -> list[str]:
    """Every changed triple is a label or definition of a class named here; no
    WONT text says causing or causally related any more, but the one history
    note. (Degree of wound pain stays `causally influenced by` a wound: an
    axiom, not a name, and not part of this decision.)"""
    from rdflib import Literal, RDFS, URIRef
    from rdflib.compare import graph_diff, to_isomorphic
    _, gone, came = graph_diff(to_isomorphic(old), to_isomorphic(g))
    allowed = {URIRef(W + "WONT_" + k) for k in {**LABELS, **DEFINITIONS}}
    preds = {RDFS.label, URIRef(OBO + "IAO_0000115")}
    off = [t for t in list(gone) + list(came) if t[0] not in allowed or t[1] not in preds]
    if off:
        raise RuntimeError(f"{len(off)} changed triple(s) outside the labels and definitions: {off[:3]}")
    if (len(gone), len(came)) != (len(LABELS) + len(DEFINITIONS),) * 2:
        raise RuntimeError(f"{len(gone)} triples gone, {len(came)} come; expected "
                           f"{len(LABELS) + len(DEFINITIONS)} each")
    left = [f"{str(s).rsplit('/', 1)[-1]}: {str(o)[:120]}" for s, p, o in g
            if str(s).startswith(W) and isinstance(o, Literal)
            and any(w in str(o).lower() for w in ("causing", "causally related"))]
    if [x.split(":")[0] for x in left] != [KEPT_NOTE]:
        raise RuntimeError(f"WONT texts still saying causing or causally: {left}")
    return left


def placements(gt) -> set:
    return {(t, gt.placement_iri(t, c)) for t, c in gt.placements()}


def main(argv) -> int:
    import rdflib
    old = rdflib.Graph().parse(OLD, format="turtle")
    g = wont(old)
    left = check(old, g)
    print(f"[causing] {OLD.name}: {len(old):,} triples -> {len(g):,}; {len(LABELS)} labels and "
          f"{len(DEFINITIONS)} definitions rewritten; kept (history): {left}")
    for k, (a, b) in LABELS.items():
        print(f"[causing]     WONT_{k}: {a!r} -> {b!r}")
    from wound_ontology.orchestrator import Orchestrator
    gt = Orchestrator().term_mapper._term_mapping
    renames = {a: b for a, b in LABELS.values()}
    taken = sorted(b for b in renames.values() if b in gt.records)
    if taken:
        raise RuntimeError(f"new label(s) already a record of the term dict: {taken}")
    before, cats, links = placements(gt), gt.categories(), gt.term_links()
    # `apply_renames` saves the term dict itself: the first dry run (2026-10-31
    # 11:16) wrote one. Held back here, it is saved after the checks, with --write.
    gt.save = lambda: None
    rep = gt.apply_renames(renames, by="author", why=f"WONT relabelled, IRI kept ({WORDS})")
    del gt.save
    after = placements(gt)
    print(f"[causing] term dict: {rep}")
    if {(renames.get(t, t), i) for t, i in before} != after:
        raise RuntimeError(f"placements changed class: {sorted(before ^ after)[:5]}")
    if {renames.get(t, t): c["verdict"] for t, c in cats.items()} != \
            {t: c["verdict"] for t, c in gt.categories().items()}:
        raise RuntimeError("a category changed with the renames")
    if sorted((renames.get(t, t), renames.get(p, p)) for t, p in links) != gt.term_links():
        raise RuntimeError("a link between two terms changed with the renames")
    print(f"[causing] placements: {len(after):,}, every one on the same class (IRI) as before")
    if "--write" not in argv:
        print(f"[causing] dry run; --write writes {NEW.name} and the term dict")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    from rdflib.compare import isomorphic
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError("the written file is not the graph meant")
    print(f"[causing] written {NEW.relative_to(ROOT)} (read back, identical)")
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_drop_causing_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[causing] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
