"""One class, material disease entity, with pathological disorder as its exact synonym (2026-10-30).

The curator, reviewing the thesis: "da disorder und material disease entity
synonym sind, würde ich nur eines verwenden. daher lieber material disease
entity"; offered one class with an exact synonym, he chose "Eine Klasse +
Synonym" (in the thesis session, and asked again here, the same). So:

* MILD (`mild_2026-10-30c.ttl`, from `mild_2026-10-30b.ttl`): MILD_120020
  material disease entity is the one class, `hasExactSynonym` "pathological
  disorder", equivalent to material entity and `has quality` some
  pathological (pathological disorder's axiom), subclass of material entity,
  `part of` some Homo sapiens and `has part` some material disease entity,
  disjoint from disease predisposition, disease diagnostic result and disease
  stage classification result; one definition from the two; pathological
  disorder's comments come along. MILD_120022 is obsolete as the OBO
  practice has it: deprecated, labelled "obsolete pathological disorder",
  replaced by MILD_120020, merged, no logical axiom. Every other use of
  MILD_120022 names MILD_120020 (`has input` some (pathological disorder and
  `part of` some material disease entity) becomes `has input` some material
  disease entity), and the definitions that name it say material disease
  entity. Written through ROBOT, the writer of the curator's editor.
* WONT (`ground_truth_final_2026-10-30.owl`, from `..._2026-10-29.owl`):
  every MILD_120022 is MILD_120020; a definition whose genus or text names a
  pathological disorder names a material disease entity ("a material disease
  entity that is the output of a wound development process"); the history
  note "Reparented ... to MILD_120022 pathological disorder" keeps its words
  and says where the class went.
* TermMappingAndGate: every placement under pathological disorder that stands
  moves to material disease entity -- the author's `no` on the old parent,
  his `yes` on the new one, naming who placed it.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

DISEASE = ROOT.parent / "Disease ontologies"
MILD_OLD, MILD_NEW = DISEASE / "mild_2026-10-30b.ttl", DISEASE / "mild_2026-10-30c.ttl"
GT_DIR = ROOT / "data" / "ground truth"
WONT_OLD, WONT_NEW = GT_DIR / "ground_truth_final_2026-10-29.owl", GT_DIR / "ground_truth_final_2026-10-30.owl"
ROBOT = ["java", "-Xmx6g", "-jar", "/usr/local/bin/robot.jar"]
M = "https://bioportal.bioontology.org/ontologies/MILD/"
OBO = "http://purl.obolibrary.org/obo/"
OIO = "http://www.geneontology.org/formats/oboInOwl#"
MDE, PD = M + "MILD_120020", M + "MILD_120022"
WORDS = ("curator 2026-10-30, reviewing the thesis: \"da disorder und material disease entity synonym sind, "
         "würde ich nur eines verwenden. daher lieber material disease entity\"; chosen: \"Eine Klasse + Synonym\"")
DEFINITION = (
    "A material entity, part of a human being, that is an abnormal presence or organization of material "
    "components -- including the limiting case where the abnormal organization consists in a normally-present "
    "component being absent -- and so has the quality pathological. Which material disease entities compose one "
    "disease is fixed by the diagnostic classification assigned to them, not by an intrinsic unity criterion. "
    "Identity is grounded in the continuity of the disorder lineage, not in momentary material composition (cf. a "
    "river persisting through complete material replacement).").replace(" -- ", " — ")
OWN_TEXT = {   # definitions that change beyond the name
    "MILD_120021": "A process that has as output a material disease entity.",
    "MILD_120086": "A planned process that realizes a treatment plan and that has as input a material disease entity.",
}
HISTORY = "MILD_120022 pathological disorder"


def swap(text: str) -> str:
    """`pathological disorder` read as material disease entity, articles and plurals kept."""
    if text.startswith("Reparented") and HISTORY in text:   # a note of what was done: its words stay
        return text.replace(HISTORY, HISTORY + " (since 2026-10-30 merged into MILD_120020 material disease "
                                               "entity, whose exact synonym it is)")
    for a, b in ((HISTORY, "MILD_120020 material disease entity"),
                 ("material pathological disorders", "material disease entities"),
                 ("material pathological disorder", "material disease entity"),
                 ("pathological disorders", "material disease entities"),
                 ("A pathological disorder", "A material disease entity"),
                 ("pathological disorder", "material disease entity")):
        text = text.replace(a, b)
    return text


def mild(old):
    import rdflib
    from rdflib import OWL, RDF, RDFS, BNode, Literal, URIRef
    from rdflib.namespace import XSD
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    g.bind("oboInOwl", OIO)
    for t in old:
        g.add(t)
    mde, pd = URIRef(MDE), URIRef(PD)
    iao115, desc = URIRef(OBO + "IAO_0000115"), URIRef("http://purl.org/dc/elements/1.1/description")
    lit = lambda s: Literal(s, lang="en")  # noqa: E731
    pd_eq = [o for o in g.objects(pd, OWL.equivalentClass) if isinstance(o, BNode)]
    pd_comments = list(g.objects(pd, RDFS.comment))
    pd_desc = list(g.objects(pd, desc))
    pd_disjoint = [o for o in g.objects(pd, OWL.disjointWith)]
    if len(pd_eq) != 1:
        raise RuntimeError(f"pathological disorder has {len(pd_eq)} anonymous equivalent class(es), expected 1")
    # 1. pathological disorder leaves the logic: its own triples go, the blank nodes they own with them
    def drop_tree(n):
        for p_, o_ in list(g.predicate_objects(n)):
            g.remove((n, p_, o_))
            if isinstance(o_, BNode) and not any(True for _ in g.subjects(None, o_)):
                drop_tree(o_)
    eq_tree = pd_eq[0]
    g.remove((pd, OWL.equivalentClass, eq_tree))
    drop_tree(pd)
    g.add((pd, RDF.type, OWL.Class))
    g.add((pd, OWL.deprecated, Literal(True, datatype=XSD.boolean)))
    g.add((pd, RDFS.label, lit("obsolete pathological disorder")))
    g.add((pd, URIRef(OBO + "IAO_0100001"), mde))
    g.add((pd, URIRef(OBO + "IAO_0000231"), URIRef(OBO + "IAO_0000227")))
    g.add((pd, RDFS.comment, lit("Merged into MILD_120020 material disease entity, of which 'pathological "
                                 "disorder' is an exact synonym (" + WORDS + ").")))
    for p_ in ("IAO_0100001", "IAO_0000231"):
        g.add((URIRef(OBO + p_), RDF.type, OWL.AnnotationProperty))
    g.add((URIRef(OIO + "hasExactSynonym"), RDF.type, OWL.AnnotationProperty))
    # 2. material disease entity: the one class
    g.remove((mde, OWL.equivalentClass, pd))
    g.add((mde, OWL.equivalentClass, eq_tree))          # material entity and has quality some pathological
    for d in pd_disjoint:
        g.add((mde, OWL.disjointWith, d))
    g.add((mde, URIRef(OIO + "hasExactSynonym"), lit("pathological disorder")))
    for p_ in (iao115, desc):
        for o_ in list(g.objects(mde, p_)):
            g.remove((mde, p_, o_))
        g.add((mde, p_, lit(DEFINITION)))
    for c in pd_comments:
        g.add((mde, RDFS.comment, lit(swap(str(c)))))
    rationale = URIRef(OBO + "IAO_0000116")
    old_via = "via MILD_120022 pathological disorder under OGMS_0000045 disorder"
    hits = [o_ for o_ in g.objects(mde, rationale) if old_via in str(o_)]
    if len(hits) != 1:
        raise RuntimeError(f"the design rationale of material disease entity: {len(hits)} text(s) with {old_via!r}")
    g.remove((mde, rationale, hits[0]))
    g.add((mde, rationale, lit(str(hits[0]).replace(old_via, (
        "via the pathological quality every material disease entity has (pathological disorder, its exact "
        "synonym, was the class MILD_120022 until 2026-10-30)")))))
    for d in pd_desc:
        g.add((mde, RDFS.comment, lit(str(d))))
    # 3. every other use of MILD_120022 names MILD_120020
    for s_, p_, o_ in list(g.triples((None, None, pd))):
        if p_ in (IAO_REPLACED := URIRef(OBO + "IAO_0100001"),):
            continue
        g.remove((s_, p_, o_)); g.add((s_, p_, mde))
    # has input some (MDE and part of some MDE) -> has input some MDE
    simplified = 0
    for b, in g.query("""SELECT ?b WHERE { ?b <http://www.w3.org/2002/07/owl#someValuesFrom> ?x .
                                          ?x <http://www.w3.org/2002/07/owl#intersectionOf> ?l .
                                          ?l <http://www.w3.org/1999/02/22-rdf-syntax-ns#first> <%s> . }""" % MDE):
        x = g.value(b, OWL.someValuesFrom)
        members = list(rdflib.collection.Collection(g, g.value(x, OWL.intersectionOf)))
        rest = [m for m in members if m != mde]
        if len(rest) == 1 and (rest[0], OWL.someValuesFrom, mde) in g \
                and (rest[0], OWL.onProperty, URIRef(OBO + "BFO_0000050")) in g:
            g.remove((b, OWL.someValuesFrom, x)); g.add((b, OWL.someValuesFrom, mde))
            rdflib.collection.Collection(g, g.value(x, OWL.intersectionOf)).clear()
            drop_tree(x)
            drop_tree(rest[0])               # the `part of` restriction, now nobody's member
            simplified += 1
    if simplified != 1:
        raise RuntimeError(f"{simplified} `material disease entity and part of some material disease entity` "
                           f"simplified, expected 1 (the treatment process)")
    # the ontology's own pointer to the class (MODEL COMMITMENT 2 of 4); fixed
    # in the written file the same evening, found by the thesis session
    for s_, p_, o_ in list(g.triples((None, RDFS.comment, None))):
        if str(o_).endswith("See MILD_120022."):
            g.remove((s_, p_, o_)); g.add((s_, p_, Literal(str(o_)[:-len("MILD_120022.")] + "MILD_120020.", lang=o_.language)))
    # 4. definitions that name it
    changed = []
    for s_, o_ in list(g.subject_objects(iao115)) + list(g.subject_objects(desc)):
        if s_ == mde or not isinstance(s_, URIRef):
            continue
        local = str(s_).rsplit("/", 1)[-1]
        new = OWN_TEXT.get(local) or swap(str(o_))
        if new != str(o_):
            p_ = iao115 if (s_, iao115, o_) in g else desc
            g.remove((s_, p_, o_)); g.add((s_, p_, lit(new)))
            changed.append((local, str(o_), new))
    return g, changed


def wont(old):
    import rdflib
    from rdflib import Literal, URIRef
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    changed, moved = [], 0
    for s_, p_, o_ in old:
        if o_ == URIRef(PD):
            o_ = URIRef(MDE); moved += 1
        elif isinstance(o_, Literal) and "pathological disorder" in str(o_):
            new = Literal(swap(str(o_)), lang=o_.language, datatype=o_.datatype)
            changed.append((str(s_).rsplit("/", 1)[-1], str(o_), str(new)))
            o_ = new
        g.add((s_, p_, o_))
    return g, changed, moved


def check(g, name):
    import rdflib
    from rdflib import URIRef
    left = [(s, p) for s, p, o in g.triples((None, None, URIRef(PD)))
            if str(p) != OBO + "IAO_0100001"]
    if left:
        raise RuntimeError(f"{name}: {len(left)} use(s) of MILD_120022 left: {left[:5]}")
    texts = [str(o) for s, p, o in g if isinstance(o, rdflib.Literal) and "pathological disorder" in str(o)]
    return texts


def placements(gt, argv) -> Counter:
    from wound_ontology.mappers.judgements import current
    tally = Counter()
    for t, rec in list(gt.records.items()):
        for k, js in list((rec.get("is_a") or {}).items()):
            cj = current(js)
            iri = next((j["iri"] for j in reversed(js) if j.get("iri")), None)
            if iri != PD or not cj or cj["verdict"] != "yes":
                continue
            why = f"pathological disorder merged into material disease entity ({WORDS}); placed under it by {cj['by']}"
            gt._put(t, "is_a", gt._j("no", "author", why, None, PD), k)
            gt._put(t, "is_a", gt._j("yes", "author", why, None, MDE), "material disease entity")
            tally[f"moved, placed by {cj['by']}"] += 1
    return tally


def curator_prefixes(text: str) -> str:
    """ROBOT sets `:` to the ontology IRI with `#` and keeps rdflib's `ns1:`; MILD
    writes its own classes as `:MILD_...` (`:` = .../MILD/). Only where `.../MILD#`
    names nothing but the prefix, and `obo:` is free, so no IRI changes."""
    if text.count("ontologies/MILD#") != 1 or "obo:" in text:
        raise RuntimeError("the prefixes cannot be set back without changing an IRI")
    text = text.replace("@prefix : <https://bioportal.bioontology.org/ontologies/MILD#> .",
                        "@prefix : <https://bioportal.bioontology.org/ontologies/MILD/> .")
    text = re.sub(r"<https://bioportal\.bioontology\.org/ontologies/MILD/(MILD_\d+)>", r":\1", text)
    text = text.replace("@prefix ns1: <http://purl.obolibrary.org/obo/> .", "@prefix obo: <http://purl.obolibrary.org/obo/> .")
    return re.sub(r"\bns1:", "obo:", text)


def main(argv) -> int:
    import rdflib
    old_m = rdflib.Graph().parse(MILD_OLD, format="turtle")
    g_m, changed_m = mild(old_m)
    texts_m = check(g_m, "MILD")
    old_w = rdflib.Graph().parse(WONT_OLD, format="turtle")
    g_w, changed_w, moved = wont(old_w)
    texts_w = check(g_w, "WONT")
    print(f"[one-entity] MILD {len(old_m):,} -> {len(g_m):,} triples; definitions rewritten:")
    for local, a, b in changed_m:
        print(f"[one-entity]     {local}: {a[:110]!r}\n[one-entity]       -> {b[:110]!r}")
    print(f"[one-entity] MILD texts still saying pathological disorder: {len(texts_m)}")
    for t in texts_m:
        print(f"[one-entity]     {t[:150]!r}")
    print(f"[one-entity] WONT {len(old_w):,} -> {len(g_w):,} triples; {moved} use(s) of MILD_120022 now MILD_120020; "
          f"{len(changed_w)} text(s) rewritten:")
    for local, a, b in changed_w:
        print(f"[one-entity]     {local}: {b[:150]!r}")
    print(f"[one-entity] WONT texts still saying pathological disorder: {len(texts_w)}")
    from wound_ontology.orchestrator import Orchestrator
    gt = Orchestrator().term_mapper._term_mapping
    tally = placements(gt, argv)
    gt._dirty()
    print(f"[one-entity] placements: {dict(tally)}")
    if "--write" not in argv:
        print("[one-entity] dry run; --write writes the two files and the term dict")
        return 0
    for f in (MILD_NEW, WONT_NEW):
        if f.exists():
            raise RuntimeError(f"{f} exists; not overwritten")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "mild.ttl"
        g_m.serialize(src, format="turtle")
        r = subprocess.run([*ROBOT, "--catalog", str(ROOT / "output" / "owl" / "catalog-v001.xml"), "convert",
                            "--input", str(src), "--output", str(MILD_NEW)],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"ROBOT could not write MILD: {(r.stderr + r.stdout)[-600:]}")
    MILD_NEW.write_text(curator_prefixes(MILD_NEW.read_text(encoding="utf-8")), encoding="utf-8")
    back = rdflib.Graph().parse(MILD_NEW, format="turtle")
    from rdflib.compare import graph_diff, to_isomorphic
    _, only_back, only_ours = graph_diff(to_isomorphic(back), to_isomorphic(g_m))
    print(f"[one-entity] {MILD_NEW.name} written by ROBOT and read back: {len(back):,} triples; "
          f"{len(only_back)} only in the file, {len(only_ours)} only in the graph meant")
    for t in list(only_back)[:10] + list(only_ours)[:10]:
        print(f"[one-entity]     {t}")
    g_w.serialize(WONT_NEW, format="turtle")
    print(f"[one-entity] written {WONT_NEW.relative_to(ROOT)}")
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_one_disease_entity_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[one-entity] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
