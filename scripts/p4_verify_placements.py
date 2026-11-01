"""Second, yes/no check of the placements that are to enter the WONT addition. Sandbox only.

    python -u scripts/p4_verify_placements.py [--budget-usd X] [--concurrency N] [--batch-size N]

A batch whose reply hits the token cap is reported and left unanswered; a rerun
asks only the unanswered rows, so rerun those with a smaller --batch-size.

Curator, 2026-10-01: the placement answers the sandbox review found reliable
enough to propose -- `is_a` whose parent shares a word with the term or sits
close to it (SapBERT >= 0.65) and that two or more abstracts mention, and
`same` at SapBERT >= 0.75 -- get a second, independent question before they
are used: is THIS statement true, yes or no. A placement stands only on `yes`.

Reads `output/placement_current_2026-10-01.json`; writes
`data/review/placement_verify_2026-10-01.json`. Nothing else. Resumable.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

SRC = ROOT / "output" / "placement_current_2026-10-01.json"
OUT = ROOT / "data" / "review" / "placement_verify_2026-10-01.json"
STOP = {"of", "the", "and", "in", "with", "for", "to", "on", "by", "a", "an", "or", "process", "entity"}


class Verdict(BaseModel):
    id: Optional[str] = None
    answer: Optional[str] = None          # "yes" | "no"
    reason: Optional[str] = ""


class VerdictBatch(BaseModel):
    verdicts: list[Verdict]


def _toks(s):
    return {re.sub(r"s$", "", w) for w in re.findall(r"[a-z0-9]+", (s or "").lower())
            if w not in STOP and len(w) > 2}


def shares(r) -> bool:
    a, b = _toks(r["term"]), _toks(r["parent"])
    return bool(a & b) or any(x.startswith(y) or y.startswith(x)
                              for x in a for y in b if min(len(x), len(y)) >= 4)


def selected(rows):
    out = []
    for r in rows:
        if r.get("unlisted") or not r.get("parent"):
            continue
        sim = r.get("similarity") or 0
        if r["relation"] == "is_a" and r["abstracts"] >= 2 and (shares(r) or sim >= 0.65):
            out.append(r)
        elif r["relation"] == "same" and sim >= 0.75:
            out.append(r)
    return out


def _usage() -> float:
    req = urllib.request.Request("https://openrouter.ai/api/v1/credits",
                                 headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return float(json.load(r)["data"]["total_usage"])


def _opt(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def main(argv: list[str]) -> int:
    import hashlib
    from wound_ontology.orchestrator import Orchestrator

    rows = selected(json.loads(SRC.read_text(encoding="utf-8"))["rows"])
    for r in rows:
        r["id"] = "v" + hashlib.sha1(f'{r["term"]}|{r["relation"]}|{r["parent"]}'.encode()).hexdigest()[:10]
    done = {}
    if OUT.exists():
        done = {x["id"]: x for x in json.loads(OUT.read_text(encoding="utf-8"))["rows"]}
    todo = [r for r in rows if r["id"] not in done]
    print(f"[verify] {len(rows):,} placements selected; {len(done):,} already checked; {len(todo):,} to ask", flush=True)
    budget = float(_opt(argv, "--budget-usd", "0.8"))
    p = Orchestrator()

    def prompt_for(batch):
        lines = []
        for r in batch:
            if r["relation"] == "same":
                st = f'"{r["term"]}" means exactly the same thing as "{r["parent"]}" (synonyms).'
            else:
                st = f'"{r["term"]}" is a kind of "{r["parent"]}" (every {r["term"]} is a {r["parent"]}).'
            lines.append(f'- id {r["id"]}: {st} [the term is typed {r["category"]}]')
        return ("You are checking statements for a wound-care ontology. For EACH statement answer "
                "\"yes\" only if it is true as written, in the biomedical sense. Answer \"no\" if it is "
                "false, only partly true, a part-of or associated-with relation rather than a kind-of, "
                "or if the term is too vague to be a kind of the class. Return every id with "
                "answer yes or no and a short reason.\n\nSTATEMENTS:\n" + "\n".join(lines))

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
                print(f"[verify]   batch failed: {type(exc).__name__}: {exc}", flush=True)
                return
        by = {r["id"]: r for r in batch}
        for v in res.verdicts:
            r = by.get((v.id or "").strip())
            a = (v.answer or "").strip().lower()
            if r is None or a not in ("yes", "no"):
                continue
            done[r["id"]] = {"id": r["id"], "term": r["term"], "relation": r["relation"],
                             "parent": r["parent"], "parent iri": r["parent iri"],
                             "category": r["category"], "abstracts": r["abstracts"],
                             "similarity": r["similarity"], "answer": a, "reason": v.reason or ""}

    def save():
        OUT.write_text(json.dumps({"measured": time.strftime("%Y-%m-%d %H:%M"),
                                   "rows": sorted(done.values(), key=lambda x: (-x["abstracts"], x["term"]))},
                                  ensure_ascii=False, indent=1), encoding="utf-8")

    size = int(_opt(argv, "--batch-size", "20"))
    batches = [todo[i:i + size] for i in range(0, len(todo), size)]
    u0 = _usage()

    async def drive():
        for i in range(0, len(batches), 40):
            await asyncio.gather(*(run(b) for b in batches[i:i + 40]))
            save()
            spent = _usage() - u0
            n = min(i + 40, len(batches))
            print(f"[verify]   {n}/{len(batches)} batches, {len(done):,} checked, ${spent:.2f} spent, "
                  f"{failed} failed", flush=True)
            if n < len(batches) and spent * len(batches) / n > budget:
                print(f"[verify] STOP: projected ${spent * len(batches) / n:.2f} > budget ${budget:.2f}", flush=True)
                return

    asyncio.run(drive())
    save()
    back = json.loads(OUT.read_text(encoding="utf-8"))["rows"]
    from collections import Counter
    c = Counter((x["relation"], x["answer"]) for x in back)
    have = {x["id"] for x in back}
    missing = sum(1 for r in rows if r["id"] not in have)
    stale = len(have - {r["id"] for r in rows})
    print(f"[verify] written and read back: {len(back):,} verdicts {dict(c)}; {missing} not yet answered; "
          f"{stale} answer rows that are no longer selected (kept, not used)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
