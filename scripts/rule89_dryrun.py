"""Dry run of rule 89: translate the term dict, date what has no time, and compare.

    python -u scripts/rule89_dryrun.py

Writes nothing the pipeline reads. Output: data/review/rule89_dryrun_<date>/
  report.json  -- counts, every reconstruction, every difference with examples
  report.md    -- the same for the curator, in plain words
and the translated records to the session scratch path given as argv[1], if any.

Compared, per question, old reading against new: the name of every term, the
spelling of every alias, the scope of every concept (the old reading pools a
concept's spellings and members by precedence; the new one pools their
judgements by time and lets the author's last one count), the placements, the
decided categories and the pairs kept apart.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from wound_ontology.mappers.judgements import AGENTS, current, is_when, ordered  # noqa: E402
from wound_ontology.mappers.rule89_migration import migrate  # noqa: E402
from wound_ontology.mappers.term_mapping_and_gate_v88 import APART, TermMappingAndGate  # noqa: E402  (the class before rule 89)

CURRENT = sorted((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"))[-1]
TODAY = dt.date.today().isoformat()
#: model runs, from the logs in output/ (p4_readjudicate, p4_second_opinion*)
PASS1_RUNS = ["2026-09-22"]
PASS2_RUNS = ["2026-09-23", "2026-09-27", "2026-09-28"]


def load(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not any(isinstance(v, dict) for v in list(raw.values())[:2000]):
        return {}                                   # a flat file of the first days: no judgements
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        return TermMappingAndGate._load(raw)


class Dating:
    """When a judgement first appears in the saved states of the file, mapped onto
    the model run that wrote it where the logs name one."""

    def __init__(self, records: dict):
        self.need = set()
        for t, r in records.items():
            if "spelling" in r:
                continue
            to = r.get("to")
            if isinstance(to, str):
                self.need.add(("to", t, to))
            for c, pv in (r.get("pairs") or {}).items():
                for slot in ("pass1", "pass2"):
                    if slot in pv:
                        self.need.add((slot, t, c, pv[slot]["verdict"]))
                cu = pv.get("curator") or {}
                if cu and not is_when(cu.get("when")):
                    self.need.add(("pair", t, c, "curator", cu["verdict"]))
        self.first: dict[tuple, str] = {}
        cache = ROOT / "output" / f"rule89_dating_{CURRENT.stem}.json"
        if cache.exists():
            saved = json.loads(cache.read_text(encoding="utf-8"))
            self.first = {tuple(k): v for k, v in saved}
            print(f"[dating] {len(self.first):,} first-seen times read from {cache.name}", flush=True)
            return
        files = sorted(set((ROOT / "data" / "backup").glob("term_mapping*.json"))
                       | set((ROOT / "data" / "cache").glob("term_mapping_2026-*.json")),
                       key=lambda p: p.stat().st_mtime)
        for f in files:
            stamp = dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")
            old = load(f)
            if not old:
                continue
            left = [k for k in self.need if k not in self.first]
            if not left:
                break
            for k in left:
                kind, t = k[0], k[1]
                r = old.get(t)
                if not r or "spelling" in r:
                    continue
                if kind == "to":
                    hit = r.get("to") == k[2]
                elif kind in ("pass1", "pass2"):
                    hit = ((r.get("pairs") or {}).get(k[2]) or {}).get(kind, {}).get("verdict") == k[3]
                else:
                    hit = (((r.get("pairs") or {}).get(k[2]) or {}).get("curator") or {}).get("verdict") == k[4]
                if hit:
                    self.first[k] = stamp
            print(f"[dating] {f.name}: {len(self.first):,} of {len(self.need):,} dated", flush=True)
        cache.write_text(json.dumps([[list(k), v] for k, v in self.first.items()], ensure_ascii=False), encoding="utf-8")

    def when(self, kind, *key, default_after=None):
        k = (kind, *key)
        seen = self.first.get(k)
        if kind in ("pass1", "pass2"):
            runs = PASS1_RUNS if kind == "pass1" else PASS2_RUNS
            if seen:
                before = [r for r in runs if r <= seen[:10]]
                if before:
                    return before[-1], f"run of {before[-1]}, from the logs"
                return seen[:10], "first saved state holding it"
            return runs[-1], "run date from the logs; not found in any saved state"
        if seen:
            return seen[:10], "first saved state holding it"
        return TODAY, "time not recorded; on record by " + TODAY


def concept_of(term, recs_old):
    r = recs_old.get(term) or {}
    seen = set()
    while "spelling" in r and term not in seen:
        seen.add(term); term = r["spelling"]["to"]; r = recs_old.get(term) or {}
    to = r.get("to")
    return to if isinstance(to, str) else term


def main() -> int:
    out_dir = ROOT / "data" / "review" / f"rule89_dryrun_{TODAY}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[rule89] reading {CURRENT.name}", flush=True)
    old = load(CURRENT)
    tm = TermMappingAndGate.__new__(TermMappingAndGate)
    tm._dm, tm._file_name, tm._records = None, CURRENT.stem, old
    tm._flat = tm._gate_idx = tm._members_idx = None

    dating = Dating(old)
    rows = json.loads((ROOT / "data" / "review" / "placement_merged_2026-10-01.json").read_text())["rows"]
    import csv
    confirmations = []
    for name in ("unterschiede.csv", "unterschiede_2.csv"):     # the author's two confirmed lists
        conf_path = ROOT / "data" / "review" / "rule89_dryrun_2026-10-28" / name
        confirmations += list(csv.DictReader(conf_path.open(encoding="utf-8")))
    edges_f = sorted((ROOT / "data" / "cache").glob("class_hierarchy_edge_verdicts_*.json"))
    edge_verdicts = json.loads(edges_f[-1].read_text(encoding="utf-8")) if edges_f else {}
    # the edge verdicts stay with the edges (2026-10-28): a run result, not a judgement on a term
    new, rep, notes = migrate(old, dating, rows, confirmations)

    diff = defaultdict(list)

    def goes_to(r, t):
        """Where a string points now: its spelling, else its name; None if itself."""
        for q in ("spelling", "name"):
            cj = current(r.get(q))
            if cj and cj["verdict"] != t:
                return cj["verdict"]
        return None

    # where every string goes (spelling or name)
    for t, r in new.items():
        o = old.get(t, {})
        o_to = o["spelling"]["to"] if "spelling" in o else o.get("to")
        n_to = goes_to(r, t)
        if n_to != o_to:
            diff["spelling or name"].append((t, o_to, n_to))
    # scope per concept: pooled judgements of the concept and everything naming it
    pooled = defaultdict(list)
    for t, r in new.items():               # members first, the concept's own last: on a tie the concept's own counts
        if r.get("scope") and concept_of(t, old) != t:
            pooled[concept_of(t, old)].extend(r["scope"])
    for t, r in new.items():
        if r.get("scope") and concept_of(t, old) == t:
            pooled[t].extend(r["scope"])
    for c, js in pooled.items():
        js = ordered(js)          # the order the stored lists have
        n = (current(js) or {}).get("verdict")
        o = tm.effective_gate_verdict(c)[0]
        if (n or None) != (o if o in ("in", "out") else None) and not (n == "undecided" and o not in ("in", "out")):
            diff["scope"].append((c, o, n))
    # placements, categories, pairs kept apart
    old_place = set(tm.placements())
    new_place = set()
    for t, r in new.items():
        if goes_to(r, t) is not None:
            continue
        for tgt, js in (r.get("is_a") or {}).items():
            cj = current(js)
            if cj and cj["verdict"] == "yes" and any(j.get("iri") for j in js) and tm.effective_gate_verdict(t)[0] != "out":
                new_place.add((t, tgt))
    diff["placements"] = [("old only", x) for x in sorted(old_place - new_place)[:50]] + \
                         [("new only", x) for x in sorted(new_place - old_place)[:50]]
    rep["placements old"], rep["placements new"] = len(old_place), len(new_place)
    rep["placements only old"], rep["placements only new"] = len(old_place - new_place), len(new_place - old_place)
    from wound_ontology.llm.category_vocab import declared_category
    old_cat = {t: v["verdict"] for t, v in tm.categories().items()}
    new_cat = {}
    for t, r in new.items():
        for tgt, js in (r.get("is_a") or {}).items():
            cj = current(js) or {}
            # a decided category names a BFO category and carries no IRI; an is_a
            # with an IRI is a placement, even under a BFO class
            if declared_category(tgt) and cj.get("verdict") == "yes" and any(not j.get("iri") for j in js):
                new_cat.setdefault(t, []).append(tgt)
    for t in set(old_cat) | set(new_cat):
        if [old_cat.get(t)] != (new_cat.get(t) or [None]):
            diff["category"].append((t, old_cat.get(t), new_cat.get(t)))
    old_apart = {(t, c) for t, r in old.items() if "spelling" not in r
                 for c in (r.get("pairs") or {}) if tm.is_refused(t, c)}
    new_apart = {(t, c) for t, r in new.items() for c, js in (r.get("pairs") or {}).items()
                 if (cj := current(js)) and AGENTS[cj["by"]]["rank"] == "author" and cj["verdict"] in APART}
    # a placement the author accepted keeps the term from merging into its parent
    new_apart |= {(t, c) for t, r in new.items() for c, js in (r.get("is_a") or {}).items()
                  if (cj := current(js)) and AGENTS[cj["by"]]["rank"] == "author" and cj["verdict"] == "yes"
                  and cj.get("iri")}
    diff["kept apart"] = [("old only", x) for x in sorted(old_apart - new_apart)[:50]] + \
                         [("new only", x) for x in sorted(new_apart - old_apart)[:50]]
    rep["kept apart only old"], rep["kept apart only new"] = len(old_apart - new_apart), len(new_apart - old_apart)

    report = {"source": CURRENT.name, "counts": dict(rep),
              "differences": {k: {"n": len(v), "examples": v[:40]} for k, v in diff.items()},
              "notes": {k: v[:40] for k, v in notes.items()},
              "by_agent": dict(Counter(j["by"] for r in new.values() for q in r.values()
                                       for js in (q.values() if isinstance(q, dict) else [q]) for j in js))}
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps({"format": "rule 89", "agents": AGENTS, "terms": new}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v["n"] for k, v in report["differences"].items()}, indent=1))
    print(json.dumps(report["counts"], indent=1, ensure_ascii=False))
    print(f"[rule89] report -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
