"""Join Claude's universality reading to the relations it read (rule 66). Read-only on the store.

    python -u scripts/compile_universality.py [--dir relation_universality_2026-10-27]

Reads data/review/<dir>/{rows.json, verdicts_*.txt} (default the 2026-10-02
reading; 2026-10-27 is the one for FCA inheritance, rule 88);
every row needs exactly one verdict (all / some / no), or this raises.
Writes data/review/<dir>/result.json, read back:
the `all` rows are the relations that may become axioms.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "review" / (sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv
                                else "relation_universality_2026-10-02")


def main() -> int:
    rows = json.loads((D / "rows.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in rows}
    verdicts = {}
    for f in sorted(D.glob("verdicts_*.txt")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            m = re.match(r"(\S+)\s+(all|some|no)\b\s*(?:#\s*(.*))?$", line.strip())
            if not m:
                raise SystemExit(f"[universality] unreadable line in {f.name}: {line!r}")
            i, v, note = m.groups()
            if i in verdicts:
                raise SystemExit(f"[universality] {i} read twice")
            verdicts[i] = (v, note or "")
    missing, extra = ids - set(verdicts), set(verdicts) - ids
    if missing or extra:
        raise SystemExit(f"[universality] {len(missing)} row(s) without a verdict {sorted(missing)[:5]}, "
                         f"{len(extra)} verdict(s) without a row {sorted(extra)[:5]}")
    for r in rows:
        r["universality"], r["note"] = verdicts[r["id"]]
    tally = Counter(r["universality"] for r in rows)
    why_no = Counter(re.sub(r",.*|:.*", "", r["note"]) or "(no note)" for r in rows if r["universality"] == "no")
    by_pred = {}
    for r in rows:
        by_pred.setdefault(r["predicate"], Counter())[r["universality"]] += 1
    out = {"read_by": f"Claude, {D.name.rsplit('_', 1)[-1]}", "rows": len(rows), "verdicts": dict(tally),
           "why_no": dict(why_no.most_common()), "by_predicate": {k: dict(v) for k, v in by_pred.items()},
           "axioms": [r for r in rows if r["universality"] == "all"], "all_rows": rows}
    (D / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads((D / "result.json").read_text(encoding="utf-8"))
    assert back["rows"] == len(rows) and len(back["axioms"]) == tally["all"]
    print(f"[universality] {len(rows)} rows read: {dict(tally)}")
    print(f"[universality] why `no`: {dict(why_no.most_common())}")
    for p, c in sorted(by_pred.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"[universality]   {p:36} all {c['all']:4}  some {c['some']:4}  no {c['no']:4}")
    print(f"[universality] written and read back: {(D / 'result.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
