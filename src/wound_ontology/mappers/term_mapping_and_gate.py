"""The GROUND TRUTH for what a term is, and every view onto it.

One record per term, holding everything anyone ever decided about that term.
Two questions are decided about a term and both live here:

* **where it belongs** -- what it maps onto, by what method, and, per candidate
  canonical, what each adjudication pass said, what the curator said, and
  whether the pair stands refused;
* **whether it belongs** -- the gate: in scope for the ontology, or out.

Nothing about either lives anywhere else. DataManager is this class's only I/O
dependency.

Why it is shaped this way
-------------------------
An entry used to be `term -> canonical` and nothing else, and everything known
*about* it lived somewhere else: the model's first verdict in
`mapping_adjudication_*.json`, its second in `mapping_second_opinion_*.json`,
the flags and the curator's marks in a review CSV. Four artifacts for one fact,
and two failures hiding in the split:

  * **A curator's refusal was a deletion.** `withdraw()` removed the entry and
    recorded nothing, so the next `build_from_embeddings` re-proposed the merge,
    the adjudication cache answered `same_class` for it again, and the refusal
    was gone. The guard's refusals survived a rebuild; the curator's did not.
  * **Two writers, one fact.** Copying `pass1` onto the record while the cache
    file stayed authoritative meant the same verdict lived in two places with
    nothing keeping them equal.

Both are the same disease, and rule 33 already names the cure for the store: a
decision is a verdict IN the record, never a deletion and never a side file.
This module applies it to the mapping. The adjudication caches are now a *view*
(`pass_cache`) that reads and writes the records in place, so asking the model
writes the answer where the decision lives, once.

The gate arrived the same way, from the same failure one layer over. Whether a
term is in scope was decided in two Python literals -- `METHODOLOGY_BLOCKLIST`
(7,757 entries) and `WHITELIST` (2,684) -- written by a cosine threshold and an
LLM batch straight into source files, with no verdict, no reason, no date and no
author. Measured on 2026-09-25: **201 of the 1,612 families the curator reviewed
by hand had a canonical the blocklist already rejects**, and they approved 167 of
them, because nothing in front of them said so. And the list had swallowed
`silver sulfadiazine`, `photobiomodulation`, `tissue repair`, `bone healing` and
`vac therapy`, indistinguishable from a decision someone meant.

The record
----------
::

    {"to":         "Wound",                # None once refused or retired
     "method":     "sapbert_cluster",
     "confidence": 0.97,
     "retired":    {"reason": "inert spelling", "when": "..."},
     "gate": {                             # whether the ontology carries it
        "rule":    {"verdict": "out", "by": "METHODOLOGY_BLOCKLIST", "when": "..."},
        "pass1":   {"verdict": "out", "score": 0.94, "near": "..."},
        "pass2":   {"verdict": "in",  "reason": "..."},
        "curator": {"verdict": "in",  "reason": "...", "when": "..."}},
     "pairs": {
        "Wound": {"pass1":   {"verdict": "same_class", "reason": "..."},
                  "pass2":   {"verdict": "different",  "reason": "..."},
                  "curator": {"verdict": "refused", "reason": "...", "when": "..."},
                  "refused": {"reason": "...", "by": "curator", "when": "..."}},
        "Wound care process": {"pass1": {"verdict": "different", "reason": "..."}},
     }}

`pairs` is keyed by CANONICAL, not flattened onto the term, because a term is
judged against more than one canonical across builds -- 192 of them in the
2026-09-24 file. Refusing `materials -> material entity` must not stop
`materials` ever mapping onto something else, and `different` on one candidate
says nothing about another.

The views
---------
* `data`                  -- `term -> canonical`, the live mapping every
                             consumer expects. Retired and refused entries are
                             absent, exactly as a deleted entry used to be.
* `pass_cache(name)`      -- the adjudicator's cache interface, backed by the
                             records. Replaces the two JSON cache files.
* `verdicts(name)`        -- every verdict of one pass, as a plain dict.
* `subsumption_candidates()` -- the pairs a pass called `narrower`/`broader`:
                             not synonyms, not nothing.
* `gated("out")` / `gated("in")` -- what `METHODOLOGY_BLOCKLIST` and `WHITELIST`
                             used to BE. Both are now views, so an entry cannot
                             exist without saying who put it there.
* `gate_disagreements()`  -- the terms whose gate sources contradict each other.
* `metadata`, `standards`, `originals` -- as before.

Nothing in here derives a view and stores it. A view is computed from the
records on every call (`data` caches, and every write invalidates it), so a
view cannot drift from the truth it is a view of.
"""

