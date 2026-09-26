"""The mapping is the ground truth; everything else about it is a view (rule 38).

Before this, one pair's verdicts lived in four places: `pass1` on the record,
the same verdict in `mapping_adjudication_*.json`, `pass2` on the record and in
`mapping_second_opinion_*.json`. Two writers per fact and nothing keeping them
equal. Worse, 2,548 of the 7,224 terms the model had judged were not in the
mapping at all, so their verdicts were reachable only by opening a cache file
nothing downstream reads -- and the subsumption CSV was written from whatever
this run happened to RE-ASK, so a pair judged `narrower` in September vanished
from the file in October the moment the cache answered it from memory.

These tests pin the shape that fixes it: the record holds every verdict, and
`pass_cache`, `verdicts`, `subsumption_candidates`, `disagreements` and `data`
are computed from it on every call.
"""

import pytest

from conftest import memory_mapper, memory_mapping
from wound_ontology.mappers.mapping_adjudicator import pair_key
from wound_ontology.mappers.term_mapping_and_gate import KEY_SEP


# ── The key ──────────────────────────────────────────────────────────────────

def test_the_pair_key_is_one_implementation():
    """Two copies of a key format is two chances to write a verdict where
    nothing will look for it."""
    assert pair_key("wounds", "Wound") == f"wounds{KEY_SEP}Wound"


# ── Migration ────────────────────────────────────────────────────────────────

def test_a_flat_file_becomes_records():
    tm = memory_mapping({"wounds": "Wound"})
    assert tm.data == {"wounds": "Wound"}
    assert tm.records["wounds"]["pairs"] == {}


def test_a_verdict_that_sat_on_the_term_moves_onto_the_pair():
    """v2 kept `pass1` at the term level, which quietly assumed a term is only
    ever judged against one canonical. 192 terms in the live file are not."""
    tm = memory_mapping({"wounds": {"to": "Wound", "refused": {},
                                    "pass1": {"verdict": "same_class", "reason": "plural"}}})
    assert tm.peek("wounds", "Wound")["pass1"]["verdict"] == "same_class"
    assert "pass1" not in tm.records["wounds"]


def test_a_v2_refusal_moves_onto_the_pair_it_was_always_about():
    tm = memory_mapping({"materials": {"to": None,
                                       "refused": {"material entity": {"by": "curator"}}}})
    assert tm.is_refused("materials", "material entity")["by"] == "curator"
    assert tm.is_refused("materials", "Wound dressing material") is None


def test_migration_is_idempotent():
    once = memory_mapping({"wounds": {"to": "Wound", "refused": {},
                                      "pass1": {"verdict": "same_class"}}})
    twice = memory_mapping(once.records)
    assert twice.records == once.records


# ── The pass cache is the record ─────────────────────────────────────────────

def test_a_verdict_written_through_the_cache_lands_on_the_record():
    tm = memory_mapping({"wounds": "Wound"})
    cache = tm.pass_cache("pass1")
    cache[pair_key("wounds", "Wound")] = {"verdict": "same_class", "reason": "plural"}
    assert tm.peek("wounds", "Wound")["pass1"]["reason"] == "plural"
    assert cache.get(pair_key("wounds", "Wound"))["verdict"] == "same_class"


def test_a_verdict_survives_for_a_pair_that_is_no_longer_mapped():
    """The whole point of the cache was memory across builds. Withdrawing the
    entry must not throw the model's answer away with it."""
    tm = memory_mapping({"wounds": "Wound"})
    tm.pass_cache("pass1")[pair_key("wounds", "Wound")] = {"verdict": "different"}
    tm.retire("wounds", reason="inert")
    assert tm.data == {}
    assert tm.pass_cache("pass1").get(pair_key("wounds", "Wound"))["verdict"] == "different"


def test_the_verdict_listing_includes_pairs_that_are_no_longer_mapped():
    """2,548 of the 7,224 terms the model has judged are not in the live
    mapping. A listing that quietly dropped them would under-report what has
    been asked and re-spend the credits asking again."""
    tm = memory_mapping({"wounds": "Wound"})
    tm.judge("gone", "Gone class", pass1={"verdict": "different"})
    assert tm.judged("pass1") == 1
    assert pair_key("gone", "Gone class") in tm.verdicts("pass1")


