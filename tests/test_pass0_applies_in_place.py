"""Pass 0 changes the labels where they live, in both places that hold them.

The curator, 2026-09-26: *pass 0 should not create another mapping, it should
change the labels right at the spot* — and then *it should be applied to the
concept store AND the termmapping dict just to make sure nothing slipped
through*.

What that replaced: pass 0 wrote 32,302 `member -> canonical` entries into the
term mapping. Two costs. The record a curator reads filled up with mechanical
respellings, burying the few hundred decisions that need eyes; and the store
went on holding the un-normalised spelling, so the term-mapping build had to
inject **23,220 canonicals that were not store strings** into its clustering,
with borrowed frequencies, because pass 0's answers lived in the mapping
instead of in the store.

Normalising only one of the two would be worse than either: the mapping would
keep handing the store back spellings the rules had just rejected.
"""

import pytest

from wound_ontology.store.concept_store import ConceptStore


class MockDM:
    def __init__(self, initial=None):
        self._data = initial

    def load_latest_json(self, _):
        return self._data

    def save_as_json(self, data, _):
        import json
        self._data = json.loads(json.dumps(data))
        return "concept_store"


def _store(data):
    return ConceptStore(MockDM(data), "concept_store")


# ── the store ────────────────────────────────────────────────────────────────

def test_an_entity_name_is_rewritten_where_it_stands():
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": 1.0}}}})
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert list(s.dict["1"]["entities"]) == ["Tumor"]


def test_the_target_half_of_a_triple_moves_with_it():
    """A rename that stops at entity names leaves the same term spelled two
    ways in one store — as a subject it reads `Tumor`, as an object `Tumours`."""
    s = _store({"1": {"entities": {"Lesion": {"is_a: Tumours": 1.0}}}})
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert list(s.dict["1"]["entities"]["Lesion"]) == ["is_a: Tumor"]


@pytest.mark.parametrize("first,second", [(0.4, 0.9), (0.9, 0.4)])
def test_two_spellings_landing_on_one_name_keep_the_strongest_evidence(first, second):
    """Both orders, because the weaker value arriving SECOND is the case a
    plain assignment gets wrong and the first order hides."""
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": first},
                                   "tumour": {"is_a: Neoplasm": second}}}})
    s.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert s.dict["1"]["entities"] == {"Tumor": {"is_a: Neoplasm": 0.9}}


def test_a_verdict_follows_the_name_it_was_written_against():
    """Rule 33: a rejection is a verdict on the record. A rename that leaves
    the verdict behind un-rejects the term, and it comes back."""
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": 1.0}}}})
    s.reject_entities(["Tumours"], by="curator", note="methodology")
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert s.verdict("Tumor") is not None
    assert s.verdict("Tumours") is None


def test_the_old_spelling_stays_recoverable():
    """Nothing is deleted — the extractor's spelling is stamped in the store's
    own `renamed` book with who did it (rule 33)."""
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": 1.0}}}})
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert s.decisions()["renamed"]["Tumours"]["to"] == "Tumor"
    assert s.decisions()["renamed"]["Tumours"]["by"] == "pass0"


def test_a_name_pass0_did_not_name_is_not_touched():
    """`normalize` matches on a folded key because the mapping is written
    against extraction spellings. Pass 0 is handed every string the store
    holds, so a folded fallback here could only rename something it never
    looked at and never reported."""
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": 1.0},
                                   "TUMOURS": {"is_a: Neoplasm": 1.0}}}})
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert set(s.dict["1"]["entities"]) == {"Tumor", "TUMOURS"}


# ── the mapping ──────────────────────────────────────────────────────────────

def _mapping(records):
    from conftest import MemoryDataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    return TermMappingAndGate(MemoryDataManager(records))


def test_a_record_key_is_rewritten():
    m = _mapping({"Tumours": {"to": "Neoplasm", "pairs": {}}})
    m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert m.data == {"Tumor": "Neoplasm"}


def test_a_live_target_is_rewritten():
    m = _mapping({"lesion": {"to": "Tumours", "pairs": {}}})
    m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert m.data == {"lesion": "Tumor"}


def test_a_verdict_stays_attached_to_the_pair_it_was_about():
    """The verdicts are keyed BY CANONICAL. Respelling the canonical without
    them detaches every judgement a model or a curator made about that pair,
    and the next build pays to ask again — or worse, re-proposes something a
    curator refused."""
    m = _mapping({"lesion": {"to": "Tumours",
                             "pairs": {"Tumours": {"curator": {"verdict": "y"},
                                                   "refused": {"by": "moritz"}}}}})
    m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert m.peek("lesion", "Tumor")["curator"] == {"verdict": "y"}
    assert m.is_refused("lesion", "Tumor") == {"by": "moritz"}


def test_two_records_landing_on_one_key_merge_and_keep_both_verdicts():
    m = _mapping({"Tumours": {"to": "Neoplasm", "pairs": {"Neoplasm": {"pass1": {"v": 1}}}},
                  "tumour": {"to": "Neoplasm", "pairs": {"Neoplasm": {"pass2": {"v": 2}}}}})
    report = m.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert report["records merged"] == 1
    assert set(m.peek("Tumor", "Neoplasm")) == {"pass1", "pass2"}


