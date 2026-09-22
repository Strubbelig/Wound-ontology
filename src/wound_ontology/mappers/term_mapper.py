"""Action layer for term-synonym clustering and mapping lookup.

Takes a TermMapping (persistence layer) and operates on it.
Has no file I/O — all persistence goes through TermMapping.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd
from rapidfuzz.fuzz import ratio as _fuzz_ratio

from wound_ontology.mappers.term_mapping import TermMapping
from wound_ontology.utils.label_match import fold, singularize
from wound_ontology.utils.string_utils import normalize_term

_GENERIC_TERMS: frozenset[str] = frozenset({
    "wound", "pain", "skin", "patient", "female", "male",
    "chronic", "acute", "severe", "infection", "tissue",
    "leg", "foot", "scar", "burn", "ulcer", "sore",
    "symptom", "complication", "deformity", "crystal",
    "vagina", "pathogen", "geriatric", "hand", "valid",
})


def _string_sim(a: str, b: str) -> float:
    return _fuzz_ratio(normalize_term(a), normalize_term(b)) / 100.0


def _is_generic(term: str) -> bool:
    return normalize_term(term) in _GENERIC_TERMS


def canonical_rank(term: str, anchors=frozenset(), frequencies: dict[str, int] | None = None):
    """How strong a claim `term` has to be the canonical spelling of its cluster.

    Higher is stronger: an ontology anchor outranks any store term; among store
    terms the corpus decides by frequency; a longer label outranks a shorter one
    at equal frequency because it is the more specific of two spellings, and a
    shorter STRING breaks the remaining tie.

    One rule with two callers, on purpose. `build_from_embeddings` picks a
    cluster's canonical with it and `resolve_chains` picks a cycle's winner with
    it; written twice they would drift, and the two would then disagree about
    which spelling of one concept is its name.
    """
    freq = frequencies or {}
    return (1 if term in anchors else 0,
            freq.get(term, 0),
            len(normalize_term(term).split()),
            -len(term))


class TermMapper:
    """Action layer: synonym clustering and mapping lookup.

    Layer 3 in the mapper stack:
      DataManager (repo) → TermMapping (persistence) → TermMapper (action) → MappingCleaner (curator)
    """

    def __init__(self, term_mapping: TermMapping, name: str = "Term mapper") -> None:
        self.name          = name
        self._term_mapping = term_mapping
        self._standard_embeddings: dict[str, np.ndarray] = {}
        self._review_threshold: float = 0.75

    # ── Mapping access (dict-compatible) ─────────────────────────────────────

    @property
    def mapping(self) -> dict[str, str]:
        """The raw mapping dict — read-only view of TermMapping.data."""
        return self._term_mapping.data

    @property
    def standards(self) -> list[str]:
        return self._term_mapping.standards

    @property
    def originals(self) -> list[str]:
        return self._term_mapping.originals

    def map(self, term: str) -> str:
        """Single-term lookup; returns term unchanged if not mapped."""
        return self._term_mapping.get(term)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply mapping to a DataFrame (index + column labels)."""
        return df.rename(index=self._term_mapping.data,
                         columns=self._term_mapping.data)

    def save(self) -> None:
        """Explicit save — delegates to TermMapping."""
        self._term_mapping.save()

    def withdraw(self, *terms: str) -> int:
        """Remove entries from the mapping. Returns how many were actually there.

        The mapping file accumulates across builds, so a mapping that a later
        step refuses may already be recorded from an earlier run that had no such
        check. Withdrawing is how a refusal reaches the file rather than being
        quietly outvoted by it.
        """
        return self._term_mapping.remove(*terms)

    def prune(self, live_terms: set[str], ontology_labels=frozenset(),
              *, dry_run: bool = False) -> dict:
        """Drop entries that can no longer map anything onto anything.

        The mapping file accumulates across builds and never forgets. Measured on
        2026-09-06 it held 26625 entries against a store of 3727 terms, and the
        shape of the excess was two distinct problems:

          * 24441 IDENTITY entries (term maps to itself). `get()` already returns
            an unmapped term unchanged, so these never did anything at all -- but
            they are 92% of the file, and they are why the mapping looked like an
            unreviewable 26k-entry artifact rather than the ~200 real decisions it
            actually contains.
          * 1969 non-identity entries -- 90% of them -- whose CANONICAL is neither
            a live store term nor an ontology label. `-125 mmHg -> -125 mm Hg`,
            `18% -> 18`. Both ends are gone. Firing one would rename a term onto a
            target that exists nowhere.

        A term being absent from the store is NOT grounds for removal on its own:
        after run_apply_mapping the mapped term is gone by design, and the entry
        has to survive so a later abstract reintroducing it is normalised the same
        way. It is the canonical having died that makes an entry inert.

        Chains are followed rather than assumed away: `A -> B -> C` keeps A when C
        is alive. Exactly one chain exists in the current file and it resolves to
        nothing, but correctness here should not rest on that staying true.
        """
        data = self._term_mapping.data
        alive = set(live_terms) | set(ontology_labels)

        def resolves(canonical: str) -> bool:
            seen, cur = set(), canonical
            while cur not in seen:
                if cur in alive:
                    return True
                seen.add(cur)
                nxt = data.get(cur)
                if nxt is None or nxt == cur:
                    return False
                cur = nxt
            return False

        identity = [t for t, c in data.items() if t == c]
        dead     = [t for t, c in data.items() if t != c and not resolves(c)]
        report = {"identity": len(identity), "dead": len(dead),
                  "kept": len(data) - len(identity) - len(dead)}
        if dry_run:
            print(f"[{self.name}] prune (dry run): would drop {report['identity']} "
                  f"identity and {report['dead']} dead entr(ies); {report['kept']} kept.")
            return report
        self._term_mapping.remove(*identity, *dead)
        print(f"[{self.name}] pruned {report['identity']} identity entr(ies) that "
              f"never mapped anything and {report['dead']} whose target no longer "
              f"exists; {report['kept']} live mapping(s) kept.")
        return report

    def resolve_chains(self, *, frequencies: dict[str, int] | None = None,
                       anchors=frozenset(), accept_mapping=None,
                       dry_run: bool = False) -> dict:
        """Collapse `A -> B -> C` to `A -> C`, and break `A <-> B`, so the
        mapping is a forest and applying it once is applying it completely.

        Every single build writes a forest: `build_from_embeddings` asserts that
        each canonical maps to itself. The file is not one build. It accumulates,
        so a term this build makes a canonical may be a term an earlier build had
        already mapped somewhere else, and the two entries then sit side by side.

        `ConceptStore.normalize` follows exactly one hop, which makes both shapes
        fail SILENTLY rather than loudly:

          * a CHAIN half-lands the merge. `thermal burns -> thermal burn` and
            `thermal burn -> thermal burn injuries` leave the store holding
            `Thermal Burn` and `Thermal Burn Injuries` — two names for the one
            concept the mapping was built to unite.
          * a CYCLE undoes itself. `CFU -> CFUs` with `CFUs -> CFU` renames each
            onto the other; both spellings survive and nothing merges at all.

        Measured on the 2026-09-21 build: 735 chains whose second hop really
        renames, and 408 two-cycles that are not mere case variants.

        A cycle is broken with `canonical_rank` — the same rule that picks a
        cluster's canonical, so the winner is the one the build itself would have
        chosen: an ontology anchor first, then the corpus frequency.

        `accept_mapping` is honoured on the way. A chain ending at an anchor the
        category guard refuses FOR THIS TERM cannot be resolved in either
        direction: walking it there defeats the guard, and leaving it one step
        short lands the term on a name that the same pass renames away. The
        entry is withdrawn instead, which is what a refusal already means
        everywhere else here — the term keeps its own name and is reported.
        """
        data = self._term_mapping.data
        succ = {t: c for t, c in data.items() if t != c}

        # ── the cycles, and who wins each one ────────────────────────────────
        winner_of: dict[str, str] = {}
        seen: set[str] = set()
        for start in succ:
            if start in seen:
                continue
            path: list[str] = []
            index: dict[str, int] = {}
            cur = start
            while cur in succ and cur not in seen:
                index[cur] = len(path)
                path.append(cur)
                seen.add(cur)
                cur = succ[cur]
            if cur in index:                      # walked back into this path
                members = path[index[cur]:]
                winner = max(sorted(members),
                             key=lambda t: canonical_rank(t, anchors, frequencies))
                for m in members:
                    winner_of[m] = winner

        # ── every entry's terminal ───────────────────────────────────────────
        cache: dict[str, str] = {}

        def terminal(term: str) -> str:
            walked: list[str] = []
            on_path: set[str] = set()
            cur = term
            while True:
                if cur in cache:
                    end = cache[cur]
                    break
                if cur in winner_of:
                    end = winner_of[cur]
                    break
                nxt = succ.get(cur)
                if nxt is None or nxt == cur:
                    end = cur
                    break
                if cur in on_path:
                    # Unreachable while the cycle pass above is intact, and a
                    # loop rather than a raise if it ever is not.
                    raise RuntimeError(
                        f"[{self.name}] resolve_chains walked into an unbroken "
                        f"cycle at {cur!r}; the cycle pass missed it."
                    )
                on_path.add(cur)
                walked.append(cur)
                cur = nxt
            for w in walked:
                cache[w] = end
            return end

        repointed: dict[str, str] = {}
        dropped: list[str] = []
        refused: list[tuple[str, str]] = []
        for term, current in succ.items():
            end = terminal(term)
            if (end != current and accept_mapping is not None and end in anchors
                    and not accept_mapping(term, end)):
                refused.append((term, end))
                continue
            if end == term:
                dropped.append(term)
            elif end != current:
                repointed[term] = end

        cycles = len(set(winner_of.values()))
        report = {"cycles": cycles, "repointed": len(repointed),
                  "dropped": len(dropped), "withdrawn": len(refused)}
        if not (repointed or dropped or refused):
            print(f"[{self.name}] mapping is already a forest — no chains, no cycles.")
            return report
        verb = "would re-point" if dry_run else "re-pointed"
        print(f"[{self.name}] {verb} {len(repointed)} entr(ies) onto their final "
              f"canonical and broke {cycles} cycle(s), dropping {len(dropped)} "
              f"entr(ies) whose term won its own cycle.")
        for term, end in list(repointed.items())[:5]:
            print(f"[{self.name}]     {term!r} -> {succ[term]!r} -> … -> {end!r}")
        if refused:
            print(f"[{self.name}] withdrew {len(refused)} entr(ies) whose chain "
                  f"ends at an anchor the category guard refuses for that term:")
            for term, end in refused[:5]:
                print(f"[{self.name}]     {term!r} kept its own name, not walked to {end!r}")
        if dry_run:
            return report

        self._term_mapping.add_batch(
            repointed,
            {t: {"standard": c, "confidence": 1.0, "method": "chain_resolved"}
             for t, c in repointed.items()},
        )
        if dropped or refused:
            self._term_mapping.remove(*dropped, *(t for t, _ in refused))

        # Verify rather than assume: the point of the step is that one hop is
        # enough afterwards, and a write that did not land would leave exactly
        # the silent half-merge it exists to end.
        after = self._term_mapping.data
        left = {t: c for t, c in after.items() if t != c and c in after and after[c] != c}
        if left:
            shown = "; ".join(f"{t!r}->{c!r}->{after[c]!r}" for t, c in list(left.items())[:3])
            raise RuntimeError(
                f"[{self.name}] resolve_chains did not reach a fixed point: "
                f"{len(left)} entr(ies) still point at a term that is itself "
                f"mapped ({shown}). The mapping was NOT left in a state where "
                f"one hop applies it completely."
            )
        return report

    # ── SapBERT clustering ────────────────────────────────────────────────────

    def build_from_embeddings(
        self,
        terms: list[str],
        embedder,
        similarity_threshold: float = 0.95,
        frequencies: dict[str, int] | None = None,
        anchors: set[str] | None = None,
        accept_mapping=None,
    ) -> dict[str, str]:
        """Synonym clustering via SapBERT cosine similarity + complete-linkage.

        MERGE CONDITION — a pair (a, b) is valid iff:
          0. fold(a) == fold(b)  (string-only pre-merge: punctuation and case
             folded AND the head noun singularized, so `Challenges` pre-merges
             with `Challenge` instead of being typed separately downstream)
          1. cosine_similarity >= similarity_threshold  (default 0.95)

        Generic single-word terms additionally require string_sim >= 0.90 to
        prevent common biomedical context words from absorbing unrelated terms.

        ANCHORS — labels of classes that already exist in WONT or MILD. They are
        clustered like any other term but always win canonicality, so a store term
        that lands in a cluster with one is mapped ONTO the existing class instead
        of the other way round.

        This is the gap the pipeline had. SapBERT only ever saw store terms, so it
        could merge "Complication" with "Complications" and never notice that WONT
        already had "Wound complication process"; the merge-time lexicon matched
        ontology labels but only by string, so "Granulation" never reached
        "Granulation process" either. A term sat between a semantic matcher that
        was not given the ontology and an ontology matcher with no semantics, and
        was minted as a twin of a class that already existed.

        ACCEPT_MAPPING — optional callable(term, canonical) -> bool, consulted
        before a term is mapped onto an ANCHOR. SapBERT at 0.95 cannot tell a
        process from its material bearer, because their labels are lexically
        almost identical: it proposed `Necrosis Process -> Necrosis`,
        `Skin grafting -> Skin graft` and `wound dehiscence -> Wound dehiscence
        process`. That is the continuant/occurrent distinction the whole pipeline
        exists to respect, and raising the threshold does not fix it -- the bad
        matches are semantically close, which is exactly why the embedding likes
        them. A rejected term keeps its own name and is reported.

        CLUSTERING: complete-linkage — two clusters merge only when EVERY
        cross-cluster pair independently passes the merge condition, preventing
        transitive false merges.
        """
        unique_terms: list[str] = list(dict.fromkeys(terms))

        if not unique_terms:
            print(f"[{self.name}] No terms to cluster.")
            return self._term_mapping.data

        freq = frequencies or {}
        anchor_set = {a for a in (anchors or set())}
        # An anchor outranks any store term on frequency, and one anchor outranks
        # another by being the shorter, more general label.
        def _rank(t: str):
            return canonical_rank(t, anchor_set, freq)

        def _canonical(members: list[str]) -> str:
            """Pick the cluster's canonical, then take the singular spelling of it.

            The canonical becomes a class LABEL in the exported ontology, and an
            OBO class label is singular. `_rank` decides on frequency, and the
            corpus says the plural more often for anything a paper counts, so it
            chose `Diabetic foot ulcers` over `Diabetic foot ulcer` and `ulcers`
            over `ulcer` -- 10 of the 193 live entries. That was invisible until
            `run_apply_mapping` propagated the plural into the store, and the
            merge then labelled the class `Diabetic Foot Ulcers`, which cost
            CQ001, CQ006, CQ051 and CQ054 the term they resolve on.

            Only spellings of the SAME term are considered: `fold` folds
            punctuation and singularizes, so this can never trade one concept for
            another, only one spelling of one concept for another. An anchor is
            exempt -- an ontology's own label is canonical however it is spelled.
            """
            best = max(members, key=_rank)
            if best in anchor_set:
                return best
            def _is_singular(m: str) -> bool:
                words = m.split()
                return bool(words) and singularize(words[-1]) == words[-1].lower()

            same = [m for m in members if fold(m) == fold(best) and _is_singular(m)]
            return max(same, key=_rank) if same else best

        # ── Step 0: pre-merge by folded form (no SapBERT) ────────────────────
        # `fold`, not `normalize_term`: normalize_term folds punctuation and case
        # but does NOT singularize, so `Challenge` and `Challenges` landed in
        # different groups and never pre-merged. They then reached the store as
        # two terms, were typed independently -- `material entity` and `quality`,
        # in disjoint BFO branches -- and the merge, which DOES fold, collapsed
        # them into one class holding both. An incoherent class, from one term
        # spelled two ways.
        #
        # `_canonical` below already reasons in `fold` (`fold(m) == fold(best)`)
        # and already returns the singular spelling per rule 23, so grouping by
        # fold is what the rest of this function was already written to expect.
        # Measured over the 4114 terms the mapper is given: fold unites exactly
        # 8 groups that normalize_term splits, every one a singular/plural pair
        # of the same term, and not one of them involves an anchor.
        norm_groups: dict[str, list[str]] = defaultdict(list)
        for t in unique_terms:
            norm_groups[fold(t)].append(t)

        pre_merged: dict[str, str] = {}
        embed_terms: list[str] = []
        self.refused_mappings: list[tuple[str, str]] = []
        for members in norm_groups.values():
            canonical = _canonical(members)
            embed_terms.append(canonical)
            for t in members:
                if t == canonical:
                    continue
                # The validator has to run here as well as on the clustered path.
                # It did not, and `Process` was mapped to BFO's `process` by
                # normalised-form pre-merge -- the one mapping guaranteed to break
                # category detection, arriving through the door nobody was watching.
                if (accept_mapping is not None and canonical in anchor_set
                        and not accept_mapping(t, canonical)):
                    self.refused_mappings.append((t, canonical))
                    continue
                pre_merged[t] = canonical

        if pre_merged:
            print(f"[{self.name}] Pre-merged {len(pre_merged)} terms by folded form.")

        print(f"[{self.name}] Embedding {len(embed_terms)} terms with SapBERT...")
        emb: np.ndarray = embedder.embed(embed_terms)
        sim_matrix: np.ndarray = emb @ emb.T

        n = len(embed_terms)
        term_to_idx = {t: i for i, t in enumerate(embed_terms)}

        # ── Step 1: valid pairs ───────────────────────────────────────────────
        rows, cols = np.where(sim_matrix >= similarity_threshold)
        valid: set[tuple[int, int]] = set()
        for i, j in zip(rows.tolist(), cols.tolist()):
            if i >= j:
                continue
            a, b = embed_terms[i], embed_terms[j]
            if (_is_generic(a) or _is_generic(b)) and _string_sim(a, b) < 0.90:
                continue
            valid.add((i, j))

        print(f"[{self.name}] {len(valid)} valid pairs "
              f"(cosine ≥ {similarity_threshold}) …")

        # ── Step 2: complete-linkage clustering ───────────────────────────────
        cluster_of: list[int]          = list(range(n))
        cl_members: dict[int, set[int]] = {i: {i} for i in range(n)}

        for i, j in sorted(valid, key=lambda p: sim_matrix[p[0], p[1]], reverse=True):
            ci, cj = cluster_of[i], cluster_of[j]
            if ci == cj:
                continue
            if all(
                (min(a, b), max(a, b)) in valid
                for a in cl_members[ci]
                for b in cl_members[cj]
            ):
                for k in cl_members[cj]:
                    cluster_of[k] = ci
                cl_members[ci] |= cl_members[cj]
                del cl_members[cj]

        clusters: dict[int, list[str]] = defaultdict(list)
        for idx, term in enumerate(embed_terms):
            clusters[cluster_of[idx]].append(term)

        # ── Step 3: pick canonical per cluster ───────────────────────────────
        assignment: dict[str, str] = {}
        for members in clusters.values():
            canonical = _canonical(members)
            if accept_mapping is not None and canonical in anchor_set:
                kept = [t for t in members
                        if t == canonical or accept_mapping(t, canonical)]
                for t in members:
                    if t not in kept:
                        self.refused_mappings.append((t, canonical))
                members = kept
            for t in members:
                assignment[t] = canonical

        n_non_identity = sum(1 for t, c in assignment.items() if t != c)
        max_size       = max(len(v) for v in clusters.values())
        print(f"[{self.name}] {len(clusters)} clusters; "
              f"{n_non_identity} non-identity mappings; "
              f"max cluster size: {max_size}")

        assert all(assignment[c] == c for c in assignment.values()), \
            "Canonical terms must map to themselves"

        # ── Step 4: resolve pre-merged terms and build metadata ───────────────
        metadata_batch: dict[str, dict] = {}

        for orig, pre_canon in pre_merged.items():
            final = assignment.get(pre_canon, pre_canon)
            assignment[orig] = final
            metadata_batch[orig] = {"standard": final, "confidence": 1.0,
                                    "method": "string_norm"}

        for term, canonical in assignment.items():
            if term in pre_merged:
                continue
            idx_t = term_to_idx[term]
            idx_c = term_to_idx[canonical]
            metadata_batch[term] = {
                "standard": canonical,
                "confidence": float(sim_matrix[idx_t, idx_c]),
                "method": "sapbert_cluster",
            }

        # Only real merges are persisted. An identity entry is a no-op -- get()
        # already returns an unmapped term unchanged -- but writing one per
        # canonical made the file 92% no-op (24441 of 26625 entries) and buried
        # the ~200 decisions a curator actually has to look at.
        merges = {t: c for t, c in assignment.items() if t != c}
        self._term_mapping.add_batch(
            merges, {t: metadata_batch[t] for t in merges if t in metadata_batch})

        # The mapping persists across builds, so a mapping this build refuses may
        # still be present from an earlier one that had no validator. Withdraw it
        # rather than let the guard be silently defeated by the file -- but only
        # that exact pair, so curation done in review_mapping is untouched.
        stale = [t for t, canonical in self.refused_mappings
                 if self._term_mapping.data.get(t) == canonical]
        if stale:
            self._term_mapping.remove(*stale)
            print(f"[{self.name}] withdrew {len(stale)} refused mapping(s) recorded "
                  f"by an earlier build.")
        # This build's decision about the terms it was given, identities included,
        # so a caller can ask what happened to any input term. It is deliberately
        # NOT the persisted mapping: the file holds only merges, and it also holds
        # entries from earlier builds that these terms say nothing about.
        return assignment
