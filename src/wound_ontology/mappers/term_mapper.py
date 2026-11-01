"""Action layer for term-synonym clustering and mapping lookup.

Takes a TermMappingAndGate (persistence layer) and operates on it.
Has no file I/O — all persistence goes through TermMappingAndGate.
"""

from __future__ import annotations

from collections import defaultdict

from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz.fuzz import ratio as _fuzz_ratio

from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
from wound_ontology.utils.label_match import fold, singular_spelling, singularize
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


#: Rows of the similarity matrix computed at a time. The whole matrix is n^2
#: float32 and n was 90,435 on the 2026-09-26 corpus -- 32.7 GB on a 17 GB
#: machine. Module level so a test can shrink it and check that a pair
#: straddling two blocks is still found.
SIMILARITY_BLOCK = 1000


def canonical_rank(term: str, anchors=frozenset(), frequencies: dict[str, int] | None = None,
                   named=frozenset(), heads=frozenset()):
    """How strong a claim `term` has to be the canonical spelling of its cluster.

    Higher is stronger: an ontology anchor outranks any store term; among store
    terms the corpus decides by frequency; a longer label outranks a shorter one
    at equal frequency because it is the more specific of two spellings, and a
    shorter STRING breaks the remaining tie.

    One rule with two callers, on purpose. `build_from_embeddings` picks a
    cluster's canonical with it and `resolve_chains` picks a cycle's winner with
    it; written twice they would drift, and the two would then disagree about
    which spelling of one concept is its name.

    The term itself is the LAST component, so the order is total. Without it
    `Derived Indices` and `derived indices` -- same frequency, same word count,
    same length -- tie, and `max()` over a set returns whichever the process's
    hash seed happened to iterate first. Two runs of the same pipeline chose
    different canonicals for the same group; pass 0 found 773 such groups on the
    2026-09-25 store by failing to converge on a second run. A canonical that
    depends on the hash seed is not a decision, it is a coin toss with a
    record.

    `named` are the terms a person chose as the name of their cluster
    (`TermMappingAndGate.named`, 2026-10-24). They come right after the
    anchors: the ontology's own label still wins (rule 36), a person's choice
    beats the corpus count.

    `heads` are the names clusters already have (`TermMappingAndGate.heads`).
    They come next (rule 85, 2026-10-25): a name stays the name when a rebuild
    or a new abstract shifts the counts -- only a label or a person moves it.
    """
    freq = frequencies or {}
    return (1 if term in anchors else 0,
            1 if term in named else 0,
            1 if term in heads else 0,
            freq.get(term, 0),
            len(normalize_term(term).split()),
            -len(term),
            term)


