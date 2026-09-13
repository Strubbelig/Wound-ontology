"""A superclass name must be the same kind of thing as the members it groups.

The naming step returned a free-text label with no type discipline, so a concept
whose extent was entirely material wounds could be named "Traumatic Wound Healing
Disorder" and every member proposed underneath it. Nothing downstream catches
that: the label is newly minted, so it carries no axioms for the reasoner gate to
clash with, and the provenance ranks only say FCA is weak evidence — not that it
is categorically wrong.

The extraction schema already types every entity, and those types reach the
context as `is_a: <Category>` attributes, so the check is deterministic.
"""
import asyncio
import tempfile

import pandas as pd
import pytest

from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.fca.concept_lattice import ConceptLattice
from wound_ontology.fca.context_matrix import ContextMatrix


@pytest.fixture
def lattice():
    d = tempfile.mkdtemp()
    dm = DataManager(d)
    m = ContextMatrix(dm, "context_matrix")
    m._df = pd.DataFrame(
        {"is_a: materialentity": [1.0, 1.0, 1.0],
         "is_a: wound": [1.0, 1.0, 1.0],
         "has_quality: chronic": [1.0, 0.0, 0.0]},
        index=["Chronic Wound", "Bite Wound", "Scratch Wound"],
    )
    return ConceptLattice(dm, m, "concept_lattice_test")


class _Concept:
    def __init__(self, extent, intent=("is_a: wound",), uppers=()):
        self.extent = extent
        self.intent = intent
        self.upper_neighbors = uppers


class _LLM:
    """Answers with a fixed name, or one per call in order."""
    def __init__(self, *answers):
        self._answers = list(answers)
        self.seen = []

    async def generate_semantic_name(self, intent, existing, cats=(), **kw):
        self.seen.append({"existing": set(existing), **kw})
        return self._answers[min(len(self.seen) - 1, len(self._answers) - 1)]


# ── reading the extent's types ──────────────────────────────────────────────

def test_extent_categories_come_from_the_context(lattice):
    cats = lattice.extent_categories(_Concept(["Chronic Wound", "Bite Wound"]))
    assert cats == {"material entity"}


def test_scaled_ancestor_columns_are_not_mistaken_for_types(lattice):
    """Conceptual scaling writes `is_a: wound` too; Wound is a class, not a
    category, and reading it as one would license anything."""
    assert "Wound" not in lattice.extent_categories(_Concept(["Chronic Wound"]))


# ── the rule: only a label the ontologies know can be judged ────────────────

KNOWN_MATERIAL = "Second-degree burn wound"   # GROUNDING: MaterialEntity (WONT_0000483; "2nd degree burn" is its alt term since 2026-09-12)
KNOWN_PROCESS = "Autolytic wound debridement process"   # GROUNDING: Process
KNOWN_QUALITY = "Redness"               # GROUNDING: Quality


def test_a_known_label_of_the_members_own_kind_is_licensed(lattice):
    ok, _ = lattice.name_is_licensed(KNOWN_MATERIAL, {"material entity"})
    assert ok


def test_a_known_label_of_the_wrong_kind_is_refused(lattice):
    """The actual failure this exists for: a process named over material wounds."""
    ok, why = lattice.name_is_licensed(KNOWN_PROCESS, {"material entity"})
    assert not ok
    assert "process" in why and "material entity" in why


def test_a_known_label_more_specific_than_its_members_is_refused(lattice):
    """A superclass is more general, never sideways and never narrower."""
    ok, _ = lattice.name_is_licensed(KNOWN_MATERIAL, {"continuant"})
    assert not ok


def test_a_mixed_extent_needs_a_common_ancestor(lattice):
    ok, _ = lattice.name_is_licensed(KNOWN_MATERIAL, {"material entity", "quality"})
    assert not ok, "MaterialEntity does not generalise Quality"


def test_a_label_the_ontologies_do_not_know_is_not_judged(lattice):
    """This is the part that was pretending. A category the model declared about
    its own new label was unverifiable by construction and satisfied by answering
    "material entity"; across five live runs it refused no bad name and lost one
    good one. What keeps a new name honest is being named top-down under an
    already-named parent."""
    ok, why = lattice.name_is_licensed("Open Fracture Wound", {"material entity"})
    assert ok
    assert "not in MILD or WONT" in why


def test_an_untyped_extent_is_not_judged(lattice):
    """Curated concepts the corpus never mentions carry no category."""
    ok, why = lattice.name_is_licensed(KNOWN_PROCESS, set())
    assert ok and "no category" in why


# ── the category is a constraint, not an answer ─────────────────────────────

