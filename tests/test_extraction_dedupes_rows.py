"""One abstract, one model call — however many queries found it.

The abstract database is row-keyed: a paper matched by three PubMed queries is
three rows differing only in `query`. The store is PMID-keyed. `add_llm_extracts`
queued ROWS, so the same abstract went to the model once per query that found
it. Measured 2026-09-11: 193 calls for 136 PMIDs on the 606-PMID corpus, and
7,536 rows queued for 5,562 PMIDs on the cap-200 fetch -- a quarter of the run
paid for nothing, and the second extraction of a PMID silently overwrote the
first with a fresh, possibly different, model answer.
"""
import asyncio

import pandas as pd
import pytest

from wound_ontology.store.concept_store import ConceptStore


class _FakeDM:
    def get_meta_stamp(self, _kind):
        return "meta", "stamp-1"


class _LLM:
    def __init__(self):
        self.abort_event = None
        self._consec_errors = 0
        self._max_consec_errors = 0


def _store(monkeypatch):
    s = ConceptStore.__new__(ConceptStore)
    s.dm = _FakeDM()
    s.file_name = "test_store"
    s._dict = {}
    monkeypatch.setattr(ConceptStore, "save", lambda self: None)
    monkeypatch.setattr(ConceptStore, "top_attributes", lambda self, n: [])
    return s


def _run(store, df, monkeypatch):
    """Run the schema-constrained path with a model that only counts calls."""
    calls: list[str] = []

    async def _fake_extract(_llm, text, meta_id):
        calls.append(text)
        return {"entities": {text.title(): {"is_a: material entity": 1.0}},
                "meta_stamp": meta_id}

    monkeypatch.setattr(
        "wound_ontology.store.concept_store._extract_schema_constrained",
        _fake_extract,
    )
    asyncio.run(store.add_llm_extracts(df, _LLM(), ["is_a"], batch_size=2))
    return calls


def test_a_paper_found_by_three_queries_is_extracted_once(monkeypatch):
    df = pd.DataFrame([
        {"pmid": 11, "query": "q1", "abstract": "venous leg ulcer"},
        {"pmid": 11, "query": "q2", "abstract": "venous leg ulcer"},
        {"pmid": 11, "query": "q3", "abstract": "venous leg ulcer"},
        {"pmid": 22, "query": "q1", "abstract": "pressure injury"},
    ])
    store = _store(monkeypatch)
    calls = _run(store, df, monkeypatch)
    assert len(calls) == 2, f"expected one call per PMID, got {len(calls)}"
    assert set(store.dict) == {"11", "22"}


def test_the_folded_duplicates_are_announced(monkeypatch, capsys):
    """The row count and the call count used to look alike; now the difference
    is printed so a 7,536-row run is understood as a 5,562-abstract run."""
    df = pd.DataFrame([
        {"pmid": 11, "query": "q1", "abstract": "a"},
        {"pmid": 11, "query": "q2", "abstract": "a"},
        {"pmid": 22, "query": "q1", "abstract": "b"},
    ])
    _run(_store(monkeypatch), df, monkeypatch)
    out = capsys.readouterr().out
    assert "2 new abstracts" in out
    assert "1 duplicate rows" in out


def test_no_duplicates_means_no_duplicate_message(monkeypatch, capsys):
    df = pd.DataFrame([{"pmid": 11, "query": "q1", "abstract": "a"}])
    _run(_store(monkeypatch), df, monkeypatch)
    assert "duplicate" not in capsys.readouterr().out


def test_pmids_already_in_the_store_are_still_skipped(monkeypatch):
    """Dedupe must sit on top of the resume behaviour, not replace it."""
    store = _store(monkeypatch)
    store._dict["11"] = {"entities": {"Already": {}}, "meta_stamp": "old"}
    df = pd.DataFrame([
        {"pmid": 11, "query": "q1", "abstract": "a"},
        {"pmid": 11, "query": "q2", "abstract": "a"},
        {"pmid": 22, "query": "q1", "abstract": "b"},
    ])
    calls = _run(store, df, monkeypatch)
    assert calls == ["b"]
    assert store.dict["11"]["meta_stamp"] == "old", "a stored PMID was re-extracted"
