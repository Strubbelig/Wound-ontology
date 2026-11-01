"""Translate a term dict of the old shape into the shape of rule 89. Pure.

`migrate(records, dating)` takes the records as `TermMappingAndGate._load`
returns them and gives back the new records and a report of everything the
translation had to reconstruct or could not place. Nothing is dropped: every
verdict, history entry, lock and withdrawn verdict becomes a judgement.

`dating` answers for judgements the old records hold without a usable time:
`dating.when(kind, *key, default=...)` -> (ISO date or date-time, note).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from wound_ontology.mappers.judgements import AGENTS, RUN, current, is_when, make, ordered

PAIR_VERDICTS = ("same_class", "narrower", "broader", "different")
#: what the curator's verdicts said before 2026-10-24, relative to the pair
OLD_CURATOR = {"refused": "different", "kept": "same_class", "reverse": "same_class",
               "reversed": "same_class", "repointed": "different"}
PLACEMENT_RUN = "2026-09-29"       # the placement model's run (placement_2026-09-29)
PLACEMENT_CHECK = "2026-10-01"     # the yes/no question and Claude's reading


# ── who: the old free-text `by` and the old slots, onto AGENTS ──────────────

def spelling_agent(by: str | None) -> str:
    b = str(by or "").lower()
    if b.startswith(("pass0", "reconstructed", "ingestion")):
        return "string-normalisation"          # ingestion cleans a new string with the same normaliser
    if "rule 58" in b:
        return "abbreviation-full-form"
    if "trauma -> injury" in b:
        return "no-trauma-to-injury"
    if "hyphenated modifier" in b:
        return "hyphen-modifier-not-grade"
    if "latin and invariant" in b:
        return "latin-keeps-final-s"
    if "proper names" in b:
        return "proper-names-kept"
    if "action potential" in b:
        return "action-potential-kept"
    if "spelling typed in the scope review" in b:
        return "author"
    return "unrecorded"


def curator_agent(by: str | None) -> str:
    """An entry in a `curator` slot: the author, unless a rule or a program wrote it."""
    b = str(by or "").lower()
    if "locks resolved" in b:
        return "author"                 # the curator ruling the rule-58 locks one by one, in chat
    if "rule 58" in b:
        return "abbreviation-full-form"
    if "rule 68" in b:
        return "tendency-not-disposition"
    if "a lock with no stated relation" in b:
        return "lock-means-different"
    if "hyphenated modifier" in b:
        return "hyphen-modifier-not-grade"
    if b == "ontology label":
        return "ontology-label-match"
    if "reasoner" in b:
        return "elk"
    if "claude" in b:
        return "claude-opus-5-5"
    return "author"


GATE_RULE_AGENT = {"METHODOLOGY_BLOCKLIST": "methodology-blocklist", "WHITELIST": "whitelist",
                   "KEYWORD_WHITELIST": "keyword-whitelist", "KEYWORD_BLOCKLIST": "keyword-blocklist"}


def gate_rule_agent(by: str | None) -> str:
    b = str(by or "")
    if b.startswith("noise rule"):
        return "number-unit-rule"
    for k, v in GATE_RULE_AGENT.items():
        if b.startswith(k):
            return v
    return "unrecorded"


METHOD_AGENT = {"sapbert_cluster": "sapbert-clustering", "string_norm": "cluster-premerge",
                "chain_resolved": "chain-resolution", "pass0": "string-normalisation",
                "ontology_label": "ontology-label-match", "curator": "author", "manual": "author"}


def retired_agent(reason: str) -> str:
    r = str(reason or "").lower()
    if r.startswith("pass 1 did not confirm"):
        return "deepseek-v4-flash_bulk20"
    if r.startswith("category guard"):
        return "category-guard"
    if r.startswith("rule 36"):
        return "ontology-label-is-canonical"
    if r.startswith(("spelling of its own canonical", "target no longer exists", "re-spelling",
                     "chain ends at an anchor")):
        return "mapping-cleanup"
    return "unrecorded"


def spelling_why(old: str, new: str) -> str:
    """Which normalisation step turns `old` into `new` (rule 89: `why` is never empty)."""
    from wound_ontology.utils.label_match import singular_spelling
    from wound_ontology.utils.spelling import american_spelling
    dash = lambda s: re.sub(r"[\s\-‐-―_]+", "", s.lower())
    if old.lower() == new.lower():
        return "capitalisation"
    if dash(old) == dash(new):
        return "hyphen or space"
    steps = []
    s = old
    for name, fn in (("singular", singular_spelling), ("American spelling", american_spelling)):
        t = fn(s)
        if t != s:
            steps.append(name)
            s = t
        if s.lower() == new.lower() or dash(s) == dash(new):
            return " and ".join(steps)
    ow, nw = old.lower().split(), new.lower().split()
    if len(ow) > len(nw) and ow[-len(nw):] == nw:
        return "leading grading word removed"
    return "string normalisation (step not identified)"


# ── the translation ───────────────────────────────────────────────────────────

def _date_and_rest(raw) -> tuple[str | None, str]:
    """`"2026-09-28 llm scope pass"` -> ("2026-09-28", "llm scope pass")."""
    if is_when(raw):
        return raw, ""
    m = re.match(r"(?:imported )?(\d{4}-\d\d-\d\d)\b\s*(.*)", str(raw or ""))
    return (m.group(1), m.group(2)) if m else (None, str(raw or ""))


def _why(*parts) -> str:
    return "; ".join(str(p) for p in parts if p not in (None, "", []))


def migrate(records: dict[str, dict], dating, placement_rows: list[dict] | None = None,
            confirmations: list[dict] | None = None, edge_verdicts: dict | None = None):
    rep = Counter()
    notes = defaultdict(list)
    new: dict[str, dict] = {}

    def when(raw, kind, *key, why_parts=None):
        d, rest = _date_and_rest(raw)
        if rest and why_parts is not None:
            why_parts.append(rest)
        if d:
            return d
        w, note = dating.when(kind, *key)
        rep[f"when reconstructed: {note}"] += 1
        if why_parts is not None:
            why_parts.append(f"time reconstructed ({note})")
        return w

    def J(verdict, by, why, w, iri=None):
        if by == "unrecorded":
            rep["by unrecorded"] += 1
        return make(verdict, by, why or "no reason recorded", w, iri)

    # 1. strings: spelling, name, pairs ------------------------------------------------
    for term, rec in records.items():
        out = new.setdefault(term, {})
        if "spelling" in rec:
            s = rec["spelling"]
            entries = []
            for h in (s.get("history") or []):
                a = spelling_agent(h.get("by"))
                entries.append(J(h["to"], a, spelling_why(term, h["to"]) if a == "string-normalisation" else str(h.get("by")),
                                 when(h.get("when"), "spelling", term, h["to"])))
            a = spelling_agent(s.get("by"))
            why = spelling_why(term, s["to"]) if a == "string-normalisation" else str(s.get("by"))
            if str(s.get("by", "")).startswith(("pass0 correction", "reconstructed")):
                why = _why(why, s["by"])
            if s.get("evidence"):
                why = _why(why, f"evidence: {s['evidence']}")
            entries.append(J(s["to"], a, why, when(s.get("when"), "spelling", term, s["to"])))
            if why.endswith("(step not identified)"):
                rep["spelling: normalisation step not identified"] += 1
            out["name"] = ordered(entries)
            continue
        # a spelling that was reversed: the old alias, then the string as itself
        if rec.get("spelling_reversed"):
            entries = []
            for h in rec["spelling_reversed"]:
                a = spelling_agent(h.get("by"))
                entries.append(J(h["to"], a, spelling_why(term, h["to"]) if a == "string-normalisation" else str(h.get("by")),
                                 when(h.get("when"), "spelling", term, h["to"])))
            # when the spelling was reversed was not recorded; it can only have been
            # after the spelling it reverses, so it is placed directly behind it
            last = max(e["when"] for e in entries)
            rep["spelling reversed: by unrecorded, placed after the spelling it reverses"] += 1
            entries.append(J(term, "unrecorded", "spelling reversed; who, why and when were not recorded "
                             "(placed directly after the spelling it reverses)", last))
            out["name"] = ordered(entries)

        # name
        name = []
        if rec.get("retired"):
            r = rec["retired"]
            name.append(J(term, retired_agent(r.get("reason")), _why("mapping retired", r.get("reason")),
                          when(r.get("when"), "retired", term)))
        to = rec.get("to")
        pairs = rec.get("pairs") or {}
        if isinstance(to, dict):
            name.append(J(dict(to), "author", "split by category (rule 87): one name per category",
                          when(None, "to", term, repr(sorted(to.items())))))
        elif isinstance(to, str):
            cu = (pairs.get(to) or {}).get("curator") or {}
            if cu.get("verdict") == "same_class":
                parts = [cu.get("reason")]
                w = when(cu.get("when"), "pair", term, to, "curator", "same_class", why_parts=parts)
                name.append(J(to, curator_agent(cu.get("by")), _why(*parts), w))
            else:
                a = METHOD_AGENT.get(rec.get("method"), "unrecorded")
                parts = [spelling_why(term, to) if a == "string-normalisation" else None, f"method {rec.get('method')}"]
                if rec.get("confidence") is not None and a == "sapbert-clustering":
                    parts.append(f"cosine similarity {rec['confidence']}")
                w = when(None, "to", term, to, why_parts=parts)
                name.append(J(to, a, _why(*parts), w))
        elif rec.get("method") and not rec.get("retired"):
            rep["no name, but a method left over"] += 1
            notes["no name, but a method left over"].append(term)
        if name:
            # the old record's `to` (or its retirement) is the answer in force; any
            # entry with a later reconstructed time is history it replaced, so the
            # answer in force is dated no earlier than that history
            in_force = name[-1]
            others = out.get("name", []) + name[:-1]
            later = [e["when"] for e in others if e["when"] > in_force["when"]]
            if later:
                in_force["when"] = max(later)
                in_force["why"] = _why(in_force["why"], "dated no earlier than the judgements it replaced")
                rep["name in force dated after the history it replaced"] += 1
            out["name"] = ordered(others + [in_force])

        # pairs (synonyms) and the placements, which are is_a
        newpairs, is_a = {}, {}
        for cand, pv in pairs.items():
            cu = pv.get("curator") or {}
            # a curator verdict carrying the class IRI is a placement, however it was
            # made (TermMappingAndGate.placements reads it that way); the placement
            # model's trail only where the placement step made it
            placement = bool(cu.get("iri")) and cu.get("verdict") in ("narrower", "same_class")
            entries = []
            for slot in ("pass1", "pass2"):
                if slot in pv:
                    v = pv[slot]
                    parts = [v.get("reason", "")]
                    for k in v:
                        if k not in ("verdict", "reason", "when"):
                            parts.append(f"{k} {v[k]}")
                    w = when(v.get("when"), slot, term, cand, v["verdict"], why_parts=parts)
                    entries.append(J(v["verdict"], RUN[slot], _why(*parts) or "no reason recorded", w))
            if "check" in pv:
                v = pv["check"]
                w = when(v.get("when"), "check", term, cand)
                entries.append(J(v["verdict"], RUN["check"], v.get("reason") or "no reason recorded", w))
                entries.append(J(v["verdict"], "claude-opus-5-5", "restatement check read: stands", w))
            for lock in pv.get("lock_history", []):
                parts = [lock.get("reason"), "a lock, kept as history since 2026-10-25"]
                w = when(lock.get("when"), "lock", term, cand, why_parts=parts)
                entries.append(J("different", curator_agent(lock.get("by")), _why(*parts), w))
            for h in pv.get("curator_history", []):
                v = h.get("verdict")
                if h.get("iri") and v in ("narrower", "same_class"):
                    # an earlier placement: an is_a (or a same-class) of the author, not a pair verdict
                    parts = [h.get("reason"), h.get("check"), "an earlier placement"]
                    w = when(h.get("when"), "pair", term, cand, "curator_history", v, why_parts=parts)
                    tgt = is_a if v == "narrower" else newpairs
                    tgt.setdefault(cand, []).append(J("yes" if v == "narrower" else v, curator_agent(h.get("by")),
                                                      _why(*parts), w, h["iri"]))
                    continue
                verdict = v if v in PAIR_VERDICTS else OLD_CURATOR.get(v)
                if verdict is None:
                    raise ValueError(f"{term!r} -> {cand!r}: curator history verdict {v!r} has no meaning")
                parts = [h.get("reason"), f"recorded as {v!r}" if v != verdict else None]
                w = when(h.get("when"), "pair", term, cand, "curator_history", v, why_parts=parts)
                entries.append(J(verdict, curator_agent(h.get("by")), _why(*parts), w, h.get("iri")))
            if cu and not placement:
                parts = [cu.get("reason")]
                if cu.get("was"):
                    parts.append(f"recorded as {cu['was']!r} until 2026-10-24")
                for k in ("why", "note", "item", "curator typed", "moved_from"):
                    if cu.get(k):
                        parts.append(f"{k}: {cu[k]}")
                w = when(cu.get("when"), "pair", term, cand, "curator", cu["verdict"], why_parts=parts)
                # The `curator` slot held the verdict in force; history and locks were
                # what it had replaced. A lock dissolved on 2026-10-25 can carry a
                # later time than a verdict whose time was never recorded; the
                # verdict was in force after it, so it is dated no earlier.
                a = curator_agent(cu.get("by"))
                later = [e["when"] for e in entries if AGENTS[e["by"]]["rank"] == "author" and e["when"] > w]
                if later and AGENTS[a]["rank"] == "author":
                    w = max(later)
                    parts.append("dated no earlier than the judgements it replaced")
                    rep["pair verdict dated after the history it replaced"] += 1
                entries.append(J(cu["verdict"], a, _why(*parts), w, cu.get("iri")))
            if placement:
                trail = _placement_trail(cu, rep)
                proposal = [j for j in trail if j["verdict"] == "same_class"] if cu["verdict"] == "narrower" else []
                if proposal:
                    # the proposal "same class" is a pair judgement, not an is_a answer (2026-10-30)
                    newpairs.setdefault(cand, []).extend(proposal)
                    trail = [j for j in trail if j["verdict"] != "same_class"]
                target = is_a if cu["verdict"] == "narrower" else newpairs
                target.setdefault(cand, [])
                target[cand].extend(trail)
                if cu["verdict"] not in ("narrower", "same_class"):
                    raise ValueError(f"{term!r} -> {cand!r}: placement verdict {cu['verdict']!r}")
            if entries:
                newpairs.setdefault(cand, []).extend(entries)
        # a placed pair refused afterwards: every later different/broader on the pair
        # is an is_a no as well, by the same agent at the same time
        for cand in list(is_a):
            first_yes = min((j["when"] for j in is_a[cand] if j["verdict"] == "yes"), default=None)
            if first_yes is None:
                continue
            for e in newpairs.get(cand, []):
                if e["verdict"] in ("different", "broader", "same_class") and e["when"] >= first_yes:
                    is_a[cand].append(J("no", e["by"], _why(e["why"], "the placement refused"), e["when"]))
                    rep["placement refused later: is_a no"] += 1
        if newpairs:
            out["pairs"] = {c: ordered(v) for c, v in newpairs.items()}
        if is_a:
            out["is_a"] = {c: ordered(v) for c, v in is_a.items()}

        # relations and the decided category
        for k, e in (rec.get("relations") or {}).items():
            if not isinstance(e, dict):
                continue
            pred, _, tgt = k.partition(":")
            pred, tgt = pred.strip(), tgt.strip()
            status = e.get("status")
            if pred == "is_a" and status == "decided":
                lst = out.setdefault("is_a", {})
                for h in e.get("history", []):
                    hw = when(h.get("when"), "category", term, h.get("verdict"))
                    lst.setdefault(h["verdict"], []).append(
                        J("yes", _category_agent(h), _why(h.get("source"), h.get("note")), hw))
                    nw = when(e.get("when"), "category", term, tgt)
                    lst[h["verdict"]].append(J("no", _category_agent(e), f"category replaced by {tgt}", nw))
                w = when(e.get("when"), "category", term, tgt)
                lst.setdefault(tgt, []).append(J("yes", _category_agent(e), _why(e.get("source"), e.get("note")) or "category decided", w))
                continue
            by = e.get("by") or e.get("source")
            w = when(e.get("when"), "relation", term, k)
            if pred == "is_a" and status == "rejected":
                # a category the abstracts gave the term, denied: an is_a judgement (rule 89)
                out.setdefault("is_a", {}).setdefault(tgt, []).append(
                    J("no", curator_agent(by), _why(e.get("note")) or "the category the abstracts give contradicts the ontology", w))
                continue
            rel = out.setdefault("relations", {})
            if status == "rejected":
                rel.setdefault(k, []).append(J("no", curator_agent(by), _why(e.get("note")) or "rejected", w))
            elif status == "repredicated":
                new_k = f"{e['to']}: {tgt}"
                a = curator_agent(by)
                rel.setdefault(k, []).append(J("no", a, _why(e.get("note"), f"predicate changed to {e['to']}"), w))
                rel.setdefault(new_k, []).append(J("yes", a, _why(e.get("note"), f"predicate changed from {pred}"), w))
            else:
                raise ValueError(f"{term!r} {k!r}: relation status {status!r} has no translation")
            if e.get("history"):
                raise ValueError(f"{term!r} {k!r}: relation history on a non-category relation")
        for k in ("relations", "is_a"):
            if k in out:
                out[k] = {t: ordered(v) for t, v in out[k].items()}

        # scope, still on the term for now (moved to the name below)
        sc = []
        g = rec.get("gate") or {}
        for src in ("rule", "pass1", "pass2", "curator"):
            v = g.get(src)
            if not isinstance(v, dict):
                continue
            sc.append(_scope_judgement(term, src, v, when, J))
        for h in g.get("rule_history", []):
            sc.append(_scope_judgement(term, "rule", h, when, J))
        for c in rec.get("gate_contested", []):
            dropped = c.get("dropped") or []
            for d in (dropped if isinstance(dropped, list) else [dropped]):
                if isinstance(d, dict) and d.get("verdict"):
                    j = _scope_judgement(term, c.get("source", "pass2"), d, when, J)
                    j["why"] = _why(j["why"], "outvoted by a later judgement of the same source")
                    sc.append(j)
                elif d:
                    rep["contested scope: dropped entry without a verdict"] += 1
        for wd in rec.get("gate_withdrawn", []):
            # a withdrawn copy is one abstention: what was copied, and why it was
            # withdrawn; it never counts, so it cannot outvote the other judgements
            copied = _scope_judgement(term, wd.get("source", "pass1"), wd, when, J)
            ww = when(wd.get("withdrawn when"), "withdrawn", term)
            sc.append(J("undecided", "neighbour-check" if wd.get("source") == "pass1" else "unrecorded",
                        _why(f"{copied['by']} had answered {wd.get('verdict')!r} on {copied['when']} ({copied['why']})",
                             f"withdrawn: {wd.get('withdrawn')}"), ww))
        if sc:
            out["scope"] = ordered(sc)

    # 1b. cycles of names: an old `to` onto a string that is now this term's own
    # spelling (`Epidermolysis bullosa -> epidermolysis bullosa` beside the later
    # spelling the other way). Before rule 89 the two sat in different fields and
    # nothing followed both; the old code dropped such identities on a rename and
    # this one slipped through. The name in force goes back to the term itself.
    def nxt(t):
        cj = current(new.get(t, {}).get("name"))
        v = cj and cj["verdict"]
        return v if isinstance(v, str) and v != t else None
    for term in list(new):
        seen, t = [], term
        while (n := nxt(t)) and t not in seen:
            seen.append(t)
            t = n
        if t == term and seen:                              # back where it started
            j = make(term, "mapping-cleanup", "its name led back to this term (a mapping onto its own "
                     "spelling, left over from before rule 51); the cycle is broken here",
                     max(e["when"] for e in new[term]["name"]))
            new[term]["name"] = ordered(new[term]["name"] + [j])
            rep["name cycle broken"] += 1
            notes["name cycle broken"].append(seen)

    # 1c. scope lives on the concept (rule 89): every string's scope judgements move
    # to the name its names lead to, members first and the concept's own last, so
    # on a tie in time the concept's own counts, as the old pooling preferred it
    def head(t):
        seen = set()
        while (n := nxt(t)) and t not in seen:
            seen.add(t)
            t = n
        return t
    moved = {}
    for term in sorted(new):
        sc = new[term].get("scope")
        if not sc:
            continue
        h = head(term)
        if h != term and not isinstance((current(new[term].get("name")) or {}).get("verdict"), dict):
            moved.setdefault(h, []).extend(sc)
            del new[term]["scope"]
            rep["scope moved to the concept"] += len(sc)
    for h, sc in moved.items():
        own = new.setdefault(h, {}).get("scope", [])
        new[h]["scope"] = ordered(sc + own)

    # 2. refused placements, from the placement file, onto the term's record
    for row in placement_rows or []:
        if not row.get("suggested"):
            continue
        term = row["term"]
        hit = None
        for t in (term, term[:1].upper() + term[1:]):
            seen = set()
            while t in new and t not in seen:                                 # follow the name (is_a lives there)
                seen.add(t)
                cj = current(new[t].get("name"))
                if not cj or not isinstance(cj["verdict"], str) or cj["verdict"] == t:
                    break
                t = cj["verdict"]
            if t in new:
                cj = current(new[t].get("name"))
                if not cj or cj["verdict"] == t:
                    hit = t
                    break
        if hit is None:
            rep["refused placement: term not found"] += 1
            notes["refused placement: term not found"].append(term)
            continue
        by = "claude-opus-5-5"            # every row was read by Claude; on a yes/no row it agreed with the model
        lst = new[hit].setdefault("is_a", {}).setdefault(row["suggested"], [])
        if any(j["verdict"] == "no" for j in lst):
            continue
        lst.append(J("yes", "deepseek-v4-flash_top_15", "placement: proposed among the ten nearest classes",
                     PLACEMENT_RUN, row.get("suggested iri")))
        lst.append(J("no", by, _why("placement refused", row.get("check"), row.get("reason")),
                     PLACEMENT_CHECK, row.get("suggested iri")))
        rep["refused placement written as is_a no"] += 1

    _edges(new, edge_verdicts or {}, rep, notes)
    _confirm(new, records, confirmations or [], rep, notes)
    rep["records"] = len(new)
    return new, rep, notes


def _edges(new: dict, verdicts: dict, rep: Counter, notes) -> None:
    """The reasoner's verdicts on the edges of the class hierarchy, as is_a no of
    the edge's child (curator, 2026-10-28: "Mach das so"). The hierarchy writes
    its labels title-cased; they are matched back to the term and, where the
    term already holds a judgement on the parent, to that target's spelling."""
    if not verdicts:
        return
    from wound_ontology.llm.category_vocab import declared_category
    from wound_ontology.utils.string_utils import smart_title
    by_title = {}
    for t, r in new.items():
        cj = current(r.get("name"))
        if not cj or cj["verdict"] == t:                 # a string that names its own concept
            by_title.setdefault(smart_title(t), []).append(t)
    when_ = verdicts["when"]
    for row in verdicts.get("rejected", []):
        terms = by_title.get(row["child"], [])
        if len(terms) != 1:
            k = "edge verdict: child is not a term" if not terms else "edge verdict: child ambiguous"
            rep[k] += 1
            notes[k].append((row["child"], row["parent"]))
            continue
        t, parent = terms[0], row["parent"]
        isa = new[t].setdefault("is_a", {})
        key = next((k for k in isa if smart_title(k) == parent), None) \
            or declared_category(parent) \
            or next(iter(by_title.get(parent, [])), None) or parent
        isa.setdefault(key, []).append(make(
            "no", "elk", f"the edge {row['child']} is_a {parent} ({row.get('source')}) made a class empty; "
                         "the reason was not recorded per edge before rule 89", when_))
        isa[key] = ordered(isa[key])
        rep[f"edge verdict as is_a no ({row.get('source')})"] += 1
        if any(j["by"] == "author" and j["verdict"] == "yes" for j in isa[key]):
            rep["edge verdict against an author's yes"] += 1
            notes["edge verdict against an author's yes"].append((t, key))


