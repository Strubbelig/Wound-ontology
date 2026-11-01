# -*- coding: utf-8 -*-
"""Each curation list must hold entries its own matching rule can carry.

Four lists, two rules:

  KEYWORD_BLOCKLIST      keyword — fires at a word START inside a term
  KEYWORD_WHITELIST      keyword
  METHODOLOGY_BLOCKLIST  term    — the whole string
  WHITELIST              term

The distinction had been lost. `KEYWORD_WHITELIST` held 1600 entries of three
or more words, the longest twenty words long, because the substring bug fixed
in 398aacf sent every interactive write for `WHITELIST` there instead -- and a
term entry filed as a keyword stops meaning what it meant. A twenty-word
phrase used as a keyword exempts every term containing it; `wound` used as a
keyword exempted 311 terms, which is how "Wound Reporting In Animal And Human
Preclinical Studies Reporting Standards" walked past the `reporting` keyword.

Measured 2026-09-09 over the 3559 live store terms and 550 curated labels: of
that whole 4104-term universe only 27 were candidates for blocking at all, 21
were vetoed by a whitelist, and 5326 of the 5336 whitelist entries were the
sole protector of nothing. These tests pin the shape the lists were put back
into, so the distinction cannot quietly collapse again.

They are shape tests, deliberately, not size tests. "Matches nothing today" is
the expected and healthy state of a preventive list -- 58 of the 69
KEYWORD_BLOCKLIST entries match nothing precisely because they already worked
-- so nothing here asserts a count.
"""
from __future__ import annotations

import pytest

from wound_ontology.store.term_lists import _starts_a_word

#: Demoted from KEYWORD_WHITELIST to WHITELIST on 2026-09-09. As keywords these
#: eight reached far enough to disable the blocklist; as terms they exempt
#: themselves and nothing else. `wound` alone covered 311 terms.
DEMOTED = ["wound", "treatment", "ulcer", "grade",
           "dressing", "injury", "burn", "pressure"]


@pytest.fixture(scope="module")
def lists():
    import config.blocklist as bl
    import config.whitelist as wl

    out = {"KEYWORD_BLOCKLIST": frozenset(bl.KEYWORD_BLOCKLIST),
           "METHODOLOGY_BLOCKLIST": frozenset(bl.METHODOLOGY_BLOCKLIST),
           "KEYWORD_WHITELIST": frozenset(wl.KEYWORD_WHITELIST),
           "WHITELIST": frozenset(wl.WHITELIST)}
    for name, entries in out.items():
        assert entries, f"{name} is empty; every test here would be vacuous"
    return out


@pytest.fixture(scope="module")
def blocker():
    from wound_ontology.store.store_cleaner import StoreCleaner

    c = StoreCleaner([])
    c._reload_lists()
    return c.blocker


@pytest.mark.parametrize("name", ["KEYWORD_BLOCKLIST", "KEYWORD_WHITELIST"])
def test_a_keyword_is_short_enough_to_be_a_keyword(lists, name):
    """Three or more words is a term, and belongs in the term list."""
    long = sorted(k for k in lists[name] if len(k.split()) >= 3)
    assert long == [], (
        f"{name} holds phrases, not keywords. A keyword matches inside other "
        f"terms, so these exempt or catch far more than themselves: {long[:10]}"
    )


@pytest.mark.parametrize("name", ["KEYWORD_BLOCKLIST", "KEYWORD_WHITELIST"])
def test_no_keyword_is_already_covered_by_a_shorter_keyword(lists, name):
    """A keyword a shorter keyword already reaches can never change an outcome.

    1544 of the 3186 KEYWORD_WHITELIST entries were in this state. Removing
    them is safe by the lemma below and by nothing softer.
    """
    entries = sorted(lists[name], key=len)
    covered = [(long, short) for i, long in enumerate(entries)
               for short in entries[:i]
               if short != long and _starts_a_word(short, long)]
    assert covered == [], (
        f"{name} entries reachable by a shorter entry in the same list: "
        f"{covered[:10]}"
    )


