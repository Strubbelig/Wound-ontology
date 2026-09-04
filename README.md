# Wound Ontology

An automated pipeline for building a wound-care ontology from PubMed literature using LLM extraction, Formal Concept Analysis (FCA), and OWL export.

## Overview

The pipeline fetches PubMed abstracts, extracts biomedical entities and relations via a large language model (Google Gemini), normalizes terminology, builds concept hierarchies, and exports a structured OWL ontology. BFO (Basic Formal Ontology) anchor classes ground entities in a top-level ontology.

```
PubMed abstracts
      ↓ LLM extraction
ConceptStore  ←  curated edges from WONT + MILD (e.g. Chronic Wound is_a Wound)
      ↓ normalize (TermMapper + Title Case)
ClassHierarchy  +  MereologicalHierarchy
      ↓ FCA on wound subtree (conceptually scaled by the hierarchy)
ConceptLattice  →  named superclasses  →  ClassHierarchy (merged)
      ↓
OWL export (RDF/XML)
```

## Project Structure

```
src/wound_ontology/
├── cache/
│   └── concept_store.py        # Central staging for all concept data
├── connectors/
│   ├── pubmed_connector.py     # PubMed abstract fetcher
│   ├── bfo_connector.py        # BFO anchor class loader
│   └── onto_connector.py       # Generic OWL connector
├── data_manager/
│   └── data_manager.py         # Versioned file persistence (JSON/CSV/Pickle)
├── export/
│   └── owl_exporter.py         # OWL/RDF-XML export via owlready2
├── fca/
│   ├── context_matrix.py       # Binary object×attribute FCA matrix
│   └── concept_lattice.py      # Concept lattice builder + LLM naming
├── hierarchies/
│   ├── base_hierarchy.py       # Abstract adjacency-matrix hierarchy
│   ├── class_hierarchy.py      # is_a (taxonomic) hierarchy
│   ├── mereological_hierarchy.py  # part_of hierarchy
│   └── fca_hierarchy.py        # Hierarchy derived from concept lattice
├── llm/
│   └── llm_client.py           # Gemini API client (extraction + naming)
├── mappers/
│   └── term_mapper.py          # Shared medical-term mapping (entities + targets)
└── orchestrator.py             # High-level pipeline orchestration
```

## Quickstart

### Prerequisites

- Python 3.11+
- Google Gemini API key
- NCBI Entrez email

### Installation

```bash
pip install -e .
```

### Environment

Create a `.env` file in the project root:

```
GOOGLE_API_KEY=your_gemini_key
ENTREZ_EMAIL=your@email.com
```

### Run the pipeline

```python
from wound_ontology.orchestrator import Orchestrator

pipeline = Orchestrator()

# 1. Fetch abstracts
pipeline.run_pubmed_search(["chronic wound healing", "surgical wound infection"], max_results_per_query=20)

# 2. Extract entities and relations
pipeline.run_extract_to_store(batch_size=10)

# 3. Build and review the shared term mapping
pipeline.run_build_term_mapping()
pipeline.mapping_cleaner.list_suspicious_mappings()
pipeline.mapping_cleaner.review_mappings()
pipeline.mapping_cleaner.apply(pipeline.store)

# 4. Reasoner gate — store relations (before anything consumes them)
pipeline.run_gate_store_relations()

# 5. Build hierarchies
#    Curated seed edges are read from WONT + MILD by default (they used to come
#    from a CSV, which has since been merged into those ontologies). Pass
#    predefined_df=<DataFrame> to override, or an empty one for no curated edges.
pipeline.run_build_hierarchies()

# 6. Reasoner gate — is_a edges (curated edges and the FCA lattice bypass the schema)
pipeline.run_gate_hierarchy_edges()

# 7. FCA — group wound entities by shared qualities
#    scale=True (default) applies conceptual scaling: each object gets its
#    superclasses as is_a: attributes and inherits their attributes, so the
#    lattice cannot order two entities against the curated hierarchy.
pipeline.run_fca(
    subtree_root="Wound",
    predicates=["has_quality", "part_of", "has_participant", "has_disposition", "inheres_in"],
)

# 8. Merge findings into WONT
#    Uses ground_truth_final.owl as the base: existing terms resolve to their
#    real IRIs (including through plurals, punctuation and stated synonyms),
#    imported classes resolve to BFO/MILD/OBI rather than being duplicated, and
#    only genuinely new terms are minted.
pipeline.run_extend_ground_truth()

# export_to_owl() is DEPRECATED: it builds a parallel ontology from an empty
# one, minting a fresh id for every class including those WONT already curates.
```

## Key Design Decisions

**ConceptStore as single source of truth** — both LLM extractions and predefined edges are stored in the same internal format. Normalization (LLM mapping + Title Case) is applied once at the store level, so all downstream consumers (hierarchies, FCA matrix) receive clean data.

**FCA-derived superclasses merged back** — named concepts from the concept lattice are wired back into the class hierarchy as intermediate grouping nodes, making them visible in the OWL output.

**BFO grounding** — mid-level BFO classes (`material entity`, `immaterial continuant`, `quality`, `disposition`, `role`, `process`) are passed to the LLM as `is_a` candidates so extracted entities are anchored to a top-level ontology.

**Mutual exclusion guard** — if the LLM marks `is_a: X = 1.0` for an entity, any `part_of: X` claim for the same target is demoted to `0.0`, preventing taxonomic and mereological relations from conflating.

## Testing

```bash
# Unit tests
pytest tests/ -m "not integration" -v

# Integration tests (requires API keys + network)
/opt/anaconda3/envs/first_env/bin/pytest tests/integration/ -m integration -v -s
```

## Dependencies

- `google-generativeai` — Gemini LLM
- `biopython` — PubMed/Entrez API
- `owlready2` — OWL ontology construction
- `concepts` — Formal Concept Analysis
- `pandas`, `pydantic`, `python-dotenv`
