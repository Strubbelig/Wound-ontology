from __future__ import annotations
import asyncio
import warnings
import re
from typing import Iterable, Iterator
import pandas as pd
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.utils.string_utils import normalize_term, smart_title
from wound_ontology.llm.category_vocab import declared_category
from wound_ontology.mappers.judgements import current
from wound_ontology.utils.normalise import normalise
from wound_ontology.utils.label_match import singular_spelling as _singular_spelling


def store_name(term: str, canonical: str | None = None, *, target: bool = False) -> str:
    """The name the view gives `term`, given the mapping's answer for it.

    One implementation of "what does this term end up called", used by the
    view's resolver and by `Orchestrator.prune_inert_mappings` to decide
    whether a mapping entry changes anything at all. Written twice they would
    drift, and the prune would delete entries that were doing work.

    Two rules: a declared BFO category is returned as declared and never
    renamed (rule 22), and otherwise the mapping's canonical wins, declared if
    it names a category. Until rule 51 the store also title-cased and
    singularised every name here; pass 0 elects and records the spelling now,
    so the view keeps it exactly -- and a case-only or plural entry is no
    longer inert, because nothing else would produce its canonical.
    """
    declared = declared_category(term)
    if declared is not None:
        return declared
    if canonical is None:
        return term
    return declared_category(canonical) or canonical


DECISIONS = "decisions"
REJECTED = "rejected"
REPREDICATED = "repredicated"


class _NoFile:
    """The term dict of a store that was not handed one: kept in memory."""

    def load_latest_json(self, _name):
        return {}

    def save_as_json(self, _data, _name):
        return None


def _is_typing(triple: str) -> bool:
    return triple.split(":", 1)[0].strip().lower().replace(" ", "_") in ("is_a", "subclass_of")


def _sense_of(attrs: dict) -> str | None:
    """The one BFO category an abstract typed a term as, or None."""
    here = {declared_category(t.split(":", 1)[1].strip())
            for t, v in attrs.items()
            if v == 1.0 and ":" in t and _is_typing(t)
            and declared_category(t.split(":", 1)[1].strip())}
    return next(iter(here)) if len(here) == 1 else None


def _sense_key(name: str) -> str:
    """The key a term's senses are filed under: case variants are ONE conflict
    (rule 13), as the hierarchy that consumes the split groups them."""
    return smart_title(name.strip())


