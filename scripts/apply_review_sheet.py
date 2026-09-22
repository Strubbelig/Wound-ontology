"""Apply a marked-up mapping review sheet back to the term mapping.

    python scripts/apply_review_sheet.py data/review/mapping_review_2026-09-22.csv
    python scripts/apply_review_sheet.py data/review/mapping_review_2026-09-22.csv --apply

Two columns are the curator's:

  keep(y/n)             `n` withdraws the entry — the term goes back to being
                        its own concept. `y` or blank leaves it standing.
  corrected canonical   a label — re-points the entry there. It WINS over
                        keep(y/n), because saying where a term belongs is a
                        stronger statement than saying it does not belong here.

Without --apply nothing is written; the counts are printed and nothing else.

Every write is verified by reloading the file and reading it back. A review
that says it saved a decision it did not save is worse than one that refuses,
so a write that did not land raises instead of being reported as done.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from wound_ontology.orchestrator import Orchestrator


def decisions(df: "pd.DataFrame") -> tuple[list[str], dict[str, str], int]:
    """(withdraw, re-point, unmarked) as the sheet's two curator columns say.

    `corrected canonical` outranks `keep(y/n)`: saying where a term belongs is a
    stronger statement than saying it does not belong here. Anything else —
    blank, `y`, whitespace — leaves the entry standing and is counted, because
    an unmarked row is not a decision and the count is what says so.
    """
    withdraw: list[str] = []
    repoint: dict[str, str] = {}
    unmarked = 0
    for _, row in df.iterrows():
        term = str(row["term"])
        corrected = str(row["corrected canonical"]).strip()
        keep = str(row["keep(y/n)"]).strip().lower()
        if corrected:
            if corrected != str(row["canonical"]):
                repoint[term] = corrected
        elif keep == "n":
            withdraw.append(term)
        elif keep not in ("y", "yes"):
            unmarked += 1
    return withdraw, repoint, unmarked


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    apply = "--apply" in argv[1:]
    if not args:
        print(__doc__)
        return 2
    sheet = Path(args[0])
    df = pd.read_csv(sheet).fillna("")
    for col in ("term", "canonical", "keep(y/n)", "corrected canonical"):
        if col not in df.columns:
            raise SystemExit(f"{sheet} has no {col!r} column — is it a review sheet?")

    withdraw, repoint, unmarked = decisions(df)

    print(f"[review] {sheet.name}: {len(df):,} rows — "
          f"{len(withdraw)} to withdraw, {len(repoint)} to re-point, "
          f"{unmarked:,} left unmarked (an unmarked row is not a decision; "
          f"the entry stands).")
    if not apply:
        print("[review] dry run — nothing written. Re-run with --apply.")
        return 0
    if not (withdraw or repoint):
        print("[review] nothing to do.")
        return 0

    p = Orchestrator()
    mapping = p.term_mapper.mapping
    missing = [t for t in withdraw if t not in mapping]
    if missing:
        print(f"[review] {len(missing)} row(s) marked `n` are no longer in the "
              f"mapping — already withdrawn, or the mapping was rebuilt since "
              f"the sheet was written: {missing[:5]}")
    n = p.term_mapper.withdraw(*withdraw)
    for term, canonical in repoint.items():
        p.term_mapper._term_mapping.add(term, canonical, confidence=1.0, method="manual")

    # Read it back. `add` and `remove` save as they go, so what the next step
    # loads is what is on disk, and that is what has to be checked.
    reloaded = Orchestrator().term_mapper.mapping
    still_there = [t for t in withdraw if t in reloaded]
    wrong = {t: reloaded.get(t) for t, c in repoint.items() if reloaded.get(t) != c}
    if still_there or wrong:
        raise RuntimeError(
            f"[review] the sheet did NOT land: {len(still_there)} withdrawn "
            f"entr(ies) are still in the mapping {still_there[:5]}, and "
            f"{len(wrong)} re-pointed entr(ies) read back wrong {list(wrong.items())[:5]}."
        )
    print(f"[review] withdrew {n} entr(ies), re-pointed {len(repoint)}; verified "
          f"against the file. {len(reloaded):,} entries remain.")
    print("[review] run_apply_mapping() next — the store still holds the old "
          "spellings until it runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
