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
RO_OWL_URL  = "http://purl.obolibrary.org/obo/ro.owl"
OBI_OWL_URL = "http://purl.obolibrary.org/obo/obi.owl"

# Output ontology identity
# Change these to your own IRI/CURIE when publishing.
ONTOLOGY_BASE_IRI = "http://purl.obolibrary.org/obo/WOND_"  # base for class IRIs
ONTOLOGY_ID_PREFIX = "WOND"                                  # CURIE prefix
ONTOLOGY_ID_START  = 1                                       # first numeric ID

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
    "has_quality",
    "occurs_in",
    "caused_by",
    "is_treatment_for",
]

# Predicate definitions — used to build the LLM extraction prompt dynamically.
# Add an entry here whenever you add a predicate to ALLOWED_PREDICATES.
PREDICATE_DEFINITIONS = {
    "is_a": {
        "summary": "CLASS MEMBERSHIP (taxonomic). Use when X is a subtype of Y.",
        "yes": [
            "Sepsis is_a Infectious Complication  (Sepsis is a type of infectious complication)",
            "Surgical Site Infection is_a Infectious Complication",
        ],
        "no": [
            "NEVER use has_part or part_of to express class membership.",
            "TEST: Can you say 'Every X is a kind of Y'? → use is_a.",
        ],
    },
    "part_of": {
        "summary": "PHYSICAL/STRUCTURAL CONTAINMENT. Use when X is a spatially contained physical component of Y.",
        "yes": [
            "Copper Nanoparticle part_of Hydrogel  (the particle is physically embedded in the gel)",
            "Dural Closure part_of Tethered Cord Release  (a surgical step within a procedure)",
        ],
        "no": [
            "NEVER use for disease categories: 'Sepsis part_of Infectious Complication' is WRONG.",
            "NEVER use for processes that happen inside something — use occurs_in instead.",
            "TEST: Can you physically remove X from Y? → use part_of.",
        ],
    },
    "has_quality": {
        "summary": "INTRINSIC PROPERTY OR CHARACTERISTIC. Use for defining qualities of the object.",
        "yes": [
            "Chronic Wound has_quality Chronic",
            "Hydrogel has_quality Biocompatible",
        ],
        "no": [
            "NEVER use for functional roles or causal relations.",
        ],
    },
    "occurs_in": {
        "summary": "SPATIAL OR TEMPORAL LOCATION. Use when a process or condition takes place in an anatomical site or time period.",
        "yes": [
            "Infection occurs_in Diabetic Wound  (infection is a process located in the wound)",
            "Wound Healing occurs_in Skin",
            "Postoperative Complication occurs_in Postoperative Period",
        ],
        "no": [
            "NEVER use part_of for this: 'Infection part_of Diabetic Wound' is WRONG.",
        ],
    },
    "caused_by": {
        "summary": "DIRECT CAUSAL AGENT. Use when Y is the necessary causal agent or mechanism of X.",
        "yes": [
            "Wound Infection caused_by Bacterial Colonization",
            "Mitochondrial Dysfunction caused_by Oxidative Stress",
        ],
        "no": [
            "Avoid if the causal link is indirect or merely correlational.",
        ],
    },
    "is_treatment_for": {
        "summary": "THERAPEUTIC RELATIONSHIP. Use when X is a clinical intervention that treats condition Y.",
        "yes": [
            "Chitosan Hydrogel is_treatment_for Chronic Wound",
            "Tethered Cord Release is_treatment_for Complex Spinal Lipoma",
        ],
        "no": [],
    },
}
