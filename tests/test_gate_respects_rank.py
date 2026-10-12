"""A clash is resolved by dropping the weakest evidence, not all of it.

WONT asserts `Necrosis subClassOf pathological disorder` and nothing else. Two
abstracts typed Necrosis as a Process. BFO makes continuant and occurrent
disjoint, so the reasoner derives ⊥ — and the gate quarantined *both* edges,
curated included. A text assertion had silently overridden the ground truth,
which is the one thing the provenance ranks exist to prevent.
"""
import pytest

from wound_ontology.hierarchies.base_hierarchy import (
    SOURCE_CURATED, SOURCE_FCA, SOURCE_TEXT,
)
from wound_ontology.reasoning.gate import BATCH_NS, ReasonerGate, _slug


class _Gate(ReasonerGate):
    """Real check_edges, fake reasoner: `Bad` is unsatisfiable until every
    edge that made it so is gone."""

    def __init__(self, bad_when):
        self._bad_when = bad_when
        self.passes = 0

    def available(self):
        return None

    def _label_index(self):
        return {}

    def build_edge_graph(self, edges, label_index=None):
        return list(edges)

    def _unsatisfiable(self, g):
        self.passes += 1
        parents = {p for c, p in g if c == "Necrosis"}
        return {BATCH_NS + _slug("Necrosis")} if self._bad_when(parents) else set()

    def _explain(self, g, max_expl=5):
        return "explanation"


def _clash_while_both_present(parents):
    return "Process" in parents and "Pathological Disorder" in parents


EDGES = [("Necrosis", "Pathological Disorder"), ("Necrosis", "Process")]
SOURCES = {("Necrosis", "Pathological Disorder"): SOURCE_CURATED,
           ("Necrosis", "Process"): SOURCE_TEXT}


def test_the_curated_edge_survives_and_the_text_edge_goes():
    r = _Gate(_clash_while_both_present).check_edges(EDGES, sources=SOURCES)
    assert r.quarantined == [("Necrosis", "Process")]
    assert ("Necrosis", "Pathological Disorder") in r.accepted


def test_without_provenance_the_gate_drops_both():
    """The old behaviour, pinned so the difference stays visible."""
    r = _Gate(_clash_while_both_present).check_edges(EDGES)
    assert len(r.quarantined) == 2


def test_the_spared_edge_is_reported():
    r = _Gate(_clash_while_both_present).check_edges(EDGES, sources=SOURCES)
    assert ("Necrosis", "Pathological Disorder") in r.spared


def test_quarantined_edges_carry_their_source():
    r = _Gate(_clash_while_both_present).check_edges(EDGES, sources=SOURCES)
    assert r.quarantined_sources[("Necrosis", "Process")] == SOURCE_TEXT


def test_a_curated_edge_that_is_inconsistent_alone_is_still_quarantined():
    """Rank buys precedence, not immunity: if the ground truth contradicts
    itself, the gate must still say so."""
    r = _Gate(lambda parents: "Pathological Disorder" in parents).check_edges(
        EDGES, sources=SOURCES)
    assert ("Necrosis", "Pathological Disorder") in r.quarantined


def test_fca_is_dropped_before_text():
    edges = EDGES + [("Necrosis", "Skin Wound")]
    sources = {**SOURCES, ("Necrosis", "Skin Wound"): SOURCE_FCA}
    r = _Gate(lambda p: "Skin Wound" in p).check_edges(edges, sources=sources)
    assert r.quarantined == [("Necrosis", "Skin Wound")]
    assert len(r.accepted) == 2


def test_an_unstamped_edge_gives_up_first():
    """An edge nothing claims is the weakest evidence there is."""
    edges = EDGES + [("Necrosis", "Mystery")]
    r = _Gate(lambda p: "Mystery" in p).check_edges(edges, sources=SOURCES)
    assert r.quarantined == [("Necrosis", "Mystery")]


def test_a_consequence_is_not_judged_before_its_cause():
    """`Dry Necrosis is_a Necrosis` is curated and is that child's only edge, so
    per-child it looked like the weakest evidence going — while the text edge
    that made Necrosis unsatisfiable was still in place. Its child was
    unsatisfiable only by inheritance."""
    edges = EDGES + [("Dry Necrosis", "Necrosis")]
    sources = {**SOURCES, ("Dry Necrosis", "Necrosis"): SOURCE_CURATED}

    class _Inheriting(_Gate):
        def _unsatisfiable(self, g):
            self.passes += 1
            parents = {p for c, p in g if c == "Necrosis"}
            if not _clash_while_both_present(parents):
                return set()
            # Necrosis is bad, and so is everything under it.
            return {BATCH_NS + _slug("Necrosis"), BATCH_NS + _slug("Dry Necrosis")}

    r = _Inheriting(None).check_edges(edges, sources=sources)
    assert r.quarantined == [("Necrosis", "Process")]
    assert ("Dry Necrosis", "Necrosis") in r.accepted


class _RemoteCause(_Gate):
    """`Protein` is empty while `Nutrient is_a Material Entity` stands -- an
    edge on ANOTHER class (2026-10-03). The explanation names it."""

    def _unsatisfiable(self, g):
        self.passes += 1
        return {BATCH_NS + _slug("Protein")} if ("Nutrient", "Material Entity") in g else set()

    def _explain(self, g, max_expl=5):
        n, m = BATCH_NS + _slug("Nutrient"), BATCH_NS + _slug("Material Entity")
        return f"  - [Nutrient]({n}) SubClassOf [Material Entity]({m})\n"


def test_a_cause_on_another_class_goes_before_a_placed_edge():
    from wound_ontology.hierarchies.base_hierarchy import SOURCE_PLACED
    edges = [("Protein", "Biomacromolecule"), ("Nutrient", "Material Entity")]
    sources = {edges[0]: SOURCE_PLACED, edges[1]: SOURCE_TEXT}
    r = _RemoteCause(lambda p: False).check_edges(edges, sources=sources)
    assert r.quarantined == [("Nutrient", "Material Entity")]
    assert ("Protein", "Biomacromolecule") in r.accepted
