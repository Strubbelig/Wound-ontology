"""Claude's readings as pipeline steps (2026-10-29): how an answer becomes a judgement.

The first run showed the fields of an answer contradicting each other: `stands`
with another class's number (264 of 17,328 rows, the reason naming the proposal),
`change` naming no class, `change` to the proposal itself, rows left out of an
answer. A row is written only when its answer settles what Claude meant.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claude_read_placements as crp  # noqa: E402
from wound_ontology.llm.claude_batch import BatchRun  # noqa: E402

ROW = {"row": 1, "term": "Acute-phase protein", "relation": "is_a", "proposed": 1,
       "offered": [{"label": "protein"}, {"label": "peptide"}, {"label": "Acute wound"}]}


def ans(verdict, relation, cls, why):
    return {"row": 1, "verdict": verdict, "relation": relation, "class": cls, "why": why}


def test_stands_on_the_proposal_is_written():
    assert crp.judge_row(ans("stands", "is_a", 1, "It is a protein."), ROW) == ("stands", None)


def test_stands_with_a_slipped_number_and_a_reason_naming_the_proposal_is_the_proposal():
    verdict, note = crp.judge_row(ans("stands", "is_a", 3, "Acute-phase proteins are proteins."), ROW)
    assert verdict == "stands" and "class number 3" in note


def test_stands_with_a_slipped_number_and_an_unclear_reason_is_not_written():
    assert crp.judge_row(ans("stands", "is_a", 3, "It fits."), ROW)[0] is None


def test_change_naming_no_class_reads_as_none():
    verdict, note = crp.judge_row(ans("change", "none", 0, "No offered class fits."), ROW)
    assert verdict == "none" and "read as none" in note


def test_change_to_the_proposal_itself_is_not_written():
    assert crp.judge_row(ans("change", "is_a", 1, "protein"), ROW) == (None, "change to the proposal itself")


def test_change_to_another_class_is_written():
    assert crp.judge_row(ans("change", "is_a", 2, "a peptide"), ROW) == ("change", None)


def test_a_row_left_out_of_the_answer_is_not_written():
    assert crp.judge_row(None, ROW) == (None, "unanswered")


def test_a_refusal_and_a_cut_off_answer_are_errors_not_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    run = BatchRun(tmp_path)
    run.state["batches"] = [{"id": "b1", "status": "completed", "model": "m", "custom_ids": ["a", "b", "c", "d"]}]

    def res(cid, stop, text):
        return {"custom_id": cid, "response": {"body": {"stop_reason": stop, "usage": {},
                                                        "content": [{"type": "text", "text": text}]}}}
    (tmp_path / "b1.json").write_text(json.dumps({"status": "completed", "model": "m", "results": [
        res("a", "end_turn", '{"answers": []}'), res("b", "refusal", ""), res("c", "max_tokens", '{"ans')]}))
    got = run.answers()
    assert got["a"].answer == {"answers": []} and got["a"].error is None
    assert got["b"].error == "stopped: refusal"
    assert got["c"].error == "stopped: max_tokens"
    assert got["d"].error.startswith("no result")


def test_the_restatement_reading_answers_with_the_four_pair_verdicts():
    """Curator, 2026-10-30: "claude antwortet mit same, broader, narrower oder
    different wie alle" -- the first restatement reading had answers of its
    own (`same`, `narrower`, `neither`)."""
    import claude_read_small as crs
    from wound_ontology.mappers.term_mapping_and_gate import PAIR_VERDICTS
    enum = crs.RESTATE_SCHEMA["properties"]["answers"]["items"]["properties"]["verdict"]["enum"]
    assert sorted(crs.PAIR_OF[v] for v in enum) == sorted(PAIR_VERDICTS)


def test_the_instance_reading_lives_in_the_term_dict_and_only_its_yes_makes_an_axiom():
    """Curator, 2026-10-30, on the reading kept in result.json files beside the
    term dict: "das machst du ganz sicher nicht". The reading's `yes` is an
    axiom; ELK's `yes` (it no longer objects) and a renaming rule's `yes` are
    not; a refusal after the reading holds it back; the author's word counts."""
    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import J
    from wound_ontology.mappers.judgements import RELATION_READER as R
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    class DM:
        def load_latest_json(self, name):
            return None

        def save_as_json(self, data, name):
            pass

    gt = TermMappingAndGate(DM(), file_name="term_mapping")
    gt.records["Burn injury"] = {"relations": {
        "has_quality: Depth": [J("yes", R)],                                   # read: axiom
        "has_quality: Contaminated": [J("no", R), J("yes", "elk")],             # ELK lifts its no: not an axiom
        "participates_in: Sepsis": [J("yes", R), J("no", "elk")],               # refused after the reading
        "has_tendency: Wound risk": [J("yes", "tendency-not-disposition")],    # never read
        "has_quality: Aseptic": [J("no", R), J("yes", "author")]}}             # the author's word
    gt._dirty()
    got = {(p, t): ax for _, p, t, ax, _ in gt.read_relations(R)}
    assert got == {("has_quality", "Depth"): True, ("has_quality", "Contaminated"): False,
                   ("participates_in", "Sepsis"): False, ("has_quality", "Aseptic"): True}


