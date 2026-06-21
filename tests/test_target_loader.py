"""Tests for alignment.target_loader."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from wound_ontology.alignment.target_loader import (
    TargetConcept,
    load_target,
    _load_snomed_json,
    _load_obo,
    _load_owl,
)

OBO_BASE    = "http://purl.obolibrary.org/obo/"
SNOMED_BASE = "http://snomed.info/id/"


# ── SNOMED JSON loader ────────────────────────────────────────────────────────

class TestLoadSnomedJson:
    def _write(self, tmp_path: Path, data: list[dict]) -> Path:
        p = tmp_path / "snomed.json"
        p.write_text(json.dumps(data))
        return p

    def test_basic_concept(self, tmp_path):
        p = self._write(tmp_path, [{"snomed_code": "123", "preferred_name": "Wound", "parent_code": ""}])
        concepts = _load_snomed_json(p)
        assert len(concepts) == 1
        assert concepts[0].label == "Wound"
        assert concepts[0].iri == SNOMED_BASE + "123"

    def test_parent_iri(self, tmp_path):
        p = self._write(tmp_path, [{"snomed_code": "456", "preferred_name": "Chronic Wound", "parent_code": "123"}])
        concepts = _load_snomed_json(p)
        assert concepts[0].parent_iri == SNOMED_BASE + "123"

    def test_empty_parent_code_yields_none(self, tmp_path):
        p = self._write(tmp_path, [{"snomed_code": "1", "preferred_name": "X", "parent_code": ""}])
        assert _load_snomed_json(p)[0].parent_iri is None

    def test_synonyms(self, tmp_path):
        p = self._write(tmp_path, [{"snomed_code": "1", "preferred_name": "X", "synonyms": ["A", "B"]}])
        assert _load_snomed_json(p)[0].synonyms == ["A", "B"]

    def test_empty_list(self, tmp_path):
        p = self._write(tmp_path, [])
        assert _load_snomed_json(p) == []


# ── OBO loader ────────────────────────────────────────────────────────────────

OBO_TEXT = textwrap.dedent("""\
    format-version: 1.2

    [Term]
    id: GO:0008150
    name: biological_process
    def: "Any process pertinent to the functioning." [GOC:go_curators]
    synonym: "bio process" EXACT []
    is_a: GO:0003674 ! molecular_function

    [Term]
    id: GO:0000001
    name: obsolete term
    is_obsolete: true

    [Term]
    id: GO:0005575
    name: cellular_component
""")


class TestLoadObo:
    def test_parses_label(self, tmp_path):
        p = tmp_path / "go.obo"
        p.write_text(OBO_TEXT)
        concepts = _load_obo(p)
        labels = [c.label for c in concepts]
        assert "biological_process" in labels

    def test_parses_definition(self, tmp_path):
        p = tmp_path / "go.obo"
        p.write_text(OBO_TEXT)
        c = next(x for x in _load_obo(p) if x.label == "biological_process")
        assert c.definition is not None
        assert "pertinent" in c.definition

    def test_parses_synonym(self, tmp_path):
        p = tmp_path / "go.obo"
        p.write_text(OBO_TEXT)
        c = next(x for x in _load_obo(p) if x.label == "biological_process")
        assert "bio process" in c.synonyms

    def test_skips_obsolete(self, tmp_path):
        p = tmp_path / "go.obo"
        p.write_text(OBO_TEXT)
        labels = [c.label for c in _load_obo(p)]
        assert "obsolete term" not in labels

    def test_parses_parent(self, tmp_path):
        p = tmp_path / "go.obo"
        p.write_text(OBO_TEXT)
        c = next(x for x in _load_obo(p) if x.label == "biological_process")
        assert c.parent_iri == OBO_BASE + "GO_0003674"

    def test_no_parent_when_absent(self, tmp_path):
        p = tmp_path / "go.obo"
        p.write_text(OBO_TEXT)
        c = next(x for x in _load_obo(p) if x.label == "cellular_component")
        assert c.parent_iri is None

    def test_iri_format(self, tmp_path):
        p = tmp_path / "go.obo"
        p.write_text(OBO_TEXT)
        c = next(x for x in _load_obo(p) if x.label == "biological_process")
        assert c.iri == OBO_BASE + "GO_0008150"


# ── OWL loader ────────────────────────────────────────────────────────────────

OWL_TTL = textwrap.dedent("""\
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix obo: <http://purl.obolibrary.org/obo/> .

    obo:BFO_0000040 a owl:Class ;
        rdfs:label "material entity" ;
        rdfs:subClassOf obo:BFO_0000001 .

    obo:BFO_0000001 a owl:Class ;
        rdfs:label "entity" .
""")


class TestLoadOwl:
    def test_parses_label(self, tmp_path):
        p = tmp_path / "bfo.ttl"
        p.write_text(OWL_TTL)
        concepts = _load_owl(p)
        labels = [c.label for c in concepts]
        assert "material entity" in labels

    def test_iri_preserved(self, tmp_path):
        p = tmp_path / "bfo.ttl"
        p.write_text(OWL_TTL)
        c = next(x for x in _load_owl(p) if x.label == "material entity")
        assert "BFO_0000040" in c.iri

    def test_parent_iri(self, tmp_path):
        p = tmp_path / "bfo.ttl"
        p.write_text(OWL_TTL)
        c = next(x for x in _load_owl(p) if x.label == "material entity")
        assert c.parent_iri is not None
        assert "BFO_0000001" in c.parent_iri

    def test_skips_unlabelled_classes(self, tmp_path):
        content = "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n" \
                  "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n" \
                  "<http://example.org/X> a owl:Class .\n"
        p = tmp_path / "test.ttl"
        p.write_text(content)
        assert _load_owl(p) == []


# ── load_target dispatcher ────────────────────────────────────────────────────

class TestLoadTargetDispatch:
    def test_json(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps([{"snomed_code": "1", "preferred_name": "X"}]))
        concepts = load_target(p)
        assert concepts[0].label == "X"

    def test_obo(self, tmp_path):
        p = tmp_path / "go.obo"
        p.write_text(OBO_TEXT)
        concepts = load_target(p)
        assert any(c.label == "biological_process" for c in concepts)

    def test_owl(self, tmp_path):
        p = tmp_path / "bfo.ttl"
        p.write_text(OWL_TTL)
        concepts = load_target(p)
        assert any(c.label == "material entity" for c in concepts)

    def test_unsupported_raises(self, tmp_path):
        p = tmp_path / "file.csv"
        p.write_text("x")
        with pytest.raises(ValueError, match="Unsupported"):
            load_target(p)