def _senses_here(entities: dict, name, splits: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Which name each split term (rule 87) takes in ONE abstract: the one for
    the category this abstract typed it as. Returns `(by raw entity, by term
    key)`; the second is for targets, since a target is the same term seen
    from the other side (rule 13). A mention typed with no category, or with
    two, keeps the unsplit name."""
    own: dict[str, str] = {}
    by_key: dict[str, str] = {}
    for raw, attrs in entities.items():
        if not isinstance(attrs, dict):
            continue
        key = _sense_key(name(raw)[1])
        label = (splits.get(key) or {}).get(_sense_of(attrs))
        if label:
            own[raw] = label
            by_key[key] = label
    return own, by_key

def _category_chain(cat: str) -> set[str]:
    from wound_ontology.llm.extraction_models import CATEGORY_PARENT
    out = set()
    while cat:
        out.add(cat); cat = CATEGORY_PARENT.get(cat)
    return out


def _apply_categories(entities: dict, decided: dict[str, str]) -> dict:
    """Type each decided term, in ONE abstract, as the category a person decided
    it names (rule 57). A category cell at or below the decision stands (a
    `function` under a decided `disposition` is the same answer, sharper); every
    other category cell is replaced by the decision, at the strongest value it
    replaces. A mention the abstract gave no category keeps none: a decision
    resolves a disagreement, it does not invent a typing. Non-category `is_a`
    targets (`is_a: Wound`) are not categories and are untouched."""
    for entity, cat in decided.items():
        attrs = entities.get(entity)
        if not attrs:
            continue
        drop, keep = [], False
        for triple in attrs:
            pred, _, tgt = triple.partition(":")
            if pred.strip() != "is_a":
                continue
            c = declared_category(tgt.strip())
            if c is None:
                continue
            if cat in _category_chain(c):
                keep = True
            else:
                drop.append(triple)
        if not drop:
            continue
        value = max(attrs.pop(t) for t in drop)
        if not keep:
            attrs[f"is_a: {cat}"] = max(attrs.get(f"is_a: {cat}", 0.0), value)
    return entities


def _rejected_in(raw: dict) -> tuple[set[str], dict[str, set[str]]]:
    """(rejected entities, {entity: rejected triples}) read off a raw store dict."""
    dec = raw.get(DECISIONS) or {}
    ents = {e for e, v in (dec.get("entity_verdicts") or {}).items()
            if isinstance(v, dict) and v.get("status") == REJECTED}
    cells: dict[str, set[str]] = {}
    for e, triples in (dec.get("cell_verdicts") or {}).items():
        got = {t for t, v in (triples or {}).items()
               if isinstance(v, dict) and v.get("status") == REJECTED}
        if got:
            cells[e] = got
    return ents, cells


def effective_records(raw: dict) -> Iterator[tuple[str, dict[str, dict[str, float]]]]:
    """(key, {entity: {triple: value}}) for every assertion record in a raw
    store dict, with the rejected entities and cells left out.

    THE one reading of the store. `ConceptStore.records()` is this; the
    hierarchies, the matrix, the cleaner's scans and the gate adapter all call
    it, whether they were handed a ConceptStore, a test fake with a `.dict`,
    or the file's dict itself -- so a verdict is honoured everywhere or
    nowhere, never in some readers and not others.
    """
    rej_e, rej_c = _rejected_in(raw)
    for key, rec in raw.items():
        if key == DECISIONS or not isinstance(rec, dict):
            continue
        out: dict[str, dict[str, float]] = {}
        for entity, attrs in rec.get("entities", {}).items():
            if entity in rej_e or not isinstance(attrs, dict):
                continue
            dropped = rej_c.get(entity)
            out[entity] = ({t: v for t, v in attrs.items() if t not in dropped}
                           if dropped else dict(attrs))
        yield key, out


def records_of(store) -> Iterator[tuple[str, dict[str, dict[str, float]]]]:
    """The effective records of anything: a ConceptStore's view (rule 51), or,
    for a raw dict or a test fake with a `.dict`, `effective_records` of it."""
    if hasattr(store, "records") and not isinstance(store, dict):
        return store.records()
    raw = store if isinstance(store, dict) else store.dict
    return effective_records(raw)


def _declared_category(term: str) -> str | None:
    """The BFO category `term` names, spelled the one way it is allowed to be.

    A category name is a value from a closed vocabulary, not a piece of prose,
    and normalising it is only ever destructive. It was destructive: the
    vocabulary was CamelCase, `normalize_term` lowercases and `smart_title`
    cannot put CamelCase back, so `MaterialEntity` came out of normalisation as
    `Materialentity` -- not in `CATEGORY_PARENT`, so the hierarchy stopped
    recognising it as a category typing and one term, one category silently
    stopped applying to it. Measured on the 2026-09-07 run: 40 classes ended up
    under two disjoint BFO branches, against 12 before the store was normalised,
    and `Surgical Site Infection` came out both a disposition and a material
    entity.

    The vocabulary is now spelled `material entity`, which survives
    normalisation intact, so this guard is no longer the only thing standing
    between the store and that bug. Matching is separator-blind, which repairs a
    store damaged under the old spelling and reads a cache written under it.
    """
    return declared_category(term)


class ConceptStore:
    """
    What each abstract said, and the view of it everything downstream reads.

    The file holds EVIDENCE only (rule 51), one record per abstract::

      {"<pmid>": {"entities": {"<as extracted>": {"<pred>: <as extracted>": 1.0}},
                  "meta_stamp": "...", "schema_report": {...}},
       "predefined" / "llm_fill" / ...: synthetic records, same shape}

    Nothing in it is rewritten after it arrives. Every decision about a TERM --
    how it is spelled now, what it maps onto, whether it is rejected, which of
    its relations are rejected, which category it names, how it splits by
    category -- lives on that
    term's record in the term mapping and gate dict (`self.terms`). `records()`
    is the evidence resolved through those records: raw string -> spelling ->
    mapping -> verdicts. A rename is therefore a line in the term dict, not an
    edit of 6,029 abstracts, and what an abstract said is always the file
    itself.

    Until 2026-09-27 the store was rewritten in place by pass 0, the mapping
    apply and the sense split, and kept its own `decisions` record beside the
    PMIDs: a second place deciding things about terms, and the reason a
    provenance book had to be carried through every rename.

    Readers go through `records()` / `assertions()` / `view()`. `dict` is the
    raw evidence and is what a test inspects to see what was STORED.
    """

    DECISIONS = DECISIONS
    """Reserved record key. It carries no `entities` key on purpose: a legacy
    reader doing `rec.get("entities", {})` sees nothing there, so a store with
    verdicts in it cannot be misread as a store with extra assertions."""

    REJECTED = REJECTED
    REPREDICATED = REPREDICATED
    #: `(agent, "relations" | "is_a")`: whose judgements on which cells the
    #: view sets aside, so that agent hears them again (the reasoner's re-check,
    #: rule 89) -- or a frozenset of agents (`term_mapping_and_gate.heard`).
    #: Nothing is lifted from the term dict, so nothing is put back.
    reopen: tuple[str | frozenset[str], str] | None = None

    @staticmethod
    def clean_entity_str(term: str) -> str:
        """The spelling the store keeps for a term the moment it arrives.

        'Systemic Sclerosis (SSc)' -> 'Systemic sclerosis'
        'Diabetic Foot Ulcers'     -> 'Diabetic foot ulcer'
        'Necrotising fasciitis'    -> 'Necrotizing fasciitis'

        The parenthetical is stripped, and then pass 0's per-label rules run
        here rather than being waited for -- the curator, 2026-09-26: the
        normalisation *should be run after every concept extraction on the new
        extract*. Singular head noun (rule 23a) and American spelling (rule
        41) are a pure function of the label and have no reason to wait for a
        maintenance pass. The other half of pass 0, which elects one spelling
        per group, needs the whole store and still runs as that pass.

        Since 2026-10-24 the name is also in sentence case (`sentence_case`:
        lowercase with a capital first letter, abbreviations and names kept),
        the way WONT writes its labels. The raw string is still what the store
        holds (rule 51); the cleaned name is only recorded as its spelling.
        """
        return normalise(re.sub(r'\s*\([^)]*\)', '', term).strip()).name

    @staticmethod
    def clean_target_str(term: str) -> str:
        """The spelling the store keeps for a predicate's target.

        The same rules as `clean_entity_str`: a target and an entity are the
        same term seen from two sides, and the store held `Tumor` as a subject
        beside `Tumours` as an object for exactly as long as these two
        functions did different things.
        """
        return normalise(re.sub(r'\s*\([^)]*\)', '', term).strip()).name

    def __init__(self, data_manager: DataManager, file_name: str, terms=None):
        """`terms` is the term mapping and gate dict every decision lives in.
        Without one the store keeps an in-memory dict of its own, so a store
        built for a test still records and applies its verdicts; the live
        mapping is applied only through a `terms` handed in (or `normalize`)."""
        self.dm = data_manager
        self.file_name = file_name
        self._dict = self.dm.load_latest_json(self.file_name)
        if (self._dict or {}).get(DECISIONS):
            # A pre-rule-51 file: its verdicts would be silently ignored by the
            # view, which reads them from the term dict. Refuse instead.
            raise ValueError(
                f"{file_name!r} still holds a `decisions` record; its rejections "
                f"and renames belong in the term dict now. Run "
                f"scripts/p4_split_evidence_and_decisions.py first (rule 51).")
        self._terms = terms
        self._live_mapping = terms is not None
        self._mapper = None
        #: The predicates the view keeps (rule 86); None keeps every one. The
        #: orchestrator hands in its allowed predicates.
        self.allowed_predicates: list[str] | None = None

    @property
    def terms(self):
        """The term mapping and gate dict every decision lives in (rule 51);
        an in-memory one for a store that was not handed one."""
        if getattr(self, "_terms", None) is None:
            from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
            self._terms = TermMappingAndGate(_NoFile())
            self._live_mapping = False
        return self._terms

    # ── Core storage ──────────────────────────────────────────────────────────

    @property
    def dict(self) -> dict:
        if self._dict is None:
            self._dict = {}
        return self._dict

    @dict.setter
    def dict(self, new_data: dict):
        self.dict.update(new_data)
        self.save()

    # ── The view: evidence resolved through the term dict (rule 51) ──────────

    def document_keys(self) -> list[str]:
        """Every record key that holds assertions -- PMIDs and the synthetic
        records. A pre-rule-51 file's `decisions` record is not one."""
        return [k for k in self.dict if k != self.DECISIONS]

    def _mapping(self, mapped: bool) -> dict[str, str]:
        if not mapped:
            return {}
        mapper = getattr(self, "_mapper", None)
        if mapper is not None:
            return dict(getattr(mapper, "mapping", mapper) or {})
        terms = self.terms
        return terms.data if getattr(self, "_live_mapping", False) else {}

    def resolver(self, *, mapped: bool = True):
        """`name(raw) -> (spelled, final)` for this view.

        `spelled` is the string's current spelling (its aliases followed);
        `final` is where the mapping sends that spelling. The mapping is looked
        up exactly and then on the folded key, as the in-place apply did,
        because its keys were written against spellings the store has since
        moved on from. Memoised: 100,000 names resolve in well under a second.
        """
        resolve = self.terms.resolve
        term_map = self._mapping(mapped)
        folded: dict[str, str] = {}
        for k, v in term_map.items():
            folded.setdefault(normalize_term(k), v)
        cache: dict[str, tuple[str, str]] = {}

        def name(raw: str) -> tuple[str, str]:
            hit = cache.get(raw)
            if hit is None:
                spelled = resolve(raw)
                c = None
                if term_map and declared_category(spelled) is None:
                    c = term_map.get(spelled) or term_map.get(raw) \
                        or folded.get(normalize_term(spelled))
                    c = resolve(c) if c is not None else None
                hit = cache[raw] = (spelled, store_name(spelled, c))
            return hit
        return name

    def _scope_test(self):
        """`name -> bool`: is the term out of scope? Memoised for one view.

        Scope is the GATE's question (rule 40), asked live (rule 51): the store
        keeps no copy of the answer, so a curator's `in` or a pass's `out`
        reaches everything downstream the moment it is written. Until
        2026-09-28 the cleaner wrote the blocklist's answer into the store as
        rejections -- 2,330 terms and 6,436 relations, frozen as of 2026-09-20
        and deciding the same question as the gate's 10,531 `out` verdicts.
        """
        terms = self.terms
        test = lambda n: terms.effective_gate_verdict(n)[0] == "out"   # noqa: E731
        cache: dict[str, bool] = {}

        def out_of_scope(n: str) -> bool:
            hit = cache.get(n)
            if hit is None:
                # A BFO category is declared, never gated (rules 20, 22). The
                # scope pass of 2026-09-28 answered `out` for `process`,
                # `material entity` and the rest, and since every typing is an
                # `is_a: <category>` cell, that one answer emptied the store of
                # its categories.
                hit = cache[n] = (declared_category(n) is None and bool(test(n)))
            return hit
        return out_of_scope

    def out_of_scope(self, names) -> set[str]:
        """The names among `names` the gate puts out of scope."""
        test = self._scope_test()
        return {n for n in names if test(n)}

    def _cell_verdict(self, owners: tuple[str, ...], pred: str,
                      targets: tuple[str, ...]) -> dict | None:
        """The `no` that counts on this cell (rule 89), or None."""
        terms, r = self.terms, getattr(self, "reopen", None)
        reopen = r[0] if r and (r[1] == "is_a") == (pred == "is_a") else None
        for owner in owners:
            if owner not in terms.records:
                continue
            for t in targets:
                v = terms.cell_rejected(owner, f"{pred}: {t}", reopen=reopen)
                if v is not None:
                    return v
        return None

    def _cell_predicate(self, owners: tuple[str, ...], pred: str,
                        targets: tuple[str, ...]) -> str | None:
        """The predicate a decision gives this cell instead of the one written
        (rule 68: `has_disposition` with a tendency value reads as
        `has_tendency`), or None."""
        terms, r = self.terms, getattr(self, "reopen", None)
        reopen = r[0] if r and r[1] == "relations" else None
        for owner in owners:
            if owner not in terms.records:
                continue
            for t in targets:
                p = terms.cell_predicate(owner, pred, t, reopen=reopen)
                if p:
                    return p
        return None

    def view(self, *, mapped: bool = True, include_rejected: bool = False, on_refused=None, on_kept=None
             ) -> Iterator[tuple[str, dict[str, dict[str, float]]]]:
        """(key, {name: {triple: value}}) per record: the evidence, resolved.

        `mapped=False` stops at the spelling -- what the mapping BUILD wants,
        since it proposes merges between the terms as they are written.
        `include_rejected=True` keeps what a verdict rejects -- what a pass
        that re-asks about rejected terms wants. Two strings that resolve to
        one name in one abstract merge, the strongest evidence winning.
        `on_refused(key, name, predicate, target, owners, targets, value)` is
        told of every relation a judgement in the term dict leaves out, with
        the names its cells are read under -- what a count of why relations
        are left out wants (the figure from the abstracts to WONT); it changes
        nothing the view yields. `on_kept`, with the same arguments, is told of
        every relation it keeps: a judgement on any of those cells is one on the
        relation, so whoever asks whether a relation was read asks them all
        (2026-10-30: a reading filed under the spelling `Risk of infection`
        counted for the view and was missed by the figure, which read the cell
        of today's name `wound infecting tendency` alone).
        """
        name = self.resolver(mapped=mapped)
        # Terms split by category (rule 87): each mention takes the name for
        # the category its own abstract gave it, BEFORE the verdicts are read,
        # so the scope of `Biopsy material` decides about its mentions.
        splits = {_sense_key(t): s for t, s in self.terms.splits().items()}
        # Decided categories (rule 57), by the name the view shows and, when the
        # view stops at the spelling, by the name the term maps to as well: a
        # synonym names what its canonical names.
        r = getattr(self, "reopen", None)
        cats = {t.lower(): c["verdict"] for t, c in
                self.terms.categories(reopen=r[0] if r and r[1] == "is_a" else None).items()}
        via_map = self.resolver(mapped=True) if (cats and not mapped) else None

        def decided_for(final: str, raw: str) -> str | None:
            c = cats.get(final.lower())
            if c is None and via_map is not None:
                c = cats.get(via_map(raw)[1].lower())
            return c
        out_of_scope = self._scope_test()
        keep = getattr(self, "allowed_predicates", None)
        allowed = set(keep) if keep else None
        # An entity nothing affirms anywhere is not in the cleaned store -- the
        # whole store counts, so a denial in one abstract stays where the term
        # is asserted in another. Two passes, so the records are held.
        # Affirmed is what the abstract asserted, before any verdict: a refused
        # cell takes off that cell, never the mention -- a term leaves the
        # cleaned store only by its scope (curator, 2026-10-29: ELK's refusal of
        # `Allergy is_a disposition` had emptied Allergy from all 4 abstracts,
        # and 328 placed terms fell below the evidence cut with it).
        pending: list[tuple[str, dict, dict]] = []
        affirmed: set[str] = set()
        for key, rec in self.dict.items():
            if key == self.DECISIONS or not isinstance(rec, dict):
                continue
            out: dict[str, dict[str, float]] = {}
            decided: dict[str, str] = {}
            refused: list[tuple] = []
            kept_cells: list[tuple] = []
            ents = rec.get("entities", {})
            own, by_key = _senses_here(ents, name, splits) if splits else ({}, {})
            for raw, attrs in ents.items():
                if not isinstance(attrs, dict):
                    continue
                spelled, final = name(raw)
                owners = (spelled, final) if spelled != final else (final,)
                if raw in own:
                    final = name(own[raw])[1]
                    owners = tuple(dict.fromkeys(owners + (final,)))
                if not include_rejected and any(map(out_of_scope, owners)):
                    continue
                dest = out.setdefault(final, {})
                if any(float(v) > 0.0 for v in attrs.values()):
                    affirmed.add(final)
                if cats and final not in decided:
                    c = decided_for(final, raw)
                    if c:
                        decided[final] = c
                for triple, value in attrs.items():
                    if ":" in triple:
                        pred, tgt = triple.split(":", 1)
                        pred = pred.strip()
                        t_spelled, t_final = name(tgt.strip())
                        targets = ((t_spelled, t_final) if t_spelled != t_final
                                   else (t_final,))
                        sense = by_key.get(_sense_key(t_final)) if by_key else None
                        if sense:
                            t_final = name(sense)[1]
                            targets = tuple(dict.fromkeys(targets + (t_final,)))
                        # A cell read under another predicate (rule 68) is
                        # judged under that one: the written one says `no`.
                        pred = self._cell_predicate(owners, pred, targets) or pred
                        if not include_rejected and any(map(out_of_scope, targets)):
                            continue
                        if not include_rejected and self._cell_verdict(owners, pred, targets):
                            if on_refused is not None and (allowed is None or pred in allowed):
                                refused.append((final, pred, t_final, owners, targets, float(value)))
                            continue
                        if not include_rejected and allowed is not None and pred not in allowed:
                            continue             # a relation the schema does not allow
                        if on_kept is not None:
                            kept_cells.append((final, pred, t_final, owners, targets, float(value)))
                        triple = f"{pred}: {t_final}"
                    dest[triple] = max(dest.get(triple, 0.0), float(value))
            pending.append((key, out, decided, refused, kept_cells))
        for key, out, decided, refused, kept_cells in pending:
            for final, pred, t_final, owners, targets, value in refused:
                if final in affirmed:
                    on_refused(key, final, pred, t_final, owners, targets, value)
            for final, pred, t_final, owners, targets, value in kept_cells:
                if final in affirmed:
                    on_kept(key, final, pred, t_final, owners, targets, value)
            if not include_rejected:
                out = {e: a for e, a in out.items() if e in affirmed}
            if decided:
                out = _apply_categories(out, decided)
            yield key, out

    @property
    def cleaned(self) -> dict[str, dict[str, dict[str, float]]]:
        """The cleaned store: `{key: {name: {triple: value}}}`, recomputed on
        every read (curator, 2026-10-25: "ein view des concept store, der sich
        bei jedem nutzen neu berechnet. eine property eben").

        The evidence as extracted, read through TermMappingAndGate: names
        resolved by the mapping, terms and relation targets the gate puts out
        left out, rejected cells left out, relations the schema does not allow
        left out, and an entity nothing affirms left out. Nothing here is
        stored; to change it, write a decision to the term dict (rules 51, 86).
        """
        return dict(self.view())

    def records(self) -> Iterator[tuple[str, dict[str, dict[str, float]]]]:
        """(key, {entity: {triple: value}}) for every assertion record: the
        evidence resolved through the term dict, rejected entities and cells
        left out. Fresh on every call; write a decision to change it."""
        return self.view()

    def effective_dict(self) -> dict:
        """The view in the file's shape -- {key: {"entities": ..., "meta_stamp": ...}}."""
        return {key: {**{k: v for k, v in self.dict[key].items() if k != "entities"},
                      "entities": ents}
                for key, ents in self.records()}

    def assertions(self) -> Iterator[tuple[str, str, str, float]]:
        """(key, entity, triple, value) for every cell that stands."""
        for key, ents in self.records():
            for entity, attrs in ents.items():
                for triple, value in attrs.items():
                    yield key, entity, triple, value

    def trace(self, name: str) -> dict:
        """Where a name in the view comes from: the strings the abstracts wrote
        that resolve to it, each with its PMIDs and its spelling steps, and the
        mapping entry that sent it there if one did."""
        from wound_ontology.mappers.term_mapping_and_gate import target_of
        resolve = self.resolver(mapped=True)
        aliases = self.terms.aliases()
        splits = {_sense_key(t): s for t, s in self.terms.splits().items()}
        found: dict[str, set[str]] = {}
        for key, rec in self.dict.items():
            if key == self.DECISIONS or not isinstance(rec, dict):
                continue
            ents = rec.get("entities", {})
            own, by_key = _senses_here(ents, resolve, splits) if splits else ({}, {})
            for raw, attrs in ents.items():
                if not isinstance(attrs, dict):
                    continue
                final = resolve(own[raw])[1] if raw in own else resolve(raw)[1]
                if final == name:
                    found.setdefault(raw, set()).add(key)
                for t in attrs:
                    if ":" not in t:
                        continue
                    s = t.split(":", 1)[1].strip()
                    t_final = resolve(s)[1]
                    sense = by_key.get(_sense_key(t_final))
                    if (resolve(sense)[1] if sense else t_final) == name:
                        found.setdefault(s, set()).add(key)
        out = {}
        for raw, keys in sorted(found.items()):
            steps, s, seen = [], raw, set()
            while s in aliases and s not in seen:
                seen.add(s)
                steps.append({"from": s, **aliases[s]})
                s = aliases[s]["to"]
            spelled = resolve(raw)[0]
            entry = self.terms.records.get(spelled) or {}
            to = target_of(entry, spelled)
            out[raw] = {"documents": sorted(keys), "spelling": steps,
                        "mapped_by": ({"entry": spelled, "to": to,
                                       "by": self.terms.named_by(spelled),
                                       "pair": (entry.get("pairs") or {}).get(to)}
                                      if spelled != name and to else None)}
        return out

    # ── Verdicts: written to the term dict ────────────────────────────────────

    def decisions(self) -> dict:
        """A read-only picture of the decisions in the shape the store's own
        `decisions` record had until rule 51. They live in the term dict now;
        writing to this dict changes nothing."""
        return {"entity_verdicts": self.rejected_entities(),
                "cell_verdicts": self.rejected_cells(),
                "renamed": self.terms.aliases()}

    def rejected_entities(self) -> dict[str, dict]:
        """{entity -> verdict} for every entity out of scope: rule 89 keeps a
        term out by its scope, there is no other verdict on a whole entity."""
        out = {}
        for t, r in self.terms.records.items():
            j = current(r.get("scope"))
            if j and j["verdict"] == "out":
                out[t] = {"status": self.REJECTED, "by": j["by"], "note": j["why"], "when": j["when"]}
        return out

    def rejected_cells(self) -> dict[str, dict[str, dict]]:
        """{entity -> {triple -> verdict}} for every single cell whose judgement is `no`."""
        return self.terms.rejected_cells()

    def verdict(self, entity: str, triple: str | None = None) -> dict | None:
        """The verdict that applies to `entity` (its scope `out`) or to one of its
        cells (a `no`), or None if it stands as asserted."""
        if triple is None:
            return self.rejected_entities().get(self.terms.concept(self.terms.resolve(entity)))
        pred, _, tgt = triple.partition(":")
        return self._cell_verdict((entity,), pred.strip(), (tgt.strip(),))

    def reject_entities(self, names: Iterable[str], *, by: str, note: str = "") -> int:
        """Put each named entity out of scope (rule 89: the scope is the verdict
        on a whole entity). Returns how many of the names are in the view -- a
        name that is not is reported, not judged, because a verdict on nothing
        is a typo in a list."""
        names = set(names)
        present = set(self.entities_raw())
        missing = sorted(names - present)
        if missing:
            print(f"[ConceptStore] {len(missing)} name(s) rejected by {by!r} are not "
                  f"in the store and were skipped: {missing[:5]}")
        n = 0
        for name in sorted(names & present):
            self.terms.gate(name, curator={"verdict": "out", "by": by, "reason": note or "rejected"})
            n += 1
        if n:
            self.terms.save()
        return n

    def reject_cells(self, cells: Iterable[tuple[str, str]], *, by: str, note: str = "",
                     notes: dict | None = None) -> int:
        """Judge single (entity, triple) cells `no`, each with its own reason from
        `notes` (else `note`). Written only where `by`'s own last judgement on the
        cell differs. Returns how many cells were present."""
        wanted = set(cells)
        present = {(e, t) for _, ents in self.view(include_rejected=True)
                   for e, attrs in ents.items() for t in attrs if (e, t) in wanted}
        missing = sorted(wanted - present)
        if missing:
            print(f"[ConceptStore] {len(missing)} cell(s) rejected by {by!r} are not "
                  f"in the store and were skipped: {missing[:5]}")
        present = self._not_decided(present, by)
        for entity, triple in sorted(present):
            self.terms.judge_cell(entity, triple, "no", by=by,
                                  why=(notes or {}).get((entity, triple)) or note or "rejected")
        if present:
            self.terms.save()
        return len(present)

    def _not_decided(self, cells: set[tuple[str, str]], by: str) -> set[tuple[str, str]]:
        """`cells` without the ones the author decided: a machine's verdict would
        not count there (rule 89), and is not written; they are reported."""
        from wound_ontology.mappers.judgements import AUTHOR, rank
        held = set()
        for e, t in cells:
            cj = self.terms.cell(self.terms.resolve(e), t)
            if cj and rank(cj) == AUTHOR:
                held.add((e, t))
        if held:
            print(f"[ConceptStore] {len(held)} cell(s) NOT judged by {by!r}: the author "
                  f"decided each -- {sorted(held)[:5]}")
        return cells - held

    def repredicate_cells(self, cells: dict, *, by: str, note: str = "") -> int:
        """Read single (entity, triple) cells under another predicate:
        `cells` maps (entity, "pred: target") -> new predicate. The assertion
        stays in the store as written; the written predicate gets `no` and the
        new one `yes` in the term dict, and the view applies them. Returns how
        many cells were present."""
        present = {(e, t) for _, ents in self.view(include_rejected=True)
                   for e, attrs in ents.items() for t in attrs if (e, t) in cells}
        missing = sorted(set(cells) - present)
        if missing:
            print(f"[ConceptStore] {len(missing)} cell(s) repredicated by {by!r} are not "
                  f"in the store and were skipped: {missing[:5]}")
        present = self._not_decided(present, by)
        for entity, triple in sorted(present):
            self.terms.judge_cell(entity, triple, "no", by=by, why=note or "another predicate",
                                  new_predicate=cells[(entity, triple)])
        if present:
            self.terms.save()
        return len(present)

    def record_rename(self, old: str, new: str, *, by: str,
                      evidence: dict | None = None) -> None:
        """`old` is now written `new`: an alias in the term dict (rule 51)."""
        if self.terms.spell(old, new, by=by, evidence=evidence):
            self.terms.save()

    def summary(self) -> dict:
        """Counts for the three buckets, measured, not estimated."""
        asserted = sum(1 for _ in self.assertions())
        raw = sum(len(a) for k in self.document_keys()
                  for a in self.dict[k].get("entities", {}).values())
        from collections import Counter
        by: Counter = Counter()
        for v in self.rejected_entities().values():
            by[("entity", v.get("by"))] += 1
        for cells in self.rejected_cells().values():
            for v in cells.values():
                by[("cell", v.get("by"))] += 1
        return {"documents": len(self.document_keys()), "cells_raw": raw,
                "cells_standing": asserted, "cells_rejected": raw - asserted,
                "rejected_entities": len(self.rejected_entities()),
                "rejected_cells": sum(len(c) for c in self.rejected_cells().values()),
                "verdicts_by": {f"{lvl}:{who}": n for (lvl, who), n in sorted(by.items())},
                "renamed": len(self.terms.aliases())}

    # ── Derived views ─────────────────────────────────────────────────────────

    @property
    def attributes(self) -> list[str]:
        """Unique predicate:target strings across all standing entities."""
        all_attrs: set[str] = set()
        for _, ents in self.records():
            for attr_dict in ents.values():
                all_attrs.update(attr_dict.keys())
        return sorted([a for a in all_attrs if not a.startswith("meta_")])

    def top_attributes(self, n: int) -> list[str]:
        """Return the n most frequently occurring predicate:target strings (by entity count)."""
        from collections import Counter
        counts: Counter = Counter()
        for _, _, attr, val in self.assertions():
            if not attr.startswith("meta_") and val == 1.0:
                counts[attr] += 1
        return [attr for attr, _ in counts.most_common(n)]

    @property
    def predicates(self) -> list[str]:
        return [a.split(':', 1)[0].strip() if ':' in a else "" for a in self.attributes]

    @predicates.setter
    def predicates(self, keep: list[str]) -> None:
        """Reject every cell whose predicate is not in `keep`. Used to delete them."""
        keep_set = set(keep)
        doomed = [(e, t) for _, e, t, _ in self.assertions()
                  if ':' in t and t.split(':', 1)[0].strip() not in keep_set]
        n = self.reject_cells(doomed, by="predicate_filter",
                              note=f"predicate not in {sorted(keep_set)}")
        print(f"[ConceptStore] Predicates filtered — {len(keep_set)} allowed, "
              f"{n} cell(s) rejected.")

    @property
    def targets(self) -> list[str]:
        return [a.split(':', 1)[1].strip() if ':' in a else a for a in self.attributes]

    @targets.setter
    def targets(self, keep: list[str]) -> None:
        """Reject every cell whose target is not in `keep`. Used to delete them."""
        keep_set = set(keep)
        doomed = [(e, t) for _, e, t, _ in self.assertions()
                  if ':' in t and t.split(':', 1)[1].strip() not in keep_set]
        n = self.reject_cells(doomed, by="target_filter", note="target not kept")
        print(f"[ConceptStore] Targets filtered — {len(keep_set)} allowed, "
              f"{n} cell(s) rejected.")

    @property
    def entities(self) -> list[str]:
        """Unique standing entity names across the store."""
        all_entities: set[str] = set()
        for _, ents in self.records():
            all_entities.update(ents)
        return sorted(all_entities)

    def entities_raw(self) -> list[str]:
        """Every entity name in the view, rejected ones included."""
        names: set[str] = set()
        for _, ents in self.view(include_rejected=True):
            names.update(ents)
        return sorted(names)

    @entities.setter
    def entities(self, keep: list[str]) -> None:
        """Reject every standing entity not in `keep`. Used to delete them."""
        keep_set = set(keep)
        doomed = [e for e in self.entities if e not in keep_set]
        n = self.reject_entities(doomed, by="entity_filter", note="not kept")
        print(f"[ConceptStore] Entities filtered — {len(keep_set)} kept, "
              f"{n} rejected.")

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def get_data(
        self,
        source,
        child_col: str = "Class",
        parent_col: str = "Parent class",
    ) -> None:
        """
        Ingest data into the store.

        source : pd.DataFrame
            Predefined edges with ``child_col`` and ``parent_col`` columns.
            Each row is converted to an ``is_a`` triple and stored under the
            key ``"predefined"``.
        source : dict
            Raw concept dict in the internal ``{ pmid: { entities: {...} } }``
            format — merged directly into the store.

        Call this *before* normalize() so all names are covered by the same
        mapping pass as the LLM extractions.
        """
        # Ensure _dict is initialised before writing
        _ = self.dict

        if isinstance(source, pd.DataFrame):
            pairs = source[[child_col, parent_col]].dropna().drop_duplicates()
            entities_map: dict[str, dict] = {}
            for _, row in pairs.iterrows():
                child  = str(row[child_col]).strip()
                parent = str(row[parent_col]).strip()
                entities_map.setdefault(child, {})[f"is_a: {parent}"] = 1.0
            self._dict["predefined"] = {"entities": entities_map, "meta_stamp": "predefined"}
            self.save()
            print(f"[ConceptStore] {len(pairs)} predefined edges stored.")
        elif isinstance(source, dict):
            self._dict.update(source)
            self.save()
            print(f"[ConceptStore] {len(source)} entries merged from dict.")
        else:
            raise TypeError(f"source must be a DataFrame or dict, got {type(source).__name__}")

    def normalize(self, mapper=None) -> None:
        """Read the store through `mapper`'s mapping from now on.

        Nothing is rewritten (rule 51): the evidence stays as the abstracts
        wrote it and the view resolves every name through the mapping. What
        this used to do in place -- rename 6,029 abstracts, then title-case
        every name -- is what made a provenance book necessary, and the
        title-casing is superseded by pass 0, which elects one spelling per
        term and records it.

        A folded mapping key claimed by two canonicals is reported, as before:
        the first is used.
        """
        self._mapper = mapper
        term_map = self._mapping(True)
        folded: dict[str, str] = {}
        collisions: dict[str, set[str]] = {}
        for k, v in term_map.items():
            key = normalize_term(k)
            prev = folded.setdefault(key, v)
            if prev != v:
                collisions.setdefault(key, {prev}).add(v)
        if collisions:
            shown = "; ".join(f"{k!r}->{sorted(v)}" for k, v in
                              sorted(collisions.items())[:3])
            print(f"[ConceptStore] WARNING: {len(collisions)} normalised mapping "
                  f"key(s) claim more than one canonical; the first is used. {shown}")
        n = sum(len(e) for _, e in self.records())
        print(f"[ConceptStore] Mapping applied through the view — {n} entity records.")

    def apply_renames(self, renames: dict[str, str], *, by: str) -> dict:
        """Record that each string in `renames` is now written differently.

        The renames go to the term dict, where `apply_renames` moves every
        decision to the new spelling and leaves the old one as an alias; the
        evidence is not touched. Returns the term dict's report, plus how many
        names in the view the renames reached.
        """
        if not renames:
            # The same shape as a real report, so a caller that prints one
            # does not crash on a run with nothing to do (2026-09-28).
            return {**self.terms.apply_renames({}, by=by),
                    "renamed": 0, "entities": 0, "merged verdicts": 0}
        in_view = {n for _, ents in self.view(mapped=False, include_rejected=True)
                   for e, attrs in ents.items()
                   for n in [e, *(t.split(":", 1)[1].strip() for t in attrs if ":" in t)]}
        report = self.terms.apply_renames(renames, by=by)
        report.update({"renamed": len(in_view & set(renames)),
                       "entities": sum(len(e) for _, e in self.view(include_rejected=True)),
                       "merged verdicts": report.get("records merged", 0)})
        return report

    async def add_llm_extracts(
        self,
        df_pubmed,
        llm,
        allowed_predicates,
        batch_size: int = 10,
        extra_targets=None,
        predicate_definitions=None,
        max_consecutive_failures: int = 20,
        max_vocab_hints: int = 300,
        milestone_every: int = 0,
        on_milestone=None,
        schema_constrained: bool = True,
    ) -> None:
        """
        Extract entities from PubMed abstracts in parallel waves and store results.

        extra_targets            – additional target candidates (e.g. BFO anchor names) passed
                                   to the LLM alongside already-known targets.
                                   DEPRECATED free-text path only: the schema-constrained
                                   path sends the generated category tree instead and
                                   ignores this, saying so on stdout when it is supplied.
        max_consecutive_failures – circuit breaker: abort and raise if this many results in a
                                   row are permanent failures (all retries exhausted).
        max_vocab_hints          – cap on how many targets/attributes are sent per prompt.
                                   Uses the most frequent entries to keep prompt size bounded.
                                   DEPRECATED free-text path only; see extra_targets.
        milestone_every          – trigger on_milestone after every N new entity mentions.
                                   0 = disabled.
        on_milestone             – async callable(store) invoked at each milestone.
                                   Safe to call: _dict writes only happen in this loop,
                                   which is paused during the await.
        schema_constrained       – use the two-stage path driven by the MILD/WONT-derived
                                   schema (config/extraction_schema.yaml). Terms are typed
                                   to one BFO category, grounded by exact-label lookup
                                   rather than by the model emitting IRIs, and relations
                                   are filtered against the category pairs the ontologies
                                   license. Set False for the legacy single free-text
                                   prompt, which is kept only for comparison.
        """
        meta_col, meta_id = self.dm.get_meta_stamp("llm_extract")
        if schema_constrained:
            # The two-stage prompts carry the generated category tree (and, when
            # with_definitions is on, the grounding table). They never carry store
            # vocabulary, so computing hints here would be dead work and accepting
            # them silently would advertise an effect this path does not have.
            if extra_targets or allowed_predicates or predicate_definitions:
                print("[ConceptStore] schema_constrained=True: vocabulary hints are NOT "
                      "sent to the model - the generated schema is the vocabulary. "
                      "extra_targets, allowed_predicates, predicate_definitions and "
                      "max_vocab_hints apply to the deprecated free-text path only.")
            top_attrs, top_targets, combined_targets = [], [], []
        else:
            top_attrs = self.top_attributes(max_vocab_hints)
            top_targets = list({a.split(':', 1)[1].strip() for a in top_attrs if ':' in a})
            combined_targets = top_targets + (list(extra_targets) if extra_targets else [])
        current = self.dict

        # The abstract database is ROW-keyed: a paper found by three queries is
        # three rows differing only in `query`. The store is PMID-keyed. Queuing
        # rows therefore sent the same abstract to the model once per query that
        # found it -- measured 2026-09-11: 193 calls for 136 PMIDs on a 606-PMID
        # corpus, and 7,536 rows queued for 5,562 PMIDs on the cap-200 fetch,
        # a quarter of the run's cost buying nothing. Dedupe on PMID, first row
        # wins (the abstract text is identical across rows), and say how many
        # were folded so the row count and the call count stop looking alike.
        seen: set[str] = set()
        to_process = []
        duplicate_rows = 0
        for _, row in df_pubmed.iterrows():
            pmid = str(int(row['pmid']))
            if pmid in current:
                continue
            if pmid in seen:
                duplicate_rows += 1
                continue
            seen.add(pmid)
            to_process.append(row)

        if not to_process:
            # Two different situations, never one message: an empty abstract
            # table is not "everything already extracted" (2026-10-01: the
            # integration test read that line over an empty table).
            if df_pubmed is None or len(df_pubmed) == 0:
                print("[ConceptStore] Nothing to extract: the abstract table is EMPTY "
                      "(no PubMed search loaded or run).")
            else:
                print(f"All {len(seen) + duplicate_rows or len(df_pubmed)} abstract row(s) "
                      f"already in store.")
            return

        print(f"Parallel Extraction: {len(to_process)} new abstracts in waves of {batch_size}..."
              + (f" ({duplicate_rows} duplicate rows of the same PMIDs folded)"
                 if duplicate_rows else ""))
        sem = asyncio.Semaphore(batch_size)
        abort = asyncio.Event()
        llm.abort_event = abort
        llm._consec_errors = 0
        llm._max_consec_errors = max_consecutive_failures

        async def extract_one(row):
            if abort.is_set():
                return str(int(row['pmid'])), None
            async with sem:
                if abort.is_set():
                    return str(int(row['pmid'])), None
                pmid = str(int(row['pmid']))
                try:
                    if schema_constrained:
                        return pmid, await _extract_schema_constrained(
                            llm, row['abstract'], meta_id
                        )
                    # DEPRECATED path. The model picks relations off a free-text
                    # list and emits its own identifiers, so nothing is typed to
                    # a BFO category and nothing is checked against the pairs
                    # MILD/WONT license. Kept for comparison against the
                    # schema-constrained path, not for production runs.
                    warnings.warn(
                        "schema_constrained=False uses the legacy free-text "
                        "extraction prompt: terms are not typed to a BFO "
                        "category, grounding is a generated identifier rather "
                        "than a label lookup, and relations are not filtered "
                        "against the category pairs the ontologies license. "
                        "Kept only for comparison.",
                        DeprecationWarning, stacklevel=2,
                    )
                    extracted = await llm.extract_entities(
                        row['abstract'],
                        allowed_predicates,
                        combined_targets,
                        top_attrs,
                        predicate_definitions=predicate_definitions,
                    )

                    entities_map: dict[str, dict] = {}
                    for ent in extracted:
                        # The string as the extractor wrote it is what is
                        # stored (rule 51), every one: whether it belongs is a
                        # verdict in the term dict, never a filter here (rule 86).
                        raw_entity = ent.object.strip()
                        entity_name = ConceptStore.clean_entity_str(raw_entity)
                        if not entity_name:
                            continue
                        # Every relation as the model gave it (rule 86): a
                        # predicate the schema does not allow is left out by
                        # the view, never here. Until 2026-10-25 this path
                        # dropped such predicates and turned `part_of: X` to
                        # 0.0 wherever `is_a: X` stood too -- a rewrite of what
                        # the abstract said. A triple both affirmed and denied
                        # keeps the affirmation, as the view does (strongest
                        # evidence wins).
                        attr_logic: dict[str, float] = {}
                        for a in ent.true_attributes:
                            attr_logic[f"{a.predicate}: {a.target.strip()}"] = 1.0
                        for a in ent.false_attributes:
                            attr_logic.setdefault(f"{a.predicate}: {a.target.strip()}", 0.0)

                        entities_map[raw_entity] = attr_logic

                    return pmid, {"entities": entities_map, "meta_stamp": meta_id}

                except Exception as e:
                    print(f"Failed PMID {pmid}: {type(e).__name__}: {e}")
                    return pmid, None

        tasks = [asyncio.create_task(extract_one(row)) for row in to_process]
        # Names the store already holds are settled -- pass 0 decided how they
        # are written -- so ingestion's cleaning never re-spells one of them
        # (rule 51). Only strings new to the store get an ingestion spelling.
        settled = {n for _, ents in self.view(mapped=False, include_rejected=True)
                   for e, attrs in ents.items()
                   for n in [e, *(t.split(":", 1)[1].strip() for t in attrs if ":" in t)]}
        succeeded = 0
        entities_since_milestone = 0

        try:
            for f in asyncio.as_completed(tasks):
                pmid, result = await f
                if result:
                    self._dict[pmid] = result
                    self._spell_ingested(result, settled)
                    self.save()
                    print(f"Cached PMID {pmid}")
                    succeeded += 1
                    if milestone_every > 0 and on_milestone:
                        entities_since_milestone += len(result.get("entities", {}))
                        if entities_since_milestone >= milestone_every:
                            print(f"\n[ConceptStore] Milestone: ~{entities_since_milestone} new entities "
                                  f"({succeeded}/{len(to_process)} PMIDs). Running normalization...")
                            await on_milestone(self)
                            entities_since_milestone = 0
                            if schema_constrained:
                                # Nothing to refresh: this path sends no vocab hints.
                                print("[ConceptStore] Normalization applied. Resuming extraction.\n")
                            else:
                                # Refresh vocab hints so subsequent extractions use updated terms
                                top_attrs[:] = self.top_attributes(max_vocab_hints)
                                top_targets[:] = list({a.split(':', 1)[1].strip() for a in top_attrs if ':' in a})
                                combined_targets[:] = top_targets + (list(extra_targets) if extra_targets else [])
                                print("[ConceptStore] Vocab hints refreshed. Resuming extraction.\n")
                if abort.is_set():
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise RuntimeError(
                        f"[Circuit breaker] Aborted after {llm._consec_errors} consecutive failures. "
                        f"{succeeded}/{len(to_process)} abstracts saved."
                    )
        finally:
            llm.abort_event = None
            llm._max_consec_errors = 0

        print(f"Batch extraction complete. {succeeded}/{len(to_process)} abstracts processed.")

    @staticmethod
    def _category_phrase(category: str) -> str:
        """The category as it reads inside a class label: `Necrosis Material Entity`.

        The vocabulary is already lowercase-with-spaces, so the phrase IS the
        declared name and the caller's `smart_title` does the casing. This used
        to split CamelCase; a name arriving CamelCase now means the vocabulary
        regressed, so it is declared through, not welded silently.
        """
        return declared_category(category) or category

    def split_irreconcilable_terms(self, resolve_conflict) -> dict:
        """One label typed several irreconcilable ways is several classes.

        `Necrosis` arrived as `material entity` from one abstract and `process`
        from two others. That is not one class typed badly: necrosis genuinely is
        a pathological process, and a material entity, and arguably a disposition
        of tissue realised by trauma. Forcing one category loses a sense; forcing
        none — which is what the reconciler does when the typings share no
        ancestor — loses the term.

        So each mention is renamed to `<Term> <Category>` using the category THAT
        abstract gave it: `Necrosis Process`, `Necrosis Material Entity`. Every
        resulting term then carries exactly one category by construction, and the
        relations an abstract asserted stay attached to the sense it meant. The
        label says which superclass it belongs under, which is also how a reader
        tells the two apart.

        Only irreconcilable terms are split. A conflict with an honest common
        ancestor (`process` and `process boundary` agree on `occurrent`) is
        reconciled instead — there is one concept there, described at two
        granularities.

        The split is written as the term's `to`, one name per category, and
        each name gets a record of its own (rule 87). A person names the senses
        instead where the generated label reads badly (`Biopsy procedure`,
        `Biopsy material`). A term that maps onto another name is not split.

        Returns a report: {split: {term: {category: new_label}}, mentions: n,
        unsensed: {term: count}, mapped: {term: its name}}.
        """
        from wound_ontology.llm.extraction_models import COARSE_CATEGORIES
        from wound_ontology.utils.string_utils import smart_title

        typings: dict[str, set[str]] = {}
        for _, rec_entities in self.records():
            for entity, attrs in rec_entities.items():
                for triple, value in attrs.items():
                    if value != 1.0 or ":" not in triple or not _is_typing(triple):
                        continue
                    declared = declared_category(triple.split(":", 1)[1].strip())
                    if declared is not None:
                        typings.setdefault(_sense_key(entity), set()).add(declared)

        typings = {t: (c - COARSE_CATEGORIES) or c for t, c in typings.items()}

        splittable = {t: c for t, c in typings.items()
                      if len(c) > 1 and resolve_conflict(c) is None}
        report: dict = {"split": {}, "mentions": 0, "unsensed": {}}
        if not splittable:
            print("[ConceptStore] no irreconcilable terms to split.")
            return report

        for term, cats in splittable.items():
            report["split"][term] = {
                c: smart_title(f"{term} {self._category_phrase(c)}")
                for c in sorted(cats)
            }
        for _, ents in self.records():
            for entity, attrs in ents.items():
                key = _sense_key(entity)
                if key not in splittable:
                    continue
                if report["split"][key].get(_sense_of(attrs)):
                    report["mentions"] += 1
                else:
                    report["unsensed"][key] = report["unsensed"].get(key, 0) + 1

        # The split is a decision about the TERM, so it goes on its record as
        # where the term points, one name per category (rule 87); the view
        # renames each mention by the category its own abstract gave it
        # (rule 51). Nothing in the evidence is rewritten.
        from wound_ontology.mappers.term_mapping_and_gate import target_of
        for term, senses in list(report["split"].items()):
            spelled = self.terms.resolve(term)
            standing = target_of(self.terms.records.get(spelled) or {}, spelled)
            if standing:
                # mapped onto another name: that name is what the view shows
                report.setdefault("mapped", {})[term] = standing
                del report["split"][term]
                continue
            self.terms.split_by_category(term, senses, method="category-split")
        if report.get("mapped"):
            print(f"[ConceptStore] {len(report['mapped'])} irreconcilable term(s) NOT "
                  f"split: each maps onto another name -- "
                  f"{dict(sorted(report['mapped'].items())[:8])}")
        self.terms.save()
        print(f"[ConceptStore] split {len(report['split'])} irreconcilable term(s) "
              f"into {sum(len(v) for v in report['split'].values())} sense(s) "
              f"across {report['mentions']} mention(s).")
        for term, senses in sorted(report["split"].items()):
            print(f"[ConceptStore]     {term} -> {', '.join(sorted(senses.values()))}")
        if report["unsensed"]:
            print(f"[ConceptStore] {len(report['unsensed'])} term(s) were mentioned "
                  f"without a category in some abstract and left unsplit there: "
                  f"{dict(sorted(report['unsensed'].items())[:8])}")
        return report

    def merge_entity_records(self, entities: dict[str, dict[str, float]], *, kind: str) -> int:
        """Merge derived entity records into a synthetic store record.

        Everything downstream -- the hierarchies, the FCA view -- is rebuilt from
        this store, so anything that must survive a rebuild has to arrive here.
        This is the door for the things that are not extracted from an abstract:
        LLM verdicts on undecided cells ("llm_fill", "llm_fill_nan") and FCA
        edges a human promoted ("fca_promoted"). `kind` becomes the record key,
        so their provenance stays visible beside the PMIDs.

        This used to be a plain assignment, so a second fill replaced the first
        one's verdicts wholesale and said nothing. Merging keeps both. The one
        way a value can still be lost -- the same (entity, attribute) decided
        differently on two runs -- is counted and reported instead of happening
        quietly.

        Returns the number of verdicts written.
        """
        if not entities:
            return 0
        record = self._dict.get(kind) or {}
        existing = dict(record.get("entities", {}))
        written = changed = 0
        for entity, attrs in entities.items():
            dest = dict(existing.get(entity, {}))
            for triple, value in attrs.items():
                if triple in dest and dest[triple] != value:
                    changed += 1
                dest[triple] = value
                written += 1
            existing[entity] = dest

        _, meta_id = self.dm.get_meta_stamp(kind)
        self._dict[kind] = {"entities": existing, "meta_stamp": meta_id}
        self.save()
        if changed:
            print(f"[ConceptStore] {changed} verdict(s) overwrote an earlier and "
                  f"different verdict for the same attribute.")
        print(f"[ConceptStore] {written} verdict(s) merged into '{kind}' "
              f"across {len(existing)} entities. Stamp: {meta_id}")
        return written

    async def fill_missing_attributes(
        self,
        llm,
        batch_size: int = 20,
        entity_batch: int = 5,
        max_entities: int | None = None,
        max_attrs_per_entity: int = 80,
    ) -> None:
        """
        For each unique entity, evaluate attributes that are not yet in its record.

        After normalize(), the store may have entity X with some attributes from
        one PMID but missing others that exist for different entities.  This step
        asks the LLM to confirm/deny every unseen (pred: target) pair so the store
        is fully populated before ContextMatrix and FCA run.

        batch_size          – concurrent LLM calls in flight.
        entity_batch        – entities grouped into one LLM call (reduces total calls).
        max_entities        – cap how many entities are filled (None = all). Useful for testing.
        max_attrs_per_entity – cap attributes sent per entity to keep prompts within token limits.
        """
        all_attrs = self.attributes  # all known pred:target pairs across the store

        if not all_attrs:
            print("[ConceptStore] No attributes found — skipping fill.")
            return

        # Build flat merged view: entity → {attr: value} across all PMIDs
        flat: dict[str, dict[str, float]] = {}
        for _, ents in self.records():
            for entity, attrs in ents.items():
                merged = flat.setdefault(entity, {})
                for attr, val in attrs.items():
                    merged[attr] = max(merged.get(attr, 0.0), float(val))

        # Identify missing (never evaluated) attributes per entity, capped per entity
        entity_missing: dict[str, list[str]] = {}
        for entity, known_attrs in flat.items():
            missing = [a for a in all_attrs if a not in known_attrs]
            if missing:
                entity_missing[entity] = missing[:max_attrs_per_entity]

        # Optionally cap total entities processed
        if max_entities is not None:
            entity_missing = dict(list(entity_missing.items())[:max_entities])

        total_missing = sum(len(m) for m in entity_missing.values())
        if total_missing == 0:
            print("[ConceptStore] All entity–attribute pairs already evaluated.")
            return

        print(f"[ConceptStore] Filling {total_missing} missing pairs across "
              f"{len(entity_missing)} entities "
              f"(batch={entity_batch}, concurrency={batch_size})...")

        chunks = [
            dict(list(entity_missing.items())[i:i + entity_batch])
            for i in range(0, len(entity_missing), entity_batch)
        ]
        sem = asyncio.Semaphore(batch_size)

        async def process_chunk(chunk: dict[str, list[str]], chunk_id: int):
            async with sem:
                try:
                    result = await llm.fill_nan_batch(chunk)
                    print(f"  Chunk {chunk_id + 1}/{len(chunks)} done ({len(chunk)} entities).")
                    return result
                except Exception as e:
                    print(f"  Chunk {chunk_id + 1}/{len(chunks)} failed ({type(e).__name__}) — skipping.")
                    return {}

        tasks = [process_chunk(chunk, i) for i, chunk in enumerate(chunks)]
        batch_results = await asyncio.gather(*tasks)

        # Three-way write-back: confirmed → 1.0, explicitly denied → 0.0, and
        # anything the model did not rule on is simply NOT written, so it stays
        # unevaluated rather than being recorded as a definite "does not hold".
        # We add a synthetic "fill" key so provenance is clear.
        fill_entities: dict[str, dict] = {}
        n_conf = n_deny = 0
        for batch in batch_results:
            if not batch:
                continue
            for entity, verdict in batch.items():
                if entity not in entity_missing:
                    continue
                asked = set(entity_missing[entity])
                confirmed = asked & set(verdict.get("confirmed", ()))
                denied    = asked & set(verdict.get("denied", ())) - confirmed
                if not confirmed and not denied:
                    continue
                attr_dict = fill_entities.setdefault(entity, {})
                for attr in confirmed:
                    attr_dict[attr] = 1.0
                    n_conf += 1
                for attr in denied:
                    attr_dict[attr] = 0.0
                    n_deny += 1
        print(f"[ConceptStore] verdicts: {n_conf} confirmed, {n_deny} denied, "
              f"{total_missing - n_conf - n_deny} left unevaluated.")

        if fill_entities:
            self.merge_entity_records(fill_entities, kind="llm_fill")
            confirmed_total = sum(
                sum(1 for v in d.values() if v == 1.0) for d in fill_entities.values()
            )
            # The stamp is printed by merge_entity_records, which owns it now.
            print(f"[ConceptStore] Fill complete — {confirmed_total} new confirmed attributes.")

    def _spell_ingested(self, payload: dict, settled: set[str]) -> int:
        """Record ingestion's cleaning of each NEW string as its spelling.

        The evidence keeps `Diabetic Foot Ulcers (DFUs)` as written; the term
        dict records that it reads `Diabetic Foot Ulcer`, by `ingestion`. A
        string the store already holds is left to pass 0, and so is one that
        carries a decision of its own (an ontology label, a mapping key):
        aliasing either would re-spell it in every abstract, not just this one.
        """
        from wound_ontology.mappers.term_mapping_and_gate import DECISION_SECTIONS
        n = 0
        for raw, attrs in payload.get("entities", {}).items():
            for string in [raw, *(t.split(":", 1)[1].strip() for t in attrs if ":" in t)]:
                if string in settled or self.terms.is_alias(string):
                    continue
                settled.add(string)
                rec = self.terms.records.get(string) or {}
                if rec.get("name") or any(rec.get(k) for k in DECISION_SECTIONS):
                    continue
                clean = self.clean_entity_str(string)
                if clean != string and self.terms.resolve(clean) != string:
                    n += self.terms.spell(string, clean, by="ingestion")
        if n:
            self.terms.save()
        return n

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        if self._dict:
            self.dm.save_as_json(self._dict, self.file_name)
        else:
            print("Save skipped: Store is empty.")

async def _extract_schema_constrained(llm, text, meta_id):
    """One abstract through the MILD/WONT-derived schema.

    Returns the same {"entities": ..., "meta_stamp": ...} payload the legacy path
    produces, so the store, FCA matrix and hierarchies are unaffected. What is
    different is upstream: the model made one categorical choice per term instead
    of picking relations off a 7-item free-text list, grounding was a lookup
    rather than a generated identifier, and every relation was checked against
    the category pairs MILD/WONT actually license.
    """
    from wound_ontology.llm import extraction_adapter as _ad

    result, report = await llm.extract_two_stage(text)
    entities_map = {}
    for label, attrs in _ad.result_to_store_entities(result).items():
        name = ConceptStore.clean_entity_str(label.strip())
        if not name:
            continue                 # every string is stored; scope is a verdict (rule 86)
        # As extracted (rule 51): the cleaned name is recorded as the string's
        # spelling by `_spell_ingested`, never written over it.
        cleaned = {}
        for triple, value in attrs.items():
            pred, target = triple.split(":", 1)
            cleaned[f"{pred.strip()}: {target.strip()}"] = value
        entities_map[label.strip()] = cleaned

    payload = {"entities": entities_map, "meta_stamp": meta_id}
    if any(report.get(k) for k in ("rejected_terms", "rejected_relations",
                                   "unknown_predicates")):
        payload["schema_report"] = report
    return payload
