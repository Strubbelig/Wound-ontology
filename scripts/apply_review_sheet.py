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

`NA`, `N/A`, `None`, `null` and `nan` are TERMS here, not missing values.
`N/A -> NA` and `Na+ -> NA` are both live mapping entries, and pandas reads all
four cells as missing by default: the review sheet showed a blank row, the UI
showed a family with no canonical and no terms, and a decision on it would have
been applied to the empty string. Every sheet is therefore read with
`keep_default_na=False`, so a cell says what it says.

Without --apply nothing is written; the counts are printed and nothing else.

Every write is verified by reloading the file and reading it back. A review
that says it saved a decision it did not save is worse than one that refuses,
so a write that did not land raises instead of being reported as done.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from wound_ontology.orchestrator import Orchestrator


class Decisions(NamedTuple):
    withdraw: list[str]
    repoint: dict[str, str]
    reverse: dict[str, str]
    kept: list[str]
    unmarked: int
    ambiguous: list[tuple[str, str, list[str]]]


def decisions(df: "pd.DataFrame") -> Decisions:
    """(withdraw, re-point, reverse, kept, unmarked) as the curator columns say.

    A `y` is a DECISION and is recorded as one. It writes no mapping — the entry
    already stands — but a review that leaves no trace of what it approved is a
    review that has to be redone: the 2026-09-24 sheet approved 164 rows and the
    mapping could not tell them from the 4,486 nobody had looked at. `kept`
    carries them so `main` can put `curator: {"verdict": "kept"}` on each.

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

    The term match is exact too WHENEVER the sheet holds that exact term. A
    family can contain two spellings of one word: `Angiogenesis process` gathers
    `angiogenesis` and `Angiogenesis`, and reversing onto `angiogenesis` made
    BOTH rows think they were the chosen one, writing two inverse entries for one
    canonical where the second silently overwrote the first. So case-insensitive
    matching is the fallback for a name typed back by hand, not the rule: when
    some row carries the correction verbatim, that row reverses and its siblings
    re-point onto it — which is what reversing a family means.

    And the fallback only fires when it identifies ONE term. `type 2 diabetes`
    gathers both `Diabetes Mellitus type 2` and `diabetes mellitus type 2`, and
    the curator corrected it to a third spelling, `Diabetes mellitus type 2`.
    Case-insensitively that named both, so both rows read themselves as the
    chosen one and each wrote an inverse entry for the same canonical — the
    second overwriting the first. Two spellings cannot both be the name typed
    back, so a correction matching several is not a reversal at all: it is a
    re-point onto the spelling the curator actually wrote, which is the plainer
    reading of typing a name that is in the family nowhere. `ambiguous` carries
    these so the run says which families were read that way.
    """
    exact_terms = {str(t) for t in df["term"]}
    # Case-insensitive matching is scoped to the FAMILY, not the whole sheet: the
    # question a correction raises is "which of THIS family's terms did the
    # curator type back", and another family's spelling of the same word cannot
    # answer it either way.
    siblings: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        siblings.setdefault(str(row["canonical"]), []).append(str(row["term"]))
    ambiguous: list[tuple[str, str, list[str]]] = []
    withdraw: list[str] = []
    repoint: dict[str, str] = {}
    reverse: dict[str, str] = {}
    kept: list[str] = []
    unmarked = 0
    seen_ambiguous: set[tuple[str, str]] = set()
    for _, row in df.iterrows():
        term = str(row["term"])
        canonical = str(row["canonical"])
        corrected = str(row["corrected canonical"]).strip()
        keep = str(row["keep(y/n)"]).strip().lower()
        if corrected and corrected.lower() != "nan":
            matches = [t for t in siblings.get(canonical, [])
                       if t.strip().lower() == corrected.strip().lower()]
            if corrected == canonical:
                pass                     # a restatement, not a decision
            elif corrected == term:
                reverse[term] = canonical
            elif (corrected.strip().lower() == term.strip().lower()
                    and corrected not in exact_terms and len(matches) == 1):
                reverse[term] = canonical
            else:
                if (corrected.strip().lower() == term.strip().lower()
                        and corrected not in exact_terms and len(matches) > 1):
                    if (canonical, corrected) not in seen_ambiguous:
                        seen_ambiguous.add((canonical, corrected))
                        ambiguous.append((canonical, corrected, sorted(matches)))
                repoint[term] = corrected
        elif keep == "n":
            withdraw.append(term)
        elif keep in ("y", "yes"):
            kept.append(term)
        else:
            unmarked += 1
    return Decisions(withdraw, repoint, reverse, kept, unmarked, ambiguous)