def test_the_category_label_is_not_an_acceptable_name(lattice):
    """Telling the model the extent's category stopped it proposing a disorder
    over wounds — and started it answering "Material entity"."""
    for bad in ("Material entity", "MATERIALENTITY", "process", "quality"):
        ok, why = lattice.name_is_a_grouping(bad)
        assert not ok, bad
        assert "biomedical grouping" in why


def test_a_real_grouping_passes(lattice):
    assert lattice.name_is_a_grouping("Traumatic Wound")[0]
    assert lattice.name_is_a_grouping("Pathological Skin Wound")[0]


def test_a_category_named_concept_is_refused_end_to_end(lattice):
    lattice._lattice = [_Concept(["Chronic Wound", "Bite Wound"])]
    asyncio.run(lattice.create_superclass_names(_LLM("Material entity")))

    assert getattr(lattice._lattice[0], "name", None) is None
    assert "biomedical grouping" in lattice.rejected_names[0][1]


def test_a_licensed_name_is_applied(lattice):
    lattice._lattice = [_Concept(["Chronic Wound", "Bite Wound"])]
    asyncio.run(lattice.create_superclass_names(_LLM("Traumatic Wound")))

    assert lattice._lattice[0].name == "Traumatic Wound"
    assert lattice.rejected_names == []


# ── the ontologies are the only source of a name's category ─────────────────

def test_a_known_label_takes_its_category_from_the_ontologies(lattice):
    """A declared category is a claim. Where MILD or WONT already knows the
    label, their answer is the one that counts — the same rule extraction uses
    for grounding: a lookup, never a generation."""
    from wound_ontology.llm.extraction_models import GROUNDING
    label, category = next((lab, cat) for cat, tab in GROUNDING.items()
                           for lab in tab if tab)
    assert lattice.category_of_known_class(label) == category
    assert lattice.category_of_known_class(label.upper()) == category


def test_an_unknown_label_has_no_ontology_category(lattice):
    assert lattice.category_of_known_class("Zzz Nonexistent Grouping") is None


def test_a_known_label_of_the_wrong_kind_is_refused_end_to_end(lattice):
    lattice._lattice = [_Concept(["Chronic Wound", "Bite Wound"])]
    asyncio.run(lattice.create_superclass_names(_LLM(KNOWN_PROCESS)))
    assert getattr(lattice._lattice[0], "name", None) is None


# ── top-down, general to specific ───────────────────────────────────────────

def test_two_concepts_may_not_share_a_name(lattice):
    """Four concepts came back called "Wound", collapsed onto one node, and the
    lattice's own order edges became a cycle."""
    top = _Concept(["Chronic Wound", "Bite Wound", "Scratch Wound"], ("is_a: wound",))
    sub = _Concept(["Bite Wound", "Scratch Wound"],
                   ("is_a: wound", "is_a: bite wound"), (top,))
    lattice._lattice = [sub, top]

    asyncio.run(lattice.create_superclass_names(_LLM("Wound")))

    assert top.name == "Wound"
    assert getattr(sub, "name", None) is None
    assert "already names another concept" in lattice.rejected_names[0][1]


def test_the_more_general_concept_is_named_first(lattice):
    """Known before unknown: the parent has to exist before the child can be
    named as a specialisation of it."""
    top = _Concept(["Chronic Wound", "Bite Wound", "Scratch Wound"], ("is_a: wound",))
    sub = _Concept(["Bite Wound", "Scratch Wound"],
                   ("is_a: wound", "is_a: bite wound"), (top,))
    lattice._lattice = [sub, top]

    llm = _LLM("Wound", "Bite Wound")
    asyncio.run(lattice.create_superclass_names(llm))

    assert [c["parent_names"] for c in llm.seen] == [[], ["Wound"]], \
        "the subclass was named without its parent in hand"
    assert sub.name == "Bite Wound"


def test_the_child_is_told_what_sets_it_apart(lattice):
    top = _Concept(["Chronic Wound", "Bite Wound", "Scratch Wound"], ("is_a: wound",))
    sub = _Concept(["Bite Wound", "Scratch Wound"],
                   ("is_a: wound", "is_a: bite wound"), (top,))
    lattice._lattice = [sub, top]

    llm = _LLM("Wound", "Bite Wound")
    asyncio.run(lattice.create_superclass_names(llm))

    assert llm.seen[1]["differentia"] == ["is_a: bite wound"]


def test_names_already_taken_are_passed_on(lattice):
    top = _Concept(["Chronic Wound", "Bite Wound", "Scratch Wound"], ("is_a: wound",))
    sub = _Concept(["Bite Wound", "Scratch Wound"],
                   ("is_a: wound", "is_a: bite wound"), (top,))
    lattice._lattice = [sub, top]

    llm = _LLM("Wound", "Bite Wound")
    asyncio.run(lattice.create_superclass_names(llm))

    assert "Wound" in llm.seen[1]["existing"], \
        "the second call could not know the first name; that is how duplicates got in"