def test_keyword_coverage_passes_through_a_containing_keyword():
    """The lemma that makes the test above safe to enforce.

    If `short` starts a word inside `long`, then every term `long` covers,
    `short` covers as well -- so dropping `long` cannot un-cover anything. It
    holds at offset zero and at an interior word start alike, which is the case
    worth pinning: the character before `short` inside `long` is the same
    character that precedes it inside the term.
    """
    for short, long in (("wound", "wound healing"),        # offset zero
                        ("healing", "wound healing"),      # interior
                        ("ulcer", "diabetic foot ulcer")):
        assert _starts_a_word(short, long), (short, long)
        for term in ("chronic " + long, long + " assessment", long):
            assert _starts_a_word(long, term)
            assert _starts_a_word(short, term), (short, term)


def test_no_term_is_whitelisted_and_blocklisted_at_once(lists):
    """`antimicrobial` and `dressing` sat on METHODOLOGY_BLOCKLIST and were
    saved only by the accident of also being broad whitelist keywords."""
    both = sorted((lists["KEYWORD_WHITELIST"] | lists["WHITELIST"])
                  & (lists["KEYWORD_BLOCKLIST"] | lists["METHODOLOGY_BLOCKLIST"]))
    assert both == [], f"on a whitelist and a blocklist at the same time: {both}"


@pytest.mark.parametrize("word", DEMOTED)
def test_a_demoted_keyword_exempts_itself_and_nothing_else(lists, blocker, word):
    """It must be gone from the keyword list AND present in the term list.

    Removal alone would have dropped the exemption entirely; the point was to
    narrow it to the word itself, not to withdraw it.

    The membership check is case-insensitive because the list is now GENERATED
    from the gate (rule 40) and carries whichever spelling pass 0 elected: the
    store says `Wound` more often than `wound`, so that is the spelling on
    record. `TermList.match` lowercases (rule 13), so the exemption is
    unaffected — and the three assertions below are the ones that say so.
    Asserting the exact casing would pin a spelling nothing depends on.
    """
    assert word not in lists["KEYWORD_WHITELIST"]
    assert not blocker.is_blocked(word)
    assert not blocker.white_kw.match(word)
    # Rule 70 (2026-10-04): `ulcer` is now written `Wound` -- the term dict keeps
    # the word as an alias and the exemption follows the name it is written as.
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    g = TermMappingAndGate(DataManager(), file_name="term_mapping")
    written = g.resolve(word) if g.is_alias(word) else word
    assert written.lower() in {t.lower() for t in lists["WHITELIST"]}
    assert blocker.white_terms.match(written)


def test_the_broad_keywords_no_longer_wave_methodology_through(blocker):
    """What demoting them was for, in the terms it actually changed.

    Each of these is in the live store, each is caught by a KEYWORD_BLOCKLIST
    entry that means it, and each was exempted only because it happened to
    contain one of the eight demoted words.

    Since rule 40 a keyword catch is no longer the last word: a `curator` or
    `pass` verdict on the record outranks it, which is the whole point of the
    gate. `Conventional Treatment` is the live example -- the 2026-09-25 scope
    pass called it "treatment used in wound care" and it is in scope again on
    purpose. So what this pins is the KEYWORD still matching; whether the term
    ends up blocked is the gate's business, and `blocker` here carries none.
    """
    assert blocker.gate is None, "this fixture must be the lists alone"
    for term, caught_by in (
        ("Wound Reporting In Animal And Human Preclinical Studies "
         "Reporting Standards", "reporting"),
        ("Conventional Treatment", "conventional"),
        ("Tertiary Wound Care Setting", "tertiary"),
        ("Education Prevention Treatment Approach", "education"),
        ("Structured Treatment Algorithm", "structured"),
        ("Burn Models", "model"),
        # `pain` was a keyword here until 2026-09-26, when the curator ruled
        # the concept in scope and it came off KEYWORD_BLOCKLIST. `Visual
        # Analog Scale Pain Score` is still out -- the exact
        # METHODOLOGY_BLOCKLIST catches it and pass 2 says `out` -- which is
        # the direction rule 40 was always going: an explicit record about the
        # instrument rather than a broad word that also caught the symptom.
        # Measured at the removal: of 86,489 store names, dropping the keyword
        # freed exactly 2.
    ):
        assert blocker.block_kw.match(term), f"{term!r} no longer caught by {caught_by!r}"
        if blocker.is_blocked(term):
            continue
        # Exempt is allowed now, but only with something on the record saying
        # so. An exemption nobody can account for is what rule 40 removed.
        assert (blocker.white_terms.match(term) or blocker.white_kw.match(term)), (
            f"{term!r} is exempt and nothing explains it")


