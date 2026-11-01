#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The built placements Claude's reading of 2026-10-29 disputes, and the classes it brought in: a page for the author.

    python -u scripts/claude_dispute_page.py       # data/review/claude_disputes_2026-10-30/{items.json, page.html}

Claude Opus 5.5 read every placement proposal again on 2026-10-29
(`claude_read_placements.py`). On about 3,170 placements the author had
accepted on his review page of 2026-10-02, the new reading says no class fits
or another one does. The author's word still counts there. On 394 classes the
new reading is the only judgement that placed them, so they entered the WONT
addition without the author's word. The author asked (2026-10-30) to see the
disputed ones that are built, and the new classes.

Only what is built is put to him: a placement below the evidence cut, of a term
out of scope, or refused by ELK changes nothing today. "Built" is read from the
WONT addition itself (`wont_extended_core.ttl`), matched on the parent's IRI or,
where the addition writes an equivalent class of another module (COB organism
as OBI organism, PATO quality as BFO quality), on its label. The new classes are
those of the addition that the one before the Claude readings did not have
(`data/backup/core_2026-10-29_23-38-10`).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))

AGENT = "claude-opus-5-5_placement"
SESSION = "claude-opus-5-5"
PROPOSER = "deepseek-v4-flash_top_15"
CORE = ROOT / "output" / "owl" / "wont_extended_core.ttl"
BEFORE = ROOT / "data" / "backup" / "core_2026-10-29_23-38-10" / "wont_extended_core.ttl"
OUT = ROOT / "data" / "review" / "claude_disputes_2026-10-30"
TEMPLATE = ROOT / "scripts" / "claude_dispute_page.html"


def core_index(path: Path):
    """label/synonym (normalised) -> class IRIs; IRI -> label; IRI -> named superclasses."""
    import rdflib
    from rdflib.namespace import OWL, RDF, RDFS
    from wound_ontology.utils.string_utils import normalize_term as N
    alt = rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000118")
    g = rdflib.Graph()
    g.parse(str(path), format="turtle")
    by_name, label, sup = defaultdict(set), {}, defaultdict(set)
    for s in g.subjects(RDF.type, OWL.Class):
        if not isinstance(s, rdflib.URIRef):
            continue
        for o in g.objects(s, RDFS.label):
            by_name[N(str(o))].add(str(s))
            label.setdefault(str(s), str(o))
        for o in g.objects(s, alt):
            by_name[N(str(o))].add(str(s))
        sup[str(s)] |= {str(o) for o in g.objects(s, RDFS.subClassOf) if isinstance(o, rdflib.URIRef)}
    return by_name, label, sup


def curator_classes() -> set[str]:
    """The classes of WONT and MILD themselves: a term that is one of them takes the ontology's word."""
    import rdflib
    from rdflib.namespace import OWL, RDF
    from config.settings import GROUND_TRUTH_TTL, MILD_TTL
    g = rdflib.Graph()
    g.parse(str(GROUND_TRUTH_TTL), format="turtle")
    g.parse(str(MILD_TTL), format="turtle")
    return {str(s) for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, rdflib.URIRef)}


def plain_why(why: str) -> str:
    """Claude's reason without the model snapshot and the notes added after it
    (the writer's slip note, the mapping note of 2026-10-30)."""
    return re.sub(r"\s*\(anthropic/[^)]*\)(\s*\[[^\]]*\])*\s*$", "", why).strip()


