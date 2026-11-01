"""Rule 87 (2026-10-26): a decided category is the `is_a` relation it settles,
and a term the abstracts use for two things points at one name per category.

The curator, on the `category` and `senses` sections beside `relations` and
`to`: "category macht keinen sinn wenn es is_a gibt, senses auch nicht gut.
to: sollte dann zwei begriffe enthalten je nachdem" -- and for the category,
"in pairs gibt es is_a: target. dahinter kann man metadaten einreihen".
"""
import copy

import pytest

from wound_ontology.mappers.judgements import current
from wound_ontology.store.concept_store import ConceptStore


class _DM:
    def __init__(self, data): self.json = data
    def load_latest_json(self, _): return self.json
    def save_as_json(self, d, _): self.json = d


BIOPSY = {
    "1": {"entities": {"Biopsy": {"is_a: process": 1.0, "has_specified_output: Tissue": 1.0}}},
    "2": {"entities": {"Biopsy": {"is_a: material entity": 1.0, "part_of: Wound bed": 1.0},
                       "Histology": {"has_specified_input: Biopsy": 1.0, "is_a: process": 1.0}}},
    "3": {"entities": {"Biopsy": {"has_participant: Patient": 1.0}}},
}


def _store(data=BIOPSY):
    return ConceptStore(_DM(copy.deepcopy(data)), "concept_store")


def _split(s):
    s.terms.split_by_category("Biopsy", {"process": "Biopsy procedure",
                                         "material entity": "Biopsy material"})


def _entities(s, **kw):
    return {(k, e): a for k, ents in s.view(**kw) for e, a in ents.items()}


# ── the category is a decided is_a ──────────────────────────────────────────

def test_a_decided_category_is_written_as_its_is_a_cell():
    s = _store()
    s.terms.set_category("Biopsy", "process", source="term ruling", note="n")
    j = current(s.terms.records["Biopsy"]["is_a"]["process"])
    assert (j["verdict"], j["by"]) == ("yes", "author") and "term ruling" in j["why"]
    assert "category" not in s.terms.records["Biopsy"]
    assert s.terms.categories()["Biopsy"]["verdict"] == "process"


def test_a_new_ruling_replaces_the_decided_cell_and_keeps_history():
    s = _store()
    s.terms.set_category("Biopsy", "process", source="head rule: biopsy")
    s.terms.set_category("Biopsy", "material entity", source="term ruling")
    isa = s.terms.records["Biopsy"]["is_a"]
    assert [(j["verdict"], j["by"]) for j in isa["process"]] == \
        [("yes", "end-word-category"), ("no", "author")], "nothing is deleted"
    assert s.terms.categories()["Biopsy"]["verdict"] == "material entity"


def test_a_decided_cell_is_not_a_rejection():
    s = _store()
    s.terms.set_category("Biopsy", "process", source="term ruling")
    ents = _entities(s)
    assert ents[("2", "Biopsy")]["is_a: process"] == 1.0      # typed by the decision
    assert ents[("1", "Biopsy")]["is_a: process"] == 1.0


def test_a_reasoner_verdict_does_not_overwrite_a_decided_category():
    s = _store()
    s.terms.set_category("Biopsy", "process", source="term ruling")
    n = s.reject_cells([("Biopsy", "is_a: process")], by="elk")
    assert n == 0
    assert [j["by"] for j in s.terms.records["Biopsy"]["is_a"]["process"]] == ["author"]


def test_setting_elks_verdicts_aside_leaves_the_authors_category():
    s = _store()
    s.terms.set_category("Biopsy", "process", source="term ruling", by="curator")
    s.reopen = ("elk", "is_a")
    assert _entities(s)[("2", "Biopsy")]["is_a: process"] == 1.0
    s.reopen = None
    assert s.terms.categories()["Biopsy"]["verdict"] == "process"


def test_an_old_category_section_is_moved_on_load():
    from conftest import memory_mapping
    gt = memory_mapping({"Infection": {"to": None, "pairs": {}, "category": {
        "verdict": "process", "source": "head rule: infection", "by": "curator",
        "note": "", "when": "2026-09-29T23:47:42",
        "history": [{"verdict": "material entity", "source": "term ruling"}]}}})
    rec = gt.records["Infection"]
    assert "category" not in rec
    assert gt.categories()["Infection"]["verdict"] == "process"
    assert "material entity" in rec["is_a"], "the earlier ruling stays on record"


