"""One-time: capture each list entry's SECTION header onto its gate record.

`METHODOLOGY_BLOCKLIST` is grouped into 207 sections whose headers `recluster`
and `recluster_sapbert` generate (`── seamc · fibroblast · inductive mesenchymal
fibroblasts ──`). Once the literal becomes a generated view of the gate, the
grouping has to come from the record or it is lost on the first export -- so it
moves onto the record, as `gate.rule.section`, before anything overwrites it.

Two sections carry hand-written PROSE as well as a header: the 2026-09-04
study-endpoint rationale (8 lines) and one two-line note. Prose is documentation
about a decision, not a per-term field, and duplicating it across 12 or 274
records to survive a round trip would be the wrong shape. This prints it, and it
moves above the declaration by hand, where module documentation belongs.

    python scripts/p4_capture_list_sections.py [--apply]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from wound_ontology.data_manager.data_manager import DataManager            # noqa: E402
from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate  # noqa: E402
from wound_ontology.store.term_lists import (                               # noqa: E402
    _declares, _entry_value, _find_block_end,
)

FILES = [(ROOT / "config" / "blocklist.py", "METHODOLOGY_BLOCKLIST"),
         (ROOT / "config" / "whitelist.py", "WHITELIST")]


def sections_of(path: Path, var: str) -> list[tuple[list[str], list[str]]]:
    """`[(comment lines, terms)]` in file order."""
    lines = path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if _declares(l, var))
    end = _find_block_end(lines, var)
    out: list[tuple[list[str], list[str]]] = []
    block: list[str] = []
    cur: list[str] = []
    for line in lines[start + 1:end]:
        value = _entry_value(line)
        if value is None:
            if line.strip().startswith("#"):
                if cur:
                    out.append((block, cur))
                    block, cur = [], []
                block.append(line.strip())
            continue
        cur.append(value)
    if cur:
        out.append((block, cur))
    return out


def main(argv: list[str]) -> int:
    apply = "--apply" in argv[1:]
    gt = TermMappingAndGate(DataManager(), file_name="term_mapping")

    written = prose = 0
    for path, var in FILES:
        secs = sections_of(path, var)
        print(f"\n{var}: {len(secs)} section(s), "
              f"{sum(len(t) for _, t in secs)} term(s)")
        for block, terms in secs:
            # The label is the LAST `──` rule line in the block: two headers can
            # sit together when a section ends up empty, and the terms below
            # belong to the second, not the first.
            heads = [l for l in block if "──" in l]
            label = heads[-1] if heads else (block[0] if block else "")
            rest = [l for l in block if l != label and "──" not in l]
            if rest:
                prose += 1
                print(f"  PROSE, {len(rest)} extra line(s), {len(terms)} terms, "
                      f"under {label[:60]!r} — move it above the declaration by hand:")
                for line in rest:
                    print(f"      {line}")
            for term in terms:
                rule = dict(gt.peek_gate(term).get("rule") or {})
                if not rule:
                    print(f"  [!] {term!r} has no rule verdict — the fold missed it")
                    continue
                if rule.get("section") == label:
                    continue
                rule["section"] = label
                if apply:
                    gt.gate(term, rule=rule)
                written += 1
    if not apply:
        print(f"\n[sections] dry run — {written:,} record(s) would gain a section, "
              f"{prose} prose block(s) to move by hand.")
        return 0
    gt.save()

    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    missing = [t for t in check.gated("out")
               if "section" not in (check.peek_gate(t).get("rule") or {})]
    if missing:
        raise RuntimeError(f"[sections] {len(missing)} entr(ies) have no section "
                           f"after the write: {missing[:5]}")
    print(f"\n[sections] {written:,} section label(s) written and read back from disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
