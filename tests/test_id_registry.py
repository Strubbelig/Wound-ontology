"""Rule 71: a minted WONT id belongs to its class for good (2026-10-04).

The export used to number minted classes afresh on every run; after a rename
upstream WONT_0004067 was `Ligamentous Rupture` instead of `Length`.
"""
import json

import pytest

from wound_ontology.owl.id_registry import IdRegistry

NS = "https://bioportal.bioontology.org/ontologies/WONT/"


def _reg(tmp_path):
    return IdRegistry(tmp_path / "ids.json", namespace=NS)


def test_a_class_keeps_its_id_across_builds(tmp_path):
    r = _reg(tmp_path)
    a = r.mint("Chronic Wound Infection", set(), floor=475)
    r.save()
    r2 = _reg(tmp_path)
    assert r2.lookup("chronic wound infections") == a        # spelling folds away
    assert a.endswith("WONT_0000475")                        # WONT's own series continues
    assert r2.mint("Something New", set(), floor=475).endswith("WONT_0000476")


def test_a_renamed_class_keeps_its_id_through_its_former_name(tmp_path):
    r = _reg(tmp_path)
    a = r.mint("Wound Dressing Change", set())
    assert r.lookup("Dressing Change Process", former=["Wound Dressing Change"]) == a
    e = r.entries[a]
    assert e["label"] == "Dressing Change Process" and "Wound Dressing Change" in e["former_labels"]


def test_two_classes_merged_by_a_rename_keep_one_id_and_the_other_is_obsolete(tmp_path):
    r = _reg(tmp_path)
    old = r.mint("Hard-To-Heal Ulceration", set())
    keep = r.mint("Hard-To-Heal Wound X", set())
    # the current name is registered under `keep`; the former spelling under `old`
    assert r.lookup("Hard-To-Heal Wound X", former=["Hard-To-Heal Ulceration"]) == keep
    assert r.entries[old]["status"] == "obsolete" and r.entries[old]["replaced_by"] == keep
    assert r.lookup("Hard-To-Heal Ulceration") == keep          # the old id answers with its successor


def test_an_id_is_never_issued_twice(tmp_path):
    r = _reg(tmp_path)
    a = r.mint("Alpha", set())
    b = r.mint("Beta", set())
    r.lookup("Beta", former=["Alpha"])                           # Alpha becomes obsolete
    c = r.mint("Gamma", set())
    assert len({a, b, c}) == 3


def test_the_registry_is_backed_up_and_read_back(tmp_path):
    r = _reg(tmp_path)
    r.mint("Alpha", set()); r.save()
    r.mint("Beta", set()); r.save(backup_dir=tmp_path / "bak")
    assert list((tmp_path / "bak").glob("wont_ids_*.json"))
    assert len(json.loads((tmp_path / "ids.json").read_text())["entries"]) == 2


def test_the_export_reuses_registered_ids(tmp_path):
    from test_extend_ground_truth import GROUND_TRUTH, _hier
    from wound_ontology.owl.extend import extend_ground_truth
    gt = tmp_path / "gt.ttl"; gt.write_text(GROUND_TRUTH, encoding="utf-8")
    hier = _hier([("New Term A", "Wound"), ("New Term B", "Wound")])
    first = extend_ground_truth(gt, tmp_path / "o1.ttl", class_hier=hier, lexicon=(),
                                registry=_reg(tmp_path))
    reg = _reg(tmp_path); reg.save()
    r1 = _reg(tmp_path)
    first = extend_ground_truth(gt, tmp_path / "o1.ttl", class_hier=hier, lexicon=(), registry=r1)
    r1.save()
    # a new class arriving FIRST in the next build must not take an old number
    hier2 = _hier([("Brand New", "Wound"), ("New Term A", "Wound"), ("New Term B", "Wound")])
    second = extend_ground_truth(gt, tmp_path / "o2.ttl", class_hier=hier2, lexicon=(),
                                 registry=_reg(tmp_path))
    assert second.minted["New Term A"] == first.minted["New Term A"]
    assert second.minted["New Term B"] == first.minted["New Term B"]
    assert second.minted["Brand New"] not in first.minted.values()


def test_a_case_variant_does_not_flip_the_label(tmp_path):
    r = _reg(tmp_path)
    a = r.mint("Burn Injury", set())
    r.lookup("burn injury")
    assert r.entries[a]["label"] == "Burn Injury" and not r.entries[a].get("former_labels")
    assert r.changes["renamed"] == 0


def test_a_registered_id_that_turns_up_in_wont_stops_the_export(tmp_path):
    """The curator resets Protégé's counter by hand; if it is forgotten, two
    classes would share an IRI. The export refuses instead."""
    from test_extend_ground_truth import GROUND_TRUTH, _hier
    from wound_ontology.owl.extend import extend_ground_truth
    gt = tmp_path / "gt.ttl"; gt.write_text(GROUND_TRUTH, encoding="utf-8")
    r = _reg(tmp_path)
    r.issue("New Term A", NS + "WONT_0000380")        # Wound's id in the test ground truth
    with pytest.raises(RuntimeError, match="curated class"):
        extend_ground_truth(gt, tmp_path / "o.ttl", class_hier=_hier([("New Term A", "Wound")]),
                            lexicon=(), registry=r)
