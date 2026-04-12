import pandas as pd
import pytest
from wound_ontology.data_manager.data_manager import DataManager


@pytest.fixture
def dm(tmp_path):
    return DataManager(base_path=tmp_path)


# ── Directory creation ─────────────────────────────────────────────────────────

def test_base_dir_created(tmp_path):
    target = tmp_path / "sub" / "cache"
    DataManager(base_path=target)
    assert target.exists()


# ── JSON round-trip ────────────────────────────────────────────────────────────

def test_json_roundtrip(dm):
    data = {"key": "value", "count": 42}
    dm.save_as_json(data, "test_json")
    result = dm.load_latest_json("test_json")
    assert result == data


def test_load_json_missing_returns_none(dm):
    assert dm.load_latest_json("nonexistent") is None


# ── CSV round-trip ─────────────────────────────────────────────────────────────

def test_csv_roundtrip(dm):
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    dm.save_as_csv(df, "test_csv")
    result = dm.load_latest_csv("test_csv")
    assert list(result["a"]) == [1, 2]


def test_load_csv_missing_returns_none(dm):
    assert dm.load_latest_csv("nonexistent") is None


# ── Pickle round-trip ──────────────────────────────────────────────────────────

def test_pickle_roundtrip(dm):
    obj = {"nested": [1, 2, 3]}
    dm.save_as_pickle(obj, "test_pickle")
    result = dm.load_latest_pickle("test_pickle")
    assert result == obj


def test_load_pickle_missing_returns_none(dm):
    assert dm.load_latest_pickle("nonexistent") is None


# ── Cleanup (version pruning) ──────────────────────────────────────────────────

def test_cleanup_prunes_old_files(dm):
    # Create 12 files with distinct names (timestamps collapse within a second)
    for i in range(12):
        (dm.base_path / f"prune_test_2026-01-{i+1:02d}_00-00.json").write_text("{}")
    dm._cleanup_old_files("prune_test", limit=10)
    remaining = list(dm.base_path.glob("prune_test_*.json"))
    assert len(remaining) == 10


# ── Reference files (stable, unversioned) ─────────────────────────────────────

def test_reference_csv_roundtrip(dm):
    df = pd.DataFrame([{"Class": "Wound", "Parent class": "Entity"}])
    dm.save_reference_csv(df, "bfo_hierarchy")
    result = dm.load_reference_csv("bfo_hierarchy")
    assert result is not None
    assert list(result["Class"]) == ["Wound"]


def test_reference_csv_overwrites(dm):
    dm.save_reference_csv(pd.DataFrame([{"x": 1}]), "ref")
    dm.save_reference_csv(pd.DataFrame([{"x": 99}]), "ref")
    result = dm.load_reference_csv("ref")
    assert result["x"][0] == 99


def test_reference_csv_missing_returns_none(dm):
    assert dm.load_reference_csv("missing_ref") is None


def test_reference_dir_is_sibling_of_cache(dm):
    dm.save_reference_csv(pd.DataFrame([{"a": 1}]), "check")
    assert dm.reference_path == dm.base_path.parent / "reference"


# ── Meta stamp ────────────────────────────────────────────────────────────────

def test_meta_stamp_format(dm):
    col, stamp = dm.get_meta_stamp("extract")
    assert col == "meta_extract_id"
    assert stamp.startswith("extract_1_")


def test_meta_stamp_increments(dm):
    _, stamp1 = dm.get_meta_stamp("extract")
    _, stamp2 = dm.get_meta_stamp("extract")
    count1 = int(stamp1.split("_")[1])
    count2 = int(stamp2.split("_")[1])
    assert count2 == count1 + 1


# ── Purge ─────────────────────────────────────────────────────────────────────

def test_purge_requires_confirm(dm):
    dm.save_as_json({"x": 1}, "purge_me")
    dm.purge_by_prefix("purge_me", confirm=False)
    remaining = list(dm.base_path.glob("purge_me_*"))
    assert len(remaining) == 1  # not deleted


def test_purge_deletes_with_confirm(dm):
    dm.save_as_json({"x": 1}, "purge_me")
    dm.purge_by_prefix("purge_me", confirm=True)
    remaining = list(dm.base_path.glob("purge_me_*"))
    assert len(remaining) == 0


def test_purge_short_prefix_rejected(dm):
    dm.save_as_json({"x": 1}, "ab")
    dm.purge_by_prefix("ab", confirm=True)          # prefix too short — aborted
    remaining = list(dm.base_path.glob("ab_*"))
    assert len(remaining) == 1
