"""Build the WONT addition's core from checked edges only (rule 66). Replaces split_extension.py.

    python -u scripts/build_wont_core.py [--write]

Curator, 2026-10-02/03: "I'd rather take little nodes and edges and add them to
the onto than bad ones" ... "rebuild the WONT addition". `split_extension.py`
(2026-09-28) placed classes by head noun (`Burn Wound` under `Wound`) and by
model subclass candidates nobody had reviewed; since rules 59-64 every
placement is read twice and enters the hierarchy as source `placed`. So:

* a minted class is in the CORE only when a `placed` edge hangs it under a
  curated class (WONT, MILD, an import module, BFO) or under another core class;
* it keeps its placed parent(s) and its BFO category typing, nothing else from
  the text -- an is_a edge one abstract wrote between two terms is not checked;
* a relation (only the 203 read as true of every instance reach the extension)
  stays when its filler is curated, a category or in the core; otherwise it is
  dropped and counted;
* every other minted class goes to `wont_candidates.ttl` under its category,
  for later review, importing the core.

Reads output/owl/wont_extended.ttl (run_extend_ground_truth) and the class
hierarchy's provenance. Writes output/owl/wont_extended_core.ttl,
output/owl/wont_candidates.ttl and output/owl/core_build_report.json; each is
read back.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

OUT = ROOT / "output" / "owl"
EXT = OUT / "wont_extended.ttl"
CORE = OUT / "wont_extended_core.ttl"
CAND = OUT / "wont_candidates.ttl"
REPORT = OUT / "core_build_report.json"
CURATOR = ROOT / "data" / "review" / "curator_axioms_2026-10-03.json"
# Relations from the abstracts on NEW classes wait for the curator (rule 72,
# 2026-10-05: "have i ever reviewed these?" -- no: they were read only by
# Claude). Only a relation marked "add" in this file goes into the addition.
REL_REVIEW = ROOT / "data" / "review" / "new_class_relation_decisions.json"
WONT_NS = "https://bioportal.bioontology.org/ontologies/WONT/"
PROV = "http://www.geneontology.org/formats/oboInOwl#source"
CORE_IRI = "https://bioportal.bioontology.org/ontologies/WONT/extended-core"


ROBOT = ["java", "-Xmx6g", "-jar", "/usr/local/bin/robot.jar"]
CATALOG = OUT / "catalog-v001.xml"


def elk_unsat(graph, *, label: str) -> set:
    """IRIs ELK finds unsatisfiable in `graph` with its import closure (via the catalog).

    An inconsistent ontology names no culprit; it means an emptied class holds
    one of WONT's named individuals. Then the question is asked again without
    the individuals, so the empty classes are named (2026-10-04, as in the
    edge gate), and that is said."""
    try:
        return _elk_unsat(graph, label=label)
    except RuntimeError as exc:
        if "inconsistent" not in str(exc):
            raise
    import rdflib
    from rdflib.namespace import OWL, RDF
    bare = rdflib.Graph(); bare += graph
    for ind in set(bare.subjects(RDF.type, OWL.NamedIndividual)):
        for t in list(bare.triples((ind, None, None))) + list(bare.triples((None, None, ind))):
            bare.remove(t)
    found = _elk_unsat(bare, label=label + " (without individuals)")
    print(f"[core] ELK: {label} is inconsistent with WONT's individuals; without them "
          f"{len(found)} class(es) are unsatisfiable", flush=True)
    if not found:
        raise RuntimeError(f"[core] {label}: inconsistent, and not through an empty class -- look by hand")
    return found


def _elk_unsat(graph, *, label: str) -> set:
    import re
    import subprocess
    import tempfile
    import rdflib
    with tempfile.TemporaryDirectory() as tmp:
        src, merged = Path(tmp) / "in.ttl", Path(tmp) / "merged.owl"
        graph.serialize(src, format="turtle")
        r = subprocess.run([*ROBOT, "--catalog", str(CATALOG), "merge", "--input", str(src),
                            "--collapse-import-closure", "true", "--output", str(merged)],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"[core] robot merge failed for {label}: {r.stderr[-800:]}")
        r = subprocess.run([*ROBOT, "reason", "--reasoner", "ELK", "--input", str(merged),
                            "--output", str(Path(tmp) / "out.owl")], capture_output=True, text=True)
        log = r.stdout + r.stderr
        if r.returncode and "unsatisfiable" not in log:
            raise RuntimeError(f"[core] ELK failed for {label}: {log[-800:]}")
        return {rdflib.URIRef(x) for x in re.findall(r"unsatisfiable: (\S+)", log)}


def ancestors(g, c) -> set:
    from rdflib.namespace import RDFS
    import rdflib
    out, stack = set(), [c]
    while stack:
        x = stack.pop()
        for p in g.objects(x, RDFS.subClassOf):
            if isinstance(p, rdflib.URIRef) and p not in out:
                out.add(p); stack.append(p)
    return out


def main(argv: list[str]) -> int:
    import rdflib
    from rdflib.namespace import OWL, RDF, RDFS
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL, GROUND_TRUTH_TTL
    from wound_ontology.llm.extraction_models import CATEGORY_IRI
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import smart_title

    ext = rdflib.Graph(); ext.parse(EXT, format="turtle")
    gt = rdflib.Graph(); gt.parse(str(GROUND_TRUTH_TTL), format="turtle")
    prov = rdflib.URIRef(PROV)
    minted = {s for s in ext.subjects(prov, None) if isinstance(s, rdflib.URIRef)}
    cats = {rdflib.URIRef(v) for v in CATEGORY_IRI.values()}
    label = {s: str(o) for s, o in ext.subject_objects(RDFS.label)}

    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    placed = {(smart_title(c), smart_title(par)) for c, par in p.class_hier.edges_by_source("placed")}
    # labels of imported parents (not in ext): from the lexicon the export used
    from wound_ontology.owl.extend import default_lexicon
    from wound_ontology.utils.rdf_io import parse_graph
    imported_label = {}
    for path in default_lexicon():
        for s_, o_ in parse_graph(Path(path), context="core labels").subject_objects(RDFS.label):
            imported_label.setdefault(s_, str(o_))

    def lab(x):
        return label.get(x) or imported_label.get(x) or ""

    def named_parents(c):
        return [o for o in ext.objects(c, RDFS.subClassOf) if isinstance(o, rdflib.URIRef)]

    # A placed parent from an import is named in the hierarchy as the term was
    # written ("Bacterium") and resolved by the export through the lexicon to
    # an IRI whose label differs (NCBITaxon_2 "Bacteria"). Comparing labels
    # alone kept 144 checked placements out of the core (found 2026-10-05):
    # compare the IRI the export resolved the parent name to as well.
    # A placed parent the naming rules renamed ("Sample From Organism", once OBI's
    # "specimen from organism") is found under its other names, exactly as the
    # export found it (rule 74, `other_names`); without this its 4 children stayed
    # out although the export had resolved their parent (found 2026-10-08).
    from wound_ontology.owl.extend import IMPORT_SKIP, find_imported, lexicon_index, other_names
    lex = lexicon_index(default_lexicon())
    names = other_names(p.term_mapper._term_mapping)
    placed_iri = set()
    for c_, par_ in placed:
        hit = lex.get(par_)[0]
        if hit is None:
            found = find_imported(lex, par_, names, IMPORT_SKIP)
            hit = rdflib.URIRef(found[0]) if isinstance(found, tuple) else None
        if hit is not None:
            placed_iri.add((c_, hit))

    def is_placed(c, par):
        return (smart_title(lab(c)), smart_title(lab(par))) in placed or (smart_title(lab(c)), par) in placed_iri

    core: set = set()
    changed = True
    while changed:                                   # parents first, to a fixed point
        changed = False
        for c in minted - core:
            if any(is_placed(c, par) and (par not in minted or par in core) for par in named_parents(c)):
                core.add(c); changed = True
    cand = minted - core

    rep = Counter()
    core_g = rdflib.Graph()
    for pfx, ns in ext.namespaces():
        core_g.bind(pfx, ns)
    core_g += gt
    for o in core_g.subjects(RDF.type, OWL.Ontology):
        core_g.add((o, RDFS.comment, rdflib.Literal(
            "WONT plus the classes the wound-ontology pipeline placed under it after two checks "
            "(rules 59-66): placed edges and BFO category typing only; relations only where read "
            "as true of every instance.", lang="en")))
    allowed = lambda x: x in cats or x not in minted or x in core
    approved = {}
    if REL_REVIEW.exists():
        approved = {k: d.get("v") for k, d in json.loads(REL_REVIEW.read_text(encoding="utf-8"))["decisions"].items()}
    held: dict = {}

    def rel_key(c, prop, f):
        return f"{lab(c).lower()}|{prop}|{lab(f).lower()}"

    def copy_class(c, g, *, typing_only: bool, keep_relations: bool = True):
        for pr, o in ext.predicate_objects(c):
            if pr == RDFS.subClassOf:
                if isinstance(o, rdflib.URIRef):
                    if o in cats:
                        g.add((c, pr, o)); rep["typing edges" + (" (candidates)" if typing_only else "")] += 1
                    elif not typing_only and is_placed(c, o) and allowed(o):
                        g.add((c, pr, o)); rep["placed edges"] += 1
                    else:
                        rep["text edges left out" + (" (candidates)" if typing_only else "")] += 1
                else:                                # a restriction
                    f = ext.value(o, OWL.someValuesFrom)
                    if typing_only:
                        rep["relations left out (subject is a candidate)"] += 1
                    elif not keep_relations:
                        rep["relations left out (ELK: unsatisfiable with them)"] += 1
                    elif f is not None and allowed(f) and approved.get(rel_key(c, ext.value(o, OWL.onProperty), f)) != "add":
                        k = rel_key(c, ext.value(o, OWL.onProperty), f)
                        held[k] = {"subject": lab(c), "subject_iri": str(c),
                                   "property_iri": str(ext.value(o, OWL.onProperty)),
                                   "value": lab(f), "value_iri": str(f), "decision": approved.get(k)}
                        rep["relations held for the curator" if approved.get(k) is None
                            else "relations left out by the curator"] += 1
                    elif f is not None and allowed(f):
                        g.add((c, pr, o))
                        for t in ext.triples((o, None, None)):
                            g.add(t)
                        rep["relations kept"] += 1
                    else:
                        rep["relations left out (filler not in core)"] += 1
            else:
                g.add((c, pr, o))

    # ELK decides what is still wrong (rule 67). A new class it finds
    # unsatisfiable loses its relations first (a relation whose filler resolved
    # to the wrong class); if it stays unsatisfiable, its BFO typing and its
    # checked placement disagree and it goes to the candidates. A class that is
    # unsatisfiable only because its curated parent is (WONT's own conflicts)
    # stays, and is reported.
    # The curator's axioms on existing classes (rule 69): read from the review,
    # added every round, and never dropped by the ELK loop -- if ELK rejects
    # one, the build stops and names it.
    curator = json.loads(CURATOR.read_text(encoding="utf-8"))["axioms"] if CURATOR.exists() else []
    by_label = {}
    for s_, o_ in ext.subject_objects(RDFS.label):
        if s_ in minted:
            by_label.setdefault(str(o_).lower(), s_)
    pulled: set = set()

    # A class the pipeline minted gets its WONT id afresh on every build, so a
    # curator axiom holding a minted IRI points at whatever took that number
    # next time (2026-10-04: "every wound has some length" landed on
    # WONT_0004067, by then `Ligamentous Rupture`, and emptied Wound). Only
    # WONT's own IRIs and imported ones are stable; anything else is found by
    # NAME, through the term dict, so a rename (ulcer -> Wound) is followed.
    gt_classes = set(gt.subjects(RDF.type, OWL.Class))
    all_by_label = {}
    for s_, o_ in ext.subject_objects(RDFS.label):
        all_by_label.setdefault(str(o_).lower(), s_)
    tdict = p.term_mapper._term_mapping

    def stable_or_by_name(iri, name, role):
        if iri and (not iri.startswith(WONT_NS) or rdflib.URIRef(iri) in gt_classes):
            return rdflib.URIRef(iri)
        cur = tdict.resolve(name)
        tried = [tdict.data.get(cur) or cur, cur, name]      # the current name first
        for n in tried:
            hit = all_by_label.get(str(n).lower())
            if hit is not None:
                return hit
        raise RuntimeError(f"[core] curator axiom {role} {name!r} is not a class in this build (tried {tried})")

    def add_curator(g):
        for a in curator:
            subj = stable_or_by_name(a["subject_iri"], a["subject_label"], "subject")
            fill = stable_or_by_name(a["filler_iri"], a["filler_label"], "filler")
            if fill in minted and fill not in core:
                pulled.add(fill)
                copy_class(fill, g, typing_only=True)
            prop = rdflib.URIRef(a["property_iri"])
            if any(isinstance(b, rdflib.BNode) and g.value(b, OWL.onProperty) == prop
                   and g.value(b, OWL.someValuesFrom) == fill for b in g.objects(subj, RDFS.subClassOf)):
                rep["curator axioms already stated"] += 1
                continue
            node = rdflib.BNode()
            g.add((node, RDF.type, OWL.Restriction))
            g.add((node, OWL.onProperty, prop))
            g.add((node, OWL.someValuesFrom, fill))
            g.add((subj, RDFS.subClassOf, node))
            rep["curator axioms"] += 1

    gt_unsat = elk_unsat(gt, label="ground truth")
    no_relations: set = set()
    elk_moves = []
    base = rdflib.Graph(); base += core_g
    for round_ in range(1, 8):
        core_g = rdflib.Graph(); core_g += base
        rep.clear(); held.clear()
        for c in core:
            copy_class(c, core_g, typing_only=False, keep_relations=c not in no_relations)
        pulled.clear()
        add_curator(core_g)
        unsat = elk_unsat(core_g, label=f"core, round {round_}")
        stray = unsat - gt_unsat - core
        if stray:
            core_g.serialize(OUT / "core_failed_elk.ttl", format="turtle")   # kept for diagnosis
            raise RuntimeError(f"[core] ELK finds classes unsatisfiable that are not new core classes -- a "
                               f"curator axiom or a curated class is involved: {sorted(lab(u) or str(u) for u in stray)[:20]}")
        new = {u for u in unsat - gt_unsat if u in core}
        below_gt = {u for u in new if any(a in gt_unsat for a in ancestors(core_g, u))}
        fix = new - below_gt
        print(f"[core] ELK round {round_}: {len(unsat)} unsatisfiable, {len(gt_unsat)} of them the ground "
              f"truth's own, {len(new)} new ({len(below_gt)} only below an unsatisfiable curated class)", flush=True)
        if not fix:
            break
        for u in sorted(fix, key=str):
            if u not in no_relations and any(isinstance(o, rdflib.BNode) for o in ext.objects(u, RDFS.subClassOf)):
                no_relations.add(u); elk_moves.append((lab(u), "relations dropped"))
            else:
                core.discard(u); elk_moves.append((lab(u), "typing contradicts placement -> candidates"))
        # a class whose placed parent left the core leaves too
        changed = True
        while changed:
            changed = False
            for c in list(core):
                if not any(is_placed(c, par) and (par not in minted or par in core) for par in named_parents(c)):
                    core.discard(c); changed = True; elk_moves.append((lab(c), "placed parent left the core"))
    else:
        raise RuntimeError("[core] ELK did not settle in 7 rounds")
    cand = minted - core - pulled
    rep["elk_left_unsatisfiable_below_curated"] = len(below_gt)
    rep["classes brought in as curator-axiom fillers"] = len(pulled)
    cand_g = rdflib.Graph()
    for pfx, ns in ext.namespaces():
        cand_g.bind(pfx, ns)
    ont = rdflib.URIRef(CORE_IRI.replace("extended-core", "candidates"))
    cand_g.add((ont, RDF.type, OWL.Ontology))
    cand_g.add((ont, OWL.imports, rdflib.URIRef(CORE_IRI)))
    for c in cand:
        copy_class(c, cand_g, typing_only=True)

    summary = {"minted": len(minted), "core": len(core), "candidates": len(cand), **dict(rep),
               "elk_moves": elk_moves,
               "relations held for the curator (list)": sorted(held.values(), key=lambda h: h["subject"].lower()),
               "unsatisfiable_below_curated": sorted(lab(u) for u in below_gt),
               "ground_truth_unsatisfiable": sorted(str(u) for u in gt_unsat),
               "core_examples": sorted(f"{lab(c)} < {', '.join(lab(o) for o in named_parents(c) if is_placed(c, o))}"
                                       for c in core)[:40]}
    print(f"[core] {json.dumps({k: v for k, v in summary.items() if k not in ('core_examples', 'elk_moves')})}")
    print(f"[core] ELK moves: {elk_moves}")
    if "--write" not in argv:
        print("[core] dry run; --write to write")
        return 0
    import shutil
    from datetime import datetime
    bak = ROOT / "data" / "backup" / f"core_{datetime.now():%Y-%m-%d_%H-%M-%S}"
    bak.mkdir(parents=True, exist_ok=True)
    for f in (CORE, CAND, REPORT):
        if f.exists():
            shutil.copy2(f, bak / f.name)
    print(f"[core] previous files backed up to {bak.relative_to(ROOT)}")
    core_g.serialize(CORE, format="turtle"); cand_g.serialize(CAND, format="turtle")
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    back = rdflib.Graph(); back.parse(CORE, format="turtle")
    n_back = len({s for s in back.subjects(prov, None)})
    if n_back != len(core) + len(pulled):
        raise RuntimeError(f"[core] read back {n_back} minted classes in the core, wrote {len(core)} + {len(pulled)}")
    print(f"[core] written and read back: {CORE.name} ({len(back):,} triples, {n_back:,} new classes), "
          f"{CAND.name}, {REPORT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
