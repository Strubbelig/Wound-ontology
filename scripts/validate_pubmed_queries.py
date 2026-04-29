"""
validate_pubmed_queries.py
--------------------------
For every query in config/pubmed_search.py:
  1. Fetch a small sample of abstracts from PubMed.
  2. Ask Gemini if the sample is within the wound-ontology scope.
  3. If it fails scope review → Gemini revises the query → retry (up to MAX_RETRIES).
  4. Write a JSON report and print a summary table.

Usage
-----
    python scripts/validate_pubmed_queries.py [--sample N] [--retries N] [--out PATH]

Requirements
------------
    pip install biopython anthropic python-dotenv
    ENTREZ_EMAIL and ANTHROPIC_API_KEY must be set (env or .env).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ── Path setup ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import requests as _requests
from Bio import Entrez, Medline

from config.pubmed_search import PUBMED_SEARCH


# ── Constants ──────────────────────────────────────────────────────────────────

SCOPE_DESCRIPTION = """
You are evaluating PubMed search results for a clinical wound ontology.

SCOPE — abstracts MUST be about one or more of:
  • Wound types (pressure injury, diabetic foot ulcer, venous ulcer, surgical
    wound, burn, traumatic wound, etc.) in HUMAN patients
  • Wound anatomy / tissue components (wound bed, granulation tissue, eschar,
    slough, wound edge, periwound skin, tissue depth / layers)
  • Wound characteristics (exudate, infection status, depth, chronicity, pain,
    odour, size, healing stage)
  • Wound assessment tools and classification systems
  • Wound management: debridement, dressings, NPWT, antimicrobials, advanced
    therapies (skin substitutes, growth factors, HBO, LLLT)
  • Wound healing biology ONLY when studied in clinical samples or patients
    (e.g. tissue biopsy studies, observational clinical studies)
  • Wound etiology and risk factors in patients
  • Wound care outcomes (healing rate, amputation, QoL, cost)
  • Clinical guidelines and care pathways for wound management

OUT OF SCOPE:
  • Animal experiments or in vitro / cell-line studies with no clinical arm
  • General surgery outcomes unrelated to wounds (e.g. anastomotic leak)
  • Dermatology topics not related to wounds (e.g. acne, psoriasis)
  • Pharmacology studies with no wound end-point
  • Radiology / imaging not focused on wound assessment
"""

EVALUATE_PROMPT = """
{scope}

=== QUERY UNDER REVIEW ===
{query}

=== SAMPLE ABSTRACTS ({n} retrieved) ===
{abstracts}

=== TASK ===
Assess whether this query reliably retrieves abstracts within scope.

Respond with EXACTLY this JSON (no markdown fences):
{{
  "verdict": "PASS" or "FAIL",
  "score": <0-10 integer; 10 = perfectly on-scope>,
  "reason": "<one concise sentence>",
  "problem": "<if FAIL: what is wrong with the query, otherwise null>"
}}
"""

REVISE_PROMPT = """
{scope}

=== ORIGINAL QUERY (FAILED scope review) ===
{query}

=== SCOPE PROBLEM IDENTIFIED ===
{problem}

=== TASK ===
Rewrite the PubMed query to fix the problem while keeping the same clinical intent.
Rules:
- Use valid PubMed/Entrez syntax (MeSH tags [MeSH Terms], field tags [tiab], etc.)
- Keep the human-only filter:
  NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms])
  NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])
