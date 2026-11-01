"""Every decision about every extracted string (rule 89, 2026-10-28).

One record per string, five questions, one form for every judgement::

    "<string>": {
      "name":      [<judgement>, ...],                  # under which name is it kept?
      "pairs":     {"<candidate>": [<judgement>, ...]}, # same_class | different | narrower | broader
      "scope":     [<judgement>, ...],                  # in | out
      "is_a":      {"<target>": [<judgement>, ...]},    # yes | no
      "relations": {"<predicate>: <target>": [<judgement>, ...]}}  # yes | no

    <judgement> = {"verdict", "by", "why", "when"} (+ "iri" on an ontology class)

`by` is an agent id from `judgements.AGENTS`, written once into the file.
Which judgement counts: the author's last; without one, the last of any agent
(`judgements.current`). A rule is a machine. Nothing is deleted, except that an
agent keeps at most `CAP` judgements per question.

A string whose name points elsewhere carries only `name` and `pairs`; scope,
is_a and relations are answered on its name, the concept. Whether a name is
another spelling or another concept's name is told by its agent: normalisation
and the spelling rules rewrite the string (`resolve`, `aliases`); the models,
the author and the programs that pick a name map it (`data`).

The record before rule 89 (`to`, `pass1`, `pass2`, `curator`, `gate`,
`spelling`, `retired`, the histories) is read by `rule89_old_format` and
translated by `rule89_migration`; `scripts/migrate_rule89.py` writes the file
with every judgement dated. This class reads an old file only to translate it,
and says so.
"""
from __future__ import annotations

import datetime as _dt
import re as _re
from collections.abc import MutableMapping

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.mappers.judgements import (ABSTAIN, AGENTS, AUTHOR, RUN, current, is_when,
                                               make, ordered, rank)

KEY_SEP = "\x1f"
SUBSUMPTION_VERDICTS = ("narrower", "broader")
GATE_VERDICTS = ("in", "out")
GATE_SOURCES = ("curator", "pass2", "pass1", "rule")
PAIR_VERDICTS = ("same_class", "narrower", "broader", "different")
APART = ("narrower", "broader", "different")
PAIR_SOURCES = ("pass1", "pass2", "check", "curator")
#: Each question's own answers; every agent answers in them (curator,
#: 2026-10-30: "halt dich einfach an die regeln"). An abstention is allowed on any.
ANSWERS = {"pairs": PAIR_VERDICTS, "scope": GATE_VERDICTS, "is_a": ("yes", "no"), "relations": ("yes", "no")}
SPELLING = "spelling"
DECISION_SECTIONS = ("pairs", "scope", "is_a", "relations")
IS_A = "is_a"
DECIDED = "decided"
TERM_RULING = "term ruling"

#: The file's own mark of its form. Not the keys `terms` and `agents`: the
#: abstracts wrote both words, and the old file holds a record for each.
FORMAT = "rule 89"

#: The most judgements one agent keeps on one question (curator, 2026-10-28:
#: "maximal 5 Urteile von einem Beurteiler").
CAP = 5

#: The agents whose name only rewrites the string -- a spelling. Any other
#: agent's name chooses the name of another concept -- a mapping: the models,
#: the author, and the programs that pick a name (chain resolution, the
#: ontology label). The final name is the same either way; the split is what
#: the mapping steps (`data`) see and what the view resolves first (`resolve`).
SPELLING_AGENTS = frozenset({"string-normalisation", "abbreviation-full-form", "no-trauma-to-injury",
                             "hyphen-modifier-not-grade", "latin-keeps-final-s", "proper-names-kept",
                             "action-potential-kept"})
_MODELS = frozenset(a for a in AGENTS if a.startswith(("deepseek", "claude", "sapbert")))


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _when(raw) -> str:
    if is_when(raw):
        return raw
    m = _re.match(r"(\d{4}-\d\d-\d\d)", str(raw or ""))
    return m.group(1) if m else _now()


_AUTHOR_MARKS = ("curator", "placement review", "judgement queue", "review page", "rulings page",
                 "words page", "contradiction queue", "chat", "author")


def agent_of(by, default: str = "author") -> str:
    """The agent id for a `by` as callers wrote it before rule 89. Unknown raises."""
    from wound_ontology.mappers.rule89_migration import curator_agent
    if by in AGENTS:
        return by
    if by in (None, ""):
        return default
    b = str(by).lower()
    if b.startswith("pass0"):
        return "string-normalisation"
    a = curator_agent(by)
    if a != "author" or any(m in b for m in _AUTHOR_MARKS):
        return a
    raise ValueError(f"no agent for by={by!r}: name it in judgements.AGENTS (rule 89)")


def target_of(rec: dict, term: str | None = None) -> str | None:
    """The one name the record's current name judgement gives, or None."""
    j = current((rec or {}).get("name"))
    v = j and j["verdict"]
    return v if isinstance(v, str) and v != term else None


def split_of(rec: dict) -> dict[str, str]:
    """`{category: name}` when the current name judgement splits the term (rule 87)."""
    j = current((rec or {}).get("name"))
    return dict(j["verdict"]) if j and isinstance(j["verdict"], dict) else {}


def edge_judgements(js: list[dict] | None) -> list[dict]:
    """An is_a list as it bears on the edge itself: without the refusals of a
    placement. A `no` that names an ontology class (an IRI) refused putting the
    term directly under that class -- the model offered a better one, or none
    near enough -- and says nothing against the term being one; `Antibiotic
    efficacy` refused under PATO `quality` is still typed a quality."""
    return [j for j in js or () if not (j["verdict"] == "no" and j.get("iri"))]


def _lists(rec: dict):
    for q, v in rec.items():
        if isinstance(v, list):
            yield v
        elif isinstance(v, dict):
            yield from v.values()


def _old_shape(j: dict | None) -> dict | None:
    """A judgement as the callers of the pre-rule-89 `peek` read it."""
    if j is None:
        return None
    out = {"verdict": j["verdict"], "reason": j["why"], "by": j["by"], "when": j["when"]}
    if j.get("iri"):
        out["iri"] = j["iri"]
    return out


# ── The one rule over strings nobody has judged (rule 86) ───────────────────
_UNIT_RE = _re.compile(
    r'(?:'
    r'\b\d+(?:[.,]\d+)?[-\s]*'
    r'(?:h|hr|hrs|hour|hours|min|mins|minute|minutes|sec|secs|second|seconds|day|days'
    r'|wk|wks|week|weeks|mo|mos|month|months|yr|yrs|year|years|kg|g|mg|mcg|µg|ug'
    r'|l|dl|ml|cc|cl|µl|ul|mmhg|cmh2o|mmol|mol|meq|iu|miu|item|items|session|sessions)\b'
    r'|\b\d+(?:[.,]\d+)?[-\s]+d\b'      # a bare `d` only when separated: `grade 1D` is not a day
    r'|\b\d+(?:[.,]\d+)?\s*%'
    r')', _re.IGNORECASE)


def noise_rule(term: str) -> bool:
    """True if `term` has no letter at all or contains a number with a unit."""
    if not bool(_re.search(r'[a-zA-Z]', term)):
        return True
    return bool(_UNIT_RE.search(term))


