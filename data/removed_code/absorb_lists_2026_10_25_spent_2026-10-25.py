#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TermMappingAndGate swallows the curation lists before they are deleted (rule 86).

    python -u scripts/absorb_lists_2026_10_25.py            # dry run
    python -u scripts/absorb_lists_2026_10_25.py --write

The curator, 2026-10-25: "termmappingandgate hält alle entscheidungen und
schluckt die listen wenn listeneinträge im termmapping fehlen. alle listen
werden gelöscht. die statistikbegriffe sind teil des mapping." Nothing a list
decides today may be lost or change silently, so:

1. Every list entry without a record gets one: the keyword blocklist (the
   statistics words) `out`, the keyword whitelist `in`, each with the `rule`
   source naming the list; a suspicious keyword gets a record with no verdict.
   An entry with a verdict of its own keeps it -- a list never overrides one.
2. What the keyword lists decide TODAY about terms in the store becomes a rule
   verdict on that term, naming the keyword: 230 terms with no verdict that a
   blocked keyword keeps out (`Standardized form`), and 41 that a whitelisted
   keyword lets in over the old blocklist entry (`Maggot debridement therapy`).
   The old rule verdict moves to `rule_history`.
3. The measurement rule (`noise_rule`, a number with a unit) gives `out` to any
   term that has no verdict and matches it.

Then the view through TermMappingAndGate alone must equal the view through the
Blocker, term for term; the script checks that before it saves.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

WHEN = "2026-10-25T23:00:00"


def view_names(store) -> set[str]:
    names = set()
    for _, ents in store.view(mapped=True, include_rejected=True):
        for e, attrs in ents.items():
            names.add(e)
            names.update(t.split(":", 1)[1].strip() for t in attrs if ":" in t)
    return names


def main(argv: list[str]) -> int:
    from config.blocklist import KEYWORD_BLOCKLIST, METHODOLOGY_BLOCKLIST
    from config.suspicious_list import SUSPICIOUS_KEYWORDS
    from config.whitelist import KEYWORD_WHITELIST, WHITELIST
    from wound_ontology.llm.category_vocab import declared_category
    from wound_ontology.mappers.term_mapping_and_gate import noise_rule
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.store.term_lists import _starts_a_word

    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    blocker = o.cleaner.blocker
    names = {n for n in view_names(o.store) if declared_category(n) is None}
    before = {n for n in names if o.cleaner._is_blocked(n)}

    lower = {t.lower(): t for t in gt.records}
    report = {"records added": 0, "exact entries without a verdict": 0,
              "keyword out": [], "keyword in": [], "noise out": []}

    # 1. every list entry has a record
    for entries, verdict, src in ((METHODOLOGY_BLOCKLIST, "out", "METHODOLOGY_BLOCKLIST"),
                                  (WHITELIST, "in", "WHITELIST"),
                                  (KEYWORD_BLOCKLIST, "out", "KEYWORD_BLOCKLIST"),
                                  (KEYWORD_WHITELIST, "in", "KEYWORD_WHITELIST"),
                                  (SUSPICIOUS_KEYWORDS, None, "SUSPICIOUS_KEYWORDS")):
        for entry in sorted(entries):
            key = lower.get(entry.lower())
            if key is None:
                key = entry
                gt.record(key)
                lower[key.lower()] = key
                report["records added"] += 1
            term = gt.resolve(key)
            if verdict and not gt.own_gate_verdict(term)[0]:
                if src in ("METHODOLOGY_BLOCKLIST", "WHITELIST"):
                    report["exact entries without a verdict"] += 1
                gt.gate(term, rule={"verdict": verdict, "by": src, "when": WHEN})

    # Decide first, write after: every gate write drops the index the next
    # read would rebuild, so reading between writes costs one rebuild each.
    gt._gate_idx = None
    pool = sorted(set(t for t in gt.records if not gt.is_alias(t)) | names)
    eff = {t: gt.effective_gate_verdict(t) for t in pool}
    white = lambda t: blocker.white_terms.match(t) or blocker.white_kw.match(t)  # noqa: E731
    writes: list[tuple[str, dict, bool]] = []

    # 3. the measurement rule for whatever has no verdict (a whitelist entry or
    #    keyword outranked it in the Blocker, so it does here)
    for t in pool:
        if not eff[t][0] and noise_rule(t) and not white(t):
            writes.append((t, {"verdict": "out", "by": "noise rule: a number with a unit",
                               "when": WHEN}, False))
            report["noise out"].append(t)

    # 2. what the keywords decide today, written on the term
    noise = set(report["noise out"])
    for n in sorted(names - noise):
        verdict, source = eff[n]
        if verdict and source != "rule":
            continue                                  # a pass or the curator decides it
        kw_in = blocker.white_kw.match(n)
        if not verdict and not kw_in and blocker.block_kw.match(n):
            kw = next(k for k in sorted(KEYWORD_BLOCKLIST, key=len, reverse=True)
                      if _starts_a_word(k, n.strip().lower()))
            writes.append((n, {"verdict": "out", "by": f"KEYWORD_BLOCKLIST: {kw}", "when": WHEN}, False))
            report["keyword out"].append(n)
        elif not verdict and not white(n) and blocker.terms.match(n):
            # the entry's verdict sits on another spelling; this one had none
            writes.append((n, {"verdict": "out", "by": "METHODOLOGY_BLOCKLIST", "when": WHEN}, False))
            report["keyword out"].append(n)
        elif verdict == "out" and white(n):
            writes.append((n, {"verdict": "in", "by": "KEYWORD_WHITELIST (outranked the blocklist entry)",
                               "when": WHEN}, True))
            report["keyword in"].append(n)

    for t, entry, keep_old in writes:
        rec = gt.gate_record(t)
        if keep_old and rec.get("rule"):
            rec.setdefault("rule_history", []).append(rec["rule"])
        rec["rule"] = entry
    gt._gate_idx = None
    after = {n for n in names if gt.effective_gate_verdict(n)[0] == "out"}
    print(f"[absorb] records added {report['records added']}; exact entries that had no verdict "
          f"{report['exact entries without a verdict']}; keyword out {len(report['keyword out'])}; "
          f"keyword in {len(report['keyword in'])}; noise out {len(report['noise out'])}")
    print(f"[absorb] the view through TermMappingAndGate alone differs from the Blocker's on "
          f"{len(before ^ after)} name(s): {sorted(before ^ after)[:10]}")
    if before ^ after:
        for n in sorted(before ^ after)[:25]:
            print("   ", repr(n), "blocker:", n in before, "| gate:", gt.effective_gate_verdict(n),
                  "| white:", blocker.white_terms.match(n) or blocker.white_kw.match(n),
                  "| noise:", noise_rule(n), "| kw block:", blocker.block_kw.match(n))
        return 1
    if "--write" not in argv:
        print("[absorb] dry run; --write to save")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_absorb_lists_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[absorb] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt._dirty(); gt.save()
    g2 = Orchestrator().term_mapper._term_mapping
    after2 = {n for n in names if g2.effective_gate_verdict(n)[0] == "out"}
    print(f"[absorb] read back: differs on {len(before ^ after2)} name(s)")
    return 1 if before ^ after2 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
