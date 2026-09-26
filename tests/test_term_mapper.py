import numpy as np
import pandas as pd
import pytest

from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
from wound_ontology.mappers.term_mapper import TermMapper


INITIAL_MAPPING = {
    "chronic wound": "wound",
    "acute wound": "wound",
    "granulation": "granulation",
}


class MockDM:
    def __init__(self, mapping=None):
        self.mapping = dict(INITIAL_MAPPING if mapping is None else mapping)
        self.saved = []

    def load_latest_json(self, _):
        return dict(self.mapping)

    def save_as_json(self, data, file_name):
        self.saved.append((dict(data), file_name))


class FakeEmbedder:
    """Returns pre-set L2-normalised embeddings for unit tests."""

    def __init__(self, embeddings: dict[str, list[float]]):
        self._raw = embeddings

    def embed(self, texts: list[str]) -> np.ndarray:
        dim = len(next(iter(self._raw.values())))
        vecs = []
        for t in texts:
            v = np.array(self._raw.get(t, [0.0] * dim), dtype=float)
            norm = np.linalg.norm(v)
            vecs.append(v / norm if norm > 0 else v)
        return np.vstack(vecs)


@pytest.fixture
def dm():
    return MockDM()


@pytest.fixture
def term_mapping(dm):
    return TermMappingAndGate(dm, "term_mapping")


@pytest.fixture
def mapper(term_mapping):
    return TermMapper(term_mapping=term_mapping, name="test_mapper")


# ── Mapping access ────────────────────────────────────────────────────────────

def test_standards_are_unique_and_sorted(mapper):
    assert mapper.standards == ["granulation", "wound"]


def test_originals_are_sorted(mapper):
    assert mapper.originals == ["acute wound", "chronic wound", "granulation"]


def test_map_known_term(mapper):
    assert mapper.map("chronic wound") == "wound"


def test_map_unknown_term_passthrough(mapper):
    assert mapper.map("unknown term") == "unknown term"


def test_apply_renames_index_and_columns_without_mutating_original(mapper):
    df = pd.DataFrame(
        [[1, 0], [0, 1]],
        index=["chronic wound", "unknown entity"],
        columns=["acute wound", "unknown term"],
    )

    result = mapper.apply(df)

    assert "wound" in result.index
    assert "wound" in result.columns
    assert "unknown entity" in result.index
    assert "unknown term" in result.columns
    assert "chronic wound" not in result.index
    assert "acute wound" not in result.columns
    assert list(df.index) == ["chronic wound", "unknown entity"]
    assert list(df.columns) == ["acute wound", "unknown term"]


def test_empty_term_mapping_passthrough():
    dm = MockDM({})
    tm = TermMappingAndGate(dm, "empty_term_mapping")
    mapper = TermMapper(term_mapping=tm, name="empty")
    df = pd.DataFrame([[1, 0]], columns=["term_a", "term_b"])

    assert list(mapper.apply(df).columns) == ["term_a", "term_b"]
    assert mapper.standards == []
    assert mapper.originals == []


def test_term_mapper_has_default_name(dm):
    tm = TermMappingAndGate(dm, "terms")
    mapper = TermMapper(term_mapping=tm)

    assert mapper.__class__ is TermMapper
    assert mapper.name == "Term mapper"


# ── build_from_embeddings ─────────────────────────────────────────────────────

def _make_mapper(data=None):
    dm = MockDM(data or {})
    tm = TermMappingAndGate(dm, "t")
    return TermMapper(term_mapping=tm, name="t")


def test_build_from_embeddings_merges_near_identical_surface_forms():
    """Case and hyphen variants of the same term collapse to one canonical."""
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "Wound Healing":  [1.0, 0.0, 0.0],
        "wound healing":  [1.0, 0.0, 0.0],
        "full-thickness": [0.0, 1.0, 0.0],
        "full thickness": [0.0, 1.0, 0.0],
    })
    freq = {"Wound Healing": 10, "wound healing": 5, "full-thickness": 8, "full thickness": 3}

    result = mapper.build_from_embeddings(
        list(freq.keys()), embedder, similarity_threshold=0.95, frequencies=freq
    )

    assert result["wound healing"] == result["Wound Healing"]
    assert result["Wound Healing"] == "Wound Healing"
    assert result["full thickness"] == result["full-thickness"]
    assert result["full-thickness"] == "full-thickness"


