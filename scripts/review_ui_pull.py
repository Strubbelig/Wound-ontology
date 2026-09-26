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

A re-point target is a LABEL, and the script checks that it looks like one
before it writes it anywhere. The 2026-09-24 review put this in the box:

    'wound healing' -> 'wound healing is a class in the onto and everything
                        should merge into that'

which is a sentence addressed to the reader, not a canonical. Applied as typed
it would have minted a 74-character class name carrying 995 mentions. A
free-text box a human types into is not a machine input, so anything that does
not read as a label stops the run and is named. `--resolve` is how the reading
is then recorded, in the open, with the original words kept in `why`:

    python scripts/review_ui_pull.py <dir> --resolve 794=keep
    python scripts/review_ui_pull.py <dir> --resolve 794=repoint:wound healing

    python scripts/review_ui_pull.py <dir-of-decision-json> [--out NAME]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import pandas as pd                                          # noqa: E402

VERDICTS = {"keep", "reject", "reverse", "repoint"}

# A label is a noun phrase. These are the shapes of a sentence: a finite verb,
# an instruction, an address to the reader. None of them can be a class name.
PROSE = re.compile(
    r"\b(is|are|was|were|should|must|shall|can|could|would|will|please|"
    r"everything|anything|merge|merged|delete|deleted|remove|removed|"
    r"i|we|you|it|this|that|onto\b)\b", re.I)
MAX_LABEL_WORDS = 8


def label_shaped(target: str) -> str:
    """"" if `target` reads as a label, else why it does not.

    Two tests, both crude on purpose: a label is short, and a label has no
    finite verb. Crude is right here — the cost of a false alarm is that the
    curator confirms one target by hand, and the cost of a miss is a sentence
    written into the ontology as a class name.
    """
    words = target.split()
    if len(words) > MAX_LABEL_WORDS:
        return f"{len(words)} words — a label is at most {MAX_LABEL_WORDS}"
    hit = PROSE.search(target)
    if hit and len(words) > 2:
        return f"reads as a sentence, not a name (on {hit.group(0)!r})"
    return ""


def parse_resolutions(argv: list[str]) -> dict[int, tuple[str, str]]:
    """`--resolve 794=keep`, `--resolve 794=repoint:wound healing`."""
    out: dict[int, tuple[str, str]] = {}
    for i, a in enumerate(argv):
        if a != "--resolve":
            continue
        if i + 1 >= len(argv):
            raise SystemExit("[pull] --resolve needs INDEX=VERDICT[:TARGET]")
        spec = argv[i + 1]
        if "=" not in spec:
            raise SystemExit(f"[pull] --resolve {spec!r}: expected INDEX=VERDICT[:TARGET]")
        idx, _, rest = spec.partition("=")
        verdict, _, target = rest.partition(":")
        if not idx.strip().isdigit():
            raise SystemExit(f"[pull] --resolve {spec!r}: {idx!r} is not a family index")
        if verdict not in VERDICTS:
            raise SystemExit(f"[pull] --resolve {spec!r}: {verdict!r} is not one of "
                             f"{sorted(VERDICTS)}")
        if verdict in ("repoint", "reverse") and not target.strip():
            raise SystemExit(f"[pull] --resolve {spec!r}: {verdict} needs a target")
        if target.strip() and label_shaped(target.strip()):
            raise SystemExit(f"[pull] --resolve {spec!r}: the target is not a label "
                             f"either ({label_shaped(target.strip())})")
        out[int(idx)] = (verdict, target.strip())
    return out


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
    resolutions = parse_resolutions(argv[1:])
    rest = list(argv[1:])
    for i, a in enumerate(rest):          # drop --resolve and its value
        if a == "--resolve":
            rest[i] = rest[i + 1] = "--"
    args = [a for a in rest if not a.startswith("--")]
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

    rows, counts, prose, resolved = [], {v: 0 for v in VERDICTS}, [], []
    for i, d in sorted(decisions.items()):
        f = by_index[i]
        if d.get("c") and d["c"] != f["c"]:
            raise SystemExit(
                f"[pull] family {i} was decided as {d['c']!r} but the data file has "
                f"{f['c']!r} — the two disagree; do not apply this.")
        verdict, note = d["v"], ""
        # A target that is not a label never reaches the sheet. Either the
        # curator's reading of it was passed in, and the original words are kept
        # in `why`, or the run stops below with the family named.
        if verdict == "repoint" and (bad := label_shaped(d.get("to", ""))):
            if i in resolutions:
                verdict, forced = resolutions[i]
                note = f"; curator wrote {d.get('to','')!r}, read as {verdict}"
                d = {**d, "to": forced, "term": forced}
                resolved.append((i, f["c"], verdict))
            else:
                prose.append((i, f["c"], d.get("to", ""), bad))
                continue
        keep, corrected = "", ""
        if verdict == "keep":
            keep = "y"
        elif verdict == "reject":
            keep = "n"
        elif verdict == "reverse":
            corrected = d.get("term", "")
            if corrected not in [t["t"] for t in f["terms"]]:
                raise SystemExit(f"[pull] family {i}: reversed onto {corrected!r}, "
                                 f"which is not one of its terms")
        else:
            corrected = d.get("to", "")
            if not corrected:
                raise SystemExit(f"[pull] family {i}: re-pointed to nothing")
        counts[verdict] += 1
        rows.append({
            "canonical": f["c"],
            "terms": " ; ".join(t["t"] for t in f["terms"]),
            "n": f["n"], "mentions": f["m"],
            "keep(y/n)": keep, "corrected canonical": corrected,
            "why": f"from the review UI, {d.get('at', '')[:19]}{note}",
        })

    if prose:
        lines = "\n".join(
            f"    family {i} ({c!r}) -> {t!r}\n        {why}" for i, c, t, why in prose)
        raise SystemExit(
            f"[pull] {len(prose)} re-point target(s) do not read as a label, so "
            f"nothing was written:\n{lines}\n"
            f"    Say how each should be read, e.g. --resolve {prose[0][0]}=keep "
            f"or --resolve {prose[0][0]}=repoint:some label")
    for i, c, v in resolved:
        print(f"[pull] family {i} ({c!r}): prose target read as {v}, as instructed")

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
