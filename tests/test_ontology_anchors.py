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
            # merges, as the real one does: the mapping persists across builds
            self.data.update({k: v for k, v in assignment.items() if k != v})
        def remove(self, *terms):
            for t in terms: self.data.pop(t, None)
    m = TermMapper.__new__(TermMapper)
    m.name = "test"
    m._term_mapping = _Mapping()
    return m


def _build(mapper, terms, anchors=None, freq=None, groups=None, accept=None):
    return mapper.build_from_embeddings(
        terms, embedder=_Embedder(groups or []),
        similarity_threshold=0.95,
        frequencies=freq or {}, anchors=anchors, accept_mapping=accept,
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
    """The old behaviour, pinned so the difference stays visible.

    The pair differs by case, not by plural: frequency is what decides here, and
    the singular-spelling rule below must not be what settles it.
    """
    out = _build(
        mapper,
        ["Granulation process", "granulation process"],
        freq={"granulation process": 99},
        groups=[["granulation"]],
    )
    assert out.get("Granulation process") == "granulation process"


# ── the canonical is the singular spelling ───────────────────────────────────
#
# The canonical becomes a class LABEL, and an OBO class label is singular.
# Frequency alone picked the plural for anything a paper counts: 10 of the 193
# live entries mapped a singular onto a plural, and once `run_apply_mapping`
# propagated them the merge labelled the class `Diabetic Foot Ulcers` — costing
# CQ001, CQ006, CQ051 and CQ054 the term they resolve on.

def test_the_singular_spelling_is_canonical_even_when_rarer(mapper):
    out = _build(
        mapper,
        ["diabetic foot ulcer", "diabetic foot ulcers"],
        freq={"diabetic foot ulcers": 99, "diabetic foot ulcer": 1},
        groups=[["diabetic foot ulcer"]],
    )
    assert out.get("diabetic foot ulcers") == "diabetic foot ulcer"


def test_an_anchor_stays_canonical_however_it_is_spelled(mapper):
    """An ontology's own label is not ours to re-spell."""
    out = _build(
        mapper,
        ["Wound complications", "wound complication"],
        anchors={"Wound complications"},
        freq={"wound complication": 99},
        groups=[["wound complication"]],
    )
    assert out.get("wound complication") == "Wound complications"


def test_the_rule_never_trades_one_concept_for_another(mapper):
    """Only spellings of the same term compete; a different term is untouched."""
    out = _build(
        mapper,
        ["pressure ulcers", "pressure ulcer", "pressure injury"],
        freq={"pressure ulcers": 99},
        groups=[["pressure ulcer"], ["pressure injury"]],
    )
    assert out.get("pressure ulcers") == "pressure ulcer"
    assert out.get("pressure injury") in (None, "pressure injury")


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
    # The store term moves onto the ontology label, and the ontology label stays
    # where it is. Asserting the direction is what this test is for; asserting the
    # anchor is merely absent would also pass if it had been mapped away and the
    # entry filtered out somewhere downstream.
    assert out["granulation processes"] == "Granulation process"
    assert out.get("Granulation process") == "Granulation process"


def test_the_orchestrator_collects_real_ontology_labels():
    """The anchors come from WONT and MILD themselves, not a hand-kept list."""
    import wound_ontology.orchestrator as orch
    p = orch.Orchestrator.__new__(orch.Orchestrator)
    labels = p.ontology_labels()
    assert len(labels) > 400
    for expected in ("Granulation process", "Wound complication process",
                     "Wound infection process", "Necrosis"):
        assert expected in labels, expected


# ── the categorical guard ───────────────────────────────────────────────────

def test_a_rejected_mapping_leaves_the_term_alone(mapper):
    """SapBERT cannot tell a process from its material bearer — the labels are
    nearly identical — so it proposed `Necrosis Process -> Necrosis`. Raising the
    threshold does not help: the bad matches are semantically close, which is
    exactly why the embedding likes them."""
    out = _build(
        mapper,
        ["Necrosis", "Necrosis Process"],
        anchors={"Necrosis"},
        groups=[["necrosis"]],
        accept=lambda term, canonical: False,     # a process is not its bearer
    )
    assert out.get("Necrosis Process") in (None, "Necrosis Process")
    assert ("Necrosis Process", "Necrosis") in mapper.refused_mappings


def test_an_accepted_mapping_still_goes_through(mapper):
    out = _build(
        mapper,
        ["Granulation process", "Granulation Process"],
        anchors={"Granulation process"},
        groups=[["granulation"]],
    )
    assert out.get("Granulation Process") == "Granulation process"
    assert mapper.refused_mappings == []


def test_the_guard_only_applies_to_anchors(mapper):
    """Store-to-store clustering is unchanged; the guard is about claiming a term
    means an existing class."""
    calls = []
    mapper.build_from_embeddings(
        ["wounds", "wound"], embedder=_Embedder([["wound"]]),
        similarity_threshold=0.95, frequencies={"wound": 9},
        anchors=set(), accept_mapping=lambda t, c: calls.append((t, c)) or False,
    )
    assert calls == [], "the validator was consulted for a non-anchor canonical"


def test_the_real_guard_refuses_a_process_mapped_onto_its_bearer():
    """Wired end to end against the live skeleton and store."""
    import wound_ontology.orchestrator as orch
    p = orch.Orchestrator()
    accept = p._category_compatible_mapping(set(p.ontology_categories()))
    assert not accept("Necrosis Process", "Necrosis")
    assert not accept("Skin grafting", "Skin graft")
    assert accept("chronic wounds", "Chronic wound")


def test_bfo_category_names_are_never_mapped():
    """They appear in the store as `is_a: Process` targets; lowercasing them to
    BFO's `process` would stop category detection recognising them, and every
    reconciliation and split downstream reads those keys."""
    import wound_ontology.orchestrator as orch
    p = orch.Orchestrator()
    accept = p._category_compatible_mapping(set(p.ontology_categories()))
    for name in ("Process", "Quality", "Disposition", "Tendency"):
        assert not accept(name, name.lower()), name


def test_the_pre_merge_path_is_guarded_too(mapper):
    """`Process` and BFO's `process` share a normalised form, so they were merged
    before clustering ever ran — through the one door the validator was not
    watching, and the one mapping guaranteed to break category detection."""
    out = _build(
        mapper,
        ["process", "Process"],
        anchors={"process"},
        groups=[["process"]],
        accept=lambda term, canonical: False,
    )
    assert out.get("Process") in (None, "Process")
    assert ("Process", "process") in mapper.refused_mappings


def test_a_refused_mapping_recorded_earlier_is_withdrawn(mapper):
    """The mapping persists across builds, so a pair refused now may still be
    present from a build that had no validator. The guard must not be defeated by
    the file."""
    mapper._term_mapping.data["Necrosis Process"] = "Necrosis"
    _build(
        mapper,
        ["Necrosis", "Necrosis Process"],
        anchors={"Necrosis"},
        groups=[["necrosis"]],
        accept=lambda term, canonical: False,
    )
    assert "Necrosis Process" not in mapper._term_mapping.data


def test_curated_mappings_are_not_disturbed(mapper):
    """Only the exact refused pair is withdrawn; anything else in the file stays."""
    mapper._term_mapping.data["some curated term"] = "its canonical form"
    _build(mapper, ["Necrosis", "Necrosis Process"], anchors={"Necrosis"},
           groups=[["necrosis"]], accept=lambda t, c: False)
    assert mapper._term_mapping.data["some curated term"] == "its canonical form"
