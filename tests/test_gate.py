"""Whether a term belongs is a verdict on its record, not a line in a .py file.

`METHODOLOGY_BLOCKLIST` (7,757) and `WHITELIST` (2,684) decided scope with no
verdict, no reason, no date and no author, because a cosine threshold and an LLM
batch wrote straight into the source files. Two things followed, both measured on
2026-09-25: the list holds `silver sulfadiazine`, `photobiomodulation`,
`tissue repair` and `vac therapy`; and 201 of the 1,612 families the curator had
just reviewed by hand had a canonical the blocklist already rejects -- 167
approved -- because nothing in front of them said so.

The gate puts that decision where the mapping's decisions already are, with the
same precedence rule 28 gives everything else: an explicit decision outranks a
heuristic, and a model is a heuristic.
"""

import pytest

from conftest import memory_mapping
from wound_ontology.mappers.term_mapping_and_gate import GATE_SOURCES, GATE_VERDICTS


# ── precedence ───────────────────────────────────────────────────────────────

def test_nothing_decided_is_not_a_verdict():
    assert memory_mapping().gate_verdict("wound") == ("", "")


def test_the_rule_decides_when_it_is_alone():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert g.gate_verdict("cohort") == ("out", "rule")


def test_one_pass_outranks_the_rule():
    g = memory_mapping()
    g.gate("silver sulfadiazine", rule={"verdict": "out", "by": "list"},
           pass2={"verdict": "in", "reason": "a topical antimicrobial"})
    assert g.gate_verdict("silver sulfadiazine") == ("in", "pass2")


def test_two_passes_agreeing_outrank_the_rule():
    g = memory_mapping()
    g.gate("tissue repair", rule={"verdict": "out", "by": "list"},
           pass1={"verdict": "in"}, pass2={"verdict": "in"})
    assert g.gate_verdict("tissue repair") == ("in", "pass1+pass2")


def test_the_curator_outranks_everything():
    g = memory_mapping()
    g.gate("vac therapy", rule={"verdict": "out", "by": "list"},
           pass1={"verdict": "out"}, pass2={"verdict": "out"},
           curator={"verdict": "in", "reason": "vacuum-assisted closure"})
    assert g.gate_verdict("vac therapy") == ("in", "curator")


def test_passes_that_contradict_each_other_fall_through_to_the_rule():
    # Two passes exist so that a disagreement becomes a question. Answering it
    # by picking one would throw away the only signal that says "look at this".
    g = memory_mapping()
    g.gate("bone healing", rule={"verdict": "out", "by": "list"},
           pass1={"verdict": "out"}, pass2={"verdict": "in"})
    assert g.gate_verdict("bone healing") == ("out", "rule")


def test_contradicting_passes_with_no_rule_decide_nothing():
    g = memory_mapping()
    g.gate("bone healing", pass1={"verdict": "out"}, pass2={"verdict": "in"})
    assert g.gate_verdict("bone healing") == ("", "")


# ── the views that replace the two literals ──────────────────────────────────

def test_gated_out_is_what_the_blocklist_used_to_be():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "list"})
    g.gate("wound", rule={"verdict": "in", "by": "list"})
    assert g.gated("out") == {"cohort": "rule"}


def test_gated_in_is_what_the_whitelist_used_to_be():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "list"})
    g.gate("wound", rule={"verdict": "in", "by": "list"})
    assert g.gated("in") == {"wound": "rule"}


def test_the_view_names_the_source_so_an_entry_cannot_be_anonymous():
    g = memory_mapping()
    g.gate("vac therapy", rule={"verdict": "out", "by": "list"},
           curator={"verdict": "in", "reason": "…"})
    assert g.gated("in")["vac therapy"] == "curator"


def test_an_unknown_verdict_is_refused_by_the_view():
    with pytest.raises(ValueError, match="maybe"):
        memory_mapping().gated("maybe")


# ── the review queue ─────────────────────────────────────────────────────────

def test_agreeing_sources_are_not_a_disagreement():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out"}, pass1={"verdict": "out"})
    assert g.gate_disagreements() == []


