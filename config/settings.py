import os
from pathlib import Path

# Project root (one level up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Paths
BASE_PATH = PROJECT_ROOT / "data" / "cache"
OWL_OUTPUT_FILE = PROJECT_ROOT / "output" / "owl" / "ontology_classes.owl"

# Search terms
PUBMED_SEARCH_TERMS = [
    "wound healing",
    "chronic wound",
    "wound care",
]

# External ontology URLs
BFO_OWL_URL = "http://purl.obolibrary.org/obo/bfo.owl"
RO_OWL_URL = "http://purl.obolibrary.org/obo/ro.owl"

# PubMed / NCBI
ENTREZ_EMAIL = os.getenv("ENTREZ_EMAIL", "")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")

# LLM
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Pipeline
BATCH_SIZE = 10
CACHE_MAX_FILES_PER_PREFIX = 10

# Ontology predicates
ALLOWED_PREDICATES = [
    "is_a",
    "part_of",
    "has_part",
    "has_quality",
    "occurs_in",
    "has_participant",
    # "causally_related_to",
]
