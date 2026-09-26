"""Pass 0: the merges a rule can settle, decided before any model is asked.

The curator's rule of 2026-09-25 -- exhaust the deterministic methods first, and
never pay a model to notice that `Surgical Site Infection` and `surgical site
infections` are one thing. Measured on the 2026-09-25 store, **9,650 of 96,243
terms are a pure spelling variant of another**: 5,638 needing only the singular
rule, 3,027 case alone, 584 a hyphen, 272 British spelling. The mapping had
found 2,820 of them.

Four steps, in this order:

1. the head noun to the singular (`singular_spelling`, rule 23a);
2. British to American (`utils.spelling`, rule 41);
3. case, hyphens and punctuation folded (`fold`);
4. group on the result, and map every member onto one spelling.

Singular BEFORE spelling: `Statistical Analyses` becomes `Statistical Analysis`
and the noun never reaches the British-verb reading of `analyses` that `breame`
answers with `analyzes` -- which would then singularise to `analyze`.

The logic is here rather than on the Orchestrator so it can be tested against
plain dicts. The Orchestrator supplies the store's frequencies, the ontology's
labels and the mapping, and writes what comes back.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable

from wound_ontology.mappers.term_mapper import canonical_rank
from wound_ontology.utils.label_match import fold, singular_spelling
from wound_ontology.utils.spelling import american_spelling

PARENTHETICAL = re.compile(r"\(([^)]*)\)")


def _final(term: str, mapping: dict[str, str]) -> str:
    """Where `term` ends up once the existing mapping is followed to the end.

    Pass 0 chooses a canonical from the spellings it can see, and that spelling
    may itself already be mapped somewhere -- often by a curator, whose entry
    pass 0 must not touch. Writing `member -> canonical` then makes a CHAIN,
    and `ConceptStore.normalize` follows exactly one hop, so the merge
    half-lands. On 2026-09-26 this produced 2,506 chained entries and a
    `resolve_chains` that could not reach a fixed point, because 101 of the
    links were curator entries it is not allowed to re-point.

    So the target is resolved here, against the mapping as it stands, and the
    chain is never created. A loop in the existing data stops the walk rather
    than hanging.
    """
    seen = {term}
    while term in mapping:
        term = mapping[term]
        if term in seen:
            break
        seen.add(term)
    return term


def normalised_label(label: str) -> str:
    """`label` as pass 0 would rather see it written: singular, American."""
    return american_spelling(singular_spelling(label))


def group_key(label: str) -> str:
    """The key two spellings of one thing share."""
    return fold(normalised_label(label))


def pass0_pairs(
    frequencies: dict[str, int],
    anchors: set[str],
    mapping: dict[str, str],
    is_curated: Callable[[str, str], bool] = lambda term, canonical: False,
) -> tuple[dict[str, str], dict]:
    """`({term: canonical}, report)` -- every merge a rule settles.

    `frequencies` is the store's terms and how many abstracts each appears in.
    `anchors` are the ontology's own labels, which outrank any store spelling
    (rule 36) and are kept EXACTLY as the ontology writes them. `mapping` is
    what already stands, so a pair already written is not written again.
    `is_curated(term, canonical)` guards a pair a person has ruled on.

    Refusals are not checked here -- `add_batch` skips them and returns them,
    and one enforcement point is better than two (rule 38).
    """
    groups: dict[str, set[str]] = defaultdict(set)
    for name in list(frequencies) + sorted(anchors):
        groups[group_key(name)].add(name)

    pairs: dict[str, str] = {}
    report = {"groups": 0, "respelled": 0, "unsafe": [], "curated": [],
              "cyclic": [], "already": 0, "minted": 0}
    for members in groups.values():
        in_store = {m for m in members if m in frequencies}
        if not in_store:
            continue
        # `fold` strips a trailing parenthetical, so `vitamin (role)` and
        # `vitamin` land together while meaning different things -- a role class
        # is not the substance. Restore them and refuse the group if they stop
        # agreeing. One group on the 2026-09-25 store, and it is that one.
        if len({tuple(PARENTHETICAL.findall(m.lower())) for m in members}) > 1:
            report["unsafe"].append(sorted(members))
            continue
        winner = max(sorted(members), key=lambda t: canonical_rank(t, anchors,
                                                                   frequencies))
        canonical = winner if winner in anchors else normalised_label(winner)
        canonical = _final(canonical, mapping)
        if canonical in mapping:
            # `_final` only returns a mapped term when it walked into a LOOP in
            # the data it was given, and there were 52 of those on 2026-09-26.
            # Merging into a loop puts the merge somewhere `resolve_chains` is
            # about to break; the loop is the thing to fix, and naming it is
            # more use than adding to it.
            report["cyclic"].append((sorted(in_store), canonical))
            continue
        wrote = False
        for member in sorted(in_store):
            if member == canonical:
                continue
            if mapping.get(member) == canonical:
                report["already"] += 1
                continue
            if is_curated(member, mapping.get(member) or canonical):
                report["curated"].append((member, mapping.get(member)))
                continue
            pairs[member] = canonical
            wrote = True
        if not wrote:
            continue
        if canonical not in members:
            report["minted"] += 1
        # A term with no variant is respelled too, on the curator's instruction
        # of 2026-09-26: the canonical is the singular and it is American, so
        # `wounds` appearing without `wound` anywhere still becomes `wound`.
        # Counted apart from the groups, because settling a choice BETWEEN
        # spellings and rewriting the only spelling there is are different acts.
        report["respelled" if len(members) < 2 else "groups"] += 1
    report["to write"] = len(pairs)
    return pairs, report