def test_a_cache_miss_does_not_create_the_record_it_missed():
    """A build asks the cache about every proposed pair. If a miss created a
    record, one build would write thousands of empty ones into the truth."""
    tm = memory_mapping({"wounds": "Wound"})
    assert tm.pass_cache("pass1").get(pair_key("never", "asked")) is None
    assert "never" not in tm.records


def test_readjudicate_reads_nothing_and_still_writes():
    tm = memory_mapping({"wounds": "Wound"})
    tm.pass_cache("pass1")[pair_key("wounds", "Wound")] = {"verdict": "same_class"}
    fresh = tm.pass_cache("pass1", read=False)
    assert fresh.get(pair_key("wounds", "Wound")) is None       # every pair re-asked
    fresh[pair_key("wounds", "Wound")] = {"verdict": "different"}
    assert tm.peek("wounds", "Wound")["pass1"]["verdict"] == "different"


def test_one_term_judged_against_two_canonicals_keeps_both_verdicts():
    tm = memory_mapping()
    tm.judge("materials", "material entity", pass1={"verdict": "different"})
    tm.judge("materials", "Wound dressing material", pass1={"verdict": "same_class"})
    assert tm.peek("materials", "material entity")["pass1"]["verdict"] == "different"
    assert tm.peek("materials", "Wound dressing material")["pass1"]["verdict"] == "same_class"


def test_the_two_passes_do_not_overwrite_each_other():
    tm = memory_mapping({"wounds": "Wound"})
    tm.pass_cache("pass1")[pair_key("wounds", "Wound")] = {"verdict": "same_class"}
    tm.pass_cache("pass2")[pair_key("wounds", "Wound")] = {"verdict": "different"}
    assert tm.judged("pass1") == tm.judged("pass2") == 1
    assert tm.peek("wounds", "Wound")["pass1"]["verdict"] == "same_class"


# ── Retiring keeps what it used to throw away ────────────────────────────────

def test_a_retired_entry_leaves_the_mapping_but_not_the_record():
    tm = memory_mapping({"wounds": "Wound"})
    assert tm.retire("wounds", reason="inert spelling") == 1
    assert tm.data == {} and "wounds" in tm.records
    assert tm.records["wounds"]["retired"]["reason"] == "inert spelling"


def test_retiring_something_already_unmapped_changes_nothing():
    tm = memory_mapping({"wounds": "Wound"})
    tm.retire("wounds")
    assert tm.retire("wounds") == 0


def test_re_adding_a_retired_term_clears_the_retirement():
    tm = memory_mapping({"wounds": "Wound"})
    tm.retire("wounds", reason="inert")
    tm.add("wounds", "Skin wound")
    assert tm.data == {"wounds": "Skin wound"}
    assert "retired" not in tm.records["wounds"]


# ── A refusal cannot be overwritten by accident ──────────────────────────────

def test_adding_a_refused_pair_raises_instead_of_reversing_it():
    tm = memory_mapping()
    tm.refuse("wounds", "Wound", reason="not the same concept here")
    with pytest.raises(ValueError, match="stands refused"):
        tm.add("wounds", "Wound")


def test_a_deliberate_override_reverses_it_and_clears_the_refusal():
    tm = memory_mapping()
    tm.refuse("wounds", "Wound", reason="mistake")
    tm.add("wounds", "Wound", override=True)
    assert tm.data == {"wounds": "Wound"}
    assert tm.is_refused("wounds", "Wound") is None


def test_add_batch_skips_a_refused_pair_and_says_which():
    tm = memory_mapping()
    tm.refuse("wounds", "Wound", reason="no")
    skipped = tm.add_batch({"wounds": "Wound", "ulcers": "Ulcer"})
    assert skipped == [("wounds", "Wound")]
    assert tm.data == {"ulcers": "Ulcer"}


def test_the_build_reports_the_proposals_a_refusal_blocked(capsys):
    m = memory_mapper()
    m._term_mapping.refuse("wounds", "Wound", reason="no")
    m._term_mapping.add_batch({"wounds": "Wound"})   # direct: no report
    m._report_skipped([("wounds", "Wound")], "this build")
    assert "refusal stands" in capsys.readouterr().out


# ── The views ────────────────────────────────────────────────────────────────

