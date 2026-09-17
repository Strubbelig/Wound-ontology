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

**Where things stand (2026-09-17, evening).** Measured: **CQ 48 / 52**, ELK
0 unsatisfiable, closure 34,787 triples, 167 external terms all labelled,
unit suite 1009 passed. Everything answered so far is in the log and in git;
this file holds only what is still open.

Next free WONT id: **WONT_0000590**; next free MILD id: **MILD_120101**.
Mint in the `WONT_` / `MILD_` prefix — never `WOND_`. (Protégé:
Preferences → New entities → set the prefix and the 7-digit counter once.)

---

## 1. The four open competency questions — all FMA anatomy

FMA owns the anatomy; WONT references the IRI and `fma_module` carries the
path (rule 34). FMA states parthood with its own `fma#constitutional_part_of`
/ `fma#regional_part_of` (32,060 uses in `fma_obo.owl`), never `BFO_0000050`,
and the MIREOT extraction carries only the subclass path — so no FMA-internal
parthood ever reaches the closure, and rule 34 forbids asserting it for them.

| CQ | asks | WONT class and relation | verdict |
|---|---|---|---|
| CQ023 | `Diabetic foot ulcer part_of Plantar foot` | **`Diabetic foot ulcer` (549) `located_in some Foot` (`FMA_9664`)** — the one clean case, and the class's natural definition (`≡ Diabetic wound ⊓ located_in some Foot`). `Plantar part of foot` is `FMA_25000`, but dorsal and interdigital DFUs exist, so *foot*, not *plantar*; and `located_in`, not `part_of` — a wound is in the foot, not a part of it. Rewrite the CQ to match. | do it |
| CQ024 | `Dermis part_of Skin` | no WONT class: it is FMA's own fact (`FMA_70323 constitutional_part_of FMA_7163`), stated in FMA's relation, and we do not restate it. `Skin wound` (already `located_in some Skin`) is the nearest WONT class. | retire or ask the FMA fact of `fma_obo.owl` directly |
| CQ020 | `Wound healing occurs_in Dermis` | no class truthfully: healing of a dermal wound occurs in the dermis, healing as such does not. | retire, or rewrite to `Skin wound located_in Skin` (passes today) |
| CQ021 | `Pressure ulcer part_of Subcutaneous tissue` | not by definition — a stage-1 pressure ulcer is intact skin; `Subcutaneous tissue` is FMA's `Superficial fascia` (`FMA_9630`, exact synonym). | retire |

## 2. Open questions you raised, not yet decided

