"""One label typed several irreconcilable ways is several classes.

`Necrosis` arrived as `MaterialEntity` from one abstract and `Process` from two
others. Necrosis genuinely is a pathological process, and a material entity, and
arguably a disposition of tissue realised by trauma. Forcing one category loses a
sense; forcing none — what the reconciler does when the typings share no common
ancestor — loses the term entirely.

Each mention is renamed to `<Term> <Category>` using the category that abstract
gave it, so the label names its own superclass and every resulting term carries
exactly one category by construction.
"""
import copy

import pytest

from wound_ontology.store.concept_store import ConceptStore


class _DM:
    def __init__(self, data): self.json = data
    def load_latest_json(self, _): return self.json
    def save_as_json(self, d, _): self.json = d


@pytest.fixture
def resolver(tmp_path):
    from wound_ontology.llm.extraction_models import CATEGORY_IRI, CATEGORY_PARENT
    from wound_ontology.reasoning.gate import ReasonerGate
    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> ."]
    for name, iri in CATEGORY_IRI.items():
        lines.append(f"<{iri}> a owl:Class .")
        if CATEGORY_PARENT.get(name):
            lines.append(f"<{iri}> rdfs:subClassOf <{CATEGORY_IRI[CATEGORY_PARENT[name]]}> .")
    f = tmp_path / "skeleton.ttl"
    f.write_text("\n".join(lines), encoding="utf-8")
    return ReasonerGate(f).least_common_category


NECROSIS = {
    "1": {"entities": {"Necrosis": {"is_a: MaterialEntity": 1.0,
                                    "part_of: Wound Bed": 1.0}}},
    "2": {"entities": {"Necrosis": {"is_a: Process": 1.0,
                                    "has_participant: Tissue": 1.0}}},
}


def _store(data):
    # deepcopy: the split mutates the store's dict in place, as it should, so a
    # shared module-level fixture would leak one test's split into the next.
    return ConceptStore(_DM(copy.deepcopy(data)), "concept_store")


def test_each_sense_becomes_its_own_term(resolver):
    s = _store(NECROSIS)
    s.split_irreconcilable_terms(resolver)
    names = {e for rec in s.dict.values() for e in rec["entities"]}
    assert names == {"Necrosis Material Entity", "Necrosis Process"}


def test_the_label_names_its_own_superclass(resolver):
    s = _store(NECROSIS)
    rep = s.split_irreconcilable_terms(resolver)
    assert rep["split"]["Necrosis"] == {
        "MaterialEntity": "Necrosis Material Entity",
        "Process": "Necrosis Process",
    }


def test_each_sense_keeps_the_relations_its_abstract_asserted(resolver):
    """The point of splitting per mention rather than per corpus: the relations
    follow the sense the abstract meant."""
    s = _store(NECROSIS)
    s.split_irreconcilable_terms(resolver)
    ents = {e: a for rec in s.dict.values() for e, a in rec["entities"].items()}
    assert "part_of: Wound Bed" in ents["Necrosis Material Entity"]
    assert "has_participant: Tissue" in ents["Necrosis Process"]


def test_each_split_term_now_has_exactly_one_category(resolver):
    s = _store(NECROSIS)
    s.split_irreconcilable_terms(resolver)
    for rec in s.dict.values():
        for _, attrs in rec["entities"].items():
            cats = [a for a in attrs if a.startswith("is_a: ")]
            assert len(cats) == 1


def test_references_to_the_term_are_renamed_too(resolver):
    """A relation pointing at `Necrosis` has to point at the sense that abstract
    used, or the split leaves dangling targets."""
    data = {
        "1": {"entities": {"Necrosis": {"is_a: MaterialEntity": 1.0},
                           "Eschar": {"has_part: Necrosis": 1.0}}},
        "2": {"entities": {"Necrosis": {"is_a: Process": 1.0}}},
    }
    s = _store(data)
    s.split_irreconcilable_terms(resolver)
    ents = {e: a for rec in s.dict.values() for e, a in rec["entities"].items()}
    assert "has_part: Necrosis Material Entity" in ents["Eschar"]


def test_a_reconcilable_conflict_is_left_alone(resolver):
    """`Process` and `ProcessBoundary` agree on `Occurrent`: one concept at two
    granularities, not two concepts. Reconciliation handles it, not splitting."""
    data = {"1": {"entities": {"Closure": {"is_a: Process": 1.0}}},
            "2": {"entities": {"Closure": {"is_a: ProcessBoundary": 1.0}}}}
    s = _store(data)
    rep = s.split_irreconcilable_terms(resolver)
    assert rep["split"] == {}
    assert {e for rec in s.dict.values() for e in rec["entities"]} == {"Closure"}


