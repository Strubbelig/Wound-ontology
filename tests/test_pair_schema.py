"""First the cluster, then its name (curator, 2026-10-24).

A pair verdict answers one question in four words; the name of a cluster is a
decision on the chosen term; the curator's verdict, not a lock beside it, keeps a
pair apart (rule 84, 2026-10-25). See `TermMappingAndGate` (`PAIR_VERDICTS`,
`APART`, `decide_name`) and scripts/migrate_pair_schema.py.
"""
import pytest

from conftest import memory_mapper, memory_mapping
from wound_ontology.mappers.term_mapper import canonical_rank


# ── one question, four words ─────────────────────────────────────────────────

@pytest.mark.parametrize("old", ["kept", "reverse", "reversed", "repointed", "refused"])
def test_the_old_curator_words_are_refused(old):
    gt = memory_mapping({})
    with pytest.raises(ValueError, match="is not one of"):
        gt.judge("wounds", "Wound", curator={"verdict": old})


def test_there_is_no_lock_beside_the_verdict():
    gt = memory_mapping({})
    with pytest.raises(ValueError, match="'refused' is not one of"):
        gt.judge("wounds", "Wound", refused={"reason": "no", "by": "curator"})
    with pytest.raises(ValueError, match="a refusal is one of"):
        gt.refuse("wounds", "Wound", reason="no", verdict="same_class")


def test_a_refusal_is_the_curators_different():
    """The curator, 2026-10-25: "not this cluster" is `different`."""
    gt = memory_mapping({"wounds": {"to": "Wound", "pairs": {}}})
    gt.refuse("wounds", "Wound", reason="not here")
    j = gt.peek("wounds", "Wound")
    assert j["curator"]["verdict"] == "different" and "refused" not in j
    assert gt.is_refused("wounds", "Wound")["reason"] == "not here"
    assert gt.data.get("wounds") is None


def test_a_placement_keeps_the_term_out_of_its_parents_cluster():
    gt = memory_mapping({"venous stasis ulcer": {"to": None, "pairs": {
        "Venous leg ulcer": {"curator": {"verdict": "narrower", "iri": "x"}}}}})
    assert gt.is_refused("venous stasis ulcer", "Venous leg ulcer")
    with pytest.raises(ValueError, match="stands refused"):
        gt.add("venous stasis ulcer", "Venous leg ulcer")
    assert gt.add_batch({"venous stasis ulcer": "Venous leg ulcer"}) == [
        ("venous stasis ulcer", "Venous leg ulcer")]


def test_an_old_lock_is_history_and_reads_as_the_verdict_it_meant():
    gt = memory_mapping({"DF": {"to": None, "pairs": {
        "Diabetic foot": {"refused": {"cause": "rule 58", "reason": "ambiguous", "by": "x"}},
        "Burn injury": {"curator": {"verdict": "narrower"},
                        "refused": {"cause": "curator", "reason": "rule 79"}}}}})
    assert gt.is_refused("DF", "Diabetic foot")["verdict"] == "different"
    assert gt.peek("DF", "Burn injury")["curator"]["verdict"] == "narrower", "a verdict stands"


def test_a_refusal_with_a_relation_records_it_and_keeps_the_old_answer():
    gt = memory_mapping({"burn wound": {"to": "Burn injury", "pairs": {
        "Burn injury": {"curator": {"verdict": "same_class", "reason": "earlier"}}}}})
    gt.refuse("burn wound", "Burn injury", reason="a burn wound is a burn injury",
              verdict="narrower")
    j = gt.peek("burn wound", "Burn injury")
    assert j["curator"]["verdict"] == "narrower"
    assert [x["verdict"] for x in gt.records["burn wound"]["pairs"]["Burn injury"]] == \
        ["same_class", "narrower"], "the earlier answer stays on record"


def test_a_refusal_moves_a_standing_same_class_to_history():
    """One class and kept apart at once is the contradiction the old schema held 30 times."""
    gt = memory_mapping({"a": {"to": "b", "pairs": {"b": {"curator": {"verdict": "same_class"}}}}})
    gt.refuse("a", "b", reason="not after all")
    j = gt.peek("a", "b")
    assert j["curator"]["verdict"] == "different"
    assert [x["verdict"] for x in gt.records["a"]["pairs"]["b"]] == ["same_class", "different"]
    assert gt.data.get("a") is None


# ── the name is `to`; that a person chose it is their same_class (rule 85) ──

def test_a_name_choice_is_to_and_the_curators_same_class():
    gt = memory_mapping({})
    gt.decide_name("snakebite envenomation", ["Snake Envenomation"], reason="review")
    assert gt.data == {"Snake Envenomation": "snakebite envenomation"}
    cur = gt.peek("Snake Envenomation", "snakebite envenomation")["curator"]
    assert cur["verdict"] == "same_class" and cur["reason"] == "review"
    assert gt.named() == {"snakebite envenomation"}
    assert "name" not in gt.records.get("snakebite envenomation", {})


def test_a_later_choice_turns_the_cluster_round():
    gt = memory_mapping({})
    gt.decide_name("therapy", ["treatment"], when="2026-09-25T18:00:00")
    gt.decide_name("treatment", ["therapy"], when="2026-09-27T15:05:12")
    assert gt.data == {"therapy": "treatment"}
    assert gt.named() == {"treatment"}