def test_the_subsumption_view_is_the_whole_record_not_one_run():
    tm = memory_mapping()
    tm.judge("pressure ulcer", "Ulcer", pass1={"verdict": "narrower", "reason": "a kind of"})
    tm.judge("wound", "Skin wound", pass1={"verdict": "broader", "reason": "wider"})
    tm.judge("wounds", "Wound", pass1={"verdict": "same_class"})
    rows = tm.subsumption_candidates()
    assert len(rows) == 2
    assert {r["store term"] for r in rows} == {"pressure ulcer", "wound"}


def test_the_subsumption_view_puts_the_specific_class_first():
    tm = memory_mapping()
    tm.judge("pressure ulcer", "Ulcer", pass1={"verdict": "narrower"})
    tm.judge("wound", "Skin wound", pass1={"verdict": "broader"})
    rows = {r["store term"]: r for r in tm.subsumption_candidates()}
    assert rows["pressure ulcer"]["Class"] == "pressure ulcer"
    assert rows["pressure ulcer"]["Parent class"] == "Ulcer"
    assert rows["wound"]["Class"] == "Skin wound"
    assert rows["wound"]["Parent class"] == "wound"


def test_pass_two_alone_can_raise_a_subsumption_candidate():
    tm = memory_mapping()
    tm.judge("pressure ulcer", "Ulcer",
             pass1={"verdict": "same_class"}, pass2={"verdict": "narrower"})
    rows = tm.subsumption_candidates()
    assert len(rows) == 1 and rows[0]["Class"] == "pressure ulcer"
    assert rows[0]["agree"] is False


def test_disagreements_are_exactly_where_the_passes_differ():
    tm = memory_mapping()
    tm.judge("a", "A", pass1={"verdict": "same_class"}, pass2={"verdict": "different"})
    tm.judge("b", "B", pass1={"verdict": "same_class"}, pass2={"verdict": "same_class"})
    tm.judge("c", "C", pass1={"verdict": "same_class"})          # pass 2 never ran
    rows = tm.disagreements()
    assert [r["term"] for r in rows] == ["a"]


def test_a_view_is_recomputed_not_stored():
    """A view that cached itself could report a truth that is no longer true --
    which is the defect the cache files were."""
    tm = memory_mapping()
    assert tm.verdicts("pass1") == {} and tm.subsumption_candidates() == []
    tm.judge("pressure ulcer", "Ulcer", pass1={"verdict": "narrower"})
    assert len(tm.verdicts("pass1")) == 1
    assert len(tm.subsumption_candidates()) == 1


def test_the_live_mapping_excludes_refused_and_retired():
    tm = memory_mapping({"a": "A", "b": "B", "c": "C"})
    tm.refuse("a", "A")
    tm.retire("b", reason="inert")
    assert tm.data == {"c": "C"}
    assert set(tm.records) == {"a", "b", "c"}


# ── Importing the retired cache files ────────────────────────────────────────

def test_import_pass_folds_a_cache_file_onto_the_records():
    tm = memory_mapping({"wounds": "Wound"})
    rep = tm.import_pass("pass1", {
        pair_key("wounds", "Wound"): {"verdict": "same_class", "reason": "plural"},
        pair_key("gone", "Gone class"): {"verdict": "different", "reason": "no"},
    })
    assert rep["added"] == 2 and rep["new_records"] == 1 and rep["conflicts"] == 0
    assert tm.judged("pass1") == 2
    # the judged-but-unmapped term is on record and still not mapped
    assert "gone" in tm.records and tm.data == {"wounds": "Wound"}


def test_import_pass_reports_a_conflict_instead_of_overwriting():
    tm = memory_mapping()
    tm.judge("wounds", "Wound", pass1={"verdict": "same_class"})
    rep = tm.import_pass("pass1", {pair_key("wounds", "Wound"): {"verdict": "different"}})
    assert rep["conflicts"] == 1 and rep["added"] == 0
    assert tm.peek("wounds", "Wound")["pass1"]["verdict"] == "same_class"
    assert rep["clashes"] and "wounds" in rep["clashes"][0]


def test_import_pass_counts_what_was_already_there():
    tm = memory_mapping()
    tm.judge("wounds", "Wound", pass1={"verdict": "same_class"})
    rep = tm.import_pass("pass1", {pair_key("wounds", "Wound"): {"verdict": "same_class"}})
    assert rep["already_on_record"] == 1 and rep["added"] == 0


def test_a_cache_key_that_is_not_a_pair_raises():
    tm = memory_mapping()
    with pytest.raises(ValueError, match="not a pass1 pair key"):
        tm.import_pass("pass1", {"wounds": {"verdict": "same_class"}})
