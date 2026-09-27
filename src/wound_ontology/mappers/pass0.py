"""Pass 0: the spellings a rule can settle, fixed before any model is asked.

The curator's rule of 2026-09-25 -- exhaust the deterministic methods first,
and never pay a model to notice that `Surgical Site Infection` and `surgical
site infections` are one thing. Measured on the 2026-09-25 store, **9,650 of
96,243 terms are a pure spelling variant of another**: 5,638 needing only the
singular rule, 3,027 case alone, 584 a hyphen, 272 British spelling.

Four steps, in this order:

1. the head noun to the singular (`singular_spelling`, rule 23a);
2. British to American (`utils.spelling`, rule 41);
3. case, hyphens and punctuation folded (`fold`);
4. group on the result, and elect one surviving spelling.

Singular BEFORE spelling: `Statistical Analyses` becomes `Statistical Analysis`
and the noun never reaches the British-verb reading of `analyses` that `breame`
answers with `analyzes` -- which would then singularise to `analyze`.

**This produces renames, not mappings** (curator, 2026-09-26: *pass 0 should
not create another mapping, it should change the labels right at the spot*).
The old version wrote `member -> canonical` into the term mapping, and that was
wrong twice over. It filled the record a curator reads with 32,302 mechanical
respellings, burying the few hundred decisions that need eyes; and it left the
store holding the un-normalised spelling, so every downstream step had to carry
the mapping around to know what a term was really called -- the term-mapping
build had to inject **23,220 canonicals that were not store strings** into the
clustering, with borrowed frequencies, because pass 0's answers lived in the
mapping instead of in the store.

The rename is applied to the concept store AND to the term mapping, on the
curator's instruction of the same day -- *just to make sure nothing slipped
through*. Normalising only the store would leave the mapping holding spellings
the rules reject, and the next apply would put them back.

The logic is here rather than on the Orchestrator so it can be tested against
plain dicts. The Orchestrator supplies the store's frequencies, the ontology's
labels, the mapping's own strings and the guards, and applies what comes back.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable, Iterable

from wound_ontology.mappers.term_mapper import canonical_rank
from wound_ontology.utils.label_match import fold
from wound_ontology.utils.normalise import PARENTHETICAL, normalise
from wound_ontology.utils.spelling import zipf

#: An alphabetic run. Digits, units and Greek letters are not words and are
#: not held against a spelling.
WORDISH = re.compile(r"[A-Za-z]+")


def invented_words(term: str) -> int:
    """How many of `term`'s alphabetic tokens the language has never seen.

    The tiebreaker for a seam group, where `canonical_rank` has nothing left
    to say. See `_elect`.
    """
    return sum(1 for w in WORDISH.findall(term) if zipf(w.lower()) == 0.0)

def pass0_renames(
    frequencies: dict[str, int],
    anchors: set[str],
    others: Iterable[str] = (),
    *,
    declares: Callable[[str], str | None] = lambda term: None,
) -> tuple[dict[str, str], dict]:
    """`({spelling: the spelling that survives}, report)`.

    `frequencies` is the store's terms and how many abstracts each appears in;
    it decides the election within a group. `anchors` are the ontology's own
    labels, which outrank any store spelling (rule 36) and are kept EXACTLY as
    the ontology writes them. `others` are strings that must be normalised but
    carry no frequency of their own -- the term mapping's keys and canonicals.

    **No person is consulted.** Pass 0 decides how a word is SPELLED -- the
    singular, the American form, the case and the hyphens -- and there is
    nothing there to disagree with: nobody holds that `haemorrhage` and
    `hemorrhage` are two terms. An earlier version of this function skipped
    any pair a curator had ruled on or refused, which read as respect and was
    not: measured on the 2026-09-26 data it held back **385 pairs, every one
    of them a pure spelling variant** -- `Aetiology`/`etiology`,
    `Hospitalisation`/`hospitalization`, `cases`/`case`, `Wound sizes`/`wound
    size` -- because the curator had ruled on them as MAPPINGS, which is a
    claim about which concept a term belongs to and not a claim about how it
    is written. A verdict on one question was being read as a veto on another.

    The two refusals that guard did catch were not disagreements either.
    `Na+`/`NA` and `grey literature`/`gray literature`: the first is two
    different strings that `normalize_term` collapsed by throwing away a `+`,
    and that is a defect in the grouping, not an opinion. `character_key`
    catches it, and every case like it, by rule.

    Two guards remain, both about whether the GROUP is one term at all, and
    both reported rather than applied in silence:

    * `character_key` -- the members must agree once case, dashes and
      whitespace are folded. A group held together only by discarding a `+`,
      a `/` or a `.` is not a group;
    * `declares(term)` -- the BFO category `term` declares, if any. A category
      keeps the spelling BFO gives it and is never elected against (rule 22).
      Two members declaring DIFFERENT categories is a group that should not
      exist, and is reported rather than merged.

    The returned map contains only real changes: `x -> x` is never in it.
    """
    # ONE normalisation per label, reused for the grouping, the split and the
    # naming. Three separate helpers used to recompute it three times and,
    # worse, disagree about it.
    norm: dict[str, object] = {}
    for label in list(frequencies) + sorted(anchors) + sorted(others):
        if label not in norm:
            norm[label] = normalise(label)

    groups: dict[str, set[str]] = defaultdict(set)
    for label, n in norm.items():
        groups[n.key].add(label)

    renames: dict[str, str] = {}
    report: dict = {"groups": 0, "respelled": 0, "unsafe": [], "characters": [],
                    "declared": [], "ontology sense": [], "minted": 0}

    def _elect(members: set[str]) -> None:
        """Name one sub-group and record the renames onto that name."""
        declared = sorted({d for d in (declares(m) for m in members) if d})
        if declared:
            # Rule 22: the category vocabulary is spelled the way BFO spells
            # it, and nothing elects a different spelling for it. What matters
            # is which category is DECLARED, not how many members declare it:
            # `Quality` and `quality` both declare `quality`, and refusing the
            # group because two members answered would leave the store holding
            # two spellings of one category -- the exact bug rule 22 exists to
            # end.
            if len(declared) > 1:
                report["declared"].append(declared)
                return
            canonical = declared[0]
        else:
            ranked = {m: canonical_rank(m, anchors, frequencies)
                      for m in sorted(members)}
            # Below the ontology test and the corpus count, `canonical_rank`
            # falls back to WORD COUNT -- a longer label is the more specific
            # of two spellings. Inside a group that met over a SEAM that
            # reasoning is false by construction: the members are the same
            # words with the boundary somewhere else, so the extra word is
            # not more specific, it is a boundary in the wrong place.
            # `Cumberland Ankle Instability Tool` and `Cumberl and Ankle
            # Instability Tool` both appear in one abstract each, the corpus
            # said nothing, the extra word won, and pass 0 was about to
            # rename the instrument onto the typo.
            #
            # So when the corpus is silent, ask the language: a tokenisation
            # that invents a word loses to one that does not. Measured over
            # the 2026-09-26 store this changes exactly one election out of
            # 522 -- that one. It is deliberately the LAST word before word
            # count and never reaches past frequency: `postradiation` and
            # `antibiofilm` are not in a general-English list either, and the
            # corpus is entitled to prefer them.
            top = max(ranked.values())
            tied = [m for m, r in ranked.items() if r[:2] == top[:2]]
            if len(tied) > 1:
                fewest = min(invented_words(m) for m in tied)
                tied = [m for m in tied if invented_words(m) == fewest]
            winner = max(tied, key=ranked.__getitem__)
            canonical = winner if winner in anchors else norm[winner].name

        wrote = False
        for member in sorted(members):
            if member == canonical:
                continue
            renames[member] = canonical
            wrote = True
        if not wrote:
            return
        if canonical not in members:
            report["minted"] += 1
        # A term with no variant is respelled too, on the curator's instruction
        # of 2026-09-26: the canonical is the singular and it is American, so
        # `wounds` appearing without `wound` anywhere still becomes `wound`.
        # Counted apart from the groups, because settling a choice BETWEEN
        # spellings and rewriting the only spelling there is are different acts.
        report["respelled" if len(members) < 2 else "groups"] += 1

    for members in groups.values():
        # `fold` strips a trailing parenthetical, so `vitamin (role)` and
        # `vitamin` land together while meaning different things -- a role
        # class is not the substance.
        #
        # But MOST parentheticals are not a sense at all, they are the phrase's
        # own abbreviation: `quality of life (qol)`, `computed tomography (ct)`,
        # `ankle-brachial index (abi)`. Refusing every group that held one
        # blocked 84 of 88 groups on the 2026-09-26 data, including seven
        # spellings of `quality of life`. Two narrower questions replace it:
        #
        #   * do the members carry DIFFERENT parentheticals? Then the group is
        #     ambiguous and nothing merges. Folded, so `(prom)` and `(proms)`
        #     count as one gloss -- 1 group on this data.
        #   * is the member carrying it an ONTOLOGY label? There the
        #     parenthetical is part of the class's official name and a rule
        #     does not get to drop it -- 3 groups: `vitamin (role)`,
        #     `Chickenpox (varicella)`, `Herpes simplex (e.g. cold sores)`.
        #     Only the first is a real sense distinction; the other two are
        #     reported for a person to look at rather than guessed about.
        paren = {tuple(sorted(fold(x) for x in PARENTHETICAL.findall(m.lower())))
                 for m in members}
        if len({p for p in paren if p}) > 1:
            report["unsafe"].append(sorted(members))
            continue
        if (len(members) > 1 and any(p for p in paren)
                and any(m in anchors and PARENTHETICAL.search(m) for m in members)):
            report["ontology sense"].append(sorted(members))
            continue
        # SPLIT the group rather than condemn it. One odd member used to hold
        # the whole group back: `patient's` sitting beside `Patients`,
        # `patient` and `patients` stopped all three from merging. The
        # sub-groups are the terms; the split itself is what gets reported.
        by_characters: dict[str, set[str]] = defaultdict(set)
        for m in members:
            by_characters[norm[m].strict].add(m)
        if len(by_characters) > 1:
            report["characters"].append(
                sorted(sorted(v) for v in by_characters.values()))
        for members in by_characters.values():
            _elect(members)
    report["to write"] = len(renames)
    return renames, report
