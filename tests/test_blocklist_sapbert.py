"""Tests for TermList.recluster_sapbert() (BlockList and WhiteList)."""

from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from wound_ontology.store.term_lists import BlockList, WhiteList


def _mock_embedder(n_terms: int, dim: int = 8) -> MagicMock:
    rng = np.random.default_rng(0)
    embedder = MagicMock()
    vecs = rng.random((n_terms, dim)).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs /= norms
    embedder.embed.return_value = vecs
    return embedder


def _blocklist_with(terms: set[str]) -> BlockList:
    bl = BlockList.__new__(BlockList)
    bl._terms = frozenset(t.lower() for t in terms)
    return bl


class TestLabelCluster:
    def test_returns_top_n_joined(self):
        terms = ["alpha", "beta", "gamma", "delta"]
        embs  = np.eye(4, dtype=np.float32)
        center = embs[0]
        label = BlockList._label_cluster(center, terms, embs, top_n=2)
        assert "alpha" in label
        assert " · " in label
        assert len(label.split(" · ")) == 2

    def test_top_n_capped_by_available(self):
        terms = ["only"]
        embs  = np.array([[1.0, 0.0]], dtype=np.float32)
        center = embs[0]
        label = BlockList._label_cluster(center, terms, embs, top_n=5)
        assert label == "only"


class TestReclusterSapbert:
    def test_dry_run_prints_no_file_change(self, tmp_path, capsys):
        bl = _blocklist_with({"randomized trial", "cohort study", "logistic regression",
                               "meta-analysis", "systematic review"})
        embedder = _mock_embedder(5)
        bl.recluster_sapbert(embedder, n_clusters=2, dry_run=True)
        out = capsys.readouterr().out
        assert "dry-run" in out
        # No file attribute needed — no file path set, test focuses on output

    def test_rewrites_file(self, tmp_path):
        path = tmp_path / "blocklist.py"
        path.write_text('METHODOLOGY_BLOCKLIST: set[str] = {\n    "term a",\n    "term b",\n    "term c",\n}\n')

        bl = _blocklist_with({"term a", "term b", "term c"})
        bl._PATH     = path
        bl._VAR_NAME = "METHODOLOGY_BLOCKLIST"
        embedder = _mock_embedder(3)

        with MagicMock() as _:
            bl.load = MagicMock()  # prevent overwriting controlled _terms
            bl.recluster_sapbert(embedder, n_clusters=2, dry_run=False)

        content = path.read_text()
        assert "METHODOLOGY_BLOCKLIST: set[str] = {" in content
        assert '"term a"' in content or '"term b"' in content or '"term c"' in content
        assert "# ──" in content

    def test_n_clusters_respected(self, tmp_path, capsys):
        terms = {f"term {i}" for i in range(10)}
        bl = _blocklist_with(terms)
        bl.load = MagicMock()
        embedder = _mock_embedder(10)
        bl.recluster_sapbert(embedder, n_clusters=3, dry_run=True)
        out = capsys.readouterr().out
        assert "3 clusters" in out

    def test_empty_blocklist_exits_early(self, capsys):
        bl = _blocklist_with(set())
        bl.load = MagicMock()
        embedder = MagicMock()
        bl.recluster_sapbert(embedder, n_clusters=5, dry_run=True)
        out = capsys.readouterr().out
        assert "empty" in out
        embedder.embed.assert_not_called()


def _whitelist_with(terms: set[str]) -> WhiteList:
    wl = WhiteList.__new__(WhiteList)
    wl._terms = frozenset(t.lower() for t in terms)
    return wl


class TestWhiteListReclusterSapbert:
    def test_dry_run_prints_no_file_change(self, capsys):
        wl = _whitelist_with({"wound healing", "granulation tissue", "re-epithelialization"})
        wl.load = MagicMock()
        embedder = _mock_embedder(3)
        wl.recluster_sapbert(embedder, n_clusters=2, dry_run=True)
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_rewrites_frozenset_format(self, tmp_path):
        path = tmp_path / "whitelist.py"
        path.write_text(
            'WHITELIST: frozenset[str] = frozenset({\n'
            '    "wound",\n'
            '    "scar",\n'
            '    "healing",\n'
            '})\n'
        )
        wl = _whitelist_with({"wound", "scar", "healing"})
        wl._PATH     = path
        wl._VAR_NAME = "WHITELIST"
        wl.load = MagicMock()
        embedder = _mock_embedder(3)

        wl.recluster_sapbert(embedder, n_clusters=2, dry_run=False)

        content = path.read_text()
        assert "WHITELIST: frozenset[str] = frozenset({" in content
        assert content.strip().endswith("})")
        assert "# ──" in content

    def test_empty_whitelist_exits_early(self, capsys):
        wl = _whitelist_with(set())
        wl.load = MagicMock()
        embedder = MagicMock()
        wl.recluster_sapbert(embedder, n_clusters=5, dry_run=True)
        out = capsys.readouterr().out
        assert "empty" in out
        embedder.embed.assert_not_called()
