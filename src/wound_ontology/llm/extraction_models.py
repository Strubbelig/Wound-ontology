# -*- coding: utf-8 -*-
"""GENERATED FILE - DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_extraction_schema.py
Source of truth:  mild.ttl (MILD) + ground_truth_final.owl (WONT)
Generated:        2026-10-24

Mirrors config/extraction_schema.yaml. Emitted directly rather than via
`gen-pydantic` so the pipeline has no hard dependency on the linkml generator;
the LinkML file stays the declarative source of truth and remains gen-owl ready.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class BFOCategory(str, Enum):
    """The one categorical choice made per extracted term."""

    Continuant = 'continuant'
    Occurrent = 'occurrent'
    IndependentContinuant = 'independent continuant'
    SpecificallyDependentContinuant = 'specifically dependent continuant'
    RealizableEntity = 'realizable entity'
    MaterialEntity = 'material entity'
    ImmaterialEntity = 'immaterial entity'
    Quality = 'quality'
    Disposition = 'disposition'
    Function = 'function'
    Role = 'role'
    Tendency = 'tendency'
    InformationEntity = 'information entity'
    Process = 'process'
    ProcessBoundary = 'process boundary'
    TemporalRegion = 'temporal region'


CATEGORY_IRI: dict[str, str] = {
    'continuant': 'http://purl.obolibrary.org/obo/BFO_0000002',
    'occurrent': 'http://purl.obolibrary.org/obo/BFO_0000003',
    'independent continuant': 'http://purl.obolibrary.org/obo/BFO_0000004',
    'specifically dependent continuant': 'http://purl.obolibrary.org/obo/BFO_0000020',
    'realizable entity': 'http://purl.obolibrary.org/obo/BFO_0000017',
    'material entity': 'http://purl.obolibrary.org/obo/BFO_0000040',
    'immaterial entity': 'http://purl.obolibrary.org/obo/BFO_0000141',
    'quality': 'http://purl.obolibrary.org/obo/BFO_0000019',
    'disposition': 'http://purl.obolibrary.org/obo/BFO_0000016',
    'function': 'http://purl.obolibrary.org/obo/BFO_0000034',
    'role': 'http://purl.obolibrary.org/obo/BFO_0000023',
    'tendency': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120005',
    'information entity': 'http://purl.obolibrary.org/obo/BFO_0000031',
    'process': 'http://purl.obolibrary.org/obo/BFO_0000015',
    'process boundary': 'http://purl.obolibrary.org/obo/BFO_0000035',
    'temporal region': 'http://purl.obolibrary.org/obo/BFO_0000008',
}

CATEGORY_GLOSS: dict[str, str] = {
    'continuant': 'FALLBACK. Something that persists through time and is wholly present whenever it exists. Use only when you cannot tell which kind of continuant it is.',
    'occurrent': 'FALLBACK. Something that happens or unfolds in time. Use only when you cannot tell which kind of occurrent it is.',
    'independent continuant': 'FALLBACK. A continuant that does not depend on a bearer. Use only when you cannot tell material from immaterial.',
    'specifically dependent continuant': 'FALLBACK. A continuant that must inhere in a bearer. Use only when you cannot tell which kind of dependent continuant it is.',
    'realizable entity': 'A dependent continuant realized in a process. Use directly only for things like plans; otherwise prefer disposition, function, role or tendency.',
    'material entity': 'A material thing: a body part, an organism, a substance, a disorder, a device.',
    'immaterial entity': 'An immaterial continuant such as a cavity, a site or a boundary.',
    'quality': 'A way a thing is, fully exhibited whenever it is present: a colour, a size, a degree.',
    'disposition': 'A tendency to behave a certain way under given conditions, grounded in physical makeup; it may never be realized.',
    'function': 'A disposition the bearer exists in order to have, by design or by selection.',
    'role': 'Something a thing has only because of context or convention, and could lose without changing.',
    'tendency': 'Raises the objective probability of an outcome without necessitating it. Use for predispositions and risk factors.',
    'information entity': 'Information: a datum, a specification, a classification result, a scale, a plan specification.',
    'process': 'Something that happens and unfolds over time; it has temporal parts.',
    'process boundary': 'The instantaneous start or end of a process.',
    'temporal region': 'A stretch or point of time over which processes unfold: an operative time, a hospital stay, a follow-up period. Not the process that happens in it.',
}

# The BFO subsumption tree over the categories. Every extracted term is
# subsumed under one of these, so a new discovery always lands somewhere in BFO.
CATEGORY_PARENT: dict[str, str | None] = {
    'continuant': None,
    'occurrent': None,
    'independent continuant': 'continuant',
    'specifically dependent continuant': 'continuant',
    'realizable entity': 'specifically dependent continuant',
    'material entity': 'independent continuant',
    'immaterial entity': 'independent continuant',
    'quality': 'specifically dependent continuant',
    'disposition': 'realizable entity',
    'function': 'disposition',
    'role': 'realizable entity',
    'tendency': 'realizable entity',
    'information entity': 'continuant',
    'process': 'occurrent',
    'process boundary': 'occurrent',
    'temporal region': 'occurrent',
}

# Coarse categories are legitimate answers, not failures: a model unsure
# whether something is a process or a material entity should retreat to
# occurrent or continuant rather than guess. They are flagged for refinement.
COARSE_CATEGORIES: frozenset[str] = frozenset({
    'continuant',
    'occurrent',
    'independent continuant',
    'specifically dependent continuant',
    'realizable entity',
})


def category_ancestors(category: str) -> list[str]:
    """The category itself, then each BFO parent up to the root."""
    out, cur = [], category
    while cur is not None:
        out.append(cur)
        cur = CATEGORY_PARENT.get(cur)
    return out


def category_descendants(category: str) -> set[str]:
    """The category plus every category beneath it."""
    out = {category}
    changed = True
    while changed:
        changed = False
        for child, parent in CATEGORY_PARENT.items():
            if parent in out and child not in out:
                out.add(child)
                changed = True
    return out


def is_refinement_of(fine: str, coarse: str) -> bool:
    """True if `fine` sits at or below `coarse` — i.e. refining is consistent."""
    return coarse in category_ancestors(fine)


# ── Grounding vocabularies, one per category ──────────────────────────────
# label -> IRI, for terms that already exist in MILD/WONT.
GROUNDING: dict[str, dict[str, str]] = {
    'occurrent': {
        'spatiotemporal region': 'http://purl.obolibrary.org/obo/BFO_0000011',
    },
    'realizable entity': {
        'treatment plan': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120090',
    },
    'material entity': {
        'fiat object part': 'http://purl.obolibrary.org/obo/BFO_0000024',
        'object aggregate': 'http://purl.obolibrary.org/obo/BFO_0000027',
        'object': 'http://purl.obolibrary.org/obo/BFO_0000030',
        'Developed material disease entity': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120001',
        'unknown-disorder disease': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120007',
        'genetic variant': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120009',
        'pathogenic genetic variant': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120013',
        'material disease entity': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120020',
        'pathological disorder': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120022',
        'Abdominal drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000002',
        'Activated carbon layer wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000005',
        'Active drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000006',
        'Adhesive silicone grid': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000008',
        'Antiseptic alcohol': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000010',
        'Alginate containing wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000011',
        'ANCA-associated Vasculitis': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000013',
        'Angiopathic wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000015',
        'Antiseptic dye': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000020',
        'Antiseptic halogen-releasing compound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000021',
        'Antiseptic metal ion': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000022',
        'Antiseptic phenol derivative': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000025',
        'Antiseptic solution': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000026',
        'Arterial leg ulcer': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000027',
        'Autoimmune disease related wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000033',
        'Bepanthen ointment': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000037',
        'Biosynthetic cellulose': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000042',
        'Bismuth III bromide': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000043',
        'Bite wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000044',
        'Blake drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000045',
        'Blistering skin wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000046',
        'Bovine collagen containing wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000047',
        'Bromelain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000048',
        'Bullosis diabeticorum': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000049',
        'Bullous impetigo': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000050',
        'Bülau drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000057',
        'Capillary drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000058',
        'Cat bite wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000060',
        'Cellulose acetate mesh impregnated with a petrolatum emulsion': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000061',
        'Clean-contaminated wound according to CDC': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000067',
        'Clean wound according to CDC': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000068',
        'Closed drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000071',
        'Contaminated wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000078',
        'Continuous suture': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000079',
        'Diabetic wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000088',
        'Dog bite wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000091',
        'Drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000093',
        'Dry necrosis': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000095',
        'Easy-Flow drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000096',
        'Elastic bandage': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000097',
        'Epithelializing wound bed': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000101',
        'Fat gauze': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000107',
        'Fibrin coating of the wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000108',
        'Fibrin-covered wound bed': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000109',
        'fistula': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000110',
        'Fixed drug exanthema': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000111',
        'Fixing bandage': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000112',
        'Flaminal': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000113',
        "Fournier's gangrene": 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000115',
        'Friction bubble': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000116',
        'Full-thickness skin graft': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000117',
        'Gauze bandage': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000120',
        'Granulating wound bed': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000131',
        'Gravity drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000133',
        'Hematoma': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000141',
        'High-vacuum drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000145',
        'Horizontal mattress suture': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000147',
        'Human bite wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000148',
        'Hydrocolloid containing wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000149',
        'Hydrofiber-containing wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000150',
        'Hydrogel containing wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000151',
        'Hypergranulation': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000153',
        'Immunosuppression': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000161',
        'Incision foil': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000162',
        'Infected wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000163',
        'Intact wound margin': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000165',
        'Intracutaneous suture': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000166',
        'Iodine ointment': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000168',
        'Jackson-Pratt drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000170',
        'Linear IgA dermatosis': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000173',
        'Livedovasculopathy': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000174',
        'Livider wound margin': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000175',
        'Low-vacuum drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000177',
        'Lymphatic fistula': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000178',
        'Macerated wound edge': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000180',
        'Malignant wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000182',
        'Manuka honey': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000185',
        'Marjolin ulcer': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000186',
        'Material used for wound treatment': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000188',
        'Medicinal honey': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000196',
        'Microangiopathy': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000201',
        'Moist necrosis': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000203',
        'Monaldi drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000204',
        'Monofilament thread material': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000205',
        'n-propanol': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000207',
        'NaCl 0.9%': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000208',
        'NaCl 10%': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000209',
        'Necrotic wound bed': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000211',
        'Non-absorbable thread material': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000215',
        'Octenidine gel': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000220',
        'Open drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000221',
        'Passive drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000224',
        'Penrose drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000227',
        'Peripheral arterial occlusive disease': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000229',
        'Phlegmon': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000233',
        'Pigtail catheter': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000235',
        'Plaster': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000237',
        'Polihexanide': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000238',
        'Polihexanide containing solution': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000239',
        'Polihexanide gel': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000240',
        'Polyfilament thread material': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000241',
        'Primarily-healing wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000247',
        'Purulent exudate': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000253',
        'Reddened wound edge': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000256',
        'Redon drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000258',
        'Regeneratively-healing wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000261',
        'Resorbable thread material': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000265',
        'Ringer solution': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000266',
        'Robinson drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000267',
        'Sanguine exudate': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000268',
        'Scratch wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000271',
        'Secondarily-healing wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000272',
        'Secondary dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000273',
        'Semi-open drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000275',
        'Seroma': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000276',
        'Serosanguineous exudate': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000277',
        'Serous exudate': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000278',
        'Silicone spacer grid': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000280',
        'Silver-containing wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000282',
        'Simple interrupted suture': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000283',
        'Skin graft': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000285',
        'Softened wound edge': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000290',
        'Split-thickness skin graft': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000292',
        'Substance used for enzymatic wound debridement': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000296',
        'Suture in situ': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000301',
        'Synthetic wound dressing foam': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000304',
        'Tertiarily-healing wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000307',
        'Thermal wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000310',
        'Thoracic drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000311',
        'trace element': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000336',
        'Transparent polyurethane film': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000337',
        'Traumatic wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000339',
        'Tympanic drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000344',
        'Ulcus cruris mixtum': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000346',
        'Ulcus cruris venosum': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000347',
        'Ulcus hypertonicus Martorell': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000348',
        'Undermined wound margin': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000351',
        'Ventricular drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000355',
        'Vertical mattress suture': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000356',
        'Voltaren gel': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000358',
        'Wound dehiscence causally related to suture insufficiency': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000379',
        'Wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000380',
        'Wound and soft tissue drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000381',
        'Wound base': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000382',
        'Wound biofilm': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000383',
        'Venous insufficiency wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000384',
        'Wound dehiscence': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000392',
        'Wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000398',
        'Wound dressing composed of a polylactide membrane': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000399',
        'Wound dressing composed of polyurethane foam': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000400',
        'Wound edge': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000401',
        'Wound exudate': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000404',
        'Wound gel/ointment/cream': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000406',
        'Wound healing disorder': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000408',
        'Wound irrigation solution': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000412',
        'Wound pocket': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000417',
        'Wound spacer grid': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000420',
        'Wound with accompanying fracture': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000426',
        'Wound-integrating wound dressing': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000427',
        'Wounds classified according to Gustilo and Anderson': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000429',
        'Wounds classified according to Tscherne and Oestern': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000430',
        'T drain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000432',
        'Skin wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000441',
        'Chronic wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000442',
        'Erysipelas': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000443',
        'Antiseptic agent': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000444',
        'Antiseptic biguanide': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000445',
        'Mucous membrane pemphigoid': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000446',
        'MRSA infection': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000447',
        'Neoplasm': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000464',
        'Malignancy': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000465',
        'Angiopathy': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000466',
        'Diabetic metabolic disorder': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000467',
        'Venous insufficiency disorder': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000468',
        'Autoimmune tissue disorder': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000469',
        'Lymphocele': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000470',
        'Abscess': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000472',
        'Mucosal blister': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000473',
        'Wound with microbial burden assessed according to IWII': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000481',
        'First-degree burn wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000482',
        'Second-degree burn wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000483',
        'Third-degree burn wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000484',
        'Fourth-degree burn wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000485',
        'Open wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000504',
        'Closed wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000505',
        'Epithelialized wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000506',
        'Large wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000507',
        'Deep wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000508',
        'Ischemic wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000509',
        'Arterial insufficiency wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000510',
        'Colonized wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000511',
        'Wound with microbial burden assessed according to CDC': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000524',
        'Contaminated wound according to CDC': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000525',
        'Dirty wound according to CDC': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000526',
        'Clean wound according to IWII': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000527',
        'Pressure ulcer': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000534',
        'Group A Streptococcus': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000547',
        'Vancomycin': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000548',
        'Diabetic foot ulcer': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000549',
        'Surgical site infection': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000550',
        'Soft tissue wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000551',
        'Laceration': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000552',
        'Acute wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000553',
        'Foreign body wound': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000554',
        'Foreign body': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000555',
        'Hypertrophic scar': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000556',
        'Sepsis': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000558',
        'Osteomyelitis': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000559',
        'Pressure redistribution mattress': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000570',
        'Therapeutic footwear': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000571',
        'Traumatic injury': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0007237',
        'Injury': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0007817',
        'pathogen with wound infecting tendency': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120019',
        'Necrosis': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120020',
    },
    'immaterial entity': {
        'spatial region': 'http://purl.obolibrary.org/obo/BFO_0000006',
        'two-dimensional spatial region': 'http://purl.obolibrary.org/obo/BFO_0000009',
        'zero-dimensional spatial region': 'http://purl.obolibrary.org/obo/BFO_0000018',
        'one-dimensional spatial region': 'http://purl.obolibrary.org/obo/BFO_0000026',
        'three-dimensional spatial region': 'http://purl.obolibrary.org/obo/BFO_0000028',
        'site': 'http://purl.obolibrary.org/obo/BFO_0000029',
        'continuant fiat boundary': 'http://purl.obolibrary.org/obo/BFO_0000140',
        'fiat line': 'http://purl.obolibrary.org/obo/BFO_0000142',
        'fiat surface': 'http://purl.obolibrary.org/obo/BFO_0000146',
        'fiat point': 'http://purl.obolibrary.org/obo/BFO_0000147',
    },
    'quality': {
        'relational quality': 'http://purl.obolibrary.org/obo/BFO_0000145',
        'pathological': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_000600',
        'Redness': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000257',
        'Thread size': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000315',
        'Thread size 0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000316',
        'Thread size 1': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000317',
        'Thread size 1-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000318',
        'Thread size 10-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000319',
        'Thread size 11-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000320',
        'Thread size 12-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000321',
        'Thread size 13-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000322',
        'Thread size 2': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000323',
        'Thread size 2-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000324',
        'Thread size 3': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000325',
        'Thread size 3-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000326',
        'Thread size 4': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000327',
        'Thread size 4-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000328',
        'Thread size 5': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000329',
        'Thread size 5-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000330',
        'Thread size 6-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000331',
        'Thread size 7-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000332',
        'Thread size 8-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000333',
        'Thread size 9-0': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000334',
        'degree of wound pain': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000415',
        'degree of maceration': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000434',
        'macerated': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000435',
        'degree of tissue firmness': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000450',
        'degree of skin adherence to underlying tissue': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000451',
        'degree of granulation': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000452',
        'degree of necrosis': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000453',
        'degree of fibrin coverage': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000454',
        'degree of epithelialization': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000455',
        'reddened': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000456',
        'livid': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000457',
        'softened': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000458',
        'undermined': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000459',
        'granulating': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000460',
        'necrotic': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000461',
        'fibrin-covered': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000462',
        'epithelialized': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000463',
        'painful': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000474',
        'degree of time after disease inception': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000475',
        'acute': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000476',
        'chronic': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000477',
        'degree of microbial burden': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000478',
        'contaminated': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000479',
        'infected': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000480',
        'sterile': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000486',
        'degree of tissue perfusion': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000487',
        'ischemic': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000488',
        'colonized': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000512',
    },
    'function': {
        'pressure redistribution function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000580',
        'clinical function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000583',
        'therapeutic function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000584',
        'wound protection function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120000',
        'wound signaling function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120001',
        'first wound dressing layer function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120002',
        'second wound dressing layer function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120003',
        'wound dressing layer function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120004',
        'wound dressing fixation function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120005',
        'non adhesive wound dressing fixation function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120006',
        'wound moisture absorbance function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120007',
        'wound moisture regulation function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120008',
        'wound desinfecting function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120009',
        'wound edge approximating function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120010',
        'wound inspection facilitation function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120011',
        'wound coverage function': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120012',
    },
    'role': {
        'Physician role': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120093',
        'Wound expert role': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000403',
        'Wound manager role': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000413',
        'antibiotic drug role': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000578',
        'therapeutic role': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000582',
        'local anesthetic drug role': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000585',
    },
    'tendency': {
        'tendency': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120005',
        'pathological genetic predisposition': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120008',
        'predisposition from an existing disorder': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120010',
        'realized disease predisposition': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120014',
        'disease predisposition': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120023',
        'perpetuation tendency': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120034',
        'advanced age wound-healing predisposition': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000449',
        'wound infecting tendency': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120018',
    },
    'information entity': {
        'disease classification stage': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120000',
        'disease diagnostic result': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120024',
        'confirmed disease diagnostic result by not completely objective criterion': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120026',
        'confirmed diseases diagnostic result by objective criterion': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120027',
        'disease threshold specification': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120029',
        'threshold value': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120030',
        'differential diagnosis result': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120032',
        'candidate diagnosis': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120033',
        'comparison_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120036',
        'binary_comparison_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120037',
        'equality_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120038',
        'inequality_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120039',
        'ordering_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120040',
        'greater_than_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120041',
        'greater_than_or_equal_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120042',
        'less_than_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120043',
        'less_than_or_equal_operator': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120044',
        'disease stage classification result': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120054',
        'treatment plan specification': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120089',
        'threshold specification': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120098',
        'Medical condition treatment plan specification': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120099',
        'prophylaxis plan specification': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120100',
        'Antibiotic therapy plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000016',
        'ASEPSIS score': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000028',
        'Aseptic conditions plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000029',
        'Aseptic cuticle plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000030',
        'Biobag debridement plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000038',
        'Biosurgical debridement plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000040',
        'Wound classification scale': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000066',
        'CO2 bath wound therapy plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000072',
        'Compress debridement plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000076',
        'Compression therapy plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000077',
        'Dressing change plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000094',
        'Flap plasty plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000114',
        'Gustilo and Anderson wound classification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000134',
        'Gustilo and Anderson wound classification grade': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000135',
        'Hand disinfection plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000138',
        'Hyperbaric O2 wound therapy plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000152',
        'Mechanical debridement plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000189',
        'Wound treatment plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000200',
        'Negative pressure wound therapy plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000213',
        'Pain management plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000222',
        'Patient education plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000225',
        'Perioperative antimicrobial prophylaxis plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000228',
        'Shea classification of pressure ulcers': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000279',
        'Skin grafting plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000286',
        'Skin stapling plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000287',
        'Surface disinfection plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000297',
        'Suturing plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000302',
        'Systemic antibiotic therapy plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000305',
        'Topical antibiotic therapy plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000335',
        'Tscherne and Oestern wound classification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000341',
        'Tscherne and Oestern wound classification grade': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000342',
        'URGE scale': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000352',
        'Wagner and Anderson wound classification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000375',
        'Wagner and Anderson wound classification grade': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000376',
        'Wearing sterile gloves plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000378',
        'Wound closure technique plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000389',
        'Wound fabric adhesive plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000405',
        'Wound staple plastering plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000421',
        'Burn classification scale': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000436',
        'Burn classification grade': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000437',
        'Shea classification grade': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000438',
        'CDC surgical wound classification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000439',
        'CDC surgical wound classification grade': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000440',
        'wound depth measurement datum': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000448',
        'Jackson burn wound zone': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000492',
        'Jackson burn wound zone classification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000493',
        'Burn wound classification according to Hildanus and Derganc': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000494',
        'Burn wound classification grade according to Hildanus and Derganc': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000495',
        'Partial thickness': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000513',
        'IWII wound classification scale': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000528',
        'IWII wound classification grade': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000529',
        'Wound healing phase': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000561',
        'Prophylactic antibiotic therapy plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000569',
        'Wound healing criterion': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000576',
        'Epithelialization criterion': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000577',
        'Surgical debridement plan specification': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000581',
        'wound classification grade': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120016',
        'Wound classification result': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120017',
    },
    'process': {
        'history': 'http://purl.obolibrary.org/obo/BFO_0000182',
        'intended disorder elimination process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120011',
        'predisposition realizing disorder development process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120012',
        'disorder development process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120021',
        'disease diagnosis process by measurement': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120025',
        'course of the disease process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120028',
        'disease perpetuation process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120035',
        'Disease diagnosis process by exclusion': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120045',
        'disease diagnosis process by conceptualization': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120046',
        'Disease diagnostic process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120047',
        'Suspected disease diagnosis process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120048',
        'disorder creating disease course process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120053',
        'disease classification process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120055',
        'Disease disorder treatment process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120086',
        'disorder elimination process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120087',
        'disorder modification process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120088',
        'disorder addition process': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120091',
        'Wound causing acidity impact process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000004',
        "Assessing patient's medical history": 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000032',
        'Autolytic wound debridement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000034',
        'Wound specimen procurement by biopsy process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000039',
        'Biosurgical wound debridement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000041',
        'Clinical inspection': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000069',
        'Clinical wound assessment': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000070',
        'Cold plasma wound treatment process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000074',
        'CUSA(r) assisted debridement': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000082',
        'Debridement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000084',
        'Diagnostic process to assess wound characteristics': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000089',
        'Doppler sonographic diagnostic process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000092',
        'Enzymatic wound debridement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000098',
        'Epithelialization process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000100',
        'Exudation process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000106',
        'Germ spectrum assessment process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000121',
        'Granulation tissue formation process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000132',
        'Wound causing heat impact process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000140',
        'Histopathological examination process of wound material': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000146',
        'Excessive collagen deposition process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000154',
        'Keloid development process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000171',
        'Process of administering a local anesthetic agent': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000176',
        'Mechanical wound debridement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000190',
        'Microbial analysis of the wound swab for wound pathogens': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000202',
        'Nutritional status improvement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000216',
        'Planimetry': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000236',
        'Postoperative wound control process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000243',
        'Wound causing pressure impact process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000245',
        'Wound healing by primary intention process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000248',
        'Regenerative wound healing process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000260',
        'Tissue repair process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000263',
        'Pathological scarring process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000269',
        'Wound healing by secondary intention process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000274',
        'Skin color assessment process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000284',
        'Smoking': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000289',
        'Wound odor assessment process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000291',
        'Surgical treatment process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000298',
        'Surgical wound debridement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000299',
        'Taking a wound swab': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000306',
        'Wound healing by tertiary intention process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000308',
        'Trauma process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000338',
        'Ultrasound-assisted wound debridement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000350',
        'Water-jet assisted wound debridement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000377',
        'Wound cleansing process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000387',
        'Wound closure process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000388',
        'Wound contraction process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000391',
        'Wound diagnostic process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000395',
        'Wound documentation process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000397',
        'Wound edge protection process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000402',
        'Wound healing related physiological process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000409',
        'Wound infection process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000410',
        'Wound irrigation process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000411',
        'Wound development process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000414',
        'Wound palpation': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000416',
        'Wound causing process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000418',
        'Wound size measurement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000419',
        'Wound temperature assessment process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000422',
        'Wound treatment process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000423',
        'Wound volumetrics': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000425',
        'Wound dehiscence process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000433',
        'Scarring process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000471',
        'Malignant process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000514',
        'Wound causing malignant process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000515',
        'Wound causing trauma process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000516',
        'Acidity impact process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000517',
        'Heat impact process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000518',
        'Pressure impact process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000519',
        'Diabetes mellitus type II disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000520',
        'Irreversibly diminished microvascular perfusion process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000521',
        'Angiopathic disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000522',
        'Autoimmune disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000523',
        'Diabetes mellitus disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000535',
        'Diabetes mellitus type I disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000536',
        'Wound causing angiopathic disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000537',
        'Wound causing autoimmune disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000538',
        'Wound causing diabetes mellitus disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000539',
        'Venous insufficiency disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000540',
        'Wound causing venous insufficiency disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000541',
        'Peripheral arterial occlusive disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000542',
        'Wound causing peripheral arterial occlusive disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000543',
        'Impaired wound healing process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000544',
        'Wound causing neuropathic disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000560',
        'Bacterial colonization process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000566',
        'Pressure offloading process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000568',
        'Bacterial culture process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000572',
        'Vascular assessment process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000573',
        'Ankle-brachial index measurement process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000574',
        'Wound photography process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000575',
        'Process of drug administration': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000579',
        'Neuropathic disease process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000586',
        'Wound causing foreign body process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000587',
        'Antibiotic administration process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000589',
        'Inflammation process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_0000590',
        'Wound dressing process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120013',
        'Wound classification process': 'https://bioportal.bioontology.org/ontologies/WONT/WONT_120015',
    },
    'process boundary': {
        'threshold crossing event': 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120031',
    },
    'temporal region': {
        'one-dimensional temporal region': 'http://purl.obolibrary.org/obo/BFO_0000038',
        'zero-dimensional temporal region': 'http://purl.obolibrary.org/obo/BFO_0000148',
        'temporal interval': 'http://purl.obolibrary.org/obo/BFO_0000202',
        'temporal instant': 'http://purl.obolibrary.org/obo/BFO_0000203',
    },
}

# label -> IAO_0000115 definition, for prompt construction.
DEFINITIONS: dict[str, str] = {
    'treatment plan': 'A plan that inheres in a Homo sapiens that bears the role physician role and that concretizes a treatment plan specification.',
    'Developed material disease entity': 'A disease whose disorders had to develop.',
    'material disease entity': 'A material entity that has one or more pathological disorders as parts; which disorders compose one disease is fixed by the diagnostic classification assigned to them, not by an intrinsic unity criterion. Identity is grounded in the continuity of the disorder lineage, not in momentary material composition (cf. a river persisting through complete material replacement).',
    'pathological disorder': 'a disorder is an abnormal presence or organization of material components — including the limiting case where the abnormal organization consists in a normally-present component being absent.',
    'Angiopathic wound': 'A wound that is the output of a wound development process that has as part a wound causing process of the course of an angiopathy. No claim is made that the disorder caused the wound.',
    'Autoimmune disease related wound': 'A wound that is the output of a wound development process that has as part a wound causing process of the course of an autoimmune tissue disorder. No claim is made that the disorder caused the wound.',
    'Clean-contaminated wound according to CDC': 'A wound with microbial burden assessed according to CDC that is an operative wound in which the respiratory, alimentary, genital or urinary tract is entered under controlled conditions and without unusual contamination.',
    'Clean wound according to CDC': 'A wound with microbial burden assessed according to CDC that is an uninfected operative wound in which no inflammation is encountered and the respiratory, alimentary, genital or urinary tract is not entered.',
    'Contaminated wound': 'A wound with recognized microbial burden that bears the quality contaminated.',
    'Diabetic wound': 'A wound that is the output of a wound development process that has as part a wound causing process of the course of a diabetic metabolic disorder. No claim is made that the disorder caused the wound.',
    'Epithelializing wound bed': 'A wound base that bears the quality epithelialized.',
    'Fibrin-covered wound bed': 'A wound base that bears the quality fibrin-covered.',
    'Granulating wound bed': 'A wound base that bears the quality granulating.',
    'Infected wound': 'A wound that participates in a wound infection process.',
    'Livider wound margin': 'A wound edge that bears the quality livid.',
    'Macerated wound edge': 'A wound edge that bears the quality macerated.',
    'Malignant wound': 'A wound that is the specified output of a disorder development process that has as participant a malignancy.',
    'Necrotic wound bed': 'A wound base that bears the quality necrotic.',
    'Primarily-healing wound': 'A wound that participates in a wound healing by primary intention.',
    'Reddened wound edge': 'A wound edge that bears the quality reddened.',
    'Regeneratively-healing wound': 'A wound that participates in a regenerative wound healing.',
    'Secondarily-healing wound': 'A wound that participates in a wound healing by secondary intention.',
    'Softened wound edge': 'A wound edge that bears the quality softened.',
    'Tertiarily-healing wound': 'A wound that participates in a wound healing by tertiary intention.',
    'trace element': 'A material entity that bears the role nutrient.',
    'Traumatic wound': 'A wound that is the output of a wound causing trauma process.',
    'Undermined wound margin': 'A wound edge that bears the quality undermined.',
    'Wound': 'A pathological disorder that is the output of a wound development process.',
    'Venous insufficiency wound': 'A wound that is the output of a wound development process that has as part a wound causing process of the course of a venous insufficiency disorder. No claim is made that the disorder caused the wound.',
    'Wound dehiscence': 'A pathological disorder that is the output of a wound dehiscence process.',
    'Wound dressing': 'A device that bears a wound coverage function.',
    'Skin wound': 'A wound whose disrupted tissue is skin.',
    'Chronic wound': 'A wound that has failed to progress through the phases of healing in an orderly and timely fashion.',
    'Erysipelas': 'A superficial bacterial skin infection, characteristically caused by Streptococcus pyogenes, involving the upper dermis and superficial lymphatics.',
    'Antiseptic agent': 'A material used for wound treatment that bears the antiseptic drug role.',
    'Antiseptic biguanide': 'A biguanide that bears the antiseptic drug role.',
    'Mucous membrane pemphigoid': 'A material disease entity that has as parts one or more mucosal blisters that are autoimmune tissue disorders.',
    'MRSA infection': 'A material disease entity that is an infection whose causal agent is a methicillin-resistant strain of Staphylococcus aureus.',
    'Neoplasm': 'A material disease entity that has as part an abnormal mass of tissue arising from autonomous, uncoordinated proliferation of its constituent cells.',
    'Malignancy': 'A neoplasm whose constituent cells are disposed to invade surrounding tissue or to metastasize.',
    'Angiopathy': 'A pathological disorder consisting in an abnormal structure of the wall or of the lumen of one or more blood vessels, such that perfusion of the tissue those vessels supply is reduced.',
    'Diabetic metabolic disorder': 'A pathological disorder consisting in the abnormal organization of the insulin-secreting or insulin-responsive tissues of a patient, such that glucose homeostasis is not maintained.',
    'Venous insufficiency disorder': 'A pathological disorder consisting in an abnormal structure of the valves or walls of the veins of a limb, such that venous return from that limb against gravity is impaired.',
    'Autoimmune tissue disorder': "A pathological disorder consisting in tissue of a patient that has been damaged by an immune response directed against constituents normally present in that patient's own body.",
    'Lymphocele': 'A pathological disorder consisting in a collection of lymphatic fluid within a non-epithelialised cavity in a bodily structure.',
    'Abscess': 'A pathological disorder consisting in a localized collection of purulent material within a bodily structure, surrounded by inflamed and granulating tissue.',
    'Mucosal blister': 'A pathological disorder that is part of a mucosa and consists in a fluid-filled separation of the epithelium of that mucosa from the tissue beneath it.',
    'Wound with microbial burden assessed according to IWII': 'A wound whose microbial burden is assessed on the IWII wound infection continuum: it bears the quality sterile, contaminated, colonized or infected.',
    'First-degree burn wound': 'A thermal wound in which the injury is confined to the epidermis.',
    'Second-degree burn wound': 'A thermal wound in which the injury extends through the epidermis into the dermis.',
    'Third-degree burn wound': 'A thermal wound in which the injury extends through the full thickness of the skin.',
    'Fourth-degree burn wound': 'A thermal wound in which the injury extends beyond the skin into underlying tissue such as fascia, muscle or bone.',
    'Open wound': 'A wound that bears the quality open: its surface is breached, so that underlying tissue is exposed.',
    'Closed wound': 'A wound that bears the quality closed: the skin or mucosal surface over the injured tissue is intact.',
    'Epithelialized wound': 'A wound that bears the quality epithelialized: its surface has been covered by newly formed epithelium.',
    'Large wound': 'A wound that bears the quality increased size: its extent is greater than is typical for a wound of its kind.',
    'Deep wound': 'A wound that bears the quality increased depth: it extends further into the tissue than is typical for a wound of its kind.',
    'Ischemic wound': 'An arterial insufficiency wound that bears the quality ischemic.',
    'Arterial insufficiency wound': 'A wound that is the output of a wound development process that has as part a wound causing process of the course of a peripheral arterial occlusive disease. No claim is made that the disorder caused the wound.',
    'Colonized wound': 'A wound with recognized microbial burden that bears the quality colonized.',
    'Wound with microbial burden assessed according to CDC': 'A wound that is classified by the CDC surgical wound classification: clean, clean-contaminated, contaminated or dirty, according to the state of the operative field.',
    'Contaminated wound according to CDC': 'A wound with microbial burden assessed according to CDC that is an open, fresh, accidental wound, or an operative wound with a major break in sterile technique or gross spillage from the gastrointestinal tract.',
    'Dirty wound according to CDC': 'A wound with microbial burden assessed according to CDC that is an old traumatic wound with retained devitalized tissue, or one that involves existing clinical infection or perforated viscera.',
    'Clean wound according to IWII': 'A wound with microbial burden assessed according to IWII that bears the quality sterile.',
    'Pressure ulcer': 'A wound that is the output of a wound development process that has as part a wound causing pressure impact process.',
    'Diabetic foot ulcer': 'A diabetic wound that is located in a foot.',
    'Foreign body wound': 'A wound that is the output of a wound development process that has as part a wound causing foreign body process.',
    'Traumatic injury': 'An injury that is the output of a trauma process.',
    'Injury': 'A pathological disorder that is structural damage to a tissue or an organ, whatever its cause.',
    'pathogen with wound infecting tendency': 'A pathogen that bears a wound infecting tendency.',
    'continuant fiat boundary': 'b is a continuant fiat boundary = Def. b is an immaterial entity that is of zero, one or two dimensions and does not include a spatial region as part. (axiom label in BFO2 Reference: [029-001])',
    'relational quality': 'b is a relational quality = Def. for some independent continuants c, d and for some time t: b quality_of c at t & b quality_of d at t. (axiom label in BFO2 Reference: [057-001])',
    'degree of wound pain': 'A quality that inheres in a patient, that is the extent of the pain that patient feels, and that is causally influenced by a wound.',
    'degree of maceration': 'A quality of a wound edge that is the extent to which its tissue has been softened by prolonged exposure to moisture.',
    'macerated': 'A degree of maceration that qualifies its bearer as macerated.',
    'degree of tissue firmness': 'A quality of a bodily tissue that is the degree of resistance it offers to deformation.',
    'degree of skin adherence to underlying tissue': 'A quality of skin that is the extent to which it remains attached to the tissue beneath it.',
    'degree of granulation': 'A quality of a wound base that is the extent to which it is covered by granulation tissue.',
    'degree of necrosis': 'A quality of a wound base that is the extent to which its tissue is necrotic.',
    'degree of fibrin coverage': 'A quality of a wound base that is the extent to which it is covered by fibrin.',
    'degree of epithelialization': 'A quality of a wound base that is the extent to which it has been covered by new epithelium.',
    'reddened': 'A color that qualifies its bearer as reddened.',
    'livid': 'A color that qualifies its bearer as livid.',
    'softened': 'A tissue firmness that qualifies its bearer as softened.',
    'undermined': 'A degree of skin adherence that qualifies its bearer as undermined.',
    'granulating': 'A degree of granulation that qualifies its bearer as granulating.',
    'necrotic': 'A degree of necrosis that qualifies its bearer as necrotic.',
    'fibrin-covered': 'A degree of fibrin coverage that qualifies its bearer as fibrin-covered.',
    'epithelialized': 'A degree of epithelialization that qualifies its bearer as epithelialized.',
    'painful': 'A degree of wound pain that qualifies its bearer as painful.',
    'degree of time after disease inception': 'A quality of a pathological disorder that is the time that has elapsed since the disorder came into existence, taken relative to the course expected for a disorder of its kind.',
    'acute': 'A degree of time after disease inception that qualifies its bearer as acute: the disorder is of recent onset and still within the period in which an orderly course is expected.',
    'chronic': 'A degree of time after disease inception that qualifies its bearer as chronic: the disorder has persisted beyond the period in which an orderly course is expected.',
    'degree of microbial burden': 'A quality of a wound that is the extent to which microorganisms are present in it, multiply in it and elicit a response from its bearer.',
    'contaminated': 'A degree of microbial burden that qualifies its bearer as contaminated: microorganisms are present in the wound but are not multiplying.',
    'infected': 'A degree of microbial burden that qualifies its bearer as infected: microorganisms are present in the wound, multiply in it and elicit a host response.',
    'sterile': 'A degree of microbial burden that qualifies its bearer as sterile: no viable microorganisms are present in the wound.',
    'degree of tissue perfusion': 'A quality of a wound that is the extent to which its tissue is supplied with blood.',
    'ischemic': 'A degree of tissue perfusion that qualifies its bearer as ischemic: the blood supply to the tissue is insufficient for its metabolic needs.',
    'colonized': 'A degree of microbial burden that qualifies its bearer as colonized: microorganisms are present in the wound and multiply in it, without invading its tissue or eliciting a host response.',
    'Physician role': 'A healthcare provider role that inheres in a person in virtue of that person being licensed to practice medicine.',
    'local anesthetic drug role': 'A clinical drug role borne by a substance used to produce local anesthesia.',
    'tendency': 'A realizable entity that inheres in a material entity and that, in virtue of the physical makeup of its bearer, inclines that bearer toward participating in processes of a certain type — such that the inclination raises the objective probability of, but does not necessitate, the occurrence of those processes; that may be counteracted or reinforced by other tendencies of the same bearer without thereby ceasing to exist; and that may be realized to varying degrees, or not at all.',
    'pathological genetic predisposition': 'A disease predisposition that has as material basis a pathogenic genetic variant.',
    'predisposition from an existing disorder': 'A disease predisposition that inheres in a Homo sapiens that has as part a pathological disorder.',
    'realized disease predisposition': 'A disease predisposition that is realized by a disorder development process.',
    'disease predisposition': 'A tendency inhering in a person, grounded in a material basis, whose realization may produce a target pathological disorder.',
    'advanced age wound-healing predisposition': 'A disease predisposition that inheres in a human being of advanced age and whose realization impairs wound healing.',
    'disease diagnostic result': "An information content entity that classifies or groups one or more pathological disorders according to diagnostic criteria. Names such as 'substance use disorder' can denote this diagnostic layer when used as DSM/ICD-style categories or results; this diagnostic use is distinct from any material disease entity in the patient.",
    'disease threshold specification': 'A directive information entity that has as part a threshold value and a comparison_operator and that is about a phenotypic abnormality.',
    'threshold value': 'A scalar value specification that has as measurement unit a unit and that has a specified numeric value.',
    'differential diagnosis result': 'A disease diagnostic result that has as part a candidate diagnosis.',
    'disease stage classification result': 'An information content entity that is the specified output of a disease classification process and that is about nothing other than a material disease entity.',
    'treatment plan specification': 'A plan specification that is about a treatment plan.',
    'threshold specification': "A directive information entity that has as part a threshold value and a comparison operator and that is about a quality, such that the quality's meeting the threshold is what the specification prescribes as decisive.",
    'Wound classification scale': 'An information content entity that is a specified input of a wound classification process.',
    'Burn classification scale': 'A wound classification scale that stratifies burn wounds by the depth of tissue destroyed.',
    'Burn classification grade': 'A wound classification grade that is a category of the burn classification scale.',
    'Shea classification grade': 'A wound classification grade that is a category of the Shea classification of pressure ulcers.',
    'CDC surgical wound classification': 'A wound classification scale that stratifies surgical wounds by degree of intraoperative microbial contamination.',
    'CDC surgical wound classification grade': 'A wound classification grade that is a category of the CDC surgical wound classification.',
    'wound depth measurement datum': 'A measurement datum that is about the depth of a wound.',
    'Jackson burn wound zone': 'A burn classification grade that is one of the three concentric zones of a burn wound distinguished by Jackson according to the severity of tissue damage.',
    'Jackson burn wound zone classification': 'A wound classification scale that divides a burn wound into three concentric zones - coagulation, stasis and hyperemia - by the severity of tissue damage.',
    'Burn wound classification according to Hildanus and Derganc': "A wound classification scale that grades a burn wound by the depth of tissue destroyed: superficial, superficial partial-thickness, deep partial-thickness and full-thickness. Derganc's subdivision of the second degree refines the degree scheme attributed to Hildanus.",
    'Burn wound classification grade according to Hildanus and Derganc': 'A burn classification grade that is a category of the burn wound classification according to Hildanus and Derganc.',
    'Partial thickness': 'A burn wound classification grade according to Hildanus and Derganc in which the injury extends into but not through the dermis; its instances are the superficial and the deep partial-thickness grade.',
    'IWII wound classification scale': 'A wound classification scale that grades a wound by its microbial burden on the wound infection continuum of the International Wound Infection Institute: clean, contaminated, colonized, infected.',
    'IWII wound classification grade': 'A wound classification grade that is a category of the IWII wound classification scale.',
    'Wound healing phase': 'A wound classification grade of the scheme that divides wound healing into phases (hemostasis, inflammatory, proliferative, remodeling). The phases are labels assigned to stretches of the healing process, not processes themselves; each is about the processes it groups.',
    'Wound classification result': 'A disease stage classification result that is about a wound and that is the specified output of a wound classification process.',
    'predisposition realizing disorder development process': 'A disorder development process that realizes a disease predisposition.',
    'disorder development process': 'A process that has as output a pathological disorder and that has as its end boundary a threshold crossing event.',
    'disease diagnosis process by measurement': 'A disease diagnostic process that has as specified input a measurement datum and a disease threshold specification and that has as specified output a confirmed diseases diagnostic result by objective criteria.',
    'course of the disease process': 'A process that has as participant a material disease entity, that is immediately causally downstream of a disorder development process, and that has as its start boundary a threshold crossing event.',
    'disease perpetuation process': 'A process that is part of a course of the disease process and that realizes a perpetuation tendency.',
    'Disease diagnostic process': 'A planned process that has as output a disease diagnostic result.',
    'Suspected disease diagnosis process': 'A disease diagnostic process that has as specified output a candidate diagnosis.',
    'disease classification process': 'A planned process that has as specified output a disease stage classification result.',
    'Disease disorder treatment process': 'A planned process that realizes a treatment plan and that has as input a pathological disorder that is part of a material disease entity.',
    'Wound causing process': 'A process that has the newly developed wound as a participant or output and does so with near certainty.',
    'Wound size measurement process': 'A wound diagnostic process that has as specified output a wound depth measurement datum.',
    'Wound dehiscence process': 'A disorder development process in which previously approximated wound edges separate.',
    'Scarring process': 'A wound healing related physiological process in which fibrous connective tissue replaces tissue lost in a wound, yielding a scar rather than restoration of the original tissue architecture.',
    'Malignant process': 'A disease course process that has as participant a malignancy.',
    'Wound causing malignant process': 'A malignant process that is a wound causing process.',
    'Wound causing trauma process': 'A trauma process that is a wound causing process.',
    'Acidity impact process': 'A process in which an acid or a base acts on a tissue.',
    'Heat impact process': 'A process in which heat acts on a tissue.',
    'Pressure impact process': 'A process in which sustained mechanical pressure acts on a tissue.',
    'Diabetes mellitus type II disease process': 'A diabetes mellitus disease process of a diabetic metabolic disorder of type II.',
    'Irreversibly diminished microvascular perfusion process': 'A process in which the perfusion of a tissue through its microvasculature is reduced without recovery.',
    'Angiopathic disease process': 'A disease course process of an angiopathy.',
    'Autoimmune disease process': 'A disease course process of an autoimmune tissue disorder.',
    'Diabetes mellitus disease process': 'A disease course process of a diabetic metabolic disorder.',
    'Diabetes mellitus type I disease process': 'A diabetes mellitus disease process of a diabetic metabolic disorder of type I.',
    'Wound causing angiopathic disease process': 'An angiopathic disease process that is a wound causing process.',
    'Wound causing autoimmune disease process': 'An autoimmune disease process that is a wound causing process.',
    'Wound causing diabetes mellitus disease process': 'A diabetes mellitus disease process that is a wound causing process.',
    'Venous insufficiency disease process': 'A course of the disease process that has as participant a venous insufficiency disorder.',
    'Wound causing venous insufficiency disease process': 'A venous insufficiency disease process that is a wound causing process.',
    'Peripheral arterial occlusive disease process': 'An angiopathic disease process that has as participant a peripheral arterial occlusive disease.',
    'Wound causing peripheral arterial occlusive disease process': 'A peripheral arterial occlusive disease process that is a wound causing process.',
    'Wound causing neuropathic disease process': 'A neuropathic disease process that is a wound causing process.',
    'Neuropathic disease process': 'A course of the disease process that has as participant a peripheral nervous system disease (peripheral neuropathy).',
    'Wound causing foreign body process': 'A wound causing process in which a foreign body participates.',
    'Antibiotic administration process': 'A process of drug administration in which a material entity bearing an antibiotic drug role participates.',
    'Wound classification process': 'A disease classification process that has as specified output a wound classification result.',
    'threshold crossing event': 'A process boundary that occupies a temporal instant and that has as participant a measurement datum that is about a phenotypic abnormality.',
}


class RelationType(str, Enum):
    """Object properties actually used by MILD/WONT."""

    CAUSALLY_INFLUENCED_BY = 'causally influenced by'
    CONCRETIZES = 'concretizes'
    HAS_A_MATERIAL_BASIS = 'has a material basis'
    HAS_AS_PROCESS_BOUNDARY_AT_END = 'has as process boundary at end'
    HAS_AS_PROCESS_BOUNDARY_AT_START = 'has as process boundary at start'
    HAS_DISPOSITION = 'has disposition'
    HAS_FUNCTION = 'has function'
    HAS_INPUT = 'has input'
    HAS_OUTPUT = 'has output'
    HAS_PART = 'has part'
    HAS_PARTICIPANT = 'has participant'
    HAS_QUALITY = 'has quality'
    HAS_REALIZATION = 'has realization'
    HAS_ROLE = 'has role'
    HAS_SPECIFIED_INPUT = 'has specified input'
    HAS_SPECIFIED_OUTPUT = 'has specified output'
    HAS_TENDENCY = 'has tendency'
    IMMEDIATELY_CAUSALLY_DOWNSTREAM_OF = 'immediately causally downstream of'
    INHERES_IN = 'inheres in'
    IS_ABOUT = 'is about'
    IS_SPECIFIED_INPUT_OF = 'is specified input of'
    IS_SPECIFIED_OUTPUT_OF = 'is specified output of'
    OCCUPIES_TEMPORAL_REGION = 'occupies temporal region'
    OUTPUT_OF = 'output of'
    PART_OF = 'part of'
    PARTICIPATES_IN = 'participates in'
    PARTICIPATES_IN_2 = 'participates in'
    REALIZES = 'realizes'


RELATION_IRI: dict[str, str] = {
    RelationType.CAUSALLY_INFLUENCED_BY.value: 'http://purl.obolibrary.org/obo/RO_0002559',
    RelationType.CONCRETIZES.value: 'http://purl.obolibrary.org/obo/RO_0000059',
    RelationType.HAS_A_MATERIAL_BASIS.value: 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120094',
    RelationType.HAS_AS_PROCESS_BOUNDARY_AT_END.value: 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120085',
    RelationType.HAS_AS_PROCESS_BOUNDARY_AT_START.value: 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120084',
    RelationType.HAS_DISPOSITION.value: 'http://purl.obolibrary.org/obo/RO_0000091',
    RelationType.HAS_FUNCTION.value: 'http://purl.obolibrary.org/obo/RO_0000085',
    RelationType.HAS_INPUT.value: 'http://purl.obolibrary.org/obo/RO_0002233',
    RelationType.HAS_OUTPUT.value: 'http://purl.obolibrary.org/obo/RO_0002234',
    RelationType.HAS_PART.value: 'http://purl.obolibrary.org/obo/BFO_0000051',
    RelationType.HAS_PARTICIPANT.value: 'http://purl.obolibrary.org/obo/RO_0000057',
    RelationType.HAS_QUALITY.value: 'http://purl.obolibrary.org/obo/RO_0000086',
    RelationType.HAS_REALIZATION.value: 'http://purl.obolibrary.org/obo/BFO_0000054',
    RelationType.HAS_ROLE.value: 'http://purl.obolibrary.org/obo/RO_0000087',
    RelationType.HAS_SPECIFIED_INPUT.value: 'http://purl.obolibrary.org/obo/OBI_0000293',
    RelationType.HAS_SPECIFIED_OUTPUT.value: 'http://purl.obolibrary.org/obo/OBI_0000299',
    RelationType.HAS_TENDENCY.value: 'https://bioportal.bioontology.org/ontologies/MILD/MILD_120101',
    RelationType.IMMEDIATELY_CAUSALLY_DOWNSTREAM_OF.value: 'http://purl.obolibrary.org/obo/RO_0002405',
    RelationType.INHERES_IN.value: 'http://purl.obolibrary.org/obo/BFO_0000197',
    RelationType.IS_ABOUT.value: 'http://purl.obolibrary.org/obo/IAO_0000136',
    RelationType.IS_SPECIFIED_INPUT_OF.value: 'http://purl.obolibrary.org/obo/OBI_0000295',
    RelationType.IS_SPECIFIED_OUTPUT_OF.value: 'http://purl.obolibrary.org/obo/OBI_0000312',
    RelationType.OCCUPIES_TEMPORAL_REGION.value: 'http://purl.obolibrary.org/obo/BFO_0000199',
    RelationType.OUTPUT_OF.value: 'http://purl.obolibrary.org/obo/RO_0002353',
    RelationType.PART_OF.value: 'http://purl.obolibrary.org/obo/BFO_0000050',
    RelationType.PARTICIPATES_IN.value: 'http://purl.obolibrary.org/obo/BFO_0000056',
    RelationType.PARTICIPATES_IN_2.value: 'http://purl.obolibrary.org/obo/RO_0000056',
    RelationType.REALIZES.value: 'http://purl.obolibrary.org/obo/BFO_0000055',
}

# (subject category, object category) pairs observed in MILD/WONT for each
# relation. This is the deterministic half of two-stage extraction: once both
# categories are known the relation is largely forced, so the model is never
# asked to choose between occurs_in / part_of / inheres_in on BFO grounds.
RELATION_DOMAINS: dict[str, set[tuple[str, str]]] = {
    RelationType.CAUSALLY_INFLUENCED_BY.value: {
        ('quality', 'material entity'),
    },
    RelationType.CONCRETIZES.value: {
        ('realizable entity', 'information entity'),
    },
    RelationType.HAS_A_MATERIAL_BASIS.value: {
        ('tendency', 'material entity'),
    },
    RelationType.HAS_AS_PROCESS_BOUNDARY_AT_END.value: {
        ('process', 'process boundary'),
    },
    RelationType.HAS_AS_PROCESS_BOUNDARY_AT_START.value: {
        ('process', 'process boundary'),
    },
    RelationType.HAS_DISPOSITION.value: {
        ('material entity', 'disposition'),
    },
    RelationType.HAS_FUNCTION.value: {
        ('material entity', 'function'),
    },
    RelationType.HAS_INPUT.value: {
        ('process', 'material entity'),
    },
    RelationType.HAS_OUTPUT.value: {
        ('process', 'information entity'),
        ('process', 'material entity'),
    },
    RelationType.HAS_PART.value: {
        ('information entity', 'information entity'),
        ('material entity', 'material entity'),
    },
    RelationType.HAS_PARTICIPANT.value: {
        ('process', 'material entity'),
        ('process boundary', 'information entity'),
    },
    RelationType.HAS_QUALITY.value: {
        ('material entity', 'quality'),
    },
    RelationType.HAS_REALIZATION.value: {
        ('tendency', 'process'),
    },
    RelationType.HAS_ROLE.value: {
        ('material entity', 'role'),
        ('material entity', 'specifically dependent continuant'),
    },
    RelationType.HAS_SPECIFIED_INPUT.value: {
        ('process', 'information entity'),
    },
    RelationType.HAS_SPECIFIED_OUTPUT.value: {
        ('process', 'information entity'),
    },
    RelationType.HAS_TENDENCY.value: {
        ('material entity', 'tendency'),
    },
    RelationType.IMMEDIATELY_CAUSALLY_DOWNSTREAM_OF.value: {
        ('process', 'process'),
    },
    RelationType.INHERES_IN.value: {
        ('quality', 'material entity'),
        ('realizable entity', 'material entity'),
        ('tendency', 'material entity'),
    },
    RelationType.IS_ABOUT.value: {
        ('information entity', 'material entity'),
        ('information entity', 'process'),
        ('information entity', 'quality'),
        ('information entity', 'realizable entity'),
        ('information entity', 'specifically dependent continuant'),
    },
    RelationType.IS_SPECIFIED_INPUT_OF.value: {
        ('information entity', 'process'),
    },
    RelationType.IS_SPECIFIED_OUTPUT_OF.value: {
        ('information entity', 'process'),
    },
    RelationType.OCCUPIES_TEMPORAL_REGION.value: {
        ('process boundary', 'temporal region'),
    },
    RelationType.OUTPUT_OF.value: {
        ('material entity', 'process'),
    },
    RelationType.PART_OF.value: {
        ('material entity', 'material entity'),
        ('process', 'process'),
    },
    RelationType.PARTICIPATES_IN.value: {
        ('material entity', 'process'),
    },
    RelationType.PARTICIPATES_IN_2.value: {
        ('material entity', 'process'),
    },
    RelationType.REALIZES.value: {
        ('process', 'function'),
        ('process', 'realizable entity'),
        ('process', 'tendency'),
    },
}


def relations_for(subject_category: str, object_category: str) -> list[str]:
    """Relations MILD/WONT license between these two categories.

    A coarse category stands for any of its descendants, so the answer widens
    to their union: asking about Continuant -> Process returns everything
    licensed for 'material entity' -> 'process', 'quality' -> 'process' and so on.
    the open-world reading — we know less, so fewer things are ruled out. Use
    `relations_are_certain()` to tell a confirmed relation from a possible one.
    """
    subs = category_descendants(subject_category)
    objs = category_descendants(object_category)
    return sorted(
        r for r, pairs in RELATION_DOMAINS.items()
        if any(s in subs and o in objs for s, o in pairs)
    )


def relations_are_certain(subject_category: str, object_category: str) -> bool:
    """True when both categories are precise, so the licensing answer is exact."""
    return (subject_category not in COARSE_CATEGORIES
            and object_category not in COARSE_CATEGORIES)


class ExtractedEntity(BaseModel):
    """A term found in the text, typed to exactly one category."""

    label: str = Field(..., description='the term exactly as it appears in the text')
    category: BFOCategory = Field(..., description='the single BFO/MILD category')
    grounded_to: Optional[str] = Field(
        None,
        description='IRI of the existing MILD/WONT class, or null if the term is new',
    )

    @property
    def bfo_iri(self) -> str:
        """The BFO class this term is subsumed under. Never null."""
        return CATEGORY_IRI[self.category.value]

    @property
    def needs_refinement(self) -> bool:
        """Typed at a coarse node — correct, but a more specific class may apply."""
        return self.category.value in COARSE_CATEGORIES

    def subsumption_axiom(self) -> tuple[str, str, str]:
        """(term, rdfs:subClassOf, BFO IRI) — the axiom this term always yields.

        A newly discovered term has no MILD/WONT parent yet, but it is never
        left dangling: it is subsumed under its BFO category from the start,
        and curation only ever moves it DOWN the tree from there.
        """
        return (self.grounded_to or self.label,
                'http://www.w3.org/2000/01/rdf-schema#subClassOf',
                self.bfo_iri)

    @model_validator(mode='after')
    def _ground_consistently(self):
        """A supplied grounding must exist AND sit in the declared category."""
        if self.grounded_to is None:
            table = GROUNDING.get(self.category.value, {})
            hit = table.get(self.label)
            if hit:
                self.grounded_to = hit          # exact-label autogrounding
            return self
        allowed = set(GROUNDING.get(self.category.value, {}).values())
        if self.grounded_to not in allowed:
            raise ValueError(
                f'{self.grounded_to!r} is not a {self.category.value} in MILD/WONT'
            )
        return self


class ExtractedRelation(BaseModel):
    """A relation between two extracted terms."""

    subject: str
    predicate: RelationType
    object: str


class ExtractionResult(BaseModel):
    """Everything extracted from one document."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)

    @model_validator(mode='after')
    def _relations_respect_categories(self):
        """Drop relations whose category pair MILD/WONT does not license."""
        cat = {e.label: e.category.value for e in self.entities}
        kept, rejected = [], []
        for r in self.relations:
            sc, oc = cat.get(r.subject), cat.get(r.object)
            if sc is None or oc is None:
                rejected.append((r, 'endpoint not among extracted entities'))
                continue
            if (sc, oc) not in RELATION_DOMAINS.get(r.predicate.value, set()):
                rejected.append((r, f'{sc} -> {oc} not licensed'))
                continue
            kept.append(r)
        self.relations = kept
        self.rejected_relations = rejected
        return self

    rejected_relations: list = Field(default_factory=list, exclude=True)