def test_members_of_a_loser_follow_the_name():
    gt = memory_mapping({"wound areas": {"to": "wound area", "pairs": {}}})
    gt.decide_name("area of wound", ["wound area"])
    assert gt.data == {"wound areas": "area of wound", "wound area": "area of wound"}


def test_an_ontology_label_stays_the_name():
    """Rule 36: the person's choice lands under the label, not over it."""
    gt = memory_mapping({"wound healing": {"to": "Wound healing process", "pairs": {}}})
    gt.decide_name("wound healing", ["wound repair"])
    assert gt.data["wound repair"] == "Wound healing process"
    assert gt.data["wound healing"] == "Wound healing process"


def test_a_choice_against_the_curators_apart_is_refused():
    gt = memory_mapping({"a": {"to": None, "pairs": {"b": {"curator": {"verdict": "different"}}}}})
    with pytest.raises(ValueError, match="apart"):
        gt.decide_name("b", ["a"])


def test_a_name_outranks_the_corpus_and_an_anchor_outranks_a_name():
    freq = {"wound area": 40, "area of wound": 2}
    assert max(freq, key=lambda t: canonical_rank(t, frozenset(), freq, {"area of wound"})) \
        == "area of wound"
    assert max(freq, key=lambda t: canonical_rank(t, {"wound area"}, freq, {"area of wound"})) \
        == "wound area"


def test_a_cluster_keeps_its_name_when_the_counts_shift():
    """Rule 85: only a label or a person moves a name, never the corpus."""
    freq = {"wound area": 40, "area of wound": 2}
    assert max(freq, key=lambda t: canonical_rank(t, frozenset(), freq, frozenset(),
                                                  {"area of wound"})) == "area of wound"


def test_resolve_chains_keeps_the_name_a_person_chose():
    m = memory_mapper({"wound areas": "wound area", "area of wound": "wound area"})
    m._term_mapping.decide_name("area of wound", ["wound area"])
    m.resolve_chains(frequencies={"wound area": 40, "area of wound": 2})
    assert m.mapping == {"wound areas": "area of wound", "wound area": "area of wound"}


def test_a_name_choice_follows_a_rename():
    gt = memory_mapping({"Snake Envenomation": {"to": "snakebite envenomation", "pairs": {}}})
    gt.decide_name("snakebite envenomation", ["Snake Envenomation"])
    gt.apply_renames({"snakebite envenomation": "Snakebite envenomation",
                      "Snake Envenomation": "Snake envenomation"}, by="pass0")
    assert gt.named() == {"Snakebite envenomation"}
    assert gt.data == {"Snake envenomation": "Snakebite envenomation"}


def test_an_old_name_section_loads_as_the_curators_same_class():
    gt = memory_mapping({
        "Snake Envenomation": {"to": "snakebite envenomation", "pairs": {}},
        "snakebite envenomation": {"to": None, "pairs": {}, "name": {
            "by": "curator", "instead_of": ["Snake Envenomation"], "reason": "review",
            "when": "2026-09-25", "history": [{"by": "curator", "instead_of": ["x"]}]}}})
    assert gt.peek("Snake Envenomation", "snakebite envenomation")["curator"]["verdict"] == "same_class"
    assert gt.named() == {"snakebite envenomation"}


# ── a confirmed synonym stays in one cluster ─────────────────────────────────

def test_a_step_never_retires_what_the_curator_confirmed():
    """237 confirmed pairs were split by pass 1 dissent and dead-target prunes."""
    gt = memory_mapping({"Klebsiella": {"to": "Klebsiella spp.", "pairs": {
        "Klebsiella spp.": {"curator": {"verdict": "same_class"}}}}})
    assert gt.retire("Klebsiella", reason="pass 1 did not confirm") == 0
    assert gt.data == {"Klebsiella": "Klebsiella spp."}


def test_split_synonyms_names_a_confirmed_pair_in_two_clusters():
    gt = memory_mapping({"Klebsiella": {"to": None, "pairs": {
        "Klebsiella spp.": {"curator": {"verdict": "same_class"}}}}})
    assert gt.split_synonyms() == [("Klebsiella", "Klebsiella spp.")]
    gt.decide_name("Klebsiella spp.", ["Klebsiella"])
    assert gt.split_synonyms() == []


# ── a merge never maps onto a target its own pair locks ──────────────────────

def test_a_merge_does_not_map_onto_a_locked_target():
    """`Antiseptic agent -> antiseptic drug`, 2026-10-20: one spelling carried
    the mapping, the other the curator's refusal, and the merge kept both."""
    gt = memory_mapping({
        "Antiseptic agent": {"to": None, "pairs": {"antiseptic drug": {
            "refused": {"cause": "curator", "reason": "relatedMatch", "by": "curator"}}}},
        "antiseptic agent": {"to": "antiseptic drug", "pairs": {}}})
    report = gt.apply_renames({"antiseptic agent": "Antiseptic agent"}, by="pass0")
    assert gt.data.get("Antiseptic agent") is None
    assert report["locked targets"] == [("Antiseptic agent", "antiseptic drug")]
    assert gt.locked_mappings() == []
