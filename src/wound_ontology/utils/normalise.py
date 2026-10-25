"""ONE normaliser. Every question about how a term is written is asked here.

The curator, 2026-09-26: *why are there several functions for normalising? One
is enough.* There were three -- `normalised_label`, `group_key` and
`character_key`, each hand-rolling the same steps in its own order -- and every
bug in them was the same bug: a new one disagreeing with the old ones about
where a step goes. In one afternoon that produced `Ulcers (DFU)` never reaching
`ulcer` (parenthetical stripped after singularising), `Case` and `cases` read
as different strings (the lookup singulariser instead of the naming one),
`DFU`/`DFUs` held apart (lowercased before the acronym rule could fire), and
`OUTCOME MEASURES` held apart from `outcome measure` (lowercased after it).

So the order of the steps, and what each class of character is worth, live in
exactly one function. It answers three questions about a label at once, because
they are three projections of one pipeline and not three pipelines:

    name    what the term should be CALLED
    key     what two spellings of one term SHARE
    strict  the key, keeping every character `fold` would throw away

A word boundary is not one of the characters a spelling is allowed to differ
in, so `key` and `strict` carry no spaces at all: a hyphen, a space and
nothing are three ways of writing one seam, and `intra-abdominal`,
`intra abdominal` and `intraabdominal` are one term written three ways. The
curator, 2026-09-27, on being asked to adjudicate the last pair by hand: *this
should have been treated by the dehyphenation.* It was not, because
`normalize_term` turns a hyphen into a SPACE, so the dehyphenated spelling
never met the undashed one -- and a U+2011 hyphen is deleted outright instead,
which left `re-tear` folding to `re tear` while `re\u2011tear` folded to
`retear`. The seam is removed LAST, after the head noun is singularised,
because `singular_spelling` needs the words to still be words.

`strict` exists because `normalize_term` strips all punctuation, and that is
how `Na+` meets `NA`, `Phase I/II` meets `Phase III` and `P < 0.05` meets
`P > 0.05`. Two labels with the same `key` and a different `strict` are not two
spellings of one term; they are two terms that met by losing a character.
"""
from __future__ import annotations

import re
from wound_ontology.utils.label_match import fold, singular_spelling
from wound_ontology.utils.spelling import american_spelling

#: `(DFU)`, `(qol)` -- an abbreviation of the phrase, or a sense qualifier on
#: an ontology label. `fold` drops it; pass 0 decides per group which it was.
PARENTHETICAL = re.compile(r"\(([^)]*)\)")

#: `normalize_term` turns the ASCII hyphen and underscore into a space, and its
#: blanket punctuation strip then DELETES every other dash. `re‑tear` in the
#: corpus carries U+2011, invisible in a diff, and `fold` reads it as `retear`.
#: `strict` has to treat dashes the same way or it would flag a group over the
#: very difference folding exists to ignore.
UNICODE_DASHES = re.compile(r"[‐-―]")
ASCII_DASHES = re.compile(r"[-_]")
WHITESPACE = re.compile(r"\s+")

