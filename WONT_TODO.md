# Curated-ontology change list

Changes that must be made **by hand**, because the pipeline is never allowed to
write to a curated file (INSTRUCTIONS, standing rule). Two files are involved:

| file | path | note |
|---|---|---|
| **WONT** | `data/ground truth/ground_truth_final.owl` | Turtle, despite the `.owl` extension — parse with `parse_graph`, not the XML reader |
| **MILD** | `../Disease ontologies/Disease proposal 2.ttl` | imported by WONT via `owl:imports` |

After an edit nothing needs running by hand: the skeleton rebuilds when a gate
next reads it and the extraction schema regenerates when extraction next starts
(rule 32). If the edit used a new external term, regenerate the modules
(`../Disease ontologies/build_disease_proposal.sh --no-reason`, rule 34) —
never import a source ontology directly.

**Where things stand (2026-09-17).** Four rounds of hand edits reviewed.
Latest: `Pressure ulcer` minted, the diabetes disease processes given a
parent with type I and II under it, `Wound causing process` narrowed to
`Anatomical structure`, the HP stubs reduced to bare declarations (the module
carries them). Review: 3 new IRIs renumbered `WOND_120064–66` → `WONT_0000534–536`;
direct `fma.owl` import removed again and the WONT catalog repointed at
`fma_module` (it had been mapped to the 66 MB `fma_obo.owl`); `degree of
malignancy` / `benign` / `malignant` moved to MILD as `MILD_120095–097`; the
`MILD_120028 relatedMatch OGMS_0000063` annotation moved to MILD; MILD header
records that foreign roots are accepted, not bridged. The build no longer
grounds FMA under BFO (your ruling: we author axioms about our own classes
only — INSTRUCTIONS rule 34). Measured: **CQ 22 / 65**, ELK 0 unsatisfiable,
closure 34,286 triples, roots beside `entity`: `disease`, `unit`, `anatomical
entity` (all three by design). Unit suite 1005 passed.

Next free WONT id: **WONT_0000537**; next free MILD id: **MILD_120098**.
Mint in the `WONT_` / `MILD_` prefix, main series — never `WOND_`. (Protégé:
Preferences → New entities → set the prefix and the 7-digit counter once.)

---

## 1. Modelling decisions — yours, not mechanical

| # | what | where | my recommendation |
|---|---|---|---|
| 1.1 | **Aetiology through process mereology.** The five wound classes are `≡ Wound ⊓ output_of some (Wound development process ⊓ has_part some <X disease process>)`. That is process-part, not causation, so it keeps MILD commitment 4 — but the three that used to be *co-location* classes (diabetic, angiopathic, autoimmune) have lost that reading: `Diabetic wound` no longer says it shares a material disease entity with a `Diabetic metabolic disorder`. Nothing is wrong; it is a change of commitment worth an `IAO_0000116` on each of the three saying why. | WONT_0000015, 0000033, 0000088 | write the note; consider keeping the co-location axiom *beside* the process one — they are independent claims |
| 1.2 | **`Diabetic wound` is still defined over `Diabetes mellitus type II disease process` (520)** although you minted the parent `Diabetes mellitus disease process` (535) with type I (536) and II under it. As it stands a wound in a type I diabetic is not a `Diabetic wound`. | WONT_0000088 | point the `has_part some` filler at 535 |
| 1.3 | **`Pressure ulcer` (534) is a bare subclass of `Wound`.** Your own pattern gives it a defining axiom: `≡ Wound ⊓ output_of some Wound causing pressure impact process` (WONT_0000245), as `Traumatic wound` and `Thermal wound` have. I wrote the definition that way; the axiom is yours to add. | WONT_0000534 | add the equivalence |

## 2. Small things

| # | what |
|---|---|
| 2.1 | Definitions written in review are first drafts in the house pattern: 36 (12 Sep), 3 + 17 (16 Sep), 3 (17 Sep: `Pressure ulcer`, the two diabetes processes; and the three malignancy qualities now in MILD). The CDC grade wordings follow the CDC/NHSN classification; the process ones are mine. |
| 2.2 | `hp_module.owl` was re-saved by Protégé (header and OWL-API version line only) — reverted. Modules are build outputs; if Protégé asks to save one, say no. |

---

## Log

| date | what |
|---|---|
| 2026-09-10 | File created: A (chronic axiom), B (3 MILD parents), C (orphan patch — withdrawn), D, E (determinate-quality block), F (import closure). |
| 2026-09-12 | A, E (mostly) and F2 applied by hand and reviewed; B closed as never missing. Details in ROADMAP changelog. |
| 2026-09-14 | Rewritten to hold only what is open. Previous full text in git history (`8896bf9`). |
| 2026-09-16 | Second and third hand edits reviewed; `fma_module`; chronic branch withdrawn; CDC/IWII split; nine CQs rewritten; anchors fixed. |
| 2026-09-17 | Fourth hand edit reviewed. Your rulings: malignancy qualities and the OGMS relatedMatch belong in MILD (moved); `unit`, `disease`, `anatomical entity` stay unbridged — we author axioms about our own classes only (rule 34 refined, FMA grounding removed from the build, MILD header says so). Closed: old 1.1, 1.3 (class minted; axiom still open as new 1.3), 1.4, 1.5 (hierarchy minted; filler still open as new 1.2), 2.2, 2.3. `located_in` left `ALLOWED_PREDICATES` again — with Skin outside BFO the schema licenses no pair for it. |