from __future__ import annotations

import datetime as _dt
import re as _re
from collections.abc import MutableMapping

from wound_ontology.data_manager.data_manager import DataManager

#: Separator for the `term \x1f canonical` key the adjudication passes use.
#: `mapping_adjudicator.pair_key` builds the same key; the two are pinned
#: together by a test rather than by hope.
KEY_SEP = "\x1f"

#: Verdicts that make a pair a candidate subsumption edge rather than a merge.
SUBSUMPTION_VERDICTS = ("narrower", "broader")

#: The gate's two answers: does the ontology carry this concept at all?
GATE_VERDICTS = ("in", "out")

#: Where a gate verdict can come from, strongest first. Rule 28: an explicit
#: decision outranks a heuristic, and a model is a heuristic.
GATE_SOURCES = ("curator", "pass2", "pass1", "rule")


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class _PassCache(MutableMapping):
    """One adjudication pass, as the `dict[key] -> {verdict, reason}` the
    adjudicator expects -- but backed by the records.

    `adjudicate()` mutates its cache in place and the caller persists it. Here
    the mutation lands on the record itself, so the verdict and the entry it
    judges cannot drift apart. Writes mark the owner dirty; the OWNER saves,
    because a 2 MB file rewritten per verdict would cost more than the model
    call it is caching.

    `read=False` is the `readjudicate` path: every lookup misses, so every pair
    is asked again, and the new answers still land on the records.
    """

    def __init__(self, owner: "TermMappingAndGate", name: str, *, read: bool = True) -> None:
        self._owner = owner
        self._name  = name
        self._read  = read

    def __getitem__(self, key: str) -> dict:
        if not self._read:
            raise KeyError(key)
        term, _, canonical = key.partition(KEY_SEP)
        # `peek`, not `judgement`: a MISS must not create the record it missed,
        # or asking the cache about 15,000 proposed pairs would write 15,000
        # empty ones into the ground truth.
        hit = self._owner.peek(term, canonical).get(self._name)
        if hit is None:
            raise KeyError(key)
        return hit

    def __setitem__(self, key: str, value: dict) -> None:
        term, _, canonical = key.partition(KEY_SEP)
        self._owner.judge(term, canonical, **{self._name: value})

    def __delitem__(self, key: str) -> None:
        term, _, canonical = key.partition(KEY_SEP)
        self._owner.judgement(term, canonical).pop(self._name, None)

    def __iter__(self):
        if not self._read:
            return iter(())
        return iter(self._owner.verdicts(self._name))

    def __len__(self) -> int:
        return 0 if not self._read else len(self._owner.verdicts(self._name))