def main() -> int:
    from claude_read_placements import _ontology_index
    from wound_ontology.llm.extraction_models import CATEGORY_IRI
    from wound_ontology.mappers.judgements import current
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import normalize_term as N

    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    docs = Counter()
    for _, ents in p.store.view():
        for name in ents:
            docs[name] += 1
    by_iri, _ = _ontology_index()
    core_by, core_label, core_sup = core_index(CORE)
    _, before_label, _ = core_index(BEFORE)
    cat_name = {v: k for k, v in CATEGORY_IRI.items()}
    own = curator_classes()
    is_cat = lambda i: i in cat_name or i.startswith("http://purl.obolibrary.org/obo/BFO_")  # noqa: E731

    def label(i: str) -> str:
        return core_label.get(i) or (by_iri.get(i) or {}).get("label") or i.rsplit("/", 1)[-1]

    def cls(i: str, key: str) -> dict:
        info = by_iri.get(i) or {}
        return {"label": info.get("label") or key, "iri": i, "cat": info.get("category"),
                "def": info.get("definition") or "", "under": info.get("parent") or ""}

    def classes_of(concept: str) -> set[str]:
        return core_by.get(N(concept), set())

    def built_parent(concept: str, q: str, key: str, iri: str) -> str | None:
        """The class of the addition that stands for this placement's target, if the placement is built."""
        names = {N(key), N((by_iri.get(iri) or {}).get("label") or key)}
        for c in classes_of(concept):
            if q == "is_a":
                hit = next((s for s in sorted(core_sup.get(c, ())) if s == iri or N(label(s)) in names), None)
                if hit:
                    return hit
            elif c == iri or N(label(c)) in names:
                return c
        return None

    def category(concept: str) -> str | None:
        cats = {cat_name.get(s) or label(s) for c in classes_of(concept) for s in core_sup.get(c, ()) if is_cat(s)}
        return " / ".join(sorted(cats)) or None

    def children(concept: str) -> int:
        mine = classes_of(concept)
        return sum(1 for c, ss in core_sup.items() if ss & mine)

    def staying(concept: str, gone: set[str]) -> list[str]:
        """The superclasses (not categories) the term's class keeps when `gone` is taken away."""
        return sorted({label(s) for c in classes_of(concept) for s in core_sup.get(c, ())
                       if s not in gone and not is_cat(s) and s not in classes_of(concept)})

    def concept_of(term: str) -> str:
        try:
            return gt.concept(gt.resolve(term))
        except RuntimeError:
            return term

    tally = Counter()
    disputes = []
    for term, rec in gt.records.items():
        for q in ("is_a", "pairs"):
            yes = "yes" if q == "is_a" else "same_class"
            for key, js in (rec.get(q) or {}).items():
                a = [j for j in js if j["by"] == "author" and j["verdict"] != "undecided"]
                c = [j for j in js if j["by"] == AGENT]
                if not a or not c or a[-1]["verdict"] != yes or c[-1]["verdict"] == yes:
                    continue
                tally["accepted by the author, disputed by Claude"] += 1
                concept = concept_of(term)
                iri = a[-1].get("iri") or c[-1].get("iri")
                if gt.gate_verdict(concept)[0] == "out":
                    tally["not built: out of scope"] += 1
                    continue
                hit = built_parent(concept, q, key, iri)
                if not hit:
                    tally["not built"] += 1
                    continue
                if classes_of(concept) and classes_of(concept) <= own:
                    tally["the term is a WONT or MILD class: the ontology decides, not asked"] += 1
                    continue
                same = next((d for d in disputes if d["concept"] == concept and d["hit"] == hit), None)
                if same:
                    same["records"].append({"term": term, "q": q, "key": key, "iri": iri})
                    tally["a spelling variant of a disputed placement, folded into it"] += 1
                    continue
                why = c[-1]["why"]
                alt = None
                for q2 in ("is_a", "pairs"):
                    for k2, js2 in (rec.get(q2) or {}).items():
                        if (q2, k2) == (q, key):
                            continue
                        mine = [j for j in js2 if j["by"] == AGENT and plain_why(j["why"]) == plain_why(why) and j["verdict"] in ("yes", "same_class")]
                        if mine:
                            au = [j for j in js2 if j["by"] == "author" and j["verdict"] != "undecided"]
                            hit2 = built_parent(concept, q2, k2, mine[-1]["iri"])
                            alt = dict(cls(mine[-1]["iri"], k2), q=q2, key=k2, built=bool(hit2),
                                       author=(au[-1]["verdict"], au[-1]["when"][:10]) if au else None)
                # Claude's other class may be the author's own word already
                if alt and alt["author"] and alt["author"][0] in ("no", "different"):
                    kind = "none"
                elif alt and alt["author"]:
                    kind = "other_own"
                else:
                    kind = "change" if alt else "none"
                tally[f"built, Claude: {kind}"] += 1
                gone = {hit} | ({built_parent(concept, alt["q"], alt["key"], alt["iri"])} if alt else set())
                disputes.append({
                    "id": "d" + hashlib.sha1(f"{term}|{q}|{key}".encode()).hexdigest()[:10],
                    "term": term, "concept": concept, "q": q, "key": key, "iri": iri, "hit": hit,
                    "records": [{"term": term, "q": q, "key": key, "iri": iri}],
                    "mine": cls(iri, key), "accepted": a[-1]["when"][:10], "kind": kind,
                    "why": plain_why(why), "alt": alt,
                    "cat": category(concept), "abstracts": docs.get(concept, 0), "children": children(concept),
                    "keeps_without_mine": staying(concept, {hit}),
                    "keeps_without_both": staying(concept, gone - {None}),
                })

    new = [(c, core_label[c]) for c in sorted(set(core_label) - set(before_label))]
    # one pass over the records for the concepts of the new classes
    wanted = {N(lab): c for c, lab in new}
    recs_of = defaultdict(list)
    for t in gt.records:
        n = N(concept_of(t))
        if n in wanted:
            recs_of[n].append(t)
    news = []
    for c, lab in new:
        edges, author_edges = [], []
        for t in recs_of.get(N(lab), []):
            for q in ("is_a", "pairs"):
                for k, js in (gt.records[t].get(q) or {}).items():
                    cj = current(js)
                    if not cj or cj["verdict"] not in ("yes", "same_class") or not cj.get("iri"):
                        continue
                    hit = None
                    for s in sorted(core_sup.get(c, ())):
                        if q == "is_a" and (s == cj["iri"] or N(label(s)) in {N(k), N((by_iri.get(cj["iri"]) or {}).get("label") or k)}):
                            hit = s
                    if not hit:
                        continue
                    if cj["by"] == AGENT:
                        prop = [j for j in js if j["by"] == PROPOSER]
                        sess = [j for j in js if j["by"] == SESSION]
                        edges.append(dict(cls(cj["iri"], k), term=t, q=q, key=k, hit=hit, why=plain_why(cj["why"]),
                                          proposed=bool(prop), session=sess[-1]["verdict"] if sess else None))
                    else:
                        author_edges.append({"label": label(hit), "by": cj["by"]})
        concept = concept_of(recs_of[N(lab)][0]) if recs_of.get(N(lab)) else lab
        if gt.gate_verdict(concept)[0] == "out":
            tally["new class now out of scope: not asked"] += 1
            continue
        if not edges:
            tally["new class without a placement of Claude's"] += 1
            print(f"[dispute-page] *** new class {lab} ({c}): no placement of {AGENT} found under it; "
                  f"its edges: {sorted(label(s) for s in core_sup.get(c, ()))} ***")
            continue
        if any(o["label"] in {label(e["hit"]) for e in edges} for o in author_edges):
            tally["new class under a parent the author gave it (on a spelling variant): not asked"] += 1
            continue
        tally["new class placed by Claude alone" if not author_edges else "new class, Claude beside another"] += 1
        replaced = None
        for e in edges:
            if not e["proposed"]:
                # Claude chose this class instead of the proposal: name the proposal it refused
                for k, js in (gt.records[e["term"]].get("is_a") or {}).items():
                    if any(j["by"] == AGENT and plain_why(j["why"]) == e["why"] and j["verdict"] == "no" for j in js):
                        replaced = k
        news.append({
            "id": "n" + c.rsplit("_", 1)[-1],
            "iri": c, "concept": concept, "label": lab, "edges": edges, "others": author_edges,
            "replaced": replaced, "cat": category(concept), "abstracts": docs.get(concept, 0),
            "children": children(concept),
            "keeps_without": staying(concept, {e["hit"] for e in edges}),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    items = {"made": datetime.now().isoformat(timespec="minutes"), "tally": dict(tally),
             "disputes": sorted(disputes, key=lambda d: (d["mine"]["label"].lower(), d["concept"].lower())),
             "new": sorted(news, key=lambda d: (d["edges"][0]["label"].lower(), d["concept"].lower()))}
    (OUT / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    page = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*ITEMS*/null", json.dumps({"disputes": items["disputes"], "new": items["new"]}, ensure_ascii=False))
    (OUT / "page.html").write_text(page, encoding="utf-8")
    print(f"[dispute-page] {dict(tally)}")
    print(f"[dispute-page] {len(disputes)} disputed and built, {len(news)} new classes -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
