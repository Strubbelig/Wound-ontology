"""Measure every figure the thesis reports, from the files, in one run. Read-only.

The thesis results chapter cites this script's output rather than numbers
copied out of logs (rule 15: measured, not estimated). Re-run it after every
rebuild; the output is dated, so the figures a chapter quotes can be traced to
the run that produced them.

    python scripts/thesis_figures.py            # writes output/thesis_figures_<date>.json/.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from config.settings import GROUND_TRUTH_TTL as WONT   # the current WONT file (dated since 2026-10-20)
from config.settings import MILD_TTL as MILD   # the current MILD file (dated since 2026-10-20)
WONT_NS = "https://bioportal.bioontology.org/ontologies/WONT/"
MILD_NS = "https://bioportal.bioontology.org/ontologies/MILD/"


def _names(view) -> Counter:
    c: Counter = Counter()
    for _, ents in view:
        c.update(ents.keys())
    return c


def corpus(p) -> dict:
    from config.pubmed_query_list import PUBMED_SEARCH
    df = p.dm.load_latest_csv("pubmed_abstracts")
    col = next((c for c in df.columns if c.lower() == "pmid"), None)
    raw = p.store.dict
    typing, relation, categories, predicates = 0, 0, Counter(), Counter()
    names = Counter()
    for rec in raw.values():
        for name, attrs in rec.get("entities", {}).items():
            names[name] += 1
            for triple in attrs:
                pred, _, tgt = triple.partition(":")
                predicates[pred.strip()] += 1
                if pred.strip() == "is_a":
                    typing += 1
                    categories[tgt.strip()] += 1
                else:
                    relation += 1
    return {
        "queries": len(PUBMED_SEARCH),
        "abstract rows fetched": int(len(df)),
        "unique PMIDs fetched": int(df[col].nunique()) if col else None,
        "abstracts in evidence store": len(raw),
        "term occurrences (entity records)": sum(names.values()),
        "distinct strings as extracted": len(names),
        "typing assertions": typing,
        "relation assertions": relation,
        "typing by category": dict(categories.most_common()),
        "assertions by predicate": dict(predicates.most_common()),
    }


def register(terms) -> dict:
    recs = terms.records
    aliases = {t: r for t, r in recs.items() if r.get("spelling")}
    alias_by = Counter(r["spelling"].get("by") for r in aliases.values())
    live = terms.data
    methods = Counter(r.get("method") for t, r in recs.items() if t in live)
    retired = sum(1 for r in recs.values() if r.get("retired"))
    pv = {k: Counter() for k in ("pass1", "pass2", "curator")}
    agree = Counter()
    n_pairs = 0
    for r in recs.values():
        for pair in (r.get("pairs") or {}).values():
            n_pairs += 1
            for k in pv:
                if isinstance(pair.get(k), dict):
                    pv[k][pair[k].get("verdict")] += 1
            a, b = (pair.get("pass1") or {}).get("verdict"), (pair.get("pass2") or {}).get("verdict")
            if a and b:
                agree["agree" if a == b else "disagree"] += 1
    scope = Counter()
    for r in recs.values():
        for src, v in (r.get("gate") or {}).items():
            if isinstance(v, dict):
                scope[f"{src}: {v.get('verdict')}"] += 1
    return {
        "records": len(recs),
        "spelling aliases": len(aliases),
        "spelling aliases by author": dict(alias_by.most_common()),
        "live synonym mappings": len(live),
        "distinct preferred terms mapped onto": len(set(live.values())),
        "live mappings by method": dict(methods.most_common()),
        "retired mappings (kept on record)": retired,
        "adjudicated term pairs": n_pairs,
        "pair verdicts, first adjudication": dict(pv["pass1"].most_common()),
        "pair verdicts, second adjudication": dict(pv["pass2"].most_common()),
        "pair verdicts, curator": dict(pv["curator"].most_common()),
        "first vs second adjudication": dict(agree),
        "scope verdicts by source": dict(sorted(scope.items())),
        "contested scope records": sum(1 for r in recs.values() if r.get("gate_contested")),
    }


def resolution(p) -> dict:
    st, terms = p.store, p.term_mapper._term_mapping
    spelled = _names(st.view(mapped=False, include_rejected=True))
    mapped = _names(st.view(mapped=True, include_rejected=True))
    kept = _names(st.view())
    decided = Counter()
    for n in spelled:
        v, src = terms.effective_gate_verdict(n)
        decided[f"{src}: {v}" if v else "no scope verdict"] += 1
    return {
        "distinct names after spelling resolution": len(spelled),
        "distinct names after synonym resolution": len(mapped),
        "distinct names retained (in scope, not rejected)": len(kept),
        "occurrences retained": sum(kept.values()),
        "spelling-resolved names by deciding scope source": dict(decided.most_common()),
    }


def ontology(path: Path, ns: str) -> dict:
    import rdflib
    from rdflib.namespace import OWL, RDF, RDFS
    g = rdflib.Graph(); g.parse(path, format="turtle")
    iao = rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000115")
    alt = rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000118")
    own = lambda s: isinstance(s, rdflib.URIRef) and str(s).startswith(ns)
    cls = [s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, rdflib.URIRef)]
    mine = [c for c in cls if own(c)]
    props = [s for s in g.subjects(RDF.type, OWL.ObjectProperty)]
    foreign = Counter(str(c).rsplit("/", 1)[-1].split("_")[0] for c in cls if not own(c))
    return {
        "triples": len(g),
        "classes declared": len(cls),
        "own classes": len(mine),
        "imported classes referenced": len(cls) - len(mine),
        "imported classes by source": dict(foreign.most_common()),
        "own individuals": sum(1 for s in g.subjects(RDF.type, OWL.NamedIndividual) if own(s)),
        "object properties referenced": len(props),
        "own object properties": sum(map(own, props)),
        "own classes with textual definition": sum(1 for c in mine if (c, iao, None) in g),
        "own classes with alternative term": sum(1 for c in mine if (c, alt, None) in g),
        "own classes with equivalence axiom": sum(1 for c in mine if (c, OWL.equivalentClass, None) in g),
        "own classes with an existential restriction as superclass": sum(
            1 for c in mine if any(isinstance(o, rdflib.BNode) for o in g.objects(c, RDFS.subClassOf))),
        "disjointness axioms": len(list(g.triples((None, OWL.disjointWith, None)))),
    }


def competency() -> dict:
    d = json.loads((ROOT / "config" / "competency_questions.json").read_text(encoding="utf-8"))
    themes = d["clinical_themes"]
    return {
        "themes": len(themes),
        "in scope": sum(len(t.get("in_scope", [])) for t in themes),
        "declared out of scope (thematic)": sum(len(t.get("out_of_scope", [])) for t in themes),
        "declared out of scope (global)": len(d.get("global_out_of_scope", [])),
        "rewritten after curator ruling": sum(1 for t in themes for q in t.get("in_scope", [])
                                              if q.get("rewrite")),
    }


def main() -> int:
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator()
    fig = {
        "measured": datetime.now().isoformat(timespec="seconds"),
        "corpus": corpus(p),
        "term register": register(p.term_mapper._term_mapping),
        "resolution": resolution(p),
        "WONT": ontology(WONT, WONT_NS),
        "MILD": ontology(MILD, MILD_NS),
        "competency questions": competency(),
    }
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out = ROOT / "output" / f"thesis_figures_{stamp}.json"
    out.write_text(json.dumps(fig, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Thesis figures, measured {fig['measured']}", ""]
    for section, vals in fig.items():
        if not isinstance(vals, dict):
            continue
        lines += [f"## {section}", "", "| figure | value |", "|---|---|"]
        for k, v in vals.items():
            v = ", ".join(f"{a} {b:,}" if isinstance(b, int) else f"{a} {b}"
                          for a, b in list(v.items())[:30]) if isinstance(v, dict) else (
                f"{v:,}" if isinstance(v, int) else v)
            lines.append(f"| {k} | {v} |")
        lines.append("")
    out.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    json.loads(out.read_text(encoding="utf-8"))                 # read back
    print(f"[thesis_figures] written and read back: {out.name} (+ .md)")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
