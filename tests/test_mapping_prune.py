"""The term mapping never forgot, and that was doing damage quietly.

Measured 2026-09-06: the file held 26625 entries against a store of 3727 terms.
The excess was two different problems wearing one costume.

24441 were IDENTITY entries — a term mapped to itself, which `get()` already does
for any unmapped term. They changed nothing, but they were 92% of the file, and
they are the reason the mapping looked like an unreviewable 26k artifact instead
of the ~200 real decisions it contains. `review_mapping()` was never run over it
by anyone; that number is why.

1969 of the 2184 non-identity entries pointed at a canonical that no longer
exists anywhere — `-125 mmHg -> -125 mm Hg`, `18% -> 18`. Both ends had been
cleaned out of the store builds ago. An entry like that is not merely useless: if
a later abstract reintroduces the term, it renames it onto a target that exists
in neither the store nor the ontology.

What is NOT stale is an entry whose term is gone but whose canonical is alive —
that is the normal state after run_apply_mapping, and the entry has to survive so
the same normalisation happens next time the term appears.
"""
import pytest

from conftest import memory_mapper
from wound_ontology.mappers.term_mapper import TermMapper


def _mapper(data):
    """The real TermMappingAndGate over an in-memory file — see tests/conftest.py."""
    return memory_mapper(data)


def test_identity_entries_are_dropped():
    m = _mapper({"wound": "wound", "wounds": "Wound", "Wound": "Wound"})
    rep = m.prune(live_terms={"Wound"})
    assert rep["identity"] == 2
    assert m.mapping == {"wounds": "Wound"}


def test_an_entry_whose_target_is_gone_is_dropped():
    m = _mapper({"18%": "18", "-125 mmHg": "-125 mm Hg"})
    rep = m.prune(live_terms={"Wound"})
    assert rep["dead"] == 2
    assert m.mapping == {}


def test_an_applied_mapping_survives_even_though_its_term_is_gone():
    """After run_apply_mapping the term is absent from the store BY DESIGN. If
    that were grounds for removal the prune would erase the entire mapping."""
    m = _mapper({"wounds": "Wound"})
    rep = m.prune(live_terms={"Wound"})
    assert rep == {"identity": 0, "dead": 0, "kept": 1}
    assert m.mapping == {"wounds": "Wound"}


def test_an_ontology_label_counts_as_a_live_target():
    """Anchor mappings point at a class, not at a store term. The class is not in
    the store and must not be mistaken for a dead target."""
    m = _mapper({"granulation": "Granulation process"})
    rep = m.prune(live_terms=set(), ontology_labels={"Granulation process"})
    assert rep["dead"] == 0
    assert m.mapping == {"granulation": "Granulation process"}


def test_a_chain_that_reaches_a_live_term_is_kept():
    m = _mapper({"A": "B", "B": "C"})
    rep = m.prune(live_terms={"C"})
    assert rep["dead"] == 0
    assert m.mapping == {"A": "B", "B": "C"}


def test_a_chain_that_reaches_nothing_is_dropped():
    m = _mapper({"A": "B", "B": "C"})
    rep = m.prune(live_terms={"Z"})
    assert rep["dead"] == 2
    assert m.mapping == {}


def test_a_cycle_does_not_hang_the_prune():
    m = _mapper({"A": "B", "B": "A"})
    assert m.prune(live_terms={"Z"})["dead"] == 2


def test_dry_run_reports_without_removing():
    m = _mapper({"wound": "wound", "18%": "18"})
    rep = m.prune(live_terms={"Wound"}, dry_run=True)
    assert rep == {"identity": 1, "dead": 1, "kept": 0}
    assert len(m.mapping) == 2


