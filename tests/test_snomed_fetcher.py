"""Tests for connectors.snomed_fetcher — pure helper functions only (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wound_ontology.connectors.snomed_fetcher import (
    SnomedFetcher,
    _BROAD_SEED_CODES,
    global_precoord_filter,
    is_laterality,
    is_precoord_of_parent,
    is_wound_relevant,
    normalize,
)


# ── normalize ─────────────────────────────────────────────────────────────────

class TestNormalize:
    def test_strips_whitespace(self):
        assert normalize("  Wound  ") == "wound"

    def test_strips_disorder_qualifier(self):
        assert normalize("Wound (disorder)") == "wound"

    def test_strips_morphology_qualifier(self):
        assert normalize("Excoriation (morphology)") == "excoriation"

    def test_strips_category_suffix(self):
        assert normalize("Burns - category") == "burns"

    def test_lowercases(self):
        assert normalize("Chronic Wound") == "chronic wound"

    def test_no_change_on_plain_name(self):
        assert normalize("laceration") == "laceration"


# ── is_laterality ─────────────────────────────────────────────────────────────

class TestIsLaterality:
    def test_left(self):
        assert is_laterality("Wound of left hand")

    def test_right(self):
        assert is_laterality("Laceration of right arm")

    def test_bilateral(self):
        assert is_laterality("Pressure ulcer of bilateral heels")

    def test_no_laterality(self):
        assert not is_laterality("Wound of hand")

    def test_case_insensitive(self):
        assert is_laterality("Wound of LEFT foot")

    def test_not_a_laterality_wound_itself(self):
        assert not is_laterality("Chronic wound")


# ── is_precoord_of_parent ─────────────────────────────────────────────────────

class TestIsPrecoordOfParent:
    def test_basic_precoord(self):
        assert is_precoord_of_parent("Laceration of trunk", "Laceration")

    def test_plural_precoord(self):
        assert is_precoord_of_parent("Lacerations of trunk", "Laceration")

    def test_not_precoord(self):
        assert not is_precoord_of_parent("Laceration", "Wound")

    def test_different_root_not_precoord(self):
        assert not is_precoord_of_parent("Burn of hand", "Laceration")

    def test_qualifier_stripped_for_comparison(self):
        # normalize is called internally — parent "(disorder)" should be stripped
        assert is_precoord_of_parent("Wound of neck", "Wound")

    def test_no_false_positive_on_partial_overlap(self):
        assert not is_precoord_of_parent("Wound healing", "Wound")


# ── is_wound_relevant ────────────────────────────────────────────────────────

class TestIsWoundRelevant:
    def test_wound(self):
        assert is_wound_relevant("Wound healing")

    def test_ulcer(self):
        assert is_wound_relevant("Pressure ulcer")

    def test_burn(self):
        assert is_wound_relevant("Thermal burn")

    def test_not_relevant(self):
        assert not is_wound_relevant("Hypertension")

    def test_scar(self):
        assert is_wound_relevant("Keloid scar")


# ── global_precoord_filter ───────────────────────────────────────────────────

class TestGlobalPrecoordFilter:
    def test_removes_body_site_narrowings(self):
        concepts = [
            {"preferred_name": "Laceration"},
            {"preferred_name": "Laceration of hand"},  # "Laceration of …" → remove
        ]
        result = global_precoord_filter(concepts)
        names = [c["preferred_name"] for c in result]
        assert "Laceration" in names
        assert "Laceration of hand" not in names

    def test_keeps_plain_concepts(self):
        concepts = [
            {"preferred_name": "Wound healing"},
            {"preferred_name": "Chronic wound"},
        ]
        result = global_precoord_filter(concepts)
        assert len(result) == 2

    def test_empty_list(self):
        assert global_precoord_filter([]) == []

    def test_qualifiers_stripped_for_matching(self):
        concepts = [
            {"preferred_name": "Wound (disorder)"},    # normalized: "wound"
            {"preferred_name": "Wound of abdomen"},    # "wound of …" → remove
        ]
        result = global_precoord_filter(concepts)
        names = [c["preferred_name"] for c in result]
        assert "Wound of abdomen" not in names

    def test_no_false_removal_when_base_absent(self):
        concepts = [
            {"preferred_name": "Wound of abdomen"},
        ]
        result = global_precoord_filter(concepts)
        # "wound" not in the set → should NOT be removed
        assert len(result) == 1


# ── SnomedFetcher init ────────────────────────────────────────────────────────

class TestSnomedFetcherInit:
    def test_raises_on_empty_api_key(self, tmp_path):
        with pytest.raises(ValueError, match="UMLS API key"):
            SnomedFetcher("", tmp_path)

    def test_accepts_valid_key(self, tmp_path):
        f = SnomedFetcher("test-key", tmp_path)
        assert f.api_key == "test-key"


# ── SnomedFetcher prune (no network) ─────────────────────────────────────────

class TestSnomedFetcherPrune:
    def _make_fetcher(self, tmp_path: Path) -> SnomedFetcher:
        return SnomedFetcher("fake-key", tmp_path)

    def _write_concepts(self, tmp_path: Path, records: list[dict]) -> None:
        (tmp_path / "snomed_wound_concepts.json").write_text(
            json.dumps(records, indent=2)
        )
        cache = {r["snomed_code"]: r for r in records}
        (tmp_path / "snomed_wound_concepts_cache.json").write_text(
            json.dumps(cache, indent=2)
        )

    def test_prune_raises_if_no_output(self, tmp_path):
        f = self._make_fetcher(tmp_path)
        with pytest.raises(FileNotFoundError):
            f.prune()

    def test_prune_raises_if_no_cache(self, tmp_path):
        f = self._make_fetcher(tmp_path)
        (tmp_path / "snomed_wound_concepts.json").write_text("[]")
        with pytest.raises(FileNotFoundError):
            f.prune()

    def test_prune_removes_laterality(self, tmp_path):
        f = self._make_fetcher(tmp_path)
        records = [
            {"snomed_code": "1", "preferred_name": "Wound", "parent_code": "", "depth": 0, "cui": "", "semantic_types": []},
            {"snomed_code": "2", "preferred_name": "Wound of left hand", "parent_code": "1", "depth": 1, "cui": "", "semantic_types": []},
        ]
        self._write_concepts(tmp_path, records)
        result = f.prune()
        names = [r["preferred_name"] for r in result]
        assert "Wound of left hand" not in names
        assert "Wound" in names

    def test_prune_removes_precoord_global(self, tmp_path):
        f = self._make_fetcher(tmp_path)
        records = [
            {"snomed_code": "1", "preferred_name": "Laceration", "parent_code": "", "depth": 0, "cui": "", "semantic_types": []},
            {"snomed_code": "2", "preferred_name": "Laceration of trunk", "parent_code": "1", "depth": 1, "cui": "", "semantic_types": []},
        ]
        self._write_concepts(tmp_path, records)
        result = f.prune()
        names = [r["preferred_name"] for r in result]
        assert "Laceration of trunk" not in names

    def test_prune_writes_json_and_csv(self, tmp_path):
        f = self._make_fetcher(tmp_path)
        records = [
            {"snomed_code": "1", "preferred_name": "Wound", "parent_code": "", "depth": 0, "cui": "", "semantic_types": []},
        ]
        self._write_concepts(tmp_path, records)
        f.prune()
        assert (tmp_path / "snomed_wound_concepts.json").exists()
        assert (tmp_path / "snomed_wound_concepts.csv").exists()


# ── SnomedFetcher rebuild_cache (no network) ──────────────────────────────────

class TestSnomedFetcherRebuildCache:
    def _make_fetcher(self, tmp_path: Path) -> SnomedFetcher:
        return SnomedFetcher("fake-key", tmp_path)

    def test_rebuild_raises_if_no_cache(self, tmp_path):
        f = self._make_fetcher(tmp_path)
        with pytest.raises(FileNotFoundError):
            f.rebuild_cache()

    def test_rebuild_writes_output(self, tmp_path):
        f = self._make_fetcher(tmp_path)
        cache = {
            "1": {"snomed_code": "1", "preferred_name": "Wound", "parent_code": "", "depth": 0, "cui": "", "semantic_types": []},
        }
        (tmp_path / "snomed_wound_concepts_cache.json").write_text(json.dumps(cache))
        result = f.rebuild_cache()
        assert len(result) == 1
        assert (tmp_path / "snomed_wound_concepts.json").exists()

    def test_rebuild_filters_laterality_from_cache(self, tmp_path):
        f = self._make_fetcher(tmp_path)
        cache = {
            "1": {"snomed_code": "1", "preferred_name": "Wound", "parent_code": "", "depth": 0, "cui": "", "semantic_types": []},
            "2": {"snomed_code": "2", "preferred_name": "Wound of right arm", "parent_code": "1", "depth": 1, "cui": "", "semantic_types": []},
        }
        (tmp_path / "snomed_wound_concepts_cache.json").write_text(json.dumps(cache))
        result = f.rebuild_cache()
        names = [r["preferred_name"] for r in result]
        assert "Wound of right arm" not in names
