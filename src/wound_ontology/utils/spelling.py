"""British to American spelling, before anything expensive is asked.

The curator's rule of 2026-09-25: exhaust the deterministic methods first, and
never let a model be asked about something a rule settles. Spelling variance is
the clearest case -- `oedema` and `edema` are one word, and no embedding or
model call should ever be spent discovering that.

Two layers, because one is not enough.

**`breame`** is a dictionary of known British/American pairs. It gets the
irregulars right (`tumour`, `analyse`, `labelled`, `paediatric`, `centre`) and,
more importantly, it knows what NOT to touch: `exercise`, `surprise`,
`advertise`, `comprise`, `expertise` and `promise` all survive it, where a naive
`-ise -> -ize` rewrite destroys them.

**Morphological patterns**, for what `breame` does not carry. It is general
English, not medical, and it misses `oedema`, `haematoma`, `ischaemia` and
`epithelialisation` -- wound-care vocabulary, not edge cases.

The patterns alone are dangerous, and were: guarded only by "the result occurs
somewhere in the corpus", they produced `toe -> te`, `four -> for`,
`anaerobic -> anerobic` and `expertise -> expertize`, the last because a typo in
one abstract made `expertize` "occur". So a pattern rewrite has to clear two
tests instead, both about evidence rather than the shape of the string:

1. **The original is not core English.** Nothing above `CORE_ZIPF` is touched.
   `four` (5.53), `exercise` (5.0), `surprise` (5.3), `precise` (4.6) are
   ordinary words that happen to end like British ones.
2. **The candidate is strictly more frequent than the original**, by `wordfreq`.
   That stops `expertise -> expertize` (4.06 against 0.00),
   `anaerobic -> anerobic` (2.97 against 0.00) and `toe -> te` (4.07 against
   4.07, not strictly greater), and allows `oedema -> edema` (2.16 -> 2.95) and
   `epithelialisation -> epithelialization` (0.00 -> 1.11).

A dictionary was tried as the first guard and dropped: `/usr/share/dict/words`
is Webster 1934, so it lists `oesophageal` as ordinary English and blocked a
rewrite that should happen. Frequency is the better witness, because it says
which spelling won rather than which one was once standard.
"""
from __future__ import annotations

import functools
import re

#: British endings and their American forms. Ordered: the longest, most
#: specific context first, so `-isation` is tried before `-ise`.
PATTERNS: tuple[tuple[str, str], ...] = (
    (r"isation\b", "ization"), (r"isations\b", "izations"),
    (r"isational\b", "izational"),
    (r"ise\b", "ize"), (r"ised\b", "ized"), (r"ising\b", "izing"),
    (r"ises\b", "izes"), (r"iser\b", "izer"), (r"isers\b", "izers"),
    (r"yse\b", "yze"), (r"ysed\b", "yzed"), (r"ysing\b", "yzing"),
    (r"yses\b", "yzes"),
    (r"our\b", "or"), (r"ours\b", "ors"),
    (r"re\b", "er"), (r"res\b", "ers"),
    (r"lled\b", "led"), (r"lling\b", "ling"), (r"llor\b", "lor"),
    (r"ae", "e"), (r"oe", "e"), (r"our", "or"),
)

WORD = re.compile(r"[A-Za-z]+")

#: `ae`, `oe` and the unanchored `our` match INSIDE a word rather than at its
#: end, so they are the ones that can fire on something that is not a word at
#: all. The unanchored `our` is what reaches `discolouration`, `behavioural`
#: and `tumourigenesis`, which the word-final rule cannot see. `irAEs` reaches the store title-cased as `Iraes`, the acronym
#: already lost, and became `Ires`. Six characters is the floor below which a
#: medical Greek/Latin root is not plausible: `oedema` (6), `anaemia` (7),
#: `ischaemia` (9) clear it, `iraes` (5) does not.
MID_WORD_MIN = 6
MID_WORD = ((r"ae", "e"), (r"oe", "e"), (r"our", "or"))

#: `-yses` is the plural of `-ysis`, not a British verb. `breame` reads
#: `analyses` as the verb and answers `analyzes`, and in a corpus of abstracts
#: it is the noun essentially every time -- `Statistical Analyses` became
#: `Statistical Analyzes`, which then singularises to `analyze` instead of
#: `analysis`. Pass 0 singularises the head noun BEFORE this runs, which fixes
#: it for `analyses`; this catches the same word arriving any other way.
NOUN_PLURAL_YSES = re.compile(r"[a-z]+yses\b")

#: Words `breame` rewrites that medical English does not. Found by listing every
#: conversion the 2026-09-25 corpus triggers -- 144 of them -- and reading the
#: list. The rest were right; these five are not, and four of them are not a
#: British/American question at all.
#:
#:   disc      intervertebral disc, optic disc, and DISC DIFFUSION, the standard
#:             antibiotic susceptibility method. American medicine writes disc.
#:             64 occurrences here.
#:   aesthetic the American Society for AESTHETIC Plastic Surgery. `esthetic`
#:             belongs to dentistry. 82 occurrences.
#:   gases     the plural of gas in every variety of English; `gasses` is the
#:             verb.
#:   gauge     needle gauge, wire gauge. `gage` is archaic.
#:   fillet    not a spelling variant of `filet`; a different word.
NEVER_CONVERT = frozenset({
    "disc", "discs", "aesthetic", "aesthetics", "aesthetically",
    "gases", "gauge", "gauges", "fillet", "fillets",
})

#: Above this Zipf frequency a word is core English and is never rewritten by a
#: pattern. `four`, `exercise`, `surprise`, `promise`, `precise`, `core`, `sure`
#: and `figure` all sit above it, and every one of them ends like something
#: British.
CORE_ZIPF = 4.5


@functools.lru_cache(maxsize=100_000)
def zipf(word: str) -> float:
    """How common `word` is in English, 0.0 if the language has never seen it.

    The one accessor (rule 44). Pass 0 asks it too -- a tokenisation that
    invents a word loses an election to one that does not -- so it is public
    and cached rather than reimported per caller.
    """
    from wordfreq import zipf_frequency
    return zipf_frequency(word, "en")


@functools.lru_cache(maxsize=100_000)
def american_word(word: str) -> str:
    """`word` in American spelling, or unchanged. Lowercase in, lowercase out."""
    from breame.spelling import get_american_spelling

    if word in NEVER_CONVERT or NOUN_PLURAL_YSES.fullmatch(word):
        return word
    known = get_american_spelling(word)
    if known and known != word:
        return known
    if zipf(word) >= CORE_ZIPF:
        return word
    for pattern, replacement in PATTERNS:
        if (pattern, replacement) in MID_WORD and len(word) < MID_WORD_MIN:
            continue
        candidate = re.sub(pattern, replacement, word)
        if candidate == word:
            continue
        if zipf(candidate) > zipf(word):
            return candidate
    return word


def american_spelling(label: str) -> str:
    """`label` with every word in American spelling, keeping its own casing.

    The casing of the original token is reapplied, so `Oedema` comes back as
    `Edema` and `OEDEMA` as `EDEMA`. A label nothing matches comes back
    identical, which is what makes this safe to run on everything, twice.
    """
    def one(match: re.Match) -> str:
        token = match.group(0)
        swapped = american_word(token.lower())
        if swapped == token.lower():
            return token
        if token.isupper():
            return swapped.upper()
        if token[:1].isupper():
            return swapped[:1].upper() + swapped[1:]
        return swapped

    return WORD.sub(one, label)
