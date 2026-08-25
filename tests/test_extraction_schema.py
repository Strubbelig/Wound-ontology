"""The extraction schema is generated from MILD/WONT and must not contradict them.

The schema this replaced was hand-written and had drifted to
`Disease: is_a: Disposition` — the OGMS pattern MILD explicitly rejects — while
grounding diseases to MONDO, a nosology. These tests pin the properties that
made that drift possible.
"""
import pytest
from pydantic import ValidationError

from wound_ontology.llm.extraction_models import (
    BFOCategory,
    DEFINITIONS,
    GROUNDING,
    RELATION_DOMAINS,
    RELATION_IRI,
    ExtractedEntity,
    ExtractionResult,
    RelationType,
    relations_for,
)
from wound_ontology.llm import extraction_prompt as ep

WONT = "https://bioportal.bioontology.org/ontologies/WONT/"


def _cat_of(label):
    for cat, table in GROUNDING.items():
        if label in table:
            return cat
    return None


# ── C1: the drift that motivated generating this file ──────────────────────
def test_disease_is_material_not_disposition():
    assert _cat_of("material disease entity") == "MaterialEntity"
    assert _cat_of("pathological disorder") == "MaterialEntity"
    assert _cat_of("Wound") == "MaterialEntity"


def test_predisposition_is_a_tendency():
    """Risk factors belong in the tendency layer, not under disease."""
    assert _cat_of("disease predisposition") == "Tendency"


def test_no_mondo_grounding():
    """MONDO is a nosology; grounding material disorders to it reimports the
    category conflation MILD removes."""
    for table in GROUNDING.values():
        assert not any("MONDO" in iri for iri in table.values())


# ── C3: `affects` had no IRI, so every such edge was unmappable ────────────
def test_affects_is_not_expressible():
    assert all(r.value != "affects" for r in RelationType)


def test_every_relation_has_an_iri():
    assert RELATION_IRI
    for r in RelationType:
        assert RELATION_IRI[r.value].startswith("http")


# ── closed where closure is correct ────────────────────────────────────────
def test_category_is_closed():
    with pytest.raises(ValidationError):
        ExtractedEntity(label="X", category="Thingamajig")


def test_grounding_must_match_declared_category():
    with pytest.raises(ValidationError):
        ExtractedEntity(label="Wound", category="Process",
                        grounded_to=WONT + "WONT_0000380")


def test_exact_label_autogrounds():
    e = ExtractedEntity(label="Wound", category="MaterialEntity")
    assert e.grounded_to == WONT + "WONT_0000380"


# ── open where discovery is needed ─────────────────────────────────────────
def test_new_terms_are_allowed_and_stay_ungrounded():
    e = ExtractedEntity(label="Nanocellulose Interface Dressing",
                        category="MaterialEntity")
    assert e.grounded_to is None


# ── C2 stage 2: relations decided by category pair, not by judgement ───────
def test_illicit_relation_is_rejected():
    res = ExtractionResult(
        entities=[{"label": "Wound", "category": "MaterialEntity"},
                  {"label": "reddened", "category": "Quality"}],
        relations=[{"subject": "reddened", "predicate": "has part",
                    "object": "Wound"}],
    )
    assert res.relations == []
    assert res.rejected_relations


def test_licit_relation_survives():
    res = ExtractionResult(
        entities=[{"label": "Wound", "category": "MaterialEntity"},
                  {"label": "Wound development process", "category": "Process"}],
        relations=[{"subject": "Wound development process",
                    "predicate": "has participant", "object": "Wound"}],
    )
    assert len(res.relations) == 1
    assert not res.rejected_relations


def test_relation_with_unknown_endpoint_is_rejected():
    res = ExtractionResult(
        entities=[{"label": "Wound", "category": "MaterialEntity"}],
        relations=[{"subject": "Wound", "predicate": "has part",
                    "object": "Something Never Extracted"}],
    )
    assert res.relations == []


def test_a_quality_has_no_material_parts():
    """A quality is not made of material, so no part/whole relation may connect
    the two — but it certainly inheres in a material bearer, so the pair is not
    empty. It became non-empty on 2026-08-20 when 'Wound pain' was retyped from a
    disposition of the wound to a quality of the patient (∃inheres_in.Homo
    sapiens, ∃causally_influenced_by.Wound). The schema is generated from the
    TTLs, so it learned that by itself."""
    licensed = relations_for("Quality", "MaterialEntity")
    assert "has part" not in licensed
    assert "part of" not in licensed
    assert "inheres in" in licensed