def _confirm(new: dict, records: dict, rows: list[dict], rep: Counter, notes) -> None:
    """The author's confirmations of the dry run (unterschiede.csv): where rule 89
    would answer differently, the author confirmed what held before, as a
    judgement of their own dated when they gave it."""
    import re as _re
    for r in rows:
        dec = r.get("Entscheidung (leer = wie heute)") or ""
        m = _re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", dec)
        if not dec.startswith("wie heute") or not m:
            rep["confirmation: row without a decision"] += 1
            notes["confirmation: row without a decision"].append(r.get("Nr"))
            continue
        when_, why = m.group(1), f"confirmed in the move to rule 89: as before (list of 2026-10-28, no. {r['Nr']})"
        t, c, art = r["Begriff"], r["Gegenstück"], r["Art"]
        if t not in new and art == "Geltungsbereich":
            new[t] = {}                       # a name that is only ever a target: its scope lives here now
        if t not in new:
            rep["confirmation: term not found"] += 1
            notes["confirmation: term not found"].append(t)
            continue
        if art == "Geltungsbereich":
            new[t].setdefault("scope", []).append(make(r["heute"], "author", why, when_))
        elif art == "Einordnung":
            new[t].setdefault("is_a", {}).setdefault(c, []).append(make("no", "author", why, when_))
        else:
            old = (records.get(t, {}).get("pairs") or {}).get(c) or {}
            v = (old.get("curator") or {}).get("verdict") or (old.get("check") or {}).get("verdict")
            if not v and records.get(t, {}).get("to") == c:
                v = "same_class"                                  # the term names it today
            if not v:
                v = (old.get("pass2") or old.get("pass1") or {}).get("verdict")
            if v not in PAIR_VERDICTS:
                rep["confirmation: no verdict holds today"] += 1
                notes["confirmation: no verdict holds today"].append((t, c))
                continue
            new[t].setdefault("pairs", {}).setdefault(c, []).append(make(v, "author", why, when_))
            if c in (new[t].get("is_a") or {}) and v != "narrower":
                new[t]["is_a"][c].append(make("no", "author", why, when_))
        rep["confirmed by the author as before"] += 1