- Do NOT wrap the result in markdown fences or quotes.
- Output ONLY the raw revised query string, nothing else.
"""


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class AttemptResult:
    query: str
    n_fetched: int
    verdict: str          # "PASS" | "FAIL" | "NO_RESULTS" | "ERROR"
    score: int
    reason: str
    problem: Optional[str] = None


@dataclass
class QueryReport:
    original_query: str
    final_query: str
    final_verdict: str    # "PASS" | "FAIL" | "NO_RESULTS" | "ERROR"
    attempts: list[AttemptResult] = field(default_factory=list)


# ── PubMed helpers ─────────────────────────────────────────────────────────────

def _fetch_sample(query: str, n: int, email: str) -> list[dict]:
    """Return up to *n* {title, abstract} dicts for *query*."""
    Entrez.email = email
    try:
        with Entrez.esearch(db="pubmed", term=query, retmax=n, sort="relevance") as h:
            id_list = Entrez.read(h)["IdList"]
    except Exception as exc:
        print(f"    [Entrez.esearch error] {exc}")
        return []

    if not id_list:
        return []

    try:
        with Entrez.efetch(db="pubmed", id=id_list, rettype="medline", retmode="text") as h:
            records = list(Medline.parse(h))
    except Exception as exc:
        print(f"    [Entrez.efetch error] {exc}")
        return []

    return [
        {"title": r.get("TI", ""), "abstract": r.get("AB", "")}
        for r in records if r.get("AB")
    ]


def _format_abstracts(abstracts: list[dict]) -> str:
    parts = []
    for i, a in enumerate(abstracts, 1):
        title    = textwrap.fill(a["title"],    width=80, initial_indent="  ")
        abstract = textwrap.fill(a["abstract"], width=80, initial_indent="  ")
        parts.append(f"[{i}] {title}\n{abstract}")
    return "\n\n".join(parts)


# ── LLM helpers ────────────────────────────────────────────────────────────────

_OPENROUTER_MODEL = "anthropic/claude-haiku-4-5"
_OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"


def _call_haiku(api_key: str, prompt: str) -> str:
    """Call Claude Haiku via OpenRouter using requests."""
    resp = _requests.post(
        url=_OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": _OPENROUTER_MODEL,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _evaluate(api_key: str, query: str, abstracts: list[dict]) -> AttemptResult:
    """Ask Claude if the abstracts are in scope. Returns AttemptResult."""
    prompt = EVALUATE_PROMPT.format(
        scope=SCOPE_DESCRIPTION,
        query=query,
        n=len(abstracts),
        abstracts=_format_abstracts(abstracts),
    )
    raw = _call_haiku(api_key, prompt)

    # Strip accidental markdown fences
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(raw)
        return AttemptResult(
            query=query,
            n_fetched=len(abstracts),
            verdict=data.get("verdict", "FAIL"),
            score=int(data.get("score", 0)),
            reason=data.get("reason", ""),
            problem=data.get("problem"),
        )
    except json.JSONDecodeError:
        return AttemptResult(
            query=query,
            n_fetched=len(abstracts),
            verdict="ERROR",
            score=0,
            reason=f"LLM returned unparseable JSON: {raw[:120]}",
            problem="JSON parse failure",
        )


def _revise(api_key: str, query: str, problem: str) -> str:
    """Ask Haiku to rewrite the query to fix the identified problem."""
    prompt = REVISE_PROMPT.format(
        scope=SCOPE_DESCRIPTION,
        query=query,
        problem=problem,
    )
    return _call_haiku(api_key, prompt).strip()


# ── Core validation loop ───────────────────────────────────────────────────────

def validate_query(
    query: str,
    *,
    email: str,
    api_key: str,
    sample_n: int,
    max_retries: int,
    delay: float,
) -> QueryReport:
    report = QueryReport(original_query=query, final_query=query, final_verdict="FAIL")
    current_query = query

    for attempt in range(max_retries + 1):
        label = "initial" if attempt == 0 else f"retry {attempt}"
        print(f"  [{label}] fetching {sample_n} abstracts …", end=" ", flush=True)

        abstracts = _fetch_sample(current_query, sample_n, email)
        time.sleep(delay)  # be polite to NCBI

        if not abstracts:
            print("NO RESULTS")
            result = AttemptResult(
                query=current_query,
                n_fetched=0,
                verdict="NO_RESULTS",
                score=0,
                reason="Query returned 0 abstracts — likely a syntax error or over-restricted query.",
                problem="Query returns no results",
            )
            report.attempts.append(result)
            if attempt < max_retries:
                print(f"  → revising query (Haiku) …")
                current_query = _revise(api_key, current_query, "Query returns no results")
                print(f"    revised: {current_query[:100]}…")
            continue

        print(f"evaluating scope (Haiku) …", end=" ", flush=True)
        result = _evaluate(api_key, current_query, abstracts)
        report.attempts.append(result)

        icon = "✓" if result.verdict == "PASS" else "✗"
        print(f"{icon} {result.verdict}  score={result.score}/10  — {result.reason}")

        if result.verdict == "PASS":
            report.final_query   = current_query
            report.final_verdict = "PASS"
            break

        if attempt < max_retries and result.problem:
            print(f"  → revising query (Haiku): {result.problem}")
            current_query = _revise(api_key, current_query, result.problem)
            print(f"    revised: {current_query[:120]}")
        else:
            report.final_query   = current_query
            report.final_verdict = result.verdict

    return report


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate pubmed_search.py queries for scope.")
    parser.add_argument("--sample",  type=int, default=5,  help="Abstracts per query to sample (default 5)")
    parser.add_argument("--retries", type=int, default=2,  help="Max retries per failing query (default 2)")
    parser.add_argument("--delay",   type=float, default=0.4, help="Seconds between Entrez calls (default 0.4)")
    parser.add_argument("--out",     type=str, default="scripts/query_validation_report.json",
                        help="Output JSON report path")
    args = parser.parse_args()

    email = os.getenv("ENTREZ_EMAIL", "")
    if not email:
        sys.exit("❌  ENTREZ_EMAIL is not set. Add it to .env or export it.")

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        sys.exit("❌  OPENROUTER_API_KEY is not set. Add it to .env or export it.")

    queries = PUBMED_SEARCH
    print(f"\n{'═'*72}")
    print(f"  Wound Ontology — PubMed Query Validator  [{_OPENROUTER_MODEL} via OpenRouter]")
    print(f"  {len(queries)} queries  ·  sample={args.sample}  ·  max_retries={args.retries}")
    print(f"{'═'*72}\n")

    reports: list[QueryReport] = []

    for idx, query in enumerate(queries, 1):
        print(f"[{idx:02d}/{len(queries):02d}] {query[:90]}{'…' if len(query) > 90 else ''}")
        report = validate_query(
            query,
            email=email,
            api_key=api_key,
            sample_n=args.sample,
            max_retries=args.retries,
            delay=args.delay,
        )
        reports.append(report)
        print()

    # ── Summary table ──────────────────────────────────────────────────────────
    passed      = [r for r in reports if r.final_verdict == "PASS"]
    failed      = [r for r in reports if r.final_verdict == "FAIL"]
    no_results  = [r for r in reports if r.final_verdict == "NO_RESULTS"]
    errors      = [r for r in reports if r.final_verdict == "ERROR"]
    revised     = [r for r in reports if r.final_query != r.original_query]

    print(f"\n{'═'*72}")
    print(f"  Summary")
    print(f"{'═'*72}")
    print(f"  PASS        : {len(passed):3d}")
    print(f"  FAIL        : {len(failed):3d}")
    print(f"  NO_RESULTS  : {len(no_results):3d}")
    print(f"  ERROR       : {len(errors):3d}")
    print(f"  Revised     : {len(revised):3d}  (query was rewritten at least once)")
    print()

    if failed or no_results or errors:
        print("  ── Queries needing attention ──────────────────────────────────────")
        for r in failed + no_results + errors:
            last = r.attempts[-1]
            print(f"  [{r.final_verdict}] {r.original_query[:70]}…")
            print(f"         → {last.reason}")
            if r.final_query != r.original_query:
                print(f"         revised to: {r.final_query[:70]}…")
            print()

    if revised and any(r.final_verdict == "PASS" for r in revised):
        print("  ── Successful revisions (copy these back to pubmed_search.py) ────")
        for r in revised:
            if r.final_verdict == "PASS":
                print(f"\n  ORIGINAL : {r.original_query[:80]}")
                print(f"  REVISED  : {r.final_query}")
        print()

    # ── JSON report ────────────────────────────────────────────────────────────
    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            [asdict(r) for r in reports],
            f, indent=2, ensure_ascii=False,
        )
    print(f"  Full report saved → {out_path}")
    print(f"{'═'*72}\n")


if __name__ == "__main__":
    main()
