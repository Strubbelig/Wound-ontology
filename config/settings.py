import os
from pathlib import Path

# Project root (one level up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Paths
BASE_PATH = PROJECT_ROOT / "data" / "cache"
OWL_OUTPUT_FILE = PROJECT_ROOT / "output" / "owl" / "ontology_classes.owl"
# NOTE: there is no PREDEFINED_HIERARCHY_FILE any more. The curated seed
# hierarchy that used to live in data/raw/predefined_concept_hierarchy.csv was
# merged into the WONT and MILD ontologies below, and is read back out of them
# by hierarchies/curated_seed.py -- GROUND_TRUTH_TTL and MILD_TTL are therefore
# load-bearing for the hierarchy build, not just for the reasoner gate.

# Ground-truth ontologies. These are the source of truth for the extraction
# schema (scripts/build_extraction_schema.py) and for the reasoner gate.
GROUND_TRUTH_TTL = PROJECT_ROOT / "data" / "ground truth" / "ground_truth_final.owl"
MILD_TTL = PROJECT_ROOT.parent / "Disease ontologies" / "Disease proposal 2.ttl"
MILD_MODULES_DIR = PROJECT_ROOT.parent / "Disease ontologies" / "Disease ontology modules"

# The competency questions, resolved absolutely. They used to be opened as the
# relative "config/competency_questions.json", which only works when the
# interpreter happens to be started from PROJECT_ROOT -- so the competency tests
# passed from a terminal and errored under the VS Code Test Explorer, which runs
# from the workspace root one level up.
COMPETENCY_QUESTIONS_FILE = PROJECT_ROOT / "config" / "competency_questions.json"

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
# WOND_ was the ontology's earlier namespace and has been retired -- the 16
# import modules were already scrubbed of it. The exporter was still minting it,
# so every newly discovered class got an IRI in a namespace nothing resolves.
ONTOLOGY_BASE_IRI = "https://bioportal.bioontology.org/ontologies/WONT/WONT_"
ONTOLOGY_ID_PREFIX = "WONT"                                  # CURIE prefix
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
# StoreCleaner STRIPS any store attribute whose predicate is not listed here,
# so this list is the pipeline's real relation vocabulary. It used to hold only
# the legacy extractor's five entries -- which meant that after the switch to
# two-stage extraction, 24 of the 26 relation types the extractor can emit were
# deleted from the store before anything downstream ever saw them.
#
# Kept explicit rather than imported, so the vocabulary is readable in one place;
# test_predicate_vocabularies_agree fails if it drifts from the extractor's
# RELATION_IRI or from owl/extend.py's export table.
ALLOWED_PREDICATES = [
    "is_a",
    # ── emitted by two-stage extraction (RelationType / RELATION_IRI) ─────────
    "causally_influenced_by",
    "concretizes",
    "has_a_material_basis",
    "has_as_process_boundary_at_end",
    "has_as_process_boundary_at_start",
    "has_disposition",
    "has_function",
    "has_input",
    "has_output",
    "has_part",
    "has_participant",
    "has_quality",
    "has_realization",
    "has_role",
    "has_specified_input",
    "has_specified_output",
    "immediately_causally_downstream_of",
    "inheres_in",
    "is_about",
    "is_specified_input_of",
    "is_specified_output_of",
    "occupies_temporal_region",
    "output_of",
    "part_of",
    "participates_in",
    "realizes",
    # ── legacy stores only; no RelationType produces these ────────────────────
    "occurs_in",
    "is_treatment_for",
]
# 'affects' and 'caused_by' were removed (C3). 'affects' had no IRI at all, so
# every affects edge was unmappable on export. 'caused_by' is refused by MILD
# model commitment 4: what a disease causes cannot be reliably separated from
# what it is. Anatomical involvement of a disorder is BFO_0000050 part_of; of a
# process, BFO_0000066 occurs_in. Aetiology has no replacement by design.

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
        "summary": (
            "INTRINSIC PROPERTY OR CHARACTERISTIC of a continuant. Use for defining "
            "qualities of the object itself. A quality attaches to the class it is "
            "actually true of. A DETERMINABLE (color, area, healing time) is true of "
            "the parent — every wound has some area. A DETERMINATE (reddened, chronic) "
            "is true only of the subclass it defines, and belongs there."
        ),
        "yes": [
            "Chronic Wound has_quality Chronic  (determinate — a wound that is not chronic is not a Chronic Wound)",
            "Reddened Wound Edge has_quality Reddened  (determinate — WONT_0000256, the same shape)",
            "Wound has_quality Wound Area  (determinable — every wound has some area, without fixing which)",
            "Hydrogel has_quality Biocompatible",
        ],
        "no": [
            "NEVER use for functional roles, causal relations, or locations.",
            "NEVER put a determinate on the parent: 'Wound has_quality Chronic' is WRONG — only some wounds are chronic. It belongs on Chronic Wound.",
            "NEVER put a determinable on the class a determinate defines: 'Chronic Wound has_quality Wound Healing Time' says nothing that is not already true of every Wound.",
            "TEST: 'if X were not <quality>, would it still be a Y?' No → the quality defines Y, put it on Y. Yes → it belongs further down, on the subclass it does define.",
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
            "NEVER two continuants: 'Wound Infection occurs_in Diabetic Foot' is WRONG — Wound Infection is a condition (continuant); use part_of.",
            "NEVER two continuants: 'Surgical Site Infection occurs_in Surgical Site' is WRONG — SSI is a condition (continuant); use part_of.",
            "NEVER two continuants: 'Pressure Injury occurs_in Subcutaneous Tissue' is WRONG — both are continuants; use part_of.",
            "TEST: Is X a process/event AND Y a material site or organ? → occurs_in. Is X a disorder/lesion? → part_of.",
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