def test_a_consistently_typed_term_is_untouched(resolver):
    data = {"1": {"entities": {"Wound": {"is_a: MaterialEntity": 1.0}}},
            "2": {"entities": {"Wound": {"is_a: MaterialEntity": 1.0}}}}
    s = _store(data)
    s.split_irreconcilable_terms(resolver)
    assert {e for rec in s.dict.values() for e in rec["entities"]} == {"Wound"}


def test_a_mention_with_no_category_is_left_and_reported(resolver):
    """Guessing a sense for an untyped mention would invent evidence."""
    data = dict(NECROSIS)
    data["3"] = {"entities": {"Necrosis": {"part_of: Skin": 1.0}}}
    s = _store(data)
    rep = s.split_irreconcilable_terms(resolver)
    assert rep["unsensed"].get("Necrosis") == 1
    assert "Necrosis" in {e for rec in s.dict.values() for e in rec["entities"]}


def test_the_rebuilt_triples_keep_the_stores_format(resolver):
    """split(":", 1) leaves the separator's space on the target, so re-joining
    naively produced "is_a:  Process" — a key nothing downstream matches."""
    s = _store(NECROSIS)
    s.split_irreconcilable_terms(resolver)
    for rec in s.dict.values():
        for _, attrs in rec["entities"].items():
            for triple in attrs:
                assert ":  " not in triple, triple
                assert triple == triple.strip()


# ── what is not a sense ─────────────────────────────────────────────────────

def test_a_coarse_category_is_not_a_sense(resolver):
    """`Continuant` and `Occurrent` are the model retreating up the tree, not a
    meaning. Splitting on them gave "complications Continuant" beside three real
    senses — a class that asserts nothing."""
    data = {
        "1": {"entities": {"Complications": {"is_a: MaterialEntity": 1.0}}},
        "2": {"entities": {"Complications": {"is_a: Process": 1.0}}},
        "3": {"entities": {"Complications": {"is_a: Continuant": 1.0}}},
        "4": {"entities": {"Complications": {"is_a: Occurrent": 1.0}}},
    }
    s = _store(data)
    rep = s.split_irreconcilable_terms(resolver)
    assert set(rep["split"]["Complications"]) == {"MaterialEntity", "Process"}


def test_a_term_typed_only_coarsely_is_still_considered(resolver):
    """Dropping coarse categories must not empty the set and hide the conflict."""
    data = {"1": {"entities": {"Thing": {"is_a: Continuant": 1.0}}},
            "2": {"entities": {"Thing": {"is_a: Occurrent": 1.0}}}}
    s = _store(data)
    rep = s.split_irreconcilable_terms(resolver)
    assert set(rep["split"]["Thing"]) == {"Continuant", "Occurrent"}


def test_labels_are_normalised_so_one_sense_is_one_class(resolver):
    """Store keys arrive in whatever case the abstract used; without normalising
    the whole label, "necrosis" and "Necrosis" yield two classes for one sense."""
    data = {"1": {"entities": {"necrosis": {"is_a: MaterialEntity": 1.0}}},
            "2": {"entities": {"necrosis": {"is_a: Process": 1.0}}}}
    s = _store(data)
    rep = s.split_irreconcilable_terms(resolver)
    assert set(rep["split"]["Necrosis"].values()) == {
        "Necrosis Material Entity", "Necrosis Process"}


def test_case_variants_of_one_term_are_one_conflict(resolver):
    """The split grouped by raw store key while the hierarchy groups by
    normalised name, so "granulation" carrying MaterialEntity and "Granulation"
    carrying Process each looked consistent — and the term reached the hierarchy
    irreconcilable and unsplit. Rule 13: normalise both sides."""
    data = {"1": {"entities": {"granulation": {"is_a: MaterialEntity": 1.0}}},
            "2": {"entities": {"Granulation": {"is_a: Process": 1.0}}}}
    s = _store(data)
    rep = s.split_irreconcilable_terms(resolver)
    assert set(rep["split"]["Granulation"].values()) == {
        "Granulation Material Entity", "Granulation Process"}
    names = {e for rec in s.dict.values() for e in rec["entities"]}
    assert names == {"Granulation Material Entity", "Granulation Process"}
