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

Rule 51 (2026-09-27) moved WHERE the label changes: the concept store keeps
what each abstract said, and the rename is an alias in the term dict that the
store's view reads through. The store tests below therefore read the view, and
check that the evidence itself is untouched.
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

def _view(s):
    return dict(s.records())


def test_an_entity_name_reads_the_new_spelling_and_the_evidence_keeps_the_old():
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": 1.0}}}})
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert list(_view(s)["1"]) == ["Tumor"]
    assert list(s.dict["1"]["entities"]) == ["Tumours"]


def test_the_target_half_of_a_triple_moves_with_it():
    """A rename that stops at entity names leaves the same term spelled two
    ways in one store — as a subject it reads `Tumor`, as an object `Tumours`."""
    s = _store({"1": {"entities": {"Lesion": {"is_a: Tumours": 1.0}}}})
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert list(_view(s)["1"]["Lesion"]) == ["is_a: Tumor"]


@pytest.mark.parametrize("first,second", [(0.4, 0.9), (0.9, 0.4)])
def test_two_spellings_landing_on_one_name_keep_the_strongest_evidence(first, second):
    """Both orders, because the weaker value arriving SECOND is the case a
    plain assignment gets wrong and the first order hides."""
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": first},
                                   "tumour": {"is_a: Neoplasm": second}}}})
    s.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert _view(s)["1"] == {"Tumor": {"is_a: Neoplasm": 0.9}}


def test_a_verdict_follows_the_name_it_was_written_against():
    """Rule 33: a rejection is a verdict on the record. A rename that leaves
    the verdict behind un-rejects the term, and it comes back."""
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": 1.0}}}})
    s.reject_entities(["Tumours"], by="curator", note="methodology")
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert s.verdict("Tumor") is not None
    assert s.verdict("Tumours") == s.verdict("Tumor"), "one concept, one answer"
    assert set(s.terms.records["Tumours"]) == {"name"}


def test_the_old_spelling_stays_recoverable():
    """Nothing is deleted — the extractor's spelling is a name judgement in the
    term dict with who made it (rules 33, 89)."""
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": 1.0}}}})
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert s.decisions()["renamed"]["Tumours"]["to"] == "Tumor"
    assert s.decisions()["renamed"]["Tumours"]["by"] == "string-normalisation"


def test_a_name_pass0_did_not_name_is_not_touched():
    """`normalize` matches on a folded key because the mapping is written
    against extraction spellings. Pass 0 is handed every string the store
    holds, so a folded fallback here could only rename something it never
    looked at and never reported."""
    s = _store({"1": {"entities": {"Tumours": {"is_a: Neoplasm": 1.0},
                                   "TUMOURS": {"is_a: Neoplasm": 1.0}}}})
    s.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert set(_view(s)["1"]) == {"Tumor", "TUMOURS"}


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
                             "pairs": {"Tumours": {"pass1": {"verdict": "same_class"},
                                                   "curator": {"verdict": "different", "by": "moritz"}}}}})
    m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert m.peek("lesion", "Tumor")["pass1"]["verdict"] == "same_class"
    assert m.is_refused("lesion", "Tumor")["by"] == "author"


def test_two_records_landing_on_one_key_merge_and_keep_both_verdicts():
    m = _mapping({"Tumours": {"to": "Neoplasm", "pairs": {"Neoplasm": {"pass1": {"verdict": "same_class"}}}},
                  "tumour": {"to": "Neoplasm", "pairs": {"Neoplasm": {"pass2": {"verdict": "same_class"}}}}})
    report = m.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert report["records merged"] == 1
    assert {"pass1", "pass2"} <= set(m.peek("Tumor", "Neoplasm"))


def test_two_records_claiming_different_canonicals_are_reported_not_hidden():
    """Two spellings of one term pointing at DIFFERENT canonicals is a real
    disagreement, not a spelling question. Both names stay on record; which
    one counts is said out loud (rule 89 decides it: the later one)."""
    m = _mapping({"Tumours": {"to": "Neoplasm", "pairs": {}},
                  "tumour": {"to": "Growth", "pairs": {}}})
    report = m.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert report["target conflicts"] == [("Tumor", ["Growth", "Neoplasm"], m.data["Tumor"])]
    assert len(m.records["Tumor"]["name"]) == 2


def test_an_entry_that_became_its_own_target_keeps_its_name_on_the_old_spelling():
    """The curator, 2026-09-26: after normalising, the sole spelling mappings
    are identity mappings. Rule 89 deletes nothing: the old string keeps the
    name it was given, which is now the spelling, and is no mapping."""
    m = _mapping({"Tumours": {"to": "Tumor", "pairs": {"Tumor": {"pass1": {"verdict": "same_class"}}}}})
    report = m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert report["names kept on the old spelling"] == 1
    assert m.data == {} and m.resolve("Tumours") == "Tumor"


def test_a_record_that_also_carries_a_gate_keeps_it():
    """Whether a term belongs (rule 40) is a different decision that happens
    to live on the same record."""
    m = _mapping({"Tumours": {"to": "Tumor", "pairs": {},
                              "gate": {"curator": {"verdict": "in"}}}})
    m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert m.data == {} and m.gate_verdict("Tumor") == ("in", "author")


def test_a_judgement_about_another_canonical_survives_the_rename():
    m = _mapping({"Tumours": {"to": "Tumor",
                              "pairs": {"Tumor": {"pass1": {"verdict": "same_class"}},
                                        "Growth": {"curator": {"verdict": "different", "by": "moritz"}}}}})
    m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert m.is_refused("Tumor", "Growth")["by"] == "author"


def test_the_gate_travels_with_the_record():
    m = _mapping({"Tumours": {"to": None, "pairs": {},
                              "gate": {"curator": {"verdict": "in"}}}})
    m.apply_renames({"Tumours": "Tumor"}, by="pass0")
    assert m.gate_verdict("Tumor") == ("in", "author")


def test_a_merge_keeps_the_scope_judgements_of_both_spellings():
    """Whether a term belongs is a judgement on its record (rule 40). A merge
    that drops one spelling's loses a scope decision."""
    m = _mapping({"Tumours": {"to": None, "pairs": {},
                              "gate": {"pass1": {"verdict": "out", "near": "x", "score": 0.97}}},
                  "tumour": {"to": None, "pairs": {},
                             "gate": {"pass2": {"verdict": "in", "reason": "r"}}}})
    m.apply_renames({"Tumours": "Tumor", "tumour": "Tumor"}, by="pass0")
    assert {j["by"] for j in m.records["Tumor"]["scope"]} == {"sapbert-neighbour", "deepseek-v4-flash"}


def test_a_merge_whose_spellings_were_judged_differently_surfaces_for_review():
    """Two spellings of one term judged `in` and `out` (2026-09-26: `pain score`
    and `pain scores`): both stay on record, the read rule picks one, and the
    disagreement is in the review queue."""
    m = _mapping({"pain scores": {"to": None, "pairs": {},
                                  "gate": {"pass2": {"verdict": "in", "reason": "a"}}},
                  "pain score": {"to": None, "pairs": {},
                                 "gate": {"curator": {"verdict": "out", "reason": "b"}}}})
    m.apply_renames({"pain scores": "pain score"}, by="pass0")
    assert [j["verdict"] for j in m.records["pain score"]["scope"]] == ["in", "out"] or \
        sorted(j["verdict"] for j in m.records["pain score"]["scope"]) == ["in", "out"]
    assert [r["term"] for r in m.gate_disagreements()] == ["pain score"]
    assert m.gate_verdict("pain score") == ("out", "author")


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
