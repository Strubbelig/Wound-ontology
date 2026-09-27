"""ONE normaliser. Every question about how a term is written is asked here.

The curator, 2026-09-26: *why are there several functions for normalising? One
is enough.* There were three -- `normalised_label`, `group_key` and
`character_key`, each hand-rolling the same steps in its own order -- and every
bug in them was the same bug: a new one disagreeing with the old ones about
where a step goes. In one afternoon that produced `Ulcers (DFU)` never reaching
`ulcer` (parenthetical stripped after singularising), `Case` and `cases` read
as different strings (the lookup singulariser instead of the naming one),
`DFU`/`DFUs` held apart (lowercased before the acronym rule could fire), and
`OUTCOME MEASURES` held apart from `outcome measure` (lowercased after it).

So the order of the steps, and what each class of character is worth, live in
exactly one function. It answers three questions about a label at once, because
they are three projections of one pipeline and not three pipelines:

    name    what the term should be CALLED
    key     what two spellings of one term SHARE
    strict  the key, keeping every character `fold` would throw away

A word boundary is not one of the characters a spelling is allowed to differ
in, so `key` and `strict` carry no spaces at all: a hyphen, a space and
nothing are three ways of writing one seam, and `intra-abdominal`,
`intra abdominal` and `intraabdominal` are one term written three ways. The
curator, 2026-09-27, on being asked to adjudicate the last pair by hand: *this
should have been treated by the dehyphenation.* It was not, because
`normalize_term` turns a hyphen into a SPACE, so the dehyphenated spelling
never met the undashed one -- and a U+2011 hyphen is deleted outright instead,
which left `re-tear` folding to `re tear` while `re\u2011tear` folded to
`retear`. The seam is removed LAST, after the head noun is singularised,
because `singular_spelling` needs the words to still be words.

`strict` exists because `normalize_term` strips all punctuation, and that is
how `Na+` meets `NA`, `Phase I/II` meets `Phase III` and `P < 0.05` meets
`P > 0.05`. Two labels with the same `key` and a different `strict` are not two
spellings of one term; they are two terms that met by losing a character.
"""
from __future__ import annotations

import re
from wound_ontology.utils.label_match import fold, singular_spelling
from wound_ontology.utils.spelling import american_spelling

#: `(DFU)`, `(qol)` -- an abbreviation of the phrase, or a sense qualifier on
#: an ontology label. `fold` drops it; pass 0 decides per group which it was.
PARENTHETICAL = re.compile(r"\(([^)]*)\)")

#: `normalize_term` turns the ASCII hyphen and underscore into a space, and its
#: blanket punctuation strip then DELETES every other dash. `re‑tear` in the
#: corpus carries U+2011, invisible in a diff, and `fold` reads it as `retear`.
#: `strict` has to treat dashes the same way or it would flag a group over the
#: very difference folding exists to ignore.
UNICODE_DASHES = re.compile(r"[‐-―]")
ASCII_DASHES = re.compile(r"[-_]")
WHITESPACE = re.compile(r"\s+")

