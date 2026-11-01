"""The read relations whose subject is an existing WONT class, for the curator's judgement.

    python -u scripts/withheld_relations_data.py OUT.json

Curator, 2026-10-03, on "82 read relations sit on existing WONT classes and stay
out, because WONT isn't changed": "I wouldn't be categorical. Show these in a UI
for my judgement." The export withholds every axiom on a curated class
(`touch_existing=False`). This collects exactly those relations from the export
itself, resolves both ends to their IRIs, lists the subject's own axioms in WONT,
the abstracts (PMIDs) that state the relation, and whether ELK accepts it: all
of them are added to WONT + the core at once and reasoned over with the import
closure; an unsatisfiable result is pinned to its relation by adding them one at
a time. An accepted relation would go into the WONT addition (the core file
imports nothing new and the ground-truth file stays as it is). Read-only.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

READ = ROOT / "data" / "review" / "relation_universality_2026-10-02" / "result.json"
CORE = ROOT / "output" / "owl" / "wont_extended_core.ttl"


def main(argv: list[str]) -> int:
    import rdflib
    from rdflib.namespace import OWL, RDFS
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL, GROUND_TRUTH_TTL
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.owl.extend import RELATION_IRIS, extend_ground_truth
    from build_wont_core import elk_unsat

    out_path = Path(argv[1])
    axioms = json.loads(READ.read_text(encoding="utf-8"))["axioms"]
    by_triple = {(a["subject"], a["predicate"], a["value"]): a for a in axioms}
    rels = list(by_triple)

    tmp = Path(tempfile.mkdtemp())
    rep = extend_ground_truth(GROUND_TRUTH_TTL, tmp / "probe.ttl", relations=rels, class_edges=[])
    withheld = [t for t in rep.withheld_existing if t[1] != "is_a"]
    print(f"[withheld] {len(rels)} read relations; {len(withheld)} on an existing class")

    # the same relations asserted on the curated classes, to resolve and to reason
    # Resolved and minted against the CORE, which is what the addition is: a
    # value the core already holds resolves to that class, and a new one is
    # minted after the core's last id. Minting from WONT's own counter
    # (2026-10-03, first run) reused ids the core had already given out, and
    # ELK then reasoned about two classes under one IRI.
    rep2 = extend_ground_truth(CORE, tmp / "with.ttl", relations=withheld,
                               class_edges=[], touch_existing=True)
    g2 = rdflib.Graph(); g2.parse(tmp / "with.ttl", format="turtle")
    gt = rdflib.Graph(); gt.parse(str(GROUND_TRUTH_TTL), format="turtle")
    resolved = {**rep2.resolved, **{k: v for k, v in rep2.minted.items()}}
    from wound_ontology.utils.rdf_io import parse_graph
    from wound_ontology.owl.extend import default_lexicon
    labels = {}
    for path in default_lexicon():
        for s, o in parse_graph(Path(path), context="labels").subject_objects(RDFS.label):
            labels.setdefault(s, str(o))
    for s, o in gt.subject_objects(RDFS.label):
        labels[s] = str(o)
    for s, o in g2.subject_objects(RDFS.label):      # the core's own classes
        labels.setdefault(s, str(o))

    def lab(x):
        return labels.get(x) or str(x).rsplit("/", 1)[-1]

    def show(o):
        if isinstance(o, rdflib.URIRef):
            return lab(o)
        p, f = gt.value(o, OWL.onProperty), gt.value(o, OWL.someValuesFrom)
        if p is not None and f is not None:
            return f"{lab(p)} some {show(f)}"
        return "(class expression)"

    # ELK: everything at once over WONT + core + these axioms
    core = rdflib.Graph(); core.parse(CORE, format="turtle")
    combined = g2
    def elk(graph, label):
        """('ok', set()) / ('unsatisfiable', classes) / ('inconsistent', set())."""
        try:
            u = elk_unsat(graph, label=label)
        except RuntimeError as exc:
            if "inconsistent" in str(exc):
                return "inconsistent", set()
            raise
        return ("unsatisfiable", u) if u else ("ok", set())

    status, base = elk(core, "core")
    if status != "ok":
        raise RuntimeError(f"[withheld] the core itself is not clean under ELK ({status}); fix that first")
    together_status, together = elk(combined, "core + withheld relations")
    print(f"[withheld] ELK: core alone clean; with all {len(withheld)} relations: {together_status} "
          f"{len(together) or ''}", flush=True)

    def restriction_triples(s_iri, prop, t_iri):
        for node in g2.objects(s_iri, RDFS.subClassOf):
            if isinstance(node, rdflib.BNode) and g2.value(node, OWL.onProperty) == prop \
                    and g2.value(node, OWL.someValuesFrom) == t_iri:
                return [(s_iri, RDFS.subClassOf, node), *g2.triples((node, None, None))]
        return []

    store_keys = {}
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    want = {(s, f"{pr}: {t}") for s, pr, t in withheld}
    for key, ents in p.store.view():
        for s, attrs in ents.items():
            for t, v in attrs.items():
                if v == 1.0 and (s, t) in want:
                    store_keys.setdefault((s, t), set()).add(key)

    rows = []
    for i, (s, pr, t) in enumerate(sorted(withheld, key=lambda x: (x[0].lower(), x[1], x[2].lower()))):
        a = by_triple[(s, pr, t)]
        s_iri = rdflib.URIRef(resolved.get(s) or "")
        t_iri = rdflib.URIRef(resolved.get(t) or "")
        prop = rdflib.URIRef(RELATION_IRIS[pr])
        existing = [show(o) for o in gt.objects(s_iri, RDFS.subClassOf)] + \
                   [("≡ " + show(o)) for o in gt.objects(s_iri, OWL.equivalentClass)]
        same_already = any(gt.value(o, OWL.onProperty) == prop and gt.value(o, OWL.someValuesFrom) == t_iri
                           for o in gt.objects(s_iri, RDFS.subClassOf) if isinstance(o, rdflib.BNode))
        verdict = "ok"
        if together_status != "ok":
            one = rdflib.Graph(); one += core
            for tr in restriction_triples(s_iri, prop, t_iri):
                one.add(tr)
            st, bad = elk(one, f"row {i}")
            if st == "inconsistent":
                verdict = "inconsistent: with this axiom WONT's individuals cannot exist"
            elif st == "unsatisfiable":
                verdict = "unsatisfiable: " + ", ".join(sorted(lab(x) for x in bad))[:300]
            print(f"[withheld]   {i + 1}/{len(withheld)} {s} {pr} {t}: {verdict[:60]}", flush=True)
        rows.append({
            "id": f"w{i:03d}", "subject": s, "subject_label": lab(s_iri), "subject_iri": str(s_iri),
            "predicate": pr.replace("_", " "), "property_iri": str(prop),
            "value": t, "value_label": lab(t_iri) if str(t_iri) in rep2.resolved.values() else t,
            "value_iri": str(t_iri), "value_is_new": t in rep2.minted,
            "abstracts": a["abstracts"], "pmids": sorted(store_keys.get((s, f"{pr}: {t}"), ())),
            "note": a.get("note", ""), "existing_axioms": existing, "already_in_wont": same_already,
            "elk": verdict,
        })
    out = {"made": "2026-10-03", "rows": rows,
           "elk_all_together": together_status}
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(back["rows"]) == len(withheld)
    from collections import Counter
    print(f"[withheld] written and read back: {out_path} -- {len(rows)} rows; "
          f"{Counter(r['predicate'] for r in rows)}; already in WONT {sum(r['already_in_wont'] for r in rows)}; "
          f"new value classes {sum(r['value_is_new'] for r in rows)}; ELK {Counter(r['elk'][:5] for r in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
