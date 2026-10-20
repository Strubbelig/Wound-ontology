"""The curator's head-word rulings for superclass edges (rule 79).

A label is read as modifiers + head word: `deep second-degree burn wound` is
{deep, second, degree, burn} + `wound`. An edge child ⊑ parent is licensed only
when the parent's head is the child's head or above it on HEAD_LADDER, and the
parent carries no modifier the child lacks. Everything below is what the
curator decided about particular head words and labels; nothing writes this
file except a curator decision.

Curator, 2026-10-18: "Wound is an injury. Burn wound is a burn injury is an
injury und burn wound is a wound aber nicht wound is a burn injury. Aber auch
Blast wound is a blast injury is an injury." Then, the same day, on the review
page and in chat (see the comments at each entry).
"""

# head -> the head directly above it. A head missing here has no place yet.
HEAD_LADDER = {
    "wound": "injury",
    "injury": None,
}

# Heads that are another head's synonym. Empty on purpose: `trauma` is NOT
# injury -- the curator ruled on 2026-10-02 that "trauma" is the same class as
# `Trauma process` (WONT_0000338), a process. Reading it as injury (Claude's
# assumption of 2026-10-18) merged the model's name `Injury` into `Trauma`, and
# the export resolved 300 wounds to subclasses of a process.
HEAD_SYNONYMS: dict[str, str] = {}

# A head that stands for modifiers + another head.
HEAD_AS = {
    "burn": ({"burn"}, "wound"),              # "a burn is a burn wound"
    "laceration": ({"laceration"}, "wound"),  # "laceration meint immer skin laceration, damit Wunde"
    "abrasion": ({"abrasion"}, "wound"),      # "abrasion im Sinne von skin abrasion ist immer eine Wunde"
    "avulsion": ({"avulsion"}, "injury"),     # "Ausriss ... damit keine Wunde per se"
    "fracture": ({"fracture"}, "injury"),     # page: fracture ⊑ injury; open fracture ⊑ wound
    "frostbite": ({"frostbite"}, "injury"),   # page: ⊑ injury, no burn
    "snakebite": ({"snake", "bite"}, "wound"),   # page: = bite wound
    "blister": ({"blister"}, "wound"),        # chat: "ein blister ist für mich schon eine Wunde, weil die Haut strukturellen Schaden genommen hat"
    "bulla": ({"bulla", "blister"}, "wound"),
    "scald": ({"scald", "thermal"}, "wound"),       # chat: "scald ist thermal wound ohne burn, weil keine Flamme im Spiel"
    "sunburn": ({"sunburn", "radiation"}, "wound"),  # chat: "sunburn ist keine thermal wound ... sondern eine radiation wound"
    "contusion": ({"contusion"}, "injury"),   # page: ⊑ injury, no wound
}

# A modifier that makes the head a wound (page: "offene Fraktur ⊑ wound").
HEAD_PROMOTED_BY = {
    "fracture": ({"open", "compound"}, "wound"),
}

# A modifier implies another (chat: a scald is a thermal wound "ohne burn",
# a sunburn "keine thermal wound und damit keine burn wound": so a burn is a
# thermal wound). Not where the burn is named by another cause.
MOD_IMPLIES = {
    "burn": ({"thermal"}, {"electrical", "chemical", "radiation", "friction"}),
}

# Heads whose place depends on the site (curator 2026-10-18): "skin ulcer ...
# gastric ulcer gibt es ja auch, das ist keine Wunde im Sinne WONT";
# "skin tear ist eine Wunde, tendon tear nicht".
SITE_DEPENDENT_HEADS = {"ulcer", "tear"}
# On skin a wound; with no site: ulcer a wound (page: "gilt als Hautulkus"),
# tear an injury (page: "tear ⊑ injury; perineal tear ⊑ wound").
NO_SITE_HEAD = {"ulcer": "wound", "tear": "injury"}
# Off skin still an injury (a meniscal tear, a burn of the ocular surface); an
# ulcer off skin is neither (a gastric ulcer).
SITE_INJURY_HEADS = {"tear", "burn"}
SKIN_SITE = {
    "skin", "cutaneous", "dermal", "foot", "plantar", "forefoot", "heel", "toe", "leg", "extremity",
    "sacral", "scalp", "penile", "groin", "neck", "perineal",
    # ulcer kinds that sit on skin by definition
    "pressure", "venous", "arterial", "diabetic",
}
NOT_SKIN_SITE = {
    "gastric", "peptic", "duodenal", "oral", "mouth", "corneal", "mucosal", "tendon", "bone", "muscle",
    "bowel", "meniscal", "ligament", "ligamentous", "ocular", "eye", "conjunctival",
}

# Parent heads that are collective names, never a superclass (curator 2026-10-18:
# lesion, skin lesion, cutaneous disorder, wound disorder, defect -> "alle ablehnen").
REFUSED_PARENT_HEADS = {"lesion", "disorder", "defect",
                        "depth",          # page: names on depth are never a superclass
                        "condition"}      # page: `Medical Condition`, `Wound Condition`
# A parent named by how things are divided is a facet, not a kind (page:
# `Burn Wound By Degree`, `Wound By Contamination Level`).
REFUSED_PARENT_PATTERNS = [r"\bby\b"]
# Heads too vague to place anything, as child or parent (chat 2026-10-18:
# "defect gefällt mir gar nicht, ist zu ungenau").
VAGUE_HEADS = {"defect"}

# Whole labels the curator ruled on.
LABEL_REWRITES = {
    "burn lesion": "burn wound",                      # chat: "das ist dasselbe für mich"
    "epidermal detachment": "epidermal detachment blister",
    "malignant fungating lesion": "malignant fungating wound",   # page: = malignant wound
    "ulcus hypertonicus martorell": "hypertensive leg ulcer",    # page: hypertensive leg ulcer ⊑ wound
}
# "a wound with X" is a wound (page: wounds with microbial burden assessed
# according to CDC / IWII are wounds).
WOUND_WITH = r"^(?P<h>.*?\bwounds?)\s+with\s+.*$"
# Labels that name the injuring process, not the wound (chat: "thermal damage
# ist nicht die Wunde, sondern der traumatische Prozess").
PROCESS_LABELS = {"thermal damage"}

# Latin labels with the head word first (page: ulcus cruris = leg ulcer).
LATIN = {
    r"^ulcus cruris (\w+)$": "{0} leg ulcer",
    r"^ulcus cruris$": "leg ulcer",
}
LATIN_WORDS = {"venosum": "venous", "mixtum": "mixed", "arteriosum": "arterial"}

# "<label> according to <system>": what the system implies about the thing
# (page: the CDC wound classes ⊑ surgical wound).
CLASSIFIED_BY = {
    "cdc": {"surgical"},
}

# Spelling of single words before parsing. Not synonyms of concepts: only
# inflection and spelling variants.
WORD_FORMS = {
    "wounds": "wound", "injuries": "injury", "ulcers": "ulcer", "burns": "burn", "tears": "tear",
    "fractures": "fracture", "blisters": "blister", "blistering": "blister",
    "ischaemic": "ischemic", "diabetes-related": "diabetic",
}