class TermMapper:
    """Action layer: synonym clustering and mapping lookup.

    Layer 3 in the mapper stack:
      DataManager (repo) → TermMappingAndGate (persistence) → TermMapper (action)
    """

    def __init__(self, term_mapping: TermMappingAndGate, name: str = "Term mapper") -> None:
        self.name          = name
        self._term_mapping = term_mapping
        self._standard_embeddings: dict[str, np.ndarray] = {}
        self._review_threshold: float = 0.75

    # ── Mapping access (dict-compatible) ─────────────────────────────────────

    @property
    def mapping(self) -> dict[str, str]:
        """The raw mapping dict — read-only view of TermMappingAndGate.data."""
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
        """Explicit save — delegates to TermMappingAndGate."""
        self._term_mapping.save()

    def _report_skipped(self, skipped: list[tuple[str, str]], what: str) -> None:
        """Say which proposals a standing refusal blocked.

        `add_batch` returns them rather than writing them, and a batch that
        silently dropped part of itself is the failure mode this pipeline does
        not get to have.
        """
        if not skipped:
            return
        print(f"[{self.name}] {len(skipped)} entr(y/ies) from {what} not written — "
              f"a refusal stands against that exact pair:")
        for t, c in skipped[:5]:
            print(f"[{self.name}]     {t!r} -> {c!r}")

    def withdraw(self, *terms: str, reason: str = "") -> int:
        """Unmap entries. Returns how many were actually mapped.

        The mapping file accumulates across builds, so a mapping that a later
        step refuses may already be recorded from an earlier run that had no such
        check. Withdrawing is how a refusal reaches the file rather than being
        quietly outvoted by it.

        The record itself stays -- `TermMappingAndGate.retire` keeps the verdicts the
        pair cost credits to obtain -- and `reason` says on the record why the
        entry stopped being live.
        """
        return self._term_mapping.retire(*terms, reason=reason)

    def refuse(self, term: str, canonical: str, reason: str = "",
               by: str = "curator", *, verdict: str = "different") -> None:
        """Record a refusal of this exact pair and unmap it.

        The difference from `withdraw` is memory. `withdraw` deletes, which is
        right for an entry that can no longer do anything; a refusal is a
        DECISION, and a decision that leaves no trace is re-made by the next
        build (rule 33, and the reason `build_from_embeddings` consults
        `is_refused`).
        """
        self._term_mapping.refuse(term, canonical, reason=reason, by=by, verdict=verdict)

    def judge(self, term: str, canonical: str, **fields) -> None:
        """Attach evidence to one PAIR — a pass verdict, a curator's mark.

        Does NOT save; `save()` afterwards, once. `TermMappingAndGate.judge` says so
        for the same reason and this wrapper used to add the save back: the
        2026-09-25 bulk acceptance wrote 2,105 curator verdicts and saved the
        whole 4.4 MB record after each one — 9 GB of writing, twenty minutes,
        for a change that takes a second. A verdict carries no risk of being
        half-written the way a mapping edit does, and every caller here already
        saves and then reads the file back to check the write landed.
        """
        self._term_mapping.judge(term, canonical, **fields)

    def gate(self, term: str, **fields) -> None:
        """Record a gate verdict on `term` — in scope, or out.

        Does NOT save, like `judge`; `save()` once when the batch is done.
        """
        self._term_mapping.gate(term, **fields)

    def gate_verdict(self, term: str) -> tuple[str, str]:
        """`(verdict, source)` the gate gives `term`, or `("", "")`."""
        return self._term_mapping.gate_verdict(term)

    def gated(self, verdict: str) -> dict[str, str]:
        """`term -> source` for every term the gate answers `verdict`."""
        return self._term_mapping.gated(verdict)

    def gate_disagreements(self) -> list[dict]:
        """The terms whose gate sources contradict each other — a view."""
        return self._term_mapping.gate_disagreements()

    def subsumption_candidates(self) -> list[dict]:
        """The pairs a pass called narrower/broader — a view of the record."""
        return self._term_mapping.subsumption_candidates()

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
            # through a respelling too: a target renamed by pass 0 is alive under
            # its new spelling (73 confirmed mappings were retired as dead targets
            # before 2026-10-25)
            seen, cur = set(), self._term_mapping.resolve(canonical)
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
        self._term_mapping.retire(*identity, reason="identity entry — mapped a term onto itself")
        self._term_mapping.retire(*dead, reason="target no longer exists anywhere")
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

        The walk folds both sides (rule 13), because `ConceptStore.normalize`
        does — it looks a term up by its exact spelling and then by
        `normalize_term`. A chain can therefore exist only after folding:
        `deep partial thickness skin burns -> deep partial-thickness burns`
        beside `deep partial-thickness burns -> deep partial-thickness burn
        wounds`, where a hyphen is the whole difference. Resolving on exact
        strings alone left that one standing and the store found it on the next
        apply. A folded key claimed by two canonicals takes the first, which is
        what the store does with the same collision.

        Two spellings that fold together are one node, so an entry between them
        makes no progress and is left exactly as it is: the mapping's own
        spelling of a canonical is a decision (`Povidone-iodine`, not
        `Povidone Iodine`), and folding is for FINDING the chain, never for
        rewriting the label at the end of it.

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
        fold = normalize_term
        freq = frequencies or {}
        named = self._term_mapping.named()
        heads = self._term_mapping.heads()

        def rank(t: str):
            return canonical_rank(t, anchors, freq, named, heads)

        # A curator's same-class ruling outranks the category guard (2026-10-04:
        # the guard withdrew "wound healing process" -> "wound healing", which
        # the curator had stated the day before).
        def ruled(term: str, end: str) -> bool:
            for target in {end, data.get(term)} - {None}:
                j = self._term_mapping.peek(term, target)
                # `check` wrote under `curator` until 2026-10-24 and counted
                # here; moving it to its own source must not change that.
                if any((j.get(s) or {}).get("verdict") == "same_class"
                       for s in ("curator", "check")):
                    return True
            return False
        if accept_mapping is not None:
            guard = accept_mapping
            accept_mapping = lambda term, end: ruled(term, end) or guard(term, end)  # noqa: E731

        # ── the concepts, as connected components ───────────────────────────
        #
        # An entry is a claim that two spellings are one concept, and that
        # claim is TRANSITIVE: `A -> B` and `B -> C` say A, B and C are one
        # thing, so the question "where does A end up" is not a walk, it is
        # "which spelling does that one thing go by". Chasing the chain was the
        # wrong shape and it showed -- the walk ran over FOLDED nodes while the
        # check ran over the raw mapping, so 2,206 entries whose first hop
        # folded to one node were invisible to the resolution and visible to
        # the check, and the function raised rather than finishing.
        #
        # Components cannot produce a chain or a cycle, because every member
        # points at the same winner in one hop and the winner points nowhere.
        # There is nothing left to iterate.
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Union over FOLDED names, because the store looks a term up by its
        # exact spelling and then by `normalize_term`, so one capital letter is
        # enough to hide a link from an exact-string walk and not enough to
        # hide it from the store. The winner and every write stay exact
        # strings: folding FINDS the component, it never renames anything.
        spellings: dict[str, set[str]] = defaultdict(set)
        out_edge: set[str] = set()
        for term, canonical in succ.items():
            spellings[fold(term)].add(term)
            spellings[fold(canonical)].add(canonical)
            if fold(term) != fold(canonical):
                union(fold(term), fold(canonical))
                out_edge.add(fold(term))
        for node in spellings:
            parent.setdefault(node, node)

        members: dict[str, list[str]] = defaultdict(list)
        for node in parent:
            members[find(node)].append(node)

        repointed: dict[str, str] = {}
        dropped: list[str] = []
        refused: list[tuple[str, str]] = []
        contested: list[tuple[str, list[str]]] = []
        multi = 0

        # ── cycles INSIDE one folded node ───────────────────────────────────
        #
        # `Co-assembly -> co-assembly` and `co-assembly -> Co-assembly`: two
        # spellings of one name pointing at each other. The component pass
        # cannot see them, because it only draws an edge when the folds
        # DIFFER, so the pair is a single node with an internal loop -- 874 of
        # them after pass 0, every one a capitalisation.
        #
        # A one-way entry between two spellings of a name is not a cycle and
        # is left alone: `Povidone Iodine -> Povidone-iodine` is the mapping
        # choosing a spelling, which is its job.
        for node, names in spellings.items():
            inside = {t: succ[t] for t in names
                      if t in succ and fold(succ[t]) == node}
            if not inside:
                continue
            looped: set[str] = set()
            for start in inside:
                seen, cur = [], start
                while cur in inside and cur not in seen:
                    seen.append(cur)
                    cur = inside[cur]
                if cur in seen:
                    looped.update(seen[seen.index(cur):])
            if looped:
                champion = max(sorted(looped),
                               key=rank)
                for member in sorted(looped):
                    if member == champion:
                        dropped.append(member)
                    elif data.get(member) != champion:
                        repointed[member] = champion
            # A same-fold CHAIN is not a cycle and still has to flatten:
            # `IL-10 -> Il10 -> il10` is three spellings of one name and the
            # store follows one hop. Everything inside the node points at the
            # node's sink; a lone `Povidone Iodine -> Povidone-iodine` already
            # does, so nothing moves.
            for member in sorted(inside):
                if member in looped:
                    continue
                seen, cur = {member}, inside[member]
                while cur in inside and cur not in seen and cur not in looped:
                    seen.add(cur)
                    cur = inside[cur]
                if cur in looped:
                    cur = repointed.get(cur, cur)
                if cur != member and data.get(member) != cur:
                    repointed[member] = cur
        for nodes in members.values():
            group = sorted({sp for n in nodes for sp in spellings.get(n, ())})
            if len(nodes) < 2:
                continue
            # Each term has at most one target, so a connected component has
            # either exactly one SINK -- a member nothing points out of, which
            # is the canonical the mapping already chose -- or no sink at all,
            # which means a cycle. Only the second needs an election.
            # Re-electing when a sink exists would churn canonicals the curator
            # settled: `wounds -> Wound` and `wound -> Wound` is already a star
            # and there is nothing to resolve.
            sink_nodes = [n for n in nodes if n not in out_edge]
            sinks = sorted({sp for n in sink_nodes for sp in spellings[n]})
            claimed = [m for m in group if m in named]
            if claimed:
                # A person chose the name (2026-10-24: first the cluster, then
                # its name). Only an anchor outranks that choice, whatever the
                # sink is; two choices in one component are reported.
                winner = max(claimed + [m for m in group if m in anchors], key=rank)
                if len(claimed) > 1:
                    contested.append((winner, [t for t in claimed if t != winner]))
            elif len(sink_nodes) == 1:
                # Among the sink's spellings, the one the mapping ALREADY
                # points at wins. Re-ranking here would rename a canonical the
                # curator settled: `wounds -> Wound` and `wound -> Wound` is a
                # finished star, and electing `wound` on frequency would move
                # every entry for nothing.
                targets = [t for t in sinks if t in set(succ.values())]
                winner = max(targets or sinks,
                             key=rank)
            elif not sink_nodes:
                # A cycle. Where the curator confirmed one of its live pairs,
                # the target of that pair is the name (2026-09-28: `miRNA ->
                # microRNA` was re-proposed backwards by a rebuild and lost the
                # frequency vote); otherwise the usual rank decides. A name
                # decision never gets here: it is handled above.
                chosen = sorted({data[m] for m in group if data.get(m) and
                                 (self._term_mapping.peek(m, data[m]).get("curator") or {})
                                 .get("verdict") == "same_class"})
                winner = max(chosen or sorted(group),
                             key=rank)
            else:
                # Several sinks in one component: two spellings that FOLD
                # together point at different canonicals, so the component has
                # two claimed names for one concept. `patient-reported
                # outcomes` -> `patient-reported outcome` beside
                # `Patient-Reported Outcomes` -> `patient-reported outcome
                # measure`. Transitivity says they are one thing, so they
                # elect, and the ones that lose are reported -- if two sinks
                # really are different concepts, the fix is to refuse one of
                # the edges that joined them, not to keep a chain.
                winner = max(sinks, key=rank)
                contested.append((winner, [t for t in sinks if t != winner]))
            if all(data.get(m) == winner for m in group
                   if m != winner and (m in succ or (claimed and m in sinks))) \
                    and winner not in succ:
                continue                      # already a star; nothing to do
            multi += 1
            if (accept_mapping is not None and winner in anchors
                    and not all(accept_mapping(m, winner) for m in group
                                if m != winner)):
                # The guard speaks per term. Any member it refuses leaves the
                # component rather than being walked onto an anchor that is
                # wrong for it -- the same meaning `refused` had before.
                for member in sorted(group):
                    if member != winner and not accept_mapping(member, winner):
                        refused.append((member, winner))
                        continue
                    if member != winner and data.get(member) != winner:
                        repointed[member] = winner
                if winner in succ:
                    dropped.append(winner)
                continue
            for member in sorted(group):
                if member == winner:
                    if member in succ:
                        dropped.append(member)     # it won its own component
                    continue
                if member not in succ and not (claimed and member in sinks):
                    # A spelling that only ever appears as a TARGET has no
                    # entry, and giving it one here would invent a mapping
                    # nobody proposed. The old name of a cluster a person has
                    # renamed is the exception: the name decision proposed it.
                    continue
                if self._term_mapping.is_refused(member, winner):
                    refused.append((member, winner))
                    continue
                if data.get(member) != winner:
                    repointed[member] = winner

        cycles = multi
        report = {"cycles": cycles, "repointed": len(repointed),
                  "dropped": len(dropped), "withdrawn": len(refused),
                  "contested": contested}
        if not (repointed or dropped or refused):
            print(f"[{self.name}] mapping is already a forest — no chains, no cycles.")
            return report
        verb = "would re-point" if dry_run else "re-pointed"
        print(f"[{self.name}] {verb} {len(repointed)} entr(ies) onto their "
              f"component's canonical across {cycles} component(s), dropping "
              f"{len(dropped)} entr(ies) whose term won its own component.")
        for term, end in list(repointed.items())[:5]:
            print(f"[{self.name}]     {term!r} -> {succ.get(term, '—')!r} -> … -> {end!r}")
        if contested:
            print(f"[{self.name}] {len(contested)} component(s) had more than one "
                  f"claimed canonical — two spellings of one folded name pointing "
                  f"different ways. They elected:")
            for winner, losers in contested[:5]:
                print(f"[{self.name}]     {winner!r} over {losers}")
        if refused:
            print(f"[{self.name}] withdrew {len(refused)} entr(ies) whose chain "
                  f"ends at an anchor the category guard refuses for that term:")
            for term, end in refused[:5]:
                print(f"[{self.name}]     {term!r} kept its own name, not walked to {end!r}")
        if dry_run:
            return report

        self._report_skipped(self._term_mapping.add_batch(
            repointed,
            {t: {"standard": c, "confidence": 1.0, "method": "chain_resolved"}
             for t, c in repointed.items()},
        ), "chain resolution")
        self._term_mapping.retire(*dropped, reason="spelling of its own canonical")
        self._term_mapping.retire(*(t for t, _ in refused),
                                  reason="chain ends at an anchor the guard refuses")

        # Verify rather than assume: the point of the step is that one hop is
        # enough afterwards, and a write that did not land would leave exactly
        # the silent half-merge it exists to end. Checked the way the store
        # looks a term up — exact key first, folded key second.
        after = self._term_mapping.data
        after_folded: dict[str, str] = {}
        for t, c in after.items():
            if t != c:
                after_folded.setdefault(fold(t), c)
        left = {}
        for t, c in after.items():
            if t == c:
                continue
            nxt = after.get(c, after_folded.get(fold(c)))
            if nxt is not None and fold(nxt) != fold(c):
                left[t] = c
        if left:
            shown = "; ".join(f"{t!r}->{c!r}" for t, c in list(left.items())[:3])
            raise RuntimeError(
                f"[{self.name}] resolve_chains did not reach a fixed point: "
                f"{len(left)} entr(ies) still point at a term that is itself "
                f"mapped ({shown}). The mapping was NOT left in a state where "
                f"one hop applies it completely."
            )
        return report

    def enforce_canonical_policy(self, *, label_spellings: dict[str, str] | None = None,
                                 blocked=frozenset(), accept_mapping=None,
                                 dry_run: bool = False) -> dict:
        """Hold every canonical in the file to four rules, and report what moves.

        The rules are decisions taken elsewhere; this is where they reach the
        file, so a mapping built before one of them existed is brought up to it
        without a five-hour rebuild.

        1. THE ONTOLOGY'S OWN LABEL WINS (curator, 2026-09-23). A canonical that
           folds to a WONT or MILD label is re-spelled to that label. The store
           had `Necrosis Process -> necrosis` where the class is spelled
           `Necrosis`, and `debridement surgery -> surgical debridement` where it
           is `Surgical debridement`: 22 entries canonicalising a class under a
           spelling the class does not use. Downstream that mints a twin.

        2. A MAPPING ONTO A CLASS IS AN IDENTITY CLAIM, so `accept_mapping` --
           the category guard -- judges it. It could not before: it is consulted
           only for ANCHORS, and anchors are the ontology labels that are NOT
           also store terms, so the guard went quiet exactly when a class label
           was common enough in the corpus to be extracted. Rule 1 is what makes
           this possible: re-spelling the canonical to the label turns a
           store-to-store merge into the anchor mapping it always was.
           `Necrosis Process` [process] -> `Necrosis` [material entity] is the
           case the guard was written for and had never once seen.

           A term that IS the label under another spelling is not asked about --
           `Closure` for `closure`, `Pressure ulcers` for `Pressure ulcer`. The
           test is `label_difference`, the same partition the adjudication uses:
           only a CONTENT difference carries a claim. Without it the guard
           refuses inflections whose store typing happens to be contradictory,
           and `Pressure ulcers -> Pressure ulcer` is not a claim anybody needs
           checked.

        3. A BLOCKED CANONICAL IS REPORTED, NOT REPAIRED. (`blocked` is what the
           gate puts out, `Orchestrator.blocked_names`; until 2026-10-25 a
           blocklist was applied at extraction.) Rule 23 makes the canonical
           singular, and the list was applied by exact lowercase name. `patients` is not
           on the list and `patient` is, so the mapping renames the survivor back
           onto the blocked name: 462 store names arrived that way carrying 7,201
           mentions, which the view then leaves out together with whatever had
           merged into them.

           This method does NOT withdraw those entries. Withdrawing would leave
           the variant standing as its own concept, which is noise leaking back
           in under a plural; keeping the merge collapses the family onto one
           name that the cleanup then removes once. Which of the two is right
           depends on whether the `out` is correct -- `intervention` yes,
           `tissue repair` almost certainly not -- and that is a decision for the
           curator, not for a mapping pass. So the pairs are counted
           and returned, and the caller writes them out as a work item.

        4. A LABEL IS NEVER MAPPED AWAY (2026-10-01, rule 36 in INSTRUCTIONS).
           Anchors are the labels NO abstract wrote; a label an abstract did
           write is ranked by frequency like any store string, and lost:
           `Impaired wound healing process -> impaired wound healing`,
           `Wound treatment process -> wound therapy` -- 18 WONT/MILD classes
           folded into a store spelling, three of them against a curator who had
           kept the label direction. Rule 1 cannot see it: the two do not fold
           together. So the entry is turned round -- the store spelling and
           everything mapped onto it now map onto the label -- unless a curator
           chose the direction (`method: curator`, or the curator's
           `same_class` on this very pair, rule 85), which is reported and left. If the category guard refuses
           the turned-round claim, the label is only unmapped, and reported.

        Returns counts, and the entries behind each of them.
        """
        from wound_ontology.mappers.mapping_adjudicator import label_difference

        labels = label_spellings or {}
        is_label = set(labels.values())
        blocked = {b.strip().lower() for b in blocked}
        data = self._term_mapping.data

        # ── rule 4: a label mapped onto a store spelling is turned round ────
        restored: dict[str, str] = {}            # label -> the store spelling it pointed at
        held: list[tuple[str, str]] = []
        unmapped: list[tuple[str, str]] = []
        for term, canonical in list(data.items()):
            if term not in is_label or term == canonical or canonical in is_label:
                continue
            if labels.get(normalize_term(canonical)) is not None:
                continue                         # folds to a label: rule 1's case
            if (self._term_mapping.named_by(term) == "author"
                    or (self._term_mapping.peek(term, canonical).get("curator") or {})
                    .get("verdict") == "same_class"):
                held.append((term, canonical))
                continue
            if (accept_mapping is not None and label_difference(canonical, term) == "content"
                    and not accept_mapping(canonical, term)):
                unmapped.append((term, canonical))
                continue
            restored[term] = canonical
        moves = {}
        for label, store in restored.items():
            moves[store] = label
            moves.update({m: label for m, c in data.items() if c == store and m != label})
        if restored or held or unmapped:
            verb = "would turn round" if dry_run else "turned round"
            print(f"[{self.name}] {verb} {len(restored)} label(s) mapped onto a store "
                  f"spelling ({len(moves)} entr(ies) now onto the label); "
                  f"{len(held)} held by a curator's direction, {len(unmapped)} only "
                  f"unmapped because the guard refuses the turned-round claim.")
            for l, s in restored.items():
                print(f"[{self.name}]     {l!r} -> {s!r} … now {s!r} -> {l!r}")
            for l, s in held:
                print(f"[{self.name}]     HELD {l!r} -> {s!r} (curator's direction)")
            for l, s in unmapped:
                print(f"[{self.name}]     UNMAPPED {l!r} (was -> {s!r}; guard refuses {s!r} -> {l!r})")
        if not dry_run and (restored or unmapped):
            self._term_mapping.retire(
                *restored, *[l for l, _ in unmapped],
                reason="rule 36: the ontology's own label is the canonical, never mapped away")
            if moves:
                self._report_skipped(self._term_mapping.add_batch(
                    moves, {t: {"confidence": 1.0, "method": "ontology_label"} for t in moves}),
                    "label restored")
            data = self._term_mapping.data
            wrong = [l for l in [*restored, *(l for l, _ in unmapped)] if data.get(l)]
            wrong += [t for t, l in moves.items() if data.get(t) != l]
            if wrong:
                raise RuntimeError(f"[{self.name}] rule 4 did not land on {len(wrong)} "
                                   f"entr(ies): {wrong[:5]}")
        rule4 = {"labels_restored": len(restored), "labels_held": len(held),
                 "labels_unmapped": len(unmapped), "restored_entries": restored,
                 "held_entries": held, "unmapped_entries": unmapped, "moved_entries": moves}
        respelled: dict[str, str] = {}
        refused: list[tuple[str, str, str]] = []
        on_blocklist: list[tuple[str, str]] = []

        identities: list[str] = []
        for term, canonical in list(data.items()):
            if term == canonical:
                continue
            target = labels.get(normalize_term(canonical), canonical)
            if target == term:
                # Re-spelling turned the entry into a term mapped onto its own
                # name (`Wound -> wound` became `Wound -> Wound`). That is an
                # identity, which rule 19 removes -- not a refusal, and not a
                # question for the guard.
                #
                # EXACTLY equal, not folded: `Povidone Iodine -> Povidone-iodine`
                # folds to itself and is still doing work, because without the
                # entry the store falls back to `normalize_term`, which drops the
                # hyphen. Folding finds chains; it never decides that a spelling
                # is worthless.
                identities.append(term)
                continue
            if target.strip().lower() in blocked:
                on_blocklist.append((term, target))
                continue
            if (target in is_label and label_difference(term, target) == "content"
                    and accept_mapping is not None
                    and not accept_mapping(term, target)):
                refused.append((term, canonical, target))
                continue
            if target != canonical:
                respelled[term] = target

        report = {"respelled": len(respelled), "refused": len(refused),
                  "identities": len(identities),
                  "blocked_canonical": len(on_blocklist)}
        if not (respelled or refused or on_blocklist or identities):
            if not (restored or held or unmapped):
                print(f"[{self.name}] every canonical already follows the policy.")
            return report | rule4 | {"respelled_entries": {}, "refused_entries": [],
                             "blocked_entries": []}

        verb = "would re-spell" if dry_run else "re-spelled"
        print(f"[{self.name}] {verb} {len(respelled)} canonical(s) to the "
              f"ontology's own label, dropped {len(identities)} that became "
              f"identities, and refused {len(refused)} mapping(s) onto a class of "
              f"a different BFO kind. {len(on_blocklist)} entr(ies) point at a "
              f"canonical the gate puts out — reported, not touched; that is "
              f"the curator's decision.")
        for t, c in list(respelled.items())[:5]:
            print(f"[{self.name}]     {t!r} -> {data[t]!r} … now -> {c!r}")
        for t, c, tgt in refused[:5]:
            print(f"[{self.name}]     REFUSED {t!r} -> {tgt!r} (was {c!r}) — wrong kind of thing")
        for t, c in on_blocklist[:5]:
            print(f"[{self.name}]     BLOCKED CANONICAL {t!r} -> {c!r} — either {t!r} "
                  f"belongs on the list too, or {c!r} does not belong on it")

        if not dry_run:
            if respelled:
                self._report_skipped(self._term_mapping.add_batch(
                    respelled,
                    {t: {"standard": c, "confidence": 1.0, "method": "ontology_label"}
                     for t, c in respelled.items()}), "canonical policy")
            gone = [t for t, _, _ in refused] + identities
            if gone:
                self._term_mapping.retire(
                    *[t for t, _, _ in refused],
                    reason="re-spelling onto the class label is the wrong kind of thing")
                self._term_mapping.retire(
                    *identities, reason="re-spelling turned the entry into an identity")
            after = self._term_mapping.data
            missed = {t: c for t, c in respelled.items() if after.get(t) != c}
            left = [t for t in gone if t in after]
            if missed or left:
                raise RuntimeError(
                    f"[{self.name}] the canonical policy did not land: "
                    f"{len(missed)} re-spelling(s) read back wrong and "
                    f"{len(left)} withdrawn entr(ies) are still in the file."
                )
        return report | rule4 | {"respelled_entries": respelled,
                         "refused_entries": refused,
                         "blocked_entries": on_blocklist}

    # ── SapBERT clustering ────────────────────────────────────────────────────

    #: One row per term, grown in place across runs. Keyed by TERM, not by the
    #: list: the first version of this cache hashed the whole term list, so
    #: dropping 622 spellings out of 90,435 missed the cache and cost another
    #: fifty minutes of CPU for the 89,813 vectors that had not changed.
    VECTOR_STORE = "sapbert_vectors"

    def _vector_store_paths(self) -> tuple[Path, Path]:
        cache = Path(__file__).resolve().parents[3] / "data" / "cache"
        return (cache / f"{self.VECTOR_STORE}.npy",
                cache / f"{self.VECTOR_STORE}_terms.json")

    def _embeddings_for(self, terms: list[str], embedder):
        """`embedder.embed(terms)`, with every vector ever computed kept on disk.

        Embedding 90,435 terms takes the better part of an hour on a CPU, and a
        crash anywhere after it throws the hour away -- there were two, both in
        the metadata step. Only the terms the store has never seen are sent to
        the model; the rest are read back by name, so a re-run after a fix, or
        a run whose term set moved a little, is seconds rather than an hour.
        """
        import json

        import numpy as np

        if not terms:
            return np.empty((0, 0))

        vec_path, terms_path = self._vector_store_paths()
        store = None
        known: dict[str, int] = {}
        if vec_path.exists() and terms_path.exists():
            store = np.load(vec_path)
            kept = json.loads(terms_path.read_text(encoding="utf-8"))
            if len(kept) != store.shape[0]:
                # Never guess which of the two is right: a row/name mismatch
                # would attach one term's vector to another term's name, which
                # is a wrong merge nobody would ever see. Start again instead.
                print(f"[{self.name}] vector store is inconsistent "
                      f"({store.shape[0]} rows, {len(kept)} names); rebuilding it.")
                store, kept = None, []
            else:
                known = {t: i for i, t in enumerate(kept)}

        wanted = list(dict.fromkeys(terms))
        missing = [t for t in wanted if t not in known]
        if known:
            print(f"[{self.name}] vector store: {len(wanted) - len(missing):,} of "
                  f"{len(wanted):,} terms already embedded, {len(missing):,} to do.")
        if missing:
            fresh = np.asarray(embedder.embed(missing))
            if store is not None and fresh.shape[1] != store.shape[1]:
                # A different model. Mixing the two would be silent nonsense.
                print(f"[{self.name}] the embedder returns {fresh.shape[1]} "
                      f"dimensions and the store holds {store.shape[1]}; "
                      f"the store is from another model and is being replaced.")
                store, known = None, {}
                missing = wanted
                fresh = np.asarray(embedder.embed(missing))
            base = len(known)
            for i, t in enumerate(missing):
                known[t] = base + i
            store = fresh if store is None else np.vstack([store, fresh])
            try:
                vec_path.parent.mkdir(parents=True, exist_ok=True)
                np.save(vec_path, store)
                names = [""] * len(known)
                for t, i in known.items():
                    names[i] = t
                terms_path.write_text(json.dumps(names), encoding="utf-8")
                print(f"[{self.name}] vector store now holds {len(names):,} terms "
                      f"({store.nbytes/1e6:.0f} MB)")
            except OSError as e:                  # a full disk must not lose the run
                print(f"[{self.name}] could not write the vector store ({e}); "
                      f"continuing with the vectors in memory")
        return np.asarray([store[known[t]] for t in terms])

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
        named = self._term_mapping.named()
        heads = self._term_mapping.heads()
        def _rank(t: str):
            return canonical_rank(t, anchor_set, freq, named, heads)

        def _canonical(members: list[str]) -> tuple[str, str]:
            """Pick the cluster's canonical, then take the singular spelling of it.

            Returns `(canonical, source)`. `source` is the member the canonical
            was derived from; it is the canonical itself unless the spelling
            was MINTED, in which case the canonical is in no cluster and has no
            embedding, and `source` is the only thing a cosine can be measured
            against.

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
                return best, best
            def _is_singular(m: str) -> bool:
                words = m.split()
                return bool(words) and singularize(words[-1]) == words[-1].lower()

            same = [m for m in members if fold(m) == fold(best) and _is_singular(m)]
            # ...and if the corpus never said it in the singular, spell it so.
            # Rule 23 could only pick a singular spelling that existed; the
            # curator's rule of 2026-09-23 is that the name is singular whether
            # or not anybody wrote it that way.
            if same:
                return max(same, key=_rank), best
            return singular_spelling(best), best

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
        # ONE PASS IS NOT ENOUGH. A minted canonical need not fold to the key of
        # the group that minted it: `multi-drug resistant bacterias` folds to
        # `multi drug resistant bacteria` and mints `multi-drug resistant
        # bacteria`, which folds to `multi drug resistant bacterium` -- the key
        # of a DIFFERENT group, whose canonical is `multi-drug-resistant
        # bacterium`. Two spellings of one term then went to SapBERT as two
        # terms. Measured on the 2026-09-26 corpus: 649 of 90,435 groups mint a
        # canonical belonging to another group, and 16 pairs of canonicals fold
        # together -- `Autoimmune disease`/`autoimmune disease`,
        # `mitogen-activated protein kinase`/`mitogen activated protein kinase`,
        # `foreign-body response`/`foreign body response`. So fold again, until
        # the set stops moving. It also closes the mint route through step 3:
        # after the fixed point no canonical spells differently from itself.
        pre_merged: dict[str, str] = {}
        self.refused_mappings: list[tuple[str, str]] = []
        MAX_FOLD_ROUNDS = 10
        pool: list[str] = unique_terms
        converged = False
        rounds = 0
        for rounds in range(1, MAX_FOLD_ROUNDS + 1):
            norm_groups: dict[str, list[str]] = defaultdict(list)
            for t in pool:
                norm_groups[fold(t)].append(t)
            canonicals: list[str] = []
            for members in norm_groups.values():
                canonical, _source = _canonical(members)
                canonicals.append(canonical)
                for t in members:
                    if t == canonical:
                        continue
                    # The validator has to run here as well as on the clustered
                    # path. It did not, and `Process` was mapped to BFO's
                    # `process` by normalised-form pre-merge -- the one mapping
                    # guaranteed to break category detection, arriving through
                    # the door nobody was watching.
                    if (accept_mapping is not None and canonical in anchor_set
                            and not accept_mapping(t, canonical)):
                        self.refused_mappings.append((t, canonical))
                        continue
                    pre_merged[t] = canonical
            nxt = list(dict.fromkeys(canonicals))
            converged = set(nxt) == set(pool)
            if rounds > 1:
                print(f"[{self.name}] fold round {rounds}: {len(pool):,} -> "
                      f"{len(nxt):,} spellings"
                      f"{' (fixed point)' if converged else ''}.")
            pool = nxt
            if converged:
                break
        embed_terms: list[str] = pool
        if not converged:
            # Not fatal -- the metadata step below no longer assumes a canonical
            # is embedded -- but it means two spellings of one term may still be
            # clustered as two, and that must not pass in silence.
            print(f"[{self.name}] WARNING: the folded pre-merge did not settle in "
                  f"{MAX_FOLD_ROUNDS} rounds; {len(embed_terms):,} spellings are "
                  f"going to the model and some of them may be the same term.")

        # A term folded in round 1 points at a spelling round 2 may have folded
        # again. Follow each chain to its end: without this the metadata step
        # would record a mapping onto a spelling that is no longer a canonical.
        resolved: dict[str, str] = {}
        looped: list[str] = []
        for t, first in pre_merged.items():
            seen, cur = {t}, first
            while cur in pre_merged and cur not in seen:
                seen.add(cur)
                cur = pre_merged[cur]
            if cur == t:
                looped.append(t)
                continue
            resolved[t] = cur
        chained = sum(1 for t, c in resolved.items() if pre_merged[t] != c)
        # `set(embed_terms)` once. Inside the comprehension it was rebuilt for
        # every one of the 32,000 folded terms -- 2.9 billion membership tests,
        # and the build sat there saying nothing.
        canonical_set = set(embed_terms)
        survived = [t for t in resolved if t in canonical_set]
        for t in survived:
            del resolved[t]
        pre_merged = resolved

        if pre_merged:
            print(f"[{self.name}] Pre-merged {len(pre_merged)} terms by folded form "
                  f"in {rounds} round(s); {chained} re-pointed by a later round.")
        if looped:
            print(f"[{self.name}] {len(looped)} term(s) fold in a cycle and were "
                  f"left unmapped: {', '.join(repr(t) for t in looped[:5])}")
        if survived:
            print(f"[{self.name}] {len(survived)} term(s) were both folded away and "
                  f"elected canonical; kept as canonical: "
                  f"{', '.join(repr(t) for t in survived[:5])}")

        print(f"[{self.name}] Embedding {len(embed_terms)} terms with SapBERT...")
        emb = self._embeddings_for(embed_terms, embedder)

        n = len(embed_terms)
        term_to_idx = {t: i for i, t in enumerate(embed_terms)}

        # ── Step 1: valid pairs ───────────────────────────────────────────────
        #
        # In BLOCKS. `emb @ emb.T` is one array of n^2 float32, and the corpus
        # made n 90,435: **32.7 GB on a 17 GB machine**. It would have embedded
        # for forty minutes and then died, or swapped for hours first. A block
        # of 1,000 rows is 362 MB and only the pairs above the threshold are
        # kept, which is a few hundred thousand, not eight billion.
        BLOCK = SIMILARITY_BLOCK
        valid: set[tuple[int, int]] = set()
        score: dict[tuple[int, int], float] = {}
        for start in range(0, n, BLOCK):
            block = emb[start:start + BLOCK] @ emb.T
            rows, cols = np.where(block >= similarity_threshold)
            for r, c in zip(rows.tolist(), cols.tolist()):
                i = start + r
                if i >= c:
                    continue
                a, b = embed_terms[i], embed_terms[c]
                if (_is_generic(a) or _is_generic(b)) and _string_sim(a, b) < 0.90:
                    continue
                valid.add((i, c))
                score[(i, c)] = float(block[r, c])
            del block

        print(f"[{self.name}] {len(valid)} valid pairs "
              f"(cosine ≥ {similarity_threshold}) …")

        # ── Step 2: complete-linkage clustering ───────────────────────────────
        cluster_of: list[int]          = list(range(n))
        cl_members: dict[int, set[int]] = {i: {i} for i in range(n)}

        for i, j in sorted(valid, key=lambda p: score[p], reverse=True):
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
        minted_from: dict[str, str] = {}
        for members in clusters.values():
            canonical, source = _canonical(members)
            if canonical not in term_to_idx:
                minted_from[canonical] = source
            if accept_mapping is not None and canonical in anchor_set:
                kept = [t for t in members
                        if t == canonical or accept_mapping(t, canonical)]
                for t in members:
                    if t not in kept:
                        self.refused_mappings.append((t, canonical))
                members = kept
            for t in members:
                assignment[t] = canonical
            # `_canonical` may MINT a spelling: rule 23a says the name is
            # singular whether or not anybody wrote it that way, so a cluster
            # of `multi-drug resistant bacteria` alone is named
            # `multi-drug resistant bacterium`, which is in no cluster and
            # therefore had no entry of its own. The forest assertion below
            # then died with a KeyError on the canonical it was checking --
            # after fifty minutes of embedding. A canonical maps to itself.
            # The fold fixed point above should now leave nothing to mint here;
            # this stays because the assertion is about `assignment`, not about
            # what the pre-merge happens to have achieved.
            assignment.setdefault(canonical, canonical)

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
            if term == canonical:
                # An identity entry is dropped from `merges` below and its
                # metadata is never read. Skipping it is not an optimisation:
                # a MINTED canonical has no embedding, so scoring it against
                # itself is the second crash this build died of.
                continue
            idx_t = term_to_idx[term]
            idx_c = term_to_idx.get(canonical)
            if idx_c is None:
                source = minted_from.get(canonical)
                if source is None or source not in term_to_idx:
                    raise AssertionError(
                        f"{canonical!r} is a canonical with no embedding and no "
                        f"record of the member it was minted from. The mapping "
                        f"would get a confidence nobody computed; refusing to "
                        f"write one."
                    )
                # The merge is still the SapBERT cluster; what has no cosine is
                # the rename at the end of it. Score against the member the
                # spelling was minted from, which is in the cluster.
                idx_c = term_to_idx[source]
            metadata_batch[term] = {
                "standard": canonical,
                # not necessarily a pair above the threshold -- complete
                # linkage puts terms in one cluster through others -- so it is
                # computed rather than looked up
                "confidence": float(emb[idx_t] @ emb[idx_c]),
                "method": "sapbert_cluster",
            }

        # Only real merges are persisted. An identity entry is a no-op -- get()
        # already returns an unmapped term unchanged -- but writing one per
        # canonical made the file 92% no-op (24441 of 26625 entries) and buried
        # the ~200 decisions a curator actually has to look at.
        merges = {t: c for t, c in assignment.items() if t != c}
        # A refusal already recorded against this exact pair stands. Clustering
        # is not a vote it can win by being run again: before this check a
        # curator's `n` was a deletion, so the next build re-proposed the merge
        # and the adjudication cache re-approved it from memory. The guard's
        # refusals survived a rebuild and the curator's did not.
        standing = {t: c for t, c in merges.items()
                    if self._term_mapping.is_refused(t, c)}
        for t in standing:
            merges.pop(t)
        if standing:
            print(f"[{self.name}] {len(standing)} proposed merge(s) skipped — a "
                  f"refusal is on record against that exact pair:")
            for t, c in list(standing.items())[:5]:
                why = self._term_mapping.is_refused(t, c) or {}
                print(f"[{self.name}]     {t!r} -> {c!r} refused by "
                      f"{why.get('by', 'someone')}: {why.get('reason', '')[:60]}")
        self._report_skipped(self._term_mapping.add_batch(
            merges, {t: metadata_batch[t] for t in merges if t in metadata_batch}),
            "this build")

        # The mapping persists across builds, so a mapping this build refuses may
        # still be present from an earlier one that had no validator. Withdraw it
        # rather than let the guard be silently defeated by the file -- but only
        # that exact pair, so curation done in review_mapping is untouched.
        stale = [t for t, canonical in self.refused_mappings
                 if self._term_mapping.data.get(t) == canonical]
        if stale:
            self._term_mapping.retire(*stale, reason="refused by the category guard")
            print(f"[{self.name}] withdrew {len(stale)} refused mapping(s) recorded "
                  f"by an earlier build.")
        # This build's decision about the terms it was given, identities included,
        # so a caller can ask what happened to any input term. It is deliberately
        # NOT the persisted mapping: the file holds only merges, and it also holds
        # entries from earlier builds that these terms say nothing about.
        return assignment
