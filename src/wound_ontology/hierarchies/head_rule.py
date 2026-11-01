"""The head-word rule for proposed superclass edges (rule 79).

The concept analysis names each formal concept with a model and used to
propose an edge from every member to that name, unchecked. On 2026-10-17 that
produced 352 proposals for the curator, all to model-made names, among them
`Burn Wound ⊑ Electrical Burn Wound`, `Wound ⊑ Cutaneous Disorder` and
`Second-Degree Burn Wound ⊑ Secondary Healing Burn Depth`. The curator: "Das
hätte vorher gelöst sein sollen."

A label is read as modifiers + head word. An edge child ⊑ parent is licensed
when the parent's head is the child's head or above it (config.head_word_rules
HEAD_LADDER) and the parent has no modifier the child lacks: burn wound ⊑ burn
injury ⊑ injury, burn wound ⊑ wound, never wound ⊑ burn injury. Two labels with
the same reading are one concept, not an edge. A head the rulings do not place
cannot be judged, and is not proposed (rule 66: precision over recall). A
verdict the curator gave on one edge outranks the rule for that edge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from config import head_word_rules as R

LICENSED, REFUSED, SYNONYM, OPEN = "licensed", "refused", "synonym", "open"
NOT_A_WOUND = "<not a wound>"
PROCESS = "<process>"


@dataclass(frozen=True)
class Reading:
    mods: frozenset
    head: str


def _label(label: str) -> tuple[str, set[str]]:
    """The label after the curator's whole-label rulings, and modifiers they add."""
    s = re.sub(r"\s+", " ", label.lower().strip().replace("’", "'"))
    extra: set[str] = set()
    m = re.search(r"\s+(?:classified\s+)?according to\s+(.*)$", s)
    if m:
        for system, mods in R.CLASSIFIED_BY.items():
            if system in m.group(1).split():
                extra |= mods
        s = s[:m.start()]
    s = re.sub(r"^wounds? classified$", "wound", s)
    s = R.LABEL_REWRITES.get(s, s)
    s = re.sub(R.WOUND_WITH, lambda m: m.group("h"), s)
    for pat, out in R.LATIN.items():
        mm = re.match(pat, s)
        if mm:
            s = out.format(*[R.LATIN_WORDS.get(g, g) for g in mm.groups()])
            break
    return s, extra


def _words(s: str) -> list[str]:
    s = s.replace("'s ", " ")
    if " of " in s:                                   # "burns of the ocular surface"
        head_part, site = s.split(" of ", 1)
        site_words = [w for w in site.split() if w not in ("the", "a", "an")]
        words = site_words + head_part.split()
    else:
        words = s.split()
    return [R.WORD_FORMS.get(w, w) for w in words]


def read(label: str) -> Reading:
    """modifiers + head of a label, after the curator's rulings."""
    s, extra = _label(label)
    if s in R.PROCESS_LABELS:
        return Reading(frozenset(s.split()), PROCESS)
    words = _words(s)
    if not words:
        return Reading(frozenset(), "")
    head = R.HEAD_SYNONYMS.get(words[-1], words[-1])
    mods: set[str] = set(extra)
    for w in words[:-1]:
        mods |= {R.WORD_FORMS.get(x, x) for x in w.split("-") if x}
    if head in R.SITE_DEPENDENT_HEADS:
        if mods & R.NOT_SKIN_SITE:
            if head in R.SITE_INJURY_HEADS:          # a meniscal tear is an injury, not a wound
                return Reading(frozenset(mods | {head}), "injury")
            return Reading(frozenset(mods | {head}), NOT_A_WOUND)   # a gastric ulcer is neither
        on_skin = bool(mods & R.SKIN_SITE)
        if head != "ulcer":                          # ulcer IS wound (rule 70): no modifier of its own
            mods.add(head)
        head = "wound" if on_skin else R.NO_SITE_HEAD[head]
    elif head in R.HEAD_AS:
        add, to = R.HEAD_AS[head]
        if head in R.SITE_INJURY_HEADS and mods & R.NOT_SKIN_SITE:
            to = "injury"                             # a burn of the ocular surface: not skin
        if head in R.HEAD_PROMOTED_BY and mods & R.HEAD_PROMOTED_BY[head][0]:
            to = R.HEAD_PROMOTED_BY[head][1]          # an open fracture is a wound
        mods |= add
        head = to
    for m, (implied, unless) in R.MOD_IMPLIES.items():
        if m in mods and not mods & unless:
            mods |= implied
    return Reading(frozenset(mods), head)


def _above(head: str) -> list[str]:
    out = [head]
    while R.HEAD_LADDER.get(out[-1]):
        out.append(R.HEAD_LADDER[out[-1]])
    return out


