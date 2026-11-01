"""Whether a term belongs is a judgement on its record, not a line in a .py file.

`METHODOLOGY_BLOCKLIST` (7,757) and `WHITELIST` (2,684) decided scope with no
verdict, no reason, no date and no author, because a cosine threshold and an LLM
batch wrote straight into the source files. Two things followed, both measured on
2026-09-25: the list holds `silver sulfadiazine`, `photobiomodulation`,
`tissue repair` and `vac therapy`; and 201 of the 1,612 families the curator had
just reviewed by hand had a canonical the blocklist already rejects -- 167
approved -- because nothing in front of them said so.

Rule 89 (2026-10-28): the scope is a list of judgements on the CONCEPT, each
with its agent, reason and time. The author's last judgement counts; without
one, the last of any agent. A rule and a list are machines.
"""

import pytest

from conftest import memory_mapping
from wound_ontology.mappers.term_mapping_and_gate import GATE_SOURCES, GATE_VERDICTS


# ── which judgement counts ───────────────────────────────────────────────────

def test_nothing_decided_is_not_a_verdict():
    assert memory_mapping().gate_verdict("wound") == ("", "")


def test_one_judgement_decides_and_names_its_agent():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert g.gate_verdict("cohort") == ("out", "methodology-blocklist")


def test_among_machines_the_later_judgement_counts():
    g = memory_mapping()
    g.gate("silver sulfadiazine", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    g.gate("silver sulfadiazine", pass2={"verdict": "in", "reason": "a topical antimicrobial"})
    assert g.gate_verdict("silver sulfadiazine") == ("in", "deepseek-v4-flash")


def test_the_author_outranks_a_later_machine():
    g = memory_mapping()
    g.gate("vac therapy", curator={"verdict": "in", "reason": "vacuum-assisted closure"})
    g.gate("vac therapy", pass2={"verdict": "out", "reason": "a device"})
    assert g.gate_verdict("vac therapy") == ("in", "author")


def test_a_rule_is_a_machine():
    g = memory_mapping()
    g.gate("NaCl 0.9%", curator={"verdict": "in", "reason": "a curated class"})
    g.gate("NaCl 0.9%", rule={"verdict": "out", "by": "noise rule: a number with a unit"})
    assert g.gate_verdict("NaCl 0.9%") == ("in", "author")


def test_nothing_is_deleted():
    g = memory_mapping()
    g.gate("bone healing", pass1={"verdict": "out", "near": "bone", "score": 0.96},
           pass2={"verdict": "in", "reason": "healing of a fracture"})
    assert [j["by"] for j in g.records["bone healing"]["scope"]] == \
        ["sapbert-neighbour", "deepseek-v4-flash"]


# ── the views that replace the two literals ──────────────────────────────────

def test_gated_out_is_what_the_blocklist_used_to_be():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    g.gate("wound", rule={"verdict": "in", "by": "WHITELIST"})
    assert g.gated("out") == {"cohort": "methodology-blocklist"}
    assert g.gated("in") == {"wound": "whitelist"}


def test_an_unknown_verdict_is_refused_by_the_view():
    with pytest.raises(ValueError, match="maybe"):
        memory_mapping().gated("maybe")


# ── the review queue ─────────────────────────────────────────────────────────

def test_agreeing_agents_are_not_a_disagreement():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"},
           pass2={"verdict": "out", "reason": "a study design"})
    assert g.gate_disagreements() == []