# ── the split `to` ──────────────────────────────────────────────────────────

def test_a_split_term_points_at_one_name_per_category_and_each_has_a_record():
    s = _store()
    _split(s)
    rec = s.terms.records["Biopsy"]
    assert current(rec["name"])["verdict"] == {"process": "Biopsy procedure",
                                               "material entity": "Biopsy material"}
    assert "senses" not in rec
    assert "Biopsy procedure" in s.terms.records and "Biopsy material" in s.terms.records


def test_a_split_term_is_not_in_the_one_name_mapping():
    s = _store()
    _split(s)
    assert "Biopsy" not in s.terms.data
    assert s.terms.splits()["Biopsy"]["process"] == "Biopsy procedure"


def test_each_mention_takes_the_name_for_its_own_category():
    s = _store()
    _split(s)
    ents = _entities(s)
    assert "has_specified_output: Tissue" in ents[("1", "Biopsy procedure")]
    assert "part_of: Wound bed" in ents[("2", "Biopsy material")]
    # a target is the same term seen from the other side
    assert "has_specified_input: Biopsy material" in ents[("2", "Histology")]
    # typed with no category: no sense can be told, the name stays
    assert ("3", "Biopsy") in ents


def test_the_scope_of_a_sense_decides_its_mentions():
    """The sense's own verdict counts, not only the split term's: the view
    renames BEFORE it reads the verdicts."""
    s = _store()
    _split(s)
    s.terms.gate("Biopsy material", curator={"verdict": "out", "reason": "", "when": "now"})
    names = {e for _, e in _entities(s)}
    assert "Biopsy material" not in names
    assert "Biopsy procedure" in names


def test_the_scope_of_a_sense_pools_what_was_said_of_the_split_term():
    s = _store()
    _split(s)
    s.terms.gate("Biopsy", rule={"verdict": "in", "by": "WHITELIST"})
    assert s.terms.effective_gate_verdict("Biopsy procedure")[0] == "in"


def test_a_machine_mapping_does_not_overwrite_a_split():
    s = _store()
    _split(s)
    skipped = s.terms.add_batch({"Biopsy": "Sample collection process"})
    assert skipped == [("Biopsy", "Sample collection process")]
    with pytest.raises(ValueError):
        s.terms.add("Biopsy", "Sample collection process")


def test_retiring_does_not_undo_a_split():
    s = _store()
    _split(s)
    assert s.terms.retire("Biopsy", reason="test") == 0
    assert s.terms.splits()["Biopsy"]


def test_a_sense_needs_a_name_of_its_own_and_a_declared_category():
    s = _store()
    with pytest.raises(ValueError):
        s.terms.split_by_category("Biopsy", {"process": "Biopsy", "material entity": "Biopsy material"})
    with pytest.raises(ValueError):
        s.terms.split_by_category("Biopsy", {"procedure": "Biopsy procedure",
                                             "material entity": "Biopsy material"})


def test_an_old_senses_section_becomes_the_split_to_on_load():
    from conftest import memory_mapping
    gt = memory_mapping({"Biopsy": {"to": None, "pairs": {}, "senses": {
        "process": "Biopsy procedure", "material entity": "Biopsy material"}}})
    assert current(gt.records["Biopsy"]["name"])["verdict"]["material entity"] == "Biopsy material"
    assert "senses" not in gt.records["Biopsy"]


def test_a_term_with_one_name_and_senses_stops_the_load():
    from conftest import memory_mapping
    with pytest.raises(ValueError):
        memory_mapping({"Biopsy": {"to": "Sampling", "pairs": {}, "senses": {
            "process": "Biopsy procedure", "material entity": "Biopsy material"}}})


def test_the_trace_follows_a_split():
    s = _store()
    _split(s)
    t = s.trace("Biopsy material")
    assert t["Biopsy"]["documents"] == ["2"]


def test_a_cluster_name_change_reaches_a_sense_name():
    s = _store()
    _split(s)
    s.terms.decide_name("Biopsy specimen", "Biopsy material")
    assert s.terms.splits()["Biopsy"]["material entity"] == "Biopsy specimen"
