"""A store term that means an existing class is mapped onto it, not beside it.

The pipeline had a semantic matcher that was never shown the ontology, and an
ontology matcher with no semantics. SapBERT clustered store terms against each
other, so it could merge "Complication" with "Complications" and never notice
WONT's "Wound complication process"; the merge-time lexicon knew every ontology
label but matched by string — exact, punctuation, singular, stated synonyms — so
"Granulation" never reached "Granulation process". Terms fell between the two and
were minted as twins of classes that already existed.

Anchors close it: ontology labels join the clustering and always win canonicality.
"""
import numpy as np
import pytest

from wound_ontology.mappers.term_mapper import TermMapper


class _Embedder:
    """Cosine geometry by hand: terms sharing a stem are near-identical."""
    def __init__(self, groups):
        self.groups = groups

    def embed(self, terms):
        dim = len(self.groups) + 1
        out = np.zeros((len(terms), dim))
        for i, t in enumerate(terms):
            slot = next((k for k, g in enumerate(self.groups)
                         if any(m.lower() in t.lower() for m in g)), dim - 1)
            out[i, slot] = 1.0
        return out


@pytest.fixture
def mapper():
    class _Mapping:
        def __init__(self): self.data = {}
        def add_batch(self, assignment, metadata):
            # keep only the non-identity mappings, which is what callers read
            self.data = {k: v for k, v in assignment.items() if k != v}
    m = TermMapper.__new__(TermMapper)
    m.name = "test"
    m._term_mapping = _Mapping()
    return m


def _build(mapper, terms, anchors=None, freq=None, groups=None):
    return mapper.build_from_embeddings(
        terms, embedder=_Embedder(groups or []),
        similarity_threshold=0.95,
        frequencies=freq or {}, anchors=anchors,
    )


def test_the_ontology_label_wins_canonicality(mapper):
    """Even though the store term is far more frequent."""
    out = _build(
        mapper,
        ["Granulation process", "granulation processes"],
        anchors={"Granulation process"},
        freq={"granulation processes": 99},
        groups=[["granulation"]],
    )
    assert out.get("granulation processes") == "Granulation process"


def test_without_anchors_the_frequent_store_term_wins(mapper):
    """The old behaviour, pinned so the difference stays visible."""
    out = _build(
        mapper,
        ["Granulation process", "granulation processes"],
        freq={"granulation processes": 99},
        groups=[["granulation"]],
    )
    assert out.get("Granulation process") == "granulation processes"


def test_an_unmatched_store_term_is_left_alone(mapper):
    out = _build(mapper, ["Ischemia", "Granulation process"],
                 anchors={"Granulation process"},
                 groups=[["granulation"], ["ischemia"]])
    assert out.get("Ischemia") in (None, "Ischemia")


def test_anchors_do_not_map_onto_store_terms(mapper):
    """The direction matters: the ontology is the target, never the source."""
    out = _build(
        mapper,
        ["Granulation process", "granulation processes"],
        anchors={"Granulation process"},
        freq={"granulation processes": 99},
        groups=[["granulation"]],
    )
    assert "Granulation process" not in out


def test_the_orchestrator_collects_real_ontology_labels():
    """The anchors come from WONT and MILD themselves, not a hand-kept list."""
    import wound_ontology.orchestrator as orch
    p = orch.Orchestrator.__new__(orch.Orchestrator)
    labels = p.ontology_labels()
    assert len(labels) > 400
    for expected in ("Granulation process", "Wound complication process",
                     "Wound infection process", "Necrosis"):
        assert expected in labels, expected
