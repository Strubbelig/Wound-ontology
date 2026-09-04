"""Vocabulary hints reach the deprecated free-text path only — and say so.

``add_llm_extracts`` computed ``top_attributes``/``extra_targets`` on every run
and passed them to ``llm.extract_entities``, which the schema-constrained path
never calls. On the default path the hints were therefore built and discarded,
and ``run_extract_to_store(use_bfo_attributes=True)`` loaded bfo.owl for them.
A knob that advertises an effect it no longer has is the silent-failure shape
this codebase keeps hitting, so the inertness is now stated, not implied.
"""
import asyncio
import inspect

import pandas as pd

from wound_ontology.store.concept_store import ConceptStore


class _FakeDM:
    def get_meta_stamp(self, _kind):
        return "meta", "stamp-1"


def _store(monkeypatch, calls):
    s = ConceptStore.__new__(ConceptStore)
    s.dm = _FakeDM()
    s.file_name = "test_store"
    s._dict = {}
    monkeypatch.setattr(ConceptStore, "save", lambda self: None)
    monkeypatch.setattr(
        ConceptStore, "top_attributes",
        lambda self, n: calls.append(n) or ["is_a: Wound"],
    )
    return s


class _LLM:
    """Records what the schema-constrained path hands the model."""
    def __init__(self):
        self.seen = []
        self.abort_event = None
        self._consec_errors = 0
        self._max_consec_errors = 0


def _abstracts():
    return pd.DataFrame([{"pmid": 1, "abstract": "chronic wound of the foot"}])


def _run(store, llm, monkeypatch, **kw):
    async def _fake_extract(_llm, text, meta_id):
        llm.seen.append(text)
        return {"entities": {"Chronic Wound": {"is_a: MaterialEntity": 1.0}},
                "meta_stamp": meta_id}

    monkeypatch.setattr(
        "wound_ontology.store.concept_store._extract_schema_constrained",
        _fake_extract,
    )
    asyncio.run(store.add_llm_extracts(_abstracts(), llm, ["is_a"], **kw))


def test_schema_path_does_not_build_vocab_hints(monkeypatch, capsys):
    calls: list[int] = []
    store = _store(monkeypatch, calls)
    _run(store, _LLM(), monkeypatch, extra_targets=["Material Entity"])

    assert calls == [], "top_attributes was computed for a path that never sends it"
    assert "1" in store.dict, "the abstract still has to be extracted and stored"


def test_supplying_inert_hints_is_announced(monkeypatch, capsys):
    """Silence would let a caller believe the hints reached the model."""
    store = _store(monkeypatch, [])
    _run(store, _LLM(), monkeypatch, extra_targets=["Material Entity"])

    out = capsys.readouterr().out
    assert "vocabulary hints are NOT sent" in out
    assert "deprecated free-text path only" in out


def test_legacy_path_still_builds_them(monkeypatch):
    """The correction must not disarm the path that genuinely uses the hints."""
    calls: list[int] = []
    store = _store(monkeypatch, calls)

    class _LegacyLLM(_LLM):
        async def extract_entities(self, text, preds, targets, attrs, **kw):
            self.seen.append((list(targets), list(attrs)))
            return []

    llm = _LegacyLLM()
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.run(store.add_llm_extracts(
            _abstracts(), llm, ["is_a"], extra_targets=["Material Entity"],
            max_vocab_hints=42, schema_constrained=False,
        ))

    assert calls == [42], "the free-text path must still receive vocab hints"
    targets, attrs = llm.seen[0]
    assert "Material Entity" in targets and "is_a: Wound" in attrs


def test_orchestrator_states_that_bfo_anchors_are_inert():
    """bfo.owl was loaded (~11s) per run purely to feed an ignored parameter."""
    import wound_ontology.orchestrator as orch

    src = inspect.getsource(orch.Orchestrator.run_extract_to_store)
    assert "OWLOntology.load" not in src, "bfo.owl is loaded for nothing"
    assert "has no effect" in src
    assert "inert" in orch.Orchestrator.run_extract_to_store.__doc__
