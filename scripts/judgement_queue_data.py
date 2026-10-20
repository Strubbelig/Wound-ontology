"""Everything in the WONT addition that waits for the curator's judgement, as one list.

    python -u scripts/judgement_queue_data.py OUT.json

Curator, 2026-10-05, on the 44 relations on new classes ("have i ever reviewed
these?" -- no, only Claude had read them): "make the page yes. and everything
else that could be worth my judgement should be in this ui too". Sections:

  relations   relations from the abstracts on new classes, held out of the
              build until decided (rule 72); abstracts, Claude's reading, and
              ELK on all of them added at once (then one by one if that fails)
  duplicates  new classes whose name is a label or exact synonym of a class
              that already exists (WONT, MILD or an imported ontology)
  parents     new classes that are not added because their parent has no
              checked parent itself; grouped by that parent
  conflicts   terms whose every parent the reasoner found contradictory
  fillers     classes added only because a curator axiom names them; they
              have a BFO type but no checked parent
  wont        parents the abstracts suggest for classes that already exist in
              WONT or MILD and that they do not have yet -- notes for the next
              WONT revision; WONT itself is not changed
  clashes     statements from the abstracts that the reasoner found contradict
              each other (rule 76), from the latest
              data/review/relation_clashes_*.json: a term said to be two kinds
              of thing at once, or a statement that needs its target to be a
              kind the target's own statements say it is not. All are held out
              now; the curator says which side is wrong.

Read-only on the pipeline: it writes OUT.json and nothing else.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

OWL_DIR = ROOT / "output" / "owl"
READ = ROOT / "data" / "review" / "relation_universality_2026-10-02" / "result.json"
CURATOR = ROOT / "data" / "review" / "curator_axioms_2026-10-03.json"
from config.settings import MILD_TTL as MILD   # the current MILD file (dated since 2026-10-20)
OBO = "http://purl.obolibrary.org/obo/"
PLAIN = {OBO + "RO_0000057": "has participant", OBO + "RO_0002233": "has input", OBO + "RO_0002234": "has output",
         OBO + "IAO_0000136": "is about", OBO + "BFO_0000050": "part of", OBO + "BFO_0000051": "has part",
         OBO + "RO_0000086": "has quality", OBO + "RO_0000052": "inheres in", OBO + "RO_0000053": "has characteristic",
         OBO + "RO_0000091": "has disposition", OBO + "RO_0000085": "has function", OBO + "RO_0000056": "participates in"}
SYN = ["http://www.w3.org/2000/01/rdf-schema#label", OBO + "IAO_0000118",
       "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"]


def main(argv: list[str]) -> int:
    import rdflib
    from rdflib import BNode, OWL, RDF, RDFS, URIRef
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL, GROUND_TRUTH_TTL
    from wound_ontology.orchestrator import Orchestrator, PLACEMENT_MIN_ABSTRACTS
    from wound_ontology.owl.extend import default_lexicon
    from wound_ontology.utils.normalise import normalise
    from wound_ontology.utils.rdf_io import parse_graph
    from build_wont_core import elk_unsat

    K = lambda s: normalise(str(s)).strict  # noqa: E731
    out_path = Path(argv[1])
    rep = json.loads((OWL_DIR / "core_build_report.json").read_text(encoding="utf-8"))
    held = rep["relations held for the curator (list)"]
    core = rdflib.Graph().parse(OWL_DIR / "wont_extended_core.ttl")
    ext = rdflib.Graph().parse(OWL_DIR / "wont_extended.ttl")
    gt = rdflib.Graph().parse(str(GROUND_TRUTH_TTL), format="turtle")
    mild = rdflib.Graph().parse(MILD, format="turtle")
    ids = json.loads((ROOT / "data" / "registry" / "wont_ids.json").read_text(encoding="utf-8"))["entries"]
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    tdict = p.term_mapper._term_mapping

    # who says what: label and synonyms of every existing class, by source
    names: dict[str, list[tuple[str, str, str]]] = defaultdict(list)   # key -> (iri, label, source)
    labels: dict = {}

    def harvest(g, source):
        for s, pr, o in g.triples((None, None, None)):
            if str(pr) in SYN and isinstance(s, URIRef):
                if pr == RDFS.label:
                    labels.setdefault(s, str(o))
                names[K(o)].append((str(s), str(o), source))
    harvest(gt, "WONT"); harvest(mild, "MILD")
    for path in default_lexicon():
        if Path(path).resolve() != MILD.resolve():
            harvest(parse_graph(Path(path), context="judgement names"), Path(path).stem.replace("_module", "").upper())
    for s, o in core.subject_objects(RDFS.label):
        labels.setdefault(s, str(o))
    for s, o in ext.subject_objects(RDFS.label):
        labels.setdefault(s, str(o))
    lab = lambda x: labels.get(URIRef(str(x))) or str(x).rsplit("/", 1)[-1]  # noqa: E731
    new_classes = {s for s in core.subjects(RDF.type, OWL.Class) if str(s) in ids}
    gt_classes = set(gt.subjects(RDF.type, OWL.Class))

    def bfo_type(c):
        for o in core.objects(c, RDFS.subClassOf):
            if isinstance(o, URIRef) and "BFO_" in str(o):
                return lab(o)
        return ""

    def parents(g, c):
        return [lab(o) for o in g.objects(c, RDFS.subClassOf) if isinstance(o, URIRef) and "BFO_" not in str(o)]

    items = []

    # ---- relations on new classes
    seen_view = {}
    for key, ents in p.store.view():
        for s, attrs in ents.items():
            for t, v in attrs.items():
                if v == 1.0 and ":" in t:
                    pr, _, val = t.partition(":")
                    seen_view.setdefault((K(s), pr.strip(), K(val.strip())), set()).add(key)
    resolve = p.store.resolver(mapped=True)
    reading = {}
    for a in json.loads(READ.read_text(encoding="utf-8"))["axioms"]:
        s, v = resolve(a["subject"])[1], resolve(a["value"])[1]
        reading.setdefault((K(s), a["predicate"], K(v)), []).append(a)
    from wound_ontology.owl.extend import RELATION_IRIS
    pred_of_iri = {iri: pr for pr, iri in RELATION_IRIS.items()}

    elk_all = elk_unsat(_with(core, held, rdflib), label="core + all held relations")
    print(f"[queue] ELK, all {len(held)} held relations added at once: {len(elk_all)} unsatisfiable", flush=True)
    # Which relation is to blame: first the ones on a class ELK named, each
    # alone; if the rest together are then clean, nobody else is tested.
    bad: dict[int, set] = {}
    if elk_all:
        named = {str(x) for x in elk_all}
        suspects = [i for i, h in enumerate(held) if h["subject_iri"] in named]
        for i in suspects:
            u = elk_unsat(_with(core, [held[i]], rdflib), label=f"held relation {i}")
            if u:
                bad[i] = u
        rest = [h for i, h in enumerate(held) if i not in bad]
        if elk_unsat(_with(core, rest, rdflib), label="the other held relations"):
            for i, h in enumerate(held):
                if i not in bad:
                    u = elk_unsat(_with(core, [h], rdflib), label=f"held relation {i}")
                    if u:
                        bad[i] = u
        print(f"[queue] ELK pins the contradiction on {len(bad)} relation(s)", flush=True)
    for i, h in enumerate(held):
        pr = pred_of_iri.get(h["property_iri"], "")
        k = (K(h["subject"]), pr, K(h["value"]))
        reads = reading.get(k, [])
        if not reads:
            # the export resolved the value through an existing class's label or
            # synonym ("burn wound" -> Thermal wound): match on subject and
            # relation, and only when exactly one written value is left over
            others = {K(o["value"]) for o in held if o is not h and K(o["subject"]) == k[0]
                      and o["property_iri"] == h["property_iri"]}
            cands = {kk: v for kk, v in reading.items() if kk[0] == k[0] and kk[1] == pr and kk[2] not in others}
            if len(cands) == 1:
                k = next(iter(cands)); reads = cands[k]
        pm = sorted(seen_view.get(k, ()))
        flags = []
        if K(h["subject"]) == K(h["value"]):
            flags.append("points at itself")
        if not reads:
            raise RuntimeError(f"[queue] held relation {h} matches no read relation -- cannot show its evidence")
        elk = "no contradiction"
        if i in bad:
            elk = "contradiction: " + ", ".join(sorted(lab(x) for x in bad[i]))[:200]
        if elk != "no contradiction":
            flags.append("reasoner finds a contradiction")
        items.append({
            "id": f"r{i:03d}", "section": "relations",
            "subject": h["subject"], "predicate": PLAIN.get(h["property_iri"], pr.replace("_", " ")),
            "value": h["value"], "key": f"{h['subject'].lower()}|{h['property_iri']}|{h['value'].lower()}",
            "abstracts": max(a["abstracts"] for a in reads), "pmids": pm,
            "reading": "; ".join(sorted({a["note"] for a in reads if a.get("note")})),
            "as_written": sorted({f"{a['subject']} {a['predicate'].replace('_', ' ')} {a['value']}" for a in reads}),
            "subject_parents": parents(core, URIRef(h["subject_iri"])),
            "elk": elk, "flags": flags,
        })

    # ---- clashes: statements the reasoner found contradict each other (rule 76)
    clash_files = sorted(glob.glob(str(ROOT / "data" / "review" / "relation_clashes_*.json")))
    if not clash_files:
        print("[queue] *** no data/review/relation_clashes_*.json: the clashes section is EMPTY ***")
    else:
        from wound_ontology.llm.extraction_adapter import normalize_predicate
        clashes = json.loads(Path(clash_files[-1]).read_text(encoding="utf-8"))["causes"]
        # These statements are held back right now, i.e. rejected in the view;
        # their abstracts are read with the rejected cells included.
        held_view = {}
        for key, ents in p.store.view(include_rejected=True):
            for s_, attrs in ents.items():
                for t, v in attrs.items():
                    if v == 1.0 and ":" in t:
                        pr, _, val = t.partition(":")
                        held_view.setdefault((K(s_), pr.strip(), K(val.strip())), set()).add(key)

        def ev(subj, pred, obj):
            return sorted(held_view.get((K(subj), normalize_predicate(pred), K(obj)), ()))

        def said(subj, pred, obj):
            pm = ev(subj, pred, obj)
            if not pm:
                raise RuntimeError(f"[queue] clash statement {subj!r} {pred} {obj!r} is in no abstract")
            return {"value": obj, "pmids": pm}

        for c in clashes:
            if c["kind"] == "two kinds":
                common = set.intersection(*(set(x) for x in c["clashing"]))
                one = sorted(common)[0] if common else None
                sides = ([[one], sorted(set(c["groups"]) - {one})] if one
                         else [sorted(c["groups"]), []])
                items.append({
                    "id": f"k{len(items):03d}", "section": "clashes", "kind": "two kinds",
                    "subject": c["subject"], "key": f"two kinds|{c['subject'].lower()}",
                    "sides": [[{"predicate": q, "kind": DOMAIN_KIND[q],
                                "said": [said(c["subject"], q, o) for o in c["groups"][q]]}
                               for q in side] for side in sides if side],
                })
            else:
                s_, q_, o_ = c["subject"], c["predicate"], c["object"]
                items.append({
                    "id": f"t{len(items):03d}", "section": "clashes", "kind": "target",
                    "subject": s_, "predicate": q_, "value": o_,
                    "key": f"target|{s_.lower()}|{q_}|{o_.lower()}",
                    "pmids": ev(s_, q_, o_), "needs": RANGE_KIND[q_],
                    "blamed": [{"predicate": b, "kind": DOMAIN_KIND[b],
                                "said": [said(o_, b, v) for pb, v in c["target_statements"] if pb == b]}
                               for b in c["target_blamed"]],
                })
        print(f"[queue] clashes from {Path(clash_files[-1]).name}: {len(clashes)}")

    # ---- duplicates: a new class named like an existing one
    for c in sorted(new_classes, key=lambda x: lab(x).lower()):
        hits = [h for h in names.get(K(lab(c)), []) if URIRef(h[0]) not in new_classes and h[0] != str(c)]
        hits = list({h[0]: h for h in hits}.values())
        if hits:
            items.append({"id": f"d{len(items):03d}", "section": "duplicates", "subject": lab(c),
                          "iri": str(c).rsplit("/", 1)[-1], "bfo": bfo_type(c), "parents": parents(core, c),
                          "matches": [{"label": lab(h[0]) if URIRef(h[0]) in labels else h[1], "said": h[1],
                                       "source": h[2], "iri": h[0].rsplit("/", 1)[-1]} for h in hits]})

    # ---- placed terms that are not added, and why (as in the figure)
    seen = {}
    for _, ents in p.store.view():
        for e in ents:
            seen[e] = seen.get(e, 0) + 1
    kept = [(t, c) for t, c in tdict.placements() if seen.get(t, 0) >= PLACEMENT_MIN_ABSTRACTS]
    core_keys = {K(lab(c)) for c in new_classes}
    hier_parents = {}
    for child in p.class_hier.df.index:
        for par in p.class_hier.parents_of(child):
            if child != par and p.class_hier.source_of(child, par) == "placed":
                hier_parents.setdefault(K(child), []).append(str(par))
    q = json.load(open(max(glob.glob(str(ROOT / "output" / "quarantine" / "edges_*.json")), key=os.path.getmtime)))
    quarantined = {(K(a), K(b)) for a, b in q["edges"]}
    wont_or_mild = {}
    for g, src in ((gt, "WONT"), (mild, "MILD")):
        for s, o in g.subject_objects(RDFS.label):
            wont_or_mild.setdefault(K(o), (s, src, g))
    blocked = defaultdict(list)
    minted_keys = {K(o) for s, o in ext.subject_objects(RDFS.label) if str(s) in ids}
    terms = {}
    for t, c in kept:
        terms.setdefault(K(t), (t, []))[1].append(c)
    for k, (t, pars) in sorted(terms.items()):
        if k in core_keys:
            continue
        if k not in hier_parents and all((k, K(c)) in quarantined for c in pars):
            items.append({"id": f"c{len(items):03d}", "section": "conflicts", "subject": t, "parents": pars,
                          "abstracts": seen.get(t, 0)})
            continue
        if k in wont_or_mild:
            s_iri, src, g = wont_or_mild[k]
            have = {K(x) for x in _ancestor_labels(g, s_iri, labels)}
            new = [c for c in pars if K(c) not in have and K(c) != k]
            if new:
                items.append({"id": f"w{len(items):03d}", "section": "wont", "subject": lab(s_iri), "source": src,
                              "iri": str(s_iri).rsplit("/", 1)[-1], "suggested": new,
                              "has": [lab(o) for o in g.objects(s_iri, RDFS.subClassOf) if isinstance(o, URIRef)],
                              "abstracts": seen.get(t, 0)})
            continue
        if k not in minted_keys:
            continue            # resolved to an existing (imported) class, nothing waits
        for par in hier_parents.get(k, []):
            if K(par) not in core_keys and K(par) not in wont_or_mild:
                blocked[par].append(t)
    for par, kids in sorted(blocked.items(), key=lambda x: (-len(x[1]), x[0].lower())):
        pi = next((s for s, o in ext.subject_objects(RDFS.label) if K(o) == K(par)), None)
        items.append({"id": f"p{len(items):03d}", "section": "parents", "subject": par,
                      "children": sorted(kids, key=str.lower), "bfo": bfo_type(pi) if pi is not None else "",
                      "now_under": parents(ext, pi) if pi is not None else []})

    # ---- classes that are in only because a curator axiom names them
    cur = json.loads(CURATOR.read_text(encoding="utf-8"))["axioms"]
    placed_keys = {K(t) for t, _ in kept}
    for c in sorted(new_classes, key=lambda x: lab(x).lower()):
        if K(lab(c)) in placed_keys:
            continue
        uses = [f"{a['subject_label']} {a['predicate']} {a['filler_label']}" for a in cur
                if K(a["filler_label"]) == K(lab(c)) or K(tdict.resolve(a["filler_label"])) == K(lab(c))]
        items.append({"id": f"f{len(items):03d}", "section": "fillers", "subject": lab(c),
                      "iri": str(c).rsplit("/", 1)[-1], "bfo": bfo_type(c), "uses": uses})

    out = {"made": rep and __import__("datetime").datetime.now().isoformat(timespec="seconds"),
           "items": items}
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(out_path.read_text(encoding="utf-8"))
    if back != out:
        raise RuntimeError(f"[queue] {out_path} did not read back as written")
    from collections import Counter
    print(f"[queue] written and read back: {out_path} -- {dict(Counter(i['section'] for i in items))}")
    return 0


# What a relation makes its subject (its domain) and needs its target to be
# (its range), in plain words for the page.
DOMAIN_KIND = {
    "inheres in": "a property of something", "is about": "a piece of information",
    "has disposition": "a thing that can have dispositions", "has function": "a thing that can have a function",
    "has role": "a thing that can have a role", "has tendency": "a thing that can have a tendency",
    "has quality": "a thing that can have qualities", "has realization": "a disposition, function or role",
    "has input": "a process", "has output": "a process", "has participant": "a process",
    "has as process boundary at end": "a process", "has as process boundary at start": "a process",
    "realizes": "a process", "participates in": "a thing that takes part in processes",
}
RANGE_KIND = {
    "has quality": "a quality", "has disposition": "a disposition", "has role": "a role",
    "has function": "a function", "has tendency": "a tendency", "has realization": "a process",
    "inheres in": "a thing that can have properties", "participates in": "a process",
    "has participant": "a thing that takes part", "has input": "a thing that goes in",
    "has output": "a thing that comes out", "realizes": "a disposition, function or role",
    "has as process boundary at end": "the point where a process ends",
    "has as process boundary at start": "the point where a process starts",
    "has a material basis": "a material thing",
}


def _with(core, rels, rdflib):
    from rdflib import BNode, OWL, RDF, RDFS, URIRef
    g = rdflib.Graph(); g += core
    for h in rels:
        n = BNode()
        g.add((n, RDF.type, OWL.Restriction)); g.add((n, OWL.onProperty, URIRef(h["property_iri"])))
        g.add((n, OWL.someValuesFrom, URIRef(h["value_iri"]))); g.add((URIRef(h["subject_iri"]), RDFS.subClassOf, n))
    return g


def _ancestor_labels(g, c, labels):
    from rdflib import RDFS, URIRef
    out, stack = [], [c]
    seen = set()
    while stack:
        x = stack.pop()
        for o in g.objects(x, RDFS.subClassOf):
            if isinstance(o, URIRef) and o not in seen:
                seen.add(o); stack.append(o)
                out.append(labels.get(o) or str(g.value(o, RDFS.label) or o))
    return out


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
