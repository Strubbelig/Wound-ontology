"""refresh_class_hierarchy must actually load curated edges when given none.

Since 2026-10-21 the class hierarchy is a VIEW: refresh_class_hierarchy derives
it from its sources and stores nothing but a provenance snapshot; the
mereological hierarchy is no longer built (run_build_hierarchies is a
deprecated alias).

The loader is unit-tested in test_curated_seed.py and the export side in
test_extend_lexicon.py; what neither covered is the wiring between them. The
CSV era failed exactly here: config pointed at a file, the file was gone, and
the only symptom was a hierarchy with no curated tier.
"""
import pandas as pd
import pytest

import wound_ontology.orchestrator as orch
from wound_ontology.hierarchies.base_hierarchy import SOURCE_CURATED

ONTO = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://example.org/> .

ex:Wound        a owl:Class ; rdfs:label "Wound" .
ex:ChronicWound a owl:Class ; rdfs:label "Chronic Wound" ; rdfs:subClassOf ex:Wound .
ex:AcuteWound   a owl:Class ; rdfs:label "Acute Wound"   ; rdfs:subClassOf ex:Wound .
"""


class _FakeStore:
    """The store is read, never written. Curated edges used to be pushed through
    it, which made it assert 459 edges it had never extracted."""

    def get_data(self, *a, **kw):
        raise AssertionError(
            "run_build_hierarchies wrote to the ConceptStore. Curated edges are "
            "read from the ontologies as their own source."
        )

    def view(self):
        return iter(())


class _FakeTermDict:
    """No placements (rule 64): the `placed` source is tested in test_placements_view."""

    def placements(self):
        return []

    def peek(self, *a):
        return {}


class _FakeTermMapper:
    _term_mapping = _FakeTermDict()


class _FakeDM:
    def list_prefixes(self, *a, **kw):
        return []

    def load_latest_json(self, *a, **kw):
        return None


class _FakeGate:
    """A unit test builds no reasoner skeleton; only the resolver is handed on."""

    @staticmethod
    def least_common_category(cats):
        return None


class _FakeHier:
    """Records what the orchestrator hands it, and stamps like the real one."""

    def __init__(self):
        self.curated = None
        self.fca = None
        self.saved = False
        self.snapshot = False
        self.df = pd.DataFrame(dtype=float)
        self.concepts, self.roots = [], []
        self._prov = {}

    def get_data(self, store, curated=None, fca=(), reconcile_categories=None, placed=()):
        self.curated = curated
        self.placed = list(placed)
        self.fca = list(fca)
        self.reconciler = reconcile_categories
        if curated is None or curated.empty:
            return
        for _, row in curated.iterrows():
            self._prov[(row["Class"], row["Parent class"])] = SOURCE_CURATED

    def save(self):
        self.saved = True

    def save_snapshot(self):
        self.snapshot = True

    def provenance_summary(self):
        counts = {}
        for v in self._prov.values():
            counts[v] = counts.get(v, 0) + 1
        return counts


@pytest.fixture
def pipeline():
    p = orch.Orchestrator.__new__(orch.Orchestrator)
    p.store = _FakeStore()
    p.dm = _FakeDM()
    fake = _FakeHier()
    p._class_hier = None
    p._view_factory = lambda dm: fake
    p._gate = _FakeGate()
    p.term_mapper = _FakeTermMapper()
    p.fake_view = fake
    return p


@pytest.fixture
def onto(tmp_path):
    p = tmp_path / "onto.ttl"
    p.write_text(ONTO)
    return p


def test_none_loads_curated_edges_from_the_ontologies(pipeline, onto):
    pipeline.refresh_class_hierarchy(curated_sources=[onto])

    pairs = set(map(tuple, pipeline.class_hier.curated.values))
    assert pairs == {("Chronic Wound", "Wound"), ("Acute Wound", "Wound")}
    assert pipeline.class_hier.provenance_summary() == {SOURCE_CURATED: 2}
    # ...and nothing was written into the store on the way. _FakeStore.get_data
    # raises, so reaching this line is the assertion.


def test_the_default_sources_are_wont_and_mild(pipeline, monkeypatch, onto):
    """No curated_sources argument -> config's ground truth + MILD, not a CSV."""
    seen = {}

    def fake_defaults():
        seen["called"] = True
        return [onto], []

    monkeypatch.setattr(
        "wound_ontology.hierarchies.curated_seed.default_curated_sources",
        fake_defaults,
    )
    pipeline.refresh_class_hierarchy()
    assert seen.get("called"), "should fall back to the WONT/MILD defaults"
    assert pipeline.class_hier.curated is not None


def test_an_explicit_frame_is_used_verbatim(pipeline, monkeypatch):
    """Passing a frame must not read any ontology from disk."""
    monkeypatch.setattr(
        "wound_ontology.hierarchies.curated_seed.default_curated_sources",
        lambda: (_ for _ in ()).throw(AssertionError("must not load")),
    )
    df = pd.DataFrame([{"Class": "A", "Parent class": "B"}])
    pipeline.refresh_class_hierarchy(predefined_df=df)
    assert pipeline.class_hier.curated is df


