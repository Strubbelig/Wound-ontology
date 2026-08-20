# -*- coding: utf-8 -*-
"""Render the generated extraction schema into LLM prompt text.

Hand-written on purpose. `extraction_models.py` is generated and holds only
data plus validation; presentation lives here so regenerating the schema never
clobbers prompt wording.

The two-stage split this supports (plan C2):

  Stage 1  typing_prompt()      one categorical choice per term, ~11 options,
                                no relational reasoning at all.
  Stage 2  relation_prompt()    the category pair is known, so the candidate
                                relations are looked up, not reasoned about.
                                If exactly one relation is licensed there is
                                nothing to ask.

Grounding blocks are sliced per category, so a stage-2 prompt carries the ~40
terms of one category rather than all 409.
"""
from __future__ import annotations

from wound_ontology.llm.extraction_models import (
    CATEGORY_GLOSS,
    CATEGORY_PARENT,
    COARSE_CATEGORIES,
    DEFINITIONS,
    GROUNDING,
    RELATION_DOMAINS,
    relations_are_certain,
    relations_for,
)

_MAX_DEF = 240


def category_block() -> str:
    """The stage-1 option list, shown as the BFO tree with fallbacks marked."""
    kids: dict[str | None, list[str]] = {}
    for name, parent in CATEGORY_PARENT.items():
        kids.setdefault(parent, []).append(name)

    lines = ["Assign each term to EXACTLY ONE category from this tree:", ""]

    def walk(parent, depth):
        for name in kids.get(parent, []):
            pad = "  " + "    " * depth
            tag = "  [FALLBACK]" if name in COARSE_CATEGORIES else ""
            lines.append(f"{pad}{name}{tag}: {CATEGORY_GLOSS[name]}")
            walk(name, depth + 1)

    walk(None, 0)
    lines += [
        "",
        "RULES",
        "1. Every term must get a category. There is no 'unknown' and no skipping.",
        "2. Prefer the most specific category you are confident in.",
        "3. If you are NOT confident, move UP the tree and pick the nearest ancestor "
        "you are sure of. A [FALLBACK] answer is a correct answer, not a failure — "
        "'Continuant' when you cannot tell a substance from a quality is better than "
        "guessing 'MaterialEntity'. Coarse answers are flagged for human refinement; "
        "a confident wrong answer is not.",
        "4. Choose on what the term IS, not what it is associated with. Something that "
        "unfolds over time is a Process even when it also names a condition. Something "
        "that raises a probability rather than describing a present state is a Tendency.",
    ]
    return "\n".join(lines)


def grounding_block(category: str, limit: int | None = None,
                    with_definitions: bool = True) -> str:
    """Existing MILD/WONT terms for one category, with their definitions."""
    table = GROUNDING.get(category, {})
    if not table:
        return f"No existing {category} terms."
    labels = sorted(table)
    if limit is not None:
        labels = labels[:limit]
    lines = [
        f"Existing {category} terms ({len(table)}). Reuse one of these labels verbatim "
        f"when the text means the same thing; otherwise give the new term as it appears "
        f"in the text and leave it ungrounded:"
    ]
    for lab in labels:
        d = DEFINITIONS.get(lab) if with_definitions else None
        if d:
            if len(d) > _MAX_DEF:
                d = d[: _MAX_DEF - 1].rstrip() + "…"
            lines.append(f"  - {lab}: {d}")
        else:
            lines.append(f"  - {lab}")
    return "\n".join(lines)


def relation_block(subject_category: str, object_category: str) -> str:
    """The relations MILD/WONT license between two categories."""
    allowed = relations_for(subject_category, object_category)
    head = f"{subject_category} -> {object_category}"
    if not relations_are_certain(subject_category, object_category):
        if not allowed:
            return (f"{head}: no relation is licensed for any refinement of these "
                    f"categories. Assert nothing.")
        return (f"{head}: at least one category is a fallback, so this list is the "
                f"widest possibility, not a confirmed set - {allowed}. "
                f"Prefer asserting nothing unless the text is explicit.")
    if not allowed:
        return (f"{head}: MILD/WONT license NO relation in this direction. "
                f"Assert nothing; if the text seems to state one, at least one of the "
                f"two terms is typed wrongly.")
    if len(allowed) == 1:
        return (f"{head}: exactly one relation is licensed - {allowed[0]}. "
                f"Use it or assert nothing.")
    return f"{head}: choose one of {allowed}, or assert nothing."


def typing_prompt(text: str, categories: list[str] | None = None,
                  with_definitions: bool = False) -> str:
    """Stage 1 - typing only. Deliberately asks for no relations."""
    cats = categories or list(CATEGORY_GLOSS)
    parts = [
        "Extract every distinct wound-care term from the text below and assign each one "
        "a category. Do NOT assert any relations; that is a separate step.",
        "",
        category_block(),
    ]
    if with_definitions:
        parts += ["", "Terms already in the ontology, by category:"]
        for c in cats:
            if GROUNDING.get(c):
                parts += ["", grounding_block(c)]
    parts += ["", "TEXT:", text]
    return "\n".join(parts)


def relation_prompt(text: str, typed_terms: dict[str, str]) -> str:
    """Stage 2 - relations, restricted to what the category pairs license.

    typed_terms: {label: category}, the accepted output of stage 1.
    """
    labels = sorted(typed_terms)
    lines = [
        "The terms below have already been typed. Assert only relations that the "
        "licensing table permits. Assert nothing where no relation is licensed.",
        "",
        "TYPED TERMS:",
    ]
    for lab in labels:
        lines.append(f"  {lab} : {typed_terms[lab]}")

    pairs = sorted({(typed_terms[a], typed_terms[b])
                    for a in labels for b in labels if a != b})
    lines += ["", "LICENSING TABLE:"]
    for sc, oc in pairs:
        lines.append("  " + relation_block(sc, oc))
    lines += ["", "TEXT:", text]
    return "\n".join(lines)


def schema_digest() -> str:
    """One-line-per-category summary, for logs and prompt headers."""
    rows = [f"{c}={len(t)}" for c, t in GROUNDING.items()]
    return (f"WONT/MILD extraction schema: {sum(len(t) for t in GROUNDING.values())} terms "
            f"({', '.join(rows)}); {len(RELATION_DOMAINS)} relations.")