def _is_spelling(term: str, to: str, method: str | None, pairs: dict) -> bool:
    """A name the old normaliser wrote that is only another way of writing the term."""
    if method not in ("string_norm", "pass0"):
        return False
    if ((pairs.get(to) or {}).get("curator") or {}).get("verdict") == "same_class":
        return False                                # someone judged it: a name
    from wound_ontology.utils.normalise import normalise
    return method == "pass0" or normalise(term).key == normalise(to).key


def _category_agent(e: dict) -> str:
    src = str(e.get("source", ""))
    if src.startswith("head rule"):
        return "end-word-category"
    return curator_agent(e.get("by"))


def _scope_judgement(term, src, v, when, J):
    parts = [v.get("reason") or v.get("section")]
    if src == "pass1":
        parts = [f"copied from the most similar decided term {v.get('near')!r} "
                 f"(cosine {v.get('score')}, margin {v.get('margin')})"]
        agent = "sapbert-neighbour"
    elif src == "pass2":
        agent = "deepseek-v4-flash"
    elif src == "curator":
        agent = curator_agent(v.get("by"))
        if agent == "author" and v.get("by") and v["by"] != "curator":
            parts.append(v["by"])
    else:
        agent = gate_rule_agent(v.get("by"))
        if v.get("by") and agent != "number-unit-rule":
            parts.append(f"list {v['by']}")
    w = when(v.get("when"), "scope", term, src, why_parts=parts)
    return J(v["verdict"], agent, _why(*parts), w)