def test_the_build_no_longer_writes_identity_entries():
    """92% of the file was no-ops written one per canonical, every build."""
    import numpy as np

    class _Persist:
        def __init__(self): self.data = {}
        def add_batch(self, entries, metadata=None): self.data.update(entries)
        def is_refused(self, term, canonical): return None
        def remove(self, *t):
            n = sum(1 for x in t if self.data.pop(x, None) is not None)
            return n

    class _Emb:
        def embed(self, terms):
            out = np.zeros((len(terms), 2))
            for i, t in enumerate(terms):
                out[i, 0 if "wound" in t.lower() else 1] = 1.0
            return out

    mapper = TermMapper(_Persist(), name="t")
    result = mapper.build_from_embeddings(
        ["wound", "wounds", "granulation"], _Emb(), similarity_threshold=0.95)

    # The persisted file carries merges only...
    assert all(t != c for t, c in mapper.mapping.items()), mapper.mapping
    # ...while the return value still answers for every term it was given, so a
    # caller can ask what happened to one without inferring it from an absence.
    assert set(result) == {"wound", "wounds", "granulation"}
    assert result["granulation"] == "granulation"


def test_a_curator_refusal_survives_the_next_build():
    """It did not, and that is why the mapping now holds records rather than a
    flat dict. `withdraw` deleted the entry and recorded nothing, so clustering
    re-proposed the merge on the next run and the adjudication cache re-approved
    it from memory: the guard's refusals survived a rebuild, the curator's did
    not (rule 33 — a decision is a verdict in the record, never a deletion)."""
    import numpy as np

    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    class _DM:
        def __init__(self): self.saved = None
        def load_latest_json(self, name): return {}
        def save_as_json(self, data, name): self.saved = data

    class _Emb:
        def embed(self, terms):
            out = np.zeros((len(terms), 2))
            for i, t in enumerate(terms):
                out[i, 0 if "wound" in t.lower() else 1] = 1.0
            return out

    tm = TermMappingAndGate(_DM())
    mapper = TermMapper(tm, name="t")
    mapper.build_from_embeddings(["wounds", "wound"], _Emb(),
                                 similarity_threshold=0.95, frequencies={"wound": 9})
    assert mapper.mapping == {"wounds": "wound"}

    mapper.refuse("wounds", "wound", reason="not the same concept here")
    assert mapper.mapping == {}

    # the same build again: SapBERT proposes the same merge, and it must not stand
    mapper.build_from_embeddings(["wounds", "wound"], _Emb(),
                                 similarity_threshold=0.95, frequencies={"wound": 9})
    assert mapper.mapping == {}, "the curator's refusal was overwritten by a rebuild"
    assert tm.is_refused("wounds", "wound")["by"] == "curator"


def test_a_refusal_is_about_the_pair_not_the_term():
    """`materials` refused onto `material entity` must still be free to map onto
    something else."""
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    class _DM:
        def load_latest_json(self, name): return {}
        def save_as_json(self, data, name): pass

    tm = TermMappingAndGate(_DM())
    mapper = TermMapper(tm, name="t")
    mapper.refuse("materials", "material entity", reason="a BFO category name")
    tm.add("materials", "Wound dressing material")
    assert mapper.mapping == {"materials": "Wound dressing material"}
    assert tm.is_refused("materials", "material entity")
    assert tm.is_refused("materials", "Wound dressing material") is None


def test_the_old_flat_file_still_loads():
    """The file on disk is `term -> canonical` until something saves records over
    it, and a migration that needs remembering is a migration that gets
    forgotten."""
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    class _DM:
        def load_latest_json(self, name): return {"wounds": "Wound", "ulcers": "Ulcer"}
        def save_as_json(self, data, name): self.written = data

    dm = _DM()
    tm = TermMappingAndGate(dm)
    assert tm.data == {"wounds": "Wound", "ulcers": "Ulcer"}
    tm.judge("wounds", "Wound", pass1={"verdict": "same_class", "reason": "plural"})
    tm.save()
    assert dm.written["wounds"] == {
        "to": "Wound",
        "pairs": {"Wound": {"pass1": {"verdict": "same_class", "reason": "plural"}}}}