#: Canonical vocabulary chosen by the curator.  These are deliberately small,
#: explicit rules rather than a general synonym table: each one says which of
#: two already-adjudicated names survives.  Inflected forms are listed too
#: because only a label's head noun is singularised.
#:
#: The -ic / -ical pairs are written -ical (curator, 2026-09-28: "exactly the
#: other way"), reversing the 2026-09-27 choice of dermatologic, oncologic,
#: pharmacologic, physiologic and radiologic, and adding biologic -> biological.
#: `numeric -> numerical` was flipped the same day, so every -ic/-ical pair
#: now points to -ical.
CANONICAL_WORDS = {
    "action": "activity",
    "actions": "activities",
    "alteration": "change",
    "alterations": "changes",
    "cutaneous": "skin",
    "biologic": "biological",
    "biologics": "biologicals",
    "dermatologic": "dermatological",
    "evaluation": "assessment",
    "evaluations": "assessments",
    "feature": "characteristic",
    "features": "characteristics",
    "full": "complete",
    "histopathologic": "histopathological",
    "limb": "extremity",
    "limbs": "extremities",
    "microbiological": "microbial",
    "numeric": "numerical",
    "oncologic": "oncological",
    "operation": "surgery",
    "operations": "surgeries",
    "pharmacologic": "pharmacological",
    "physiologic": "physiological",
    "preventative": "preventive",
    "previous": "prior",
    "radiologic": "radiological",
    "specimen": "sample",
    "specimens": "samples",
    "strategy": "approach",
    "strategies": "approaches",
    "technique": "method",
    "techniques": "methods",
    "testing": "test",
    # `trauma -> injury` withdrawn 2026-09-28 (curator: "Trauma into injury
    # is wrong"): a trauma is the event, an injury what it leaves.
    "usage": "use",
    "usages": "uses",
    "value": "level",
    "values": "levels",
}
CANONICAL_WORD = re.compile(
    r"\b(?:" + "|".join(
        sorted(map(re.escape, CANONICAL_WORDS), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

#: Fixed technical terms a preferred word must not reach into (curator,
#: 2026-09-27). `action potential` is electrophysiology, not an activity:
#: `Compound Muscle Action Potentials` had become `Compound Muscle Activity
#: Potential`, found through the first `as_extracted` book read (rule 50).
PROTECTED_PHRASES = re.compile(
    r"\bactions?[\s-]+potentials?\b"
    # A product name, not the adjective: `XCM BIOLOGIC Tissue Matrix`
    # (curator, 2026-09-28).
    r"|\bXCM[\s-]+BIOLOGIC\b",
    re.IGNORECASE)

#: These six choices cross a noun/adjective boundary, so they apply only when
#: the word modifies a following noun-like token.  The blockers are relations
#: and constructions where the word is the head instead (`inflammation in the
#: wound`, `diabetes-related complication`).
CANONICAL_MODIFIERS = {
    "bony": "bone",
    "cellular": "cell",
    "diabetes": "diabetic",
    "infectious": "infection",
    "inflammation": "inflammatory",
    "surgery": "surgical",
}
CANONICAL_MODIFIER = re.compile(
    r"\b(?:" + "|".join(sorted(CANONICAL_MODIFIERS, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)
MODIFIER_FOLLOWER = re.compile(r"^[\s-]+([A-Za-z]+)")
MODIFIER_BLOCKERS = frozenset({
    "after", "and", "as", "associated", "based", "before", "by", "caused",
    "dependent", "during", "for", "from", "in", "induced", "mediated", "of",
    "on", "or", "related", "specific", "to", "versus", "vs", "with", "without",
    # `diabetes mellitus` is one disease name, not a modifier and its head:
    # rule 49 had made 28 names `diabetic mellitus` (found 2026-09-28).
    "mellitus", "insipidus",
})

#: Curator, 2026-09-28 (Naming Rulings, adjectives tab): a leading word that
#: grades or praises is not part of the concept's name -- `massive rotator cuff
#: tear` is a rotator cuff tear, `novel therapeutics` are therapeutics. Stripped
#: from the FRONT only, repeatedly (`severe, extensive burn`), never from a
#: one-word name, never where what follows is a function word (`standard of
#: care`), and never from a name that starts with an exception. The curator's
#: exceptions come first; the second list is fixed names the review page never
#: showed because they were out of scope at the time (`standard deviation`,
#: `multiple sclerosis`, `major adverse limb event`). `small` and `big` are left
#: alone; `giant` is kept and recorded as a subtype instead (no rule here).
LEADING_ADJECTIVES = frozenset(['adequate', 'advanced', 'appropriate', 'better', 'certain', 'conventional', 'current', 'different', 'effective', 'emerging', 'excessive', 'extensive', 'favorable', 'good', 'improved', 'innovative', 'key', 'large', 'main', 'major', 'marked', 'massive', 'mild', 'minor', 'moderate', 'modern', 'multiple', 'new', 'novel', 'optimal', 'poor', 'potential', 'profound', 'proper', 'severe', 'significant', 'standard', 'substantial', 'successful', 'traditional'])
LEADING_ADJECTIVE_EXCEPTIONS = (
    ['current or past', 'current smoker', 'large bowel', 'large intestine', 'large wound', 'major amputation', 'major lower extremity', 'marked improvement', 'mild cognitive impairment', 'minor amputation', 'moderate and severe', 'moderate to severe', 'multiple organ dysfunction syndrome', 'multiple organ failure', 'new zealand']
    + ['multiple sclerosis', 'multiple myeloma', 'standard deviation', 'standard error', 'severe acute respiratory syndrome', 'large language model', 'major adverse', 'key opinion leader', 'traditional chinese medicine', 'advanced glycation end', 'advanced practice', 'new onset', 'new-onset'])
_FUNCTION_WORDS = frozenset({"of", "to", "and", "or", "with", "for", "in", "on",
                             "at", "by", "vs", "versus", "than"})
_LEAD = re.compile(r"^([A-Za-z]+)[\s,-]+(?=\S)")


def _strip_leading_adjectives(label: str) -> str:
    while True:
        m = _LEAD.match(label)
        if not m or m.group(1).lower() not in LEADING_ADJECTIVES:
            return label
        low = WHITESPACE.sub(" ", label.replace("-", " ")).lower()
        if any(low.startswith(e.replace("-", " ")) for e in LEADING_ADJECTIVE_EXCEPTIONS):
            return label
        rest = label[m.end():]
        if not rest or rest.split()[0].lower().strip(",") in _FUNCTION_WORDS:
            return label
        label = rest


#: Curator, 2026-09-28: VAC and vacuum therapy ARE negative pressure wound
#: therapy. Expanded inside compounds too (`VAC dressing`, `incisional NPWT`),
#: so a trailing `therapy`/`treatment` is absorbed rather than doubled. The
#: endoscopic/endoluminal vacuum procedures for gastrointestinal leaks are a
#: different thing and keep their names; bare `vacuum` and `vacuum sealing
#: drainage` is a different technique (curator, 2026-09-28); `negative
#: pressure therapy` is NPWT (same ruling).
NPWT_SYNONYM = re.compile(
    r"\b(?:NPWT|VAC|V\.A\.C\.?|vacuum[\s-]+assisted[\s-]+closure|vacuum(?=[\s-]+therapy)"
    r"|negative[\s-]+pressure(?=[\s-]+(?:therapy|treatment)\b))"
    r"(?:[\s-]+(?:therapy|treatment))?(?![\w-])",
    re.IGNORECASE)
NPWT_EXEMPT_BEFORE = re.compile(r"\b(?:endoscopic|endoluminal)[\s-]+$", re.IGNORECASE)
NPWT = "negative pressure wound therapy"


def _npwt(label: str) -> str:
    def sub(match: re.Match) -> str:
        if NPWT_EXEMPT_BEFORE.search(label[:match.start()]):
            return match.group(0)
        src = match.group(0)
        if match.start() == 0 and src[:1].isupper() and not src.split()[0].isupper():
            return NPWT[:1].upper() + NPWT[1:]
        return NPWT
    return NPWT_SYNONYM.sub(sub, label)


#: Curator, 2026-09-28: a treatment named `... approach`, `... strategy` or
#: `... intervention` is a `... therapy`. Only the HEAD noun is renamed, and
#: never where the word means something else: a search, coping or design
#: strategy is method, a surgical or anterior approach is an access route,
#: pre-/post-intervention is a time point. `therapeutic strategy` and
#: `treatment approach` collapse to `therapy`, and a prevention strategy is
#: prophylaxis, not therapy.
THERAPY_HEAD = re.compile(
    r"(?P<word>approach(?:es)?|strateg(?:y|ies)|interventions?)$", re.IGNORECASE)
THERAPY_PREV = re.compile(r"([A-Za-z]+)[\s-]*$")
THERAPY_NOT_A_TREATMENT = frozenset({
    "search", "coping", "implementation", "grade", "diagnostic", "design",
    "evaluation", "assessment", "research", "sampling", "recruitment",
    "statistical", "analytic", "analytical", "modeling", "modelling",
    "communication", "teaching", "educational", "learning", "management",
    "care", "pre", "post"})
THERAPY_ACCESS_ROUTE = frozenset({
    "surgical", "open", "invasive", "endoscopic", "laparoscopic",
    "arthroscopic", "percutaneous", "endovascular", "robotic", "anterior",
    "posterior", "lateral", "medial", "dorsal", "volar", "transfemoral",
    "transradial", "retrograde", "antegrade"})
THERAPY_COLLAPSE = frozenset({"therapeutic", "treatment", "therapy"})
THERAPY_PROPHYLAXIS = frozenset({"prevention", "preventive", "preventative",
                                 "prophylactic"})


def _therapy_head(label: str) -> str:
    m = THERAPY_HEAD.search(label)
    if not m or (m.start() and not label[m.start() - 1] in " -"):
        return label
    word = m.group("word")
    before = label[:m.start()]
    prev_m = THERAPY_PREV.search(before)
    prev = prev_m.group(1).lower() if prev_m else ""
    if prev in THERAPY_NOT_A_TREATMENT:
        return label
    if word.lower().startswith("approach") and prev in THERAPY_ACCESS_ROUTE:
        return label
    if prev in THERAPY_COLLAPSE or prev in THERAPY_PROPHYLAXIS:
        target = "therapy" if prev in THERAPY_COLLAPSE else "prophylaxis"
        return before[:prev_m.start()] + _with_case_of(prev_m.group(1), target)
    return before + _with_case_of(word, "therapy")


#: Curator, 2026-10-02: "pressure ulcer and pressure injury are the same
#: thing. still, there is sacral pressure ulcer and sacral pressure injury".
#: WONT's label is `Pressure ulcer`; the phrase is rewritten inside every name.
PRESSURE_INJURY = re.compile(r"\b(?P<p>pressure)(?P<sep>[\s-]+)(?P<w>injur(?:y|ies))\b", re.IGNORECASE)


def _pressure_ulcer(label: str) -> str:
    def sub(m: re.Match) -> str:
        w = m.group("w")
        return m.group("p") + m.group("sep") + _with_case_of(
            w, "ulcers" if w.lower().endswith("ies") else "ulcer")
    return PRESSURE_INJURY.sub(sub, label)


#: Curator, 2026-10-04: "leg should be converted to lower extremity always"
#: (the FCA nesting proposals were only leg / foot / lower extremity over
#: again). Rewritten inside every name: `lower leg` and `leg` become `lower
#: extremity`, `legs` `lower extremities`. Kept as written: `upper leg` (the
#: thigh), and fixed names of instruments, tests, exercises, procedures and
#: programmes, read one by one on 2026-10-04 from the 356 names that use the
#: word. A WONT/MILD label keeps its own word (pass 0 keeps labels as
#: written, so `venous lower extremity ulcer` joins `Venous leg ulcer`).
LEG_WORD = re.compile(r"\b(?:(?P<lower>lower)(?P<sep>[\s-]+))?(?P<w>legs?)\b", re.IGNORECASE)
LEG_KEEP = re.compile(
    r"\bupper[\s-]+legs?\b"
    r"|\bface,?[\s-]+legs,?[\s-]+activity\b"
    r"|\bleg[\s-]+ulcer[\s-]+measurement[\s-]+tool\b"
    r"|\bvenous[\s-]+leg[\s-]+ulcer[\s-]+self-efficacy[\s-]+tool\b"
    r"|\bleg[\s-]+clubs?\b"
    r"|\beuropean[\s-]+leg[\s-]+ulcer[\s-]+series\b"
    r"|\bhealing[\s-]+of[\s-]+excisional[\s-]+wounds[\s-]+on[\s-]+lower[\s-]+legs\b"
    r"|\bs2k[\s-]+guideline[\s-]+on[\s-]+venous[\s-]+leg[\s-]+ulcers?\b"
    r"|\bstraight[\s-]+leg[\s-]+raises?\b"
    r"|\b(?:single|short|cross|between)-legs?\b"
    r"|\bshort[\s-]+leg[\s-]+(?:polypropylene[\s-]+)?splints?\b"
    r"|\bleg[\s-]+(?:press|extensions?|cycling|muscle[\s-]+pump)\b"
    r"|\bcross[\s-]+leg\b",
    re.IGNORECASE)


def _lower_extremity(label: str) -> str:
    keep = [m.span() for m in LEG_KEEP.finditer(label)]

    def sub(m: re.Match) -> str:
        if any(a <= m.start("w") < b for a, b in keep):
            return m.group(0)
        plural = m.group("w").lower() == "legs"
        out = _with_case_of(m.group("w"), "lower extremities" if plural else "lower extremity")
        if m.group("lower"):
            # `lower leg` -> `lower extremity`, written in the case of `lower`
            out = _with_case_of(m.group("lower"), "lower") + m.group("sep") + out.split(" ", 1)[1] \
                if m.group("w")[0].isupper() == m.group("lower")[0].isupper() else out
            return out
        return out
    return LEG_WORD.sub(sub, label)


#: Curator, 2026-10-04: "ulceration" is the same as "ulcer". Rewritten inside
#: every name (`venous leg ulceration` -> `venous leg ulcer`).
ULCERATION = re.compile(r"\b(?P<w>ulcerations?)\b", re.IGNORECASE)


def _ulceration(label: str) -> str:
    return ULCERATION.sub(lambda m: _with_case_of(
        m.group("w"), "ulcers" if m.group("w").lower().endswith("s") else "ulcer"), label)


#: Curator, 2026-10-18: "ich war eigentlich auch schon vor einiger Zeit klar in
#: meiner Aussage, dass ulcer eine Wunde ist, da sollte nicht mehr ulcer überall
#: stehen" (on `Ulcer Diagnosis`, `Ulcer Event`, `Ulcer Prevention`). So inside
#: every name `ulcer(s)` -> `wound(s)`, except where the word is not the wound:
#: an ulcer off skin ("gastric ulcer ... ist keine Wunde im Sinne WONT"), a fixed
#: eponymous name, and the name of an instrument, scale, study or guideline.
#: A WONT/MILD label is never renamed (pass 0 keeps labels as written).
ULCER_WORD = re.compile(r"\b(?P<w>ulcers?)\b", re.IGNORECASE)
ULCER_KEEP = re.compile(
    r"\b(gastric|gastroduodenal|peptic|duodenal|stomal|esophageal|oesophageal|intestinal|colonic|"
    r"rectal|anal|oral|mouth|aphthous|corneal|mucosal|genital|vulvar|stress|"
    r"marjolin|martorell|kennedy|buruli|curling|cushing|meleney|rodent|lipsch\w*|"
    r"tool|scale|score|series|classification|questionnaire|index|instrument|trial|study|"
    r"guideline|guidelines|panel|association|registry|self-efficacy)\b",
    re.IGNORECASE)


#: WONT's own labels that use the word (rule 61: pressure injury is pressure
#: ulcer): a name built on one keeps it, so `Heel pressure ulcer` stays under
#: `Pressure ulcer` instead of becoming a `pressure wound` beside it.
ULCER_LABEL_PHRASES = re.compile(
    r"\b(pressure ulcers?|diabetic foot ulcers?|arterial leg ulcers?|marjolin ulcers?)\b", re.IGNORECASE)
DOUBLE_WOUND = re.compile(r"\b(wounds?) (?P<w>wounds?)\b", re.IGNORECASE)


def _ulcer_to_wound(label: str) -> str:
    if not ULCER_WORD.search(label) or ULCER_KEEP.search(label) or ULCER_LABEL_PHRASES.search(label):
        return label
    out = ULCER_WORD.sub(lambda m: _with_case_of(
        m.group("w"), "wounds" if m.group("w").lower().endswith("s") else "wound"), label)
    return DOUBLE_WOUND.sub(lambda m: m.group("w"), out)          # `ulcer wound` -> `wound`


#: Curator, 2026-10-04: "we should do something against the ulcer vs. wound
#: synonym" -- `X ulcer` and `X wound` are one term. Applied to what two
#: spellings SHARE (`Normalised.key`, `.strict`), never to the name: pass 0
#: groups them and elects one name (an ontology label first, then the
#: spelling more abstracts use), so a lone `gastric ulcer` keeps its word.
ULCER_AS_WOUND = re.compile(r"\bulcers?\b")


def _ulcer_is_wound(folded: str) -> str:
    return _burn_is_burn_wound(ULCER_AS_WOUND.sub("wound", folded))


#: Curator, 2026-10-18: "es braucht nicht burn lesion und burn wound, das ist
#: dasselbe für mich"; "a burn is a burn wound"; a burn is a thermal wound
#: (flame), so `thermal burn` is a burn. Like ulcer and wound (rule 70) this
#: is applied to what two spellings SHARE, never to a name: pass 0 groups
#: `burn care` with `burn wound care` and elects one name (an ontology label
#: first, then the spelling more abstracts use). `burn injury` is NOT one of
#: them: a burn wound is a burn injury, not the other way round (rule 79).
BURN_AS_BURN = re.compile(r"(?<!non-)(?<!non )\b(?:thermal )?burns? (?:wounds?|lesions?)\b"
                          r"|(?<!non-)(?<!non )\bthermal burns?\b")   # `non-burn wound` is not `non-thermal burn`


def _burn_is_burn_wound(folded: str) -> str:
    return BURN_AS_BURN.sub("burn", folded)


#: Curator, 2026-10-02: "illness, disorder, pathology, disease, condition and
#: dysfunction are used completely interchangably" -- "disorder wins.
#: condition can stay where it is a condition." Rewritten inside every name;
#: a WONT/MILD label keeps its own word (pass 0 keeps labels as written, so
#: `autoimmune disorder` joins the label `Autoimmune disease`). Kept as written:
#: an eponymous disease (`Crohn's disease`, `Buerger disease`); fixed names
#: (`multiple organ dysfunction syndrome`, `critical illness`,
#: `tick-associated rash illness`, `illness perception`); `pathology` the
#: discipline (`surgical pathology`, `pathology report`). `condition` becomes
#: `disorder` only in the names in DISORDER_CONDITION, read one by one on
#: 2026-10-02 from the 233 names that use it; `wound condition`, `hypoxic
#: condition`, `culture condition` and the like name a state and stay.
DISORDER_WORD = re.compile(
    r"\b(?P<w>diseases?|illness(?:es)?|patholog(?:y|ies)|dysfunctions?)\b", re.IGNORECASE)
DISORDER_EPONYM_BEFORE = re.compile(
    r"(?:'s|’s|\b(?:addison|alzheimer|behcet|bowen|buerger|chagas|charcot-marie-tooth|crohn|"
    r"cushing|dupuytren|graves|hansen|hirschsprung|hodgkin|huntington|kawasaki|kienbock|"
    r"kummell|legg-calve-perthes|lyme|osgood-schlatter|paget|parkinson|peyronie|peyronies|"
    r"raynaud|sjogren|whipple|wilson))[\s-]+$", re.IGNORECASE)
DISORDER_KEEP = re.compile(
    r"\bmulti(?:ple)?[\s-]*organ[\s-]+dysfunction[\s-]+syndromes?\b"
    r"|\bcritical[\s-]+illness(?:es)?\b"
    r"|\btick-associated[\s-]+rash[\s-]+illness\b"
    r"|\billness[\s-]+(?:perception|experience|belief|trajectory)\b"
    r"|\b(?:forensic|surgical|final|oral|cell)[\s-]+patholog(?:y|ies)\b"
    r"|\bpatholog(?:y|ies)[\s-]+(?:report|result|assessment|department|examination)s?\b"
    r"|\bpatholog(?:y|ies)-(?:guided|validated|triggered|timing)\b"
    # proper names of institutions, classifications and instruments (found
    # 2026-10-02: `Centers for Disorder Control and Prevention`)
    r"|\bcenters?[\s-]+for[\s-]+disease[\s-]+control\b"
    r"|\bburden[\s-]+of[\s-]+diseases?\b"
    r"|\bclassification[\s-]+of[\s-]+diseases?\b"
    r"|\bdiseases?[\s-]+society[\s-]+of[\s-]+america\b"
    r"|\binfection[\s-]+diseases[\s-]+and[\s-]+travel[\s-]+medicine\b"
    r"|\bdigestive[\s-]+and[\s-]+kidney[\s-]+diseases?\b"
    r"|\bocular[\s-]+surface[\s-]+disease[\s-]+index\b"
    r"|\bperi-implant[\s-]+diseases[\s-]+and[\s-]+conditions?\b"
    # fixed terms that are not the name of a disease (found 2026-10-02 in the
    # abbreviations written out: DMARD, COVID-19)
    r"|\bdisease[\s-]+modifying\b"
    r"|\bcoronavirus[\s-]+disease\b",
    re.IGNORECASE)
DISORDER_CONDITION = frozenset({
    "skin condition", "chronic condition", "diabetic condition", "comorbid condition",
    "health condition", "inflammatory condition", "neurosurgical condition",
    "dermatological condition", "life-threatening condition", "debilitating condition",
    "infection condition", "acute condition", "ischemic condition", "autoinflammatory condition",
    "degenerative condition", "rare condition", "neurological condition", "long-term condition",
    "pathological condition", "musculoskeletal condition", "extremity-threatening condition",
    "neuropathic condition", "medical condition", "underlying condition", "neuromuscular condition",
    "cardiovascular condition", "otorhinolaryngological condition", "febrile condition",
    "ear condition", "orthopedic condition", "serious medical condition", "autoimmune condition",
    "rare congenital condition", "long-term neurological condition", "iatrogenic condition",
    "geriatric condition", "pre-existing metabolic condition", "neuropathy-induced condition",
    "foot-related condition", "comorbid chronic condition", "diabetes-related foot condition",
    "emergency general surgical condition", "brain condition", "debilitating medical condition",
    "pre-existing condition", "desquamating skin condition", "blistering skin condition",
    "refractory condition", "monogenic condition", "pulmonary condition", "common oral condition",
    "sinus condition", "cardiac, pulmonary, or renal condition", "neurologic condition",
    "oncological condition", "dental condition", "immune-related condition",
    "pre-existing chronic condition", "chronic overuse condition", "malignant condition",
    "physical health condition", "neurodevelopmental condition", "immune-mediated condition",
    "underlying health condition", "intermittent autoimmune condition", "underlying medical condition",
    "abnormal skin condition", "urinary condition", "degenerative and inflammatory condition",
    "meniscal condition", "pathologic condition", "chronic joint condition",
    "chronic autoinflammatory condition", "autoimmune skin condition", "long-term health condition",
    "predisposing condition", "exclusionary medical condition", "prolonged medical condition",
    "serious underlying medical condition", "metabolic condition", "oral condition",
    "periodontal condition", "vascular condition", "respiratory condition",
    "critical ischemic condition", "distressing condition", "orthopaedic condition",
})
CONDITION_WORD = re.compile(r"\b(?P<w>conditions?)\b", re.IGNORECASE)


def _disorder(label: str) -> str:
    keep = [m.span() for m in DISORDER_KEEP.finditer(label)]

    def sub(m: re.Match) -> str:
        if any(a <= m.start() < b for a, b in keep):
            return m.group(0)
        w = m.group("w")
        if w.lower().startswith("disease") and DISORDER_EPONYM_BEFORE.search(label[:m.start()]):
            return m.group(0)
        plural = w.lower().endswith(("s", "ies")) and not w.lower().startswith("illness") \
            or w.lower().startswith("illnesses")
        return _with_case_of(w, "disorders" if plural else "disorder")

    label = DISORDER_WORD.sub(sub, label)
    if " ".join(label.lower().replace("conditions", "condition").split()) in DISORDER_CONDITION:
        label = CONDITION_WORD.sub(
            lambda m: _with_case_of(m.group("w"),
                                    "disorders" if m.group("w").lower().endswith("s") else "disorder"),
            label)
    return label


WOUND_MANAGEMENT = re.compile(
    r"(?P<prefix>\bwound[\s-]+)(?P<word>management)\b", re.IGNORECASE)
POSTSURGICAL = re.compile(r"\bpost(?:[\s-]+)?surgical\b", re.IGNORECASE)


def _with_case_of(source: str, replacement: str) -> str:
    """Write `replacement` with the ordinary casing pattern of `source`."""
    if source.isupper():
        return replacement.upper()
    if source.istitle():
        return replacement.title()
    return replacement


def canonical_vocabulary(label: str) -> str:
    """Apply the curator's unambiguous preferred-name rules to `label`.

    `management` is changed only in the phrase `wound management`; a general
    management/care rewrite would conflate many unrelated concepts.  Word
    boundaries keep `limbic` and similar words out.  The function preserves
    lower, title and upper case and is idempotent.
    """
    label = _strip_leading_adjectives(label)
    label = _npwt(label)
    label = _therapy_head(label)
    label = _pressure_ulcer(label)
    label = _ulceration(label)
    label = _lower_extremity(label)
    label = _disorder(label)
    label = WOUND_MANAGEMENT.sub(
        lambda match: (match.group("prefix")
                       + _with_case_of(match.group("word"), "care")),
        label,
    )
    label = POSTSURGICAL.sub(
        lambda match: _with_case_of(match.group(0), "postoperative"), label)
    protected = [m.span() for m in PROTECTED_PHRASES.finditer(label)]

    def word(match: re.Match) -> str:
        if any(start <= match.start() < end for start, end in protected):
            return match.group(0)
        return _with_case_of(match.group(0), CANONICAL_WORDS[match.group(0).lower()])

    label = CANONICAL_WORD.sub(word, label)

    def modifier(match: re.Match) -> str:
        follower = MODIFIER_FOLLOWER.match(label[match.end():])
        if not follower or follower.group(1).lower() in MODIFIER_BLOCKERS:
            return match.group(0)
        return _with_case_of(
            match.group(0), CANONICAL_MODIFIERS[match.group(0).lower()])

    label = CANONICAL_MODIFIER.sub(modifier, label)
    # last, so the label phrases it keeps are seen in their final spelling
    # (`diabetes foot ulcer` is `diabetic foot ulcer` by now, and stays); a
    # changed name goes through the rules once more (`ulcer management` ->
    # `wound management` -> `wound care`), which keeps the function idempotent
    out = _ulcer_to_wound(label)
    return canonical_vocabulary(out) if out != label else out


#: Chemical element symbols keep their capital (`Zn`, `Ag`). Left out are the
#: symbols that are also English words a Title Case string capitalises (`In`,
#: `As`, `At`, `Be`, `No`, `He`, `Co`): there the capital says nothing.
ELEMENT_SYMBOLS = frozenset("""
    Ac Ag Al Ar Au Ba Bi Bk Br Ca Cd Ce Cf Cl Cm Cn Cr Cs Cu Db Ds Dy Er Es Eu Fe Fl Fm Fr Ga Gd
    Ge Hf Hg Ho Hs Ir Kr La Li Lr Lu Lv Mc Md Mg Mn Mo Mt Na Nb Nd Ne Nh Ni Np Og Os Pa Pb Pd Pm
    Po Pr Pt Pu Ra Rb Re Rf Rg Rh Rn Ru Sb Sc Se Sg Si Sm Sn Sr Ta Tb Tc Te Th Ti Tl Tm Ts Xe Yb Zn Zr
""".split())

_CASE_WORD = re.compile(r"[A-Za-z][A-Za-z']*")


def sentence_case(label: str) -> str:
    """`label` in lowercase with a capital first letter, abbreviations and names kept.

    Curator, 2026-10-24: names are written the way WONT writes its labels --
    `Surgical debridement`, `Methicillin-resistant Staphylococcus aureus
    infection`. Before this, the writer's own case was kept, which left 1,101
    Title Case names (`3S Intraoperative Pressure Ulcer Risk Assessment Scale`)
    beside 38,888 lowercase ones.

    Only a word written with ONE capital, at its start, is ever lowercased. A
    word with a capital anywhere else (`MRSA`, `pH`, `mRNA`, `NaCl`, `IL-6`'s
    `IL`), a digit (`Ki67`, `3D`) or a single letter (`T cell`, `vitamin C`) is
    an abbreviation or a symbol and is left exactly as written. A capitalised
    word after the first keeps its capital when it is a name: it is in
    `PROPER_NOUNS`, read off the corpus by `scripts/build_proper_nouns.py`
    (`Staphylococcus`, `Doppler`, `Braden`), or it is a chemical element symbol
    (`Zn`). A name the corpus has seen too rarely for the list loses its capital
    mid-name (`Family aerococcaceae`). "The language does not know the word"
    was tried as a third test and dropped: on the 2026-10-20 term dict half the
    capitalised words `wordfreq` has never seen are names (`Rammelt`, `Judet`)
    and half are jargon (`Photobiomodulation`, `Neuraxial`), and a capital a
    Title Case string gave every word could not be told from a chosen one, so
    the function was not idempotent with it (`dermal Micrograft`).

    The first letter is raised only when the first word is plain lowercase
    ASCII, so `pH value`, `mRNA` and `β-lactam` keep their first letter.
    Idempotent: a second pass finds nothing left to lower.
    """
    from wound_ontology.utils.proper_nouns import PROPER_NOUNS

    def word(match: re.Match) -> str:
        w = match.group(0)
        core = re.sub(r"'s?$", "", w)
        if match.start() == 0 or len(core) < 2 or not core[0].isupper() \
                or any(c.isupper() for c in core[1:]) or re.fullmatch(r"[A-Z]s", core):
            return w                    # `[A-Z]s`: a letter's plural, `the 5 Ps`
        if core.lower() in PROPER_NOUNS or core in ELEMENT_SYMBOLS:
            return w
        if len(core) <= 3 and re.match(r"-?\d", label[match.end():]):
            return w                    # a gene or protein symbol: `Bcl-2`, `Ki-67`
        return w.lower()

    out = _CASE_WORD.sub(word, label)
    first = _CASE_WORD.match(out)
    if first and first.group(0).isascii() and first.group(0).islower():
        out = out[0].upper() + out[1:]
    return out


class Normalised:
    """What one label is called, what it shares, and what it keeps.

    The three are computed on first use and then held, because the ingestion
    path asks 179,000 times for `name` alone and has no use for the other two.
    """

    __slots__ = ("label", "_name", "_key", "_strict")

    def __init__(self, label: str) -> None:
        self.label = label
        self._name: str | None = None
        self._key: str | None = None
        self._strict: str | None = None

    @property
    def name(self) -> str:
        """What the term should be CALLED.

        Singular head noun (rule 23a), British to American (rule 41), the
        curator's preferred vocabulary (rules 48–49), then the case
        (`sentence_case`), in that order. `Statistical Analyses` becomes
        `Statistical analysis` and the noun never reaches the British-verb
        reading of `analyses` that `breame` answers with `analyzes`. Case
        comes last because the singular rule reads it (`DFUs` is an acronym
        plural only while it has its capitals). Any parenthetical is kept,
        because on an ontology label it is part of the official name (`vitamin
        (role)`). A BFO category is spelled the way BFO spells it (rule 22).
        """
        if self._name is None:
            from wound_ontology.llm.category_vocab import declared_category
            # Asked twice, because the singular rule can make a category of a
            # plural (`processes`, `multiple roles`) that only then is one.
            named = sentence_case(canonical_vocabulary(
                american_spelling(singular_spelling(self.label))))
            self._name = declared_category(self.label) or declared_category(named) or named
        return self._name

    @property
    def key(self) -> str:
        """What two spellings of one term SHARE.

        `fold` lowercases, drops the parenthetical, flattens hyphens, strips
        the remaining punctuation and singularises the head again; then every
        word boundary goes, so a seam written as a hyphen, as a space or as
        nothing at all reads the same. Built on the NAME rather than the raw
        label so the British and singular rules are already applied and two
        spellings cannot disagree about them.
        """
        if self._key is None:
            self._key = WHITESPACE.sub("", _ulcer_is_wound(fold(self.name)))
        return self._key

    @property
    def strict(self) -> str:
        """The key, keeping every character `fold` would throw away.

        The parenthetical goes first, or the singulariser is handed `(dfu)` as
        the head noun and `Ulcers (DFU)` never reaches `ulcer`. Dashes are
        treated exactly as `normalize_term` treats them, or this would flag a
        group over the very difference folding exists to ignore. Then the head
        is singularised on BOTH sides of the lowercasing, because
        `singular_spelling` reads case and the two all-caps rules pull opposite
        ways: `DFUs` is an acronym plural only while it still has its capitals,
        and `OUTCOME MEASURES` only stops being exempt from rule 23a once it
        loses them. Safe to apply twice -- the function is unchanged on an
        already-singular head. The spaces go last, with `key`'s, or a group
        `key` merged over a seam would be split straight back apart by the
        very difference it was merged over.
        """
        if self._strict is None:
            bare = PARENTHETICAL.sub("", self.label)
            bare = ASCII_DASHES.sub(" ", UNICODE_DASHES.sub("", bare))
            bare = WHITESPACE.sub(" ", bare).strip()
            self._strict = WHITESPACE.sub("", _ulcer_is_wound(canonical_vocabulary(
                american_spelling(
                    singular_spelling(singular_spelling(bare).lower()))).lower()))
        return self._strict

    def __repr__(self) -> str:                          # pragma: no cover
        return f"Normalised({self.label!r})"


def normalise(label: str) -> Normalised:
    """The one answer. See the module docstring for what each field is for."""
    return Normalised(label)
