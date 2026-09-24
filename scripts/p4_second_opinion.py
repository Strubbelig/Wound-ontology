"""Pass 2 — a second, independently-evidenced judgement on every content pair.

Pass 1 (`_adjudicate_anchor_mappings`) asked the model with the ontology's
definitions for anchor pairs and NO categories for store-to-store pairs: the
store's own typings are the noisy input the pipeline exists to reconcile, and
feeding them in the slot the skeleton fills made the model refuse on invented
grounds (46% not-synonymous with them, 27% without, on the same 52 pairs).

Pass 2 asks the same pairs with exactly the evidence pass 1 withheld: each
side's BFO category as the store typed it. Its verdicts are NOT applied --
they would over-refuse for the reason above. They are compared with pass 1, and
only the DISAGREEMENTS go to the curator. Two independently-evidenced
judgements agreeing is decent grounds to wave a row through; disagreeing is
where a human is worth the time.

Writes data/review/second_opinion_<date>.csv and caches verdicts in
data/cache/mapping_second_opinion_*.json, so a re-run asks nothing twice.
"""
from __future__ import annotations
import asyncio, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import pandas as pd
from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
from wound_ontology.mappers.mapping_adjudicator import label_difference, _key, _loose
from wound_ontology.orchestrator import Orchestrator
from wound_ontology.utils.string_utils import smart_title

BATCH = 20


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


async def ask(llm, chunk, store_cat, onto_cat, defs):
    payload = [{
        "store_term": t,
        "ontology_class": c,
        "store_category": store_cat.get(smart_title(t.strip())),
        "ontology_category": onto_cat.get(c.strip()) or store_cat.get(smart_title(c.strip())),
        "ontology_definition": defs.get(c.strip()),
        "ontology_parents": None,
    } for t, c in chunk.items()]
    verdicts = await llm.adjudicate_mappings_batch(payload)
    by_loose = {(_loose(t), _loose(c)): (t, c) for t, c in chunk.items()}
    out = {}
    for v in verdicts:
        pair = (v.store_term, v.ontology_class)
        if chunk.get(v.store_term) != v.ontology_class:
            pair = by_loose.get((_loose(v.store_term), _loose(v.ontology_class)))
        if pair is not None:
            out[pair] = (v.verdict, v.reason)
    return out


async def main() -> None:
    p = Orchestrator(entrez_email=ENTREZ_EMAIL,
                     allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    mapping = dict(p.term_mapper.mapping)
    pairs = {t: c for t, c in mapping.items() if label_difference(t, c) == "content"}
    log(f"{len(mapping):,} entries, {len(pairs):,} content pairs to second-guess")

    store_cat = p.store_categories()
    onto_cat = p.ontology_categories()
    defs = p.ontology_definitions()
    first = p.dm.load_latest_json("mapping_adjudication") or {}
    cache = p.dm.load_latest_json("mapping_second_opinion") or {}
    todo = {t: c for t, c in pairs.items() if _key(t, c) not in cache}
    log(f"{len(cache):,} already in the pass-2 cache; {len(todo):,} to ask")

    # Five batches in flight. One at a time measured 60 s per batch of 20 —
    # four hours for the queue, all of it waiting on the network.
    items = list(todo.items())
    chunks = [dict(items[i:i + BATCH]) for i in range(0, len(items), BATCH)]
    gate = asyncio.Semaphore(5)
    done = 0

    async def one(chunk):
        nonlocal done
        async with gate:
            try:
                answers = await ask(p.llm, chunk, store_cat, onto_cat, defs)
            except Exception as exc:                      # reported, never swallowed
                log(f"  batch failed ({type(exc).__name__}: {exc}); its pairs stay "
                    f"unanswered and will be re-asked on the next run")
                return
        for (t, c), (verdict, reason) in answers.items():
            cache[_key(t, c)] = {"verdict": verdict, "reason": reason}
        done += len(chunk)
        if done % (BATCH * 10) < BATCH:
            log(f"  {done:,}/{len(items):,} asked")
            p.dm.save_as_json(cache, "mapping_second_opinion")

    await asyncio.gather(*(one(c) for c in chunks))
    p.dm.save_as_json(cache, "mapping_second_opinion")

    rows = []
    agree = disagree = unanswered = 0
    for t, c in pairs.items():
        one = (first.get(_key(t, c)) or {}).get("verdict")
        two = (cache.get(_key(t, c)) or {}).get("verdict")
        if two is None:
            unanswered += 1
            continue
        if one == two:
            agree += 1
            continue
        disagree += 1
        rows.append({"term": t, "canonical": c,
                     "pass 1": one, "pass 1 reason": (first.get(_key(t, c)) or {}).get("reason", ""),
                     "pass 2": two, "pass 2 reason": cache[_key(t, c)]["reason"],
                     "term category": store_cat.get(smart_title(t.strip())),
                     "canonical category": onto_cat.get(c.strip()) or store_cat.get(smart_title(c.strip()))})
    log(f"agree {agree:,} | disagree {disagree:,} | no pass-2 verdict {unanswered:,}")
    if rows:
        out = ROOT / "data" / "review" / f"second_opinion_{time.strftime('%Y-%m-%d')}.csv"
        pd.DataFrame(rows).to_csv(out, index=False)
        log(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
