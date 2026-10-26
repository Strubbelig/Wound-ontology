# -*- coding: utf-8 -*-
"""Head-word category rules: the curator's rulings on the Signature Words page.

Curator, 2026-09-29: "whenever there is injury as a last word, that is a
material entity. Whenever there is inflammation or infection, that is a
process. make a list of signature words and ask me that first." The page
(https://claude.ai/artifact/2HY2b1T2FzQnts16CDcBFX) listed the 82 head words of
the terms whose abstracts typed them irreconcilably; these are the answers.

The head word is the word before the first preposition, else the last word
(`wound infection`, `infection of the wound` -> `infection`); see
`scripts/apply_category_rulings.py:head`.

REACH (curator, 2026-09-29, after the measurement): a head rule decides only a
term whose abstracts DISAGREE irreconcilably -- 597 terms. It does not overturn
a term every abstract typed the same way (2,406 would have flipped), a
WONT/MILD class (its category is the ontology's), or a term ruled on its own
(the Category Rulings page), which outranks it.

Rechecked 2026-09-29, the first answer in the comment:
  pressure   information entity -> quality   (PATO; 'pressure' itself ruled a process)
  procedure  plan specification -> process   ('surgical procedure' ruled a process)
  pathway    process boundary   -> process   (a boundary is an instant)
  survival   process boundary   -> process
  pain       immaterial entity  -> quality   (immaterial entity = cavity, site, boundary)
  time       'time interval'    -> temporal region (BFO_0000008, added as a category)

`OUT` heads put every term with that head out of scope (a gate decision, not
a category): `involvement` (generic), `ssi` (the abbreviation).
Not ruled: `anesthesia`, `scarring`.
"""

HEAD_CATEGORY: dict[str, str] = {
    "activity": "function",
    "amputation": "process",
    "antibiotic": "material entity",
    "application": "process",
    "assessment": "process",
    "avulsion": "material entity",
    "biopsy": "process",          # material entity until 2026-10-26; the curator: the procedure
    "bite": "process",
    "burn": "material entity",
    "care": "process",
    "change": "process",
    "closure": "process",
    "colonization": "process",
    "complication": "material entity",
    "contamination": "process",
    "control": "information entity",          # "plan specification"
    "coverage": "process",
    "damage": "immaterial entity",
    "dehiscence": "immaterial entity",
    "disease": "material entity",
    "drainage": "process",
    "dressing": "material entity",
    "dysfunction": "process",
    "effect": "function",
    "exposure": "immaterial entity",
    "expression": "process",
    "failure": "specifically dependent continuant",
    "fracture": "material entity",
    "graft": "material entity",
    "healing": "process",
    "homeostasis": "process",
    "hygiene": "process",
    "incision": "immaterial entity",
    "infection": "process",
    "inflammation": "process",
    "injury": "material entity",
    "intake": "process",
    "irritation": "process",
    "ischemia": "process",
    "loss": "process",
    "mechanism": "information entity",
    "method": "information entity",           # "plan specification"
    "morbidity": "material entity",
    "necrosis": "material entity",
    "occlusion": "process",
    "outcome": "information entity",
    "pain": "quality",                        # rechecked
    "pathway": "process",                     # rechecked
    "perfusion": "process",
    "persistence": "process",
    "pressure": "quality",                    # rechecked
    "procedure": "process",                   # rechecked
    "process": "process",
    "program": "information entity",          # "plan specification"
    "prophylaxis": "information entity",      # "plan specification"
    "rate": "information entity",
    "reaction": "material entity",
    "recurrence": "process",
    "reduction": "process",
    "release": "process",
    "response": "process",
    "rupture": "immaterial entity",
    "stress": "information entity",           # answered "generically dependent continuant"
    "stroke": "material entity",
    "surgery": "process",
    "survival": "process",                    # rechecked
    "suture": "material entity",
    "symptom": "specifically dependent continuant",
    "therapy": "process",
    "thrombosis": "material entity",
    "time": "temporal region",                # rechecked: "time interval"
    "trauma": "process",
    "treatment": "process",
    "ulcer": "material entity",
    "ulceration": "material entity",
    "ultrasound": "process",
    "union": "process",
    "use": "process",
}

HEAD_OUT: frozenset[str] = frozenset({"involvement", "ssi"})