def expand_families(df: "pd.DataFrame") -> "pd.DataFrame":
    """One row per family becomes one row per member, and per canonical.

    The members come from the `terms` column, so a decision on a family reaches
    all of them — which is the point of the family sheet.

    The canonical joins its own family whenever the family is being MOVED.
    `silver-containing dressings` gathered 7 spellings and the curator
    re-pointed it to `silver-containing dressing`; moving only the 7 leaves the
    plural they were deleting standing as its own concept, still holding its own
    mentions — the decision defeated by the shape of the sheet. A correction
    names where the family belongs, and the canonical is in the family.

    `y` and `n` get no such row: they change no mapping, and a canonical is the
    target of its pairs, not one of them.
    """
    df = df.assign(term=df["terms"].str.split(" ; ")).explode("term")
    df["term"] = df["term"].str.strip()
    corrected = df["corrected canonical"].astype(str).str.strip()
    canonical = df["canonical"].astype(str).str.strip()
    moved = df[(corrected != "") & (corrected.str.lower() != "nan")
               & (corrected != canonical)].drop_duplicates(subset=["canonical"]).copy()
    if not len(moved):
        return df
    members = {(str(c), str(t)) for c, t in zip(df["canonical"], df["term"])}
    moved = moved[[(str(c), str(c)) not in members for c in moved["canonical"]]]
    if not len(moved):
        return df
    moved["term"] = moved["canonical"].astype(str)
    print(f"[review] {len(moved)} canonical(s) join their own family, because a "
          f"correction moves the family and the canonical is in it")
    return pd.concat([df, moved], ignore_index=True)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    apply = "--apply" in argv[1:]
    if not args:
        print(__doc__)
        return 2
    sheet = Path(args[0])
    df = pd.read_csv(sheet, keep_default_na=False).fillna("")
    if "terms" in df.columns and "term" not in df.columns:
        df = expand_families(df)

    for col in ("term", "canonical", "keep(y/n)", "corrected canonical"):
        if col not in df.columns:
            raise SystemExit(f"{sheet} has no {col!r} column — is it a review sheet?")

    withdraw, repoint, reverse, kept, unmarked, ambiguous = decisions(df)
    for canonical, corrected, matches in ambiguous:
        print(f"[review]  AMBIGUOUS  {canonical!r} corrected to {corrected!r}, which "
              f"matches {len(matches)} of its terms case-insensitively "
              f"({', '.join(repr(m) for m in matches)}) and none of them exactly "
              f"— read as a re-point onto {corrected!r}, not a reversal")

    print(f"[review] {sheet.name}: {len(df):,} rows — "
          f"{len(withdraw)} to withdraw, {len(repoint)} to re-point, "
          f"{len(reverse)} to reverse, {len(kept)} approved as they stand, "
          f"{unmarked:,} left unmarked (an unmarked row is not a decision; "
          f"the entry stands).")
    for t, c in list(reverse.items())[:10]:
        print(f"[review]     REVERSE  {c!r} -> {t!r}  (was {t!r} -> {c!r})")
    if not apply:
        print("[review] dry run — nothing written. Re-run with --apply.")
        return 0
    if not (withdraw or repoint or reverse or kept):
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
        if canonical == term:
            # a row whose term IS its canonical is not a pair, so there is no
            # merge to refuse; silently refusing `x -> x` would write a verdict
            # against a mapping that never existed
            print(f"[review] {term!r} is its own canonical — nothing to refuse")
            continue
        p.term_mapper.refuse(term, canonical,
                             reason=reasons.get(term, "")[:200], by="curator")
        refused_pairs[term] = canonical
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

    # An approval changes no mapping and is still a decision. Without it the next
    # sheet cannot tell a row the curator waved through from one nobody opened.
    for term in kept:
        canonical = mapping.get(term)
        if canonical:
            p.term_mapper.judge(term, canonical,
                                curator={"verdict": "kept",
                                         "reason": reasons.get(term, "")[:200]})
    p.term_mapper.save()

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
    # `judge` does not save, so an approval only reaches disk through the
    # save above. Nothing else would notice if it did not: an approval changes
    # no mapping, so the entry reads back identical either way, and the
    # decision would be silently gone at the next sheet.
    unapproved = [t for t in kept
                  if (c := mapping.get(t))
                  and (reloaded_mapper._term_mapping.peek(t, c).get("curator") or {})
                  .get("verdict") != "kept"]
    if unapproved:
        raise RuntimeError(
            f"[review] {len(unapproved)} approval(s) were applied but not "
            f"recorded: {unapproved[:5]}")
    wrong = {t: reloaded.get(t) for t, c in repoint.items() if reloaded.get(t) != c}
    wrong.update({c: reloaded.get(c) for t, c in reverse.items() if reloaded.get(c) != t})
    still_there += [t for t in reverse if t in reloaded]
    if still_there or wrong:
        raise RuntimeError(
            f"[review] the sheet did NOT land: {len(still_there)} withdrawn "
            f"entr(ies) are still in the mapping {still_there[:5]}, and "
            f"{len(wrong)} re-pointed entr(ies) read back wrong {list(wrong.items())[:5]}."
        )
    # Counted AFTER the reversals, which refuse a pair each. Counting before them
    # reported 2 refusals on a run that recorded 8.
    print(f"[review] {len(refused_pairs)} refusal(s) on the record "
          f"({len(withdraw)} withdrawn, {len(reverse)} the refused half of a "
          f"reversal), {len(repoint)} re-pointed, {len(reverse)} reversed; "
          f"{len(kept)} approved as they stand; verified against the file. "
          f"{len(reloaded):,} entries remain.")
    print("[review] run_apply_mapping() next — the store still holds the old "
          "spellings until it runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