def test_two_passes_contradicting_each_other_surface():
    g = memory_mapping()
    g.gate("bone healing", pass1={"verdict": "out"}, pass2={"verdict": "in"})
    rows = g.gate_disagreements()
    assert [r["term"] for r in rows] == ["bone healing"]
    assert rows[0]["said"] == {"pass2": "in", "pass1": "out"}


def test_a_pass_contradicting_the_rule_surfaces():
    g = memory_mapping()
    g.gate("silver sulfadiazine", rule={"verdict": "out"}, pass2={"verdict": "in"})
    assert [r["term"] for r in g.gate_disagreements()] == ["silver sulfadiazine"]


def test_the_row_carries_the_resolved_verdict_and_its_source():
    g = memory_mapping()
    g.gate("vac therapy", rule={"verdict": "out"}, curator={"verdict": "in"})
    r = g.gate_disagreements()[0]
    assert r["verdict"] == "in" and r["source"] == "curator"


def test_the_queue_is_ordered_so_a_run_is_comparable_to_the_last():
    g = memory_mapping()
    for t in ("Zebra", "apple", "Mango"):
        g.gate(t, rule={"verdict": "out"}, pass1={"verdict": "in"})
    assert [r["term"] for r in g.gate_disagreements()] == ["apple", "Mango", "Zebra"]


# ── writing ──────────────────────────────────────────────────────────────────

def test_a_gate_verdict_needs_a_known_source():
    with pytest.raises(ValueError, match="pass3"):
        memory_mapping().gate("wound", pass3={"verdict": "in"})


def test_a_gate_verdict_needs_a_known_verdict():
    with pytest.raises(ValueError, match="probably"):
        memory_mapping().gate("wound", curator={"verdict": "probably"})


def test_the_gate_writes_a_record_for_a_term_that_maps_nowhere():
    # most out-of-scope terms were never proposed for a merge, so the gate must
    # be able to speak about a term with no mapping at all
    g = memory_mapping()
    g.gate("Kaplan-Meier analysis", rule={"verdict": "out", "by": "list"})
    assert "Kaplan-Meier analysis" in g.records
    assert g.records["Kaplan-Meier analysis"]["to"] is None


def test_the_gate_does_not_disturb_the_mapping():
    g = memory_mapping({"wounds": "Wound"})
    g.gate("wounds", curator={"verdict": "in"})
    assert g.data == {"wounds": "Wound"}


def test_peek_does_not_create_a_record():
    g = memory_mapping()
    g.peek_gate("nothing here")
    assert "nothing here" not in g.records


def test_the_gate_survives_a_save_and_reload():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "list"})
    g.save()
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    again = TermMappingAndGate(g._dm)
    assert again.gate_verdict("cohort") == ("out", "rule")


def test_the_gate_does_not_save_because_a_pass_writes_thousands():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out"})
    assert g._dm.written is None


# ── the constants are the contract ───────────────────────────────────────────

def test_the_two_verdicts_are_in_and_out():
    assert GATE_VERDICTS == ("in", "out")


def test_the_sources_are_ordered_strongest_first():
    assert GATE_SOURCES == ("curator", "pass2", "pass1", "rule")


# ── what the gate does to the Blocker ────────────────────────────────────────

def _blocker(gate=None):
    from wound_ontology.store.blocker import Blocker
    return Blocker(gate=gate)


def _a_blocked_term():
    from config.blocklist import METHODOLOGY_BLOCKLIST
    return sorted(METHODOLOGY_BLOCKLIST)[0]


def _a_whitelisted_term():
    from config.whitelist import WHITELIST
    return sorted(WHITELIST)[0]


def test_without_a_gate_the_lists_decide_exactly_as_before():
    b = _blocker()
    assert b.gate is None
    assert b.gate_verdict("anything") == ("", "")
    assert b.is_blocked(_a_blocked_term())
    assert not b.is_blocked(_a_whitelisted_term())


def test_the_gate_can_let_a_blocklisted_term_through():
    t = _a_blocked_term()
    g = memory_mapping()
    g.gate(t, rule={"verdict": "out", "by": "list"},
           curator={"verdict": "in", "reason": "a real wound concept"})
    assert _blocker().is_blocked(t)
    assert not _blocker(g).is_blocked(t)


