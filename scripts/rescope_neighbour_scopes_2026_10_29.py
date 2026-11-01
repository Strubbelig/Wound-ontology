#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DeepSeek judges again the scopes copied from the most similar term (rule 89).

    python -u scripts/rescope_neighbour_scopes_2026_10_29.py            # dry run: the queue only
    python -u scripts/rescope_neighbour_scopes_2026_10_29.py --apply

Rule 89 (curator, 2026-10-28; go-ahead 2026-10-29): "the 501 terms whose scope
`sapbert-neighbour` decides are judged again by `deepseek-v4-flash`". Added on
2026-10-29: the five terms the pair page took apart from the concept whose
scope they shared, which have no scope of their own yet.

The question and the answer form are those of the scope pass
(`LLMClient.gate_scope_batch`): one verdict per term, a term missing from the
answer gets nothing and is named. The answer is written by `deepseek-v4-flash`
after the copied one, so it counts unless the author has spoken; nothing is
removed. Ontology classes and BFO category names are never asked (rules 20, 26).
"""
from __future__ import annotations

import asyncio
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

SPLIT_OFF = ("Acute infection disorder", "Anti-biofilm function", "Aseptic conditions",
             "Broad-spectrum antibacterial activity", "Magnetic resonance imaging study")
BATCH, CONCURRENCY = 25, 8


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.llm.category_vocab import declared_category
    from wound_ontology.utils.label_match import fold
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)

    freq: Counter = Counter()
    attrs: dict[str, list[str]] = {}
    for _, ents in p.store.view(include_rejected=True):
        for name, cells in ents.items():
            freq[name] += 1
            if name not in attrs and isinstance(cells, dict):
                attrs[name] = [a for a, v in cells.items() if v == 1.0][:3]
    curated = {fold(str(l)) for l in p.ontology_labels()}

    neighbour = sorted(c for c in gt.records
                       if gt.concept(gt.resolve(c)) == c and gt.gate_verdict(c)[1] == "sapbert-neighbour")
    split_off = [t for t in SPLIT_OFF if not gt.gate_verdict(t)[0]]
    skipped = [t for t in neighbour + split_off if fold(t) in curated or declared_category(t) is not None]
    queue = [t for t in neighbour + split_off if t not in skipped]
    print(f"[rescope] {live.name}: {len(neighbour)} concepts with a copied scope, {len(split_off)} split off "
          f"without one; {len(skipped)} not asked (ontology class or BFO category): {skipped[:8]}")
    print(f"[rescope] {len(queue)} to ask, {sum(1 for t in queue if freq[t] == 0)} of them in no abstract of the "
          f"cleaned store; ~{(len(queue) + BATCH - 1) // BATCH} model calls")
    if "--apply" not in argv:
        print("[rescope] dry run; --apply to ask")
        return 0
    if not p.llm.has_credentials:
        raise SystemExit("[rescope] no API key: the model cannot be asked")

    backup = ROOT / "data" / "backup" / f"term_mapping_before_rescope_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[rescope] backed up {live.name} -> {backup.relative_to(ROOT)}")
    before = {t: gt.gate_verdict(t)[0] for t in queue}
    answered: dict[str, tuple[str, str]] = {}
    silent: list[str] = []
    stray: list[str] = []
    failed: list[str] = []
    batches = [queue[i:i + BATCH] for i in range(0, len(queue), BATCH)]

    async def run() -> None:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def one(batch: list[str]) -> None:
            async with sem:
                try:
                    got, odd = await p.llm.gate_scope_batch([(t, freq[t], attrs.get(t, [])) for t in batch])
                except Exception as e:                       # noqa: BLE001
                    failed.extend(batch)
                    print(f"[rescope]   a batch failed, {len(batch)} term(s) stay as they were: "
                          f"{type(e).__name__}: {e}", flush=True)
                    return
                for term, (verdict, reason) in got.items():
                    gt.gate(term, pass2={"verdict": verdict,
                                         "reason": f"{reason[:300]}; scope judged again, it was copied from "
                                                   f"the most similar term (rule 89)"})
                answered.update(got)
                silent.extend(t for t in batch if t not in got)
                stray.extend(odd or ())

        await asyncio.gather(*(one(b) for b in batches))

    p._run_sync(run())
    gt.save()

    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    landed = {t: check.gate_verdict(t) for t in answered}
    wrong = [t for t, (v, by) in landed.items() if (v, by) != (answered[t][0], "deepseek-v4-flash")
             and by != "author"]
    flips = Counter((before[t] or "none", answered[t][0]) for t in answered)
    print(f"[rescope] {len(answered)} answered and read back ({len(wrong)} not as written: {wrong[:5]}); "
          f"{len(silent)} not answered: {silent[:10]}; {len(failed)} in failed batches; "
          f"{len(stray)} stray answer(s) dropped: {stray[:5]}")
    print(f"[rescope] before -> now: { {f'{a} -> {b}': n for (a, b), n in sorted(flips.items())} }")
    for t in sorted(answered, key=lambda t: -freq[t]):
        if (before[t] or "none") != answered[t][0] and freq[t] >= 2:
            print(f"  {t} ({freq[t]} abstracts): {before[t] or 'none'} -> {answered[t][0]}: {answered[t][1][:110]}")
    return 1 if (wrong or failed) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
