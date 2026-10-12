"""Split the concept store into evidence and decisions (rule 51). One-time.

Until 2026-09-27 the concept store was rewritten in place -- pass 0, the
mapping apply, the sense split -- and kept a `decisions` record of its own
beside the PMIDs: rejected entities, rejected cells and a global rename book.
That made two files decide things about terms, and made what an abstract
actually said something that had to be carried through every rename.

After this script:

* the CONCEPT STORE holds evidence only: per PMID, the entities and relations
  as the earliest surviving spelling has them -- the 2026-09-22 snapshot taken
  before the first mapping apply, because the extractor's literal strings for
  these 6,029 abstracts were never kept -- stamped `evidence_from`;
* the TERM DICT holds every decision about a term: the store's rename book
  becomes `spelling` aliases (plus the renames made before target renames were
  recorded, reconstructed and marked so), rejected entities become `rejected`,
  rejected cells become `relations`.

Nothing is written unless the new view reproduces today's store exactly: every
PMID, every name, every triple, every value -- both with the rejected entities
and cells hidden and with them shown. Both files are backed up first and read
back from disk after.

    python scripts/p4_split_evidence_and_decisions.py [--write]
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

SNAPSHOT = ROOT / "data" / "backup" / "concept_store_pre_mapping_2026-09-22.json"
SOURCE = ("snapshot 2026-09-22 (concept_store_pre_mapping_2026-09-22.json): the "
          "earliest spelling kept; the extractor's literal strings for these "
          "abstracts were never stored")
RECONSTRUCTED = ("reconstructed 2026-09-27: renamed as a relation target before "
                 "target renames were recorded")


class _Memory:
    def __init__(self, data):
        self.data = data

    def load_latest_json(self, _):
        return self.data

    def save_as_json(self, data, _):
        self.data = data


def _names(doc: dict) -> set[str]:
    ents = doc.get("entities", {})
    out = set(ents)
    for attrs in ents.values():
        out.update(t.split(":", 1)[1].strip() for t in attrs if ":" in t)
    return out


def _compare(label: str, got: dict, want: dict) -> list:
    """Every difference between two {key: {entity: {triple: value}}} maps."""
    problems = []
    for key in sorted(set(got) | set(want)):
        g, w = got.get(key), want.get(key)
        if g != w:
            problems.append((label, key,
                             sorted(set(g or {}) ^ set(w or {}))[:3] or
                             [(e, g[e], w[e]) for e in g if e in w and g[e] != w[e]][:2]))
    return problems


def main(argv: list[str]) -> int:
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import (
        DECISION_SECTIONS, SPELLING, TermMappingAndGate)
    from wound_ontology.store.concept_store import ConceptStore, effective_records

    write = "--write" in argv
    dm = DataManager()
    store_file = sorted((ROOT / "data" / "cache").glob("concept_store_*.json"))[-1]
    terms_file = sorted((ROOT / "data" / "cache").glob("term_mapping_*.json"))[-1]
    current = json.loads(store_file.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    decisions = current.get("decisions")
    if decisions is None:
        raise SystemExit(f"[split] {store_file.name} has no `decisions` record: "
                         f"already split, nothing to do.")
    print(f"[split] store {store_file.name}, terms {terms_file.name}, "
          f"snapshot {SNAPSHOT.name}")

    # ── the evidence ─────────────────────────────────────────────────────────
    evidence: dict = {}
    for key, rec in current.items():
        if key == "decisions":
            continue
        if key not in snapshot:
            raise SystemExit(f"[split] {key} is in the store and not in the snapshot; "
                             f"its evidence would have to come from somewhere else")
        kept = {k: v for k, v in rec.items()
                if k not in ("entities", "as_extracted", "as_extracted_from")}
        evidence[key] = {"entities": copy.deepcopy(snapshot[key]["entities"]),
                         **kept, "evidence_from": SOURCE}

    # ── the decisions, onto the term dict ────────────────────────────────────
    terms = TermMappingAndGate(dm, file_name="term_mapping")
    records = terms.records
    report = {"aliases from the rename book": 0, "aliases reconstructed": 0,
              "rejected entities": 0, "rejected cells": 0}
    clashes = []
    # A book entry whose OLD name is a name the store holds today records a
    # rename that a later decision reversed -- 27 on 2026-09-27: pass 0's
    # `histopathological -> histopathologic` before rule 49 turned it round,
    # hyphenations undone, `action potential` repaired. As a log line it was
    # true; as an alias it would re-spell today's name into the one it
    # replaced. It stays on record as history on the current name.
    current_names = set().union(*(_names(r) for k, r in current.items() if k != "decisions"))
    report["reversed renames kept as history"] = 0
    for old, entry in decisions.get("renamed", {}).items():
        if old in current_names:
            terms.record(old).setdefault("spelling_reversed", []).append(dict(entry))
            report["reversed renames kept as history"] += 1
            continue
        rec = records.get(old)
        if rec is not None and any(rec.get(s) for s in DECISION_SECTIONS):
            clashes.append((old, entry["to"], [s for s in DECISION_SECTIONS if rec.get(s)]))
            continue
        records[old] = {SPELLING: dict(entry)}
        report["aliases from the rename book"] += 1
    terms._dirty()

    # A snapshot string whose recorded chain does not end where the store
    # now has it: a target renamed before target renames were recorded. The
    # alias goes on the END of its chain, never over a recorded step.
    now_name: dict[str, set[str]] = {}
    for key, rec in evidence.items():
        cur_names = _names(current[key])
        for old in _names(rec):
            end = terms.resolve(old)
            if end in cur_names:
                continue
            candidates = [n for n in cur_names
                          if n.lower() == end.lower() or _key(n) == _key(end)]
            now_name.setdefault(end, set()).update(candidates[:1] if len(candidates) == 1
                                                   else ["?AMBIGUOUS?"] + candidates)
    ambiguous = {e: n for e, n in now_name.items() if len(n) != 1 or "?AMBIGUOUS?" in n}
    if ambiguous:
        raise SystemExit(f"[split] {len(ambiguous)} string(s) cannot be traced to one "
                         f"current name: {list(ambiguous.items())[:5]}")
    for end, (target,) in ((e, tuple(n)) for e, n in now_name.items()):
        if terms.spell(end, target, by=RECONSTRUCTED):
            report["aliases reconstructed"] += 1

    for name, verdict in decisions.get("entity_verdicts", {}).items():
        terms.record(name)["rejected"] = verdict
        report["rejected entities"] += 1
    for name, cells in decisions.get("cell_verdicts", {}).items():
        terms.record(name).setdefault("relations", {}).update(cells)
        report["rejected cells"] += len(cells)
    terms._dirty()
    for k, v in report.items():
        print(f"[split] {k}: {v:,}")
    if clashes:
        raise SystemExit(f"[split] {len(clashes)} renamed string(s) still carry "
                         f"decisions in the term dict: {clashes[:5]}")

    # ── the proof: the view is today's store ─────────────────────────────────
    view = ConceptStore(_Memory(evidence), "concept_store", terms=terms)
    view._live_mapping = False                    # today's store has no mapping applied
    got_all = dict(view.view(mapped=False, include_rejected=True))
    want_all = {k: v["entities"] for k, v in current.items() if k != "decisions"}
    got_eff = dict(view.view(mapped=False))
    want_eff = dict(effective_records(current))
    problems = (_compare("with rejections shown", got_all, want_all)
                + _compare("as downstream reads it", got_eff, want_eff))
    cells = sum(len(a) for ents in want_all.values() for a in ents.values())
    if problems:
        for p in problems[:10]:
            print(f"[split]   MISMATCH {p}")
        raise SystemExit(f"[split] the view does not reproduce the store: "
                         f"{len(problems)} record(s) differ. Nothing written.")
    print(f"[split] the view reproduces today's store exactly: {len(want_all):,} "
          f"records, {cells:,} cells, both with and without the rejections.")
    if not write:
        print("[split] dry run -- nothing written. Pass --write.")
        return 0

    stamp = date.today()
    for src, name in ((store_file, f"concept_store_before_evidence_split_{stamp}.json"),
                      (terms_file, f"term_mapping_before_evidence_split_{stamp}.json")):
        shutil.copy2(src, ROOT / "data" / "backup" / name)
        print(f"[split] backed up {src.name} -> {name}")
    dm.save_as_json(evidence, "concept_store")
    terms.save()

    from wound_ontology.orchestrator import Orchestrator
    fresh = Orchestrator()
    fresh.store._live_mapping = False
    again = _compare("read back", dict(fresh.store.view(mapped=False, include_rejected=True)),
                     want_all) + _compare("read back, effective",
                                          dict(fresh.store.view(mapped=False)), want_eff)
    if again or "decisions" in fresh.store.dict:
        raise RuntimeError(f"[split] the files on disk do not reproduce the store: "
                           f"{again[:3]}")
    print(f"[split] written and read back from disk at {datetime.now():%H:%M}; the view "
          f"reproduces the store exactly.")
    return 0


def _key(name: str) -> str:
    from wound_ontology.utils.normalise import normalise
    return normalise(name).key


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
