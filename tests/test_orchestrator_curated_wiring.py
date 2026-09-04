"""run_build_hierarchies must actually load curated edges when given none.

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


class _FakeDM:
    def list_prefixes(self, *a, **kw):
        return []

    def load_latest_json(self, *a, **kw):
        return None


class _FakeHier:
    """Records what the orchestrator hands it, and stamps like the real one."""

    def __init__(self):
        self.curated = None
        self.fca = None
        self.saved = False
        self.concepts, self.roots = [], []
        self._prov = {}

    def get_data(self, store, curated=None, fca=()):
        self.curated = curated
        self.fca = list(fca)
        if curated is None or curated.empty:
            return
        for _, row in curated.iterrows():
            self._prov[(row["Class"], row["Parent class"])] = SOURCE_CURATED

    def save(self):
        self.saved = True

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
    p.class_hier = _FakeHier()
    p.mere_hier = _FakeHier()
    return p


@pytest.fixture
def onto(tmp_path):
    p = tmp_path / "onto.ttl"
    p.write_text(ONTO)
    return p


def test_none_loads_curated_edges_from_the_ontologies(pipeline, onto):
    pipeline.run_build_hierarchies(curated_sources=[onto])

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
    pipeline.run_build_hierarchies()
    assert seen.get("called"), "should fall back to the WONT/MILD defaults"
    assert pipeline.class_hier.curated is not None


def test_an_explicit_frame_is_used_verbatim(pipeline, monkeypatch):
    """Passing a frame must not read any ontology from disk."""
    monkeypatch.setattr(
        "wound_ontology.hierarchies.curated_seed.default_curated_sources",
        lambda: (_ for _ in ()).throw(AssertionError("must not load")),
    )
    df = pd.DataFrame([{"Class": "A", "Parent class": "B"}])
    pipeline.run_build_hierarchies(predefined_df=df)
    assert pipeline.class_hier.curated is df


def test_an_empty_frame_means_no_curated_edges(pipeline, monkeypatch):
    """The documented opt-out, and it must not silently reload from disk."""
    monkeypatch.setattr(
        "wound_ontology.hierarchies.curated_seed.default_curated_sources",
        lambda: (_ for _ in ()).throw(AssertionError("must not load")),
    )
    empty = pd.DataFrame(columns=["Class", "Parent class"])
    pipeline.run_build_hierarchies(predefined_df=empty)
    assert pipeline.class_hier.provenance_summary() == {}


def test_a_missing_source_stops_the_build(pipeline, tmp_path):
    """Not a warning and a smaller hierarchy — curated edges outrank the rest."""
    with pytest.raises(FileNotFoundError, match="outrank"):
        pipeline.run_build_hierarchies(curated_sources=[tmp_path / "gone.ttl"])
    assert pipeline.class_hier.curated is None
    assert not pipeline.class_hier.saved


def test_hierarchies_are_saved_on_the_default_path(pipeline, onto):
    pipeline.run_build_hierarchies(curated_sources=[onto])
    assert pipeline.class_hier.saved and pipeline.mere_hier.saved


def test_accepted_lattice_slices_reach_the_hierarchy(pipeline, onto):
    """A review done in an earlier session is read back from disk, not from
    this session's objects — otherwise promoting and then restarting loses it."""
    class _DM(_FakeDM):
        def list_prefixes(self, pattern, extension):
            return ["concept_lattice_wound_accepted"]

        def load_latest_json(self, prefix):
            return [["Chronic Wound", "Injury"]]

    pipeline.dm = _DM()
    pipeline.run_build_hierarchies(curated_sources=[onto])

    assert pipeline.class_hier.fca == [[("Chronic Wound", "Injury")]]


def test_no_review_means_no_fca_source(pipeline, onto):
    pipeline.run_build_hierarchies(curated_sources=[onto])
    assert pipeline.class_hier.fca == []


def test_a_subtree_gets_its_own_artifact_names():
    """One lattice was shared by every analysis; the FCA hierarchy never cleared
    itself, so its saved CSV was the union of every subtree ever analysed."""
    from wound_ontology.orchestrator import _slugify
    assert _slugify("Chronic Wound") == "chronic_wound"
    assert _slugify("CO2 Wound") == "co2_wound"
    assert _slugify("  ") == "unnamed"
