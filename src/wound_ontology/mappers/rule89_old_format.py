"""The term dict as it was before rule 89 (2026-10-28), read for the migration only.

`old_records(raw)` turns any of the five old shapes into the last old one, which
`rule89_migration.migrate` translates. Kept verbatim from the class it came from
(data/backup/rule89_code/term_mapping_and_gate_before_rule89.py), so an old file
or an old test fixture reads exactly as it did.
"""
from __future__ import annotations

SPELLING = "spelling"
PAIR_VERDICTS = ("same_class", "narrower", "broader", "different")
IS_A = "is_a"
DECIDED = "decided"


def target_of(rec: dict) -> str | None:
    """The one term `to` names, or None -- also for a term split by category,
    whose `to` names one term per category (rule 87)."""
    to = rec.get("to")
    return to if isinstance(to, str) else None


def split_of(rec: dict) -> dict[str, str]:
    """`{category: name}` for a term split by category, else empty (rule 87)."""
    to = rec.get("to")
    return dict(to) if isinstance(to, dict) else {}


def decided_is_a(rec: dict) -> tuple[str, dict] | None:
    """`(category, entry)` of the record's decided `is_a` cell, or None."""
    for triple, entry in (rec.get("relations") or {}).items():
        pred, _, tgt = triple.partition(":")
        if pred.strip() == IS_A and isinstance(entry, dict) and entry.get("status") == DECIDED:
            return tgt.strip(), entry
    return None


def _set_decided_is_a(rec: dict, category: str, entry: dict) -> None:
    """Put `entry` on `is_a: <category>`, removing any other decided `is_a`."""
    rel = rec.setdefault("relations", {})
    for triple in [t for t, e in rel.items()
                   if t.partition(":")[0].strip() == IS_A and isinstance(e, dict)
                   and e.get("status") == DECIDED]:
        del rel[triple]
    rel[f"{IS_A}: {category}"] = {"status": DECIDED, **entry}




def _load(raw: dict) -> dict[str, dict]:
    """Read any of the four formats this file has had.

    A flat `term -> canonical` file, a record with `pass1`/`pass2`/
    `refused` at the TERM level, or a pair with a lock `refused` beside its
    verdicts is migrated in memory and written in the current shape the
    next time anything saves. No separate migration step
    exists to be forgotten -- which is the same reason the caches are now
    read through `pass_cache` rather than off disk.
    """
    records: dict[str, dict] = {}
    for term, value in raw.items():
        if not isinstance(value, dict):                      # v1: flat
            records[term] = {"to": value, "pairs": {}}
            continue
        if SPELLING in value:                                # an alias: nothing to migrate
            records[term] = dict(value)
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
        # v3 (until 2026-10-25): a lock `refused` beside the verdicts. The
        # verdict says it now; a lock that somehow still has none reads as
        # the curator's `different`, which is what every such lock meant.
        for j in pairs.values():
            lock = j.pop("refused", None)
            if not lock:
                continue
            if (j.get("curator") or {}).get("verdict") not in PAIR_VERDICTS:
                j["curator"] = {"verdict": "different", "reason": lock.get("reason", ""),
                                "by": lock.get("by", "curator"), "when": lock.get("when")}
            j["lock_history"] = j.get("lock_history", []) + [lock]
        rec["pairs"] = pairs
        records[term] = rec
    # v4 (until 2026-10-25): a name section on the chosen term. What it said
    # is the curator's `same_class` on each loser's pair onto the name, with
    # the name's reason; earlier choices it had superseded stay as history.
    for term, rec in list(records.items()):
        name = rec.pop("name", None)
        if not name:
            continue
        for loser in name.get("instead_of", []):
            lr = records.get(loser)
            if lr is None or SPELLING in lr or loser == term:
                continue
            j = lr.setdefault("pairs", {}).setdefault(term, {})
            cur = j.get("curator") or {}
            if cur.get("verdict") != "same_class":
                if cur:
                    j["curator_history"] = j.get("curator_history", []) + [cur]
                j["curator"] = {"verdict": "same_class", "by": name.get("by", "curator"),
                                "reason": name.get("reason", "") or "chose this name",
                                "when": name.get("when")}
        if name.get("history"):
            rec["name_history"] = rec.get("name_history", []) + name["history"]
    # v5 (until 2026-10-26, rule 87): a `category` section beside the
    # relations, and a `senses` section beside `to`. The category IS the
    # `is_a` cell it settles; the senses ARE where the term points, one
    # name per category. A term that pointed at one name AND had senses
    # would lose a decision either way, so it stops the load.
    moved = {"category": 0, "senses": 0}
    for term, rec in records.items():
        cat = rec.pop("category", None)
        if isinstance(cat, dict) and cat.get("verdict"):
            entry = {k: v for k, v in cat.items() if k != "verdict"}
            if entry.get("history"):
                entry["history"] = [dict(h) for h in entry["history"]]
            _set_decided_is_a(rec, cat["verdict"], entry)
            moved["category"] += 1
        senses = rec.pop("senses", None)
        if senses:
            if isinstance(rec.get("to"), str):
                raise ValueError(f"[mapping] {term!r} maps onto {rec['to']!r} and also "
                                 f"splits into {senses}; one of the two has to go")
            rec["to"] = dict(senses)
            moved["senses"] += 1
    if any(moved.values()):
        print(f"[mapping] rule 87: {moved['category']:,} category section(s) moved "
              f"into relations as a decided is_a, {moved['senses']:,} senses "
              f"section(s) into `to`")
    return records



old_records = _load