def judge(child: str, parent: str) -> tuple[str, str]:
    """(verdict, reason) for the edge child ⊑ parent, by the rule alone."""
    c, p = read(child), read(parent)
    if p.head in R.REFUSED_PARENT_HEADS:
        return REFUSED, f"'{parent}' is a collective name ({p.head}), never a superclass"
    if any(re.search(pat, parent.lower()) for pat in R.REFUSED_PARENT_PATTERNS):
        return REFUSED, f"'{parent}' names a way of dividing, not a kind"
    if c.head in R.VAGUE_HEADS:
        return REFUSED, f"'{child}' is too vague to place ({c.head})"
    if c.head == PROCESS or p.head == PROCESS:
        which = child if c.head == PROCESS else parent
        return REFUSED, f"'{which}' names the injuring process, not a wound or injury"
    if c.head == NOT_A_WOUND and p.head in R.HEAD_LADDER:
        return REFUSED, f"'{child}' is not on skin, so neither a wound nor an injury in WONT's sense"
    if c == p:
        return SYNONYM, f"'{child}' and '{parent}' read the same"
    if c.head == p.head and c.head not in R.HEAD_LADDER:
        # same kind of thing outside the ladder: diabetic foot ulcer ⊑ diabetic ulcer
        if p.mods < c.mods:
            return LICENSED, "same head, the parent's modifiers are the child's"
        return REFUSED, f"'{parent}' says {sorted(p.mods - c.mods)} that '{child}' does not"
    if c.head not in R.HEAD_LADDER or p.head not in R.HEAD_LADDER:
        unknown = [h for h in (c.head, p.head) if h not in R.HEAD_LADDER]
        return OPEN, f"head word {unknown[0]!r} has no place in the rulings yet"
    if p.head not in _above(c.head):
        return REFUSED, f"a {c.head} is not a {p.head}"
    if not p.mods <= c.mods:
        return REFUSED, f"'{parent}' says {sorted(p.mods - c.mods)} that '{child}' does not"
    return LICENSED, f"{c.head} ⊑ {p.head}, modifiers contained"


def canonical_names(names, known=()) -> dict[str, str]:
    """name -> the one name its reading goes by.

    A name that exists in the hierarchy stays itself. A model-made name that
    reads like an existing one is that one (`Ischemic Wounds` -> `Ischemic
    Wound`); two model-made names with one reading are one concept (`Diabetic
    Ulcer`, `Diabetes-Related Ulcer`), named by the shorter, then
    alphabetically first, so the choice is stable.
    """
    by_reading: dict[Reading, list[str]] = {}
    exact = {}
    for k in known:
        by_reading.setdefault(read(k), []).append(k)
        exact.setdefault(k.lower(), k)
    out: dict[str, str] = {}
    pending: dict[Reading, list[str]] = {}
    for n in names:
        r = read(n)
        if n.lower() in exact:
            out[n] = exact[n.lower()]
        elif r in by_reading:
            out[n] = sorted(by_reading[r], key=lambda s: (len(s), s))[0]
        else:
            pending.setdefault(r, []).append(n)
    for group in pending.values():
        first = sorted(set(group), key=lambda s: (len(s), s))[0]
        for n in group:
            out[n] = first
    return out


def sort_proposals(pairs, known=(), curator=None) -> dict[str, list[dict]]:
    """Judge proposed (child, parent) edges; parents go by their canonical name.

    `curator` maps (child, parent) in lower case -- the parent as proposed or
    as canonical -- to "yes" or "no": the curator's verdict on that one edge,
    which outranks the rule. Returns {verdict: [{child, parent, as, reason}]}
    with every pair in exactly one list, so a caller can report what it did
    with all of them (rule 1).
    """
    curator = {(a.lower(), b.lower()): v for (a, b), v in (curator or {}).items()}
    pairs = sorted(set((str(c), str(p)) for c, p in pairs))
    canon = canonical_names({p for _, p in pairs}, known=known)
    out: dict[str, list[dict]] = {LICENSED: [], REFUSED: [], SYNONYM: [], OPEN: []}
    seen = set()
    for child, parent in pairs:
        target = canon.get(parent, parent)
        if (child, target) in seen:
            continue
        seen.add((child, target))
        if target.lower() == child.lower():
            out[SYNONYM].append({"child": child, "parent": parent, "as": target,
                                 "reason": f"'{parent}' is '{child}' under another spelling"})
            continue
        said = curator.get((child.lower(), parent.lower())) or curator.get((child.lower(), target.lower()))
        if said in ("yes", "no"):
            verdict = LICENSED if said == "yes" else REFUSED
            reason = f"curator said {said} to this edge"
        else:
            verdict, reason = judge(child, target)
        out[verdict].append({"child": child, "parent": parent, "as": target, "reason": reason})
    return out
