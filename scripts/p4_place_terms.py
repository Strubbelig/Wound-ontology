"""Ask the model where each extracted term belongs under WONT/MILD. Writes a SANDBOX file only.

    python -u scripts/p4_place_terms.py [--limit-batches N] [--budget-usd X]

Curator, 2026-09-29: run the placement step over every in-scope, consistently
typed term, "and don't merge the answers yet -- I want to inspect the results".
So this writes `data/review/placement_<date>.json` and nothing else: no term
dict, no ontology file.

Per term: its category (one across every abstract), how many abstracts mention
it, and the 10 WONT/MILD classes of a compatible BFO category (same branch)
that are closest to it by SapBERT cosine. The model picks the class the term is
a kind of (`is_a`), says it IS that class (`same`), or `none`. An answer naming
a class that was not offered is kept and flagged `unlisted`.

Resumable: terms already answered in the sandbox file are not asked again.
Cost is measured, not estimated: after the first batches the OpenRouter usage
delta is extrapolated, and the run stops if it would exceed `--budget-usd`.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

OUT = ROOT / "data" / "review" / "placement_2026-09-29.json"   # the sandbox the page reads; resumable across days
GT = ROOT / "data" / "ground truth" / "ground_truth_final.owl"
MILD = ROOT.parent / "Disease ontologies" / "Disease proposal 2.ttl"
MODULES = ROOT.parent / "Disease ontologies" / "Disease ontology modules"
TOP_K, BATCH, CONCURRENCY = 10, 20, 8


class Placement(BaseModel):
    term: Optional[str] = None
    relation: Optional[str] = None  # "is_a" | "same" | "none"
    parent: Optional[str] = None
    reason: Optional[str] = ""


class PlacementBatch(BaseModel):
    placements: list[Placement]


def _usage() -> float:
    req = urllib.request.Request("https://openrouter.ai/api/v1/credits",
                                 headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return float(json.load(r)["data"]["total_usage"])


def _opt(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv: list[str]) -> int:
    import numpy as np
    import rdflib
    from rdflib.collection import Collection
    from rdflib.namespace import OWL, RDF, RDFS

    from wound_ontology.llm.extraction_models import CATEGORY_IRI, CATEGORY_PARENT
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import normalize_term as N

    limit_batches = int(_opt(argv, "--limit-batches", "0"))
    budget = float(_opt(argv, "--budget-usd", "8"))
    p = Orchestrator()
    gt = p.term_mapper._term_mapping

    # ── the terms ────────────────────────────────────────────────────────────
    docs: Counter = Counter(); typings = defaultdict(set); name_of = {}
    for _, ents in p.store.view():
        for name, attrs in ents.items():
            k = N(name); docs[k] += 1; name_of.setdefault(k, name)
            for t in attrs:
                pr, _, tg = t.partition(":")
                if pr.strip() == "is_a":
                    typings[k].add(tg.strip())
    onto_labels = {N(str(l)) for l in p.ontology_labels()}

    def category(k):
        c = typings.get(k, set())
        if not c:
            return None
        return next(iter(c)) if len(c) == 1 else p.reasoner_gate.least_common_category(c)

    terms = []
    for k, name in name_of.items():
        if k in onto_labels:
            continue                               # already a WONT/MILD class
        cat = category(k)
        if cat is None or gt.effective_gate_verdict(gt.resolve(name))[0] != "in":
            continue
        terms.append((name, cat, docs[k]))
    terms.sort(key=lambda t: (-t[2], t[0].lower()))

    # ── the candidate parents ────────────────────────────────────────────────
    cur = rdflib.Graph(); cur.parse(GT, format="turtle"); cur.parse(MILD, format="turtle")
    full = rdflib.Graph(); full += cur
    for m in sorted(MODULES.glob("*_module.owl")):
        full.parse(m)
    cat_iris = {rdflib.URIRef(v): k for k, v in CATEGORY_IRI.items()}

    def named_parents(c):
        for o in full.objects(c, RDFS.subClassOf):
            if isinstance(o, rdflib.URIRef):
                yield o
        for e in full.objects(c, OWL.equivalentClass):
            lst = full.value(e, OWL.intersectionOf)
            if lst is not None:
                yield from (m for m in Collection(full, lst) if isinstance(m, rdflib.URIRef))

    def bfs_category(c):
        frontier, seen = [c], {c}
        while frontier:
            nxt = []
            for node in frontier:
                if node in cat_iris:
                    return cat_iris[node]
                for pp in sorted(set(named_parents(node)), key=str):
                    if pp not in seen:
                        seen.add(pp); nxt.append(pp)
            frontier = nxt
        return None

    iao_def = rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000115")
    parents = []                                  # (label, iri, category, definition)
    # WONT/MILD classes AND the classes of their import modules (curator,
    # 2026-09-29): the probe left `foot`, `fibroblast`, `hydrogel` without a
    # parent because FMA, CL/GO and CHEBI classes were not on offer.
    pool = {s for s in cur.subjects(RDF.type, OWL.Class) if isinstance(s, rdflib.URIRef)}
    pool |= {s for s in full.subjects(RDF.type, OWL.Class) if isinstance(s, rdflib.URIRef)}
    for s in sorted(pool, key=str):
        if s in cat_iris:
            continue
        lab = cur.value(s, RDFS.label) or full.value(s, RDFS.label)
        cat = bfs_category(s)
        if lab and cat:
            d = str(cur.value(s, iao_def) or full.value(s, iao_def) or "")
            parents.append((str(lab), str(s), cat, d[:110]))
    print(f"[place] {len(terms):,} terms to place; {len(parents):,} WONT/MILD/module classes as parents", flush=True)

    def ancestors(c):
        out = set()
        while c:
            out.add(c); c = CATEGORY_PARENT.get(c)
        return out

    emb = p._ensure_embedder()
    vec = p.term_mapper._embeddings_for
    pv = np.asarray(vec([pl for pl, *_ in parents], emb), dtype=np.float32)
    pv /= np.linalg.norm(pv, axis=1, keepdims=True)
    pcat = [c for _, _, c, _ in parents]
    compat = {}
    for c in set(t[1] for t in terms):
        compat[c] = np.array([(pc in ancestors(c) or c in ancestors(pc)) for pc in pcat])

    done = {}
    if OUT.exists():
        done = {r["term"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))["rows"]}
    todo = [t for t in terms if t[0] not in done]
    print(f"[place] {len(done):,} already answered in {OUT.name}; {len(todo):,} to ask", flush=True)

    rows_by_term = dict(done)
    CH = 2000
    cands: dict[str, list] = {}
    for i in range(0, len(todo), CH):
        block = todo[i:i + CH]
        tv = np.asarray(vec([t[0] for t in block], emb), dtype=np.float32)
        tv /= np.linalg.norm(tv, axis=1, keepdims=True)
        sims = tv @ pv.T
        for j, (name, cat, _) in enumerate(block):
            s = np.where(compat[cat], sims[j], -1.0)
            top = np.argsort(-s)[:TOP_K]
            cands[name] = [(parents[x][0], parents[x][1], parents[x][2], parents[x][3],
                            round(float(s[x]), 3)) for x in top if s[x] > -1]

    size = int(_opt(argv, "--batch", str(BATCH)))
    batches = [todo[i:i + size] for i in range(0, len(todo), size)]
    if limit_batches:
        batches = batches[:limit_batches]

    def prompt_for(batch):
        lines = []
        for name, cat, n in batch:
            opts = "; ".join(f"[{i + 1}] {c[0]}" + (f" ({c[3]})" if c[3] else "")
                             for i, c in enumerate(cands[name]))
            lines.append(f'- TERM "{name}" (typed {cat}, in {n} abstracts). CANDIDATES: {opts}')
        return f"""
