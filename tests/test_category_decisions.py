"""A person's decision about a term's BFO category is a term decision (rule 57).

The abstracts typed `infection` a process in some places and a material entity
in others -- irreconcilably, so the term had no category and could not be
placed. The curator decided it (by the head word, "whenever there is infection,
that is a process", or term by term). The decision lives in the term dict; the
view types every mention of the term with it, and the concept store still keeps
what each abstract said.
"""
import copy

import pytest

from wound_ontology.store.concept_store import ConceptStore


class _DM:
    def __init__(self, data): self.json = data
    def load_latest_json(self, _): return self.json
    def save_as_json(self, d, _): self.json = d


INFECTION = {
    "1": {"entities": {"Infection": {"is_a: material entity": 1.0,
                                     "located_in: Wound": 1.0}}},
    "2": {"entities": {"Infection": {"is_a: process": 0.8}}},
    "3": {"entities": {"Infection": {"is_a: disposition": 0.9}}},
    "4": {"entities": {"Infection": {"located_in: Foot": 1.0}}},
}


def _store(data=INFECTION):
    return ConceptStore(_DM(copy.deepcopy(data)), "concept_store")


def _typings(s, term, **kw):
    out = []
    for key, ents in s.view(**kw):
        for e, attrs in ents.items():
            if e == term:
                out.append((key, sorted(t for t in attrs if t.startswith("is_a:"))))
    return sorted(out)


def test_undecided_term_keeps_every_typing():
    s = _store()
    assert _typings(s, "Infection") == [("1", ["is_a: material entity"]),
                                        ("2", ["is_a: process"]),
                                        ("3", ["is_a: disposition"]),
                                        ("4", [])]


def test_decision_types_every_typed_mention():
    s = _store()
    assert s.terms.set_category("Infection", "process", source="head rule: infection") == "set"
    assert _typings(s, "Infection") == [("1", ["is_a: process"]), ("2", ["is_a: process"]),
                                        ("3", ["is_a: process"]), ("4", [])]


def test_decision_keeps_the_strongest_value_and_other_relations():
    s = _store()
    s.terms.set_category("Infection", "process", source="term ruling")
    ents = {k: e["Infection"] for k, e in s.view()}
    assert ents["1"] == {"is_a: process": 1.0, "located_in: Wound": 1.0}
    assert ents["3"] == {"is_a: process": 0.9}


def test_a_mention_without_a_category_is_not_given_one():
    s = _store()
    s.terms.set_category("Infection", "process", source="term ruling")
    assert dict(s.view())["4"]["Infection"] == {"located_in: Foot": 1.0}


def test_a_sharper_typing_on_the_decided_branch_stands():
    data = {"1": {"entities": {"Activity": {"is_a: function": 1.0}}},
            "2": {"entities": {"Activity": {"is_a: process": 1.0}}},
            "3": {"entities": {"Activity": {"is_a: continuant": 1.0}}}}
    s = _store(data)
    s.terms.set_category("Activity", "disposition", source="term ruling")
    assert _typings(s, "Activity") == [("1", ["is_a: function"]),
                                       ("2", ["is_a: disposition"]),
                                       ("3", ["is_a: disposition"])]


def test_a_non_category_parent_is_untouched():
    data = {"1": {"entities": {"Burn": {"is_a: material entity": 1.0, "is_a: Wound": 1.0}}},
            "2": {"entities": {"Burn": {"is_a: process": 1.0}}}}
    s = _store(data)
    s.terms.set_category("Burn", "material entity", source="term ruling")
    assert _typings(s, "Burn") == [("1", ["is_a: Wound", "is_a: material entity"]),
                                   ("2", ["is_a: material entity"])]


def test_the_evidence_is_not_rewritten():
    s = _store()
    s.terms.set_category("Infection", "process", source="term ruling")
    assert s.dict["1"]["entities"]["Infection"] == {"is_a: material entity": 1.0,
                                                   "located_in: Wound": 1.0}


def test_a_term_ruling_outranks_a_head_rule():
    s = _store()
    assert s.terms.set_category("Infection", "material entity", source="term ruling") == "set"
    assert s.terms.set_category("Infection", "process", source="head rule: infection") == "kept"
    assert s.terms.categories()["Infection"]["verdict"] == "material entity"


def test_a_later_term_ruling_replaces_a_head_rule_and_keeps_history():
    s = _store()
    s.terms.set_category("Infection", "process", source="head rule: infection")
    assert s.terms.set_category("Infection", "disposition", source="term ruling") == "set"
    c = s.terms.categories()["Infection"]
    assert c["verdict"] == "disposition"
    assert c["history"][0]["verdict"] == "process"


def test_an_unknown_category_raises():
    s = _store()
    with pytest.raises(ValueError):
        s.terms.set_category("Infection", "time interval", source="term ruling")


def test_temporal_region_is_a_category():
    s = _store({"1": {"entities": {"Operative Time": {"is_a: quality": 1.0}}},
                "2": {"entities": {"Operative Time": {"is_a: process": 1.0}}}})
    s.terms.set_category("Operative Time", "temporal region", source="term ruling")
    assert _typings(s, "Operative Time") == [("1", ["is_a: temporal region"]),
                                             ("2", ["is_a: temporal region"])]


def test_a_synonym_names_what_its_canonical_names_when_the_view_stops_at_spelling():
    data = {"1": {"entities": {"Postoperative Wound Infection": {"is_a: material entity": 1.0}}},
            "2": {"entities": {"Surgical Site Infection": {"is_a: disposition": 1.0}}}}
    s = _store(data)
    s.terms.add("Postoperative Wound Infection", "Surgical Site Infection")
    s.terms.set_category("Surgical Site Infection", "process", source="term ruling")
    s._live_mapping = True          # after `terms` exists: a store without a file has none
    assert _typings(s, "Postoperative Wound Infection", mapped=False) == [("1", ["is_a: process"])]
    assert _typings(s, "Surgical Site Infection") == [("1", ["is_a: process"]),
                                                      ("2", ["is_a: process"])]


def test_the_decision_travels_through_a_rename():
    s = _store()
    s.terms.set_category("Infection", "process", source="term ruling")
    rep = s.terms.apply_renames({"Infection": "Infectious Process"}, by="test")
    assert rep["category conflicts"] == []
    assert s.terms.categories()["Infectious Process"]["verdict"] == "process"


def test_two_spellings_decided_differently_are_reported():
    s = _store()
    s.terms.set_category("Infection", "process", source="head rule: infection")
    s.terms.set_category("infection", "material entity", source="term ruling")
    rep = s.terms.apply_renames({"infection": "Infection"}, by="test")
    assert rep["category conflicts"]
    assert s.terms.categories()["Infection"]["verdict"] == "material entity"
