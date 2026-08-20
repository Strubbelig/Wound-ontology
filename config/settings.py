import os
from pathlib import Path

# Project root (one level up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Paths
BASE_PATH = PROJECT_ROOT / "data" / "cache"
OWL_OUTPUT_FILE = PROJECT_ROOT / "output" / "owl" / "ontology_classes.owl"
PREDEFINED_HIERARCHY_FILE = PROJECT_ROOT / "data" / "raw" / "predefined_concept_hierarchy.csv"

# Ground-truth ontologies. These are the source of truth for the extraction
# schema (scripts/build_extraction_schema.py) and for the reasoner gate.
GROUND_TRUTH_TTL = PROJECT_ROOT / "data" / "ground truth" / "ground_truth_final.owl"
MILD_TTL = PROJECT_ROOT.parent / "Disease ontologies" / "Disease proposal 2.ttl"
MILD_MODULES_DIR = PROJECT_ROOT.parent / "Disease ontologies" / "Disease ontology modules"

# Where the reasoner gate keeps its cached skeleton TBox and quarantined batches.
REASONER_SKELETON = PROJECT_ROOT / "output" / "owl" / "skeleton_tbox.ttl"
QUARANTINE_DIR = PROJECT_ROOT / "output" / "quarantine"

# Local source-ontology files used for external-class label enrichment.
# Defaults to the shared Import-Ontologien folder one project-level up.
IMPORT_ONTO_DIR = Path(
    os.getenv("IMPORT_ONTO_DIR",
              str(PROJECT_ROOT.parent / "Flap ontology" / "Import-Ontologien"))
)

# Search terms — canonical list lives in pubmed_search.py
from config.pubmed_query_list import PUBMED_SEARCH as PUBMED_SEARCH_TERMS

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
BATCH_SIZE = 40
CACHE_MAX_FILES_PER_PREFIX = 10

# Ontology predicates
ALLOWED_PREDICATES = [
    "is_a",
    "part_of",
    "has_quality",
    "occurs_in",
    "affects",
    "caused_by",
    "is_treatment_for",
]

# Predicate definitions — used to build the LLM extraction prompt dynamically.
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
        "summary": "BFO MEREOLOGY. Connects two continuants (material parts) OR two occurrents (process steps). NEVER across categories.",
        "yes": [
            "Dermis part_of Skin  (continuant part of continuant — spatial structural part)",
            "Copper Nanoparticle part_of Hydrogel  (continuant part of continuant — physically embedded)",
            "Debridement part_of Wound Care Procedure  (occurrent part of occurrent — process step within a process)",
            "Dural Closure part_of Tethered Cord Release  (occurrent part of occurrent — surgical step within procedure)",
        ],
        "no": [
            "NEVER across BFO categories: a process cannot be part_of a material entity, and a material entity cannot be part_of a process.",
            "NEVER for taxonomic membership — use is_a: 'Pressure Injury part_of Hospital-Associated Complications' is WRONG — use is_a.",
            "'Delirium part_of Postoperative Complications' is WRONG — use is_a.",
            "'Sepsis part_of Infectious Complication' is WRONG — use is_a.",
            "TEST continuant: Can you physically remove X from Y? → part_of. Otherwise → is_a or occurs_in.",
            "TEST occurrent: Is X a temporal subprocess of Y? → part_of. Otherwise → occurs_in or is_a.",
        ],
    },
    "has_quality": {
        "summary": "INTRINSIC PROPERTY OR CHARACTERISTIC of a continuant. Use for defining qualities of the object itself.",
        "yes": [
            "Chronic Wound has_quality Chronic",
            "Hydrogel has_quality Biocompatible",
        ],
        "no": [
            "NEVER use for functional roles, causal relations, or locations.",
        ],
    },
    "occurs_in": {
        "summary": "BFO PROCESS LOCATION. Connects an OCCURRENT (process/event) to a CONTINUANT (material entity/anatomical site). NEVER two occurrents, NEVER two continuants.",
        "yes": [
            "Wound Healing occurs_in Dermis  (healing process occurs_in anatomical continuant — correct)",
            "Wound Assessment occurs_in Wound  (assessment process occurs_in material site — correct)",
            "Surgical Debridement occurs_in Wound Bed  (surgical process occurs_in anatomical site — correct)",
            "Inflammatory Response occurs_in Wound  (biological process occurs_in wound site — correct)",
        ],
        "no": [
            "NEVER two occurrents: 'Wound Healing occurs_in Postoperative Period' is WRONG — a time period is an occurrent; use part_of for process-in-process.",
            "NEVER two continuants: 'Wound Infection occurs_in Diabetic Foot' is WRONG — Wound Infection is a condition (continuant); use affects.",
            "NEVER two continuants: 'Surgical Site Infection occurs_in Surgical Site' is WRONG — SSI is a condition (continuant); use affects.",
            "NEVER two continuants: 'Pressure Injury occurs_in Subcutaneous Tissue' is WRONG — both are continuants; use affects.",
            "TEST: Is X a process/event AND Y a material site or organ? → occurs_in. Is X a condition/lesion? → affects.",
        ],
    },
    "affects": {
        "summary": "ANATOMICAL INVOLVEMENT. Connects a CONTINUANT (wound, condition, lesion) to the CONTINUANT (tissue, anatomical structure) it involves or damages. NEVER for processes — use occurs_in.",
        "yes": [
            "Pressure Injury affects Subcutaneous Tissue  (lesion affects anatomical site — correct)",
            "Diabetic Foot Ulcer affects Plantar Foot  (condition affects body region — correct)",
            "Necrotizing Fasciitis affects Fascia  (condition affects tissue — correct)",
            "Burn Injury affects Epidermis  (wound affects skin layer — correct)",
        ],
        "no": [
            "NEVER for processes: 'Wound Healing affects Dermis' is WRONG — use occurs_in.",
            "NEVER for taxonomic membership: 'Pressure Injury affects Chronic Wound' is WRONG — use is_a.",
            "NEVER for causal relationships: 'Ischemia affects Wound Healing' is WRONG — use caused_by.",
            "TEST: Is X a material lesion/condition AND Y the anatomical site it involves? → affects. If X is a process → occurs_in.",
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