def test_build_from_embeddings_pre_merges_trailing_abbreviations():
    """Terms identical after normalize_term merge without SapBERT (step 0)."""
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "Systemic Sclerosis (SSc)":          [1.0, 0.0],
        "Split-Thickness Skin Graft (STSG)": [0.0, 1.0],
    })
    freq = {
        "Systemic Sclerosis (SSc)":          10,
        "Systemic Sclerosis":                 5,
        "Split-Thickness Skin Graft (STSG)":  8,
        "Split-thickness skin graft (STSG)":  3,
    }

    result = mapper.build_from_embeddings(list(freq.keys()), embedder, frequencies=freq)

    assert result["Systemic Sclerosis"] == result["Systemic Sclerosis (SSc)"]
    assert result["Split-thickness skin graft (STSG)"] == result["Split-Thickness Skin Graft (STSG)"]


def test_build_from_embeddings_keeps_distinct_terms_separate():
    """Orthogonal embeddings never merge regardless of string similarity."""
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "wound":      [1.0, 0.0, 0.0],
        "laceration": [0.0, 1.0, 0.0],
        "necrosis":   [0.0, 0.0, 1.0],
    })

    result = mapper.build_from_embeddings(
        ["wound", "laceration", "necrosis"], embedder, similarity_threshold=0.95
    )

    assert result["wound"]      == "wound"
    assert result["laceration"] == "laceration"
    assert result["necrosis"]   == "necrosis"


def test_build_from_embeddings_generic_term_not_merged_without_string_match():
    """Generic single-word terms (wound, pain…) require string_sim ≥ 0.90."""
    mapper = _make_mapper()
    v = np.array([1.0, 0.01, 0.0])
    v /= np.linalg.norm(v)
    embedder = FakeEmbedder({
        "wound": v.tolist(),
        "pain":  [1.0, 0.0, 0.0],
    })

    result = mapper.build_from_embeddings(
        ["wound", "pain"], embedder, similarity_threshold=0.95
    )

    assert result["wound"] != result["pain"]


def test_build_from_embeddings_canonicals_map_to_themselves():
    """Every canonical in the output must map to itself."""
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "A": [1.0, 0.0],
        "B": [1.0, 0.0],
        "C": [0.0, 1.0],
    })

    result = mapper.build_from_embeddings(
        ["A", "B", "C"], embedder, similarity_threshold=0.95
    )

    for term, canonical in result.items():
        assert result[canonical] == canonical, f"Canonical '{canonical}' does not map to itself"


def test_build_from_embeddings_single_linkage_would_merge_complete_linkage_does_not():
    """
    Classic Union-Find failure case: A↔B valid, B↔C valid, but A↔C invalid.
    Complete-linkage must keep A and C in separate clusters.

    Geometry (3D, L2-normalised):
      B = [1, 0, 0]          — the bridge
      A = [0.95,  0.312, 0]  — cos(A,B) = 0.95  (at merge threshold)
      C = [0.95, -0.312, 0]  — cos(C,B) = 0.95  (at merge threshold)
      cos(A,C) = 0.95²-0.312² ≈ 0.805  (below threshold → no direct edge)
    """
    mapper = _make_mapper()
    embedder = FakeEmbedder({
        "term_a": [0.95,  0.312, 0.0],
        "term_b": [1.0,   0.0,   0.0],
        "term_c": [0.95, -0.312, 0.0],
    })

    result = mapper.build_from_embeddings(
        ["term_a", "term_b", "term_c"], embedder, frequencies={}
    )

    ab_merged = result.get("term_a", "term_a") == result.get("term_b", "term_b")
    bc_merged = result.get("term_b", "term_b") == result.get("term_c", "term_c")
    assert ab_merged or bc_merged, "At least one valid edge must produce a merge"

    assert result.get("term_a", "term_a") != result.get("term_c", "term_c"), \
        "Complete-linkage must not merge term_a and term_c via term_b as bridge"


