"""Tests for alignment.aligner."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from wound_ontology.alignment.aligner import (
    Aligner,
    AlignmentResult,
    MappedPair,
    _norm,
    _xref_id,
)
from wound_ontology.alignment.target_loader import TargetConcept

WOND    = Namespace("http://purl.obolibrary.org/obo/WOND_")
OBOANN  = Namespace("http://www.geneontology.org/formats/oboInOwl#")
HAS_XREF = OBOANN["hasDbXref"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm_test():
    assert _norm("  Wound  Healing  ") == "wound healing"


def _write_source_owl(tmp_path: Path, classes: list[tuple[str, str]]) -> Path:
    """Write a minimal Turtle OWL with WOND classes: [(iri_suffix, label), ...]."""
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


def _mock_embedder(labels: list[str], dim: int = 8) -> MagicMock:
    rng = np.random.default_rng(42)
    emb = MagicMock()
    def _embed(texts):
        vecs = rng.random((len(texts), dim)).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / norms
    emb.embed.side_effect = _embed
    return emb


# ── _xref_id ──────────────────────────────────────────────────────────────────

class TestXrefId:
    def test_snomed(self):
        assert _xref_id("http://snomed.info/id/12345") == "SNOMEDCT:12345"

    def test_obo(self):
        assert _xref_id("http://purl.obolibrary.org/obo/BFO_0000040") == "BFO:0000040"

    def test_unknown_passthrough(self):
        iri = "http://example.org/X"
        assert _xref_id(iri) == iri


# ── Aligner construction ──────────────────────────────────────────────────────

class TestAlignerInit:
    def test_raises_if_source_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Aligner(tmp_path / "missing.owl")

    def test_accepts_valid_source(self, tmp_path):
        owl = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        aligner = Aligner(owl)
        assert aligner.source_owl == owl


# ── align (lexical) ───────────────────────────────────────────────────────────

class TestAlignLexical:
    def _aligner(self, tmp_path):
        owl = _write_source_owl(tmp_path, [
            ("0000001", "Wound Healing"),
            ("0000002", "Chronic Wound"),
        ])
        return Aligner(owl, embedder=None)

    def test_exact_match_maps(self, tmp_path):
        aligner = self._aligner(tmp_path)
        target  = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        result = aligner.align(target, method="lexical", close_thresh=0.99)
        assert len(result.mappings) == 1
        assert result.mappings[0].method == "exact"
        assert result.mappings[0].score == 1.0

    def test_unmatched_source_reported(self, tmp_path):
        aligner = self._aligner(tmp_path)
        target  = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        result = aligner.align(target, method="lexical", close_thresh=0.99)
        assert len(result.unmatched_source) == 1  # "Chronic Wound" unmatched

    def test_no_match_below_threshold(self, tmp_path):
        aligner = self._aligner(tmp_path)
        target  = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Something Else", "parent_code": ""},
        ])
        result = aligner.align(target, method="lexical", close_thresh=0.99)
        assert result.mappings == []
        assert len(result.unmatched_source) == 2

    def test_synonym_match(self, tmp_path):
        aligner = self._aligner(tmp_path)
        target  = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Different Label",
             "synonyms": ["Wound Healing"], "parent_code": ""},
        ])
        result = aligner.align(target, method="lexical", close_thresh=0.99)
        assert len(result.mappings) == 1

    def test_candidates_populated(self, tmp_path):
        aligner = self._aligner(tmp_path)
        target  = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
            {"snomed_code": "X2", "preferred_name": "Scar",          "parent_code": ""},
        ])
        result = aligner.align(target, method="lexical", top_k=2, close_thresh=0.99)
        assert len(result.candidates) > 0

    def test_result_carries_target_concepts(self, tmp_path):
        aligner = self._aligner(tmp_path)
        target  = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        result = aligner.align(target, method="lexical")
        assert len(result.target_concepts) == 1
        assert result.target_concepts[0].label == "Wound Healing"


# ── align (sapbert) ───────────────────────────────────────────────────────────

class TestAlignSapbert:
    def test_sapbert_called(self, tmp_path):
        owl = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Care", "parent_code": ""},
        ])
        embedder = _mock_embedder(["Wound Healing", "Wound Care"])
        aligner  = Aligner(owl, embedder=embedder)
        aligner.align(target, method="sapbert", close_thresh=0.0)
        embedder.embed.assert_called_once()

    def test_lexical_only_skips_embedder(self, tmp_path):
        owl = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        embedder = MagicMock()
        aligner  = Aligner(owl, embedder=embedder)
        aligner.align(target, method="lexical")
        embedder.embed.assert_not_called()


# ── extend ────────────────────────────────────────────────────────────────────

class TestExtend:
    def _result_with_one_unmatched(self, tmp_path) -> tuple[Aligner, AlignmentResult]:
        owl = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
            {"snomed_code": "X2", "preferred_name": "Chronic Wound",  "parent_code": "X1"},
        ])
        aligner = Aligner(owl)
        result  = aligner.align(target, method="lexical", close_thresh=0.99)
        return aligner, result

    def test_dry_run_no_file(self, tmp_path):
        aligner, result = self._result_with_one_unmatched(tmp_path)
        out = tmp_path / "out.owl"
        stats = aligner.extend(result, out, dry_run=True)
        assert not out.exists()
        assert stats["new_stubs"] == 1

    def test_stub_added(self, tmp_path):
        aligner, result = self._result_with_one_unmatched(tmp_path)
        out = tmp_path / "out.owl"
        stats = aligner.extend(result, out, dry_run=False)
        assert stats["new_stubs"] == 1
        g = Graph()
        g.parse(str(out))
        labels = {str(o) for _, _, o in g.triples((None, RDFS.label, None))}
        assert "Chronic Wound" in labels

    def test_parent_resolved_to_matched_source(self, tmp_path):
        aligner, result = self._result_with_one_unmatched(tmp_path)
        out = tmp_path / "out.owl"
        stats = aligner.extend(result, out, dry_run=False)
        assert stats["parent_resolved"] == 1
        assert stats["parent_owlthing"] == 0

    def test_no_unmatched_writes_source_unchanged(self, tmp_path):
        owl = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        aligner = Aligner(owl)
        result  = aligner.align(target, method="lexical", close_thresh=0.99)
        out = tmp_path / "out.owl"
        stats = aligner.extend(result, out, dry_run=False)
        assert stats["new_stubs"] == 0


# ── enrich ────────────────────────────────────────────────────────────────────

class TestEnrich:
    def _result_with_match(self, tmp_path) -> tuple[Aligner, AlignmentResult]:
        owl = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing",
             "parent_code": "", "definition": "The process of wound repair."},
        ])
        aligner = Aligner(owl)
        result  = aligner.align(target, method="lexical", close_thresh=0.99)
        return aligner, result

    def test_xref_added(self, tmp_path):
        aligner, result = self._result_with_match(tmp_path)
        out = tmp_path / "out.owl"
        stats = aligner.enrich(result, out, dry_run=False)
        assert stats["added_xrefs"] == 1
        g = Graph()
        g.parse(str(out))
        xrefs = {str(o) for _, _, o in g.triples((None, HAS_XREF, None))}
        assert "SNOMEDCT:X1" in xrefs

    def test_definition_added(self, tmp_path):
        aligner, result = self._result_with_match(tmp_path)
        out = tmp_path / "out.owl"
        stats = aligner.enrich(result, out, dry_run=False)
        assert stats["added_defs"] == 1

    def test_dry_run_no_write(self, tmp_path):
        aligner, result = self._result_with_match(tmp_path)
        out = tmp_path / "out.owl"
        aligner.enrich(result, out, dry_run=True)
        assert not out.exists()

    def test_reads_extended_owl_if_exists(self, tmp_path):
        aligner, result = self._result_with_match(tmp_path)
        out = tmp_path / "out.owl"
        aligner.extend(result, out, dry_run=False)
        stats = aligner.enrich(result, out, dry_run=False)
        assert stats["added_xrefs"] == 1


# ── write_candidates / write_sssom ────────────────────────────────────────────

class TestWriteOutputs:
    def _result(self, tmp_path) -> tuple[Aligner, AlignmentResult]:
        owl = _write_source_owl(tmp_path, [("0000001", "Wound Healing")])
        target = _write_snomed_json(tmp_path, [
            {"snomed_code": "X1", "preferred_name": "Wound Healing", "parent_code": ""},
        ])
        aligner = Aligner(owl)
        return aligner, aligner.align(target, method="lexical")

    def test_candidates_csv_created(self, tmp_path):
        aligner, result = self._result(tmp_path)
        out = tmp_path / "candidates.csv"
        aligner.write_candidates(result, out)
        assert out.exists()
        assert "source_iri" in out.read_text()

    def test_sssom_tsv_created(self, tmp_path):
        aligner, result = self._result(tmp_path)
        out = tmp_path / "alignment.sssom.tsv"
        aligner.write_sssom(result, out)
        assert out.exists()
        content = out.read_text()
        assert "subject_id" in content
        assert "SSSOM" in content
