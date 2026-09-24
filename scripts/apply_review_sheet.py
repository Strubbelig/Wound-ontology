"""Apply a marked-up mapping review sheet back to the term mapping.

    python scripts/apply_review_sheet.py data/review/mapping_review_2026-09-22.csv
    python scripts/apply_review_sheet.py data/review/mapping_review_2026-09-22.csv --apply

It takes either sheet: the row-level `mapping_review_*.csv`, or the
`mapping_families_*.csv` where one row is one CANONICAL and the `terms` column
lists everything that collapses onto it. A decision on a family applies to
every term in it, which is the point of the family sheet — 4,813 entries are
3,574 families, and the repetition is in the families.

Two columns are the curator's:

  keep(y/n)             `n` withdraws the entry — the term goes back to being
                        its own concept. `y` or blank leaves it standing.
  corrected canonical   a label — re-points the entry there. It WINS over
                        keep(y/n), because saying where a term belongs is a
                        stronger statement than saying it does not belong here.

                        Put the row's OWN TERM here to REVERSE the entry: the
                        term is the canonical and the current canonical should
                        collapse onto it. `subcutaneous tissue -> subcutaneous
                        layer` with `subcutaneous tissue` in this column
                        refuses that pair and writes `subcutaneous layer ->
                        subcutaneous tissue` instead.

                        Reversal is its own case because `n` cannot say it.
                        Marking such a row `n` refuses the merge and leaves BOTH
                        spellings standing as separate concepts — the opposite
                        of what "the other one is the right name" means. On the
                        2026-09-24 sheet 6 of 9 `n` marks said exactly that in
                        their `why` cell, so the column could not carry the
                        decision the curator was making.

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


def decisions(df: "pd.DataFrame") -> tuple[list[str], dict[str, str], dict[str, str], int]:
    """(withdraw, re-point, reverse, unmarked) as the sheet's two curator columns say.

    `corrected canonical` outranks `keep(y/n)`: saying where a term belongs is a
    stronger statement than saying it does not belong here. Anything else —
    blank, `y`, whitespace — leaves the entry standing and is counted, because
    an unmarked row is not a decision and the count is what says so.

    `corrected canonical` holding the row's own TERM is a REVERSAL, not a
    re-point onto itself: the curator is saying this term is the canonical. It
    maps to `{term: canonical}` — the pair to refuse, and the direction to write
    instead. Read case-insensitively: a curator typing a name back is matching a
    concept, not a byte string. Nothing here writes an identity entry, which
    rule 19 prunes and which would lose the decision on the next build.

    The canonical is checked FIRST, and exactly. When a term and its canonical
    differ only in case — `a -> A` — a case-insensitive test cannot tell a
    restatement of the canonical from the term typed back, and restating the
    canonical is the one of the two that means nothing. Typing `a` there still
    reverses, because `a` is not `A`.
    """
    withdraw: list[str] = []
    repoint: dict[str, str] = {}
    reverse: dict[str, str] = {}
    unmarked = 0
    for _, row in df.iterrows():
        term = str(row["term"])
        canonical = str(row["canonical"])
        corrected = str(row["corrected canonical"]).strip()
        keep = str(row["keep(y/n)"]).strip().lower()
        if corrected and corrected.lower() != "nan":
            if corrected == canonical:
                pass                     # a restatement, not a decision
            elif corrected.strip().lower() == term.strip().lower():
                reverse[term] = canonical
            else:
                repoint[term] = corrected
        elif keep == "n":
            withdraw.append(term)
        elif keep not in ("y", "yes"):
            unmarked += 1
    return withdraw, repoint, reverse, unmarked


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    apply = "--apply" in argv[1:]
    if not args:
        print(__doc__)
        return 2
    sheet = Path(args[0])
    df = pd.read_csv(sheet).fillna("")
    if "terms" in df.columns and "term" not in df.columns:
        # a family sheet: expand each family into its members, so everything
        # below works on entries and one decision reaches all of them
        df = df.assign(term=df["terms"].str.split(" ; ")).explode("term")
        df["term"] = df["term"].str.strip()
    for col in ("term", "canonical", "keep(y/n)", "corrected canonical"):
        if col not in df.columns:
            raise SystemExit(f"{sheet} has no {col!r} column — is it a review sheet?")

    withdraw, repoint, reverse, unmarked = decisions(df)

    print(f"[review] {sheet.name}: {len(df):,} rows — "
          f"{len(withdraw)} to withdraw, {len(repoint)} to re-point, "
          f"{len(reverse)} to reverse, "
          f"{unmarked:,} left unmarked (an unmarked row is not a decision; "
          f"the entry stands).")
    for t, c in list(reverse.items())[:10]:
        print(f"[review]     REVERSE  {c!r} -> {t!r}  (was {t!r} -> {c!r})")
    if not apply:
        print("[review] dry run — nothing written. Re-run with --apply.")
        return 0
    if not (withdraw or repoint or reverse):
        print("[review] nothing to do.")
        return 0

    p = Orchestrator()
    mapping = p.term_mapper.mapping
    missing = [t for t in withdraw if t not in mapping]
    if missing:
        print(f"[review] {len(missing)} row(s) marked `n` are no longer in the "
              f"mapping — already withdrawn, or the mapping was rebuilt since "
              f"the sheet was written: {missing[:5]}")
    # A refusal is recorded, not deleted. `withdraw` would remove the entry and
    # leave nothing behind, so the next mapping build would re-propose the merge
    # and the adjudication cache would re-approve it — the curator's evening,
    # overwritten by a rebuild. `refuse` keeps the pair on record and
    # `build_from_embeddings` honours it.
    reasons = {str(r["term"]): str(r.get("why") or r.get("LLM reason") or "")
               for _, r in df.iterrows()}
    refused_pairs: dict[str, str] = {}
    for term in withdraw:
        canonical = mapping.get(term) or str(
            df.loc[df["term"] == term, "canonical"].iloc[0])
        p.term_mapper.refuse(term, canonical,
                             reason=reasons.get(term, "")[:200], by="curator")
        refused_pairs[term] = canonical
    n = len(refused_pairs)
    for term, canonical in repoint.items():
        p.term_mapper._term_mapping.add(term, canonical, confidence=1.0, method="manual")
        p.term_mapper.judge(term, canonical,
                            curator={"verdict": "repointed",
                                     "reason": reasons.get(term, "")[:200]})
    # A reversal is two writes and they belong together: the pair the curator
    # rejected is refused so no rebuild proposes it again, and the merge they DO
    # want is written in the direction they want it.
    for term, canonical in reverse.items():
        why = reasons.get(term, "")[:200]
        p.term_mapper.refuse(term, canonical,
                             reason=f"reversed by the curator: {why}"[:200], by="curator")
        refused_pairs[term] = canonical
        p.term_mapper._term_mapping.add(canonical, term, confidence=1.0, method="manual")
        p.term_mapper.judge(canonical, term,
                            curator={"verdict": "reversed", "reason": why})

    # Read it back. `add` and `remove` save as they go, so what the next step
    # loads is what is on disk, and that is what has to be checked.
    reloaded_mapper = Orchestrator().term_mapper
    reloaded = reloaded_mapper.mapping
    still_there = [t for t in withdraw if t in reloaded]
    unremembered = [t for t, c in refused_pairs.items()
                    if not reloaded_mapper._term_mapping.is_refused(t, c)]
    if unremembered:
        raise RuntimeError(
            f"[review] {len(unremembered)} refusal(s) were applied but not "
            f"recorded, so the next build would re-propose them: "
            f"{unremembered[:5]}")
    wrong = {t: reloaded.get(t) for t, c in repoint.items() if reloaded.get(t) != c}
    wrong.update({c: reloaded.get(c) for t, c in reverse.items() if reloaded.get(c) != t})
    still_there += [t for t in reverse if t in reloaded]
    if still_there or wrong:
        raise RuntimeError(
            f"[review] the sheet did NOT land: {len(still_there)} withdrawn "
            f"entr(ies) are still in the mapping {still_there[:5]}, and "
            f"{len(wrong)} re-pointed entr(ies) read back wrong {list(wrong.items())[:5]}."
        )
    print(f"[review] refused {n} entr(ies) on the record, re-pointed {len(repoint)}, "
          f"reversed {len(reverse)}; verified against the file. "
          f"{len(reloaded):,} entries remain.")
    print("[review] run_apply_mapping() next — the store still holds the old "
          "spellings until it runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
