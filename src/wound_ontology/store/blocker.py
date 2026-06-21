"""Blocker: uses all term/keyword lists to classify, flag, and curate terms."""

from __future__ import annotations

from wound_ontology.store.term_lists import (
    BlockKeywordList,
    BlockList,
    SuspiciousList,
    WhiteKeywordList,
    WhiteList,
)


class Blocker:
    """Classifies terms as blocked, whitelisted, or suspicious.

    Uses five lists:
      terms      — BlockList       (exact full-term blocklist)
      white_terms— WhiteList       (exact full-term whitelist)
      block_kw   — BlockKeywordList (substring keyword blocklist)
      white_kw   — WhiteKeywordList (substring keyword whitelist)
      suspicious — SuspiciousList  (substring keywords for flagging)

    Priority order in is_blocked():
      1. noise regex (is_noise) → blocked
      2. white_terms or white_kw → NOT blocked
      3. block_kw or terms       → blocked
      4. otherwise               → NOT blocked
    """

    def __init__(self) -> None:
        self.terms       = BlockList()
        self.white_terms = WhiteList()
        self.block_kw    = BlockKeywordList()
        self.white_kw    = WhiteKeywordList()
        self.suspicious  = SuspiciousList()
        self.reload()

    def reload(self) -> None:
        """Reload all lists from their config files."""
        self.terms.load()
        self.white_terms.load()
        self.block_kw.load()
        self.white_kw.load()
        self.suspicious.load()

    # ── Classification ────────────────────────────────────────────────────────

    @staticmethod
    def is_noise(term: str) -> bool:
        """True if term matches the measurement/unit noise regex."""
        from config.blocklist import is_noise_term
        return is_noise_term(term)

    def is_blocked(self, term: str) -> bool:
        """True if term should be excluded from the ontology."""
        if self.is_noise(term):
            return True
        if self.white_terms.match(term) or self.white_kw.match(term):
            return False
        return self.block_kw.match(term) or self.terms.match(term)

    def score(self, term: str) -> float:
        """Return 0.0 (in-scope) or 100.0 (out-of-scope) based on lists alone.

        SapBERT similarity scores for undecided terms are computed by callers
        (StoreCleaner) rather than here, to keep Blocker free of embedding deps.
        """
        if self.is_noise(term):
            return 100.0
        if self.white_terms.match(term) or self.white_kw.match(term):
            return 0.0
        if self.block_kw.match(term) or self.terms.match(term):
            return 100.0
        return 0.0

    def flag(self, term: str) -> str | None:
        """Return the cluster label if term is suspicious, else None."""
        if self.suspicious.match(term):
            return BlockList.assign_cluster(term)
        return None

    # ── Reporting ─────────────────────────────────────────────────────────────

    def cluster_report(self) -> None:
        """Print a summary of METHODOLOGY_BLOCKLIST terms grouped by cluster."""
        self.terms.cluster_report()

    def recluster(self, dry_run: bool = False) -> None:
        """Rewrite METHODOLOGY_BLOCKLIST in blocklist.py with cluster-headed sections."""
        self.terms.recluster(dry_run=dry_run)

    def recluster_sapbert(
        self,
        embedder,
        n_clusters: int = 40,
        dry_run: bool = False,
    ) -> None:
        """Rewrite METHODOLOGY_BLOCKLIST using SapBERT K-means cluster labels."""
        self.terms.recluster_sapbert(embedder, n_clusters=n_clusters, dry_run=dry_run)

    def recluster_whitelist_sapbert(
        self,
        embedder,
        n_clusters: int = 25,
        dry_run: bool = False,
    ) -> None:
        """Rewrite WHITELIST using SapBERT K-means cluster labels."""
        self.white_terms.recluster_sapbert(embedder, n_clusters=n_clusters, dry_run=dry_run)