#: Canonical vocabulary chosen by the curator.  These are deliberately small,
#: explicit rules rather than a general synonym table: each one says which of
#: two already-adjudicated names survives.  Inflected forms are listed too
#: because only a label's head noun is singularised.
CANONICAL_WORDS = {
    "action": "activity",
    "actions": "activities",
    "alteration": "change",
    "alterations": "changes",
    "cutaneous": "skin",
    "dermatological": "dermatologic",
    "evaluation": "assessment",
    "evaluations": "assessments",
    "feature": "characteristic",
    "features": "characteristics",
    "full": "complete",
    "histopathologic": "histopathological",
    "limb": "extremity",
    "limbs": "extremities",
    "microbiological": "microbial",
    "numerical": "numeric",
    "oncological": "oncologic",
    "operation": "surgery",
    "operations": "surgeries",
    "pharmacological": "pharmacologic",
    "physiological": "physiologic",
    "preventative": "preventive",
    "previous": "prior",
    "radiological": "radiologic",
    "specimen": "sample",
    "specimens": "samples",
    "strategy": "approach",
    "strategies": "approaches",
    "technique": "method",
    "techniques": "methods",
    "testing": "test",
    "trauma": "injury",
    "traumas": "injuries",
    "usage": "use",
    "usages": "uses",
    "value": "level",
    "values": "levels",
}
CANONICAL_WORD = re.compile(
    r"\b(?:" + "|".join(
        sorted(map(re.escape, CANONICAL_WORDS), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

#: These six choices cross a noun/adjective boundary, so they apply only when
#: the word modifies a following noun-like token.  The blockers are relations
#: and constructions where the word is the head instead (`inflammation in the
#: wound`, `diabetes-related complication`).
CANONICAL_MODIFIERS = {
    "bony": "bone",
    "cellular": "cell",
    "diabetes": "diabetic",
    "infectious": "infection",
    "inflammation": "inflammatory",
    "surgery": "surgical",
}
CANONICAL_MODIFIER = re.compile(
    r"\b(?:" + "|".join(sorted(CANONICAL_MODIFIERS, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)
MODIFIER_FOLLOWER = re.compile(r"^[\s-]+([A-Za-z]+)")
MODIFIER_BLOCKERS = frozenset({
    "after", "and", "as", "associated", "based", "before", "by", "caused",
    "dependent", "during", "for", "from", "in", "induced", "mediated", "of",
    "on", "or", "related", "specific", "to", "versus", "vs", "with", "without",
})

WOUND_MANAGEMENT = re.compile(
    r"(?P<prefix>\bwound[\s-]+)(?P<word>management)\b", re.IGNORECASE)
POSTSURGICAL = re.compile(r"\bpost(?:[\s-]+)?surgical\b", re.IGNORECASE)


def _with_case_of(source: str, replacement: str) -> str:
    """Write `replacement` with the ordinary casing pattern of `source`."""
    if source.isupper():
        return replacement.upper()
    if source.istitle():
        return replacement.title()
    return replacement


def canonical_vocabulary(label: str) -> str:
    """Apply the curator's unambiguous preferred-name rules to `label`.

    `management` is changed only in the phrase `wound management`; a general
    management/care rewrite would conflate many unrelated concepts.  Word
    boundaries keep `limbic` and similar words out.  The function preserves
    lower, title and upper case and is idempotent.
    """
    label = WOUND_MANAGEMENT.sub(
        lambda match: (match.group("prefix")
                       + _with_case_of(match.group("word"), "care")),
        label,
    )
    label = POSTSURGICAL.sub(
        lambda match: _with_case_of(match.group(0), "postoperative"), label)
    label = CANONICAL_WORD.sub(
        lambda match: _with_case_of(
            match.group(0), CANONICAL_WORDS[match.group(0).lower()]),
        label,
    )

    def modifier(match: re.Match) -> str:
        follower = MODIFIER_FOLLOWER.match(label[match.end():])
        if not follower or follower.group(1).lower() in MODIFIER_BLOCKERS:
            return match.group(0)
        return _with_case_of(
            match.group(0), CANONICAL_MODIFIERS[match.group(0).lower()])

    return CANONICAL_MODIFIER.sub(modifier, label)


class Normalised:
    """What one label is called, what it shares, and what it keeps.

    The three are computed on first use and then held, because the ingestion
    path asks 179,000 times for `name` alone and has no use for the other two.
    """

    __slots__ = ("label", "_name", "_key", "_strict")

    def __init__(self, label: str) -> None:
        self.label = label
        self._name: str | None = None
        self._key: str | None = None
        self._strict: str | None = None

    @property
    def name(self) -> str:
        """What the term should be CALLED.

        Singular head noun (rule 23a), British to American (rule 41), then the
        curator's preferred vocabulary (rules 48–49), in that order. `Statistical
        Analyses` becomes `Statistical Analysis` and the noun never reaches the
        British-verb reading of `analyses` that `breame` answers with
        `analyzes`. The writer's own case is kept -- this is a name, not a key
        -- and so is any parenthetical, because on an ontology label it is part
        of the official name (`vitamin (role)`).
        """
        if self._name is None:
            self._name = canonical_vocabulary(
                american_spelling(singular_spelling(self.label)))
        return self._name

    @property
    def key(self) -> str:
        """What two spellings of one term SHARE.

        `fold` lowercases, drops the parenthetical, flattens hyphens, strips
        the remaining punctuation and singularises the head again; then every
        word boundary goes, so a seam written as a hyphen, as a space or as
        nothing at all reads the same. Built on the NAME rather than the raw
        label so the British and singular rules are already applied and two
        spellings cannot disagree about them.
        """
        if self._key is None:
            self._key = WHITESPACE.sub("", fold(self.name))
        return self._key

    @property
    def strict(self) -> str:
        """The key, keeping every character `fold` would throw away.

        The parenthetical goes first, or the singulariser is handed `(dfu)` as
        the head noun and `Ulcers (DFU)` never reaches `ulcer`. Dashes are
        treated exactly as `normalize_term` treats them, or this would flag a
        group over the very difference folding exists to ignore. Then the head
        is singularised on BOTH sides of the lowercasing, because
        `singular_spelling` reads case and the two all-caps rules pull opposite
        ways: `DFUs` is an acronym plural only while it still has its capitals,
        and `OUTCOME MEASURES` only stops being exempt from rule 23a once it
        loses them. Safe to apply twice -- the function is unchanged on an
        already-singular head. The spaces go last, with `key`'s, or a group
        `key` merged over a seam would be split straight back apart by the
        very difference it was merged over.
        """
        if self._strict is None:
            bare = PARENTHETICAL.sub("", self.label)
            bare = ASCII_DASHES.sub(" ", UNICODE_DASHES.sub("", bare))
            bare = WHITESPACE.sub(" ", bare).strip()
            self._strict = WHITESPACE.sub("", canonical_vocabulary(
                american_spelling(
                    singular_spelling(singular_spelling(bare).lower()))))
        return self._strict

    def __repr__(self) -> str:                          # pragma: no cover
        return f"Normalised({self.label!r})"


def normalise(label: str) -> Normalised:
    """The one answer. See the module docstring for what each field is for."""
    return Normalised(label)
