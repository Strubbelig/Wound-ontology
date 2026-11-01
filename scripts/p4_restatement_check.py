"""Is a kept placement a new kind of its class, or just another name for it? Sandbox only.

    python -u scripts/p4_restatement_check.py [--budget-usd X] [--batch-size N]

Curator, 2026-10-02: "Wound Analysis, Wound Assessment, Wound Exploration,
Wound Monitoring, Wound Recognition, Wound Scanning -- placed. so many
nonsense terms" -- answered: check every kept placement for "this just
restates its class" and turn those into synonyms. The check runs on the
placements the evidence cut keeps (`PLACEMENT_MIN_ABSTRACTS`): for each
`term < class`, the model answers `same` (another name for the class, possibly
looser or with a generic word added), `narrower` (a genuinely more specific
kind) or `unclear`. Every `same` is then read by Claude before anything
changes (`apply_restatements.py`).

Reads the term dict and the store; writes
`data/review/placement_restatement_2026-10-02.json`. Resumable.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

OUT = ROOT / "data" / "review" / "placement_restatement_2026-10-02.json"


class Verdict(BaseModel):
    id: Optional[str] = None
    answer: Optional[str] = None          # same | narrower | unclear
    reason: Optional[str] = ""


class VerdictBatch(BaseModel):
    verdicts: list[Verdict]


def main(argv: list[str]) -> int:
    from p4_verify_placements import _opt, _usage
    from wound_ontology.orchestrator import PLACEMENT_MIN_ABSTRACTS, Orchestrator
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    seen = {}
    for key, ents in p.store.view():
        for name in ents:
            seen.setdefault(name, set()).add(key)
    rows = []
    for term, cls in gt.placements():
        n = len(seen.get(term, ()))
        if n >= PLACEMENT_MIN_ABSTRACTS:
            rows.append({"id": "r" + hashlib.sha1(f"{term}|{cls}".encode()).hexdigest()[:10],
                         "term": term, "class": cls, "abstracts": n})
    done = {}
    if OUT.exists():
        done = {x["id"]: x for x in json.loads(OUT.read_text(encoding="utf-8"))["rows"]}
    todo = [r for r in rows if r["id"] not in done]
    print(f"[restate] {len(rows):,} kept placements; {len(done):,} answered; {len(todo):,} to ask", flush=True)

    def prompt_for(batch):
        lines = [f'- id {r["id"]}: term "{r["term"]}" is placed under the class "{r["class"]}"' for r in batch]
        return ("You are cleaning a wound-care ontology. Each extracted term below was placed as a "
                "subclass of an existing class. For EACH, decide:\n"
                "  same     -- the term is just another name for the class: it denotes the same thing, "
                "perhaps more loosely, more colloquially, or with a generic word added "
                "(e.g. \"wound assessment\" under \"Wound diagnostic process\", \"bacteria\" under \"Bacteria\").\n"
                "  narrower -- the term names a genuinely more specific kind of the class, with a "
                "distinguishing feature (e.g. \"remote wound assessment\" under \"Wound diagnostic process\").\n"
                "  unclear  -- you cannot tell.\n"
                "Return every id with answer same, narrower or unclear and a short reason.\n\n"
                + "\n".join(lines))

    sem = asyncio.Semaphore(int(_opt(argv, "--concurrency", "4")))
    failed = 0

    async def run(batch):
        nonlocal failed
        async with sem:
            try:
                res = await p.llm._execute_with_retry(
                    p.llm._call_json, prompt_for(batch), VerdictBatch, temperature=0.0,
                    timeout=600, max_tokens=8000)
            except Exception as exc:
                failed += 1
                print(f"[restate]   batch failed: {type(exc).__name__}: {exc}", flush=True)
                return
        by = {r["id"]: r for r in batch}
        for v in res.verdicts:
            r = by.get((v.id or "").strip())
            a = (v.answer or "").strip().lower()
            if r is None or a not in ("same", "narrower", "unclear"):
                continue
            done[r["id"]] = {**r, "answer": a, "reason": v.reason or ""}

    def save():
        OUT.write_text(json.dumps({"measured": time.strftime("%Y-%m-%d %H:%M"),
                                   "rows": sorted(done.values(), key=lambda x: (x["class"], -x["abstracts"]))},
                                  ensure_ascii=False, indent=1), encoding="utf-8")

    size = int(_opt(argv, "--batch-size", "40"))
    budget = float(_opt(argv, "--budget-usd", "0.5"))
    batches = [todo[i:i + size] for i in range(0, len(todo), size)]
    u0 = _usage()

    async def drive():
        for i in range(0, len(batches), 40):
            await asyncio.gather(*(run(b) for b in batches[i:i + 40]))
            save()
            spent = _usage() - u0
            n = min(i + 40, len(batches))
            print(f"[restate]   {n}/{len(batches)} batches, {len(done):,} answered, ${spent:.2f}, {failed} failed", flush=True)
            if n < len(batches) and spent * len(batches) / n > budget:
                print(f"[restate] STOP: projected ${spent * len(batches) / n:.2f} > budget ${budget:.2f}", flush=True)
                return

    asyncio.run(drive())
    save()
    back = json.loads(OUT.read_text(encoding="utf-8"))["rows"]
    have = {x["id"] for x in back}
    print(f"[restate] written and read back: {len(back):,} {dict(Counter(x['answer'] for x in back))}; "
          f"{sum(1 for r in rows if r['id'] not in have)} not yet answered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
