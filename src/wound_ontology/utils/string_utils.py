from __future__ import annotations

import re


def normalize_term(s: str) -> str:
    """
    Canonical surface-form normalization for biomedical term strings.

    Applies in order:
      1. Lowercase
      2. Strip parenthetical abbreviations  e.g. "(DFU)" → removed
      3. Replace hyphens / underscores with spaces
      4. Strip remaining punctuation
      5. Collapse whitespace

    Result is a clean, lowercase token sequence suitable for exact-string
    comparison or as a display-name base before .title().

    Examples:
      "Wound Healing"              → "wound healing"
      "full-thickness"             → "full thickness"
      "Diabetic Foot Ulcer (DFU)" → "diabetic foot ulcer"
      "deep-partial thickness"     → "deep partial thickness"
    """
    s = s.lower()
    s = re.sub(r'\([^)]*\)', '', s)     # strip (abbreviations)
    s = re.sub(r'[-_]', ' ', s)         # hyphen/underscore → space
    s = re.sub(r'[^\w\s]', '', s)       # strip remaining punctuation
    return re.sub(r'\s+', ' ', s).strip()


def smart_title(s: str) -> str:
    """Title-case a label WITHOUT destroying acronyms, units or roman numerals.

    `str.title()` uppercases the first letter of every alphabetic run and
    lowercases the rest, which mangles exactly the terms a clinical ontology is
    full of::

        "CO2 bath wound therapy"        -> "Co2 Bath Wound Therapy"
        "MRSA infection"                -> "Mrsa Infection"
        "type II diabetes"              -> "Type Ii Diabetes"
        "pH value"                      -> "Ph Value"
        "CUSA(r) assisted debridement"  -> "Cusa(R) Assisted Debridement"

    Those mangled forms then become the matching key, so the same concept can
    fail to match itself and label-based grounding degrades.

    Rule: a token is left EXACTLY as written when it already carries case
    information worth keeping — it contains a digit, or an uppercase letter
    anywhere but a lone leading one. Otherwise it is capitalised normally.
    """
    def cap(part: str) -> str:
        if not part:
            return part
        if any(ch.isdigit() for ch in part):
            return part                     # CO2, 2nd, IIb
        uppers = [i for i, ch in enumerate(part) if ch.isupper()]
        if uppers and uppers != [0]:
            return part                     # MRSA, pH, V.A.C., CUSA
        return part[:1].upper() + part[1:]

    def fix(tok: str) -> str:
        """Capitalise across '/' and '-' boundaries too, matching str.title(),
        but protect any sub-part that already carries meaningful case."""
        out, buf = [], ""
        for ch in tok:
            if ch in "/-":
                out.append(cap(buf))
                out.append(ch)
                buf = ""
            else:
                buf += ch
        out.append(cap(buf))
        return "".join(out)

    return " ".join(fix(t) for t in s.strip().split(" "))