You are placing terms extracted from wound-care abstracts into a wound ontology
(WONT, built on the disease ontology MILD and BFO). For EVERY term, choose among
ITS candidate classes:

- relation "is_a": the term names a KIND of that class (a subclass). Choose the
  most specific candidate that is still correct.
- relation "same": the term names exactly that class (a synonym).
- relation "none": no candidate is a correct parent or synonym. Say so; a wrong
  parent is worse than none.

Rules: the parent must be the same kind of thing (a dressing is not a process;
a process is not a quality). A word shared with the candidate is not enough
("wound closure" the process is not a kind of "closure" the quality). Give the
candidate's name exactly as written, and a short reason.

TERMS:
{chr(10).join(lines)}
"""

    t_start, u_start = time.time(), _usage()
    sem = asyncio.Semaphore(int(_opt(argv, "--concurrency", str(CONCURRENCY))))
    failed = 0
    unmatched_total = 0

    async def run_batch(batch):
        nonlocal failed, unmatched_total
        async with sem:
            try:
                res = await p.llm._execute_with_retry(
                    p.llm._call_json, prompt_for(batch), PlacementBatch,
                    temperature=0.0, timeout=int(_opt(argv, "--timeout", "360")), max_tokens=p.llm.BATCH_MAX_TOKENS)
            except Exception as exc:
                failed += 1
                print(f"[place]   batch failed: {type(exc).__name__}: {exc}", flush=True)
                return
        by = {N(t[0]): t for t in batch}
        for pl in res.placements:
            if not pl.term:                    # the model left the echo empty
                unmatched_total += 1
                continue
            t = by.get(N(pl.term))
            if t is None:
                unmatched_total += 1
                continue
            name, cat, n = t
            offered = {N(c[0]): c for c in cands[name]}
            hit = offered.get(N(pl.parent or "")) if pl.parent else None
            rows_by_term[name] = {
                "term": name, "category": cat, "abstracts": n,
                "relation": (pl.relation or "").strip().lower(),
                "parent": hit[0] if hit else pl.parent,
                "parent iri": hit[1] if hit else None,
                "parent category": hit[2] if hit else None,
                "similarity": hit[4] if hit else None,
                "unlisted": bool(pl.parent) and hit is None,
                "reason": pl.reason or "",
                "candidates": [[c[0], c[4]] for c in cands[name]],
            }

    def save():
        rows = sorted(rows_by_term.values(), key=lambda r: (-r["abstracts"], r["term"].lower()))
        OUT.write_text(json.dumps({"measured": time.strftime("%Y-%m-%d %H:%M"), "rows": rows},
                                  ensure_ascii=False, indent=1), encoding="utf-8")

    async def drive():
        for i in range(0, len(batches), 50):
            await asyncio.gather(*(run_batch(b) for b in batches[i:i + 50]))
            save()
            spent = _usage() - u_start
            done_b = min(i + 50, len(batches))
            per = spent / done_b if done_b else 0
            projected = per * len(batches)
            print(f"[place]   {done_b}/{len(batches)} batches, {len(rows_by_term):,} answered, "
                  f"${spent:.2f} spent, projected ${projected:.2f}, {failed} failed, "
                  f"{unmatched_total} unmatched echoes", flush=True)
            if done_b < len(batches) and spent + 50 * per > budget:
                print(f"[place] STOP: ${spent:.2f} spent; the next 50 batches would pass the "
                      f"${budget:.2f} budget (projected total ${projected:.2f}). Answers so far are "
                      f"saved; re-run with a higher --budget-usd to continue.", flush=True)
                return

    asyncio.run(drive())
    save()
    back = json.loads(OUT.read_text(encoding="utf-8"))["rows"]
    rel = Counter(r["relation"] for r in back)
    print(f"[place] written and read back: {len(back):,} answers in {OUT.name}: {dict(rel)}; "
          f"{sum(r['unlisted'] for r in back)} name a class that was not offered; "
          f"{time.time() - t_start:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