# ── CSV review workflow (MappingCleaner) ──────────────────────────────────────

def test_export_review_csv_writes_low_confidence_metadata(mapper, tmp_path):
    from wound_ontology.mappers.mapping_cleaner import MappingCleaner
    # Confidence and method live ON the record now (rule 37); `metadata` is a
    # view over them rather than a dict of its own that vanished with the run.
    mapper._term_mapping._records = {
        "needs review": {"to": "candidate", "confidence": 0.6, "method": "llm",
                         "refused": {}},
        "accepted":     {"to": "wound", "confidence": 0.95, "method": "similarity",
                         "refused": {}},
    }
    mapper._term_mapping._dirty()
    cleaner = MappingCleaner(mapper)
    path = tmp_path / "review.csv"

    cleaner.export_review_csv(str(path))

    df = pd.read_csv(path)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["term"] == "needs review"
    assert row["suggested_standard"] == "candidate"
    assert row["confidence"] == 0.6
    assert row["method"] == "llm"
    assert pd.isna(row["reviewed_standard"])
    assert pd.isna(row["notes"])


def test_import_review_csv_overrides_mapping_and_marks_manual(mapper, dm, tmp_path):
    from wound_ontology.mappers.mapping_cleaner import MappingCleaner
    cleaner = MappingCleaner(mapper)
    path = tmp_path / "review.csv"
    pd.DataFrame([{
        "term":               "needs review",
        "suggested_standard": "candidate",
        "confidence":         0.6,
        "method":             "llm",
        "reviewed_standard":  "manual standard",
        "notes":              "reviewed",
    }]).to_csv(path, index=False)

    cleaner.import_review_csv(str(path))

    assert mapper.mapping["needs review"] == "manual standard"
    assert mapper._term_mapping.metadata["needs review"] == {
        "standard":   "manual standard",
        "confidence": 1.0,
        "method":     "manual",
    }
    assert dm.saved[-1][1] == "term_mapping"


# ── the similarity matrix is computed in blocks ──────────────────────────────

class _TinyEmbedder:
    """Unit vectors: terms sharing a first letter are identical, so they cluster."""

    def embed(self, terms):
        import numpy as np
        letters = sorted({t[0].lower() for t in terms})
        out = np.zeros((len(terms), len(letters)), dtype="float32")
        for i, t in enumerate(terms):
            out[i, letters.index(t[0].lower())] = 1.0
        return out


def test_a_pair_straddling_two_blocks_is_still_found(monkeypatch):
    """The whole matrix is n^2 float32 and n was 90,435 -- 32.7 GB on a 17 GB
    machine, so it is computed a block of rows at a time. The risk that
    introduces is a pair whose two terms fall in different blocks."""
    import wound_ontology.mappers.term_mapper as tm
    monkeypatch.setattr(tm, "SIMILARITY_BLOCK", 1)
    from conftest import memory_mapper

    m = memory_mapper()
    terms = ["alpha one", "alpha two", "alpha three", "beta one", "beta two"]
    m.build_from_embeddings(terms, embedder=_TinyEmbedder(),
                            similarity_threshold=0.95,
                            frequencies={t: 1 for t in terms})
    canonicals = {m.mapping.get(t, t) for t in terms}
    assert len(canonicals) == 2, f"expected one canonical per letter, got {canonicals}"


