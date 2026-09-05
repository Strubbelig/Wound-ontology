"""Pruning old versions must not delete a different prefix's files.

`_cleanup_old_files` globbed `<prefix>_*`, which for "class_hierarchy" also
matches every `class_hierarchy_provenance_*`. Sorted lexicographically a digit
comes before a letter, so the matrix files were always at the front of the list
and always the ones deleted. Ten saves later every `class_hierarchy_<stamp>.csv`
was gone and only the provenance sidecars remained — measured on the live cache,
which held 0 matrix files and 10 provenance files.

Nothing reported it, because the hierarchy is rebuilt from its sources on every
run and an empty reload looks identical to a first run. `_find_latest_path` was
fixed for exactly this over-matching; the code that deletes was not.
"""
import pytest

from wound_ontology.data_manager.data_manager import DataManager


@pytest.fixture
def dm(tmp_path):
    return DataManager(tmp_path)


def _touch(dm, prefix, n, ext="csv"):
    """n versions of `prefix` with distinct, sortable stamps."""
    made = []
    for i in range(n):
        f = dm.base_path / f"{prefix}_2026-09-{i + 1:02d}_12-00.{ext}"
        f.write_text("x", encoding="utf-8")
        made.append(f.name)
    return made


def test_a_sidecar_prefix_is_not_pruned_by_its_parent(dm):
    _touch(dm, "class_hierarchy", 12)
    _touch(dm, "class_hierarchy_provenance", 12)

    dm._cleanup_old_files("class_hierarchy", limit=10)

    main = sorted(f.name for f in dm.base_path.glob("class_hierarchy_2026*"))
    side = sorted(f.name for f in dm.base_path.glob("class_hierarchy_provenance_*"))
    assert len(main) == 10, "the prefix's own files were not pruned to the limit"
    assert len(side) == 12, "pruning one prefix deleted another prefix's files"


def test_the_oldest_of_the_prefix_go_first(dm):
    _touch(dm, "class_hierarchy", 12)
    dm._cleanup_old_files("class_hierarchy", limit=10)
    kept = sorted(f.name for f in dm.base_path.glob("class_hierarchy_2026*"))
    assert kept[0] == "class_hierarchy_2026-09-03_12-00.csv"
    assert kept[-1] == "class_hierarchy_2026-09-12_12-00.csv"


def test_pruning_the_sidecar_does_not_touch_the_parent(dm):
    _touch(dm, "class_hierarchy", 12)
    _touch(dm, "class_hierarchy_provenance", 12)
    dm._cleanup_old_files("class_hierarchy_provenance", limit=10)
    assert len(list(dm.base_path.glob("class_hierarchy_2026*"))) == 12


def test_an_unstamped_file_is_never_deleted(dm):
    """Only versioned files are pruned; anything else in the directory is not
    this function's business."""
    _touch(dm, "class_hierarchy", 12)
    stray = dm.base_path / "class_hierarchy_notes.txt"
    stray.write_text("keep me", encoding="utf-8")
    dm._cleanup_old_files("class_hierarchy", limit=10)
    assert stray.exists()


def test_lattice_and_its_accepted_slice_are_independent(dm):
    """Same shape one artifact over: `concept_lattice_wound_*` matches
    `concept_lattice_wound_accepted_*`, and the pickles sort first."""
    _touch(dm, "concept_lattice_wound", 12, ext="pkl")
    _touch(dm, "concept_lattice_wound_accepted", 12, ext="json")
    dm._cleanup_old_files("concept_lattice_wound", limit=10)
    assert len(list(dm.base_path.glob("concept_lattice_wound_accepted_*"))) == 12
