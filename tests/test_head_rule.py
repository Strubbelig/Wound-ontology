"""Rule 79: the curator's head-word rule, on the curator's own examples (2026-10-18)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from wound_ontology.hierarchies.head_rule import (LICENSED, OPEN, REFUSED, SYNONYM,  # noqa: E402
                                                  canonical_names, judge)


def v(c, p):
    return judge(c, p)[0]


def test_curator_examples():
    assert v("Wound", "Injury") == LICENSED
    assert v("Burn Wound", "Burn Injury") == LICENSED
    assert v("Burn Injury", "Injury") == LICENSED
    assert v("Burn Wound", "Wound") == LICENSED
    assert v("Wound", "Burn Injury") == REFUSED
    assert v("Blast Wound", "Blast Injury") == LICENSED
    assert v("Blast Injury", "Injury") == LICENSED


def test_a_burn_is_a_burn_wound():
    assert v("Second-Degree Burn", "Burn Wound") == LICENSED
    assert v("Deep Dermal Burn", "Hand Burn") == REFUSED
    assert v("Burn Wound", "Electrical Burn Wound") == REFUSED
    assert v("Burn Wound", "Total Body Surface Area Burn") == REFUSED


def test_site_decides_ulcer_and_tear():
    assert v("Diabetic Foot Ulcer", "Wound") == LICENSED
    assert v("Gastric Ulcer", "Wound") == REFUSED
    assert v("Skin Tear", "Wound") == LICENSED
    assert v("Tendon Tear", "Wound") == REFUSED
    assert v("Meniscal Tear", "Injury") == LICENSED
    assert v("Gastric Ulcer", "Injury") == REFUSED
    assert v("Active Diabetic Foot Ulcer", "Diabetic Ulcer") == LICENSED


def test_laceration_abrasion_avulsion():
    assert v("Laceration", "Wound") == LICENSED
    assert v("Abrasion", "Wound") == LICENSED
    assert v("Bone Avulsion", "Injury") == LICENSED
    assert v("Avulsion", "Wound") == REFUSED


def test_collective_names_refused_and_unknown_heads_open():
    assert v("Wound", "Cutaneous Disorder") == REFUSED
    assert v("Blister", "Skin Lesion") == REFUSED
    assert v("Secondary Healing Burn Depth Thing", "Burn Depth") in (OPEN, REFUSED)


def test_synonyms_are_not_edges():
    assert v("Ischemic Wound", "Ischemic Wounds") == SYNONYM
    names = canonical_names(["Diabetic Ulcer", "Diabetes-Related Ulcer", "Trauma", "Injury", "Ischemic Wounds"],
                            known=["Ischemic Wound", "Trauma"])
    assert names["Diabetes-Related Ulcer"] == names["Diabetic Ulcer"] == "Diabetic Ulcer"
    # trauma is the curator's Trauma process (2026-10-02), never injury
    assert names["Injury"] == "Injury" and names["Trauma"] == "Trauma"
    assert v("Abdominal Injury", "Trauma") == OPEN
    assert names["Ischemic Wounds"] == "Ischemic Wound"


def test_curator_rulings_2026_10_18_chat_and_page():
    cases = [
        ("Blister", "Wound", LICENSED), ("Tension Blister", "Blistering Wound", LICENSED),
        ("Bulla", "Blistering Wound", LICENSED), ("Epidermal Detachment", "Blistering Wound", LICENSED),
        ("Burn Lesion", "Burn Wound", SYNONYM), ("Burn Wound", "Thermal Wound", LICENSED),
        ("Scald", "Thermal Wound", LICENSED), ("Scald", "Burn Wound", REFUSED), ("Scald", "Injury", LICENSED),
        ("Sunburn", "Burn Injury", REFUSED), ("Sunburn", "Radiation Wound", LICENSED), ("Sunburn", "Thermal Wound", REFUSED),
        ("Thermal Damage", "Burn Injury", REFUSED), ("Thermal Damage", "Injury", REFUSED),
        ("Soft Tissue Defect", "Soft Tissue Injury", REFUSED), ("Open Fracture", "Wound", LICENSED),
        ("Open Fracture", "Fracture Wound", LICENSED), ("Fracture", "Wound", REFUSED), ("Compound Fracture", "Injury", LICENSED),
        ("Frostbite", "Burn Injury", REFUSED), ("Frostbite", "Injury", LICENSED), ("Snakebite", "Bite Wound", LICENSED),
        ("Burns Of The Ocular Surface", "Burn Injury", LICENSED), ("Burns Of The Ocular Surface", "Wound", REFUSED),
        ("Clean Wound According To CDC", "Surgical Wound", LICENSED), ("Ulcus Cruris Venosum", "Venous Ulcer", LICENSED),
        ("Ischemic Ulcer", "Wound", LICENSED), ("2nd Degree Perineal Tear", "Injury", LICENSED),
        ("Perineal Tear", "Wound", LICENSED), ("Complete Tear", "Injury", LICENSED), ("Complete Tear", "Wound", REFUSED),
        ("Electrical Burn", "Thermal Wound", REFUSED),
    ]
    wrong = [(c, p, e, judge(c, p)) for c, p, e in cases if judge(c, p)[0] != e]
    assert not wrong, wrong


def test_a_curator_verdict_on_an_edge_outranks_the_rule():
    from wound_ontology.hierarchies.head_rule import sort_proposals
    out = sort_proposals([("Abdominal Injury", "Injury")], curator={("Abdominal Injury", "Injury"): "no"})
    assert [r["child"] for r in out[REFUSED]] == ["Abdominal Injury"]


def test_page_rulings_2026_10_18_second_round():
    assert v("Contusion", "Injury") == LICENSED
    assert v("Contusion", "Wound") == REFUSED
    assert v("Second-Degree Burn Wound", "Secondary Healing Burn Depth") == REFUSED
    assert v("Third-Degree Burn Wound", "Burn Wound By Degree") == REFUSED
    assert v("Wound", "Medical Condition") == REFUSED
    assert v("Wound With Microbial Burden Assessed According To CDC", "Injury") == LICENSED
    assert v("Malignant Fungating Lesion", "Malignant Wound") == LICENSED
    assert v("Ulcus Hypertonicus Martorell", "Wound") == LICENSED
    assert v("Closed Surgical Incision", "Injury") == OPEN       # page: not ruled ("nicht einordnen")