| # | what |
|---|---|
| 2.1 | Naming under plan specification: should every class under a plan specification carry "plan specification" in its name (`Antibiotic therapy` → `Antibiotic therapy plan specification`)? You raised it on 17 Sep; not applied. |
| 2.2 | `Hypertrophic scarring process` (154) ⊑ `Pathological scarring process` (269) and `Excessive collagen deposition process` (567) ⊑ disorder development process both still say *abnormal*, while `Hypertrophic scar` (556) no longer does. `Scarring process` (471) is the non-pathological parent available. |
| 2.3 | `Inflammatory phase` (563) is the one grade with no `is_about`: WONT has no inflammation process class (GO's would need `--leaf-modules`). |

## 3. Standing notes

| # | what |
|---|---|
| 3.1 | Definitions written in review are first drafts in the house pattern. Never on a foreign class (rule 34, refined 17 Sep). |
| 3.2 | Modules are build outputs; if Protégé asks to save one, say no. |

---

## Log

| date | what |
|---|---|
| 2026-09-10 | File created: A (chronic axiom), B (3 MILD parents), C (orphan patch — withdrawn), D, E (determinate-quality block), F (import closure). |
| 2026-09-12 | A, E (mostly) and F2 applied by hand and reviewed; B closed as never missing. |
| 2026-09-14 | Rewritten to hold only what is open. Previous full text in git history (`8896bf9`). |
| 2026-09-16 | Second and third hand edits reviewed; `fma_module`; chronic branch withdrawn; CDC/IWII split; nine CQs rewritten; anchors fixed. |
| 2026-09-17 | Fourth hand edit reviewed; malignancy qualities and the OGMS relatedMatch to MILD; foreign roots accepted (rule 34 refined). |
| 2026-09-17 | §1 rewritten as the class list the 43 open CQs need (your ask); old 1.2 (Wound causing process under MILD_120053) withdrawn on your ruling — a wound causing process causes with near certainty, a disease course does not. |
| 2026-09-17 | **Co-location retired for the complication pattern (rule 35)**; `output_of` replaces `is_specified_output_of` on unplanned processes; venous/arterial classes renamed; seven process classes minted; MILD commitment 4 amended; eleven CQs repointed. Closed: old 1.1 (notes written), 1.2 (you pointed Diabetic wound at the parent), 1.3 (you added the axiom; I restored the asserted parent). |
| 2026-09-17 | **Sixth hand edit reviewed (night).** 44 classes landed and renumbered (`WOND_120067–072`, `WONT_000600–638` → `WONT_0000544–587`). Fixes: unlabelled empty class dropped; `Surgical debridement process` and `Diagnostic process` dropped as duplicates of 299 / MILD_120047 (children reparented to `Wound diagnostic process`); `Sustained mechanical load process` folded into `Pressure impact process` (519) as alt terms — same definition; `Granulation process` (132) had been deleted and re-minted — IRI restored, new label kept; `Laceration` ⊑ material entity → ⊑ `Traumatic wound`; `Diabetic foot ulcer` ⊑ `Diabetic wound`; `Wound complication` ⊑ MILD_120051, SSI under it; the local-anaesthetic process had the *antibiotic* drug role as filler → `local anaesthetic drug role` (585); Vancomycin `has_function therapeutic function` → `has_role antibiotic drug role`; footwear/mattress ⊑ `device` bearing `pressure redistribution function`, offloading process realizes it; `Wound causing neuropathic disease process` put on the rule-35 shape with `Neuropathic disease process` (586, participant DOID_574); `Foreign body wound` on the rule-35 shape with `Wound causing foreign body process` (587); phases → individuals of `Wound healing phase` (grades are individuals, 1.2); old labels of the three intention classes kept as alt terms (CQ060/061 had regressed); `threshold specification` → MILD_120098. CQ file: 14 label fixes, CQ003 and CQ056 rewritten. Blocklist: 4 entries removed. **CQ 22 → 32 / 65.** |
| 2026-09-17 | **Curator's calls answered (late).** CQ004/072/100 rewritten and made to pass (`Heat impact process ⊑ Trauma process`; `Wound complication disorder` 588 with dehiscence under it and the disease-level class having it as part; `has_participant some Wound` on 89; checker gained `has_participant`, 1 test, mutation-checked). CQ005/007/008/031/034/042/045/057/071/074 retired as `out_of_scope` with your reasons; dehiscence confirmed not a wound development (its process was already a disorder development process). **CQ 32/65 → 35/55.** |
| 2026-09-17 | **Last calls answered (end of day).** CQ044/073 retired; CQ062–065 rewritten to the scheme (`561 is_about wound healing`; grades `is_about` hemostasis / epithelialization + granulation / tissue remodeling; checker reads individuals); CQ050–055/080–082 rewritten to participation, `is_treatment_for` withdrawn. **CQ 35/55 → 48/53.** |
| 2026-09-17 | **§1.4 answered (evening).** 199 → MILD_120099; prophylaxis plan specification MILD_120100; hypertrophic scar ⊑ material entity; 545 dropped; relatedMatch on sepsis/osteomyelitis; 65 foreign definitions removed from WONT (rule 34 refined); CQ022 retired. **CQ 48/53 → 48/52.** §1.2 now says which class gets which FMA relation. |
| 2026-09-17 | File cut to what is open: the four FMA CQs, three undecided questions, two standing notes. Everything done is in this log. |
