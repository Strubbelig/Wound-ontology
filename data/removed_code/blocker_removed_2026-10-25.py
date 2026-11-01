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
      1. white_terms or white_kw → NOT blocked
      2. noise regex (is_noise)  → blocked
      3. block_kw or terms       → blocked
      4. otherwise               → NOT blocked

    The whitelist comes FIRST. It used to sit behind is_noise, which put a
    regex heuristic above an explicit human decision: `NaCl 0.9%`
    (WONT_0000208) and `NaCl 10%` (WONT_0000209) are curated classes, and no
    whitelist entry could reach them -- the only remedy was to weaken the
    regex for every term. Now a curator can name the exception, and the
    heuristic keeps deciding everything nobody has ruled on.

    The whitelists therefore now carry the whole burden of being right about
    what they exempt. That is the intended trade: `is_noise` is a guess about
    a string's shape, a whitelist entry is a decision about a concept.

    The GATE, when one is given
    ---------------------------
    `gate=` is a `TermMappingAndGate`, and where it has an answer for a term it
    is the answer -- ahead of both exact lists and ahead of the noise regex,
    because a gate verdict carries who decided it and why, and the lists do not.
    The two exact lists are what the gate's `rule` verdicts were imported FROM,
    so with only those imported the two agree by construction; what the gate adds
    is somewhere for a curator's override and a pass's opinion to live, and a
    reason attached to each.

    Without a gate the lists decide exactly as before, so every existing caller
    -- `StoreCleaner`, the notebooks, the tests -- keeps working unchanged. The
    keyword lists and the noise regex are NOT in the gate and never will be:
    they are rules over strings nobody has seen, and rule 29 puts an entry in the
    list whose matching rule it can carry.
    """

    def __init__(self, gate=None) -> None:
        self.terms       = BlockList()
        self.white_terms = WhiteList()
        self.block_kw    = BlockKeywordList()
        self.white_kw    = WhiteKeywordList()
        self.suspicious  = SuspiciousList()
        self.gate        = gate
        self.reload()

    def gate_verdict(self, term: str) -> tuple[str, str]:
        """`(verdict, source)` for the CONCEPT `term` names, or `("", "")`.

        `effective_gate_verdict`, not `gate_verdict`: scope is a property of the
        concept and the mapping is what says which spellings are one concept.
        Asking per spelling let `post-operative pain` be in scope and
        `postoperative pain` out of it -- 37 such pairs on 2026-09-25 -- and
        which answer applied depended on which spelling a reader looked up.

        `is not None`, not truthiness: `TermMappingAndGate.__len__` counts the
        LIVE MAPPING, so a gate holding ten thousand scope verdicts and no
        mappings is falsy. Testing it with `if self.gate` turned the gate off
        silently and left the lists deciding, which is the failure this whole
        change exists to stop.
        """
        return ("", "") if self.gate is None else self.gate.effective_gate_verdict(term)

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
        """True if term should be excluded from the ontology.

        A gate verdict from the CURATOR or a PASS is new evidence and outranks
        every list. A gate verdict sourced `rule` is one of the two exact lists
        re-encoded, so it keeps the position that list already had -- behind the
        whitelists, ahead of nothing. Putting it first instead changed two terms:
        `abusive head trauma` and `absence of vaginal cleansing right before
        surgery` are on METHODOLOGY_BLOCKLIST and rescued by a whitelist KEYWORD,
        and the fold is a move, not a ruling.
        """
        verdict, source = self.gate_verdict(term)
        if verdict and source != "rule":
            return verdict == "out"
        if self.white_terms.match(term) or self.white_kw.match(term):
            return False
        if self.is_noise(term):
            return True
        if verdict:
            return verdict == "out"
        return self.block_kw.match(term) or self.terms.match(term)

    def score(self, term: str) -> float:
        """Return 0.0 (in-scope) or 100.0 (out-of-scope) based on lists alone.

        SapBERT similarity scores for undecided terms are computed by callers
        (StoreCleaner) rather than here, to keep Blocker free of embedding deps.
        """
        return 100.0 if self.is_blocked(term) else 0.0

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