def test_a_rule_verdict_keeps_the_position_the_list_it_came_from_had():
    # A whitelist KEYWORD used to rescue a term on the exact blocklist, and the
    # fold must not change that: `rule` IS that list, moved, not re-decided.
    # Only a curator or a pass -- new evidence -- goes ahead of the keywords.
    from config.whitelist import KEYWORD_WHITELIST
    kw = sorted(KEYWORD_WHITELIST)[0]
    t = kw + " in a methodology phrase"
    g = memory_mapping()
    g.gate(t, rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert _blocker(g).white_kw.match(t)
    assert not _blocker(g).is_blocked(t)          # the keyword still rescues it
    g.gate(t, pass2={"verdict": "out", "reason": "a study-design phrase"})
    assert _blocker(g).is_blocked(t)              # new evidence does not


def test_the_gate_can_block_a_whitelisted_term():
    t = _a_whitelisted_term()
    g = memory_mapping()
    g.gate(t, curator={"verdict": "out", "reason": "methodology after all"})
    assert not _blocker().is_blocked(t)
    assert _blocker(g).is_blocked(t)


def test_a_gate_verdict_beats_the_noise_regex():
    from config.blocklist import is_noise_term
    noise = "12.5 mg/kg"
    assert is_noise_term(noise)
    g = memory_mapping()
    g.gate(noise, curator={"verdict": "in", "reason": "a dosage that names a class"})
    assert _blocker().is_blocked(noise)
    assert not _blocker(g).is_blocked(noise)


def test_a_keyword_still_decides_a_term_the_gate_says_nothing_about():
    b = _blocker(memory_mapping())
    assert b.is_blocked("multivariable Cox regression")      # KEYWORD_BLOCKLIST
    assert not b.is_blocked("venous leg ulcer")


def test_score_follows_is_blocked_through_the_gate():
    t = _a_blocked_term()
    g = memory_mapping()
    g.gate(t, curator={"verdict": "in"})
    assert _blocker().score(t) == 100.0
    assert _blocker(g).score(t) == 0.0


def test_a_gate_that_only_holds_the_imported_rule_changes_nothing():
    # what the one-time fold produces: every list entry as `rule`, nothing else.
    # The two must then agree by construction, or the fold moved a decision.
    from config.blocklist import METHODOLOGY_BLOCKLIST
    from config.whitelist import WHITELIST
    g = memory_mapping()
    sample = sorted(METHODOLOGY_BLOCKLIST)[:40] + sorted(WHITELIST)[:40]
    for t in sorted(METHODOLOGY_BLOCKLIST)[:40]:
        g.gate(t, rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    for t in sorted(WHITELIST)[:40]:
        g.gate(t, rule={"verdict": "in", "by": "WHITELIST"})
    plain, gated = _blocker(), _blocker(g)
    assert [plain.is_blocked(t) for t in sample] == [gated.is_blocked(t) for t in sample]


def test_a_gate_with_an_empty_mapping_is_still_a_gate():
    # `TermMappingAndGate.__len__` counts the live MAPPING, so a gate carrying
    # ten thousand scope verdicts and no mappings is falsy. `if self.gate` turned
    # the gate off and left the lists deciding, silently -- found by this test
    # failing on a term the curator had explicitly let through.
    t = _a_blocked_term()
    g = memory_mapping()
    g.gate(t, curator={"verdict": "in"})
    assert len(g) == 0 and not bool(g)
    assert _blocker(g).gate_verdict(t) == ("in", "curator")
    assert not _blocker(g).is_blocked(t)


# ── the gate matches the way the lists always have ───────────────────────────

def test_a_capitalised_spelling_finds_the_verdict():
    # `TermList.match` lowercases and normalises (rule 13); an exact-match gate
    # answered about `cohort` and said nothing about `Cohort`, and the store
    # holds both -- 92,683 of its 96,243 names looked undecided to the gate
    # against 77,317 to the lists.
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "list"})
    assert g.gate_verdict("Cohort") == ("out", "rule")
    assert g.gate_verdict("COHORT") == ("out", "rule")


