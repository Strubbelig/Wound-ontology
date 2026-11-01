# ICOPLAST 2027 abstract — wound ontology (plain-language version)

4th ICOPLAST World Congress, Berlin, 24-26 June 2027 (hosted by DGPRAEC).
Call for abstracts: 31 July - **15 October 2026**. Portal: conftool.pro/icoplast-dgpraec-2027
Word limit, required headings and prior-presentation rules are NOT published on the
public pages - confirm in the portal. Two versions below: 300 words and 258 words.
Suggested category: "Burns and wound healing" (alternative: "Health policy").
Unlike EURAPS, ICOPLAST lists "experimental surgery" and does not restrict to
clinical research, so this work needs no separate research-council route.

## Title

What Is a Wound? A Computable Definition for Reconstructive Surgery

## Version A - 300 words with headings

**Introduction**

Plastic surgeons treat wounds every day, yet "wound" means different things in operative notes, registries and trials. A diabetic foot ulcer, an irradiated scalp defect and a traumatic leg wound share that label but differ in biology, reconstruction and expected outcome. Free text cannot record these differences in a form a computer can use, so studies are hard to compare and decision support hard to build. We asked whether the distinctions surgeons already make can be written down as a model a computer can check.

**Methods**

We built such a model for wounds: a hierarchy in which every concept is a kind of something more general, with explicit rules linking them. Concepts and relations were gathered from 6,029 published wound abstracts by a pipeline we built ourselves, combining large language models with Formal Concept Analysis, a mathematical method that groups concepts by shared properties. Nothing was accepted on an automatic proposal alone: a human reviewer ruled on every placement, anything unjustified was dropped, and a relation became a rule only where it held for every example.

**Results**

The model grew from 489 to 3,535 concepts, and a further 4,104 candidates were left out because they could not be verified. Formal Concept Analysis added nothing, because wound properties are reported too sparsely to form meaningful groups. Automated logical checking found no self-contradictory concept, either in the model alone or together with the established biomedical vocabularies it draws on, some 9,200 concepts in all. Of 73 clinical questions agreed in advance, all 49 within the intended scope were answered correctly.

**Conclusion**

Wound terminology can be made precise enough for a computer without being loosened to fit: most of what was extracted was refused, and what remains is logically consistent. This gives reconstructive surgery a shared, machine-readable vocabulary for registries, outcome research and decision support.

## Version B - 258 words with headings

**Introduction**

Plastic surgeons treat wounds every day, yet "wound" means different things in operative notes, registries and trials. A diabetic foot ulcer, an irradiated scalp defect and a traumatic leg wound share that label but differ in biology, reconstruction and expected outcome. Free text cannot record these differences in a form a computer can use. We asked whether the distinctions surgeons already make can be written down as a model a computer can check.

**Methods**

We built such a model for wounds: a hierarchy in which every concept is a kind of something more general, with explicit rules linking them. Concepts and relations were gathered from 6,029 published wound abstracts by a pipeline we built ourselves, combining large language models with Formal Concept Analysis, a mathematical method that groups concepts by shared properties. Nothing was accepted on an automatic proposal alone: a human reviewer ruled on every placement, anything unjustified was dropped, and a relation became a rule only where it held for every example.

**Results**

The model grew from 489 to 3,535 concepts, and a further 4,104 candidates were left out because they could not be verified. Formal Concept Analysis added nothing, because wound properties are reported too sparsely to form meaningful groups. Automated logical checking found no self-contradictory concept. Of 73 clinical questions agreed in advance, all 49 within the intended scope were answered correctly.

**Conclusion**

Wound terminology can be made precise enough for a computer without being loosened to fit. This gives reconstructive surgery a shared, machine-readable vocabulary for registries, outcome research and decision support.

