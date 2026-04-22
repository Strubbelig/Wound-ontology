"""
OFL vocabulary constants — namespaces, class IRIs, and property IRIs.

Import from here rather than hard-coding OFL IRIs in generator classes.
"""
from rdflib import Namespace, URIRef

OFL     = Namespace("https://purl.bioontology.org/ontology/OFL/")
OBO     = Namespace("http://purl.obolibrary.org/obo/")
FMA     = Namespace("http://purl.obolibrary.org/obo/FMA_")
DCTERMS = Namespace("http://purl.org/dc/terms/")

# ── Ontology roots ────────────────────────────────────────────────────────────
FLAP_ROOT   = OFL.OFLID10002   # top-level flap class
ORIGIN_ROOT = OFL.OFLID10098   # Flaps classified by region of origin

# ── OFL object properties ─────────────────────────────────────────────────────
HAS_PART   = OFL.OFLID13296
PART_OF    = OFL.OFLID13297
HAS_ORIGIN = OFL.OFLID12003

# ── RO / OBI properties ───────────────────────────────────────────────────────
HAS_PARTICIPANT = OBO.RO_0000057   # has participant
CONCRETIZES     = OBO.RO_0000059   # concretizes (sdc concretizes gdc)
HAS_FUNCTION    = OBO.RO_0000085   # has function
HAS_QUALITY     = OBO.RO_0000086   # has quality
IS_OUTPUT_OF    = OBO.OBI_0000312  # is specified output of

# ── Modification classes ──────────────────────────────────────────────────────
MOD_NO  = OFL.OFLID10130   # without preharvest modification
MOD_YES = OFL.OFLID10131   # with preharvest modification

# ── Survival outcome classes ──────────────────────────────────────────────────
SURVIVAL_NO_LOSS  = OFL.OFLID10184
SURVIVAL_APEX     = OFL.OFLID10179
SURVIVAL_TOTAL    = OFL.OFLID10183
SURVIVAL_ARTERIAL = OFL.OFLID10180
SURVIVAL_VENOUS   = OFL.OFLID10181

LEAF_SURVIVAL = [SURVIVAL_NO_LOSS, SURVIVAL_APEX, SURVIVAL_TOTAL,
                 SURVIVAL_ARTERIAL, SURVIVAL_VENOUS]
MAIN_SURVIVAL = [SURVIVAL_NO_LOSS, SURVIVAL_APEX, SURVIVAL_TOTAL]

# ── Transfer distance classes ─────────────────────────────────────────────────
LOCAL_FLAP    = OFL.OFLID10134
REGIONAL_FLAP = OFL.OFLID10140
DISTANT_FLAP  = OFL.OFLID10085

# ── Transfer process classes ──────────────────────────────────────────────────
FREE_TRANSFER     = OFL.OFLID1000137
PEDICLED_TRANSFER = OFL.OFLID1000138

# ── Operative process / plan classes ─────────────────────────────────────────
FLAP_HARVEST_PROCESS = OFL.OFLID1000132   # Flap harvest process
COMPLETE_OPERATION   = OFL.OFLID1000128   # Complete flap operation process
FLAP_SURGERY_PLAN    = OFL.OFLID10507     # Flap surgery plan (gdc)

# ── BFO / PATO / NCBITaxon types ─────────────────────────────────────────────
CONC_PLAN_TYPE = OBO.BFO_0000020      # specifically dependent continuant
PATIENT_TYPE   = OBO.NCBITaxon_9606   # Homo sapiens
VOL_TYPE       = OBO.PATO_0001679     # volume

# ── OFL role / function types ─────────────────────────────────────────────────
ROLE_TYPE = OFL.OFLID106000   # Wound coverage role
FUNC_TYPE = OFL.OFLID106029   # Oxygenated blood supply to flap function
