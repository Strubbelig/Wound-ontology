"""Split the extended WONT into a placed core and a module of unplaced candidates.

    python scripts/split_extension.py [--min-abstracts 2] [--write]

Curator, 2026-09-28 ("do the middle way"). A class the pipeline minted is KEPT
when it is an extracted term (not only a relation target), in scope, mentioned
in at least `--min-abstracts` abstracts, and typed into one category by every
abstract. Kept classes are then PLACED, if they can be, under a WONT/MILD class:

* head noun   -- `Burn Wound` under `Wound`, `Foot Ulcer` under `Ulcer`: the
                 longest trailing word sequence that is a curated label or
                 another kept term;
* subclass candidate -- a pair the model adjudications (or the curator) judged
                 `narrower`/`broader` and nobody refused.

A parent is accepted only when its category is the child's or an ancestor of
it, so `Wound Bed` (material entity) cannot land under a hospital `Bed` of
another kind by accident of wording -- and only when the parent is itself
placed, so every placed class has a chain to the curated core. Each added edge
carries its source as an axiom annotation.

Output, beside the extension (which is left as it is):
  output/owl/wont_extended_core.ttl  WONT + the placed classes
  output/owl/wont_candidates.ttl     the kept but unplaced classes, under their
                                     BFO category, importing the core
Relations are kept only between classes that are in one of the two files or in
the curated closure; a relation to anything else is dropped (its target stays a
grouping attribute for concept analysis, not a class).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "output" / "owl"
EXT = OUT / "wont_extended.ttl"
GT = ROOT / "data" / "ground truth" / "ground_truth_final.owl"
MILD = ROOT.parent / "Disease ontologies" / "mild.ttl"
NS = "https://bioportal.bioontology.org/ontologies/WONT/"
PROV = "http://www.geneontology.org/formats/oboInOwl#source"


def _opt(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv: list[str]) -> int:
    import rdflib
    from rdflib.namespace import OWL, RDF, RDFS

    from wound_ontology.llm.extraction_models import CATEGORY_IRI, CATEGORY_PARENT
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import normalize_term as N

    write = "--write" in argv
    min_abs = int(_opt(argv, "--min-abstracts", "2"))
    prov = rdflib.URIRef(PROV)

    ext = rdflib.Graph(); ext.parse(EXT, format="turtle")
    cur = rdflib.Graph(); cur.parse(GT, format="turtle"); cur.parse(MILD, format="turtle")
    curated = {s for s in cur.subjects(RDF.type, OWL.Class) if isinstance(s, rdflib.URIRef)}
    cat_iris = {rdflib.URIRef(v): k for k, v in CATEGORY_IRI.items()}
    minted = sorted(set(ext.subjects(prov, None)), key=str)
    label = {s: str(ext.value(s, RDFS.label) or "") for s in minted}

    def ancestors(cat):
        out, c = set(), cat
        while c:
            out.add(c); c = CATEGORY_PARENT.get(c)
        return out

    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    onto_cat = {N(k): v for k, v in p.ontology_categories().items()}
    docs: Counter = Counter(); typings: dict[str, set] = defaultdict(set)
    for _, ents in p.store.view():
        for name, attrs in ents.items():
            docs[N(name)] += 1
            for t in attrs:
                pred, _, tgt = t.partition(":")
                if pred.strip() == "is_a":
                    typings[N(name)].add(tgt.strip())

    def category(n: str):
        cats = typings.get(n, set())
        if not cats:
            return None
        return next(iter(cats)) if len(cats) == 1 else p.reasoner_gate.least_common_category(cats)

    kept: dict[str, rdflib.URIRef] = {}        # normalised label -> IRI
    kept_cat: dict[rdflib.URIRef, str] = {}
    for c in minted:
        n = N(label[c])
        if docs[n] < min_abs:
            continue
        v, _ = gt.effective_gate_verdict(gt.resolve(label[c]))
        cat = category(n)
        if v != "in" or cat is None:
            continue
        kept[n] = c; kept_cat[c] = cat
    curated_by_label = {}
    for s in curated:
        for l in cur.objects(s, RDFS.label):
            curated_by_label.setdefault(N(str(l)), s)
    print(f"[split] {len(minted):,} minted; kept {len(kept):,} "
          f"(term, in scope, >= {min_abs} abstracts, one category)")

    full = rdflib.Graph()
    full += cur
    for m in (ROOT.parent / "Disease ontologies" / "Disease ontology modules").glob("*_module.owl"):
        try:
            full.parse(m)
        except Exception as exc:                 # reported, never silent
            print(f"[split]   ! could not read {m.name}: {exc}")
    from rdflib.collection import Collection

    def named_parents(c):
        for o in full.objects(c, RDFS.subClassOf):
            if isinstance(o, rdflib.URIRef):
                yield o
        for e in full.objects(c, OWL.equivalentClass):
            lst = full.value(e, OWL.intersectionOf)
            if lst is not None:
                for m in Collection(full, lst):
                    if isinstance(m, rdflib.URIRef):
                        yield m

    closure_cat: dict = {}

    def curated_category(c):
        """Breadth-first up the curated closure to the nearest BFO category.

        Deterministic: parents are visited in sorted order and nothing but the
        start node's own answer is cached. A depth-first walk that cached
        every node it passed also cached the dead ends a cycle cut short, so
        the answer depended on rdflib's hash-ordered iteration and two runs
        placed 318 and 325 classes."""
        if c in closure_cat:
            return closure_cat[c]
        frontier, seen, found = [c], {c}, None
        while frontier and found is None:
            nxt = []
            for node in frontier:
                if node in cat_iris:
                    found = cat_iris[node]
                    break
                for pp in sorted(set(named_parents(node)), key=str):
                    if pp not in seen:
                        seen.add(pp); nxt.append(pp)
            frontier = nxt
        closure_cat[c] = found
        return found

    def cat_of(iri):
        if iri in kept_cat:
            return kept_cat[iri]
        if iri in curated:
            got = curated_category(iri)
            if got:
                return got
        n = N(str(cur.value(iri, RDFS.label) or ""))
        # The skeleton does not reach every imported class (FMA `Skin`, CHEBI
        # `Vancomycin`); the category the abstracts gave the same name is the
        # next-best evidence.
        return onto_cat.get(n) or category(n)

    def compatible(child, parent) -> bool:
        """Same branch of BFO: one category is the other's ancestor. `Burn
        Wound` typed `independent continuant` (material and immaterial across
        abstracts) may still go under `Wound`; `Severity Of The Wound` (a
        quality) may not."""
        cc, pc = cat_of(child), cat_of(parent)
        return bool(cc and pc and (pc in ancestors(cc) or cc in ancestors(pc)))

    # candidate edges child -> parent, with their source
    edges: dict[rdflib.URIRef, list[tuple[rdflib.URIRef, str]]] = defaultdict(list)
    for n, c in kept.items():
        words = n.split()
        if any(w in ("of", "in", "with", "for", "on", "at", "after", "by") for w in words):
            continue    # `Presence Of Osteomyelitis`: the head is before the preposition
        for i in range(1, len(words)):
            head = " ".join(words[i:])
            parent = curated_by_label.get(head) or kept.get(head)
            if parent is not None and parent != c:
                edges[c].append((parent, "head noun"))
                break
    refused = {"refused", "different", "same_class", "kept"}
    sc_stats = Counter()
    for row in gt.subsumption_candidates():
        term, canon = row["store term"], row["ontology class"]
        j = gt.peek(term, canon)
        cv = (j.get("curator") or {}).get("verdict")
        v1, v2 = row["pass 1"], row["pass 2"]
        if cv in refused or "different" in (v1, v2):
            continue
        child_n, parent_n = N(row["Class"]), N(row["Parent class"])
        child = kept.get(child_n)
        parent = curated_by_label.get(parent_n) or kept.get(parent_n)
        sc_stats["child kept" if child is not None else "child not kept"] += 1
        sc_stats["parent found" if parent is not None else "parent not found"] += 1
        if child is not None and parent is not None and parent != child:
            edges[child].append((parent, "model subclass candidate"))

    print(f"[split] subclass candidates usable: {dict(sc_stats)}")
    placed: dict[rdflib.URIRef, list[tuple[rdflib.URIRef, str]]] = {}
    rejected_cat = Counter()
    rejected_examples: list = []
    changed = True
    while changed:                      # parents placed first, to a fixed point
        changed = False
        for c, cands in edges.items():
            if c in placed:
                continue
            ok = []
            for parent, src in cands:
                if parent in cat_iris:
                    continue            # a BFO category is not placement
                if not (parent in curated or parent in placed):
                    continue
                if not compatible(c, parent):
                    rejected_cat[src] += 1
                    if len(rejected_examples) < 25:
                        rejected_examples.append(
                            (label[c], cat_of(c), str(label.get(parent) or cur.value(parent, RDFS.label)),
                             cat_of(parent), src))
                    continue
                ok.append((parent, src))
            if ok:
                placed[c] = ok
                changed = True
    candidates = [c for c in kept.values() if c not in placed]
    by_src = Counter(src for v in placed.values() for _, src in v)
    print(f"[split] placed under the curated core: {len(placed):,} "
          f"(edges by source: {dict(by_src)}; refused on category: {dict(rejected_cat)})")
    print(f"[split] unplaced candidates (BFO category only): {len(candidates):,}")
    print(f"[split]   refused on category e.g. {rejected_examples[:25]}")
    top = sorted(placed, key=lambda c: -docs[N(label[c])])[:12]
    print("[split]   placed e.g. " + "; ".join(
        f"{label[c]} < {label.get(placed[c][0][0]) or cur.value(placed[c][0][0], RDFS.label)}"
        f" [{placed[c][0][1]}]" for c in top))
    print("[split]   candidates e.g. " + ", ".join(
        label[c] for c in sorted(candidates, key=lambda c: -docs[N(label[c])])[:15]))
    if not write:
        print("[split] dry run -- nothing written. Pass --write.")
        return 0

    keep_core = set(placed)
    keep_cand = set(candidates)
    allowed = curated | keep_core | keep_cand | set(cat_iris)

    def subgraph(classes, *, base: bool):
        g = rdflib.Graph()
        for pfx, ns in ext.namespaces():
            g.bind(pfx, ns)
        if base:
            for t in cur_ground():
                g.add(t)
        for c in classes:
            for pr, o in ext.predicate_objects(c):
                if pr == RDFS.subClassOf and isinstance(o, rdflib.BNode):
                    f = ext.value(o, OWL.someValuesFrom)
                    if f not in allowed:
                        continue
                    for t in ext.triples((o, None, None)):
                        g.add(t)
                elif pr == RDFS.subClassOf and o not in allowed:
                    continue
                g.add((c, pr, o))
        return g

    def cur_ground():
        base = rdflib.Graph(); base.parse(GT, format="turtle")
        return base

    core = subgraph(keep_core, base=True)
    for c, ps in placed.items():
        for parent, src in ps:
            core.add((c, RDFS.subClassOf, parent))
            ax = rdflib.BNode()
            core.add((ax, RDF.type, OWL.Axiom))
            core.add((ax, OWL.annotatedSource, c))
            core.add((ax, OWL.annotatedProperty, RDFS.subClassOf))
            core.add((ax, OWL.annotatedTarget, parent))
            core.add((ax, prov, rdflib.Literal(f"wound-ontology-pipeline: {src}")))
    cand = subgraph(keep_cand, base=False)
    cand_iri = rdflib.URIRef(NS.rstrip("/") + "/candidates")
    cand.add((cand_iri, RDF.type, OWL.Ontology))
    cand.add((cand_iri, OWL.imports, rdflib.URIRef(NS.rstrip("/"))))
    cand.add((cand_iri, RDFS.comment, rdflib.Literal(
        "Classes the ontology-learning pipeline extracted, kept (in scope, mentioned in "
        f">= {min_abs} abstracts, one category) but not yet placed under a WONT/MILD class. "
        "Each sits under its BFO category only. A class moves to WONT when a placement "
        "step or the curator finds its parent.")))
    for c in keep_cand:
        cand.add((c, rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000114"),
                  rdflib.Literal("candidate, unplaced")))
    (OUT / "wont_extended_core.ttl").write_text(core.serialize(format="turtle"), encoding="utf-8")
    (OUT / "wont_candidates.ttl").write_text(cand.serialize(format="turtle"), encoding="utf-8")
    back_core = rdflib.Graph(); back_core.parse(OUT / "wont_extended_core.ttl", format="turtle")
    back_cand = rdflib.Graph(); back_cand.parse(OUT / "wont_candidates.ttl", format="turtle")
    missing = [c for c in keep_core if (c, RDF.type, OWL.Class) not in back_core]
    missing += [c for c in keep_cand if (c, RDF.type, OWL.Class) not in back_cand]
    if missing:
        raise RuntimeError(f"[split] {len(missing)} class(es) did not read back")
    print(f"[split] written and read back: core {len(back_core):,} triples "
          f"({len(keep_core):,} placed classes + WONT), candidates {len(back_cand):,} "
          f"triples ({len(keep_cand):,} classes)")
    json.dump({"placed": {label[c]: [[str(p_), s] for p_, s in v] for c, v in placed.items()},
               "candidates": sorted(label[c] for c in keep_cand)},
              open(OUT / "split_extension_report.json", "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