def test_a_hyphen_finds_the_verdict():
    g = memory_mapping()
    g.gate("cell based therapies", rule={"verdict": "out"})
    assert g.gate_verdict("Cell-Based Therapies") == ("out", "rule")


def test_a_trailing_parenthetical_finds_the_verdict():
    g = memory_mapping()
    g.gate("vitamin", rule={"verdict": "in"})
    assert g.gate_verdict("vitamin (role)") == ("in", "rule")


def test_the_terms_own_verdict_wins_over_another_spellings():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out"})
    g.gate("Cohort", curator={"verdict": "in", "reason": "a named cohort study arm"})
    assert g.gate_verdict("Cohort") == ("in", "curator")
    assert g.gate_verdict("cohort") == ("out", "rule")


def test_a_spelling_with_no_gate_of_its_own_stays_out_of_the_view():
    # otherwise every export would add the aliases to the file and the next
    # export would add theirs
    g = memory_mapping({"Cohort": "cohort"})
    g.gate("cohort", rule={"verdict": "out"})
    assert g.gate_verdict("Cohort") == ("out", "rule")
    assert set(g.gated("out")) == {"cohort"}


def test_own_gate_verdict_does_not_fall_back():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out"})
    assert g.own_gate_verdict("Cohort") == ("", "")


def test_an_alias_does_not_invent_a_disagreement():
    g = memory_mapping({"Cohort": "cohort"})
    g.gate("cohort", rule={"verdict": "out"})
    assert g.gate_disagreements() == []


def test_the_index_is_rebuilt_after_a_write():
    g = memory_mapping()
    assert g.gate_verdict("Cohort") == ("", "")     # builds the index empty
    g.gate("cohort", rule={"verdict": "out"})
    assert g.gate_verdict("Cohort") == ("out", "rule")


# ── scope belongs to the CONCEPT, not to the spelling ────────────────────────

def test_a_member_inherits_its_canonicals_verdict():
    g = memory_mapping({"wounds": "Wound"})
    g.gate("Wound", curator={"verdict": "in"})
    assert g.effective_gate_verdict("wounds") == ("in", "curator")


def test_a_term_that_maps_nowhere_decides_for_itself():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out"})
    assert g.effective_gate_verdict("cohort") == ("out", "rule")


def test_better_evidence_on_a_MEMBER_beats_a_rule_on_the_canonical():
    # `IL6` carries an imported `rule` of out that nobody can account for; its
    # member `IL-6` carries a pass2 of in, with a reason. Letting the canonical
    # simply win undid 37 judgements the scope pass had just made.
    g = memory_mapping({"IL-6": "IL6"})
    g.gate("IL6", rule={"verdict": "out", "by": "list"})
    g.gate("IL-6", pass2={"verdict": "in", "reason": "a cytokine in wound healing"})
    assert g.effective_gate_verdict("IL6") == ("in", "pass2")
    assert g.effective_gate_verdict("IL-6") == ("in", "pass2")


def test_the_canonical_wins_when_the_source_is_the_same_strength():
    g = memory_mapping({"conventional treatment": "conventional therapy"})
    g.gate("conventional therapy", pass2={"verdict": "out", "reason": "a"})
    g.gate("conventional treatment", pass2={"verdict": "in", "reason": "b"})
    assert g.effective_gate_verdict("conventional treatment") == ("out", "pass2")


def test_one_concept_gets_one_answer_whichever_spelling_is_asked():
    g = memory_mapping({"post-operative pain": "postoperative pain"})
    g.gate("postoperative pain", rule={"verdict": "out"})
    g.gate("post-operative pain", pass2={"verdict": "in", "reason": "wound pain"})
    assert (g.effective_gate_verdict("post-operative pain")
            == g.effective_gate_verdict("postoperative pain"))


def test_a_sibling_contributes_its_evidence_too():
    g = memory_mapping({"a variant": "the canonical", "another": "the canonical"})
    g.gate("the canonical", rule={"verdict": "out"})
    g.gate("another", curator={"verdict": "in", "reason": "a real concept"})
    assert g.effective_gate_verdict("a variant") == ("in", "curator")


