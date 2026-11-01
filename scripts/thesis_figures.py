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
    """The term dict by its five questions (rule 89): for each, the judgement
    that counts -- its verdict and its agent -- and how many judgements each
    agent made in all."""
    from wound_ontology.mappers.judgements import ABSTAIN, current
    from wound_ontology.mappers.term_mapping_and_gate import SPELLING_AGENTS, edge_judgements, split_of
    recs = terms.records
    by_agent: Counter = Counter()
    for r in recs.values():
        for q, v in r.items():
            for js in ([v] if isinstance(v, list) else v.values()):
                by_agent.update(j["by"] for j in js)

    kind, name_by = Counter(), Counter()
    for t, r in recs.items():
        j = current(r.get("name"))
        if split_of(r):
            kind["split by category"] += 1
        elif j and isinstance(j["verdict"], str) and j["verdict"] != t:
            kind["under another name"] += 1
            name_by[j["by"]] += 1
        else:
            kind["its own name"] += 1

    n_pairs, pair_v, pair_by = 0, Counter(), Counter()
    for r in recs.values():
        for js in (r.get("pairs") or {}).values():
            n_pairs += 1
            if (j := current(js)):
                pair_v[j["verdict"]] += 1
                pair_by[j["by"]] += 1

    scope_v, scope_by, abstained = Counter(), Counter(), 0
    for r in recs.values():
        js = r.get("scope") or []
        if (j := current(js)):
            scope_v[j["verdict"]] += 1
            scope_by[f"{j['by']}: {j['verdict']}"] += 1
        elif js and all(x["verdict"] == ABSTAIN for x in js):
            abstained += 1

    placed, placed_by, refused, edge_no = 0, Counter(), Counter(), Counter()
    for r in recs.values():
        for tgt, js in (r.get("is_a") or {}).items():
            j = current(js)
            if j and j["verdict"] == "yes" and any(x.get("iri") for x in js):
                placed += 1
                placed_by[j["by"]] += 1
            elif j and j["verdict"] == "no" and j.get("iri"):
                refused[j["by"]] += 1
            if (e := current(edge_judgements(js))) and e["verdict"] == "no" and not e.get("iri"):
                edge_no[e["by"]] += 1

    cats = terms.categories()          # the class's own reading of a decided category
    categories, cat_by = len(cats), Counter(c["by"] for c in cats.values())
    rel_v = Counter()
    for r in recs.values():
        for js in (r.get("relations") or {}).values():
            if (j := current(js)):
                rel_v[f"{j['by']}: {j['verdict']}"] += 1
    return {
        "records": len(recs),
        "judgements by agent": dict(by_agent.most_common()),
        "name: strings": dict(kind),
        "name: the name that counts, by agent": dict(name_by.most_common()),
        "name: spellings (string rewritten)": sum(n for a, n in name_by.items() if a in SPELLING_AGENTS),
        "name: mappings (another concept's name)": sum(n for a, n in name_by.items() if a not in SPELLING_AGENTS),
        "pairs": n_pairs,
        "pairs: verdict that counts": dict(pair_v.most_common()),
        "pairs: by agent": dict(pair_by.most_common()),
        "scope: verdict that counts": dict(scope_v.most_common()),
        "scope: by agent and verdict": dict(scope_by.most_common()),
        "scope: only abstentions": abstained,
        "is_a: placements under an ontology class": placed,
        "is_a: placements by agent": dict(placed_by.most_common()),
        "is_a: placements refused, by agent": dict(refused.most_common()),
        "is_a: categories decided": categories,
        "is_a: categories by agent": dict(cat_by.most_common()),
        "is_a: edges refused, by agent": dict(edge_no.most_common()),
        "relations: by agent and verdict": dict(rel_v.most_common()),
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
