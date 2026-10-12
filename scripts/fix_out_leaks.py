"""Unmap the abbreviations rule 58 put out of scope, so the out stays on them.

    python -u scripts/fix_out_leaks.py [--write]

Found 2026-10-02: scope is pooled over a concept (rule 28,
`effective_gate_verdict`), so an abbreviation that is still MAPPED onto its
full form carries its `out` to the full form. `DF` ruled out (its abstracts
use it for diabetic foot and for dermal fibroblast) put `diabetic foot` out of
scope; `%TBSA` put `total body surface area` out; `BMP-2` put `Bone
Morphogenetic Protein 2` out. The rule meant the abbreviation, never the
concept.

For every term a rule-58 step put out (curator verdict tagged `rule 58...`)
that still maps onto a canonical which is out only through it, the pair is
refused (`TermMappingAndGate.refuse`: the term is unmapped, the refusal kept);
the same where it ran the other way and the full form's curator `in`
swallowed the abbreviation's out (`NLR`, `EC`, `GF` stayed in and mapped);
the term stays out, the canonical gets its own verdict back. Outs the curator
set by hand (the contradiction queue) are not touched: those are the
curator's ruling on the concept.

Dry by default; `--write` backs up the term dict, saves once, reads back.
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

BY = "rule 58 outs kept on the abbreviation (2026-10-02)"


def leaks(gt):
    rows = []
    for t, rec in gt.records.items():
        if gt.is_alias(t):
            continue
        cur = (rec.get("gate") or {}).get("curator") or {}
        to = rec.get("to")
        if cur.get("verdict") != "out" or not to or not str(cur.get("by", "")).startswith("rule 58"):
            continue
        own = (((gt.records.get(to) or {}).get("gate") or {}).get("curator") or {}).get("verdict")
        if gt.effective_gate_verdict(to)[0] == "out" and own != "out":
            rows.append((t, to))            # the out reached the full form
        elif gt.effective_gate_verdict(t)[0] == "in" and cur.get("by") == "rule 58 inside names, v2 (2026-10-02)":
            # the full form's `in` swallowed the out (`NLR`): only where the out
            # says the abbreviation MEANS different things; `IL‑6` -> interleukin-6
            # (out as an undefined spelling, mapped rightly) keeps its mapping
            rows.append((t, to))
    return rows


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator

    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    rows = leaks(gt)
    print(f"[leaks] {len(rows)} full form(s) out of scope only through an abbreviation ruled out:")
    for t, to in rows:
        print(f"[leaks]     {t!r} -> {to!r}")
    if "--write" not in argv:
        print("[leaks] dry run; --write to unmap them")
        return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_out_leaks_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[leaks] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    for t, to in rows:
        gt.refuse(t, to, reason="the abbreviation is out of scope (rule 58); its full form is not", by=BY)
    gt._dirty()
    gt.save()
    print(f"[leaks] gate lists re-exported: {p.export_gate_lists()}")
    g2 = Orchestrator().term_mapper._term_mapping
    # a full form may still be out by its OWN sources (`placental membrane`
    # sits on the old blocklist): that is its verdict, not a leak
    bad = [(t, to) for t, to in rows
           if g2.data.get(t) == to or g2.effective_gate_verdict(t)[0] != "out"
           or g2.effective_gate_verdict(to)[1] == "curator" and g2.effective_gate_verdict(to)[0] == "out"]
    if bad or leaks(g2):
        raise RuntimeError(f"[leaks] read back: {bad[:5]} still wrong; {len(leaks(g2))} leak(s) left")
    print(f"[leaks] written and read back: {len(rows)} unmapped; each stays out, each full form is back "
          f"to its own verdict")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
