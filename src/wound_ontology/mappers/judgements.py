"""One form for every judgement in the term dict, and who may make one (rule 89).

A judgement is `{"verdict", "by", "why", "when"}` -- plus `iri` where the
judgement names an ontology class. Each question about a term holds a LIST of
judgements in time order, and nothing is ever removed from it.

Which judgement counts (curator, 2026-10-28: "nur ein späterer autor-eintrag
sticht den älteren"): the author's last one; without one, the last one of any
agent. A machine judging after the author is kept and does not count. A rule
is a machine even when the author made it ("eine regel ist eine regel und
nicht vom autor").

`by` is an id from `AGENTS`, never free text. The table says exactly who
each agent is -- model id and access, program file, the rule's number and
date -- and is written once into the file, so a judgement names its agent and
nothing else.
"""
from __future__ import annotations

import re as _re

#: The questions a term record answers (rule 89). The first two are about
#: the STRING; the last three about the concept and live on its name.
QUESTIONS = ("name", "pairs", "scope", "is_a", "relations")
STRING_QUESTIONS = ("name", "pairs")

FIELDS = ("verdict", "by", "why", "when")

AUTHOR, MACHINE = "author", "machine"

#: The instance reading (rules 66, 88): its `yes` on a relation makes it an
#: axiom of the WONT addition and lets the concept lattice pass it down
#: (`TermMappingAndGate.read_relations`).
RELATION_READER = "claude-opus-5-5_universality"

