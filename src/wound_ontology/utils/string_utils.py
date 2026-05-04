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
