"""Turn the contested-set UI's PER-TERM decisions into a row sheet.

The 2026-09-24 round decided a family at a time, which is right when every term
in it agrees. The 15 families left over are exactly the ones where they do not:
`antiseptic drug` gathers three terms pass 2 calls the same class and one it
calls broader, and `antimicrobial effect` splits three ways. So this round
decides one TERM at a time, and the sheet it writes is the row sheet
`apply_review_sheet.py` has always taken.

    merge      -> keep(y/n) = y        the mapping stands, approved
    split      -> keep(y/n) = n        the pair refused on the record
    canonical  -> corrected canonical = the term itself, which reverses it
    elsewhere  -> corrected canonical = the label typed in

The `canonical` column is the term's CURRENT canonical, not the one the family
had when the page was built. Four of the fifteen were moved by the earlier
review -- `subcutaneous layer` now points at `subcutaneous tissues` -- and a
decision the curator makes while looking at where a term IS must be applied
there, not against a pair that no longer exists.

    python scripts/review_ui_pull_terms.py <dir-of-decision-json>
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import pandas as pd                                          # noqa: E402

VERDICTS = {"merge", "split", "canonical", "elsewhere"}


def _label_shaped(target: str) -> str:
    """The same shape check the family pull uses, imported rather than copied."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "review_ui_pull", Path(__file__).resolve().parent / "review_ui_pull.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.label_shaped(target)


def load(src: Path) -> dict[str, dict]:
    """Every term decision in `src`, keyed `"<family index>:<term index>"`."""
    files = sorted(src.rglob("*.json")) if src.is_dir() else [src]
    if not files:
        raise SystemExit(f"[pull] no .json under {src}")
    out: dict[str, dict] = {}
    for f in files:
        if not f.stem.startswith("f"):
            continue                              # not a family document
        fam = f.stem[1:]
        body = json.loads(f.read_text())
        for key, d in body.items():
            if not key.startswith("t") or not isinstance(d, dict):
                continue
            if d.get("v") not in VERDICTS:
                raise SystemExit(f"[pull] {f.name}/{key}: verdict {d.get('v')!r} is "
                                 f"not one of {sorted(VERDICTS)}")
            if not d.get("term"):
                raise SystemExit(f"[pull] {f.name}/{key}: the decision names no term")
            out[f"{fam}:{key[1:]}"] = d
    print(f"[pull] {len(out)} term decision(s) across {len(files)} file(s)")
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    decisions = load(Path(args[0]))

    data = json.loads((ROOT / "data" / "review" /
                       "review_ui_contested_2026-09-25.json").read_text())
    fams = {str(f["i"]): f for f in data["families"]}
    unknown = [k for k in decisions if k.split(":")[0] not in fams]
    if unknown:
        raise SystemExit(f"[pull] {len(unknown)} decision(s) name a family that is "
                         f"not in the data file: {unknown[:5]}")

    rows, counts, prose = [], {v: 0 for v in VERDICTS}, []
    for key, d in sorted(decisions.items(), key=lambda kv: (int(kv[0].split(":")[0]),
                                                            int(kv[0].split(":")[1]))):
        fi, ti = key.split(":")
        f = fams[fi]
        if int(ti) >= len(f["terms"]):
            raise SystemExit(f"[pull] family {fi} has no term {ti}")
        t = f["terms"][int(ti)]
        if t["t"] != d["term"]:
            raise SystemExit(f"[pull] family {fi} term {ti} was decided as "
                             f"{d['term']!r} but the data file has {t['t']!r} — "
                             f"the page was built from different data; do not apply this.")
        # decide against where the term IS, not where the family used to point
        canonical = t.get("now") or f["c"]
        keep, corrected = "", ""
        if d["v"] == "merge":
            keep = "y"
        elif d["v"] == "split":
            keep = "n"
        elif d["v"] == "canonical":
            corrected = t["t"]
        else:
            corrected = (d.get("to") or "").strip()
            if not corrected:
                raise SystemExit(f"[pull] family {fi} term {ti}: 'elsewhere' with "
                                 f"no label — {t['t']!r} was left half-decided")
            if (bad := _label_shaped(corrected)):
                prose.append((fi, t["t"], corrected, bad))
                continue
        counts[d["v"]] += 1
        moved = " (moved since the review; decided against where it now points)" \
            if t.get("now") and t["now"] != f["c"] else ""
        rows.append({"term": t["t"], "canonical": canonical,
                     "term mentions": t["mn"],
                     "keep(y/n)": keep, "corrected canonical": corrected,
                     "why": f"contested set, {d.get('at', '')[:19]}{moved}"})

    if prose:
        lines = "\n".join(f"    family {i}, {t!r} -> {to!r}\n        {why}"
                          for i, t, to, why in prose)
        raise SystemExit(f"[pull] {len(prose)} target(s) do not read as a label, so "
                         f"nothing was written:\n{lines}")

    out = ROOT / "data" / "review" / f"mapping_terms_contested_{date.today()}.csv"
    for n in range(2, 100):
        if not out.exists():
            break
        out = out.with_name(f"mapping_terms_contested_{date.today()}_{n}.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print("[pull] " + ", ".join(f"{counts[v]} {v}" for v in sorted(VERDICTS)))
    print(f"[pull] wrote {out.relative_to(ROOT)}")
    print(f"[pull] dry run it:  python scripts/apply_review_sheet.py {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
