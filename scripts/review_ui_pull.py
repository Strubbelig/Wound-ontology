"""Turn the review UI's decisions into a sheet `apply_review_sheet.py` can apply.

The UI writes one document per hundred families into the artifact's store
(`decisions/b0`, `b1`, …), each `{familyIndex: {v, c, term?, to?, at}}`. This
reads those documents — fetched with the Artifact tool's `read_db` into a
directory — and writes a `mapping_families_*.csv` in the shape the applier
already understands, so the UI adds a way to DECIDE and changes nothing about
how a decision is recorded.

How each verdict lands, once the applier explodes a family into its terms:

    keep     every term marked `y`        -> curator: kept, mapping unchanged
    reject   every term marked `n`        -> the pair refused on the record
    reverse  `corrected canonical` = the chosen term. The chosen term's own row
             reverses (refuse it, write the inverse); every sibling re-points
             onto it. Which is exactly what reversing a family means.
    repoint  `corrected canonical` = the new label on every row

    python scripts/review_ui_pull.py <dir-of-decision-json> [--out NAME]
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import pandas as pd                                          # noqa: E402

VERDICTS = {"keep", "reject", "reverse", "repoint"}


def load_decisions(src: Path) -> dict[int, dict]:
    """Every decision in `src`, whether it holds one JSON file or a tree."""
    files = sorted(src.rglob("*.json")) if src.is_dir() else [src]
    if not files:
        raise SystemExit(f"[pull] no .json under {src}")
    out: dict[int, dict] = {}
    for f in files:
        body = json.loads(f.read_text())
        # read_db writes the document body; a wrapper with "data" is tolerated
        body = body.get("data", body) if isinstance(body.get("data"), dict) else body
        for key, d in body.items():
            if not key.lstrip("-").isdigit() or not isinstance(d, dict):
                continue                       # version, metadata, anything else
            v = d.get("v")
            if v not in VERDICTS:
                raise SystemExit(f"[pull] {f.name}: family {key} has verdict {v!r}, "
                                 f"which is not one of {sorted(VERDICTS)}")
            out[int(key)] = d
    print(f"[pull] {len(out):,} decision(s) across {len(files)} file(s)")
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    decisions = load_decisions(Path(args[0]))

    ui = sorted((ROOT / "data" / "review").glob("review_ui_*.json"))[-1]
    fams = json.loads(ui.read_text())["families"]
    print(f"[pull] against {ui.name} ({len(fams):,} families)")
    by_index = {f["i"]: f for f in fams}

    missing = [i for i in decisions if i not in by_index]
    if missing:
        raise SystemExit(
            f"[pull] {len(missing)} decision(s) name a family index that is not in "
            f"{ui.name}: {missing[:5]}. The UI was built from a different data file; "
            f"rebuild it with scripts/review_ui_data.py rather than guessing.")

    rows, counts = [], {v: 0 for v in VERDICTS}
    for i, d in sorted(decisions.items()):
        f = by_index[i]
        if d.get("c") and d["c"] != f["c"]:
            raise SystemExit(
                f"[pull] family {i} was decided as {d['c']!r} but the data file has "
                f"{f['c']!r} — the two disagree; do not apply this.")
        keep, corrected = "", ""
        if d["v"] == "keep":
            keep = "y"
        elif d["v"] == "reject":
            keep = "n"
        elif d["v"] == "reverse":
            corrected = d.get("term", "")
            if corrected not in [t["t"] for t in f["terms"]]:
                raise SystemExit(f"[pull] family {i}: reversed onto {corrected!r}, "
                                 f"which is not one of its terms")
        else:
            corrected = d.get("to", "")
            if not corrected:
                raise SystemExit(f"[pull] family {i}: re-pointed to nothing")
        counts[d["v"]] += 1
        rows.append({
            "canonical": f["c"],
            "terms": " ; ".join(t["t"] for t in f["terms"]),
            "n": f["n"], "mentions": f["m"],
            "keep(y/n)": keep, "corrected canonical": corrected,
            "why": f"from the review UI, {d.get('at', '')[:19]}",
        })

    out = ROOT / "data" / "review" / f"mapping_families_from_ui_{date.today()}.csv"
    for n in range(2, 100):
        if not out.exists():
            break
        out = out.with_name(f"mapping_families_from_ui_{date.today()}_{n}.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print("[pull] " + ", ".join(f"{counts[v]} {v}" for v in sorted(VERDICTS)))
    print(f"[pull] wrote {out.relative_to(ROOT)}")
    print(f"[pull] dry run it:  python scripts/apply_review_sheet.py {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
