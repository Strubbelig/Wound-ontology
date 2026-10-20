"""Measure release filters on the extended WONT, before any is applied. Read-only.

    python scripts/measure_extension_filters.py

For every class the extension minted it records: how it got there (an
extracted term, or only ever the TARGET of a relation), its scope decision and
who made it, how many abstracts mention it, whether its typings agree, and
whether its superclass chain reaches a curated WONT/MILD class or stops at an
upper-level category (`process`, `information entity` ...). Then it counts what
each candidate filter, and their combination, would keep.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

EXT = ROOT / "output" / "owl" / "wont_extended.ttl"
GT = ROOT / "data" / "ground truth" / "ground_truth_final.owl"
MILD = ROOT.parent / "Disease ontologies" / "mild.ttl"
NS = "https://bioportal.bioontology.org/ontologies/WONT/"
PROV = "http://www.geneontology.org/formats/oboInOwl#source"


def main() -> int:
    import rdflib
    from rdflib.namespace import OWL, RDF, RDFS

    from wound_ontology.llm.extraction_models import CATEGORY_IRI
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import normalize_term as N

    ext = rdflib.Graph(); ext.parse(EXT, format="turtle")
    cur = rdflib.Graph(); cur.parse(GT, format="turtle"); cur.parse(MILD, format="turtle")
    curated = {s for s in cur.subjects(RDF.type, OWL.Class) if isinstance(s, rdflib.URIRef)}
    categories = {rdflib.URIRef(i) for i in CATEGORY_IRI.values()}
    anchors = curated - categories
    minted = [s for s in ext.subjects(rdflib.URIRef(PROV), None)]
    label = {s: str(ext.value(s, RDFS.label) or "") for s in minted}
    parents = defaultdict(set)
    for s, o in ext.subject_objects(RDFS.subClassOf):
        if isinstance(o, rdflib.URIRef):
            parents[s].add(o)

    # A restriction on the minted class whose filler is a curated class: the
    # only other way a term is tied to the curated core, since the text's is_a
    # edges are all stage-1 typings (term -> BFO category).
    linked = defaultdict(set)
    for s_, node in ext.subject_objects(RDFS.subClassOf):
        if isinstance(node, rdflib.BNode):
            f = ext.value(node, OWL.someValuesFrom)
            if f in anchors:
                linked[s_].add(str(ext.value(f, RDFS.label) or cur.value(f, RDFS.label) or f))
    placed_cache: dict = {}

    def placed(c, seen=None) -> bool:
        """Does the chain reach a curated class that is not an upper-level category?"""
        if c in placed_cache:
            return placed_cache[c]
        seen = seen or set()
        if c in anchors:
            return True
        if c in seen:
            return False
        seen.add(c)
        ok = any(placed(pp, seen) for pp in parents.get(c, ()) if pp not in categories)
        placed_cache[c] = ok
        return ok

    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    ent_docs: Counter = Counter(); tgt_docs: Counter = Counter()
    typings: dict[str, set[str]] = defaultdict(set)
    for _, ents in p.store.view():
        seen_t = set()
        for name, attrs in ents.items():
            ent_docs[N(name)] += 1
            for triple in attrs:
                pred, _, t = triple.partition(":")
                if pred.strip() == "is_a":
                    typings[N(name)].add(t.strip())
                else:
                    seen_t.add(N(t.strip()))
        for t in seen_t:
            tgt_docs[t] += 1
    name_of = {}
    for _, ents in p.store.view():
        for name in ents:
            name_of.setdefault(N(name), name)

    rows = []
    for c in minted:
        k = N(label[c])
        name = name_of.get(k, label[c])
        verdict, source = gt.effective_gate_verdict(gt.resolve(name))
        cats = typings.get(k, set())
        lcc = p.reasoner_gate.least_common_category(cats) if len(cats) > 1 else (next(iter(cats)) if cats else None)
        rows.append({
            "label": label[c],
            "entity": ent_docs[k] > 0,
            "abstracts": ent_docs[k],
            "as target": tgt_docs[k],
            "scope": verdict or "undecided",
            "scope source": source or "-",
            "typed": bool(cats),
            "consistent": lcc is not None,
            "placed": placed(c),
            "linked": bool(linked.get(c)),
            "words": len(label[c].split()),
        })

    def count(pred) -> tuple[int, list[str]]:
        hit = [r for r in rows if pred(r)]
        hit.sort(key=lambda r: -(r["abstracts"] + r["as target"]))
        return len(hit), [r["label"] for r in hit[:8]]

    out = {"minted": len(rows)}
    print(f"[filters] {len(rows):,} minted classes in {EXT.name}")
    print(f"[filters] scope of the minted: {dict(Counter((r['scope'], r['scope source']) for r in rows).most_common())}")
    for name, pred in [
        ("extracted as a term (not only a relation target)", lambda r: r["entity"]),
        ("only ever a relation target", lambda r: not r["entity"]),
        ("scope decided 'in'", lambda r: r["scope"] == "in"),
        ("scope undecided", lambda r: r["scope"] == "undecided"),
        ("F1 placed under a curated WONT/MILD class", lambda r: r["placed"]),
        ("   ...stops at an upper-level category only", lambda r: r["entity"] and not r["placed"]),
        ("L  related to a curated class by a restriction", lambda r: r["linked"]),
        ("L  ...and an extracted term, in scope, >= 2 abstracts, consistent",
         lambda r: r["linked"] and r["entity"] and r["scope"] == "in" and r["abstracts"] >= 2 and r["consistent"]),
        ("F2 mentioned in >= 2 abstracts", lambda r: r["abstracts"] >= 2),
        ("   ...extracted term, in scope, >= 2 abstracts, consistent (no placement test)",
         lambda r: r["entity"] and r["scope"] == "in" and r["abstracts"] >= 2 and r["consistent"]),
        ("   ...same, >= 3 abstracts",
         lambda r: r["entity"] and r["scope"] == "in" and r["abstracts"] >= 3 and r["consistent"]),
        ("   ...same, >= 5 abstracts",
         lambda r: r["entity"] and r["scope"] == "in" and r["abstracts"] >= 5 and r["consistent"]),
        ("F3 consistently typed", lambda r: r["entity"] and r["consistent"]),
        ("   ...inconsistently typed", lambda r: r["entity"] and r["typed"] and not r["consistent"]),
        ("F0+F1+F2+F3 (term, in scope, placed, >=2, consistent)",
         lambda r: r["entity"] and r["scope"] == "in" and r["placed"] and r["abstracts"] >= 2 and r["consistent"]),
        ("same, but >= 1 abstract",
         lambda r: r["entity"] and r["scope"] == "in" and r["placed"] and r["consistent"]),
        ("same, but undecided scope allowed",
         lambda r: r["entity"] and r["scope"] in ("in", "undecided") and r["placed"] and r["abstracts"] >= 2 and r["consistent"]),
    ]:
        n, ex = count(pred)
        out[name] = n
        print(f"[filters] {n:>7,}  {name}   e.g. {ex}")
    kept = [r for r in rows if r["entity"] and r["scope"] == "in"
            and r["abstracts"] >= 2 and r["consistent"]]
    print(f"[filters] of in-scope/>=2/consistent terms, one-word labels: {sum(r['words'] == 1 for r in kept)}  "
          f"e.g. {[r['label'] for r in sorted(kept, key=lambda r: -r['abstracts']) if r['words'] == 1][:15]}")
    (ROOT / "output" / "extension_filters_2026-09-28.json").write_text(
        json.dumps({"counts": out, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