#: Every agent that has judged anything in the term dict. `rank` decides which
#: judgement counts; the rest is the exact identity, written once.
AGENTS: dict[str, dict] = {
    "author": {"rank": AUTHOR, "who": "Moritz Milewski, the author; the channel (chat, review page) is in `why`"},
    # rules: the author made them, a program applies them -- machines
    "abbreviation-full-form": {"rank": MACHINE, "rule": 58, "who": "rule 58: an abbreviation is replaced by the full form an abstract defines for it, also inside names; no definition, or several, makes the term out"},
    "tendency-not-disposition": {"rank": MACHINE, "rule": 68, "who": "rule 68: a has_disposition whose value is a tendency becomes has_tendency"},
    "ontology-label-is-canonical": {"rank": MACHINE, "rule": 36, "who": "rule 36: an ontology's own label is the canonical, never mapped onto another"},
    "no-trauma-to-injury": {"rank": MACHINE, "who": "spelling rule (2026-09-28): rule 49's trauma -> injury withdrawn"},
    "hyphen-modifier-not-grade": {"rank": MACHINE, "who": "spelling rule (2026-10-25): a hyphenated modifier is not a leading grade word"},
    "latin-keeps-final-s": {"rank": MACHINE, "who": "spelling rule (2026-10-25): Latin and invariant words keep their final s"},
    "proper-names-kept": {"rank": MACHINE, "who": "spelling rule (2026-10-02): the disorder rule leaves proper names as they are"},
    "action-potential-kept": {"rank": MACHINE, "who": "spelling rule (2026-09-27): action potential is exempt from rule 49's action -> activity"},
    "lock-means-different": {"rank": MACHINE, "who": "rule (2026-10-25): a locked pair with no stated relation is different"},
    "end-word-category": {"rank": MACHINE, "who": "rule: a term's BFO category follows the author's ruling on its end word (rule 57)"},
    # programs
    "string-normalisation": {"rank": MACHINE, "who": "program wound_ontology/utils/normalise.py (pass 0): singular, American spelling, capitalisation, hyphen and space, grading words, preferred vocabulary (rule 49)"},
    "chain-resolution": {"rank": MACHINE, "who": "program: resolves chains in the mapping graph (A -> B -> C becomes A -> C)"},
    "cluster-premerge": {"rank": MACHINE, "who": "program TermMapper.build_from_embeddings: strings one normalisation key joins are merged before SapBERT clusters them, and take the cluster's name"},
    "ontology-label-match": {"rank": MACHINE, "who": "program: the term is written like a class of WONT, MILD or the modules"},
    "number-unit-rule": {"rank": MACHINE, "who": "program: a term made of a number and a unit (10 mg) is out (term_mapping_and_gate.noise_rule)"},
    "category-split": {"rank": MACHINE, "who": "program ConceptStore.split_irreconcilable_terms: a term the abstracts type in categories with no common ancestor gets one name per category (rule 87)"},
    "category-guard": {"rank": MACHINE, "who": "program: refuses a mapping whose two sides lie in separate BFO branches"},
    "neighbour-check": {"rank": MACHINE, "who": "program scripts/p4_gate_pass1_withdraw.py: withdraws a copied scope whose source term had no authored decision"},
    "mapping-cleanup": {"rank": MACHINE, "who": "program: removes a mapping that a rename made empty or impossible (its target gone, or the term now spelled as its target)"},
    # lists, imported 2026-09-25 from config files whose provenance was not recorded
    "methodology-blocklist": {"rank": MACHINE, "who": "list METHODOLOGY_BLOCKLIST, imported 2026-09-25, provenance not recorded"},
    "whitelist": {"rank": MACHINE, "who": "list WHITELIST, imported 2026-09-25, provenance not recorded"},
    "keyword-blocklist": {"rank": MACHINE, "who": "list KEYWORD_BLOCKLIST, imported 2026-09-25, provenance not recorded"},
    "keyword-whitelist": {"rank": MACHINE, "who": "list KEYWORD_WHITELIST, imported 2026-09-25, provenance not recorded"},
    # models
    "sapbert-clustering": {"rank": MACHINE, "who": "SapBERT cambridgeltl/SapBERT-from-PubMedBERT-fulltext: clusters at cosine >= 0.95, proposes the name"},
    "sapbert-neighbour": {"rank": MACHINE, "who": "SapBERT cambridgeltl/SapBERT-from-PubMedBERT-fulltext: copies the scope of the most similar decided term (>= 0.95, margin >= 0.03)"},
    # DeepSeek V4 Flash (deepseek/deepseek-v4-flash-20260423, OpenRouter, temperature 0), one id per run
    # (curator, 2026-10-28, in the thesis: the run is part of who judged)
    "deepseek-v4-flash": {"rank": MACHINE, "who": "DeepSeek V4 Flash: scope classification, batches of 25"},
    "deepseek-v4-flash_bulk20": {"rank": MACHINE, "who": "DeepSeek V4 Flash: first synonym judgement, batches of 20"},
    "deepseek-v4-flash_bfo_type": {"rank": MACHINE, "who": "DeepSeek V4 Flash: second synonym judgement, with the BFO categories"},
    "deepseek-v4-flash_control": {"rank": MACHINE, "who": "DeepSeek V4 Flash: restatement check of narrower and broader"},
    "deepseek-v4-flash_top_15": {"rank": MACHINE, "who": "DeepSeek V4 Flash: placement proposal among the ten nearest classes (SapBERT preselects)"},
    "deepseek-v4-flash_single": {"rank": MACHINE, "who": "DeepSeek V4 Flash: yes/no question on the most reliable placement proposals"},
    "claude-opus-5-5": {"rank": MACHINE, "who": "Claude Opus 5.5 (claude-opus-5-5) reading rows in Claude Code sessions (2026-10-01 to 2026-10-25); the curator, 2026-10-29: quick and easy, but not right -- read again by the pipeline (the claude-opus-5-5_* agents)"},
    # Claude Opus 5.5 as a pipeline step (curator, 2026-10-29): OpenRouter batch
    # (anthropic/claude-opus-5.5, Anthropic Messages body, adaptive thinking,
    # effort high, answer constrained to a JSON schema), one id per reading
    "claude-opus-5-5_placement": {"rank": MACHINE, "who": "Claude Opus 5.5 via OpenRouter batch: reads every placement proposal with the definitions of the offered classes (scripts/claude_read_placements.py)"},
    "claude-opus-5-5_universality": {"rank": MACHINE, "who": "Claude Opus 5.5 via OpenRouter batch: reads whether a relation holds for every instance of its subject (rules 66, 88; scripts/claude_read_universality.py)"},
    "claude-opus-5-5_restatement": {"rank": MACHINE, "who": "Claude Opus 5.5 via OpenRouter batch: reads whether a placed term only restates its class (scripts/claude_read_small.py)"},
    "claude-opus-5-5_same_type": {"rank": MACHINE, "who": "Claude Opus 5.5 via OpenRouter batch: reads whether an author's clash decision carries over to a statement of the same type (scripts/claude_read_small.py)"},
    "elk": {"rank": MACHINE, "who": "ELK reasoner via ROBOT 1.9.8"},
    "relation-typing-check": {"rank": MACHINE, "who": "program scripts/relation_typing_check.py: each end of a relation against the category its predicate requires (RO/BFO domain and range); both ends ok -> yes (no objection, never an axiom), an end disjoint -> no, cannot tell -> undecided. First run 2026-10-02 (a file, not in the term dict); run again on the categories of 2026-10-30"},
    # what the records before rule 89 did not say
    "unrecorded": {"rank": MACHINE, "who": "not recorded before rule 89; kept so that nothing is lost, counted in the migration report"},
}

