"""A term gets one category edge, decided once, not one per mention.

Stage-1 typing runs per abstract, so nothing stops two abstracts typing the same
term differently. `Necrosis` arrived as `MaterialEntity` from one abstract and
`Process` from two others; both became edges; BFO makes continuant and occurrent
disjoint; the reasoner derived ⊥ and the gate had to remove them afterwards. 42
of 48 quarantined edges were this, across 16 terms.

The store keeps every abstract's opinion — the disagreement is data. What may not
survive is a hierarchy built incoherently from it.
"""
import pandas as pd
import pytest

from wound_ontology.hierarchies.base_hierarchy import SOURCE_TEXT
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.store.concept_store import ConceptStore


class _DM:
    def __init__(self, data): self.json = data
    def load_latest_json(self, _): return self.json
    def save_as_json(self, d, _): self.json = d
    def load_latest_csv(self, _): return None
    def save_as_csv(self, *a): pass


def _store(records):
    return ConceptStore(_DM(records), "concept_store")


def _hier():
    h = ClassHierarchy.__new__(ClassHierarchy)
    h._df = pd.DataFrame(dtype=float)
    h._prov, h._candidates = {}, {}
    h._prov_loaded = True
    return h


@pytest.fixture
def resolver(tmp_path):
    """A reasoner gate over a minimal skeleton: least_common_category reads the
    BFO backbone from the skeleton TTL, so it needs one — but not ROBOT, and not
    the generated output/ file, which tests must not depend on."""
    from wound_ontology.llm.extraction_models import CATEGORY_IRI, CATEGORY_PARENT
    from wound_ontology.reasoning.gate import ReasonerGate

    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> ."]
    for name, iri in CATEGORY_IRI.items():
        lines.append(f"<{iri}> a owl:Class .")
        parent = CATEGORY_PARENT.get(name)
        if parent:
            lines.append(f"<{iri}> rdfs:subClassOf <{CATEGORY_IRI[parent]}> .")
    skeleton = tmp_path / "skeleton.ttl"
    skeleton.write_text("\n".join(lines), encoding="utf-8")
    return ReasonerGate(skeleton).least_common_category


CONFLICTED = {
    "1": {"entities": {"Necrosis": {"is_a: material entity": 1.0}}},
    "2": {"entities": {"Necrosis": {"is_a: process": 1.0}}},
}


def test_without_a_resolver_both_categories_become_edges():
    """The old behaviour, pinned so the difference stays visible.

    Two spellings are in play and both are correct. The STORE holds the
    declared vocabulary (`material entity`); the HIERARCHY holds class labels,
    which it title-cases like every other label, so the same category reads
    back as `Material Entity` -- the spelling the curated seed also gives
    BFO_0000040. That is what makes the seed edge and the extracted edge one
    edge instead of two. Recognition is separator-blind, so it is still a
    category on the way back in.
    """
    h = _hier()
    h.get_data(_store(CONFLICTED))
    assert set(h.parents_of("Necrosis")) == {"Material Entity", "Process"}


RECONCILABLE = {
    "1": {"entities": {"Closure": {"is_a: process": 1.0}}},
    "2": {"entities": {"Closure": {"is_a: process boundary": 1.0}}},
}


def test_a_conflict_collapses_to_the_common_ancestor(resolver):
    """`Process` and `ProcessBoundary` both sit under `Occurrent`, so there is an
    honest answer and the term keeps a category."""
    h = _hier()
    h.get_data(_store(RECONCILABLE), reconcile_categories=resolver)
    assert h.parents_of("Closure") == ["Occurrent"]


def test_an_agreed_term_keeps_its_own_category(resolver):
    h = _hier()
    h.get_data(_store({"1": {"entities": {"Wound": {"is_a: material entity": 1.0}}},
                       "2": {"entities": {"Wound": {"is_a: material entity": 1.0}}}}),
               reconcile_categories=resolver)
    assert h.parents_of("Wound") == ["Material Entity"]


def test_an_irreconcilable_term_gets_no_category_edge(resolver):
    """The real case: `Necrosis` typed MaterialEntity by one abstract and Process
    by two others spans continuant and occurrent, which BFO declares disjoint.
    There is no honest category, so it gets none — and the clash that the edge
    gate had to clean up afterwards never enters the hierarchy."""
    h = _hier()
    h.get_data(_store(CONFLICTED), reconcile_categories=resolver)
    assert h.parents_of("Necrosis") == []
    assert h.irreconcilable["Necrosis"] == {"material entity", "process"}


def test_the_irreconcilable_list_is_announced(resolver, capsys):
    _hier().get_data(_store(CONFLICTED), reconcile_categories=resolver)
    out = capsys.readouterr().out
    assert "NO common ancestor" in out and "Necrosis" in out


def test_non_category_is_a_edges_are_untouched(resolver):
    """Only BFO category edges are reconciled. `Chronic Wound is_a Wound` is an
    ordinary subsumption and must survive alongside whatever category the term
    also carries."""
    store = _store({"1": {"entities": {"Chronic Wound": {"is_a: Wound": 1.0,
                                                         "is_a: material entity": 1.0}}},
                    "2": {"entities": {"Chronic Wound": {"is_a: process": 1.0}}}})
    h = _hier()
    h.get_data(store, reconcile_categories=resolver)
    assert "Wound" in h.parents_of("Chronic Wound")


def test_reconciled_edges_are_still_text(resolver):
    h = _hier()
    h.get_data(_store(RECONCILABLE), reconcile_categories=resolver)
    assert h.source_of("Closure", "Occurrent") == SOURCE_TEXT
