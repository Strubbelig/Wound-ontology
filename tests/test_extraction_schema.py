"""The extraction schema is generated from MILD/WONT and must not contradict them.

The schema this replaced was hand-written and had drifted to
`Disease: is_a: disposition` — the OGMS pattern MILD explicitly rejects — while
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
    assert _cat_of("material disease entity") == "material entity"
    # one class since 2026-10-30 (rule 92): pathological disorder is its exact
    # synonym, the obsolete MILD_120022 no grounding target
    assert _cat_of("pathological disorder") is None
    assert _cat_of("Wound") == "material entity"


def test_predisposition_is_a_tendency():
    """Risk factors belong in the tendency layer, not under disease."""
    assert _cat_of("disease predisposition") == "tendency"


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
        ExtractedEntity(label="Wound", category="process",
                        grounded_to=WONT + "WONT_0000380")


def test_exact_label_autogrounds():
    e = ExtractedEntity(label="Wound", category="material entity")
    assert e.grounded_to == WONT + "WONT_0000380"


# ── open where discovery is needed ─────────────────────────────────────────
def test_new_terms_are_allowed_and_stay_ungrounded():
    e = ExtractedEntity(label="Nanocellulose Interface Dressing",
                        category="material entity")
    assert e.grounded_to is None


# ── C2 stage 2: relations decided by category pair, not by judgement ───────
def test_illicit_relation_is_rejected():
    res = ExtractionResult(
        entities=[{"label": "Wound", "category": "material entity"},
                  {"label": "reddened", "category": "quality"}],
        relations=[{"subject": "reddened", "predicate": "has part",
                    "object": "Wound"}],
    )
    assert res.relations == []
    assert res.rejected_relations


def test_licit_relation_survives():
    res = ExtractionResult(
        entities=[{"label": "Wound", "category": "material entity"},
                  {"label": "Wound development process", "category": "process"}],
        relations=[{"subject": "Wound development process",
                    "predicate": "has participant", "object": "Wound"}],
    )
    assert len(res.relations) == 1
    assert not res.rejected_relations


def test_relation_with_unknown_endpoint_is_rejected():
    res = ExtractionResult(
        entities=[{"label": "Wound", "category": "material entity"}],
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
    licensed = relations_for("quality", "material entity")
    assert "has part" not in licensed
    assert "part of" not in licensed
    assert "inheres in" in licensed


def test_a_quality_bears_no_relation_to_a_process():
    """Genuinely empty pair: nothing in MILD/WONT connects a quality to an
    occurrent, so the schema must offer the model nothing at all."""
    assert relations_for("quality", "process") == []


# ── prompt rendering ───────────────────────────────────────────────────────
def test_definitions_reach_the_prompt():
    assert DEFINITIONS.get("Wound")
    block = ep.grounding_block("material entity")
    assert "Wound" in block and "specified output" in block


def test_relation_block_states_when_nothing_is_licensed():
    assert "NO relation" in ep.relation_block("quality", "process")


def test_relation_block_collapses_to_one_option():
    assert "exactly one relation" in ep.relation_block("material entity", "quality")


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
                        category="material entity")
    subj, pred, obj = e.subsumption_axiom()
    assert subj == "Nanocellulose Interface Dressing"
    assert pred.endswith("subClassOf")
    assert obj == "http://purl.obolibrary.org/obo/BFO_0000040"


def test_coarse_fallbacks_exist_for_both_branches():
    """A model unsure of the precise kind must still be able to answer."""
    assert "continuant" in COARSE_CATEGORIES
    assert "occurrent" in COARSE_CATEGORIES


def test_coarse_typing_is_accepted_and_flagged():
    e = ExtractedEntity(label="Some Ambiguous Term", category="continuant")
    assert e.needs_refinement is True
    assert e.bfo_iri == "http://purl.obolibrary.org/obo/BFO_0000002"


def test_precise_typing_is_not_flagged():
    assert ExtractedEntity(label="Wound", category="material entity").needs_refinement is False


# ── the tree must be a real BFO tree ───────────────────────────────────────
def test_category_tree_is_rooted_and_acyclic():
    roots = [c for c, p in CATEGORY_PARENT.items() if p is None]
    assert sorted(roots) == ["continuant", "occurrent"]
    for c in CATEGORY_PARENT:
        assert category_ancestors(c)[-1] in ("continuant", "occurrent")


def test_refinement_is_consistent_downward_only():
    assert is_refinement_of("process", "occurrent")
    assert is_refinement_of("material entity", "continuant")
    assert is_refinement_of("function", "disposition")
    # cross-branch refinement is a contradiction, not a refinement
    assert not is_refinement_of("process", "continuant")
    assert not is_refinement_of("material entity", "occurrent")


def test_tendency_is_a_sibling_of_disposition_not_a_subtype():
    """MILD places tendency under realizable entity deliberately."""
    assert CATEGORY_PARENT["tendency"] == "realizable entity"
    assert not is_refinement_of("tendency", "disposition")


def test_function_is_a_disposition_bfo_compatible():
    assert is_refinement_of("function", "disposition")


# ── coarse categories widen the licensing answer ───────────────────────────
def test_coarse_subject_widens_relations():
    precise = set(relations_for("material entity", "process"))
    coarse = set(relations_for("continuant", "process"))
    assert precise <= coarse


def test_certainty_flag_tracks_coarseness():
    assert relations_are_certain("material entity", "process")
    assert not relations_are_certain("continuant", "process")


def test_descendants_include_self_and_children():
    d = category_descendants("occurrent")
    assert {"occurrent", "process", "process boundary"} <= d
    assert "material entity" not in d


def test_prompt_marks_fallbacks_and_forbids_skipping():
    block = ep.category_block()
    assert "[FALLBACK]" in block
    assert "no 'unknown' and no skipping" in block
    assert "move UP the tree" in block


# ── a determinate quality belongs to the class it defines (rule 31) ─────────
#
# The prompt taught one example, "Chronic Wound has_quality Chronic", and no
# rule about *where* a determinate attaches. Measured on the live store, the
# extractor then produced `has_quality: chronic` on 2 of 4150 entity-attribute
# pairs, and in the Wound-subtree FCA context that became a column true of one
# object and undecided for the other 39 — every undecided cell in a 40x16
# matrix. The example was right; the missing rule was the defect.

def _has_quality():
    from config.settings import PREDICATE_DEFINITIONS
    return PREDICATE_DEFINITIONS["has_quality"]


def test_has_quality_names_both_halves_of_the_distinction():
    hq = _has_quality()
    text = " ".join([hq["summary"], *hq["yes"], *hq["no"]]).lower()
    assert "determinable" in text, "the prompt never explains what a determinable is"
    assert "determinate" in text, "the prompt never explains what a determinate is"


def test_has_quality_forbids_a_determinate_on_the_parent():
    hq = _has_quality()
    assert any("determinate on the parent" in n.lower() for n in hq["no"]), (
        "'Wound has_quality Chronic' is the error this rule exists to stop; "
        "the prompt must name it"
    )


def test_has_quality_forbids_a_determinable_on_the_class_it_defines():
    hq = _has_quality()
    assert any("determinable on the class" in n.lower() for n in hq["no"]), (
        "the reverse error — 'Chronic Wound has_quality Wound Healing Time' — "
        "adds a column true of every wound, and must be named too"
    )


def test_has_quality_carries_the_decision_procedure_not_just_the_vocabulary():
    hq = _has_quality()
    assert any(n.strip().lower().startswith("test:") for n in hq["no"]), (
        "naming the two categories does not tell the model how to choose; the "
        "'if X were not <quality>, would it still be a Y?' test does"
    )


def test_has_quality_keeps_the_worked_determinate_example():
    hq = _has_quality()
    assert any("Chronic Wound has_quality Chronic" in y for y in hq["yes"]), (
        "the example is correct and is kept deliberately: WONT models this "
        "shape ten times, e.g. Reddened wound edge = Wound edge and "
        "has_quality some reddened (WONT_0000256)"
    )


def test_has_quality_keeps_a_worked_determinable_example():
    hq = _has_quality()
    assert any("determinable" in y.lower() for y in hq["yes"]), (
        "without a positive determinable example the rule reads as 'never put "
        "a quality on a parent', which is wrong"
    )


# ── 2026-10-30: no allowed relation drops out unseen ──────────────────────────

@pytest.fixture(scope="module")
def onto():
    from wound_ontology.llm.schema_builder import Onto, load_graph
    return Onto(load_graph())


def test_every_allowed_relation_is_offered():
    """Three relations dropped out of the schema in one evening when the axiom
    that used them went; the curator: "jetzt importier gesamt RO und fertig"."""
    from config.settings import ALLOWED_PREDICATES, LEGACY_PREDICATES
    offered = {r.value.replace(" ", "_") for r in RelationType}
    assert set(ALLOWED_PREDICATES) - {"is_a"} - set(LEGACY_PREDICATES) <= offered


def test_a_relation_no_axiom_uses_comes_from_ro_and_bfo_under_the_pipelines_name(onto, monkeypatch):
    """Without its required pattern, has realization (BFO_0000054, which RO
    calls "realized in") is offered by its domain and range."""
    from wound_ontology.llm import schema_builder as sb
    monkeypatch.setattr(sb, "REQUIRED_PATTERNS",
                        [r for r in sb.REQUIRED_PATTERNS if not r[1].endswith("BFO_0000054")])
    _, _, _, patterns, labels = sb.collect(onto)
    p = "http://purl.obolibrary.org/obo/BFO_0000054"
    assert labels[p] == "has realization"
    assert ("realizable entity", p, "process") in patterns


def test_an_allowed_relation_nothing_can_offer_stops_the_build(onto, monkeypatch):
    from wound_ontology.llm import schema_builder as sb
    monkeypatch.setattr(sb, "ALLOWED_PREDICATES", list(sb.ALLOWED_PREDICATES) + ["has_no_such_relation"])
    with pytest.raises(RuntimeError, match="has_no_such_relation"):
        sb.collect(onto)
