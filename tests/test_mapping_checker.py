"""Tests for wound_ontology.mappers.mapping_checker."""

from __future__ import annotations

import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from wound_ontology.mappers.mapping_checker import (
    check_mapping,
    load_latest_mapping,
    print_report,
    MERGE_THRESHOLD,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _unit(v: list[float]) -> np.ndarray:
    a = np.array(v, dtype=np.float32)
    return a / np.linalg.norm(a)


def _make_embedder(term_to_vec: dict[str, list[float]]) -> MagicMock:
    """Stub embedder: returns fixed unit vectors for a known vocabulary."""
    embedder = MagicMock()

    def _embed(texts: list[str]) -> np.ndarray:
        return np.vstack([_unit(term_to_vec[t]) for t in texts])

    embedder.embed.side_effect = _embed
    return embedder


# ── Tests for load_latest_mapping ─────────────────────────────────────────────

class TestLoadLatestMapping:
    def test_loads_most_recent(self, tmp_path):
        older = tmp_path / "term_mapping_2025-01-01_00-00.json"
        newer = tmp_path / "term_mapping_2025-06-01_00-00.json"
        older.write_text(json.dumps({"a": "b"}))
        newer.write_text(json.dumps({"c": "d"}))

        path, mapping = load_latest_mapping(tmp_path)
        assert path == newer
        assert mapping == {"c": "d"}

    def test_raises_when_no_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_latest_mapping(tmp_path)


# ── Tests for check_mapping ───────────────────────────────────────────────────

class TestCheckMapping:
    def test_identity_entries_skipped(self):
        mapping = {"wound": "wound", "ulcer": "ulcer"}
        embedder = MagicMock()
        result = check_mapping(mapping, embedder, threshold=0.95)
        assert result == []
        embedder.embed.assert_not_called()

    def test_clean_mapping_returns_empty(self):
        # Two nearly identical vectors → cosine close to 1.0
        vecs = {
            "chronic wound": [1.0, 0.01, 0.0],
            "wound":         [1.0, 0.00, 0.0],
        }
        mapping = {"chronic wound": "wound"}
        embedder = _make_embedder(vecs)
        result = check_mapping(mapping, embedder, threshold=0.95)
        assert result == []

    def test_false_merge_flagged(self):
        # Orthogonal vectors → cosine = 0.0
        vecs = {
            "appendix": [1.0, 0.0, 0.0],
            "wound":    [0.0, 1.0, 0.0],
        }
        mapping = {"appendix": "wound"}
        embedder = _make_embedder(vecs)
        result = check_mapping(mapping, embedder, threshold=0.95)
        assert len(result) == 1
        assert result[0]["term"] == "appendix"
        assert result[0]["canonical"] == "wound"
        assert result[0]["cosine"] == pytest.approx(0.0, abs=1e-4)

    def test_sorted_by_cosine_ascending(self):
        # Three entries: cosines ~0.0, ~0.5, ~0.8
        vecs = {
            "a": [1.0, 0.0, 0.0],
            "b": [0.0, 1.0, 0.0],   # cos(a,b) ≈ 0
            "c": [1.0, 1.0, 0.0],   # cos(a,c) ≈ 0.707
            "d": [1.0, 0.3, 0.0],   # cos(a,d) ≈ 0.958 → clean
            "e": [0.5, 0.5, 0.5],   # cos(a,e) ≈ 0.577
        }
        mapping = {"b": "a", "c": "a", "d": "a", "e": "a"}
        embedder = _make_embedder(vecs)
        result = check_mapping(mapping, embedder, threshold=0.95)
        cosines = [r["cosine"] for r in result]
        assert cosines == sorted(cosines)
        # d→a should NOT be flagged
        assert all(r["term"] != "d" for r in result)

    def test_result_keys(self):
        vecs = {"x": [1.0, 0.0], "y": [0.0, 1.0]}
        mapping = {"x": "y"}
        embedder = _make_embedder(vecs)
        result = check_mapping(mapping, embedder)
        assert set(result[0].keys()) == {"term", "canonical", "cosine", "string_sim"}

    def test_custom_threshold(self):
        vecs = {
            "chronic wound": [1.0, 0.1, 0.0],
            "wound":         [1.0, 0.0, 0.0],
        }
        mapping = {"chronic wound": "wound"}
        embedder = _make_embedder(vecs)
        # At threshold=1.0 everything is flagged (cosine never reaches 1.0 for different vecs)
        result = check_mapping(mapping, embedder, threshold=1.0)
        assert len(result) == 1

    def test_empty_mapping(self):
        result = check_mapping({}, MagicMock())
        assert result == []


# ── Tests for print_report ────────────────────────────────────────────────────

class TestPrintReport:
    def test_no_flagged_prints_clean(self, capsys):
        print_report([], total_non_id=10, threshold=0.95)
        out = capsys.readouterr().out
        assert "No suspicious mappings found" in out
        assert "CLEAN" in out

    def test_flagged_entries_appear_in_output(self, capsys):
        flagged = [{"term": "appendix", "canonical": "wound", "cosine": 0.12, "string_sim": 0.20}]
        print_report(flagged, total_non_id=5, threshold=0.95)
        out = capsys.readouterr().out
        assert "appendix" in out
        assert "wound" in out
        assert "FLAGGED" in out

    def test_mapping_name_appears_in_header(self, capsys):
        print_report([], total_non_id=0, mapping_name="term_mapping_2025-06-01")
        out = capsys.readouterr().out
        assert "term_mapping_2025-06-01" in out
