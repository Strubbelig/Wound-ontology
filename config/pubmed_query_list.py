"""
PubMed search queries for wound ontology construction.

Scope
-----
- Clinical / translational only: human studies, case series, systematic reviews,
  clinical guidelines. No animal-only research, no in vitro / cell-line studies.
- One list entry = one independent Entrez search (results are deduplicated by
  PMID before LLM extraction).
- Queries marked (REVISED) were rewritten by the LLM validator after failing
  scope review. Queries marked (NEW) were added to fill lifecycle gaps.
- Queries are grouped by ontological domain so the LLM extraction is well-seeded
  for every predicate: is_a, part_of, has_quality, occurs_in,
  is_treatment_for.

Filter helper
-------------
  _q(core) appends the standard human-only and non-experimental filters.
  Revised queries that already embed their own filters are stored as raw strings.
"""

_HUMAN   = 'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms])'
_NON_EXP = 'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])'

def _q(core: str) -> str:
    return f"({core}) {_HUMAN} {_NON_EXP}"


PUBMED_SEARCH = [

    # ── Wound taxonomy & classification ───────────────────────────────────────
    # REVISED: tighter wound-specific MeSH terms replace the over-broad
    # "wounds and injuries" heading that returned TBI, infectious disease etc.

    '(("pressure ulcer"[MeSH Terms] OR "diabetic foot ulcer"[MeSH Terms] OR '
    '"leg ulcer"[MeSH Terms] OR "burn"[MeSH Terms] OR "surgical wound"[MeSH Terms] OR '
    '"traumatic wound"[tiab] OR "chronic wound"[tiab] OR "acute wound"[tiab]) AND '
    '(classification OR taxonomy OR "wound type" OR assessment OR staging)) AND '
    '("humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    _q('("skin ulcer"[MeSH Terms] OR "chronic wound"[tiab]) AND '
       '(classification OR staging OR grading OR etiology OR epidemiology) AND '
       '("humans"[MeSH Terms])'),

    # ── Pressure injuries ─────────────────────────────────────────────────────

    _q('("pressure ulcer"[MeSH Terms] OR "pressure injury"[tiab]) AND '
       '(staging OR classification OR "NPUAP" OR "EPUAP" OR "NPIAP" OR '
       '"deep tissue" OR management OR prevention OR treatment OR risk) AND '
       '"humans"[MeSH Terms]'),

    _q('("pressure ulcer"[MeSH Terms]) AND '
       '("risk factors"[MeSH Terms] OR incidence OR prevalence OR repositioning OR '
       '"pressure redistribution" OR "support surface") AND '
       '"humans"[MeSH Terms]'),

    # ── Diabetic foot ulcer ───────────────────────────────────────────────────

    _q('("diabetic foot"[MeSH Terms] OR "diabetic foot ulcer"[tiab]) AND '
       '(classification OR "Wagner" OR "PEDIS" OR "Texas classification" OR '
       '"WIfI" OR staging OR grading OR depth OR management) AND '
       '"humans"[MeSH Terms]'),

    _q('("diabetic foot"[MeSH Terms]) AND '
       '(neuropathy OR ischemia OR "peripheral arterial disease" OR infection OR '
       '"offloading" OR amputation OR revascularization OR debridement OR outcome) AND '
       '"humans"[MeSH Terms]'),

    # ── Venous leg ulcers ─────────────────────────────────────────────────────

    _q('("varicose ulcer"[MeSH Terms] OR "venous leg ulcer"[tiab] OR '
       '"venous ulcer"[tiab]) AND '
       '(pathophysiology OR "venous hypertension" OR compression OR treatment OR '
       '"four-layer bandage" OR "multilayer compression" OR care) AND '
       '"humans"[MeSH Terms]'),

    # ── Arterial / ischemic ulcers ────────────────────────────────────────────
    # REVISED: added mandatory wound-assessment anchor so vascular studies
    # without wound endpoints are excluded.

    '(("peripheral arterial disease"[MeSH Terms] OR "arterial ulcer"[tiab] OR '
    '"ischemic ulcer"[tiab] OR "critical limb ischemia"[tiab]) AND '
    '("ulcer"[tiab] OR "wound"[tiab] OR "ulceration"[tiab]) AND '
    '("wound assessment"[tiab] OR "wound management"[tiab] OR "wound healing"[tiab] OR '
    'debridement[tiab] OR dressing*[tiab] OR "exudate"[tiab] OR "granulation tissue"[tiab] OR '
    '"wound bed"[tiab] OR "antimicrobial"[tiab] OR "skin substitute*"[tiab] OR '
    'NPWT[tiab] OR "negative pressure"[tiab] OR amputation[tiab] OR '
    '"healing rate"[tiab] OR "wound care"[tiab]) AND "humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    # ── Surgical wounds & postoperative complications ─────────────────────────

    # REVISED: original lacked wound-specific terms and returned general surgical
    # complications (transplantation, sepsis). Now anchored to wound management
    # vocabulary (dressing, debridement, wound bed, exudate, etc.).
    '(("surgical wound infection"[MeSH Terms] OR "surgical wound dehiscence"[MeSH Terms] OR "surgical site infection"[tiab]) AND '
    '("wound management"[MeSH Terms] OR "wound healing"[MeSH Terms] OR dressing*[tiab] OR debridement[tiab] OR '
    '"wound bed"[tiab] OR "granulation tissue"[tiab] OR exudate[tiab] OR eschar[tiab] OR slough[tiab] OR '
    '"periwound skin"[tiab] OR "wound assessment"[tiab] OR "wound classification"[tiab] OR '
    '"wound care"[tiab] OR antimicrobial*[tiab] OR "negative pressure"[tiab]) AND '
    '"humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    # REVISED: "postoperative complications" was too broad; now anchored to
    # wound-specific MeSH to exclude cardiac, pain, and orthopaedic literature.

    '(("Wound Healing"[MeSH Terms] OR "Surgical Wound Infection"[MeSH Terms] OR '
    '"Wounds and Injuries"[MeSH Terms]) AND '
    '(wound OR dehiscence OR "wound breakdown" OR "surgical site infection") AND '
    '(management OR treatment OR care OR prevention OR classification) AND '
    '"humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    # ── Burns ─────────────────────────────────────────────────────────────────

    _q('("burns"[MeSH Terms]) AND '
       '(classification OR depth OR "superficial" OR "partial thickness" OR '
       '"full thickness" OR "TBSA" OR assessment OR first-aid OR "burn center") AND '
       '"humans"[MeSH Terms]'),

    _q('("burns"[MeSH Terms]) AND '
       '(management OR treatment OR "burn wound" OR "skin grafting" OR '
       '"escharotomy" OR "fluid resuscitation" OR rehabilitation OR scar OR '
       '"hypertrophic scar") AND '
       '"humans"[MeSH Terms]'),

    # ── Traumatic & acute wounds ──────────────────────────────────────────────

    _q('("lacerations"[MeSH Terms] OR "abrasions"[tiab] OR "puncture wound"[tiab] OR '
       '"bite wound"[tiab] OR "avulsion"[tiab] OR "degloving"[tiab]) AND '
       '(management OR treatment OR closure OR infection OR classification OR care) AND '
       '"humans"[MeSH Terms]'),

    _q('("fasciitis, necrotizing"[MeSH Terms] OR "necrotizing fasciitis"[tiab] OR '
       '"gas gangrene"[MeSH Terms] OR "Fournier gangrene"[tiab]) AND '
       '(diagnosis OR classification OR management OR treatment OR debridement OR '
       'mortality OR complication) AND '
       '"humans"[MeSH Terms]'),

    # ── Wound anatomy & tissue components ────────────────────────────────────
    # REVISED: added clinical study type filter to block in vitro keratinocyte
    # and mechanistic studies that escaped the NOT operator.

    '((wound OR ulcer) AND '
    '("wound bed"[tiab] OR "granulation tissue" OR "epithelialization" OR '
    '"wound edge"[tiab] OR "periwound skin"[tiab] OR eschar OR slough OR '
    'exudate OR "wound margins") AND '
    '(assessment OR management OR treatment OR definition OR characteristics) AND '
    '("humans"[MeSH Terms]) AND '
    '(clinical[tiab] OR patient*[tiab] OR observational[tiab] OR "case report"[tiab] OR '
    '"case series"[tiab] OR trial[tiab] OR cohort[tiab] OR "tissue biopsy"[tiab] OR '
    '"clinical sample"[tiab])) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab] OR '
    '"ex vivo"[tiab] OR mechanistic[tiab])',

    # REVISED: added negative terms for tendinopathy, sports medicine, cosmetic.

    '((wound OR ulcer OR "pressure injury" OR "pressure ulcer" OR "diabetic foot ulcer" OR '
    '"venous ulcer" OR "surgical wound" OR burn OR "traumatic wound") AND '
    '(depth OR staging OR classification OR "tissue layer" OR anatomy OR assessment OR evaluation) AND '
    '(skin OR dermis OR epidermis OR "subcutaneous tissue" OR fascia OR muscle OR bone) AND '
    '(management OR treatment OR care OR debridement OR dressing OR healing OR clinical OR '
    'patient* OR assessment)) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab] OR "basic science") '
    'NOT (tendon OR tendinopathy OR "muscle injury" OR "orthopedic" OR "sports medicine" OR '
    'reconstruction OR cosmetic OR "aging skin" OR retinoid)',

    # ── Wound characteristics / qualities ─────────────────────────────────────

    _q('(wound OR ulcer) AND '
       '("wound exudate" OR "wound odour" OR "wound odor" OR "wound size" OR '
       '"wound area" OR "wound depth" OR "wound volume" OR "wound pain" OR '
       '"wound temperature" OR "wound colour" OR "wound color") AND '
       '(assessment OR classification OR measurement OR documentation) AND '
       '"humans"[MeSH Terms]'),

    _q('(wound OR ulcer) AND '
       '("TIME framework"[tiab] OR "wound bed preparation"[tiab] OR '
       '"Tissue, Infection, Moisture, Edge"[tiab] OR '
       '"wound classification"[tiab] OR "wound scoring"[tiab]) AND '
       '"humans"[MeSH Terms]'),

    # ── Wound infection & biofilm ─────────────────────────────────────────────
    # REVISED: anchored to specific wound-type MeSH to exclude fracture,
    # dental, and endodontic infection literature.

    '(("wound infection"[MeSH Terms] OR "biofilms"[MeSH Terms]) AND '
    '("pressure ulcer"[MeSH Terms] OR "diabetic foot"[MeSH Terms] OR '
    '"venous ulcer"[MeSH Terms] OR "surgical wound infection"[MeSH Terms] OR '
    '"burn wounds"[MeSH Terms] OR "chronic wound"[tiab] OR "acute wound"[tiab] OR '
    '"traumatic wound"[tiab]) AND '
    '(diagnosis OR "wound culture"[tiab] OR "critical colonization"[tiab] OR '
    'treatment OR antimicrobial OR antiseptic OR antibiotic OR debridement OR dressing) AND '
    '"humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab]) '
    'NOT (fracture OR dental OR endodontic OR implant OR prosthetic OR orthopedic NOT wound)',

    _q('(wound OR ulcer) AND '
       '("MRSA" OR "Pseudomonas" OR "Staphylococcus aureus"[MeSH Terms] OR '
       '"polymicrobial" OR "anaerobic" OR fungal OR "Candida"[MeSH Terms]) AND '
       '(wound OR infection OR colonization OR treatment OR management OR outcome) AND '
       '"humans"[MeSH Terms]'),

    # ── Wound assessment tools ────────────────────────────────────────────────

    _q('("wound assessment"[tiab] OR "wound documentation"[tiab] OR '
       '"wound measurement"[tiab]) AND '
       '(tool OR scale OR score OR instrument OR "BWAT" OR "PUSH tool" OR '
       '"Bates-Jensen" OR "wound photography" OR "planimetry" OR reliability OR '
       'validity OR accuracy) AND '
       '"humans"[MeSH Terms]'),

    # ── Debridement ───────────────────────────────────────────────────────────

    _q('("debridement"[MeSH Terms]) AND '
       '(wound OR ulcer OR "necrotic tissue" OR eschar OR slough OR biofilm) AND '
       '(surgical OR enzymatic OR autolytic OR mechanical OR biological OR '
       '"larval therapy" OR "maggot therapy" OR ultrasonic OR hydrosurgery OR '
       '"sharp debridement" OR outcome OR comparison) AND '
       '"humans"[MeSH Terms]'),

    # ── Wound dressings ───────────────────────────────────────────────────────
    # REVISED (was FAIL): now uses the MeSH term "wound dressing" + specific
    # wound-type MeSH + clinical publication-type filter to block animal-model
    # and in vitro hydrogel studies that evade the NOT operator.

    _q('("wound dressing"[MeSH Terms] OR "bandages"[MeSH Terms]) AND '
       '("pressure ulcer"[MeSH Terms] OR "diabetic foot"[MeSH Terms] OR '
       '"varicose ulcer"[MeSH Terms] OR "leg ulcer"[MeSH Terms] OR '
       '"burns"[MeSH Terms] OR "chronic wound"[tiab] OR "surgical wound"[tiab]) AND '
       '("hydrocolloid" OR "foam dressing" OR alginate OR hydrofiber OR hydrogel OR '
       '"silver dressing" OR "antimicrobial dressing" OR "silicone dressing" OR '
       '"honey dressing" OR "DACC" OR "superabsorbent") AND '
       '("clinical trial"[pt] OR "randomized controlled trial"[pt] OR '
       '"comparative study"[pt] OR "multicenter study"[pt] OR "cohort study"[tiab]) AND '
       '"humans"[MeSH Terms]'),

    # ── Topical antimicrobial agents ──────────────────────────────────────────
    # REVISED: added exclusion for SSI prophylaxis and ophthalmology topics.

    '(("iodine"[tiab] OR "silver sulfadiazine"[tiab] OR "cadexomer"[tiab] OR '
    '"medical grade honey"[tiab] OR "polyhexamethylene biguanide"[tiab] OR '
    '"PHMB"[tiab] OR "chlorhexidine"[tiab] OR "povidone iodine"[tiab]) AND '
    '("wound healing"[MeSH Terms] OR "wound care"[tiab] OR "ulcer"[MeSH Terms] OR '
    '"diabetic foot"[MeSH Terms] OR "pressure injury"[MeSH Terms] OR '
    '"venous ulcer"[tiab] OR "chronic wound"[tiab] OR "burn wound"[tiab]) AND '
    '(treatment[tiab] OR management[tiab] OR efficacy[tiab] OR outcome[tiab] OR dressing[tiab]) '
    'NOT ("surgical site infection"[tiab] OR "antisepsis"[tiab] OR "preoperative"[tiab] OR '
    '"ophthalmology"[tiab]) AND "humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    # ── Negative pressure wound therapy ──────────────────────────────────────

    _q('("negative-pressure wound therapy"[MeSH Terms] OR "NPWT"[tiab] OR '
       '"vacuum-assisted closure"[tiab] OR "VAC therapy"[tiab] OR '
       '"topical negative pressure"[tiab]) AND '
       '(wound OR ulcer OR dehiscence OR "open abdomen" OR "sternal wound" OR '
       'diabetic OR pressure OR outcome OR complication OR indication) AND '
       '"humans"[MeSH Terms]'),

    # ── Growth factors & PRP ─────────────────────────────────────────────────
    # REVISED (was FAIL): switched to MeSH terms for specific growth-factor
    # products and restricted to clinical wound types to block animal-only,
    # ophthalmology, and cosmetic scar studies.

    _q('("platelet-rich plasma"[MeSH Terms] OR "becaplermin"[MeSH Terms] OR '
       '"epidermal growth factor"[MeSH Terms] OR "fibroblast growth factors"[MeSH Terms] OR '
       '"vascular endothelial growth factors"[MeSH Terms] OR "PRP"[tiab]) AND '
       '("pressure ulcer"[MeSH Terms] OR "diabetic foot"[MeSH Terms] OR '
       '"varicose ulcer"[MeSH Terms] OR "leg ulcer"[MeSH Terms] OR '
       '"burns"[MeSH Terms] OR "chronic wound"[tiab]) AND '
       '("clinical trial"[pt] OR "randomized controlled trial"[pt] OR '
       '"observational study"[pt] OR "comparative study"[pt]) AND '
       '"humans"[MeSH Terms]'),

    # ── Skin substitutes & bioengineered therapies ────────────────────────────

    _q('("skin, artificial"[MeSH Terms] OR "skin substitute"[tiab] OR '
       '"bioengineered skin"[tiab] OR "acellular dermal matrix"[tiab] OR '
       '"ADM"[tiab] OR "split-thickness skin graft"[tiab] OR '
       '"tissue-engineered"[tiab]) AND '
       '(wound OR ulcer OR healing OR burn OR coverage) AND '
       '"humans"[MeSH Terms]'),

    # ── Advanced adjunctive therapies ─────────────────────────────────────────
    # REVISED: added exclusion for hernia/mesh/reconstruction to block general
    # surgery papers without wound management endpoints.

    '(("hyperbaric oxygenation"[MeSH Terms] OR "hyperbaric oxygen"[tiab] OR '
    '"HBO"[tiab] OR "photobiomodulation"[tiab] OR "low-level laser"[tiab] OR '
    '"electrical stimulation"[tiab] OR "ultrasound therapy"[tiab]) AND '
    '("pressure ulcer"[MeSH Terms] OR "diabetic foot ulcer"[tiab] OR '
    '"venous ulcer"[tiab] OR "chronic wound"[tiab] OR "acute wound"[tiab] OR '
    '"burn"[MeSH Terms] OR "surgical wound infection"[tiab] OR '
    '"wound healing"[MeSH Terms] OR "ulcer"[MeSH Terms]) AND '
    '(clinical OR patient OR outcome OR randomized OR trial) AND '
    '"humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab]) '
    'NOT ("hernia"[tiab] OR "mesh"[tiab] OR "reconstruction"[tiab])',

    # ── Wound healing phases (clinical evidence) ──────────────────────────────
    # REVISED: now requires specific wound-type MeSH + clinical outcome term
    # to exclude general mechanism reviews ungrounded in patient data.

    '(("wound healing"[MeSH Terms]) AND '
    '("inflammatory phase" OR "proliferative phase" OR remodeling OR "epithelialization" OR '
    'angiogenesis OR "granulation tissue" OR fibroblast OR collagen OR "scar formation" OR '
    '"keloid"[MeSH Terms] OR "hypertrophic scar"[tiab]) AND '
    '("pressure ulcer"[MeSH Terms] OR "diabetic foot ulcer"[MeSH Terms] OR '
    '"venous ulcer"[tiab] OR "surgical wound"[tiab] OR burn[MeSH Terms] OR '
    '"traumatic wound"[tiab] OR "chronic wound"[tiab]) AND '
    '("healing rate"[tiab] OR wound closure[tiab] OR infection[tiab] OR '
    '"clinical trial"[PT] OR observational[tiab]) AND '
    '"humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    # REVISED: replaced broad "wound healing" + mechanism terms with specific
    # wound-type anchors + clinical study-type filter to exclude dental,
    # acne, palatal, and other out-of-scope healing contexts.

    '(("pressure ulcer"[MeSH Terms] OR "diabetic foot ulcer"[tiab] OR '
    '"venous ulcer"[tiab] OR "venous leg ulcer"[tiab] OR "surgical wound"[tiab] OR '
    '"burn wound"[tiab] OR "traumatic wound"[tiab] OR "chronic wound"[tiab] OR '
    '"leg ulcer"[MeSH Terms] OR "foot ulcer"[MeSH Terms]) AND '
    '(impaired OR delayed OR stalled OR biofilm OR proteases OR '
    '"matrix metalloproteinase" OR senescent OR ischemia) AND '
    '("clinical trial"[Publication Type] OR "observational study"[Publication Type] OR '
    '"comparative study"[Publication Type] OR "patient cohort"[tiab] OR '
    '"wound biopsy"[tiab] OR "tissue biopsy"[tiab] OR '
    '"case series"[Publication Type] OR "case reports"[Publication Type]) AND '
    '"humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab]) '
    'NOT ("dental"[tiab] OR "oral"[tiab] OR "periodontal"[tiab] OR "implant"[tiab] OR '
    '"acne"[tiab] OR "scar"[tiab])',

    # ── Wound etiology & risk factors ────────────────────────────────────────

    _q('(wound OR ulcer) AND '
       '("risk factors"[MeSH Terms]) AND '
       '(diabetes[tiab] OR ischemia[tiab] OR neuropathy[tiab] OR '
       'malnutrition[tiab] OR obesity[tiab] OR immunosuppression[tiab] OR '
       'smoking[tiab] OR "corticosteroids"[tiab] OR radiation[tiab] OR '
       'age[tiab] OR mobility[tiab]) AND '
       '"humans"[MeSH Terms]'),

    # ── Special populations ───────────────────────────────────────────────────

    _q('("pressure ulcer"[MeSH Terms] OR "chronic wound"[tiab]) AND '
       '(elderly OR "older adult" OR "nursing home" OR "long-term care" OR '
       '"spinal cord injury"[MeSH Terms] OR "intensive care unit"[tiab]) AND '
       '(management OR prevention OR treatment OR outcome OR care) AND '
       '"humans"[MeSH Terms]'),

    # REVISED: anchored to wound types + wound-management terms; added
    # exclusion for mucosal / ocular / GI ulcers.

    '((("pressure ulcer"[MeSH Terms] OR "diabetic foot"[tiab] OR "venous ulcer"[tiab] OR '
    '"surgical wound"[tiab] OR "traumatic wound"[tiab] OR "burn wound"[tiab] OR '
    '"chronic wound"[tiab] OR "acute wound"[tiab]) OR '
    '("wound"[tiab] AND ("debridement"[tiab] OR "dressing"[tiab] OR '
    '"wound healing"[MeSH Terms] OR "wound care"[tiab] OR "wound management"[tiab] OR '
    '"negative pressure"[tiab] OR "granulation tissue"[tiab]))) AND '
    '("immunocompromised"[tiab] OR "immunosuppressed"[tiab] OR "cancer patient"[tiab] OR '
    '"chemotherapy"[MeSH Terms] OR "radiation therapy"[MeSH Terms] OR '
    '"transplant recipient"[tiab] OR "HIV infection"[MeSH Terms] OR "corticosteroid"[tiab])) '
    'NOT ("mucosal"[tiab] OR "oral ulcer"[tiab] OR "mouth ulcer"[tiab] OR '
    '"peptic ulcer"[tiab] OR "ocular"[tiab] OR "corneal"[tiab] OR '
    '"conjunctival"[tiab] OR "gastrointestinal ulcer"[tiab]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    # ── Wound care outcomes ───────────────────────────────────────────────────

    _q('(wound OR ulcer) AND '
       '("time to healing"[tiab] OR "healing rate"[tiab] OR "wound closure"[tiab] OR '
       '"wound recurrence"[tiab] OR "quality of life"[MeSH Terms] OR '
       '"pain"[MeSH Terms] OR "cost" OR hospitalization OR amputation OR mortality) AND '
       '("clinical trial"[pt] OR "systematic review"[pt] OR '
       '"randomized controlled trial"[pt]) AND '
       '"humans"[MeSH Terms]'),

    # ── Clinical guidelines & pathways ────────────────────────────────────────
    # REVISED: replaced bare "ulcer" with specific wound terms to block
    # ulcerative colitis, aortic ulcer, and TMD guidelines.

    '((wound[tiab] OR "wound care"[tiab] OR "pressure injury"[tiab] OR '
    '"pressure ulcer"[tiab] OR "diabetic foot ulcer"[tiab] OR "venous ulcer"[tiab] OR '
    '"surgical wound"[tiab] OR "chronic wound"[tiab] OR "acute wound"[tiab] OR '
    '"skin ulcer"[tiab]) AND '
    '(guideline[pt] OR "practice guideline"[pt] OR "clinical pathway"[tiab] OR '
    '"care bundle"[tiab] OR consensus OR recommendation OR protocol) AND '
    '"humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    # ── Wound prevention & risk screening (NEW) ───────────────────────────────
    # Covers: Braden/Norton/Waterlow scales, DFU foot-care programs, SSI
    # prevention bundles — the very start of the clinical lifecycle.

    _q('("risk assessment"[MeSH Terms] OR "Braden scale"[tiab] OR '
       '"Norton scale"[tiab] OR "Waterlow score"[tiab]) AND '
       '("pressure ulcer"[MeSH Terms] OR "pressure injury"[tiab]) AND '
       '(prevention OR screening OR "risk stratification" OR reliability OR '
       'validity OR sensitivity OR specificity) AND '
       '"humans"[MeSH Terms]'),

    _q('("diabetic foot"[MeSH Terms]) AND '
       '(prevention OR "foot care" OR "footwear" OR "offloading" OR '
       '"total contact cast" OR "therapeutic shoe" OR "insole" OR '
       '"monofilament" OR "vibration perception" OR "foot screening") AND '
       '"humans"[MeSH Terms]'),

    # ── Wound diagnostics & vascular assessment (NEW) ─────────────────────────
    # Covers: ABPI, duplex ultrasound, wound imaging, differential diagnosis —
    # the "first occurrence / diagnostic workup" phase.

    _q('(wound OR ulcer OR "diabetic foot" OR "leg ulcer") AND '
       '("ankle brachial index"[tiab] OR "ABPI"[tiab] OR "ABI"[tiab] OR '
       '"duplex ultrasound"[tiab] OR "transcutaneous oxygen"[tiab] OR '
       '"TcPO2"[tiab] OR "wound photography"[tiab] OR "thermography"[tiab] OR '
       '"MRI"[tiab] OR "wound imaging"[tiab]) AND '
       '(assessment OR diagnosis OR "differential diagnosis" OR classification OR '
       'accuracy OR reliability OR outcome) AND '
       '"humans"[MeSH Terms]'),

    # ── Nutritional support for wound healing (NEW) ───────────────────────────
    # Covers: protein/albumin supplementation, micronutrients (zinc, vit C,
    # arginine) as interventions — systemic co-treatment alongside local care.

    _q('(wound OR ulcer OR "pressure injury" OR "diabetic foot") AND '
       '("malnutrition"[MeSH Terms] OR "nutritional support"[MeSH Terms] OR '
       '"protein"[tiab] OR "albumin"[tiab] OR "arginine"[tiab] OR '
       '"zinc"[tiab] OR "vitamin C"[tiab] OR "ascorbic acid"[MeSH Terms] OR '
       '"omega-3"[tiab] OR "enteral nutrition"[MeSH Terms]) AND '
       '("wound healing"[MeSH Terms] OR "healing rate"[tiab] OR '
       '"wound closure"[tiab] OR outcome OR intervention OR supplementation) AND '
       '"humans"[MeSH Terms]'),

    # ── Scar assessment & treatment (NEW) ────────────────────────────────────
    # REVISED: pure keloid/scar searches retrieved cosmetic dermatology outside
    # scope. Now anchored to wound types as the causal context for scar.

    '(("surgical wound"[tiab] OR "surgical site infection"[tiab] OR '
    '"wound healing"[tiab] OR "traumatic wound"[tiab] OR "burn wound"[tiab]) AND '
    '("scar formation"[tiab] OR "scar tissue"[tiab] OR "hypertrophic scar"[tiab] OR '
    '"keloid"[tiab]) AND '
    '("assessment"[tiab] OR "prevention"[tiab] OR "management"[tiab] OR '
    '"treatment"[tiab]) AND '
    '"humans"[MeSH Terms]) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

    # ── Palliative & malignant wound care (NEW) ───────────────────────────────
    # REVISED: added clinical study type requirement and excluded molecular
    # mechanism terms (apoptosis, cell death) that escaped the NOT filter.

    '(("fungating wound"[tiab] OR "malignant wound"[tiab] OR "neoplastic wound"[tiab] OR '
    '"tumor wound"[tiab] OR "palliative wound care"[tiab] OR "end-of-life wound"[tiab]) AND '
    '(management OR treatment OR dressing OR odour OR odor OR exudate OR bleeding OR '
    '"symptom control" OR comfort OR care OR outcome OR assessment OR evaluation) AND '
    '("humans"[MeSH Terms] OR "clinical trial"[Publication Type] OR '
    '"observational study"[tiab] OR "case report"[Publication Type] OR '
    '"case series"[Publication Type])) '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab]) '
    'NOT (apoptosis[tiab] OR "cell death"[tiab] OR "molecular mechanism"[tiab] OR '
    '"signaling pathway"[tiab])',

    # ── Osteomyelitis as wound complication (NEW) ────────────────────────────
    # Covers: bone infection secondary to DFU, pressure injury, or chronic wound
    # — a major clinical decision point (probe-to-bone test, MRI, resection vs.
    # antibiotics, amputation risk) not captured by existing infection queries.

    _q('("osteomyelitis"[MeSH Terms]) AND '
       '("diabetic foot"[MeSH Terms] OR "pressure ulcer"[MeSH Terms] OR '
       '"chronic wound"[tiab] OR "foot ulcer"[MeSH Terms] OR '
       '"wound infection"[MeSH Terms]) AND '
       '(diagnosis OR "probe-to-bone"[tiab] OR "bone biopsy"[tiab] OR '
       '"MRI"[tiab] OR treatment OR "antibiotic"[tiab] OR '
       '"surgical debridement"[tiab] OR amputation OR outcome OR '
       '"conservative treatment"[tiab]) AND '
       '"humans"[MeSH Terms]'),

    # ── Wound recurrence & long-term follow-up (NEW) ──────────────────────────
    # REVISED: bare wound/ulcer + recurrence pulled ankle-fracture literature.
    # Now uses wound-type MeSH exclusively and adds reulceration as a term.

    '((("pressure ulcer"[MeSH Terms] OR "foot ulcer"[MeSH Terms] OR '
    '"varicose ulcer"[MeSH Terms] OR "surgical wound"[MeSH Terms] OR '
    '"burns"[MeSH Terms] OR "traumatic wound"[tiab] OR "chronic wound"[tiab] OR '
    '"acute wound"[tiab]) AND '
    '("recurrence"[tiab] OR "reulceration"[tiab] OR "wound healing"[MeSH Terms] OR '
    '"long-term follow-up"[tiab] OR "durable healing"[tiab] OR '
    '"maintained closure"[tiab] OR "secondary prevention"[tiab] OR '
    '"prevention of recurrence"[tiab])) OR '
    '("diabetic foot ulcer"[MeSH Terms] AND '
    '("recurrence"[tiab] OR "reulceration"[tiab] OR "long-term outcome"[tiab]))) AND '
    '("clinical trial"[pt] OR "cohort study"[tiab] OR '
    '"systematic review"[pt] OR "randomized controlled trial"[pt] OR '
    '"prospective study"[tiab] OR "observational study"[tiab]) AND '
    '"humans"[MeSH Terms] '
    'NOT ("animals"[MeSH Terms] NOT "humans"[MeSH Terms]) '
    'NOT ("in vitro"[tiab] OR "cell line"[tiab] OR "cell culture"[tiab])',

]