class TermMappingAndGate:
    """Persistence data class for the term mapping, the gate, and their evidence.

    Layer 2 in the mapper stack:
      DataManager (repo) → TermMappingAndGate (persistence) → TermMapper (action) → MappingCleaner (curator)
    """

    def __init__(self, dm: DataManager, file_name: str = "term_mapping") -> None:
        self._dm        = dm
        self._file_name = file_name
        self._records: dict[str, dict] = self._load(dm.load_latest_json(file_name) or {})
        self._flat: dict[str, str] | None = None
        self._gate_idx: dict[str, str] | None = None
        self._members_idx: dict[str, list[str]] | None = None

    # ── Loading and migration ────────────────────────────────────────────────

    @staticmethod
    def _load(raw: dict) -> dict[str, dict]:
        """Read any of the three formats this file has had.

        A flat `term -> canonical` file, or a record with `pass1`/`pass2`/
        `refused` at the TERM level, is migrated in memory and written in the
        current shape the next time anything saves. No separate migration step
        exists to be forgotten -- which is the same reason the caches are now
        read through `pass_cache` rather than off disk.
        """
        records: dict[str, dict] = {}
        for term, value in raw.items():
            if not isinstance(value, dict):                      # v1: flat
                records[term] = {"to": value, "pairs": {}}
                continue
            rec = dict(value)
            rec.setdefault("to", None)
            pairs = {c: dict(j) for c, j in (rec.get("pairs") or {}).items()}
            # v2: the verdicts sat on the term and the refusals in their own
            # dict. Both are about a PAIR, so both move onto the canonical they
            # were always about.
            target = rec.get("to")
            for field in ("pass1", "pass2", "curator"):
                moved = rec.pop(field, None)
                if moved and target:
                    pairs.setdefault(target, {}).setdefault(field, moved)
                elif moved:
                    # No target left to attach it to: a v2 record that was
                    # refused. `refused` below carries the canonical.
                    for canonical in (value.get("refused") or {}):
                        pairs.setdefault(canonical, {}).setdefault(field, moved)
            if not isinstance(rec.get("refused"), dict):
                rec.pop("refused", None)
            for canonical, refusal in (rec.pop("refused", None) or {}).items():
                pairs.setdefault(canonical, {}).setdefault("refused", refusal)
            rec["pairs"] = pairs
            records[term] = rec
        return records

    # ── Read access: the records themselves ──────────────────────────────────

    @property
    def records(self) -> dict[str, dict]:
        """The ground truth: every term, every verdict, every mark."""
        return self._records

    def record(self, term: str) -> dict:
        """The record for `term`, created empty if there is none."""
        rec = self._records.setdefault(term, {"to": None, "pairs": {}})
        rec.setdefault("pairs", {})
        return rec

    def judgement(self, term: str, canonical: str) -> dict:
        """Everything decided about this exact PAIR, created empty if new."""
        return self.record(term)["pairs"].setdefault(canonical, {})

    def peek(self, term: str, canonical: str) -> dict:
        """What is on record for this pair, WITHOUT creating anything."""
        return self._records.get(term, {}).get("pairs", {}).get(canonical, {})

    def is_refused(self, term: str, canonical: str) -> dict | None:
        """The refusal standing against this exact pair, if there is one."""
        return self.peek(term, canonical).get("refused")

    # ── Read access: the live mapping ────────────────────────────────────────

    @property
    def data(self) -> dict[str, str]:
        """The mapping every consumer expects: original_term → canonical_term.

        A view of the records, cached until something writes. A record without a
        live `to` -- refused, or retired as inert -- is absent, so nothing
        downstream can act on a decision by accident.
        """
        if self._flat is None:
            self._flat = {t: r["to"] for t, r in self._records.items() if r.get("to")}
        return self._flat

    @property
    def metadata(self) -> dict[str, dict]:
        """Per-term confidence and method, as the old in-memory dict presented it."""
        return {t: {"standard": r.get("to"),
                    "confidence": r.get("confidence", 1.0),
                    "method": r.get("method", "manual")}
                for t, r in self._records.items() if r.get("to")}

    @property
    def standards(self) -> list[str]:
        """Unique sorted canonical (target) terms."""
        return sorted(set(self.data.values()))

    @property
    def originals(self) -> list[str]:
        """Sorted list of all live raw terms in the mapping."""
        return sorted(self.data.keys())

    def get(self, term: str) -> str:
        """Return canonical form; returns *term* unchanged if not mapped."""
        return self.data.get(term, term)

    def __contains__(self, term: str) -> bool:
        return term in self.data

    def __len__(self) -> int:
        return len(self.data)

    # ── Read access: the adjudication views ──────────────────────────────────

    def pass_cache(self, name: str, *, read: bool = True) -> _PassCache:
        """The named pass's verdicts, in the shape `adjudicate(cache=…)` wants.

        This is what replaced `mapping_adjudication_*.json` and
        `mapping_second_opinion_*.json`. Writes land on the records; the caller
        saves.
        """
        return _PassCache(self, name, read=read)

    def verdicts(self, name: str) -> dict[str, dict]:
        """Every verdict of one pass, keyed `term \\x1f canonical`."""
        return {f"{t}{KEY_SEP}{c}": j[name]
                for t, rec in self._records.items()
                for c, j in rec.get("pairs", {}).items() if j.get(name)}

    def judged(self, name: str) -> int:
        """How many pairs this pass has answered."""
        return len(self.verdicts(name))

    def subsumption_candidates(self) -> list[dict]:
        """The pairs a pass called `narrower` or `broader`.

        Not synonyms, so they never became mappings -- but not nothing either:
        each is a candidate subsumption edge, in the hierarchy's own
        'Class' / 'Parent class' shape with the specific one first, so the view
        can be read straight into a review without re-deriving which way round
        the verdict pointed.

        A view over the whole ground truth, not over one build: a pair judged
        `narrower` in September is still a candidate edge in October, and the
        old behaviour -- write only what this run happened to re-ask -- lost it
        the moment the cache answered from memory.
        """
        rows = []
        for term, rec in self._records.items():
            for canonical, j in rec.get("pairs", {}).items():
                v1 = (j.get("pass1") or {}).get("verdict")
                v2 = (j.get("pass2") or {}).get("verdict")
                direction = v1 if v1 in SUBSUMPTION_VERDICTS else v2
                if direction not in SUBSUMPTION_VERDICTS:
                    continue
                narrower = direction == "narrower"
                rows.append({
                    "Class":        term if narrower else canonical,
                    "Parent class": canonical if narrower else term,
                    "store term": term, "ontology class": canonical,
                    "pass 1": v1, "pass 1 reason": (j.get("pass1") or {}).get("reason", ""),
                    "pass 2": v2, "pass 2 reason": (j.get("pass2") or {}).get("reason", ""),
                    "agree": bool(v1 and v2 and v1 == v2),
                    "mapped": rec.get("to") == canonical,
                })
        return sorted(rows, key=lambda r: (r["store term"], r["ontology class"]))

    def disagreements(self) -> list[dict]:
        """Pairs where the two passes did not say the same thing.

        Two independently-evidenced judgements agreeing is decent grounds to
        wave a row through; disagreeing is where a curator is worth the time.
        """
        rows = []
        for term, rec in self._records.items():
            for canonical, j in rec.get("pairs", {}).items():
                v1 = (j.get("pass1") or {}).get("verdict")
                v2 = (j.get("pass2") or {}).get("verdict")
                if v1 and v2 and v1 != v2:
                    rows.append({"term": term, "canonical": canonical,
                                 "pass 1": v1,
                                 "pass 1 reason": j["pass1"].get("reason", ""),
                                 "pass 2": v2,
                                 "pass 2 reason": j["pass2"].get("reason", ""),
                                 "mapped": rec.get("to") == canonical})
        return sorted(rows, key=lambda r: (r["term"], r["canonical"]))

    # ── Read access: the gate ────────────────────────────────────────────────

    def gate_record(self, term: str) -> dict:
        """The gate section for `term`, created empty if there is none."""
        return self.record(term).setdefault("gate", {})

    def peek_gate(self, term: str) -> dict:
        """What the gate holds for `term`, WITHOUT creating anything."""
        return self._records.get(term, {}).get("gate", {})

    @staticmethod
    def _gate_key(term: str) -> str:
        """The spelling the two lists have always matched on.

        `TermList.match` lowercases, strips a trailing parenthetical and runs
        `normalize_term` (rule 13). The gate has to agree, or it answers about
        `cohort` and says nothing about `Cohort` -- and the store holds both:
        92,683 of its 96,243 names looked undecided to an exact-match gate
        against 77,317 to the lists.

        The RECORD stays keyed by the exact spelling, because the mapping side
        needs `Wound` and `wound` apart. Only the gate lookup folds them.

        `normalize_term` alone, not lowercase-then-strip-then-normalize: it
        already lowercases, strips a parenthetical and flattens hyphens, and
        rule 13 is that a name is normalised in exactly ONE way. Doing the first
        two steps again here would be a second implementation of a rule that
        already has one, which is the family of bug rules 25-29 exist for.

        It folds more than case: `N/A` and `Na+` share the key `na`. So do the
        lists, which is why `Na+ -> NA` was ever proposed -- the collision is
        inherited, not introduced, and the exact record always wins over it.
        """
        from wound_ontology.utils.string_utils import normalize_term
        return normalize_term(term) or term.strip().lower()

    def _gate_alias(self, term: str) -> str | None:
        """Another spelling of `term` that carries a gate section, if there is one."""
        if self._gate_idx is None:
            idx: dict[str, str] = {}
            for name, rec in self._records.items():
                if rec.get("gate"):
                    key = self._gate_key(name)
                    # deterministic when two spellings both carry a gate: the
                    # one that IS the normalised key wins, else the first
                    # alphabetically, so two runs never disagree
                    if key not in idx or name == key or name < idx[key]:
                        if key not in idx or name == key or idx[key] != key:
                            idx[key] = name
            self._gate_idx = idx
        hit = self._gate_idx.get(self._gate_key(term))
        return hit if hit and hit != term else None

    def gate_verdict(self, term: str) -> tuple[str, str]:
        """`(verdict, source)` for `term`, or `("", "")` if nothing decided it.

        Precedence, strongest first:

        1. **the curator**, always and alone;
        2. **the passes**, when they agree, or when only one of them answered;
        3. **the rule** -- the list entry this term was imported from.

        Passes that CONTRADICT each other decide nothing and fall through to the
        rule. That is the whole reason for having two: a disagreement is a
        question for the curator, and answering it by picking a pass would throw
        away the only signal that says a term needs looking at. `gate_disagreements`
        is where they surface.

        The keyword lists are not consulted here and never will be. A keyword is
        a RULE over strings nobody has seen yet -- `Blocker` applies it to any
        term, including the 77,317 this record says nothing about -- and rule 29
        is that an entry belongs in the list whose matching rule it can carry.
        """
        g = self.peek_gate(term)
        if not g and (alias := self._gate_alias(term)):
            g = self.peek_gate(alias)
        return self._resolve(g)

    def own_gate_verdict(self, term: str) -> tuple[str, str]:
        """`gate_verdict` WITHOUT the spelling fallback -- this term's own sources.

        Enumeration uses this and lookup uses the other. A record that carries no
        gate of its own must not appear in `gated()` just because another
        spelling of it does, or every export would add the aliases to the file
        and the next one would add theirs.
        """
        return self._resolve(self.peek_gate(term))

    @staticmethod
    def _resolve(g: dict) -> tuple[str, str]:
        cur = (g.get("curator") or {}).get("verdict")
        if cur in GATE_VERDICTS:
            return cur, "curator"
        p1 = (g.get("pass1") or {}).get("verdict")
        p2 = (g.get("pass2") or {}).get("verdict")
        both = [v for v in (p1, p2) if v in GATE_VERDICTS]
        if len(both) == 2 and p1 == p2:
            return p1, "pass1+pass2"
        if len(both) == 1:
            return both[0], "pass1" if p1 in GATE_VERDICTS else "pass2"
        rule = (g.get("rule") or {}).get("verdict")
        if rule in GATE_VERDICTS:
            return rule, "rule"
        return "", ""

    def effective_gate_verdict(self, term: str) -> tuple[str, str]:
        """The verdict that APPLIES to `term`: its canonical's, then its own.

        Scope is a property of the concept, not of the spelling. Once the
        mapping says `post-operative pain` and `postoperative pain` are one
        thing, they cannot be in scope and out of scope, and on 2026-09-25
        **28 pairs were exactly that** -- `Platelet rich plasma` in against
        `platelet-rich plasma` out, `relief of pain` in against `pain relief`
        out. Each is one concept with two answers, and which one applied
        depended on which spelling a reader happened to look up.

        So the CONCEPT decides, not the spelling: the sources on the canonical
        and on every member are pooled and the usual precedence applied to the
        pool -- curator, then the passes, then the rule -- with the canonical's
        entry preferred when two spellings offer the same source.

        Pooling rather than "the canonical simply wins", because the canonical
        is not always the better-informed spelling. `IL6` carries a `rule`
        verdict of `out` imported from a list nobody can account for, while its
        member `IL‑6` carries a `pass2` verdict of `in` with a reason. Letting
        the canonical win there would have quietly undone 37 of the judgements
        the scope pass had just made, including `conventional treatment` and
        `post-operative pain`. Rule 28 does not stop applying because the better
        evidence landed on a variant spelling.

        A term that maps nowhere is its own canonical and decides for itself.
        """
        return self._resolve(self._concept_gate(term))

    def _concept_gate(self, term: str) -> dict:
        """The gate sections of `term`, its canonical and its siblings, pooled."""
        canonical = self.data.get(term) or term
        pooled: dict = {}
        for name in self._members(canonical):
            for source, value in self.peek_gate(name).items():
                if source not in pooled or name == canonical:
                    pooled[source] = value
        if not pooled:
            # Nothing on the concept, so try the spelling -- `gate_verdict`
            # does this and pooling was skipping it, which left
            # `Conventional Treatment` with no answer while
            # `conventional treatment` had a pass 2 verdict on record.
            for name in (term, canonical):
                if (alias := self._gate_alias(name)):
                    pooled = dict(self.peek_gate(alias))
                    if pooled:
                        break
        return pooled

    def _members(self, canonical: str) -> list[str]:
        """`canonical` first, then every term mapped onto it, sorted."""
        if self._members_idx is None:
            idx: dict[str, list[str]] = {}
            for term, target in self.data.items():
                idx.setdefault(target, []).append(term)
            for v in idx.values():
                v.sort(key=str.lower)
            self._members_idx = idx
        return [canonical] + [t for t in self._members_idx.get(canonical, [])
                              if t != canonical]

    def gate_contradictions(self) -> list[dict]:
        """Members whose own gate verdict differs from their canonical's.

        Not the same as `gate_disagreements`, which is about one term's sources
        disagreeing. This is two spellings of ONE concept carrying opposite
        answers -- only possible because the gate was run over spellings before
        it was run over canonicals, and worth keeping visible because the
        member's verdict is the one being ignored.
        """
        rows = []
        for term, canonical in self.data.items():
            mine, my_src = self.gate_verdict(term)
            theirs, their_src = self.gate_verdict(canonical)
            if mine and theirs and mine != theirs:
                rows.append({"term": term, "verdict": mine, "source": my_src,
                             "canonical": canonical, "applies": theirs,
                             "canonical source": their_src})
        rows.sort(key=lambda r: r["term"].lower())
        return rows

    def gated(self, verdict: str) -> dict[str, str]:
        """`term -> source` for every term the gate answers `verdict`.

        This is what replaces reading `METHODOLOGY_BLOCKLIST` (`"out"`) and
        `WHITELIST` (`"in"`) as authoring surfaces: both are now a view over the
        records, so an entry cannot exist without saying who put it there.
        """
        if verdict not in GATE_VERDICTS:
            raise ValueError(f"{verdict!r} is not one of {GATE_VERDICTS}")
        out = {}
        for term, rec in self._records.items():
            if not rec.get("gate"):
                continue
            v, src = self.own_gate_verdict(term)
            if v == verdict:
                out[term] = src
        return out

    def gate_disagreements(self) -> list[dict]:
        """Every CONCEPT whose gate sources do not agree — the review queue.

        Per concept, not per record. Scope resolves over the pooled sources of a
        canonical and its members, so a conflict between a `rule` sitting on one
        spelling and a `pass2` sitting on another is a conflict about one thing;
        counting per record found 84 of the 149 concepts the 2026-09-25 scope
        pass overturned and missed 65, because on those the rule was on a member
        and the verdict on the canonical.

        Three kinds, all worth a curator's eye and none of them visible while
        the decisions lived in two Python literals:

        * the two passes contradict each other;
        * a pass contradicts the rule the concept was imported under;
        * the curator contradicts either.

        `where` names the spelling each source came from, because "which of my
        eleven spellings is on the blocklist" is the first thing to ask.
        """
        rows = []
        seen: set[str] = set()
        for term in self._records:
            canonical = self.data.get(term) or term
            if canonical in seen:
                continue
            seen.add(canonical)
            said: dict[str, str] = {}
            where: dict[str, str] = {}
            for name in self._members(canonical):
                for src in GATE_SOURCES:
                    verdict = (self.peek_gate(name).get(src) or {}).get("verdict")
                    if verdict and (src not in said or name == canonical):
                        said[src] = verdict
                        where[src] = name
            if len(set(said.values())) > 1:
                v, src = self.effective_gate_verdict(canonical)
                rows.append({"term": canonical, "said": said, "where": where,
                             "verdict": v, "source": src,
                             "to": self._records.get(canonical, {}).get("to")})
        rows.sort(key=lambda r: r["term"].lower())
        return rows

    # ── Write access ─────────────────────────────────────────────────────────

    def add(
        self,
        term: str,
        standard: str,
        confidence: float = 1.0,
        method: str = "manual",
        *,
        override: bool = False,
    ) -> None:
        """Add or update one entry and save.

        Writing a pair that stands REFUSED raises. A refusal is a decision, and
        an `add` that quietly overwrote it would be the deletion this class
        exists to stop, wearing a different hat. `override=True` is the
        deliberate reversal, and it clears the refusal rather than hiding it.
        """
        refusal = self.is_refused(term, standard)
        if refusal and not override:
            raise ValueError(
                f"{term!r} -> {standard!r} stands refused "
                f"({refusal.get('by', '?')}, {refusal.get('when', '?')}: "
                f"{refusal.get('reason', '')!r}). Pass override=True to reverse it.")
        if refusal:
            self.judgement(term, standard).pop("refused", None)
        rec = self.record(term)
        rec.update({"to": standard, "confidence": confidence, "method": method})
        rec.pop("retired", None)
        self._dirty()
        self.save()

    def add_batch(
        self,
        entries: dict[str, str],
        metadata_batch: dict[str, dict] | None = None,
    ) -> list[tuple[str, str]]:
        """Add multiple entries at once; saves once at the end.

        Returns the pairs it SKIPPED because they stand refused. A batch is a
        machine proposal, so one refused pair in it is not an error -- but it is
        never silently applied either, and every caller reports the list.
        """
        meta = metadata_batch or {}
        skipped: list[tuple[str, str]] = []
        for term, standard in entries.items():
            if self.is_refused(term, standard):
                skipped.append((term, standard))
                continue
            rec = self.record(term)
            rec["to"] = standard
            rec.pop("retired", None)
            m = meta.get(term)
            if m:
                rec["confidence"] = m.get("confidence", rec.get("confidence", 1.0))
                rec["method"] = m.get("method", rec.get("method", "manual"))
        self._dirty()
        self.save()
        return skipped

    def annotate(self, term: str, **fields) -> None:
        """Attach term-level evidence -- a note, a method -- without touching
        what the term maps to. Pair-level evidence goes to `judge`."""
        self.record(term).update(fields)
        self.save()

    def judge(self, term: str, canonical: str, **fields) -> None:
        """Attach evidence to one PAIR: a pass verdict, a curator's mark.

        This is where a model verdict lands, so the entry carries its own
        provenance instead of pointing at a side file the next build will not
        consult. It does not save -- a pass writes thousands of these; the
        caller saves once.
        """
        self.judgement(term, canonical).update(fields)

    def gate(self, term: str, **fields) -> None:
        """Attach a gate verdict to `term` -- `pass1=`, `pass2=`, `curator=`, `rule=`.

        Does NOT save, for the same reason `judge` does not: a pass writes
        thousands of these and the caller saves once.

        A record is created for a term that has none. That is deliberate and it
        is the difference between this and `judge`: the gate has to be able to
        say "out" about a term that maps nowhere, because most out-of-scope
        terms never got as far as being proposed for a merge.
        """
        bad = [k for k in fields if k not in GATE_SOURCES]
        if bad:
            raise ValueError(f"{bad} is not a gate source; expected {GATE_SOURCES}")
        for k, v in fields.items():
            if isinstance(v, dict) and v.get("verdict") not in GATE_VERDICTS:
                raise ValueError(
                    f"{term!r} {k}: verdict {v.get('verdict')!r} is not one of "
                    f"{GATE_VERDICTS}")
        self.gate_record(term).update(fields)
        self._gate_idx = None

    def refuse(self, term: str, canonical: str, reason: str = "", by: str = "curator") -> None:
        """Record that `term` must NOT map onto `canonical`, and unmap it.

        The pair is remembered, not the term: `materials` refused onto
        `material entity` is still free to map onto something else. A build that
        re-proposes the refused pair has to skip it -- that is the whole point,
        and `TermMapper.build_from_embeddings` enforces it.
        """
        when = _now()
        self.judge(term, canonical,
                   refused={"reason": reason, "by": by, "when": when},
                   curator={"verdict": "refused", "reason": reason, "when": when})
        rec = self.record(term)
        if rec.get("to") == canonical:
            rec["to"] = None
        self._dirty()
        self.save()

    def retire(self, *terms: str, reason: str = "") -> int:
        """Unmap *terms*, keeping everything decided about them; saves if
        anything changed. Returns how many were actually mapped.

        For entries that can no longer do anything -- identities, dead targets,
        inert spellings. It used to DELETE them, which also threw away the model
        verdicts the pair had cost credits to obtain and let the next build ask
        for them again. Retiring keeps the record and empties the mapping, so
        the prune is itself on the record.
        """
        retired = 0
        for t in terms:
            rec = self._records.get(t)
            if rec is None or not rec.get("to"):
                continue
            rec["to"] = None
            rec["retired"] = {"reason": reason, "when": _now()}
            retired += 1
        if retired:
            self._dirty()
            self.save()
        return retired

    def forget(self, *terms: str) -> int:
        """Delete records outright. Nothing in the pipeline calls this: a term
        whose record is gone is a term the next build re-decides from scratch.
        It exists for tests and for repairing a corrupt file by hand."""
        before = len(self._records)
        for t in terms:
            self._records.pop(t, None)
        gone = before - len(self._records)
        if gone:
            self._dirty()
            self.save()
        return gone

    # ── Importing the retired cache files ────────────────────────────────────

    def import_pass(self, name: str, cache: dict[str, dict]) -> dict:
        """Fold a `mapping_adjudication`/`mapping_second_opinion` cache file
        onto the records. Run once, per file; `pass_cache` is how verdicts get
        here from now on.

        Reports rather than resolves a CONFLICT -- the same pair already
        carrying a different verdict for this pass. That should not happen (the
        records were copied FROM these files), and if it does it is a fact about
        the data, not something to paper over.
        """
        added = existing = conflicts = new_terms = 0
        clashes: list[str] = []
        for key, verdict in cache.items():
            term, sep, canonical = key.partition(KEY_SEP)
            if not sep:
                raise ValueError(f"cache key {key!r} is not a {name} pair key")
            if term not in self._records:
                new_terms += 1
            have = self.peek(term, canonical).get(name)
            if have is None:
                self.judge(term, canonical, **{name: verdict})
                added += 1
            elif have.get("verdict") != verdict.get("verdict"):
                conflicts += 1
                if len(clashes) < 5:
                    clashes.append(f"{term!r} -> {canonical!r}: record says "
                                   f"{have.get('verdict')!r}, file says "
                                   f"{verdict.get('verdict')!r}")
            else:
                existing += 1
        self._dirty()
        self.save()
        return {"pass": name, "in_file": len(cache), "added": added,
                "already_on_record": existing, "conflicts": conflicts,
                "new_records": new_terms, "clashes": clashes}

    # ── Persistence ───────────────────────────────────────────────────────────

    def _dirty(self) -> None:
        self._flat = None
        self._gate_idx = None
        self._members_idx = None

    def save(self) -> None:
        """Write current records to disk via DataManager."""
        if self._records:
            self._dm.save_as_json(self._records, self._file_name)