def test_the_block_size_does_not_change_the_answer(monkeypatch):
    import wound_ontology.mappers.term_mapper as tm
    from conftest import memory_mapper

    terms = ["alpha one", "alpha two", "alpha three", "beta one", "beta two"]
    answers = []
    for size in (1, 2, 1000):
        monkeypatch.setattr(tm, "SIMILARITY_BLOCK", size)
        m = memory_mapper()
        m.build_from_embeddings(terms, embedder=_TinyEmbedder(),
                                similarity_threshold=0.95,
                                frequencies={t: 1 for t in terms})
        answers.append(dict(m.mapping))
    assert answers[0] == answers[1] == answers[2]


class _AngleEmbedder:
    """Unit vectors at chosen angles, so every pairwise cosine is exact."""

    def __init__(self, angles):
        self.angles = angles

    def embed(self, terms):
        import math

        import numpy as np
        return np.array([[math.cos(self.angles[t]), math.sin(self.angles[t])]
                         for t in terms], dtype="float32")


def test_the_merge_order_follows_the_score():
    """Complete linkage merges the strongest pair first, and which pair that is
    decides the answer.

    `beta thing`-`gamma thing` at 0.990 and `alpha thing`-`beta thing` at 0.961
    are both valid; `alpha thing`-`gamma thing` at 0.912 is not. Whichever
    merges first excludes the third. Keeping the score per pair is what picks
    the right one: with the scores dropped the sort falls back to set order,
    which offers the WEAKER pair first and merges alpha instead of gamma.
    """
    import math

    from conftest import memory_mapper

    # The STRONGER pair is the second one, (1, 2). Set iteration would offer
    # (0, 1) first, so a sort with the scores dropped merges the weaker pair
    # and leaves a different term out.
    angles = {"alpha thing": 0.0,
              "beta thing": math.radians(16.1),     # cos to alpha ≈ 0.961
              "gamma thing": math.radians(24.2)}    # to beta ≈ 0.990, alpha ≈ 0.912
    m = memory_mapper()
    m.build_from_embeddings(list(angles), embedder=_AngleEmbedder(angles),
                            similarity_threshold=0.95,
                            frequencies={t: 1 for t in angles})
    # alpha and beta merge; gamma is left out, because joining would need
    # alpha-gamma and that pair is below the threshold. Which of the two is the
    # canonical is `canonical_rank`'s business, not this test's.
    assert m.mapping.get("alpha thing") in (None, "alpha thing"), \
        "alpha merged, so the weaker pair was taken first"
    beta_gamma = {m.mapping.get(t, t) for t in ("beta thing", "gamma thing")}
    assert len(beta_gamma) == 1, f"beta and gamma did not merge: {beta_gamma}"
    assert "alpha thing" not in beta_gamma


def test_a_cluster_whose_canonical_is_minted_still_maps_it_to_itself(monkeypatch):
    """`_canonical` may name a cluster something no member is called.

    Rule 23a: the name is singular whether or not the corpus said it that way.
    When no member both shares the best member's fold and reads as singular,
    the canonical is SPELLED rather than chosen -- and it is then in no
    cluster, so it had no entry of its own. `assignment[c]` in the forest
    assertion died with a KeyError on the very canonical it was checking,
    after fifty minutes of embedding.

    HONEST LIMIT: this does not reproduce the crash. Every route I could
    construct through the public interface makes the minted spelling a
    pre-merge canonical too, which puts it in the clustering and gives it an
    entry. The live trigger is a disagreement between `singularize` and
    `singular_spelling` on one corpus term, and I could not get the clustered
    path to mint something the pre-merge path had not already produced. So
    what is pinned here is the INVARIANT -- every canonical maps to itself --
    and the one-line `setdefault` that guarantees it; the crash itself is
    witnessed by the traceback in output/mapping_build_2026-09-26.log, not by
    a test.
    """
    import wound_ontology.mappers.term_mapper as tm
    from conftest import memory_mapper

    monkeypatch.setattr(tm, "singularize", lambda w: w + "x")       # nothing is singular
    monkeypatch.setattr(tm, "singular_spelling", lambda label: "minted canonical")

    terms = ["alpha one", "alpha two"]
    m = memory_mapper()
    m.build_from_embeddings(terms, embedder=_TinyEmbedder(),
                            similarity_threshold=0.95,
                            frequencies={t: 1 for t in terms})
    assert set(m.mapping.values()) == {"minted canonical"}
    assert "minted canonical" not in terms, \
        "the canonical has to be MINTED for this to test anything"


