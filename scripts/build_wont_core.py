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
hierarchy VIEW's provenance (derived on the spot, with the edge gate's verdicts
taken off -- the same view the extension was built from). Writes output/owl/wont_extended_core.ttl,
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
# The curator's word on relations is in the term dict (rules 69, 72; until
# 2026-10-30 in curator_axioms_2026-10-03.json and
# new_class_relation_decisions.json): relations from the abstracts on NEW
# classes wait for it (2026-10-05: "have i ever reviewed these?" -- no: they
# were read only by Claude), and only his `yes` goes into the addition.
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
    # Rule 79 (2026-10-20): an edge from the concept analysis is in the
    # hierarchy only because the curator's head-word rule licensed it, and the
    # edge check reasoned over it; it hangs a class into the core like a
    # checked placement. Without this the 464 licensed edges reached only the
    # full extension and `Burn Injury` (under `Injury`) never reached the core.
    ruled = {(smart_title(c), smart_title(par)) for c, par in p.class_hier.edges_by_source("fca")}
    print(f"[core] {len(placed):,} placed edge(s) + {len(ruled):,} edge(s) licensed by the head-word rule (rule 79)")
    placed_only = set(placed)                       # which way a class came in, for the report
    placed |= ruled
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
    # A placed parent WONT has merged away is found as the export found it: by
    # WONT's own labels and synonyms first. Redness, merged into reddened with
    # "Redness" kept as its synonym (curator, 2026-10-31), is reddened in the
    # export; matched on labels alone its three placed children fell out of the
    # core (found 2026-10-31).
    from wound_ontology.owl.extend import IMPORT_SKIP, find_imported, label_index, lexicon_index, other_names
    gt_idx = label_index(gt)
    lex = lexicon_index(default_lexicon())
    names = other_names(p.term_mapper._term_mapping)
    placed_iri, placed_iri_only = set(), set()
    for c_, par_ in placed:
        hit = gt_idx.get(par_)[0]
        if hit is None:
            hit = lex.get(par_)[0]
        if hit is None:
            found = find_imported(lex, par_, names, IMPORT_SKIP)
            hit = rdflib.URIRef(found[0]) if isinstance(found, tuple) else None
        if hit is not None:
            placed_iri.add((c_, hit))
            if (c_, par_) in placed_only:
                placed_iri_only.add((c_, hit))

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
    tdict = p.term_mapper._term_mapping
    from wound_ontology.llm.extraction_models import RELATION_IRI
    from wound_ontology.utils.string_utils import normalize_term as N
    authored = tdict.author_relations()
    # a predicate the extraction never writes is found by its label among the
    # object properties of WONT and MILD ("is process boundary at start of",
    # MILD_120083: a recurrence starts a course of the disease, curator 2026-10-30)
    from config.settings import MILD_TTL
    prop_label = {}
    for g_ in (gt, rdflib.Graph().parse(str(MILD_TTL), format="turtle")):
        for s_ in g_.subjects(RDF.type, OWL.ObjectProperty):
            for o_ in g_.objects(s_, RDFS.label):
                prop_label.setdefault(str(o_).lower(), str(s_))
    RELATION_IRI = {**{k.lower(): v for k, v in prop_label.items()}, **RELATION_IRI}
    unknown = sorted({pr for _, pr, _, _ in authored if pr.replace("_", " ") not in RELATION_IRI})
    if unknown:
        raise RuntimeError(f"[core] the author judged relations with predicates that have no IRI: {unknown}")
    approved: dict = {}       # (subject class, property, filler class) -> add | leave out; filled below
    held: dict = {}

    def rel_key(c, prop, f):
        return (c, str(prop), f)

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
                        held["|".join(map(str, k))] = {"subject": lab(c), "subject_iri": str(c),
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
    # The curator's axioms (rule 69): every relation he said `yes` to, and his
    # links between two terms on a class the addition does not mint (Wound is
    # an Injury); added every round and never dropped by the ELK loop -- if ELK
    # rejects one, the build stops and names it. Read from the term dict.
    curator = [{"subject_iri": None, "subject_label": s_, "property_iri": RELATION_IRI[pr.replace("_", " ")],
                "filler_iri": j.get("iri"), "filler_label": t_, "why": j["why"]}
               for s_, pr, t_, j in authored if j["verdict"] == "yes"]
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
    known_as: dict = {}
    for t_ in tdict.records:
        try:
            known_as.setdefault(tdict.concept(tdict.resolve(t_)), set()).add(t_)
        except RuntimeError:
            pass
    by_norm: dict = {}
    for s_, o_ in ext.subject_objects(RDFS.label):
        by_norm.setdefault(N(str(o_)), set()).add(s_)
    for t_, par_ in tdict.term_links():
        hits = by_norm.get(N(t_), set())
        if hits and not hits & minted:
            curator.append({"subject_iri": None, "subject_label": t_, "property_iri": None,
                            "filler_iri": None, "filler_label": par_, "why": "the author's link between two terms"})

    def stable_or_by_name(iri, name, role):
        if iri and (not iri.startswith(WONT_NS) or rdflib.URIRef(iri) in gt_classes):
            return rdflib.URIRef(iri)
        cur = tdict.resolve(name)
        tried = [tdict.data.get(cur) or cur, cur, name]      # the current name first
        for n in tried:
            hit = all_by_label.get(str(n).lower())
            if hit is not None:
                return hit
        # the term dict's names are not the build's labels ("Burn depth", "Burn Wound Depth")
        hits = sorted(by_norm.get(N(cur), set()) | by_norm.get(N(name), set()))
        if not hits:
            # an imported class, found through the lexicon as the export finds it
            # ("wound healing", GO_0042060), under the concept's other names too:
            # one the author made the same as it ("wound healing process")
            for n in [cur, name, *sorted(known_as.get(tdict.concept(cur), ()))]:
                hit = lex.get(n)[0]
                if hit is None:
                    found = find_imported(lex, n, names, IMPORT_SKIP)
                    hit = found[0] if isinstance(found, tuple) else None
                if hit is not None:
                    hits = [rdflib.URIRef(hit)]
                    break
        if not hits:
            hits = sorted({h for n in known_as.get(tdict.concept(cur), ()) for h in
                           ({all_by_label.get(n.lower())} - {None}) | by_norm.get(N(n), set())})
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise RuntimeError(f"[core] curator axiom {role} {name!r}: {len(hits)} classes share its spelling: "
                               f"{[lab(h) or str(h) for h in hits]}")
        # not built, and said so in the report (`author axioms not built`)
        return "out of scope" if tdict.gate_verdict(tdict.concept(cur))[0] == "out" else "not a class in this build"

    # the author's word on each relation, found on the classes the build names
    # them by, with the same lookup as his axioms ("Early wound healing process
    # part_of wound healing process" is GO's "wound healing" here)
    for s_, pr, t_, j in authored:
        try:
            sc = stable_or_by_name(None, s_, "subject")
            fc = stable_or_by_name(j.get("iri"), t_, "filler")
        except RuntimeError:
            if j["verdict"] == "yes":
                raise
            continue                  # a `no` on a name several classes share: nothing of it is built either
        if isinstance(sc, rdflib.URIRef) and isinstance(fc, rdflib.URIRef):
            approved[rel_key(sc, RELATION_IRI[pr.replace("_", " ")], fc)] = {"yes": "add", "no": "leave out"}[j["verdict"]]

    unbuilt: list = []
    # what became of each of the author's axioms, one entry each, so that they
    # add up (the counters above overlap: a relation kept from the export is
    # "already stated" when his axiom on it comes round)
    account: list = []

    def stated(g, subj, prop, fill):
        return any(isinstance(b, rdflib.BNode) and g.value(b, OWL.onProperty) == prop
                   and g.value(b, OWL.someValuesFrom) == fill for b in g.objects(subj, RDFS.subClassOf))

    def tell(a, outcome, subj=None):
        account.append({"subject": a["subject_label"], "property_iri": a["property_iri"],
                        "filler": a["filler_label"], "outcome": outcome,
                        "on a new class": isinstance(subj, rdflib.URIRef) and subj in minted})

    def add_curator(g):
        unbuilt.clear(); account.clear()
        for a in curator:
            subj = stable_or_by_name(a["subject_iri"], a["subject_label"], "subject")
            fill = stable_or_by_name(a["filler_iri"], a["filler_label"], "filler")
            if not isinstance(subj, rdflib.URIRef) or not isinstance(fill, rdflib.URIRef):
                unbuilt.append((a["subject_label"], a["property_iri"], a["filler_label"],
                                "; ".join(f"{role} {w}" for role, w in (("subject", subj), ("filler", fill))
                                          if not isinstance(w, rdflib.URIRef))))
                tell(a, "not built", subj)
                continue
            if subj in minted and subj not in core:
                unbuilt.append((a["subject_label"], a["property_iri"], a["filler_label"], "the subject is a candidate"))
                tell(a, "not built", subj)
                continue
            if fill in minted and fill not in core:
                pulled.add(fill)
                copy_class(fill, g, typing_only=True)
            if not a.get("property_iri"):
                # a plain subclass axiom (curator 2026-10-18: "Wound is an injury")
                if (subj, RDFS.subClassOf, fill) in g:
                    rep["curator axioms already stated"] += 1
                    tell(a, "already in WONT" if (subj, RDFS.subClassOf, fill) in gt else "already built", subj)
                else:
                    g.add((subj, RDFS.subClassOf, fill))
                    rep["curator axioms"] += 1
                    tell(a, "added", subj)
                continue
            prop = rdflib.URIRef(a["property_iri"])
            if stated(g, subj, prop, fill):
                rep["curator axioms already stated"] += 1
                tell(a, "already in WONT" if stated(gt, subj, prop, fill) else "already built", subj)
                continue
            node = rdflib.BNode()
            g.add((node, RDF.type, OWL.Restriction))
            g.add((node, OWL.onProperty, prop))
            g.add((node, OWL.someValuesFrom, fill))
            g.add((subj, RDFS.subClassOf, node))
            rep["curator axioms"] += 1
            tell(a, "added", subj)

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

    def came_in_by(c):
        """A checked placement or a link of the author's, else the head-word rule's edge (rule 79)."""
        for par in named_parents(c):
            if is_placed(c, par) and (par not in minted or par in core) and (
                    (smart_title(lab(c)), smart_title(lab(par))) in placed_only
                    or (smart_title(lab(c)), par) in placed_iri_only):
                return "placement"
        return "head-word rule"
    entered = {lab(c): came_in_by(c) for c in core}
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

    if unbuilt:
        print(f"[core] *** {len(unbuilt)} of the author's axiom(s) not built: ***")
        for u in unbuilt:
            print(f"[core]     {u[0]} | {u[1]} | {u[2]}: {u[3]}")
    summary = {"minted": len(minted), "core": len(core), "candidates": len(cand), **dict(rep),
               "author axioms not built": [list(u) for u in unbuilt],
               "author axioms (account)": account,
               "core classes, the way they came in": entered,
               "classes brought in as curator-axiom fillers (list)": sorted(lab(c) or str(c) for c in pulled),
               "elk_moves": elk_moves,
               "relations held for the curator (list)": sorted(held.values(), key=lambda h: h["subject"].lower()),
               "unsatisfiable_below_curated": sorted(lab(u) for u in below_gt),
               "ground_truth_unsatisfiable": sorted(str(u) for u in gt_unsat),
               "core_examples": sorted(f"{lab(c)} < {', '.join(lab(o) for o in named_parents(c) if is_placed(c, o))}"
                                       for c in core)[:40]}
    print(f"[core] {json.dumps({k: v for k, v in summary.items() if k not in ('core_examples', 'elk_moves', 'author axioms (account)', 'core classes, the way they came in')})}")
    print(f"[core] the author's axioms: {dict(Counter((x['outcome'], x['on a new class']) for x in account))}")
    print(f"[core] core classes by the way they came in: {dict(Counter(entered.values()))}")
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
