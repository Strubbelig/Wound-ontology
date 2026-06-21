"""Tests for term_lists.py and blocker.py."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from wound_ontology.store.term_lists import (
    BaseList,
    BlockList,
    KeywordList,
    SuspiciousList,
    TermList,
    WhiteKeywordList,
    WhiteList,
    _find_block_end,
    _pylist_add,
    _pylist_remove,
)
from wound_ontology.store.blocker import Blocker


# ── Persistence helper tests ───────────────────────────────────────────────────

class TestFindBlockEnd:
    def test_simple_set(self):
        lines = [
            'MY_SET: set[str] = {',
            '    "a",',
            '    "b",',
            '}',
            'OTHER = 1',
        ]
        assert _find_block_end(lines, "MY_SET") == 3

    def test_frozenset(self):
        lines = [
            'MY_FS: frozenset[str] = frozenset({',
            '    "x",',
            '})',
            'OTHER = 1',
        ]
        assert _find_block_end(lines, "MY_FS") == 2

    def test_raises_when_not_found(self):
        lines = ['OTHER = 1']
        with pytest.raises(RuntimeError):
            _find_block_end(lines, "MISSING")


class TestPylistAdd:
    def test_adds_new_terms(self, tmp_path):
        p = tmp_path / "config.py"
        p.write_text('MY_SET: set[str] = {\n    "existing",\n}\n')
        current = frozenset({"existing"})
        n = _pylist_add(p, "MY_SET", current, {"newterm"})
        assert n == 1
        assert '"newterm"' in p.read_text()

    def test_skips_existing_terms(self, tmp_path):
        p = tmp_path / "config.py"
        p.write_text('MY_SET: set[str] = {\n    "existing",\n}\n')
        current = frozenset({"existing"})
        n = _pylist_add(p, "MY_SET", current, {"existing"})
        assert n == 0

    def test_lowercases_new_terms(self, tmp_path):
        p = tmp_path / "config.py"
        p.write_text('MY_SET: set[str] = {\n}\n')
        n = _pylist_add(p, "MY_SET", frozenset(), {"NewTerm"})
        assert n == 1
        assert '"newterm"' in p.read_text()


class TestPylistRemove:
    def test_removes_term(self, tmp_path):
        p = tmp_path / "config.py"
        p.write_text('MY_SET: set[str] = {\n    "keep",\n    "remove",\n}\n')
        n = _pylist_remove(p, "MY_SET", {"remove"})
        assert n == 1
        assert '"remove"' not in p.read_text()
        assert '"keep"' in p.read_text()

    def test_returns_zero_when_not_present(self, tmp_path):
        p = tmp_path / "config.py"
        p.write_text('MY_SET: set[str] = {\n    "keep",\n}\n')
        n = _pylist_remove(p, "MY_SET", {"missing"})
        assert n == 0


# ── TermList / KeywordList matching ───────────────────────────────────────────

class TestTermListMatch:
    """Use WhiteList as a concrete TermList to test matching logic."""

    def _list_with(self, terms: set[str]) -> WhiteList:
        wl = WhiteList.__new__(WhiteList)
        wl._terms = frozenset(t.lower() for t in terms)
        return wl

    def test_exact_match(self):
        wl = self._list_with({"wound healing"})
        assert wl.match("wound healing")

    def test_case_insensitive(self):
        wl = self._list_with({"wound healing"})
        assert wl.match("Wound Healing")

    def test_parenthetical_abbreviation_stripped(self):
        wl = self._list_with({"wound healing"})
        assert wl.match("wound healing (WH)")

    def test_non_member(self):
        wl = self._list_with({"wound healing"})
        assert not wl.match("scar")

    def test_contains_operator(self):
        wl = self._list_with({"wound"})
        assert "wound" in wl
        assert "scar" not in wl


class TestKeywordListMatch:
    def _list_with(self, kws: set[str]) -> SuspiciousList:
        sl = SuspiciousList.__new__(SuspiciousList)
        sl._terms = frozenset(kws)
        return sl

    def test_substring_match(self):
        sl = self._list_with({"study"})
        assert sl.match("observational study design")

    def test_case_insensitive(self):
        sl = self._list_with({"study"})
        assert sl.match("STUDY design")

    def test_no_match(self):
        sl = self._list_with({"study"})
        assert not sl.match("wound healing")

    def test_empty_keywords(self):
        sl = self._list_with(set())
        assert not sl.match("anything")


# ── BlockList clustering ──────────────────────────────────────────────────────

class TestBlockListClustering:
    def test_assign_cluster_known_term(self):
        assert BlockList.assign_cluster("randomized controlled trial") == "Study design & trial types"

    def test_assign_cluster_uncategorized(self):
        assert BlockList.assign_cluster("xyzzy unknown term") == "Uncategorized"

    def test_cluster_returns_all_labels(self):
        bl = BlockList.__new__(BlockList)
        bl._terms = frozenset({"randomized trial", "xyzzy"})
        clusters = bl.cluster()
        assert "Study design & trial types" in clusters
        assert "Uncategorized" in clusters
        assert "randomized trial" in clusters["Study design & trial types"]
        assert "xyzzy" in clusters["Uncategorized"]

    def test_cluster_report_prints(self, capsys):
        bl = BlockList.__new__(BlockList)
        bl._terms = frozenset({"randomized trial"})
        bl.cluster_report()
        out = capsys.readouterr().out
        assert "BLOCKLIST CLUSTER SUMMARY" in out
        assert "Study design" in out


# ── Blocker tests ─────────────────────────────────────────────────────────────

class TestBlocker:
    @pytest.fixture
    def blocker(self):
        from wound_ontology.store.term_lists import (
            BlockKeywordList as BKL, BlockList as BL,
            SuspiciousList as SL, WhiteKeywordList as WKL, WhiteList as WL,
        )
        b = Blocker.__new__(Blocker)
        b.terms        = BL.__new__(BL)
        b.white_terms  = WL.__new__(WL)
        b.block_kw     = BKL.__new__(BKL)
        b.white_kw     = WKL.__new__(WKL)
        b.suspicious   = SL.__new__(SL)
        b.terms._terms       = frozenset({"methodology study"})
        b.white_terms._terms = frozenset({"wound healing"})
        b.block_kw._terms    = frozenset({"regression"})
        b.white_kw._terms    = frozenset({"wound care"})
        b.suspicious._terms  = frozenset({"study"})
        return b

    def test_noise_term_is_blocked(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=True):
            assert blocker.is_blocked("100 mg")

    def test_whitelist_term_not_blocked(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            assert not blocker.is_blocked("wound healing")

    def test_whitelist_keyword_wins_over_blocklist_keyword(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            # "wound care protocol" contains both "wound care" (whitelist kw) and "protocol"
            # white_kw wins
            assert not blocker.is_blocked("wound care protocol")

    def test_block_kw_triggers(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            assert blocker.is_blocked("logistic regression analysis")

    def test_explicit_blocklist_term(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            assert blocker.is_blocked("methodology study")

    def test_clean_term_not_blocked(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            assert not blocker.is_blocked("granulation tissue")

    def test_score_noise(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=True):
            assert blocker.score("100 mg") == 100.0

    def test_score_whitelisted(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            assert blocker.score("wound healing") == 0.0

    def test_score_blocked(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            assert blocker.score("methodology study") == 100.0

    def test_flag_suspicious(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            result = blocker.flag("observational study design")
            assert result is not None

    def test_flag_clean(self, blocker):
        with patch("config.blocklist.is_noise_term", return_value=False):
            result = blocker.flag("wound healing")
            assert result is None


# ── BaseList interface ────────────────────────────────────────────────────────

class TestBaseListInterface:
    def test_len(self):
        wl = WhiteList.__new__(WhiteList)
        wl._terms = frozenset({"a", "b", "c"})
        assert len(wl) == 3

    def test_iter_sorted(self):
        wl = WhiteList.__new__(WhiteList)
        wl._terms = frozenset({"c", "a", "b"})
        assert list(wl) == ["a", "b", "c"]

    def test_contains(self):
        wl = WhiteList.__new__(WhiteList)
        wl._terms = frozenset({"wound"})
        assert "wound" in wl
        assert "scar" not in wl