def test_every_answer_stays_in_its_question_s_answers():
    """Curator, 2026-10-30: "kannst du nicht einfach die Antworten mappen". The
    placement reading's "same as X, answered a kind of X" is `narrower` on the
    pair (23 had been written `different`); the term dict refuses, on writing
    and on loading, any answer outside its question's set (149 old DeepSeek
    judgements had been: `same_class` in an is_a cell, `no` on a pair)."""
    import pytest
    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import J
    from wound_ontology.mappers.term_mapping_and_gate import FORMAT, TermMappingAndGate

    x = {"label": "Manuka honey", "iri": "X_1"}
    row = {"question": "pairs", "iri": "X_1", "key": "Manuka honey", "offered": [x, {"label": "honey", "iri": "X_2"}]}
    assert crp.answer_verdicts(row, ans("change", "is_a", 1, "A kind of it."), "change") == [
        ("pairs", "narrower", {"iri": "X_1", "label": "Manuka honey"}), ("is_a", "yes", x)]
    assert crp.answer_verdicts(row, ans("change", "same", 2, "Honey."), "change")[0][1] == "different"
    assert crp.answer_verdicts(dict(row, question="is_a"), ans("change", "same", 1, "It is it."), "change") == [
        ("is_a", "no", {"iri": "X_1", "label": "Manuka honey"}), ("pairs", "same_class", x)]

    class DM:
        def __init__(self, raw=None):
            self.raw = raw

        def load_latest_json(self, name):
            return self.raw

        def save_as_json(self, data, name):
            pass

    gt = TermMappingAndGate(DM(), file_name="term_mapping")
    with pytest.raises(ValueError, match="not one of"):
        gt._put("Active leptospermum honey", "is_a", J("same_class", "deepseek-v4-flash_top_15"), "Manuka honey")
    with pytest.raises(ValueError, match="outside their question's answers"):
        TermMappingAndGate(DM({"format": FORMAT, "agents": {}, "terms": {
            "Copper": {"pairs": {"copper atom": [J("no", "deepseek-v4-flash_single")]}}}}), file_name="term_mapping")


def test_the_author_s_relation_decisions_live_in_the_term_dict_and_count_over_the_reading():
    """Curator, 2026-10-30, asked whether the decisions of the review pages kept
    in curator_axioms_2026-10-03.json and new_class_relation_decisions.json
    should move into the term dict: "Ja". His `yes` makes an axiom where the
    reading said no, his `no` keeps out what it read as true, and the concept
    lattice reads both from the term dict alone."""
    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import J
    from wound_ontology.fca.universality import load_verdicts
    from wound_ontology.mappers.judgements import RELATION_READER as R
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    class DM:
        def load_latest_json(self, name):
            return None

        def save_as_json(self, data, name):
            pass

    gt = TermMappingAndGate(DM(), file_name="term_mapping")
    gt.records["Wound"] = {"relations": {
        "has_part: Tissue": [J("yes", R), J("no", "author")],              # left out on the axiom page
        "has_quality: Age": [J("no", R), J("yes", "author")],              # an axiom he added
        "has_quality: Depth": [J("yes", R)]}}                               # the reading alone
    gt.records["Burn care"] = {"relations": {"has_input: Thermal wound": [J("yes", "author")]}}  # never read
    gt._dirty()
    assert {(s, p, t): j["verdict"] for s, p, t, j in gt.author_relations()} == {
        ("Wound", "has_part", "Tissue"): "no", ("Wound", "has_quality", "Age"): "yes",
        ("Burn care", "has_input", "Thermal wound"): "yes"}

    class Store:
        terms = gt

    verdicts, rep = load_verdicts(Store())
    assert verdicts[("Wound", "has_part: tissue")][0] == "no"
    assert verdicts[("Wound", "has_quality: age")][0] == "all"
    assert verdicts[("Burn Care", "has_input: thermal wound")][0] == "all"
    assert (rep["curator"], rep["curator_overrides_reading"]) == (3, 2)


