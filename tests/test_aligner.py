"""Tests for OntologyMapper — align / extend / enrich / write outputs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from rdflib import Graph, Namespace
from rdflib.namespace import RDFS

from wound_ontology.owl.ontology_mapper import (
    OntologyMapper,
    MapMatch,
    MapResult,
    _norm,
    _iri_to_xref,
)

WOND     = Namespace("http://purl.obolibrary.org/obo/WOND_")
OBOANN   = Namespace("http://www.geneontology.org/formats/oboInOwl#")
HAS_XREF = OBOANN["hasDbXref"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_source_owl(tmp_path: Path, classes: list[tuple[str, str]]) -> Path:
    lines = [
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix wond: <http://purl.obolibrary.org/obo/WOND_> .",
    ]
    for suffix, label in classes:
        lines.append(f'wond:{suffix} a owl:Class ; rdfs:label "{label}" .')
    p = tmp_path / "ground_truth.owl"
    p.write_text("\n".join(lines))
    return p


def _write_snomed_json(tmp_path: Path, concepts: list[dict]) -> Path:
    p = tmp_path / "snomed.json"
    p.write_text(json.dumps(concepts))
    return p


def _make_encode():
    """Return a callable that produces consistent random embeddings (8-dim)."""
    rng = np.random.default_rng(42)
    def _encode(texts):
        vecs = rng.random((len(texts), 8)).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / norms
    return _encode


# ── Module-level helpers ──────────────────────────────────────────────────────

def test_norm_strips_and_lowercases():
    assert _norm("  Wound  Healing  ") == "wound healing"


class TestIriToXref:
    def test_snomed(self):
        assert _iri_to_xref("http://snomed.info/id/12345") == "SNOMEDCT:12345"

    def test_obo(self):
        assert _iri_to_xref("http://purl.obolibrary.org/obo/BFO_0000040") == "BFO:0000040"

    def test_unknown_passthrough(self):
        iri = "http://example.org/X"
        assert _iri_to_xref(iri) == iri


# ── align (lexical) ───────────────────────────────────────────────────────────

class TestAlignLexical:
    def _setup(self, tmp_path, source_classes=None, target_concepts=None):
        source_classes  = source_classes or [
            ("0000001", "Wound Healing"),
            ("0000002", "Chronic Wound"),
        ]
        target_concepts = target_concepts or [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ]
        owl    = _write_source_owl(tmp_path, source_classes)
        target = _write_snomed_json(tmp_path, target_concepts)
        return OntologyMapper(), owl, target

    def test_raises_if_source_missing(self, tmp_path):
        mapper = OntologyMapper()
        target = _write_snomed_json(tmp_path, [])
        with pytest.raises(Exception):
            mapper.align(tmp_path / "missing.owl", target)

    def test_exact_match_maps(self, tmp_path):
        mapper, owl, target = self._setup(tmp_path)
        result = mapper.align(owl, target, method="lexical", threshold=0.99)
        assert len(result.matches) == 1
        assert result.matches[0].method == "lexical"
        assert result.matches[0].score == 1.0

    def test_unmatched_source_reported(self, tmp_path):
        mapper, owl, target = self._setup(tmp_path)
        result = mapper.align(owl, target, method="lexical", threshold=0.99)
        assert len(result.unmatched) == 1  # "Chronic Wound" unmatched

    def test_no_match_returns_empty(self, tmp_path):
        mapper, owl, _ = self._setup(tmp_path)
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Something Else", "parent_code": ""},
        ])
        result = mapper.align(owl, target, method="lexical", threshold=0.99)
        assert result.matches == []
        assert len(result.unmatched) == 2

    def test_synonym_match(self, tmp_path):
        mapper, owl, _ = self._setup(tmp_path)
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Different Label",
             "synonyms": ["Wound Healing"], "parent_code": ""},
        ])
        result = mapper.align(owl, target, method="lexical", threshold=0.99)
        assert len(result.matches) == 1

    def test_candidates_populated(self, tmp_path):
        mapper, owl, _ = self._setup(tmp_path)
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
            {"snomed_code": "X2", "preferred_name": "Scar",          "parent_code": ""},
        ])
        result = mapper.align(owl, target, method="lexical", top_k=2, threshold=0.99)
        assert len(result.candidates) > 0

    def test_result_carries_target_concepts(self, tmp_path):
        mapper, owl, target = self._setup(tmp_path)
        result = mapper.align(owl, target, method="lexical")
        assert len(result.target_concepts) == 1
        assert result.target_concepts[0].label == "Wound Healing"


# ── align (sapbert) ───────────────────────────────────────────────────────────

class TestAlignSapbert:
    def test_encode_called_for_sapbert(self, tmp_path, monkeypatch):
        owl    = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Care", "parent_code": ""},
        ])
        encode = MagicMock(side_effect=_make_encode())
        mapper = OntologyMapper()
        monkeypatch.setattr(mapper, "_get_encoder", lambda: encode)

        mapper.align(owl, target, method="sapbert", threshold=0.0)

        encode.assert_called_once()

    def test_lexical_skips_encoder(self, tmp_path, monkeypatch):
        owl    = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        encode = MagicMock()
        mapper = OntologyMapper()
        monkeypatch.setattr(mapper, "_get_encoder", lambda: encode)

        mapper.align(owl, target, method="lexical")

        encode.assert_not_called()


# ── extend ────────────────────────────────────────────────────────────────────

class TestExtend:
    def _result_with_one_unmatched(self, tmp_path):
        owl    = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
            {"snomed_code": "X2", "preferred_name": "Chronic Wound",  "parent_code": "X1"},
        ])
        mapper = OntologyMapper()
        result = mapper.align(owl, target, method="lexical", threshold=0.99)
        return mapper, result

    def test_dry_run_no_file(self, tmp_path):
        mapper, result = self._result_with_one_unmatched(tmp_path)
        out   = tmp_path / "out.owl"
        stats = mapper.extend(result, out, dry_run=True)
        assert not out.exists()
        assert stats["new_stubs"] == 1

    def test_stub_added(self, tmp_path):
        mapper, result = self._result_with_one_unmatched(tmp_path)
        out   = tmp_path / "out.owl"
        stats = mapper.extend(result, out, dry_run=False)
        assert stats["new_stubs"] == 1
        g = Graph()
        g.parse(str(out))
        labels = {str(o) for _, _, o in g.triples((None, RDFS.label, None))}
        assert "Chronic Wound" in labels

    def test_parent_resolved_to_matched_source(self, tmp_path):
        mapper, result = self._result_with_one_unmatched(tmp_path)
        out   = tmp_path / "out.owl"
        stats = mapper.extend(result, out, dry_run=False)
        assert stats["parent_resolved"] == 1
        assert stats["parent_owlthing"] == 0

    def test_no_unmatched_writes_no_stubs(self, tmp_path):
        owl    = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        mapper = OntologyMapper()
        result = mapper.align(owl, target, method="lexical", threshold=0.99)
        out    = tmp_path / "out.owl"
        stats  = mapper.extend(result, out, dry_run=False)
        assert stats["new_stubs"] == 0


# ── enrich ────────────────────────────────────────────────────────────────────

class TestEnrich:
    def _result_with_match(self, tmp_path):
        owl    = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing",
             "parent_code": "", "definition": "The process of wound repair."},
        ])
        mapper = OntologyMapper()
        result = mapper.align(owl, target, method="lexical", threshold=0.99)
        return mapper, result

    def test_xref_added(self, tmp_path):
        mapper, result = self._result_with_match(tmp_path)
        out   = tmp_path / "out.owl"
        stats = mapper.enrich(result, out, dry_run=False)
        assert stats["added_xrefs"] == 1
        g = Graph()
        g.parse(str(out))
        xrefs = {str(o) for _, _, o in g.triples((None, HAS_XREF, None))}
        assert "SNOMEDCT:X1" in xrefs

    def test_definition_added(self, tmp_path):
        mapper, result = self._result_with_match(tmp_path)
        out   = tmp_path / "out.owl"
        stats = mapper.enrich(result, out, dry_run=False)
        assert stats["added_defs"] == 1

    def test_dry_run_no_write(self, tmp_path):
        mapper, result = self._result_with_match(tmp_path)
        out = tmp_path / "out.owl"
        mapper.enrich(result, out, dry_run=True)
        assert not out.exists()

    def test_reads_extended_owl_if_exists(self, tmp_path):
        mapper, result = self._result_with_match(tmp_path)
        out = tmp_path / "out.owl"
        mapper.extend(result, out, dry_run=False)
        stats = mapper.enrich(result, out, dry_run=False)
        assert stats["added_xrefs"] == 1


# ── write_candidates / write_sssom ────────────────────────────────────────────

class TestWriteOutputs:
    def _result(self, tmp_path):
        owl    = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        mapper = OntologyMapper()
        return mapper, mapper.align(owl, target, method="lexical")

    def test_candidates_csv_created(self, tmp_path):
        mapper, result = self._result(tmp_path)
        out = tmp_path / "candidates.csv"
        mapper.write_candidates(result, out)
        assert out.exists()
        assert "source_iri" in out.read_text()

    def test_sssom_tsv_created(self, tmp_path):
        mapper, result = self._result(tmp_path)
        out = tmp_path / "alignment.sssom.tsv"
        mapper.write_sssom(result, out)
        assert out.exists()
        content = out.read_text()
        assert "subject_id" in content
        assert "SSSOM" in content