def test_a_quality_bears_no_relation_to_a_process():
    """Genuinely empty pair: nothing in MILD/WONT connects a quality to an
    occurrent, so the schema must offer the model nothing at all."""
    assert relations_for("Quality", "Process") == []


# ── prompt rendering ───────────────────────────────────────────────────────
def test_definitions_reach_the_prompt():
    assert DEFINITIONS.get("Wound")
    block = ep.grounding_block("MaterialEntity")
    assert "Wound" in block and "specified output" in block


def test_relation_block_states_when_nothing_is_licensed():
    assert "NO relation" in ep.relation_block("Quality", "Process")


def test_relation_block_collapses_to_one_option():
    assert "exactly one relation" in ep.relation_block("MaterialEntity", "Quality")


def test_typing_prompt_asks_for_no_relations():
    p = ep.typing_prompt("some clinical text")
    assert "Do NOT assert any relations" in p
    for cat in BFOCategory:
        assert cat.value in p


# ── every discovery lands under a BFO class ────────────────────────────────
from wound_ontology.llm.extraction_models import (  # noqa: E402
    COARSE_CATEGORIES,
    CATEGORY_IRI,
    CATEGORY_PARENT,
    category_ancestors,
    category_descendants,
    is_refinement_of,
    relations_are_certain,
)


def test_category_is_mandatory_so_nothing_is_unsubsumed():
    with pytest.raises(ValidationError):
        ExtractedEntity(label="Orphan Term")


@pytest.mark.parametrize("cat", [c.value for c in BFOCategory])
def test_every_category_has_a_bfo_iri(cat):
    assert CATEGORY_IRI[cat].startswith("http")


def test_new_term_yields_a_subsumption_axiom():
    e = ExtractedEntity(label="Nanocellulose Interface Dressing",
                        category="MaterialEntity")
    subj, pred, obj = e.subsumption_axiom()
    assert subj == "Nanocellulose Interface Dressing"
    assert pred.endswith("subClassOf")
    assert obj == "http://purl.obolibrary.org/obo/BFO_0000040"


def test_coarse_fallbacks_exist_for_both_branches():
    """A model unsure of the precise kind must still be able to answer."""
    assert "Continuant" in COARSE_CATEGORIES
    assert "Occurrent" in COARSE_CATEGORIES


def test_coarse_typing_is_accepted_and_flagged():
    e = ExtractedEntity(label="Some Ambiguous Term", category="Continuant")
    assert e.needs_refinement is True
    assert e.bfo_iri == "http://purl.obolibrary.org/obo/BFO_0000002"


def test_precise_typing_is_not_flagged():
    assert ExtractedEntity(label="Wound", category="MaterialEntity").needs_refinement is False


# ── the tree must be a real BFO tree ───────────────────────────────────────
def test_category_tree_is_rooted_and_acyclic():
    roots = [c for c, p in CATEGORY_PARENT.items() if p is None]
    assert sorted(roots) == ["Continuant", "Occurrent"]
    for c in CATEGORY_PARENT:
        assert category_ancestors(c)[-1] in ("Continuant", "Occurrent")


def test_refinement_is_consistent_downward_only():
    assert is_refinement_of("Process", "Occurrent")
    assert is_refinement_of("MaterialEntity", "Continuant")
    assert is_refinement_of("Function", "Disposition")
    # cross-branch refinement is a contradiction, not a refinement
    assert not is_refinement_of("Process", "Continuant")
    assert not is_refinement_of("MaterialEntity", "Occurrent")


def test_tendency_is_a_sibling_of_disposition_not_a_subtype():
    """MILD places tendency under realizable entity deliberately."""
    assert CATEGORY_PARENT["Tendency"] == "RealizableEntity"
    assert not is_refinement_of("Tendency", "Disposition")


def test_function_is_a_disposition_bfo_compatible():
    assert is_refinement_of("Function", "Disposition")


# ── coarse categories widen the licensing answer ───────────────────────────
def test_coarse_subject_widens_relations():
    precise = set(relations_for("MaterialEntity", "Process"))
    coarse = set(relations_for("Continuant", "Process"))
    assert precise <= coarse


def test_certainty_flag_tracks_coarseness():
    assert relations_are_certain("MaterialEntity", "Process")
    assert not relations_are_certain("Continuant", "Process")


def test_descendants_include_self_and_children():
    d = category_descendants("Occurrent")
    assert {"Occurrent", "Process", "ProcessBoundary"} <= d
    assert "MaterialEntity" not in d


def test_prompt_marks_fallbacks_and_forbids_skipping():
    block = ep.category_block()
    assert "[FALLBACK]" in block
    assert "no 'unknown' and no skipping" in block
    assert "move UP the tree" in block