def test_the_typing_check_answers_in_the_term_dict_and_a_rerun_hears_its_own_refusals():
    """Curator, 2026-10-30, asked whether to write the typing check of
    2026-10-02 into the term dict or to run it again on today's categories:
    "neu laufen lassen". Its `no` leaves a relation out of the store view; a
    rerun sets its own judgements aside (`reopen`), also through rule 68's
    change of predicate, and several checkers can be set aside at once (the
    figure's start: the relations before any check)."""
    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import J
    from wound_ontology.mappers.judgements import RELATION_READER as R
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate, heard

    class DM:
        def load_latest_json(self, name):
            return None

        def save_as_json(self, data, name):
            pass

    T = "relation-typing-check"
    gt = TermMappingAndGate(DM(), file_name="term_mapping")
    gt.records["Wound"] = {"relations": {
        "has_quality: Contamination": [J("no", T)],
        "has_quality: Depth": [J("yes", T)],
        "has_part: Tissue": [J("no", "elk"), J("no", T)],
        "has_disposition: Pressure ulcer risk": [J("no", "tendency-not-disposition")],
        "has_tendency: Pressure ulcer risk": [J("yes", "tendency-not-disposition",
                                                why="rule 68; predicate changed from has_disposition"),
                                              J("no", T)]}}
    gt._dirty()
    assert gt.cell_rejected("Wound", "has_quality: Contamination")["by"] == T
    assert gt.cell_rejected("Wound", "has_quality: Depth") is None           # its yes is no objection
    assert gt.cell_rejected("Wound", "has_quality: Contamination", reopen=T) is None
    assert gt.cell_rejected("Wound", "has_part: Tissue", reopen=T)["by"] == "elk"   # only its own aside
    assert gt.cell_rejected("Wound", "has_part: Tissue", reopen=frozenset({T, "elk"})) is None
    # rule 68: another agent's word on has_tendency judges the relation under its
    # new predicate and never undoes the change (2026-10-30: the typing check's
    # `yes` did, and 48 has_tendency relations left the store view)
    assert gt.cell_predicate("Wound", "has_disposition", "Pressure ulcer risk") == "has_tendency"
    assert gt.cell_rejected("Wound", "has_tendency: Pressure ulcer risk")["by"] == T
    assert gt.cell_predicate("Wound", "has_disposition", "Pressure ulcer risk", reopen=T) == "has_tendency"
    gt.records["Wound"]["relations"]["has_tendency: Pressure ulcer risk"].append(J("yes", T))
    assert gt.cell_predicate("Wound", "has_disposition", "Pressure ulcer risk") == "has_tendency"
    assert gt.cell_rejected("Wound", "has_tendency: Pressure ulcer risk") is None
    # only the changing agent's own later word undoes it
    gt.records["Wound"]["relations"]["has_tendency: Pressure ulcer risk"].append(J("no", "tendency-not-disposition"))
    assert gt.cell_predicate("Wound", "has_disposition", "Pressure ulcer risk") is None
    assert heard([J("yes", R), J("no", T)], None) == [J("yes", R), J("no", T)]
    assert [j["by"] for j in heard([J("yes", R), J("no", T)], frozenset({T}))] == [R]