class _StableEmbedder:
    """A fixed-width vector per term, the same one every time.

    `_TinyEmbedder`'s width depends on the term list, which is fine inside one
    build and useless for testing a cache that outlives the list.
    """

    DIM = 16

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, terms):
        import hashlib

        import numpy as np

        self.calls.append(list(terms))
        out = np.zeros((len(terms), self.DIM), dtype="float32")
        for i, t in enumerate(terms):
            digest = hashlib.sha256(t.encode()).digest()
            v = np.frombuffer(digest[: self.DIM], dtype="uint8").astype("float32")
            out[i] = v / np.linalg.norm(v)
        return out


# ── the pre-merge runs until the spellings stop moving ───────────────────────

def test_the_folded_pre_merge_runs_until_the_spellings_stop_moving():
    """One pass over the folded forms is not enough, and the corpus proved it.

    `multi-drug resistant bacterias` folds to `multi drug resistant bacteria`
    and mints `multi-drug resistant bacteria`, whose OWN fold is
    `multi drug resistant bacterium` -- the key of a different group, the one
    holding `multi-drug-resistant bacterium`. After one pass those are two
    terms, and they went to SapBERT as two terms. The embedder here gives
    every distinct string an unrelated vector, so nothing merges by cosine:
    whatever ends up together got there by folding.
    """
    from conftest import memory_mapper

    terms = ["multi-drug resistant bacterias", "multi-drug-resistant bacterium"]
    m = memory_mapper()
    m.build_from_embeddings(terms, embedder=_StableEmbedder(),
                            similarity_threshold=0.95,
                            frequencies={"multi-drug-resistant bacterium": 6,
                                         "multi-drug resistant bacterias": 1})
    assert m.map("multi-drug resistant bacterias") == "multi-drug-resistant bacterium"


def test_a_term_folded_twice_lands_on_the_final_spelling_not_the_intermediate():
    """Transitivity. A -> B in round 1 and B -> C in round 2 means A -> C.

    Without the chain resolution the mapping says `bacterias -> bacteria`, a
    spelling no later step knows about: it is not a canonical, nothing points
    at it, and the term is stranded one hop short of where it belongs.
    """
    from conftest import memory_mapper

    terms = ["multi-drug resistant bacterias", "multi-drug-resistant bacterium"]
    m = memory_mapper()
    m.build_from_embeddings(terms, embedder=_StableEmbedder(),
                            similarity_threshold=0.95,
                            frequencies={"multi-drug-resistant bacterium": 6,
                                         "multi-drug resistant bacterias": 1})
    assert m.map("multi-drug resistant bacterias") != "multi-drug resistant bacteria"
    assert m.map("multi-drug resistant bacteria") == "multi-drug-resistant bacterium", \
        "the intermediate spelling has to point at the survivor as well"


# ── the vector store ─────────────────────────────────────────────────────────

def test_the_vector_store_embeds_only_the_terms_it_has_not_seen(_vector_store_stays_out_of_data_cache):
    """Fifty minutes of embedding must survive a term list that moved.

    The first version of this cache hashed the whole list, so dropping 622
    spellings out of 90,435 missed it and re-embedded the 89,813 that had not
    changed. The store is keyed by term.
    """
    from conftest import memory_mapper

    e = _StableEmbedder()
    first = ["alpha one", "beta one"]
    memory_mapper().build_from_embeddings(first, embedder=e,
                                          similarity_threshold=0.95,
                                          frequencies={t: 1 for t in first})
    second = ["beta one", "gamma one"]
    memory_mapper().build_from_embeddings(second, embedder=e,
                                          similarity_threshold=0.95,
                                          frequencies={t: 1 for t in second})
    assert e.calls[0] == first
    assert e.calls[1] == ["gamma one"], \
        f"the second build re-embedded terms it already had: {e.calls[1]}"


