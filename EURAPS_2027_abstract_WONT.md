# EURAPS 2027 abstract — wound ontology

Deadline 20 October 2026. Limit 300 words (body). Fixed headings: Introduction /
Materials and Methods / Results / Conclusion. No institution, city or address in
title or body — penalty is exclusion. Previously presented at ASRM, so the
prior-presentation rule applies: this version must carry substantially new data,
which it does (the ASRM text proposed a framework and reported no results).

Numbers: ontology counts from the 2026-10-11 build (output/owl/core_build_report.json);
corpus funnel from output/figure_abstracts_to_wont_2026-10-05_12-49.json;
competency questions from output/competency_report.md. Re-check after the pending
rebuild before submitting.

## Title

What Is a Wound? A Computable Definition for Reconstructive Surgery, Built and Logically Verified

## Abstract body

**Introduction**

Plastic surgeons treat wounds daily, yet "wound" denotes different things in operative notes, registries and trials: a diabetic plantar ulcer, an irradiated scalp defect and a traumatic lower-limb soft-tissue loss share a label but not biology or reconstructive demand. Free text cannot express these distinctions, weakening comparative research and blocking decision support. We asked whether the reasoning surgeons apply to wounds can be formalised, machine-verified, and shown to answer clinical questions.

**Materials and Methods**

A purpose-built ontology learning pipeline, combining large language models with Formal Concept Analysis, extracted terms and relations from 6,029 wound-related abstracts, giving 96,239 strings and 32,519 distinct in-scope terms; those recurring in at least two abstracts were carried forward. Every parent-child assignment was ruled on individually, not accepted from automated suggestion. Terms that could not be placed soundly were held back. Relations became axioms only where they held of every instance, not some. The result aligns to Basic Formal Ontology and reuses established biomedical ontologies. Consistency was tested by automated reasoning, scope against 73 predefined competency questions.

**Results**

The ontology grew from 489 to 3,535 classes on 3,039 parent-child and 2,023 category axioms, with 4,104 further terms kept apart as unverified. Of 1,007 typed relations, 203 held of every instance; 44 entered the ontology, with 42 further axioms added on expert review. Formal Concept Analysis proved non-expressive here and contributed no axioms. No class was unsatisfiable, and the full imported closure of roughly 9,200 classes was consistent. All 49 in-scope competency questions were answered correctly; 24 were declared outside scope.

**Conclusion**

Wound terminology can be made computable without loosening it: strict admission left most extracted terms out, and what remains is verified. This gives reconstructive surgery a machine-readable vocabulary for registry design, outcome research and decision support.
