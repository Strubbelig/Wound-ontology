"""Rule 89: one form for every judgement; the author's last word counts."""
import pytest

from wound_ontology.mappers.judgements import current, make
from wound_ontology.mappers.rule89_migration import migrate


def J(v, by, when, why="x"):
    return make(v, by, why, when)


def test_the_authors_last_judgement_counts_even_before_a_later_machine():
    js = [J("in", "deepseek-v4-flash", "2026-09-28"), J("out", "author", "2026-10-01"),
          J("in", "deepseek-v4-flash", "2026-10-20")]
    assert current(js)["verdict"] == "out"


def test_a_later_author_judgement_beats_an_earlier_one():
    js = [J("out", "author", "2026-10-01"), J("in", "author", "2026-10-02")]
    assert current(js)["verdict"] == "in"


def test_a_rule_is_a_machine():
    # curator, 2026-10-28: "eine regel ist eine regel und nicht vom autor"
    js = [J("out", "author", "2026-10-01"), J("in", "abbreviation-full-form", "2026-10-02")]
    assert current(js)["verdict"] == "out"


def test_without_the_author_the_last_judgement_counts():
    js = [J("same_class", "deepseek-v4-flash", "2026-09-22"), J("different", "deepseek-v4-flash", "2026-09-23")]
    assert current(js)["verdict"] == "different"


def test_a_judgement_names_a_known_agent_and_an_iso_time():
    with pytest.raises(ValueError):
        make("in", "pass2", "x", "2026-09-28")
    with pytest.raises(ValueError):
        make("in", "deepseek-v4-flash", "x", "2026-09-28 llm scope pass")


class _Dating:
    def when(self, kind, *key, default_after=None):
        return "2026-09-22", "test"


def test_the_old_record_translates_without_losing_a_verdict():
    old = {
        "acute burn wound": {"spelling": {"to": "Acute burn wound", "by": "pass0", "when": "2026-10-24T20:30:24"}},
        "Acute burn wound": {
            "to": None, "method": "curator", "confidence": 1.0,
            "pairs": {
                "Burn injury": {"pass1": {"verdict": "narrower", "reason": "a"},
                                "pass2": {"verdict": "narrower", "reason": "b"},
                                "curator": {"verdict": "narrower", "reason": "rule 79", "when": "2026-10-18T21:36:03"}},
                "Thermal wound": {"curator": {"verdict": "narrower", "iri": "WONT_0000310",
                                              "check": "verify: yes; Claude: agrees",
                                              "by": "placement review (curator page, 2026-10-02)",
                                              "when": "2026-10-02T15:26:18", "reason": "placed"}}},
            "gate": {"pass2": {"verdict": "in", "reason": "A wound type.", "when": "2026-09-28 llm scope pass"}},
            "relations": {"has_disposition: Wound risk": {
                "status": "repredicated", "to": "has_tendency", "when": "2026-10-03T15:06:47",
                "by": "rule 68: has_disposition with a tendency value (curator 2026-10-03)", "note": "n"}},
        },
    }
    new, rep, _ = migrate(old, _Dating())
    sp = new["acute burn wound"]["name"]
    assert sp[-1]["by"] == "string-normalisation" and sp[-1]["why"] == "capitalisation"
    rec = new["Acute burn wound"]
    burn = rec["pairs"]["Burn injury"]
    assert [j["by"] for j in burn] == ["deepseek-v4-flash_bulk20", "deepseek-v4-flash_bfo_type", "author"]
    assert burn[0]["by"] == "deepseek-v4-flash_bulk20" and burn[1]["by"] == "deepseek-v4-flash_bfo_type"
    assert "Thermal wound" not in rec["pairs"]                       # a placement is an is_a
    thermal = rec["is_a"]["Thermal wound"]
    assert [j["by"] for j in thermal] == ["deepseek-v4-flash_top_15", "deepseek-v4-flash_single", "claude-opus-5-5", "author"]
    assert current(thermal)["verdict"] == "yes" and current(thermal)["iri"] == "WONT_0000310"
    assert rec["scope"] == [{"verdict": "in", "by": "deepseek-v4-flash",
                             "why": "A wound type.; llm scope pass", "when": "2026-09-28"}]
    rel = rec["relations"]
    assert current(rel["has_disposition: Wound risk"])["verdict"] == "no"
    assert current(rel["has_tendency: Wound risk"])["verdict"] == "yes"
    assert current(rel["has_tendency: Wound risk"])["by"] == "tendency-not-disposition"