def test_two_records_claiming_different_canonicals_are_reported_not_chosen():
    """Two spellings of one term pointing at DIFFERENT canonicals is a real
    disagreement, not a spelling question. Both survive in `pairs`; which one
    is live is said out loud."""
    m = _mapping({"Tumours": {"to": "Neoplasm", "pairs": {}},
                  "tumour": {"to": "Growth", "pairs": {}}})
    report = m.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert report["target conflicts"] == [("Tumor", "Neoplasm", "Growth")]


def test_an_entry_that_became_its_own_target_is_deleted():
    """The curator, 2026-09-26: *you can delete the sole spelling mappings —
    after normalising they are identity mappings.*

    Rule 37 keeps a retired entry because it carries verdicts that cost
    credits. A verdict about the pair (term, term) is a verdict about the
    spelling question pass 0 has just settled by rule, so there is nothing
    left to keep.
    """
    m = _mapping({"Tumours": {"to": "Tumor", "pairs": {"Tumor": {"pass1": {"v": 1}}}}})
    report = m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert report["identities dropped"] == 1 and report["records deleted"] == 1
    assert m.data == {} and "Tumor" not in m.records


def test_a_record_that_also_carries_a_gate_survives_the_deletion():
    """Whether a term belongs (rule 40) is a different decision that happens
    to live on the same record. Deleting the spelling mapping must not take a
    scope verdict with it."""
    m = _mapping({"Tumours": {"to": "Tumor", "pairs": {},
                              "gate": {"curator": {"verdict": "in"}}}})
    report = m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert report["identities dropped"] == 1 and report["records deleted"] == 0
    assert m.data == {} and m.peek_gate("Tumor") == {"curator": {"verdict": "in"}}


def test_a_judgement_about_another_canonical_survives_the_deletion():
    m = _mapping({"Tumours": {"to": "Tumor",
                              "pairs": {"Tumor": {"pass1": {"v": 1}},
                                        "Growth": {"refused": {"by": "moritz"}}}}})
    report = m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert report["records deleted"] == 0
    assert m.is_refused("Tumor", "Growth") == {"by": "moritz"}
    assert m.peek("Tumor", "Tumor") == {}, "the self-pair decides nothing"


def test_the_gate_travels_with_the_record():
    m = _mapping({"Tumours": {"to": None, "pairs": {},
                              "gate": {"curator": {"verdict": "in"}}}})
    m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert m.peek_gate("Tumor") == {"curator": {"verdict": "in"}}


def test_a_merge_keeps_the_gate_verdicts_of_both_spellings():
    """Whether a term belongs is a verdict on its record (rule 40). A merge
    that drops one spelling's gate loses a scope decision — and the term comes
    back into the hierarchy views it had been ruled out of."""
    m = _mapping({"Tumours": {"to": None, "pairs": {},
                              "gate": {"pass1": {"verdict": "out"}}},
                  "tumour": {"to": None, "pairs": {},
                             "gate": {"pass2": {"verdict": "in"}}}})
    m.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert set(m.peek_gate("Tumor")) == {"pass1", "pass2"}


def test_a_gate_source_that_contradicts_itself_decides_nothing():
    """Two spellings of one term whose SAME source answers differently.

    First-come used to win and the other side was gone — 10 of them on the
    2026-09-26 data, `pain score` among them, where pass 2 said `in` of one
    spelling and `out` of another. Surfacing disagreement is the whole reason
    the gate holds two passes (rule 40), so a source contradicting ITSELF
    decides nothing either, and both sides stay where a person can see them.
    """
    m = _mapping({"pain scores": {"to": None, "pairs": {},
                                  "gate": {"pass2": {"verdict": "in"}}},
                  "pain score": {"to": None, "pairs": {},
                                 "gate": {"pass2": {"verdict": "out"}}}})
    report = m.apply_renames({"pain scores": "pain score"}, by="pass0")
    assert len(report["gate conflicts"]) == 1
    assert "pass2" not in m.peek_gate("pain score")
    contested = m.records["pain score"]["gate_contested"]
    assert {contested[0]["kept"]["verdict"], contested[0]["dropped"]["verdict"]} == {"in", "out"}


def test_the_same_verdict_twice_is_folded_not_reported():
    m = _mapping({"pain scores": {"to": None, "pairs": {},
                                  "gate": {"pass2": {"verdict": "in"}}},
                  "pain score": {"to": None, "pairs": {},
                                 "gate": {"pass2": {"verdict": "in"}}}})
    report = m.apply_renames({"pain scores": "pain score"}, by="pass0")
    assert report["gate conflicts"] == []
    assert m.peek_gate("pain score")["pass2"]["verdict"] == "in"


def test_the_chains_the_rename_reveals_are_counted():
    """`A -> B` beside `b -> C` was always a chain — `B` and `b` are one term
    and the spelling hid it. Making it visible is the point; leaving the
    operator to discover it downstream is not."""
    m = _mapping({"lesion": {"to": "Tumours", "pairs": {}},
                  "tumour": {"to": "Neoplasm", "pairs": {}}})
    report = m.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert report["chains"] == 1


def test_nothing_is_written_when_there_is_nothing_to_rename():
    m = _mapping({"lesion": {"to": "Tumor", "pairs": {}}})
    report = m.apply_renames({}, by="pass0")
    assert report["keys renamed"] == 0 and m.data == {"lesion": "Tumor"}