class _Undated:
    """Dating for an old file translated in memory: nothing is looked up."""
    def when(self, kind, *key, default_after=None):
        return _dt.date.today().isoformat(), "time not recorded; translated in memory"


class _PassCache(MutableMapping):
    """One model run's synonym judgements as the adjudicator's `dict[key] -> {verdict, reason}`."""

    def __init__(self, owner: "TermMappingAndGate", name: str, *, read: bool = True) -> None:
        self._owner, self._name, self._read = owner, name, read

    def __getitem__(self, key: str) -> dict:
        if not self._read:
            raise KeyError(key)
        term, _, canonical = key.partition(KEY_SEP)
        hit = self._owner.peek(term, canonical).get(self._name)
        if hit is None:
            raise KeyError(key)
        return hit

    def __setitem__(self, key: str, value: dict) -> None:
        term, _, canonical = key.partition(KEY_SEP)
        self._owner.judge(term, canonical, **{self._name: value})

    def __delitem__(self, key: str) -> None:
        raise TypeError("a judgement is never removed (rule 89)")

    def __iter__(self):
        return iter(self._owner.verdicts(self._name) if self._read else ())

    def __len__(self) -> int:
        return len(self._owner.verdicts(self._name)) if self._read else 0


def heard(js: list[dict] | None, reopen: str | frozenset[str] | None) -> list[dict] | None:
    """`js` without the judgements of the agent `reopen` sets aside, or of each
    agent in it: one agent re-hears what it refused (the reasoner's re-check,
    the typing check's rerun); several show the evidence before their checks
    (the figure of the relations from the abstracts to WONT)."""
    if not reopen or not js:
        return js
    aside = {reopen} if isinstance(reopen, str) else set(reopen)
    return [j for j in js if j["by"] not in aside]


