"""Rule 58 for the abbreviations the strict test missed (mixed case: `MSC-Exo`, `i-PRF`).

    python -u scripts/apply_abbreviation_wide.py [--write]

Curator, 2026-10-02: "there are still abbreviations like MSC-Exo and i-PRF in
the term list" -- then "keep microRNA send the rest out". Reads the report of
`expand_abbreviations.py --wide` (one token holding a run of two or more
capitals, not caught by the strict test) and applies the curator's rule of
2026-09-30, every row read by Claude on 2026-10-02:

  expand     one full form, spelled letter by letter -> map onto it, except
             EXPAND_FIX, where the shortest-match lost or garbled a word
  unspelled  one full form that failed the letter check -> map it as the
             abstract writes it, except UNSPELLED_OUT (a sentence fragment, or
             a form that would need guessing) and UNSPELLED_FIX
  ambiguous  KEEP: one concept spelled differently -> map onto that form;
             every other one -> out
  undefined  no abstract defines it -> out, except KEEP_UNDEFINED

A full form that still holds an abbreviation (`soluble RAGE`) is left to the
inside-the-name step (`expand_abbreviations_inside.py`).

Dry by default; `--write` backs up the term dict, saves once, reads back.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

SRC = ROOT / "output" / "abbreviation_expansion_wide_2026-10-02.json"
BY = "rule 58, widened test (curator, 2026-10-02)"

EXPAND_FIX = {
    "sTBI": "severe traumatic brain injury",                    # match dropped "severe"
    "sST2": "soluble suppression of tumorigenicity 2",          # match dropped "soluble"
    "beta-TCP": "beta-tricalcium phosphate",                    # text read as "betaeta Tri-calcium"
}
UNSPELLED_OUT = {"DFU-Ab", "PG-i", "PG-ni", "SPARC‑HG", "Stand-scES", "aBEF", "wPU"}
UNSPELLED_FIX = {"PrUMS": "pressure ulcer monitoring system"}
KEEP = {
    "NF-kappaB": "nuclear factor kappa-B",
    "NPWTi-d": "negative pressure wound therapy with instillation and dwell time",
    "rhEGF": "recombinant human epidermal growth factor",
    "WIfI": "Wound, Ischemia, and foot Infection",
    "GelMA": "gelatin methacryloyl",
}
KEEP_UNDEFINED = {"microRNA"}


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.normalise import normalise

    write = "--write" in argv
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    names_by_key = defaultdict(Counter)
    for _, ents in p.store.view(mapped=False):
        for name in ents:
            names_by_key[normalise(name).key][name] += 1

    def target(form: str) -> str:
        got = names_by_key.get(normalise(form).key)
        return got.most_common(1)[0][0] if got else normalise(form).name

    for table, section in ((EXPAND_FIX, "expand"), (UNSPELLED_OUT | set(UNSPELLED_FIX), "unspelled"),
                           (KEEP, "ambiguous"), (KEEP_UNDEFINED, "undefined")):
        missing = sorted(set(table) - {r["term"] for r in rows[section]})
        if missing:
            raise SystemExit(f"[abbrW] not in the {section} rows: {missing}")

    maps, outs = {}, {}
    for r in rows["expand"]:
        t = r["term"]
        to = target(EXPAND_FIX[t]) if t in EXPAND_FIX else r["to"]
        maps[t] = (to, f"defined as {r['as written']!r} in PMID {', '.join(r['defined in'][:3])}"
                       + (" (corrected: the match lost a word)" if t in EXPAND_FIX else ""))
    for r in rows["unspelled"]:
        t = r["term"]
        if t in UNSPELLED_OUT:
            outs[t] = f"no usable full form (abstract wrote {r['as written']!r})"
        elif t in UNSPELLED_FIX:
            maps[t] = (target(UNSPELLED_FIX[t]), "full form as the abstracts write it out")
        else:
            maps[t] = (r["to"], f"full form as written: {r['as written']!r}")
    for r in rows["ambiguous"]:
        t = r["term"]
        if t in KEEP:
            maps[t] = (target(KEEP[t]), "abstracts spell one concept differently: " + " / ".join(r["forms"]))
        else:
            outs[t] = "abstracts define it as different things: " + " / ".join(r["forms"])
    for r in rows["undefined"]:
        if r["term"] not in KEEP_UNDEFINED:
            outs[r["term"]] = "abbreviation only; no abstract that uses it defines it"

    refused = [t for t, (to, _) in maps.items() if gt.is_refused(t, to)]
    for t in refused:
        maps.pop(t)
    print(f"[abbrW] map {len(maps)}  e.g. {list(maps.items())[:5]}")
    print(f"[abbrW] out {len(outs)}  e.g. {list(outs)[:12]}")
    print(f"[abbrW] kept as they are: {sorted(KEEP_UNDEFINED)}; skipped as refused pairs: {refused}")
    if not write:
        print("[abbrW] dry run; --write to apply")
        return 0

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_abbreviation_wide_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[abbrW] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    for t, (to, why) in maps.items():
        rec = gt.record(t)
        rec.update({"to": to, "confidence": 1.0, "method": "curator"})
        rec.pop("retired", None)
        gt.judge(t, to, curator={"verdict": "same_class", "when": when, "by": BY, "reason": why})
    for t, why in outs.items():
        gt.gate(t, curator={"verdict": "out", "when": when, "by": BY, "reason": why})
    gt._dirty()
    gt.save()
    print(f"[abbrW] gate lists re-exported: {p.export_gate_lists()}")

    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    g2 = TermMappingAndGate(DataManager(), file_name="term_mapping")
    lost = [t for t, (to, _) in maps.items() if g2.data.get(t) != to]
    lost += [t for t in outs if g2.peek_gate(g2.resolve(t)).get("curator", {}).get("verdict") != "out"]
    if lost:
        raise RuntimeError(f"{len(lost)} decision(s) did not land: {lost[:10]}")
    print(f"[abbrW] written and read back: {len(maps)} mapped, {len(outs)} out of scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