def test_an_empty_frame_means_no_curated_edges(pipeline, monkeypatch):
    """The documented opt-out, and it must not silently reload from disk."""
    monkeypatch.setattr(
        "wound_ontology.hierarchies.curated_seed.default_curated_sources",
        lambda: (_ for _ in ()).throw(AssertionError("must not load")),
    )
    empty = pd.DataFrame(columns=["Class", "Parent class"])
    pipeline.refresh_class_hierarchy(predefined_df=empty)
    assert pipeline.class_hier.provenance_summary() == {}


def test_a_missing_source_stops_the_build(pipeline, tmp_path):
    """Not a warning and a smaller hierarchy — curated edges outrank the rest."""
    with pytest.raises(FileNotFoundError, match="outrank"):
        pipeline.refresh_class_hierarchy(curated_sources=[tmp_path / "gone.ttl"])
    assert pipeline.fake_view.curated is None
    assert pipeline._class_hier is None, "a failed derivation must not leave a view behind"


def test_the_view_is_not_stored_and_there_is_no_mereological_hierarchy(pipeline, onto):
    """The class hierarchy is a view (2026-10-21): no matrix is written, only the
    provenance snapshot for the inspection pages. The mereological hierarchy is
    gone (2026-10-27): part_of reaches the FCA from the cleaned store, and WONT
    only as a read relation."""
    view = pipeline.refresh_class_hierarchy(curated_sources=[onto])
    assert view is pipeline.fake_view and pipeline.class_hier is view
    assert not view.saved, "the view itself must never be written"
    assert view.snapshot, "the inspection pages read the provenance snapshot"
    assert not hasattr(orch.Orchestrator, "mere_hier")


def test_run_build_hierarchies_is_an_alias_for_the_view(pipeline, onto):
    view = pipeline.run_build_hierarchies(curated_sources=[onto])
    assert view is pipeline.fake_view


def test_the_edge_gate_verdicts_are_taken_off_the_view(pipeline, onto):
    """A later process (build_wont_core.py) must see the gated view the
    extension was built from -- but a curated edge is never taken off."""
    class _DM(_FakeDM):
        def load_latest_json(self, prefix):
            if prefix == "class_hierarchy_edge_verdicts":
                return {"rejected": [{"child": "Chronic Wound", "parent": "Wound"},
                                     {"child": "Burn", "parent": "Process"}]}
            return None

    fake = pipeline.fake_view
    fake.df = pd.DataFrame(1.0, index=["Chronic Wound", "Burn"], columns=["Wound", "Process"])
    pipeline.dm = _DM()
    view = pipeline.refresh_class_hierarchy(curated_sources=[onto])
    assert view.df.at["Burn", "Process"] == 0.0, "a text edge the gate rejected stays off"
    assert view.df.at["Chronic Wound", "Wound"] == 1.0, "a curated edge is the curator's to remove"
    assert view.verdicts_applied


def test_the_gate_can_ask_for_every_edge_again(pipeline, onto):
    class _DM(_FakeDM):
        def load_latest_json(self, prefix):
            if prefix == "class_hierarchy_edge_verdicts":
                return {"rejected": [{"child": "Burn", "parent": "Process"}]}
            return None

    fake = pipeline.fake_view
    fake.df = pd.DataFrame(1.0, index=["Burn"], columns=["Process"])
    pipeline.dm = _DM()
    view = pipeline.refresh_class_hierarchy(curated_sources=[onto], include_rejected=True)
    assert view.df.at["Burn", "Process"] == 1.0
    assert not view.verdicts_applied


def test_accepted_lattice_slices_reach_the_hierarchy(pipeline, onto):
    """A review done in an earlier session is read back from disk, not from
    this session's objects — otherwise promoting and then restarting loses it."""
    class _DM(_FakeDM):
        def list_prefixes(self, pattern, extension):
            return ["concept_lattice_wound_accepted"]

        def load_latest_json(self, prefix):
            if prefix == "concept_lattice_wound_accepted":
                return [["Chronic Wound", "Injury"]]
            return None

    pipeline.dm = _DM()
    pipeline.refresh_class_hierarchy(curated_sources=[onto])

    assert pipeline.class_hier.fca == [[("Chronic Wound", "Injury")]]


def test_no_review_means_no_fca_source(pipeline, onto):
    pipeline.refresh_class_hierarchy(curated_sources=[onto])
    assert pipeline.class_hier.fca == []


def test_a_subtree_gets_its_own_artifact_names():
    """One lattice was shared by every analysis; the FCA hierarchy never cleared
    itself, so its saved CSV was the union of every subtree ever analysed."""
    from wound_ontology.orchestrator import _slugify
    assert _slugify("Chronic Wound") == "chronic_wound"
    assert _slugify("CO2 Wound") == "co2_wound"
    assert _slugify("  ") == "unnamed"


def test_the_class_hierarchy_is_given_a_category_resolver(pipeline, onto):
    """Without it the hierarchy contradicts itself by construction: one term
    typed several ways across abstracts becomes several category edges, and the
    reasoner has to clean up afterwards."""
    pipeline.refresh_class_hierarchy(curated_sources=[onto])
    assert pipeline.class_hier.reconciler is not None
