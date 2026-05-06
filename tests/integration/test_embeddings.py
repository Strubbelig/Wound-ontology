import pytest
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


# ----------------------------
# Helpers
# ----------------------------

async def embed_terms(llm, terms):
    """
    Wrapper to get embeddings as numpy array.
    """
    embs = await llm.create_embeddings(terms)
    return np.array(embs)


def sim(a, b):
    """
    Cosine similarity between two vectors.
    """
    return float(cosine_similarity([a], [b])[0][0])


# ----------------------------
# Fixtures
# ----------------------------

@pytest.fixture
def embedding_model():
    """
    You should replace this with your actual LLM client.
    Must expose:
        await create_embeddings(list[str]) -> list[list[float]]
    """
    from wound_ontology.embedding.embedder import Embedder
    return Embedder()


# ----------------------------
# Tests
# ----------------------------

@pytest.mark.asyncio
async def test_semantic_similarity(embedding_model):
    """
    Similar medical concepts should be close.
    """
    terms = [
        "heart attack",
        "myocardial infarction"
    ]

    embs = await embed_terms(embedding_model, terms)

    score = sim(embs[0], embs[1])

    assert score > 0.7, f"Expected high similarity, got {score}"


@pytest.mark.asyncio
async def test_semantic_dissimilarity(embedding_model):
    """
    Completely unrelated terms should be far apart.
    """
    terms = [
        "wound healing",
        "car engine",
    ]

    embs = await embed_terms(embedding_model, terms)

    score = sim(embs[0], embs[1])

    assert score < 0.5, f"Expected low similarity, got {score}"


@pytest.mark.asyncio
async def test_abbreviation_handling(embedding_model):
    """
    Critical for medical domain: abbreviations.
    """
    terms = [
        "MI",
        "myocardial infarction"
    ]

    embs = await embed_terms(embedding_model, terms)

    score = sim(embs[0], embs[1])

    # SapBERT handles abbreviations via training data context, not pure string match.
    # Raw cosine on CPU lands around 0.75–0.80 for known abbrev pairs.
    # Actual abbreviation merging in build_from_embeddings uses _is_abbreviation_pair(),
    # which is independent of this score.
    assert score > 0.7, f"Abbreviation not recognized well, got {score}"


@pytest.mark.asyncio
async def test_variation_consistency(embedding_model):
    """
    Same concept phrased differently should be very close.
    """
    terms = [
        "stage 3 pressure ulcer",
        "pressure ulcer stage III"
    ]

    embs = await embed_terms(embedding_model, terms)

    score = sim(embs[0], embs[1])

    assert score > 0.8, f"Variation inconsistency, got {score}"


@pytest.mark.asyncio
async def test_cluster_separation(embedding_model):
    """
    Positive pairs should be more similar than negative ones.
    This is more robust than absolute thresholds.
    """
    positive = [
        ("heart attack", "myocardial infarction"),           # ~0.78 empirical
        ("MI", "myocardial infarction"),                     # ~0.75 empirical
        ("stage 3 pressure ulcer", "pressure ulcer stage III"),  # ~0.85 empirical
        ("wound healing", "healing of a wound"),             # ~0.96 empirical
    ]

    negative = [
        ("heart attack", "banana"),
        ("ulcer", "car engine"),
        ("Rehabilitation Intervention", "Surgical Procedure"),
        ("Exercise-based Rehabilitation", "Flap-based Reconstruction"),
        ("Patellar Redislocation", "Surgical Procedure"),
        ("wound healing", "car engine"),
    ]

    pos_scores = []
    neg_scores = []

    for a, b in positive:
        embs = await embed_terms(embedding_model, [a, b])
        pos_scores.append(sim(embs[0], embs[1]))

    for a, b in negative:
        embs = await embed_terms(embedding_model, [a, b])
        neg_scores.append(sim(embs[0], embs[1]))

    assert min(pos_scores) > max(neg_scores), (
        f"Overlap detected: pos={pos_scores}, neg={neg_scores}"
    )


@pytest.mark.asyncio
async def test_embedding_stability(embedding_model):
    """
    Same input should produce consistent embeddings.
    """
    term = "myocardial infarction"

    emb1 = (await embed_terms(embedding_model, [term]))[0]
    emb2 = (await embed_terms(embedding_model, [term]))[0]

    score = sim(emb1, emb2)

    assert score > 0.99, f"Embedding not stable, got {score}"


@pytest.mark.asyncio
async def test_similarity_distribution_sanity(embedding_model):
    """
    Checks general spread of similarities.
    Helps detect broken embedding models.
    """
    terms = [
        "heart attack",
        "myocardial infarction",
        "pressure ulcer",
        "banana",
        "car engine"
    ]

    embs = await embed_terms(embedding_model, terms)

    sims = cosine_similarity(embs)

    # remove diagonal (self-similarity)
    mask = ~np.eye(len(terms), dtype=bool)
    values = sims[mask]

    mean_sim = float(np.mean(values))

    # sanity bounds (tune if needed)
    assert 0.2 < mean_sim < 0.8, f"Similarity distribution looks off: {mean_sim}"