#: The agent of each old synonym pass: the run is part of who judged.
RUN = {"pass1": "deepseek-v4-flash_bulk20", "pass2": "deepseek-v4-flash_bfo_type",
       "check": "deepseek-v4-flash_control"}

_ISO = _re.compile(r"\d{4}-\d\d-\d\d(T\d\d:\d\d(:\d\d(\.\d+)?)?)?$")


def is_when(value) -> bool:
    """An ISO date or date-time, nothing else (rule 89: never free text)."""
    return isinstance(value, str) and bool(_ISO.match(value))


def make(verdict, by: str, why: str, when: str, iri: str | None = None) -> dict:
    """One judgement, checked: a known agent, a reason, an ISO `when`."""
    if by not in AGENTS:
        raise ValueError(f"unknown agent {by!r}; add it to AGENTS with who it is")
    if not why:
        raise ValueError(f"a judgement by {by!r} needs a reason")
    if not is_when(when):
        raise ValueError(f"`when` must be an ISO date or date-time, got {when!r}")
    j = {"verdict": verdict, "by": by, "why": why, "when": when}
    if iri:
        j["iri"] = iri
    return j


def rank(j: dict) -> str:
    return AGENTS[j["by"]]["rank"]


#: An abstention: an agent that answered once and then found it could not
#: (a copied scope withdrawn because its source was never authored). It is
#: kept for the record and never counts.
ABSTAIN = "undecided"


def current(entries: list[dict] | None) -> dict | None:
    """The judgement that counts: the author's last, else the last of all.
    An abstention never counts, but it takes back its own agent's earlier
    word: what an agent says last stands for it, "cannot tell" too (curator,
    2026-10-30, asked whether it should: "Ja, nur das eigene"). Until then the
    typing check's old `no` kept 2 relations out of the store view after it
    had answered `undecided`; another agent's word is never touched."""
    entries = list(entries or ())
    last = {j["by"]: j for j in entries}
    live = [j for j in entries if j["verdict"] != ABSTAIN and last[j["by"]]["verdict"] != ABSTAIN]
    if not live:
        return None
    for j in reversed(live):
        if rank(j) == AUTHOR:
            return j
    return live[-1]


def _order_key(j: dict) -> tuple:
    w = j["when"]
    return (w[:10], 1 if len(w) == 10 else 0, w)


def ordered(entries: list[dict]) -> list[dict]:
    """In time order. A date without a time sorts after that day's timed entries:
    the runs recorded by day only (the scope pass of 2026-09-28, the synonym
    passes) ran after the timed steps that prepared them -- the scope pass of
    that afternoon judged exactly the terms whose copied verdict had been
    withdrawn at 16:08. Entries with the same `when` keep their given order."""
    return sorted(entries, key=_order_key)
