"""The mapping's GROUND TRUTH, and every view onto it.

One record per term, holding everything anyone ever decided about that term:
what it maps onto, by what method, and -- per candidate canonical -- what each
adjudication pass said, what the curator said, and whether the pair stands
refused. Nothing about a mapping lives anywhere else. DataManager is this
class's only I/O dependency.

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

The record
----------
::

    {"to":         "Wound",                # None once refused or retired
     "method":     "sapbert_cluster",
     "confidence": 0.97,
     "retired":    {"reason": "inert spelling", "when": "..."},
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
* `metadata`, `standards`, `originals` -- as before.

Nothing in here derives a view and stores it. A view is computed from the
records on every call (`data` caches, and every write invalidates it), so a
view cannot drift from the truth it is a view of.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import MutableMapping

from wound_ontology.data_manager.data_manager import DataManager

#: Separator for the `term \x1f canonical` key the adjudication passes use.
#: `mapping_adjudicator.pair_key` builds the same key; the two are pinned
#: together by a test rather than by hope.
KEY_SEP = "\x1f"

#: Verdicts that make a pair a candidate subsumption edge rather than a merge.
SUBSUMPTION_VERDICTS = ("narrower", "broader")


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

    def __init__(self, owner: "TermMapping", name: str, *, read: bool = True) -> None:
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


class TermMapping:
    """Persistence data class for the term mapping and everything decided about it.

    Layer 2 in the mapper stack:
      DataManager (repo) → TermMapping (persistence) → TermMapper (action) → MappingCleaner (curator)
    """

    def __init__(self, dm: DataManager, file_name: str = "term_mapping") -> None:
        self._dm        = dm
        self._file_name = file_name
        self._records: dict[str, dict] = self._load(dm.load_latest_json(file_name) or {})
        self._flat: dict[str, str] | None = None

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

    def save(self) -> None:
        """Write current records to disk via DataManager."""
        if self._records:
            self._dm.save_as_json(self._records, self._file_name)
