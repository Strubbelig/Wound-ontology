"""Validate PubMed search queries for wound-ontology scope using Claude Haiku.

For every query:
  1. Fetch a small sample of abstracts from PubMed.
  2. Ask Claude Haiku if the sample is within wound-ontology scope.
  3. If it fails → Haiku revises the query → retry (up to max_retries).
  4. Return a list of QueryReport objects and optionally write a JSON report.
"""

from __future__ import annotations

import json
import os
import textwrap
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import requests as _requests

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
  • Wound etiology and risk factors in patients
  • Wound care outcomes (healing rate, amputation, QoL, cost)
  • Clinical guidelines and care pathways for wound management

OUT OF SCOPE:
  • Animal experiments or in vitro / cell-line studies with no clinical arm
  • General surgery outcomes unrelated to wounds
  • Dermatology topics not related to wounds (e.g. acne, psoriasis)
  • Pharmacology studies with no wound end-point
  • Radiology / imaging not focused on wound assessment
"""

_EVALUATE_PROMPT = """
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

_REVISE_PROMPT = """
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

_OPENROUTER_MODEL = "anthropic/claude-haiku-4-5"
_OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"


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


class PubMedQueryValidator:
    """Validate and optionally revise PubMed queries for wound-ontology scope."""

    def __init__(self, entrez_email: str, api_key: str) -> None:
        self.entrez_email = entrez_email
        self.api_key      = api_key

    # ── PubMed helpers ────────────────────────────────────────────────────────

    def _fetch_sample(self, query: str, n: int) -> list[dict]:
        from Bio import Entrez, Medline
        Entrez.email = self.entrez_email
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

    @staticmethod
    def _format_abstracts(abstracts: list[dict]) -> str:
        parts = []
        for i, a in enumerate(abstracts, 1):
            title    = textwrap.fill(a["title"],    width=80, initial_indent="  ")
            abstract = textwrap.fill(a["abstract"], width=80, initial_indent="  ")
            parts.append(f"[{i}] {title}\n{abstract}")
        return "\n\n".join(parts)

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _call_haiku(self, prompt: str) -> str:
        resp = _requests.post(
            url=_OPENROUTER_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": _OPENROUTER_MODEL,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def _evaluate(self, query: str, abstracts: list[dict]) -> AttemptResult:
        prompt = _EVALUATE_PROMPT.format(
            scope=SCOPE_DESCRIPTION,
            query=query,
            n=len(abstracts),
            abstracts=self._format_abstracts(abstracts),
        )
        raw = self._call_haiku(prompt)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(raw)
            return AttemptResult(
                query=query, n_fetched=len(abstracts),
                verdict=data.get("verdict", "FAIL"),
                score=int(data.get("score", 0)),
                reason=data.get("reason", ""),
                problem=data.get("problem"),
            )
        except json.JSONDecodeError:
            return AttemptResult(
                query=query, n_fetched=len(abstracts),
                verdict="ERROR", score=0,
                reason=f"LLM returned unparseable JSON: {raw[:120]}",
                problem="JSON parse failure",
            )

    def _revise(self, query: str, problem: str) -> str:
        prompt = _REVISE_PROMPT.format(
            scope=SCOPE_DESCRIPTION, query=query, problem=problem,
        )
        return self._call_haiku(prompt).strip()

    # ── Core validation loop ──────────────────────────────────────────────────

    def validate_query(
        self,
        query: str,
        sample_n: int = 5,
        max_retries: int = 2,
        delay: float = 0.4,
    ) -> QueryReport:
        """Validate one query, retrying with Haiku-revised versions on failure."""
        report = QueryReport(
            original_query=query, final_query=query, final_verdict="FAIL"
        )
        current_query = query

        for attempt in range(max_retries + 1):
            label = "initial" if attempt == 0 else f"retry {attempt}"
            print(f"  [{label}] fetching {sample_n} abstracts …", end=" ", flush=True)

            abstracts = self._fetch_sample(current_query, sample_n)
            time.sleep(delay)

            if not abstracts:
                print("NO RESULTS")
                result = AttemptResult(
                    query=current_query, n_fetched=0,
                    verdict="NO_RESULTS", score=0,
                    reason="Query returned 0 abstracts — likely syntax error or over-restriction.",
                    problem="Query returns no results",
                )
                report.attempts.append(result)
                if attempt < max_retries:
                    print("  → revising query (Haiku) …")
                    current_query = self._revise(current_query, "Query returns no results")
                    print(f"    revised: {current_query[:100]}…")
                continue

            print("evaluating scope (Haiku) …", end=" ", flush=True)
            result = self._evaluate(current_query, abstracts)
            report.attempts.append(result)

            icon = "✓" if result.verdict == "PASS" else "✗"
            print(f"{icon} {result.verdict}  score={result.score}/10  — {result.reason}")

            if result.verdict == "PASS":
                report.final_query   = current_query
                report.final_verdict = "PASS"
                break

            if attempt < max_retries and result.problem:
                print(f"  → revising query (Haiku): {result.problem}")
                current_query = self._revise(current_query, result.problem)
                print(f"    revised: {current_query[:120]}")
            else:
                report.final_query   = current_query
                report.final_verdict = result.verdict

        return report

    def run(
        self,
        queries: list[str],
        sample_n: int = 5,
        max_retries: int = 2,
        delay: float = 0.4,
        out_path: str | Path | None = None,
    ) -> list[QueryReport]:
        """Validate all *queries* and write a JSON report to *out_path*.

        Args:
            queries:     List of PubMed query strings.
            sample_n:    Abstracts per query to sample.
            max_retries: Max revision attempts per failing query.
            delay:       Seconds between Entrez calls.
            out_path:    Path for the JSON report (optional).
        """
        print(f"\n{'═'*72}")
        print(f"  Wound Ontology — PubMed Query Validator  [{_OPENROUTER_MODEL}]")
        print(f"  {len(queries)} queries  ·  sample={sample_n}  ·  max_retries={max_retries}")
        print(f"{'═'*72}\n")

        reports: list[QueryReport] = []
        for idx, query in enumerate(queries, 1):
            print(f"[{idx:02d}/{len(queries):02d}] {query[:90]}{'…' if len(query) > 90 else ''}")
            reports.append(self.validate_query(query, sample_n, max_retries, delay))
            print()

        # Summary
        passed     = [r for r in reports if r.final_verdict == "PASS"]
        failed     = [r for r in reports if r.final_verdict == "FAIL"]
        no_results = [r for r in reports if r.final_verdict == "NO_RESULTS"]
        errors     = [r for r in reports if r.final_verdict == "ERROR"]
        revised    = [r for r in reports if r.final_query != r.original_query]

        print(f"\n{'═'*72}")
        print(f"  Summary")
        print(f"{'═'*72}")
        print(f"  PASS        : {len(passed):3d}")
        print(f"  FAIL        : {len(failed):3d}")
        print(f"  NO_RESULTS  : {len(no_results):3d}")
        print(f"  ERROR       : {len(errors):3d}")
        print(f"  Revised     : {len(revised):3d}")

        if revised and any(r.final_verdict == "PASS" for r in revised):
            print("\n  ── Successful revisions (copy back to pubmed_search.py) ────")
            for r in revised:
                if r.final_verdict == "PASS":
                    print(f"\n  ORIGINAL : {r.original_query[:80]}")
                    print(f"  REVISED  : {r.final_query}")

        if out_path:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps([asdict(r) for r in reports], indent=2, ensure_ascii=False)
            )
            print(f"\n  Full report saved → {out_path}")

        print(f"{'═'*72}\n")
        return reports