def test_a_vector_store_whose_rows_and_names_disagree_is_rebuilt_not_trusted(
        _vector_store_stays_out_of_data_cache, capsys):
    """A row/name mismatch would attach one term's vector to another's name.

    That is a wrong merge no one would ever see, so the store is thrown away
    and said out loud rather than half-believed.
    """
    import json

    import numpy as np

    from conftest import memory_mapper

    sandbox = _vector_store_stays_out_of_data_cache
    np.save(sandbox / "sapbert_vectors.npy", np.zeros((3, _StableEmbedder.DIM), "float32"))
    (sandbox / "sapbert_vectors_terms.json").write_text(json.dumps(["alpha one", "beta one"]))

    e = _StableEmbedder()
    terms = ["alpha one", "beta one"]
    memory_mapper().build_from_embeddings(terms, embedder=e,
                                          similarity_threshold=0.95,
                                          frequencies={t: 1 for t in terms})
    out = capsys.readouterr().out
    assert "inconsistent" in out, "a broken store was used without a word"
    assert e.calls == [terms], "the broken store was trusted for some terms"


# ── a canonical nobody embedded ──────────────────────────────────────────────

def _never_settles(monkeypatch):
    """A normaliser that oscillates, so the fold pre-merge cannot reach a fixed
    point and step 3 is left with a spelling that was never embedded.

    This is the ONLY way into that branch. With the real normalisers the fixed
    point guarantees `singular_spelling(c) == c` for every canonical, so the
    clustered path never mints -- measured on the 2026-09-26 corpus: 0 of
    89,813. The branch is still reached in anger the moment those two
    functions disagree about one term, which is what killed two builds, so it
    is pinned with a normaliser that disagrees on purpose.
    """
    import wound_ontology.mappers.term_mapper as tm

    cycle = {"alpha one": "alpha uno", "alpha uno": "alpha one"}
    monkeypatch.setattr(tm, "singularize", lambda w: w + "x")   # nothing reads as singular
    monkeypatch.setattr(tm, "singular_spelling", lambda label: cycle.get(label, label))


def test_a_pre_merge_that_never_settles_says_so_and_still_finishes(monkeypatch, capsys):
    from conftest import memory_mapper

    _never_settles(monkeypatch)
    terms = ["alpha one", "beta"]
    m = memory_mapper()
    m.build_from_embeddings(terms, embedder=_StableEmbedder(),
                            similarity_threshold=0.95,
                            frequencies={t: 1 for t in terms})
    out = capsys.readouterr().out
    assert "did not settle" in out, "a pre-merge that never converged passed in silence"
    assert "fold in a cycle" in out, "terms dropped from the mapping without a word"


def test_a_canonical_nobody_embedded_is_scored_against_the_term_it_came_from(monkeypatch):
    """`_canonical` may name a cluster something no member is called.

    Rule 23a: the name is singular whether or not the corpus said it that way.
    The minted spelling is then in no cluster and has no embedding, and two
    builds died on it -- first `assignment[c]` in the forest assertion, then
    `term_to_idx[term]` in the metadata step, each after fifty minutes. The
    mapping is still recorded, with a confidence measured against the member
    the spelling was minted from, because that member IS embedded.
    """
    from conftest import memory_mapper

    _never_settles(monkeypatch)
    terms = ["alpha one", "beta"]
    m = memory_mapper()
    m.build_from_embeddings(terms, embedder=_StableEmbedder(),
                            similarity_threshold=0.95,
                            frequencies={t: 1 for t in terms})
    assert m.map("alpha one") == "alpha uno"
    assert "alpha uno" not in terms, "the canonical has to be MINTED to test anything"
    meta = m._term_mapping.metadata["alpha one"]
    assert meta["confidence"] == pytest.approx(1.0)
    assert meta["method"] == "sapbert_cluster"