def test_the_contradiction_is_reported_not_hidden():
    g = memory_mapping({"post-operative pain": "postoperative pain"})
    g.gate("postoperative pain", rule={"verdict": "out"})
    g.gate("post-operative pain", pass2={"verdict": "in", "reason": "r"})
    rows = g.gate_contradictions()
    assert len(rows) == 1
    assert rows[0]["term"] == "post-operative pain"
    assert rows[0]["canonical"] == "postoperative pain"


def test_agreeing_spellings_are_not_a_contradiction():
    g = memory_mapping({"wounds": "Wound"})
    g.gate("Wound", rule={"verdict": "in"})
    g.gate("wounds", pass2={"verdict": "in", "reason": "r"})
    assert g.gate_contradictions() == []


def test_the_member_index_is_rebuilt_after_a_mapping_change():
    # the verdict has to sit on the MEMBER: with it on the canonical a stale
    # index still finds it, and the test passes while the cache is broken
    g = memory_mapping()
    g.gate("wounds", curator={"verdict": "in"})
    assert g.effective_gate_verdict("Wound") == ("", "")     # builds the index
    g.add("wounds", "Wound")
    assert g.effective_gate_verdict("Wound") == ("in", "curator")


def test_a_disagreement_across_two_spellings_of_one_concept_is_found():
    # counted per record this is invisible: `IL6` holds only a rule and `IL-6`
    # only a pass2, so neither record contradicts itself. 65 of the 149 concepts
    # the scope pass overturned looked exactly like this.
    g = memory_mapping({"IL-6": "IL6"})
    g.gate("IL6", rule={"verdict": "out", "by": "list"})
    g.gate("IL-6", pass2={"verdict": "in", "reason": "a cytokine"})
    rows = g.gate_disagreements()
    assert [r["term"] for r in rows] == ["IL6"]
    assert rows[0]["said"] == {"pass2": "in", "rule": "out"}


def test_the_row_names_which_spelling_each_source_sits_on():
    g = memory_mapping({"IL-6": "IL6"})
    g.gate("IL6", rule={"verdict": "out"})
    g.gate("IL-6", pass2={"verdict": "in", "reason": "r"})
    assert g.gate_disagreements()[0]["where"] == {"rule": "IL6", "pass2": "IL-6"}


def test_one_concept_is_reported_once_however_many_spellings_it_has():
    g = memory_mapping({"IL-6": "IL6", "il 6": "IL6", "Il-6": "IL6"})
    g.gate("IL6", rule={"verdict": "out"})
    g.gate("IL-6", pass2={"verdict": "in", "reason": "r"})
    assert len(g.gate_disagreements()) == 1


def test_the_reported_term_is_the_canonical_not_the_spelling_that_clashed():
    g = memory_mapping({"IL-6": "IL6"})
    g.gate("IL6", rule={"verdict": "out"})
    g.gate("IL-6", pass2={"verdict": "in", "reason": "r"})
    assert g.gate_disagreements()[0]["term"] == "IL6"


def test_a_spelling_with_no_concept_of_its_own_still_finds_the_verdict():
    # `Conventional Treatment` maps nowhere and carries nothing, while
    # `conventional treatment` has a pass 2 verdict. Pooling over the concept
    # skipped the spelling fallback that `gate_verdict` does, so the capitalised
    # form came back undecided and fell through to the keyword lists.
    g = memory_mapping()
    g.gate("conventional treatment", pass2={"verdict": "in", "reason": "r"})
    assert g.effective_gate_verdict("Conventional Treatment") == ("in", "pass2")


def test_the_concept_still_wins_over_the_spelling_fallback():
    g = memory_mapping({"Conventional Treatment": "conventional therapy"})
    g.gate("conventional therapy", pass2={"verdict": "out", "reason": "a"})
    g.gate("conventional treatment", pass2={"verdict": "in", "reason": "b"})
    assert g.effective_gate_verdict("Conventional Treatment") == ("out", "pass2")
