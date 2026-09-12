# -*- coding: utf-8 -*-
"""A review queue that does not survive the session is not a review queue.

`propose_edge` recorded FCA suggestions in an instance dict and nothing ever
wrote it out. `save()` persisted the matrix, `save_provenance()` persisted the
COMMITTED edges, and the proposed ones died when the process did -- while
`run_build_hierarchies(commit_fca=False)` printed "Inspect
class_hier.candidates, then class_hier.promote_candidates(...)", an instruction
that only worked before you closed the notebook. Twelve candidates were lost
that way, and nothing said so: an empty queue and a discarded queue look
identical.

Found 2026-09-09 while trying to show those twelve.
"""
from __future__ import annotations

import pandas as pd
import pytest

from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy


@pytest.fixture
def dm(tmp_path):
    from wound_ontology.data_manager.data_manager import DataManager

    return DataManager(base_path=str(tmp_path))


def _queue_file_rows(dm) -> set[tuple[str, str]]:
    """(child, parent) pairs the newest candidates CSV actually holds."""
    import pathlib

    files = sorted(pathlib.Path(dm.base_path).glob("class_hierarchy_candidates_*.csv"))
    assert files, "no candidates file was written at all"
    df = pd.read_csv(files[-1])
    return {(str(r.child), str(r.parent)) for r in df.itertuples()}


def _fresh(dm) -> ClassHierarchy:
    """A hierarchy reading the same directory — i.e. the next session."""
    return ClassHierarchy(dm)


def test_a_candidate_survives_a_reload(dm):
    h = _fresh(dm)
    h.propose_edge("Dog Bite Wound", "Bite Wound", "fca")
    h.save()

    again = _fresh(dm)
    assert ("Dog Bite Wound", "Bite Wound") in again.candidates
    assert again.candidates[("Dog Bite Wound", "Bite Wound")] == "fca"


def test_promoting_the_last_candidate_empties_the_queue_on_disk(dm):
    """The trap `save_provenance` would have walked into.

    Provenance only grows, so returning early on an empty dict is safe there. A
    queue shrinks. If the write were skipped when it empties, the previous file
    would still be the newest on disk and the next session would load the
    promoted edges back as though they were still waiting.
    """
    h = _fresh(dm)
    h.propose_edge("Dog Bite Wound", "Bite Wound", "fca")
    h.save()

    h2 = _fresh(dm)
    assert len(h2.candidates) == 1
    with pytest.warns(RuntimeWarning):          # no lattice passed; expected
        assert h2.promote_candidates() == 1
    assert h2.candidates == {}

    h3 = _fresh(dm)
    assert h3.candidates == {}, "a promoted candidate came back as unreviewed"


def test_a_candidate_committed_elsewhere_is_not_reloaded_as_pending(dm):
    """`propose_edge` refuses an already-committed edge; loading must agree.

    The queue file has to still NAME the edge for this to test anything. Writing
    both files from one instance does not produce that state -- `_set_edge`
    de-queues the candidate, so the queue is already empty when it is written,
    and the test would pass without the provenance check ever running. So the
    provenance is saved on its own here, leaving the edge in both files at once,
    which is exactly what a promotion in another session leaves behind.
    """
    h = _fresh(dm)
    h.propose_edge("Dog Bite Wound", "Bite Wound", "fca")
    h.save()

    h2 = _fresh(dm)
    h2._set_edge("Dog Bite Wound", "Bite Wound", source="curated")
    h2.save_provenance()                 # NOT save() — the queue file stays as it was

    queued = _queue_file_rows(dm)
    assert ("Dog Bite Wound", "Bite Wound") in queued, (
        "the queue file must still name the edge, or this test proves nothing")

    stale = _fresh(dm)
    assert ("Dog Bite Wound", "Bite Wound") not in stale.candidates
    assert stale.source_of("Dog Bite Wound", "Bite Wound") == "curated"


def test_an_unreadable_queue_raises_rather_than_looking_empty(dm, tmp_path, monkeypatch):
    """The failure mode this whole file exists for."""
    h = _fresh(dm)
    h.propose_edge("Dog Bite Wound", "Bite Wound", "fca")
    h.save()

    def boom(prefix):
        if prefix.endswith("_candidates"):
            raise OSError("disk on fire")
        return None

    monkeypatch.setattr(dm, "load_latest_csv", boom)
    with pytest.raises(RuntimeError, match="could not be read"):
        _fresh(dm)


def test_a_queue_missing_a_column_raises(dm, tmp_path):
    h = _fresh(dm)
    h.propose_edge("Dog Bite Wound", "Bite Wound", "fca")
    h.save()
    bad = sorted(tmp_path.glob("class_hierarchy_candidates_*.csv"))[-1]
    pd.DataFrame([{"child": "a", "parent": "b"}]).to_csv(bad, index=True)
    with pytest.raises(ValueError, match="missing column"):
        _fresh(dm)


def test_the_candidate_file_is_not_pruned_as_a_matrix_file(dm, tmp_path):
    """Rule 27's second row, now with a THIRD sibling name.

    `class_hierarchy_*` once globbed onto `class_hierarchy_provenance_*` and
    deleted the matrix files. `class_hierarchy_candidates_*` is a third name
    under the same stem, so the anchored match matters again.
    """
    h = _fresh(dm)
    h.propose_edge("Dog Bite Wound", "Bite Wound", "fca")
    for _ in range(3):
        h.save()
    names = {p.name.rsplit("_", 2)[0] for p in tmp_path.glob("*.csv")}
    assert "class_hierarchy_candidates" in names
    assert "class_hierarchy" in names or not h.df.empty is False
    # and the candidate file is still loadable
    assert _fresh(dm).candidates