def _placement_trail(cu: dict, rep: Counter) -> list[dict]:
    """The model's proposal, the second check and the author's acceptance, as judgements."""
    iri = cu.get("iri")
    yes = "yes" if cu["verdict"] == "narrower" else "same_class"
    check = str(cu.get("check") or "")
    out = []
    by = str(cu.get("by") or "")
    when_ = cu.get("when") if is_when(cu.get("when")) else PLACEMENT_CHECK
    if not check and "placement" not in by:
        # placed by the author directly (chat, review or judgement page): no model trail
        return [make(yes, curator_agent(by), _why(cu.get("reason"), by) or "placed by the author", when_, iri)]
    if "alternative" in check:
        out.append(make(yes, "claude-opus-5-5",
                        f"placement: chose this class among the offered ones ({check}); the model had proposed another",
                        PLACEMENT_CHECK, iri))
    else:
        proposed = "same_class" if "same ->" in check or "not same" in check else yes
        if proposed == "same_class" and yes == "yes":
            out.append(make("same_class", "deepseek-v4-flash_top_15", "placement: proposed as the same class", PLACEMENT_RUN, iri))
        else:
            out.append(make(yes, "deepseek-v4-flash_top_15", "placement: proposed among the ten nearest classes", PLACEMENT_RUN, iri))
        if check.startswith("verify"):
            m = re.match(r"verify: (\w+); Claude: (.*)", check)
            model_says, claude_says = (m.group(1), m.group(2)) if m else ("?", check)
            # on a pair, the statement's no is the nearest pair answer, different (2026-10-30)
            no = "no" if yes == "yes" else "different"
            out.append(make(yes if model_says == "yes" else no, "deepseek-v4-flash_single",
                            "placement: yes/no question" + ("" if model_says == "yes" or no == "no" else
                                                            "; answered no to 'means exactly the same thing'"),
                            PLACEMENT_CHECK, iri))
            out.append(make(yes, "claude-opus-5-5", f"placement: read row by row ({claude_says})", PLACEMENT_CHECK, iri))
        elif check.startswith("self-check"):
            out.append(make(yes, "claude-opus-5-5", f"placement: read row by row ({check})", PLACEMENT_CHECK, iri))
        else:
            rep["placement without a recorded check"] += 1
    out.append(make(yes, "author", _why(cu.get("reason"), cu.get("by")), when_, iri))
    return out
