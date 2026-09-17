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

**Where things stand (2026-09-17, evening).** The co-location axiom is gone.
Every aetiological wound class — angiopathic, autoimmune, diabetic, venous
insufficiency (was *co-located with impaired venous backflow*), arterial
insufficiency (was *… impaired arterial inflow*), traumatic, thermal,
malignant, pressure ulcer — is on one shape, MILD's own complication pattern
(INSTRUCTIONS rule 35): `≡ Wound ⊓ output_of some (Wound development process
⊓ has_part some Wound causing X process)`. `is_specified_output_of` was
replaced by `output_of` on the six unplanned processes (Wound, Angiopathic,
Autoimmune, Thermal, Traumatic, Wound dehiscence); the planned ones
(classification and diagnostic results) keep it. Seven process classes
minted (`WONT_0000537–543`). MILD commitment 4 amended to say so. Eleven CQs
moved from `co_located_with` to `complication_of`. Measured: **CQ 22 / 65**
(CQ032 and CQ033 now pass; CQ002 kept passing once `Pressure ulcer` got its
asserted parent back and the `is_a` check learned to see through a defining
axiom), ELK 0 unsatisfiable, closure 34,370 triples. Unit suite 1006 passed.

Next free WONT id: **WONT_0000544**; next free MILD id: **MILD_120098**.
Mint in the `WONT_` / `MILD_` prefix — never `WOND_`. (Protégé:
Preferences → New entities → set the prefix and the 7-digit counter once.)

---

## 1. Modelling decisions — yours, not mechanical

| # | what | where | my recommendation |
|---|---|---|---|
| 1.1 | **The nine remaining `complication_of` CQs are UNRESOLVED or FAIL because the classes do not exist**: `Sustained Mechanical Load` (CQ030), `Diabetic Foot Ulcer` / `Peripheral Neuropathy` (031), `Impaired Wound Healing` (034), `Bacterial Colonization` (042, 045), `Foreign Body Wound` / `Foreign Body` (043), `Group A Streptococcus` (044), `Hypertrophic Scar` / `Excessive Collagen Deposition` (075); CQ074 (`Wound Dehiscence complication_of wound infection process`) has both classes and no axiom. Each is either a class to mint on the rule-35 shape or a question to retire. | CQ file / WONT | decide per row; CQ074 is one axiom away |
| 1.2 | **`Wound causing process` (418) could be placed under MILD_120053** ("disease course process putting out disorders as part of a complication") when the X is a disease process — that is what the `Wound causing angiopathic disease process` family *is*. Today 418 ⊑ MILD_120021 only. One axiom: `Wound causing process ⊓ MILD_120028 ⊑ MILD_120053`, or simply make each `Wound causing <disease> process` ⊑ MILD_120053. | WONT_0000418, 537–543 | assert it on the five disease-process members; it ties WONT's pattern to MILD's by name |
| 1.3 | The three formerly co-located classes lost the note that explained the co-location reading; each now carries a `COMPLICATION, NOT CAUSATION, NOT CO-LOCATION` note I wrote. Read them. | WONT_0000015, 0000033, 0000088, 0000384, 0000510 | — |

## 2. Small things

| # | what |
|---|---|
| 2.1 | Definitions written in review are first drafts in the house pattern (36 on 12 Sep; 3 + 17 on 16 Sep; 3 + 7 process classes + 5 rewritten wound definitions on 17 Sep). |
| 2.2 | `hp_module.owl` was re-saved by Protégé once (header only) — reverted. Modules are build outputs; if Protégé asks to save one, say no. |

---

## Log

| date | what |
|---|---|
| 2026-09-10 | File created: A (chronic axiom), B (3 MILD parents), C (orphan patch — withdrawn), D, E (determinate-quality block), F (import closure). |
| 2026-09-12 | A, E (mostly) and F2 applied by hand and reviewed; B closed as never missing. |
| 2026-09-14 | Rewritten to hold only what is open. Previous full text in git history (`8896bf9`). |
| 2026-09-16 | Second and third hand edits reviewed; `fma_module`; chronic branch withdrawn; CDC/IWII split; nine CQs rewritten; anchors fixed. |
| 2026-09-17 | Fourth hand edit reviewed; malignancy qualities and the OGMS relatedMatch to MILD; foreign roots accepted (rule 34 refined). |
| 2026-09-17 | **Co-location retired for the complication pattern (rule 35)**; `output_of` replaces `is_specified_output_of` on unplanned processes; venous/arterial classes renamed; seven process classes minted; MILD commitment 4 amended; eleven CQs repointed. Closed: old 1.1 (notes written), 1.2 (you pointed Diabetic wound at the parent), 1.3 (you added the axiom; I restored the asserted parent). |
