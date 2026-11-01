"""An answer the caller cannot place is reported, never counted as silence.

`gate_scope_batch` exists because `classify_scope_batch` returns only the
out-of-scope names, so an omission and an in-scope judgement look identical and
`review_susp_entities` whitelisted both. Asking for a verdict per term makes
silence visible — and then the echo has to be matched back, or the fix reinvents
the bug one layer along. Both of these happened on 2026-09-25, in one run:

* asked `Kaplan-Meier analysis`, answered `Kaplan Meier analysis`: an
  exact-match filter dropped 320 of 400 judgements and reported them as silence;
* asked `"high-risk cohort"`, answered with the whole input LINE,
  `'"high-risk cohort" (in 2 abstracts): is_a: material entity'`: 1,126 of 3,848.
"""

import asyncio

import pytest

from wound_ontology.llm.llm_client import LLMClient
from wound_ontology.llm.schemas import GateBatchResponse, GateVerdict


def _client(reply: list[tuple[str, str, str]]) -> LLMClient:
    c = LLMClient.__new__(LLMClient)

    async def fake(func, *a, **kw):
        return GateBatchResponse(
            verdicts=[GateVerdict(term=t, verdict=v, reason=r) for t, v, r in reply])

    c._execute_with_retry = fake
    return c


def _ask(client, terms):
    return asyncio.run(client.gate_scope_batch([(t, 1, []) for t in terms]))


def test_an_exact_echo_places():
    got, stray = _ask(_client([("wound pain", "in", "a symptom")]), ["wound pain"])
    assert got == {"wound pain": ("in", "a symptom")} and stray == []


def test_a_case_variant_places():
    got, stray = _ask(_client([("Wound Pain", "in", "r")]), ["wound pain"])
    assert got == {"wound pain": ("in", "r")} and stray == []


def test_a_hyphen_variant_places():
    got, stray = _ask(_client([("Kaplan Meier analysis", "out", "statistics")]),
                      ["Kaplan-Meier analysis"])
    assert got == {"Kaplan-Meier analysis": ("out", "statistics")} and stray == []


def test_the_whole_input_line_places_on_its_quoted_span():
    echo = '"high-risk cohort" (in 2 abstracts): is_a: material entity'
    got, stray = _ask(_client([(echo, "out", "a study grouping")]), ["high-risk cohort"])
    assert got == {"high-risk cohort": ("out", "a study grouping")} and stray == []


def test_an_uppercase_verdict_places():
    got, _ = _ask(_client([("wound pain", "IN", "r")]), ["wound pain"])
    assert got["wound pain"][0] == "in"


def test_an_echo_naming_nothing_asked_is_returned_not_dropped():
    got, stray = _ask(_client([("something else entirely", "in", "r")]), ["wound pain"])
    assert got == {} and stray == ["something else entirely"]


def test_a_nonsense_verdict_is_returned_not_dropped():
    got, stray = _ask(_client([("wound pain", "maybe", "r")]), ["wound pain"])
    assert got == {}
    assert len(stray) == 1 and "maybe" in stray[0]


def test_a_term_the_model_never_mentions_gets_no_verdict():
    got, stray = _ask(_client([("wound pain", "in", "r")]), ["wound pain", "cohort"])
    assert set(got) == {"wound pain"} and stray == []


def test_the_quoted_span_does_not_place_a_term_that_was_not_asked():
    echo = '"something else" (in 2 abstracts): is_a: process'
    got, stray = _ask(_client([(echo, "out", "r")]), ["wound pain"])
    assert got == {} and stray == [echo]