class TermMappingAndGate:
    """Persistence of the term dict (rule 89). DataManager is its only I/O."""

    def __init__(self, dm: DataManager, file_name: str = "term_mapping") -> None:
        self._dm = dm
        self._file_name = file_name
        self._records: dict[str, dict] = self._load(dm.load_latest_json(file_name) or {})
        self._dirty()

    # ── Loading ───────────────────────────────────────────────────────────────

    @staticmethod
    def _load(raw: dict) -> dict[str, dict]:
        if not raw:
            return {}
        if raw.get("format") == FORMAT:
            terms = raw["terms"]
            unknown = {j["by"] for r in terms.values() for js in _lists(r) for j in js} - set(AGENTS)
            if unknown:
                raise ValueError(f"[mapping] judgements by unknown agents {sorted(unknown)[:5]}: "
                                 f"add them to judgements.AGENTS")
            off = [(t, q, j["verdict"], j["by"]) for t, r in terms.items() for q, v in r.items() if q in ANSWERS
                   for js in (v.values() if isinstance(v, dict) else [v]) for j in js
                   if j["verdict"] not in ANSWERS[q] and j["verdict"] != ABSTAIN]
            if off:
                raise ValueError(f"[mapping] {len(off)} judgement(s) outside their question's answers, e.g. "
                                 f"{off[:3]}: translate them (scripts/map_off_set_verdicts_2026_10_30.py)")
            return terms
        from wound_ontology.mappers.rule89_migration import migrate
        from wound_ontology.mappers.rule89_old_format import old_records
        new, rep, _ = migrate(old_records(raw), _Undated())
        print(f"[mapping] an old term dict ({len(raw):,} entries) was translated in memory to rule 89; "
              f"{sum(v for k, v in rep.items() if k.startswith('when reconstructed')):,} judgement(s) "
              f"undated -- run scripts/migrate_rule89.py to write it with dated judgements")
        return new

    # ── Writing one judgement ───────────────────────────────────────────────────

    def _put(self, term: str, question: str, j: dict, key: str | None = None, *,
             dated: bool = False) -> None:
        """Add `j` to its list. A judgement made now is the latest and goes last;
        one `dated` by its caller (a decision recorded with the time it was
        given) is put in time order. Sorting a judgement made now would put it
        before a same-day entry that carries a date only (`judgements.ordered`)."""
        if question in ANSWERS and j["verdict"] not in ANSWERS[question] and j["verdict"] != ABSTAIN:
            raise ValueError(f"{term!r} {question} {key!r}: {j['by']} answered {j['verdict']!r}, "
                             f"not one of {ANSWERS[question]}")
        rec = self._records.setdefault(term, {})
        lst = rec.setdefault(question, {}).setdefault(key, []) if key is not None else \
            rec.setdefault(question, [])
        lst.append(j)
        lst[:] = self._capped(ordered(lst) if dated else lst)
        self._dirty()
        if question == "name":
            self._carry_to_concept(term)

    @staticmethod
    def _capped(lst: list[dict]) -> list[dict]:
        """`lst` with at most `CAP` judgements per agent, each agent's oldest dropped first."""
        seen: dict[str, int] = {}
        keep = []
        for j in reversed(lst):
            seen[j["by"]] = seen.get(j["by"], 0) + 1
            if seen[j["by"]] <= CAP:
                keep.append(j)
        return keep[::-1]

    def _carry_to_concept(self, term: str) -> None:
        """A string named after another concept hands its scope, is_a and
        relations to that concept, where they are answered (rule 89). Nothing is
        dropped: the lists are joined in time order, the string's first on a tie."""
        rec = self._records.get(term) or {}
        held = [q for q in ("scope", "is_a", "relations") if rec.get(q)]
        if not held:
            return
        c = self.concept(term)
        if c == term:
            return
        dest = self._records.setdefault(c, {})
        for q in held:
            v = rec.pop(q)
            if isinstance(v, list):
                dest[q] = self._capped(ordered(v + dest.get(q, [])))
            else:
                d = dest.setdefault(q, {})
                for k, js in v.items():
                    d[k] = self._capped(ordered(js + d.get(k, [])))
        self._dirty()

    @staticmethod
    def _j(verdict, by: str, why: str, when=None, iri=None) -> dict:
        return make(verdict, by, why or "no reason given", _when(when) if when else _now(), iri)

    # ── The records ─────────────────────────────────────────────────────────

    @property
    def records(self) -> dict[str, dict]:
        return self._records

    def record(self, term: str) -> dict:
        """The record of `term`'s current spelling, created empty."""
        return self._records.setdefault(self.resolve(term), {})

    # ── Names: spelling and synonym (one question, the agent tells which) ──────

    def _name_j(self, term: str) -> dict | None:
        return current((self._records.get(term) or {}).get("name"))

    def _target(self, term: str) -> str | None:
        return target_of(self._records.get(term) or {}, term)

    def named_by(self, term: str) -> str | None:
        """The agent of the name judgement that counts on `term`, or None."""
        j = self._name_j(term)
        return j["by"] if j else None

    def is_alias(self, term: str) -> bool:
        """True when `term` is now written differently (a spelling, not a mapping)."""
        j = self._name_j(term)
        return bool(j and j["by"] in SPELLING_AGENTS and self._target(term))

    def aliases(self) -> dict[str, dict]:
        out = {}
        for t in self._records:
            if self.is_alias(t):
                j = self._name_j(t)
                out[t] = {"to": j["verdict"], "by": j["by"], "when": j["when"]}
        return out

    def resolve(self, term: str) -> str:
        """The spelling `term` is written as now: the fixed steps followed to the end."""
        seen: set[str] = set()
        while self.is_alias(term):
            if term in seen:
                raise RuntimeError(f"spelling cycle through {sorted(seen)[:5]}")
            seen.add(term)
            term = self._target(term)
        return term

    @property
    def data(self) -> dict[str, str]:
        """`term -> name` where the name is another concept's, not a respelling."""
        if self._flat is None:
            out = {}
            for t, r in self._records.items():
                j = current(r.get("name"))
                if j and j["by"] not in SPELLING_AGENTS and isinstance(j["verdict"], str) and j["verdict"] != t:
                    out[t] = j["verdict"]
            self._flat = out
        return self._flat

    @property
    def metadata(self) -> dict[str, dict]:
        return {t: {"standard": s, "confidence": 1.0, "method": self._name_j(t)["by"]}
                for t, s in self.data.items()}

    def splits(self) -> dict[str, dict[str, str]]:
        return {t: split_of(r) for t, r in self._records.items() if split_of(r)}

    @property
    def standards(self) -> list[str]:
        return sorted(set(self.data.values()))

    @property
    def originals(self) -> list[str]:
        return sorted(self.data.keys())

    def get(self, term: str) -> str:
        return self.data.get(term, term)

    def __contains__(self, term: str) -> bool:
        return term in self.data

    def __len__(self) -> int:
        return len(self.data)

    def _head(self, term: str) -> str:
        """Where `term` ends: every name followed. A split term is its own end."""
        seen = set()
        while (t := self._target(term)) and term not in seen:
            seen.add(term)
            term = t
        return term

    def concept(self, term: str) -> str:
        """The record that answers scope, is_a and relations for `term`."""
        return self._head(term)

    def spell(self, old: str, new: str, *, by: str, evidence: dict | None = None,
              when: str | None = None) -> bool:
        """Record that `old` is now written `new`. Returns whether anything changed."""
        from wound_ontology.mappers.rule89_migration import spelling_agent, spelling_why
        if old == new:
            return False
        if self.resolve(new) == old:
            raise ValueError(f"spelling {old!r} -> {new!r} would close a cycle")
        held = [q for q in DECISION_SECTIONS if (self._records.get(old) or {}).get(q)]
        nj = self._name_j(old)
        if nj and nj["by"] not in SPELLING_AGENTS and self._target(old):
            held.append(f"name {nj['verdict']!r} by {nj['by']}")
        if held:
            raise ValueError(f"{old!r} still carries {held}; move them with apply_renames, not spell")
        if self._target(old) == new:
            return False
        a = by if by in AGENTS else spelling_agent(by)
        if a == "unrecorded":
            a = agent_of(by)
        why = spelling_why(old, new) if a == "string-normalisation" else str(by)
        if evidence:
            why = f"{why}; evidence: {evidence}"
        self._put(old, "name", self._j(new, a, why, when), dated=bool(when))
        return True

    def split_by_category(self, term: str, names: dict[str, str], *, method: str = "curator") -> None:
        from wound_ontology.llm.category_vocab import declared_category
        term = self.resolve(term)
        clean: dict[str, str] = {}
        for cat, name in names.items():
            c = declared_category(cat)
            if c is None:
                raise ValueError(f"{term!r}: {cat!r} is not a BFO category")
            name = self.resolve(name)
            if name == term:
                raise ValueError(f"{term!r}: the {c} sense needs a name of its own")
            clean[c] = name
        if len(clean) < 2:
            raise ValueError(f"{term!r}: a split names at least two categories, got {clean}")
        if self._target(term):
            raise ValueError(f"{term!r} maps onto {self._target(term)!r}; refuse that first")
        self._put(term, "name", self._j(clean, agent_of(method), "split by category (rule 87)"))
        for name in clean.values():
            self._records.setdefault(name, {})

    def add(self, term: str, standard: str, confidence: float = 1.0, method: str = "manual",
            *, override: bool = False) -> None:
        """Name `term` by `standard` and save. A pair the author keeps apart raises."""
        term = self.resolve(term)
        if split_of(self._records.get(term) or {}) and not override:
            raise ValueError(f"{term!r} is split by category (rule 87); pass override=True")
        refusal = self.is_refused(term, standard)
        if refusal and not override:
            raise ValueError(f"{term!r} -> {standard!r} stands refused: {refusal}. Pass override=True to reverse it.")
        if refusal:
            self._put(term, "pairs", self._j("same_class", "author", "the refusal reversed"), standard)
        self._put(term, "name", self._j(standard, self._method_agent(method),
                                        f"method {method}; confidence {confidence}"))
        self.save()

    @staticmethod
    def _method_agent(method: str) -> str:
        from wound_ontology.mappers.rule89_migration import METHOD_AGENT
        if method in AGENTS:
            return method
        if method in METHOD_AGENT:
            return METHOD_AGENT[method]
        raise ValueError(f"no agent for method {method!r}: name it in judgements.AGENTS (rule 89)")

    def add_batch(self, entries: dict[str, str], metadata_batch: dict[str, dict] | None = None
                  ) -> list[tuple[str, str]]:
        """Name many terms; returns the pairs skipped because refused or split."""
        meta = metadata_batch or {}
        skipped = []
        for term, standard in entries.items():
            if self.is_refused(term, standard) or split_of(self._records.get(term) or {}):
                skipped.append((term, standard))
                continue
            m = meta.get(term) or {}
            method = m.get("method", "manual")
            self._put(term, "name", self._j(standard, self._method_agent(method),
                                            f"method {method}; confidence {m.get('confidence', 1.0)}"))
        self.save()
        return skipped

    def annotate(self, term: str, **fields) -> None:
        raise TypeError("rule 89: a record holds judgements only; write one with judge, gate or add")

    def retire(self, *terms: str, reason: str = "") -> int:
        """Un-name `terms` (the name judgement goes back to the term itself); saves."""
        from wound_ontology.mappers.rule89_migration import retired_agent
        a = retired_agent(reason)
        if a == "unrecorded":
            r = reason.lower()
            a = "category-guard" if "category guard" in r else "mapping-cleanup"
        n, kept = 0, []
        for t in terms:
            tgt = self._target(t)
            if not tgt or split_of(self._records.get(t) or {}):
                continue
            if (cj := current(((self._records.get(t) or {}).get("pairs") or {}).get(tgt))) \
                    and rank(cj) == AUTHOR and cj["verdict"] == "same_class":
                kept.append((t, tgt))
                continue
            self._put(t, "name", self._j(t, a, f"mapping retired: {reason}"))
            n += 1
        if kept:
            print(f"[mapping] {len(kept)} mapping(s) NOT retired ({reason!r}): the author called "
                  f"each pair same_class -- " + ", ".join(f"{t!r} -> {c!r}" for t, c in kept[:5]))
        if n:
            self.save()
        return n

    def forget(self, *terms: str) -> int:
        """Delete records outright: for tests and hand repair only."""
        before = len(self._records)
        for t in terms:
            self._records.pop(t, None)
        gone = before - len(self._records)
        if gone:
            self._dirty()
            self.save()
        return gone

    # ── Pairs ───────────────────────────────────────────────────────────────────

    def peek(self, term: str, canonical: str) -> dict:
        """What stands on one pair, in the slots the callers of old read:
        `pass1`/`pass2`/`check` (the model runs), `curator` (the last word of
        the author, a rule or a program). A placement reads as `curator: narrower`."""
        rec = self._records.get(term) or {}
        js = (rec.get("pairs") or {}).get(canonical) or []
        slot_of = {v: k for k, v in RUN.items()}
        out: dict = {}
        for j in js:
            if j["by"] in slot_of:
                out[slot_of[j["by"]]] = _old_shape(j)
        decisive = [j for j in js if j["by"] not in _MODELS and j["verdict"] != ABSTAIN]
        if decisive:
            out["curator"] = _old_shape(decisive[-1])
        isa = current((rec.get("is_a") or {}).get(canonical))
        if isa and isa["verdict"] == "yes" and isa.get("iri") and rank(isa) == AUTHOR:
            out["curator"] = {**_old_shape(isa), "verdict": "narrower"}
        return out

    def is_refused(self, term: str, canonical: str) -> dict | None:
        """The author's verdict that keeps this pair apart, if there is one."""
        rec = self._records.get(term) or {}
        cj = current((rec.get("pairs") or {}).get(canonical))
        if cj and rank(cj) == AUTHOR and cj["verdict"] in APART:
            return _old_shape(cj)
        isa = current((rec.get("is_a") or {}).get(canonical))
        if isa and rank(isa) == AUTHOR and isa["verdict"] == "yes" and isa.get("iri"):
            return {**_old_shape(isa), "verdict": "narrower"}
        return None

    def judge(self, term: str, canonical: str, **fields) -> None:
        """A judgement on one pair: `pass1=`, `pass2=`, `check=`, `curator=`. Does not save."""
        for slot, v in fields.items():
            if slot not in PAIR_SOURCES:
                raise ValueError(f"{slot!r} is not one of {PAIR_SOURCES}")
            verdict = v.get("verdict")
            if verdict not in PAIR_VERDICTS:
                raise ValueError(f"{term!r} -> {canonical!r} {slot}: verdict {verdict!r} is not one of {PAIR_VERDICTS}")
            by = RUN[slot] if slot in RUN else agent_of(v.get("by"))
            j = self._j(verdict, by, v.get("reason", ""), v.get("when"), v.get("iri"))
            dated = bool(v.get("when"))
            if slot == "curator" and v.get("iri") and verdict == "narrower":
                self._put(term, "is_a", {**j, "verdict": "yes"}, canonical, dated=dated)
            else:
                self._put(term, "pairs", j, canonical, dated=dated)

    def refuse(self, term: str, canonical: str, reason: str = "", by: str = "curator",
               *, verdict: str = "different") -> None:
        """`term` is NOT `canonical`; un-names it if it pointed there. Saves."""
        if verdict not in APART:
            raise ValueError(f"a refusal is one of {APART}, not {verdict!r}")
        a = agent_of(by)
        self._put(term, "pairs", self._j(verdict, a, reason or "refused"), canonical)
        if self._target(term) == canonical:
            self._put(term, "name", self._j(term, a, f"refused: {reason}"))
        isa = current(((self._records.get(term) or {}).get("is_a") or {}).get(canonical))
        if verdict == "different" and isa and isa["verdict"] == "yes":
            # unrelated is not beneath it either: a placement there is refused too
            self._put(term, "is_a", self._j("no", a, f"refused: {reason or 'different'}", iri=isa.get("iri")),
                      canonical)
        self.save()

    def pass_cache(self, name: str, *, read: bool = True) -> _PassCache:
        return _PassCache(self, name, read=read)

    def verdicts(self, name: str) -> dict[str, dict]:
        agent = RUN[name]
        out = {}
        for t, r in self._records.items():
            for c, js in (r.get("pairs") or {}).items():
                mine = [j for j in js if j["by"] == agent]
                if mine:
                    out[f"{t}{KEY_SEP}{c}"] = {"verdict": mine[-1]["verdict"], "reason": mine[-1]["why"]}
        return out

    def judged(self, name: str) -> int:
        return len(self.verdicts(name))

    def _runs(self, js: list[dict]) -> tuple[dict, dict]:
        last = {}
        for j in js:
            last[j["by"]] = j
        return last.get(RUN["pass1"]) or {}, last.get(RUN["pass2"]) or {}

    def subsumption_candidates(self) -> list[dict]:
        rows = []
        for term, r in self._records.items():
            for c, js in (r.get("pairs") or {}).items():
                p1, p2 = self._runs(js)
                v1, v2 = p1.get("verdict"), p2.get("verdict")
                direction = v1 if v1 in SUBSUMPTION_VERDICTS else v2
                if direction not in SUBSUMPTION_VERDICTS:
                    continue
                narrower = direction == "narrower"
                rows.append({"Class": term if narrower else c, "Parent class": c if narrower else term,
                             "store term": term, "ontology class": c,
                             "pass 1": v1, "pass 1 reason": p1.get("why", ""),
                             "pass 2": v2, "pass 2 reason": p2.get("why", ""),
                             "agree": bool(v1 and v2 and v1 == v2), "mapped": self._target(term) == c})
        return sorted(rows, key=lambda r: (r["store term"], r["ontology class"]))

    def disagreements(self) -> list[dict]:
        rows = []
        for term, r in self._records.items():
            for c, js in (r.get("pairs") or {}).items():
                p1, p2 = self._runs(js)
                v1, v2 = p1.get("verdict"), p2.get("verdict")
                if v1 and v2 and v1 != v2:
                    rows.append({"term": term, "canonical": c, "pass 1": v1, "pass 1 reason": p1["why"],
                                 "pass 2": v2, "pass 2 reason": p2["why"], "mapped": self._target(term) == c})
        return sorted(rows, key=lambda r: (r["term"], r["canonical"]))

    # ── The name of a cluster (rule 85) ────────────────────────────────────────

    def decide_name(self, chosen: str, instead_of, *, by: str = "curator",
                    reason: str = "", when: str | None = None) -> None:
        a = agent_of(by)
        chosen = self.resolve(chosen)
        instead = sorted({self.resolve(t) for t in ([instead_of] if isinstance(instead_of, str)
                                                    else instead_of)} - {chosen})
        head = self._head(chosen)
        if head in instead:
            self._put(chosen, "name", self._j(chosen, a, "named its own cluster", when), dated=bool(when))
            name = chosen
        else:
            name = head
            instead = [l for l in instead if l != name]
        for loser in instead:
            if self.is_refused(loser, chosen):
                raise ValueError(f"{loser!r} -> {chosen!r}: the author keeps the two apart")
        for loser in instead:
            for t in list(self._records):
                if self._target(t) == loser:
                    self._put(t, "name", self._j(name, a, f"its cluster is named {name!r}", when), dated=bool(when))
                elif loser in split_of(self._records[t]).values():
                    sp = {c: (name if n == loser else n) for c, n in split_of(self._records[t]).items()}
                    self._put(t, "name", self._j(sp, a, f"a sense renamed to {name!r}", when), dated=bool(when))
            self._put(loser, "name", self._j(name, a, reason or f"chose {chosen!r} as the name", when), dated=bool(when))
            cj = current(((self._records.get(loser) or {}).get("pairs") or {}).get(chosen))
            if not (cj and cj["verdict"] == "same_class" and cj["by"] == a):
                self._put(loser, "pairs", self._j("same_class", a, reason or f"chose {chosen!r} as the name", when),
                          chosen, dated=bool(when))

    def heads(self) -> set[str]:
        out = set()
        for t, r in self._records.items():
            if (tg := self._target(t)):
                out.add(tg)
            out.update(split_of(r).values())
        return out

    def named(self) -> set[str]:
        out = set()
        for t, r in self._records.items():
            tg = self._target(t)
            cj = current((r.get("pairs") or {}).get(tg)) if tg else None
            if cj and rank(cj) == AUTHOR and cj["verdict"] == "same_class":
                out.add(tg)
        return out

    def split_synonyms(self) -> list[tuple[str, str]]:
        out = set()
        for t, r in self._records.items():
            for c, js in (r.get("pairs") or {}).items():
                cj = current(js)
                if cj and rank(cj) == AUTHOR and cj["verdict"] == "same_class":
                    a, b = self._head(t), self._head(self.resolve(c))
                    if a != b:
                        out.add(tuple(sorted((a, b))))
        return sorted(out)

    def locked_mappings(self) -> list[tuple[str, str]]:
        return sorted((t, tg) for t in self._records if (tg := self._target(t)) and self.is_refused(t, tg))

    def apply_renames(self, renames: dict[str, str], *, by: str, why: str = "renamed") -> dict:
        """Rewrite every string the file holds. A renamed record's judgements move to
        the new spelling; the old string keeps its name judgements that point there
        (or gets one) -- nothing is dropped. A name naming another concept moves
        with the decisions."""
        report: dict = {"keys renamed": 0, "targets renamed": 0, "pair keys renamed": 0,
                        "records merged": 0, "aliases": 0, "chains": 0,
                        "names kept on the old spelling": 0, "sense labels renamed": 0}
        if not renames:
            return report
        a = agent_of(by, "string-normalisation")
        look = lambda s: renames.get(s, s)

        def rename_target(j: dict) -> dict:
            v = j["verdict"]
            if isinstance(v, str) and look(v) != v:
                report["targets renamed"] += 1
                return {**j, "verdict": look(v)}
            if isinstance(v, dict):
                report["sense labels renamed"] += sum(1 for n in v.values() if look(n) != n)
                return {**j, "verdict": {c: look(n) for c, n in v.items()}}
            return j

        def rekey(d: dict, relation: bool = False) -> dict:
            out: dict = {}
            for k, js in d.items():
                if relation and ":" in k:
                    p, t = k.split(":", 1)
                    nk = f"{p.strip()}: {look(t.strip())}"
                else:
                    nk = look(k)
                if nk != k:
                    report["pair keys renamed"] += 1
                out[nk] = ordered(out.get(nk, []) + js)
            return out

        clash = sorted({o for o, n in renames.items() if o != n} & {n for o, n in renames.items() if o != n})
        if clash:
            raise RuntimeError(f"[mapping] {len(clash)} string(s) are renamed away and onto at once: {clash[:5]}")
        cats_before = {t: c["verdict"] for t, c in self.categories().items()}
        names_before = {t: self._target(t) for t in self._records
                        if self._target(t) and self.named_by(t) not in SPELLING_AGENTS}
        merged: dict[str, dict] = {}
        for term in sorted(self._records):
            rec = self._records[term]
            new = {}
            for q, v in rec.items():
                if q == "name" and look(term) == term:
                    # A rename that turns a spelling back onto this very string
                    # (the curator, 2026-09-28: -ical, not -ic) keeps the old
                    # spelling as history and says so in a judgement after it.
                    out_l = []
                    for j in v:
                        nj = rename_target(j)
                        reversed_ = isinstance(j["verdict"], str) and j["verdict"] != term \
                            and nj["verdict"] == term
                        out_l.append(j if reversed_ else nj)
                    cj = current(out_l)
                    if cj and isinstance(cj["verdict"], str) and look(cj["verdict"]) == term \
                            and cj["verdict"] != term:
                        out_l.append(self._j(term, a, f"spelling reversed: {term!r} is written so again"))
                    new[q] = out_l
                elif q == "name":
                    new[q] = [rename_target(j) for j in v]
                elif q in ("pairs", "is_a"):
                    new[q] = rekey(v)
                elif q == "relations":
                    new[q] = rekey(v, relation=True)
                else:
                    new[q] = v
            key = look(term)
            if key != term:
                report["keys renamed"] += 1
                names = new.pop("name", [])
                moved = new
                # what names the new spelling stays with the old string, as its
                # history, and so does how a spelling rule once wrote the old
                # string: moved, `bacterial infection` -> `Bacterial infection`
                # came back pointing from the new name to the old spelling, which
                # points to the new name -- 82 strings in a loop on 2026-10-29.
                # A name naming another concept goes with the decisions.
                own = lambda j: j["verdict"] == key or j["by"] in SPELLING_AGENTS  # noqa: E731
                stay = [j for j in names if own(j)]
                go = [j for j in names if not own(j)]
                report["names kept on the old spelling"] += len(stay)
                new = {"name": stay or [self._j(key, a, why)]}
                cj = current(new["name"])
                if cj["verdict"] != key or cj["by"] not in SPELLING_AGENTS:
                    # the old string is now this spelling; a name it had onto the
                    # same string stays before it, as its history
                    new["name"].append(self._j(key, a, why))
                if go:
                    moved = {**moved, "name": go}
                dest = merged.setdefault(key, {})
                if dest:
                    report["records merged"] += 1
                for q, v in moved.items():
                    if isinstance(v, list):
                        dest[q] = ordered(dest.get(q, []) + v)
                    else:
                        d = dest.setdefault(q, {})
                        for k2, js in v.items():
                            d[k2] = ordered(d.get(k2, []) + js)
            if term in merged and key == term:
                for q, v in new.items():
                    if isinstance(v, list):
                        merged[term][q] = ordered(merged[term].get(q, []) + v)
                    else:
                        d = merged[term].setdefault(q, {})
                        for k2, js in v.items():
                            d[k2] = ordered(d.get(k2, []) + js)
            else:
                merged[term] = new
        for old, new_ in renames.items():
            if old != new_ and old not in self._records:
                merged.setdefault(old, {"name": [self._j(new_, a, why)]})
        report["aliases"] = sum(1 for o, n in renames.items() if o != n)
        self._records = merged
        self._dirty()
        # A merge can bring a name onto a string whose pair with that name the
        # author keeps apart (2026-10-20: `Antiseptic agent -> antiseptic drug`,
        # one spelling carried the mapping, the other the refusal). The author's
        # word on the pair stands: the name is answered with the string's own.
        locked = []
        for t in list(self._records):
            tgt = self._target(t)
            if tgt and self.named_by(t) not in SPELLING_AGENTS and self.is_refused(t, tgt):
                self._put(t, "name", self._j(t, a, f"the author keeps {t!r} and {tgt!r} apart (rule 84)"))
                locked.append((t, tgt))
        report["locked targets"] = sorted(locked)
        # Two spellings merged with two decided categories: the read rule picks
        # one (the author's last word), and the disagreement is named, not hidden.
        came = {}
        for t in cats_before:
            came.setdefault(look(t), set()).add(cats_before[t])
        landed: dict = {}
        for t, tgt in names_before.items():
            landed.setdefault(look(t), set()).add(look(tgt))
        report["target conflicts"] = sorted(
            (k, sorted(v), self._target(k)) for k, v in landed.items() if len(v) > 1)
        report["category conflicts"] = sorted(
            (k, sorted(c), (self.categories().get(k) or {}).get("verdict")) for k, c in came.items() if len(c) > 1)
        live = self.data
        report["chains"] = sum(1 for c in live.values() if c in live)
        self.save()
        return report

    # ── Scope ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _gate_key(term: str) -> str:
        from wound_ontology.utils.string_utils import normalize_term
        return normalize_term(term) or term.strip().lower()

    def _gate_alias(self, term: str) -> str | None:
        """Another spelling of `term` whose record answers scope, folded by `normalize_term`.
        A name with a bracketed qualifier is not folded onto the bare word:
        `normalize_term` drops the qualifier, and `vitamin (role)` is not `vitamin`."""
        if self._gate_idx is None:
            idx: dict[str, str] = {}
            for name, rec in self._records.items():
                if rec.get("scope") and "(" not in name:
                    key = self._gate_key(name)
                    if key not in idx or name == key or (idx[key] != key and name < idx[key]):
                        idx[key] = name
            self._gate_idx = idx
        hit = self._gate_idx.get(self._gate_key(term))
        return hit if hit and hit != term else None

    def gate(self, term: str, **fields) -> None:
        """A scope judgement on `term`'s concept: `rule=`, `pass1=`, `pass2=`, `curator=`. Does not save."""
        from wound_ontology.mappers.rule89_migration import gate_rule_agent
        concept = self.concept(self.resolve(term))
        for src, v in fields.items():
            if src not in GATE_SOURCES:
                raise ValueError(f"{src!r} is not a gate source; expected {GATE_SOURCES}")
            if v.get("verdict") not in GATE_VERDICTS:
                raise ValueError(f"{term!r} {src}: verdict {v.get('verdict')!r} is not one of {GATE_VERDICTS}")
            if src == "pass1":
                by = "sapbert-neighbour"
                why = f"copied from the most similar decided term {v.get('near')!r} (cosine {v.get('score')})"
            elif src == "pass2":
                by, why = "deepseek-v4-flash", v.get("reason", "")
            elif src == "rule":
                by = "number-unit-rule" if str(v.get("by", "")).startswith("noise") else gate_rule_agent(v.get("by"))
                if by == "unrecorded":
                    raise ValueError(f"no agent for the scope rule {v.get('by')!r}")
                why = v.get("reason") or v.get("by") or "rule"
            else:
                by, why = agent_of(v.get("by")), v.get("reason", "")
            self._put(concept, "scope", self._j(v["verdict"], by, why, v.get("when")), dated=bool(v.get("when")))
        self._gate_idx = None

    def _scope_j(self, term: str) -> dict | None:
        return current((self._records.get(term) or {}).get("scope"))

    def gate_verdict(self, term: str) -> tuple[str, str]:
        """`(verdict, agent)` the concept's scope gives `term`, or `("", "")`.
        A sense of a term split by category (rule 87) without a scope of its
        own takes the split term's."""
        c = self.concept(self.resolve(term))
        j = self._scope_j(c)
        if j is None and (src := self._split_source(c)):
            j = self._scope_j(src)
        if j is None and (alias := self._gate_alias(c) or self._gate_alias(term)):
            j = self._scope_j(alias)
        return (j["verdict"], j["by"]) if j else ("", "")

    def _split_source(self, name: str) -> str | None:
        """The term split by category that names `name` as one of its senses."""
        if self._split_idx is None:
            self._split_idx = {n: t for t, r in self._records.items() for n in split_of(r).values()}
        return self._split_idx.get(name)

    effective_gate_verdict = gate_verdict

    def own_gate_verdict(self, term: str) -> tuple[str, str]:
        j = self._scope_j(term)
        return (j["verdict"], j["by"]) if j else ("", "")

    def gated(self, verdict: str) -> dict[str, str]:
        if verdict not in GATE_VERDICTS:
            raise ValueError(f"{verdict!r} is not one of {GATE_VERDICTS}")
        out = {}
        for t, r in self._records.items():
            j = current(r.get("scope"))
            if j and j["verdict"] == verdict:
                out[t] = j["by"]
        return out

    def gate_disagreements(self) -> list[dict]:
        """Concepts whose scope judgements do not all say the same."""
        rows = []
        for t, r in self._records.items():
            said = {}
            for j in r.get("scope") or []:
                if j["verdict"] != ABSTAIN:
                    said[j["by"]] = j["verdict"]
            if len(set(said.values())) > 1:
                v, src = self.own_gate_verdict(t)
                rows.append({"term": t, "said": said, "verdict": v, "source": src})
        return sorted(rows, key=lambda r: r["term"].lower())

    def gate_contradictions(self) -> list[dict]:
        """Scope lives on the concept only (rule 89): nothing to contradict."""
        return []

    # ── is_a: placements and categories ───────────────────────────────────────

    def placements(self) -> list[tuple[str, str]]:
        """`(term, class)`: every term under an ontology class, as the hierarchy's `placed` source."""
        out = []
        for term, r in self._records.items():
            if self._target(term) or split_of(r):
                continue
            for tgt, js in (r.get("is_a") or {}).items():
                cj = current(js)
                if cj and cj["verdict"] == "yes" and any(j.get("iri") for j in js) \
                        and self.gate_verdict(term)[0] != "out":
                    out.append((term, tgt))
        return sorted(out)

    def relation_judgement(self, subject: str, predicate: str, target: str) -> dict | None:
        """The judgement that counts on `subject predicate target`, read on the
        subject's concept, with both ends followed to their current names and
        the predicate's spelling (`has quality`, `has_quality`) ignored."""
        norm = lambda p: p.strip().lower().replace(" ", "_")  # noqa: E731
        here = lambda t: self.concept(self.resolve(t.strip())).lower()  # noqa: E731
        rec = self._records.get(self.concept(self.resolve(subject))) or {}
        want = (norm(predicate), here(target))
        js = [j for k, v in (rec.get("relations") or {}).items()
              if (norm(k.partition(":")[0]), here(k.partition(":")[2])) == want for j in v]
        return current(ordered(js)) if js else None

    def read_relations(self, reader: str) -> list[tuple[str, str, str, bool, dict]]:
        """`(subject, predicate, target, axiom, judgement)` for every relation
        the instance reading `reader` or the author judged (rules 66, 88, 89).

        A relation becomes an axiom when the author's last word on it is `yes`;
        without one, when the reading's last answer is `yes` and nothing that
        counts says `no` (an ELK refusal after the reading). ELK's own `yes`
        says only that it no longer objects, and a renaming rule's `yes` that
        the relation has the right form; neither makes a relation true of
        every instance. The reading lived in `result.json` files beside the
        term dict until 2026-10-30 (curator: "das machst du ganz sicher nicht")."""
        out = []
        for subj, rec in self._records.items():
            for key, js in (rec.get("relations") or {}).items():
                mine = [j for j in js if j["by"] == reader or rank(j) == AUTHOR]
                if not mine:
                    continue
                said = current(mine)
                if said is None:
                    continue
                now = current(js)
                axiom = said["verdict"] == "yes" and (rank(said) == AUTHOR or (now or said)["verdict"] != "no")
                pred, _, tgt = key.partition(":")
                out.append((subj, pred.strip(), tgt.strip(), axiom, said))
        return out

    def author_relations(self) -> list[tuple[str, str, str, dict]]:
        """`(subject, predicate, target, judgement)`: the author's last word on
        every relation he judged. The core's relations are his `yes` (rules 69,
        72); his decisions of the review pages were kept in files beside the
        term dict until 2026-10-30 (`curator_axioms_2026-10-03.json`,
        `new_class_relation_decisions.json`)."""
        out = []
        for subj, rec in self._records.items():
            for key, js in (rec.get("relations") or {}).items():
                said = current([j for j in js if rank(j) == AUTHOR])
                if said is not None:
                    pred, _, tgt = key.partition(":")
                    out.append((subj, pred.strip(), tgt.strip(), said))
        return out

    def end_word_renames(self, suffixes: dict[str, str], is_ontology_label, head=None) -> dict[str, str]:
        """`{term: "<term> <category>"}` for every concept ending in a word of
        `suffixes` whose category is the one named there
        (`config.category_head_rules.HEAD_NAME_SUFFIX`: a process ending in
        "infection" is named "... infection process"). A term that is the
        label of an ontology class (`is_ontology_label`) keeps its name and the
        ontology's sense; a new name already taken by another concept is not
        given and is named loudly."""
        out, taken = {}, []
        for t, c in self.categories().items():
            # the head word as the head rules read it (`scripts/apply_category_rulings.head`:
            # the word before the first preposition, else the last): "Treatment of
            # infection" is a treatment, not an infection
            hit = (head(t) if head(t) in suffixes else None) if head is not None else \
                next((w for w in suffixes if t.lower().endswith(w)), None)
            if hit is None or c["verdict"] != suffixes[hit] or self.concept(self.resolve(t)) != t \
                    or is_ontology_label(t):
                continue
            new = f"{t} {suffixes[hit]}"
            if new in self._records and self.concept(self.resolve(new)) != t:
                taken.append((t, new))
                continue
            out[t] = new
        if taken:
            print(f"[TermMappingAndGate] *** {len(taken)} name(s) the end-word rule asks for are another "
                  f"concept's already; not renamed: {taken[:5]} ***")
        return out

    def placement_iri(self, term: str, target: str) -> str | None:
        js = ((self._records.get(term) or {}).get("is_a") or {}).get(target) or []
        return next((j["iri"] for j in reversed(js) if j.get("iri")), None)

    def term_links(self) -> list[tuple[str, str]]:
        """`(term, parent term)`: every term the author put under another term,
        as the hierarchy's `placed` source beside `placements()`.

        Rule 89 (curator, 2026-10-28): the author's `narrower` / `broader`
        between two terms are also written as is_a `yes`, so they act in the
        hierarchy. Only the author's word counts here: ELK's `yes` on an edge
        between two terms says the edge is consistent, not that it holds, and
        the naming review's `narrower` without an is_a stays a note
        (`reducing Pressure ulcer`). Both ends must be concepts in scope; a
        parent renamed since is named loudly and left out, never followed."""
        from wound_ontology.llm.category_vocab import declared_category
        out, moved = [], []
        for term, r in self._records.items():
            if self._target(term) or split_of(r):
                continue
            for tgt, js in (r.get("is_a") or {}).items():
                if declared_category(tgt) or any(j.get("iri") for j in js) or tgt not in self._records:
                    continue
                cj = current(js)
                if not (cj and cj["verdict"] == "yes" and rank(cj) == AUTHOR):
                    continue
                if self.concept(self.resolve(tgt)) != tgt:
                    moved.append((term, tgt, self.concept(self.resolve(tgt))))
                    continue
                if self.gate_verdict(term)[0] != "out" and self.gate_verdict(tgt)[0] != "out":
                    out.append((term, tgt))
        if moved:
            print(f"[TermMappingAndGate] *** {len(moved)} author is_a link(s) name a parent that is "
                  f"now written differently; left out until the link is rewritten: ***")
            for t, p, now in moved[:10]:
                print(f"[TermMappingAndGate]     {t} is_a {p}  ({p!r} is now {now!r})")
        return sorted(out)

    def categories(self, *, reopen: str | frozenset[str] | None = None) -> dict[str, dict]:
        """`{term: {"verdict": category, "source", "by", "note", "when"}}` for every decided category.

        `reopen` sets one agent's judgements aside, as `cell` does: the edge
        check re-hears a category the end-word rule decided and ELK refused
        (98 on 2026-10-29), which it never could while the refusal hid it."""
        from wound_ontology.llm.category_vocab import declared_category
        out = {}
        for t, r in self._records.items():
            for tgt, js in (r.get("is_a") or {}).items():
                if not declared_category(tgt) or not any(not j.get("iri") for j in js):
                    continue
                cj = current(heard(js, reopen))
                if cj and cj["verdict"] == "yes":
                    out[t] = {"verdict": tgt, "source": TERM_RULING if cj["by"] == "author" else "end-word rule",
                              "by": cj["by"], "note": cj["why"], "when": cj["when"]}
        return out

    def set_category(self, term: str, verdict: str, *, source: str, by: str = "curator",
                     note: str = "") -> str:
        """Decide the BFO category `term` names. Returns `set`, `same` or `kept`. Does not save."""
        from wound_ontology.llm.category_vocab import declared_category
        cat = declared_category(verdict)
        if cat is None:
            raise ValueError(f"{term!r}: {verdict!r} is not a BFO category")
        term = self.resolve(term)
        a = "author" if source == TERM_RULING else ("end-word-category" if source.startswith("head rule")
                                                   else agent_of(by))
        standing = self.categories().get(term) if term in self._records else None
        if standing and standing["verdict"] == cat and standing["by"] == a:
            return "same"
        if standing and standing["by"] == "author" and a != "author":
            return "kept"
        self._put(term, "is_a", self._j("yes", a, f"{source}; {note}".strip("; ")), cat)
        if standing and standing["verdict"] != cat:
            self._put(term, "is_a", self._j("no", a, f"category replaced by {cat}"), standing["verdict"])
        return "set"

    # ── Cells of the store: relations, and is_a typings ───────────────────────

    def cell(self, entity: str, triple: str, *, reopen: str | frozenset[str] | None = None) -> dict | None:
        """The judgement that counts on one store cell `predicate: target`, or None.
        `reopen` sets one agent's judgements aside, so that agent hears the cell
        anew -- or several agents' (`heard`)."""
        pred, _, tgt = triple.partition(":")
        pred, tgt = pred.strip(), tgt.strip()
        rec = self._records.get(entity) or {}
        js = edge_judgements((rec.get("is_a") or {}).get(tgt)) if pred == IS_A \
            else (rec.get("relations") or {}).get(f"{pred}: {tgt}")
        return current(heard(js, reopen))

    def cell_rejected(self, entity: str, triple: str, *, reopen: str | frozenset[str] | None = None) -> dict | None:
        cj = self.cell(entity, triple, reopen=reopen)
        if cj and cj["verdict"] == "no":
            return {"status": "rejected", "by": cj["by"], "note": cj["why"], "when": cj["when"]}
        return None

    def cell_predicate(self, entity: str, pred: str, target: str, *,
                       reopen: str | frozenset[str] | None = None) -> str | None:
        """The predicate a decision gives this cell instead of `pred` (rule 68), or None.
        `reopen` sets one agent's judgements aside, as `cell` does: the typing
        check re-hears a `has_tendency` it refused, which the refusal would
        otherwise hide together with the change of predicate.

        The change stands while its own agent's last word on both cells is the
        change (`no` on the old predicate, `yes` on the new one); what another
        agent says later judges the relation under its new predicate and does
        not undo the change. Until 2026-10-30 the change had to be the last
        word of all: when the typing check passed `Pressure ulcer has_tendency
        Pressure ulcer risk`, the change vanished, the old `has_disposition`
        cell's `no` counted, and the relation left the store view."""
        rel = (self._records.get(entity) or {}).get("relations") or {}
        old = heard(rel.get(f"{pred}: {target}"), reopen) or []
        for k, js in rel.items():
            p2, _, t2 = k.partition(":")
            if t2.strip() != target or p2.strip() == pred:
                continue
            new = heard(js, reopen) or []
            change = next((j for j in reversed(new) if f"predicate changed from {pred}" in (j.get("why") or "")), None)
            if change is None:
                continue
            own_new = [j for j in new if j["by"] == change["by"]]
            own_old = [j for j in old if j["by"] == change["by"]]
            if own_new[-1] is change and change["verdict"] == "yes" and own_old and own_old[-1]["verdict"] == "no":
                return p2.strip()
        return None

    def relation_cells(self, owners, pred: str, target: str) -> list[tuple[str, str]]:
        """Every cell `(owner, "pred: t")` of the records `owners` whose value `t`
        names the concept `target` names: one relation under all its spellings.

        A judgement on any of them is one on the relation, as the axioms count
        it (`read_relations` resolves the value). 2026-10-30: `Burn wound
        has_disposition` was read `no` under the spelling `Risk of infection`
        and, unseen, read again under `Infection risk`. A spelling cycle
        raises, as `resolve` does: it is a defect of the term dict."""
        def concept(x):
            return self.concept(self.resolve(x))
        want = concept(target)
        return [(o, k) for o in dict.fromkeys(owners)
                for k in ((self._records.get(o) or {}).get("relations") or {})
                if k.partition(":")[0].strip() == pred and concept(k.partition(":")[2].strip()) == want]

    def judge_cell(self, entity: str, triple: str, verdict: str, *, by: str, why: str = "",
                   new_predicate: str | None = None, only_on_change: bool = True) -> bool:
        """A judgement on one store cell. With `only_on_change`, nothing is written
        when the agent's own last judgement on it already says the same, for the
        same reason."""
        if verdict not in ("yes", "no"):
            raise ValueError(f"a cell verdict is yes or no, not {verdict!r}")
        a = agent_of(by)
        pred, _, tgt = triple.partition(":")
        pred, tgt = pred.strip(), tgt.strip()
        q, key = (IS_A, tgt) if pred == IS_A else ("relations", f"{pred}: {tgt}")
        js = ((self._records.get(entity) or {}).get(q) or {}).get(key) or []
        mine = [j for j in js if j["by"] == a]
        why = why or ("rejected" if verdict == "no" else "passes")
        if only_on_change and mine and (mine[-1]["verdict"], mine[-1]["why"]) == (verdict, why) \
                and not new_predicate:
            return False
        self._put(entity, q, self._j(verdict, a, why), key)
        if new_predicate:
            self._put(entity, q, self._j("no", a, f"{why}; predicate changed to {new_predicate}"), key)
            self._put(entity, "relations", self._j("yes", a, f"{why}; predicate changed from {pred}"),
                      f"{new_predicate}: {tgt}")
        return True

    def last_of(self, agent: str, verdict: str) -> set[tuple[str, str]]:
        """`(entity, "pred: target")` for every cell whose last judgement by `agent` is `verdict`."""
        out = set()
        for t, r in self._records.items():
            for k, js in (r.get("relations") or {}).items():
                mine = [j for j in js if j["by"] == agent]
                if mine and mine[-1]["verdict"] == verdict:
                    out.add((t, k))
            for tgt, js in (r.get("is_a") or {}).items():
                mine = [j for j in js if j["by"] == agent]
                if mine and mine[-1]["verdict"] == verdict:
                    out.add((t, f"{IS_A}: {tgt}"))
        return out

    def decided_category_cell(self, entity: str, triple: str) -> bool:
        """True when the cell is the category a person or rule decided for the term."""
        pred, _, tgt = triple.partition(":")
        c = self.categories().get(self.resolve(entity))
        return pred.strip() == IS_A and bool(c) and c["verdict"] == tgt.strip()

    def rejected_cells(self) -> dict[str, dict[str, dict]]:
        out: dict[str, dict[str, dict]] = {}
        for t, r in self._records.items():
            for k, js in (r.get("relations") or {}).items():
                cj = current(js)
                if cj and cj["verdict"] == "no":
                    out.setdefault(t, {})[k] = {"status": "rejected", "by": cj["by"], "note": cj["why"], "when": cj["when"]}
            for tgt, js in (r.get("is_a") or {}).items():
                cj = current(edge_judgements(js))
                if cj and cj["verdict"] == "no":
                    out.setdefault(t, {})[f"{IS_A}: {tgt}"] = {"status": "rejected", "by": cj["by"],
                                                              "note": cj["why"], "when": cj["when"]}
        return out

    # ── Edges of the class hierarchy (rule 89: the reasoner writes here) ──────

    def edge_judgement(self, child: str, parent: str) -> dict | None:
        return current(edge_judgements(((self._records.get(child) or {}).get("is_a") or {}).get(parent)))

    def judge_edge(self, child: str, parent: str, verdict: str, *, why: str) -> bool:
        """ELK's verdict on the edge `child is_a parent`, written only when it or
        its reason changes."""
        js = ((self._records.get(child) or {}).get("is_a") or {}).get(parent) or []
        mine = [j for j in js if j["by"] == "elk"]
        if mine and (mine[-1]["verdict"], mine[-1]["why"]) == (verdict, why):
            return False
        if not mine and verdict == "yes":
            return False                    # an edge ELK never refused needs no yes
        self._put(child, "is_a", self._j(verdict, "elk", why), parent)
        return True

    # ── Persistence ───────────────────────────────────────────────────────────

    def _dirty(self) -> None:
        self._flat = None
        self._gate_idx = None
        self._split_idx = None

    def save(self) -> None:
        if self._records:
            self._dm.save_as_json({"format": FORMAT, "agents": AGENTS, "terms": self._records}, self._file_name)