def test_agents_that_disagree_surface_with_the_verdict_that_counts():
    g = memory_mapping()
    g.gate("vac therapy", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    g.gate("vac therapy", curator={"verdict": "in", "reason": "vacuum-assisted closure"})
    rows = g.gate_disagreements()
    assert [r["term"] for r in rows] == ["vac therapy"]
    assert rows[0]["said"] == {"methodology-blocklist": "out", "author": "in"}
    assert (rows[0]["verdict"], rows[0]["source"]) == ("in", "author")


def test_the_queue_is_ordered_so_a_run_is_comparable_to_the_last():
    g = memory_mapping()
    for t in ("Zebra", "apple", "Mango"):
        g.gate(t, rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"}, pass2={"verdict": "in", "reason": "r"})
    assert [r["term"] for r in g.gate_disagreements()] == ["apple", "Mango", "Zebra"]


# ── writing ──────────────────────────────────────────────────────────────────

def test_a_gate_verdict_needs_a_known_source():
    with pytest.raises(ValueError, match="pass3"):
        memory_mapping().gate("wound", pass3={"verdict": "in"})


def test_a_gate_verdict_needs_a_known_verdict():
    with pytest.raises(ValueError, match="probably"):
        memory_mapping().gate("wound", curator={"verdict": "probably"})


def test_a_rule_needs_a_known_agent():
    with pytest.raises(ValueError, match="no agent"):
        memory_mapping().gate("wound", rule={"verdict": "in", "by": "some list"})


def test_the_gate_writes_a_record_for_a_term_that_maps_nowhere():
    # most out-of-scope terms were never proposed for a merge, so the gate must
    # be able to speak about a term with no mapping at all
    g = memory_mapping()
    g.gate("Kaplan-Meier analysis", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert set(g.records["Kaplan-Meier analysis"]) == {"scope"}


def test_the_gate_does_not_disturb_the_mapping():
    g = memory_mapping({"wounds": "Wound"})
    g.gate("wounds", curator={"verdict": "in"})
    assert g.data == {"wounds": "Wound"}


def test_reading_does_not_create_a_record():
    g = memory_mapping()
    g.gate_verdict("nothing here")
    g.own_gate_verdict("nothing here")
    assert "nothing here" not in g.records


def test_the_gate_survives_a_save_and_reload():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    g.save()
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    again = TermMappingAndGate(g._dm)
    assert again.gate_verdict("cohort") == ("out", "methodology-blocklist")


def test_the_gate_does_not_save_because_a_pass_writes_thousands():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert g._dm.written is None


# ── the constants are the contract ───────────────────────────────────────────

def test_the_two_verdicts_are_in_and_out():
    assert GATE_VERDICTS == ("in", "out")


def test_the_sources_a_caller_may_name():
    assert set(GATE_SOURCES) == {"curator", "pass2", "pass1", "rule"}


# ── the one rule over strings (rule 86) ───────────────────────────────────────

@pytest.mark.parametrize("term", ["12.5 mg/kg", "3 days", "44.8%", "7 d", "---"])
def test_the_noise_rule_takes_a_number_with_a_unit(term):
    from wound_ontology.mappers.term_mapping_and_gate import noise_rule
    assert noise_rule(term)


@pytest.mark.parametrize("term", ["Wagner grade 1D", "venous leg ulcer", "2D imaging"])
def test_the_noise_rule_leaves_a_name_alone(term):
    from wound_ontology.mappers.term_mapping_and_gate import noise_rule
    assert not noise_rule(term)


# ── the gate matches the way the lists always have ───────────────────────────

def test_a_capitalised_spelling_finds_the_verdict():
    # `TermList.match` lowercases and normalises (rule 13); an exact-match gate
    # answered about `cohort` and said nothing about `Cohort`, and the store
    # holds both -- 92,683 of its 96,243 names looked undecided to the gate
    # against 77,317 to the lists.
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert g.gate_verdict("Cohort") == ("out", "methodology-blocklist")
    assert g.gate_verdict("COHORT") == ("out", "methodology-blocklist")


def test_a_hyphen_finds_the_verdict():
    g = memory_mapping()
    g.gate("cell based therapies", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert g.gate_verdict("Cell-Based Therapies")[0] == "out"


def test_a_bracketed_name_is_not_folded_onto_the_bare_word():
    # `normalize_term` drops the bracket; `vitamin (role)` is not `vitamin`
    # (2026-10-28: with the scope on the concept, the fold would have put the
    # substance in scope by the role's verdict)
    g = memory_mapping()
    g.gate("vitamin (role)", pass2={"verdict": "in", "reason": "r"})
    assert g.gate_verdict("vitamin") == ("", "")


def test_the_terms_own_verdict_wins_over_another_spellings():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    g.gate("Cohort", curator={"verdict": "in", "reason": "a named cohort study arm"})
    assert g.gate_verdict("Cohort") == ("in", "author")
    assert g.gate_verdict("cohort") == ("out", "methodology-blocklist")


def test_own_gate_verdict_does_not_fall_back():
    g = memory_mapping()
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert g.own_gate_verdict("Cohort") == ("", "")


def test_an_alias_does_not_invent_a_disagreement():
    g = memory_mapping({"Cohort": "cohort"})
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert g.gate_disagreements() == []


def test_the_index_is_rebuilt_after_a_write():
    g = memory_mapping()
    assert g.gate_verdict("Cohort") == ("", "")     # builds the index empty
    g.gate("cohort", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    assert g.gate_verdict("Cohort")[0] == "out"


# ── scope belongs to the CONCEPT, not to the spelling ────────────────────────

def test_a_member_reads_its_concepts_verdict():
    g = memory_mapping({"wounds": "Wound"})
    g.gate("Wound", curator={"verdict": "in"})
    assert g.gate_verdict("wounds") == ("in", "author")


def test_a_verdict_written_through_a_member_lands_on_the_concept():
    g = memory_mapping({"IL-6": "IL6"})
    g.gate("IL-6", pass2={"verdict": "in", "reason": "a cytokine in wound healing"})
    assert "scope" not in g.records["IL-6"]
    assert g.gate_verdict("IL6") == ("in", "deepseek-v4-flash")


def test_one_concept_gets_one_answer_whichever_spelling_is_asked():
    g = memory_mapping({"post-operative pain": "postoperative pain"})
    g.gate("postoperative pain", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    g.gate("post-operative pain", pass2={"verdict": "in", "reason": "wound pain"})
    assert g.gate_verdict("post-operative pain") == g.gate_verdict("postoperative pain") \
        == ("in", "deepseek-v4-flash")


def test_a_scope_written_before_the_mapping_moves_with_the_name():
    # the verdict has to sit on the MEMBER first: with it on the concept a
    # missing move still finds it, and the test passes while the move is broken
    g = memory_mapping()
    g.gate("wounds", curator={"verdict": "in"})
    assert g.gate_verdict("Wound") == ("", "")
    g.add("wounds", "Wound")
    assert g.gate_verdict("Wound") == ("in", "author")
    assert "scope" not in g.records["wounds"]


def test_a_moved_scope_joins_the_concepts_in_time_order():
    g = memory_mapping()
    g.gate("Wound", pass2={"verdict": "out", "reason": "later", "when": "2026-10-02T10:00:00"})
    g.gate("wounds", pass2={"verdict": "in", "reason": "earlier", "when": "2026-10-01T10:00:00"})
    g.add("wounds", "Wound")
    assert [j["why"] for j in g.records["Wound"]["scope"]] == ["earlier", "later"]
    assert g.gate_verdict("wounds")[0] == "out"


def test_there_is_nothing_to_contradict_across_spellings():
    g = memory_mapping({"post-operative pain": "postoperative pain"})
    g.gate("postoperative pain", rule={"verdict": "out", "by": "METHODOLOGY_BLOCKLIST"})
    g.gate("post-operative pain", pass2={"verdict": "in", "reason": "r"})
    assert g.gate_contradictions() == []


def test_a_spelling_with_no_concept_of_its_own_still_finds_the_verdict():
    # `Conventional Treatment` maps nowhere and carries nothing, while
    # `conventional treatment` has a judgement: the fold finds it.
    g = memory_mapping()
    g.gate("conventional treatment", pass2={"verdict": "in", "reason": "r"})
    assert g.gate_verdict("Conventional Treatment") == ("in", "deepseek-v4-flash")


def test_the_concept_still_wins_over_the_spelling_fallback():
    g = memory_mapping({"Conventional Treatment": "conventional therapy"})
    g.gate("conventional therapy", pass2={"verdict": "out", "reason": "a"})
    g.gate("conventional treatment", pass2={"verdict": "in", "reason": "b"})
    assert g.gate_verdict("Conventional Treatment") == ("out", "deepseek-v4-flash")


def test_a_sense_of_a_split_term_takes_the_split_terms_scope():
    g = memory_mapping()
    g.gate("Biopsy", rule={"verdict": "in", "by": "WHITELIST"})
    g.split_by_category("Biopsy", {"process": "Biopsy procedure", "material entity": "Biopsy material"})
    assert g.gate_verdict("Biopsy procedure") == ("in", "whitelist")