def test_the_store_view_tells_which_relations_a_judgement_leaves_out():
    """The figure from the abstracts to WONT counts why each relation is left
    out; the view reports those itself (`on_refused`), with the names it read
    the cells under, and yields exactly what it yields without being asked."""
    from wound_ontology.store.concept_store import ConceptStore

    class _DM:
        def __init__(self, data): self.data = data
        def load_latest_json(self, name): return self.data if name == "concept_store" else {}
        def save_as_json(self, data, name): pass

    T = "relation-typing-check"
    rec = {"entities": {"Wound": {"has_quality: Contamination": 1.0, "has_quality: Depth": 1.0}}}
    st = ConceptStore(_DM({"1": rec, "2": rec}), "concept_store")
    st.terms._put("Wound", "relations", st.terms._j("no", T, "subject ok; value violates"), "has_quality: Contamination")
    plain = dict(st.view())
    told = []
    asked = dict(st.view(on_refused=lambda *a: told.append(a)))
    assert asked == plain == {"1": {"Wound": {"has_quality: Depth": 1.0}}, "2": {"Wound": {"has_quality: Depth": 1.0}}}
    assert sorted((k, s, p, t, v) for k, s, p, t, _, _, v in told) == [
        ("1", "Wound", "has_quality", "Contamination", 1.0), ("2", "Wound", "has_quality", "Contamination", 1.0)]
    kept = []
    assert dict(st.view(on_kept=lambda *a: kept.append(a))) == plain        # it tells what it keeps, too
    assert sorted((k, s, p, t) for k, s, p, t, _, _, _ in kept) == [
        ("1", "Wound", "has_quality", "Depth"), ("2", "Wound", "has_quality", "Depth")]
    st.reopen = (frozenset({T, "elk"}), "relations")
    assert dict(st.view())["1"]["Wound"] == {"has_quality: Contamination": 1.0, "has_quality: Depth": 1.0}


def test_a_relation_is_judged_under_every_spelling_of_its_value():
    """2026-10-30: `Burn wound has_disposition` was read `no` under the
    spelling `Risk of infection` and, unseen, read again under `Infection
    risk`; both name one concept. `relation_cells` finds every cell of the
    relation, whatever the spelling of the value."""
    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import J, memory_mapping
    gt = memory_mapping()
    gt.spell("Risk of infection", "wound infecting tendency", by="author")
    gt.spell("Infection risk", "wound infecting tendency", by="author")
    gt.records.setdefault("Burn wound", {})["relations"] = {
        "has_disposition: Risk of infection": [J("no", "claude-opus-5-5_universality")],
        "has_disposition: Infection risk": [J("yes", "relation-typing-check")],
        "has_tendency: Risk of infection": [J("yes", "tendency-not-disposition")],
        "has_disposition: Depth": [J("yes", "relation-typing-check")]}
    gt._dirty()
    assert sorted(gt.relation_cells(["Burn wound"], "has_disposition", "wound infecting tendency")) == [
        ("Burn wound", "has_disposition: Infection risk"), ("Burn wound", "has_disposition: Risk of infection")]
    assert gt.relation_cells(["Burn wound", "Nobody"], "has_tendency", "Infection risk") == [
        ("Burn wound", "has_tendency: Risk of infection")]


def test_an_abstention_takes_back_its_own_agents_earlier_word():
    """Curator, 2026-10-30, asked whether "cannot tell" should take back the
    same agent's earlier verdict: "Ja, nur das eigene". The typing check's old
    `no` had kept 2 relations out of the store view after it answered
    `undecided`. Another agent's word stands."""
    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import J
    from wound_ontology.mappers.judgements import current
    T, R = "relation-typing-check", "claude-opus-5-5_universality"
    assert current([J("no", T), J("undecided", T)]) is None                  # its own no is withdrawn
    assert current([J("no", T), J("undecided", T), J("yes", T)])["verdict"] == "yes"
    assert current([J("no", R), J("undecided", T)])["by"] == R               # another's stands
    assert current([J("no", T), J("yes", R), J("undecided", T)])["by"] == R
    assert current([J("yes", "author"), J("undecided", "author"), J("no", T)])["by"] == T
    assert current([J("undecided", T)]) is None