def test_demoting_them_did_not_open_the_gate_on_the_domain(blocker):
    """The other half: ordinary wound vocabulary must still pass.

    These are the terms the broad keywords were plausibly there to protect, and
    each survives on a narrower entry of its own.
    """
    for term in ("wound bed", "chronic wound", "diabetic foot ulcer",
                 "pressure ulcer", "burn wound", "wound healing",
                 "negative pressure wound therapy", "compression therapy"):
        assert not blocker.is_blocked(term), term


# ── the config modules hold lists; the rule lives in one place ────────────────

#: Every public name each config module is allowed to export. `is_noise_term`
#: earns its place -- `Blocker.is_noise` imports it. The two that were removed
#: on 2026-09-09, `contains_blocked_keyword` and `contains_whitelisted_keyword`,
#: did not: both were dead (zero callers across `*.py`, all five notebooks and
#: `*.md`) and both did `any(kw in lower for kw in ...)` -- the plain-substring
#: match rule 27 forbids and `KeywordList.match` was fixed to avoid. A second,
#: wrong implementation of the project's central rule, sitting where someone
#: would reasonably reach for it.
CONFIG_SURFACE = {
    "config.blocklist": {"KEYWORD_BLOCKLIST", "METHODOLOGY_BLOCKLIST", "is_noise_term"},
    "config.whitelist": {"KEYWORD_WHITELIST", "WHITELIST"},
    "config.suspicious_list": {"SUSPICIOUS_KEYWORDS"},
}


@pytest.mark.parametrize("module_name,allowed", sorted(CONFIG_SURFACE.items()))
def test_a_config_module_holds_lists_not_matching_logic(module_name, allowed):
    """One keyword rule, in one place: `KeywordList.match`."""
    import importlib

    module = importlib.import_module(module_name)
    public = {n for n in vars(module) if not n.startswith("_")}
    assert public == allowed, (
        f"{module_name} exports {sorted(public - allowed)} beyond its lists. "
        "If that is a matcher, there is now more than one keyword rule in the "
        "project and they will disagree; see INSTRUCTIONS rule 27"
    )


# ── one entry per line, in every list literal ─────────────────────────────────

LIST_LITERALS = [
    ("config/blocklist.py", "KEYWORD_BLOCKLIST"),
    ("config/blocklist.py", "METHODOLOGY_BLOCKLIST"),
    ("config/whitelist.py", "KEYWORD_WHITELIST"),
    ("config/whitelist.py", "WHITELIST"),
    ("config/suspicious_list.py", "SUSPICIOUS_KEYWORDS"),
]


@pytest.mark.parametrize("rel,var", LIST_LITERALS)
def test_every_list_literal_is_written_one_entry_per_line(rel, var):
    """The format the persistence layer can remove from.

    `_pylist_remove` deletes a line only when the line holds exactly one entry.
    KEYWORD_BLOCKLIST (69 entries on 27 lines) and SUSPICIOUS_KEYWORDS (84 on
    29) were packed several to a line, so removing from either removed nothing,
    returned 0 and said nothing -- while adding worked, because the writer
    appends one per line. Unpacked 2026-09-09.
    """
    import pathlib
    import re

    from wound_ontology.store.term_lists import _entry_value

    path = pathlib.Path(__file__).resolve().parents[1] / rel
    lines = path.read_text().splitlines()
    inside = depth = 0
    started = False
    packed = []
    entries = 0
    for n, line in enumerate(lines, 1):
        if not started:
            if re.match(rf"\s*{re.escape(var)}\s*[:=]", line) and "{" in line:
                started = True
                depth += line.count("{") - line.count("}")
            continue
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if _entry_value(line) is None:
            packed.append((n, text[:70]))
        else:
            entries += 1
    assert started, f"{var} not found in {rel}"
    assert entries, f"no entries parsed out of {var}; this test would be vacuous"
    assert packed == [], (
        f"{rel}:{var} has {len(packed)} line(s) the remover cannot parse as a "
        f"single entry, so those entries cannot be removed: {packed[:5]}"
    )
