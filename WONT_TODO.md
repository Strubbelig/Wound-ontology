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

**Where things stand (2026-09-17, late).** Sixth hand edit reviewed and the
curator's calls answered. Ten CQs retired on your rulings (premise rejected,
recorded as `out_of_scope` with the reason: NF and abscess are not wounds,
laceration is not acute by definition, DFU/impaired healing/sepsis/dehiscence
are not complications *by definition*, colonization is a grade not a
complication, irrigation is not part of cleansing) — the denominator is now
**55**. Three landed: burn is a trauma (`Heat impact process ⊑ Trauma
process`, ELK infers `Thermal wound ⊑ Traumatic wound`), `Wound complication
disorder` (588) for dehiscence, `has_participant some Wound` on the wound
assessment process. Measured: **CQ 35 / 55** (15 FAIL, 5 UNRESOLVED, 18
DECLARED), ELK 0 unsatisfiable, closure 34,675 triples, unit suite 1007
passed.

Next free WONT id: **WONT_0000589**; next free MILD id: **MILD_120099**.
Mint in the `WONT_` / `MILD_` prefix — never `WOND_`. (Protégé:
Preferences → New entities → set the prefix and the 7-digit counter once.)

---

## 1. What the 20 open competency questions still need

*Measured 2026-09-17 (late): 35 PASS, 15 FAIL, 5 UNRESOLVED of 55. Items
marked* are curator's calls.*

### 1.1 Curator's calls left

| CQ | today | the call* |
|---|---|---|
| CQ044 `Necrotizing fasciitis complication_of Group A Streptococcus` | label resolves to the DOID stub; `Group A Streptococcus` (547) ⊑ pathogen | you ruled NF is an infection, not a wound (CQ005). So this CQ is about a disease, not a wound — is it in WONT's scope at all? If yes it needs WONT's own NF class with a wound causing process that has 547 as participant; if no, retire like CQ005. |
| CQ062–065 phases | `Wound healing phase` (561) is a classification grade (ICE) with four individuals (562–565) | an ICE is not `part_of` a process and a process is not `is_a` an ICE, so all four fail *by design*. Either (a) rewrite them to what the scheme says — `Proliferative phase is_about Granulation tissue formation process` — which needs the checker to read individuals, or (b) add the four fiat process parts (`Inflammation process part_of some wound healing` …) beside the scheme. (b) passes all four with no checker change. |
| CQ073 `Osteomyelitis is_a wound complication process` | 559 ⊑ material disease entity | the same ruling as CQ071 (sepsis) applies — not a wound complication by definition. Not in your list of 17 Sep; retire? |
| `Acute wound` (553) | ⊑ `Wound`, no axiom, no CQ left that names it | with CQ008 retired and no wound acute by definition, does the class stay? |

### 1.2 Anatomy — reference FMA terms, mint nothing (unchanged)

Dermis (CQ020, CQ024), subcutaneous tissue (CQ021), fascia (CQ022), plantar
foot / foot (CQ023): use the FMA IRI in WONT, `fma_module` picks up the path.
Then each CQ needs its `part_of` / `occurs_in` axiom.

### 1.3 `is_treatment_for` — nine CQs (050–055, 080–082), one decision — **the biggest lever left**

RO_0002606 is *is substance that treats*: substance/device → condition. The
device rows (CQ051 dressing, CQ081 mattress, CQ082 footwear) and CQ052
(Vancomycin) fit it; the process rows (CQ050 NPWT, CQ053 surgical debridement,
CQ054 compression therapy, CQ055 pressure offloading, CQ080 prophylactic
antibiotic therapy) do not — a process has the condition as `has_input`
(RO_0002233, already in `RelationType`). Offered 17 Sep, not yet decided:
rewrite the five process rows to `has_input`, keep `is_treatment_for` for the
four bearer rows and add it to `RelationType` (P3). Note CQ080/081/082 ask
about *prevention*; `is_treatment_for` is the wrong relation there whatever
the subject — a `Disease disorder prevention process` is missing in MILD.

### 1.4 Things landed this round that you may want to look at again

| what | why |
|---|---|
| `Method used for medical condition treatment` (199, relabelled) ⊑ `treatment plan specification` | it now says exactly what MILD_120089 says; `Method used for wound treatment` (200) could sit under MILD_120089 directly. |
| `Perioperative antimicrobial prophylaxis` (228) ⊑ `Method used for wound treatment`; `Prophylactic antibiotic therapy` (569) ⊑ `Antibiotic therapy` | prophylaxis is prevention, not treatment. `Method used for wound complication prevention` (198) was deleted this round; that was the branch they belong in. |
| `Antibiotic therapy` (16), debridement techniques, `Wound closure technique`, `Aseptic cuticle` (30) ⊑ `treatment plan specification` | "therapy" as a plan specification is one of the three readings (17 Sep); it means CQ052 `Vancomycin is_treatment_for …` and the process CQs never meet these classes. `Aseptic cuticle` is not a plan. |
| `Hypertrophic scar` (556) | moved from material disease entity to `pathological disorder` with `output_of some (Hypertrophic scarring process ⊓ has_part some Excessive collagen deposition process)` — CQ075 passes; check you agree a scar is the disorder, not the disease. |
| `Wound care procedure` (545) | a plan specification nobody references now that CQ056 asks about `Wound treatment process`. |
| `Sepsis`, `Osteomyelitis` minted | DOID has `osteomyelitis` (`DOID_1019`) and only `bacterial sepsis` (`DOID_0040085`), no plain sepsis; if the WONT classes stay, a `skos:relatedMatch` is cheap. |
| `therapeutic role` (582), `clinical function` / `therapeutic function` (583/584) | minted, referenced by nothing after the review (Vancomycin bears `antibiotic drug role`, the devices bear `pressure redistribution function`). Keep or drop. |

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
| 2026-09-17 | §1 rewritten as the class list the 43 open CQs need (your ask); old 1.2 (Wound causing process under MILD_120053) withdrawn on your ruling — a wound causing process causes with near certainty, a disease course does not. |
| 2026-09-17 | **Co-location retired for the complication pattern (rule 35)**; `output_of` replaces `is_specified_output_of` on unplanned processes; venous/arterial classes renamed; seven process classes minted; MILD commitment 4 amended; eleven CQs repointed. Closed: old 1.1 (notes written), 1.2 (you pointed Diabetic wound at the parent), 1.3 (you added the axiom; I restored the asserted parent). |
| 2026-09-17 | **Sixth hand edit reviewed (night).** 44 classes landed and renumbered (`WOND_120067–072`, `WONT_000600–638` → `WONT_0000544–587`). Fixes: unlabelled empty class dropped; `Surgical debridement process` and `Diagnostic process` dropped as duplicates of 299 / MILD_120047 (children reparented to `Wound diagnostic process`); `Sustained mechanical load process` folded into `Pressure impact process` (519) as alt terms — same definition; `Granulation process` (132) had been deleted and re-minted — IRI restored, new label kept; `Laceration` ⊑ material entity → ⊑ `Traumatic wound`; `Diabetic foot ulcer` ⊑ `Diabetic wound`; `Wound complication` ⊑ MILD_120051, SSI under it; the local-anaesthetic process had the *antibiotic* drug role as filler → `local anaesthetic drug role` (585); Vancomycin `has_function therapeutic function` → `has_role antibiotic drug role`; footwear/mattress ⊑ `device` bearing `pressure redistribution function`, offloading process realizes it; `Wound causing neuropathic disease process` put on the rule-35 shape with `Neuropathic disease process` (586, participant DOID_574); `Foreign body wound` on the rule-35 shape with `Wound causing foreign body process` (587); phases → individuals of `Wound healing phase` (grades are individuals, 1.2); old labels of the three intention classes kept as alt terms (CQ060/061 had regressed); `threshold specification` → MILD_120098. CQ file: 14 label fixes, CQ003 and CQ056 rewritten. Blocklist: 4 entries removed. **CQ 22 → 32 / 65.** |
| 2026-09-17 | **Curator's calls answered (late).** CQ004/072/100 rewritten and made to pass (`Heat impact process ⊑ Trauma process`; `Wound complication disorder` 588 with dehiscence under it and the disease-level class having it as part; `has_participant some Wound` on 89; checker gained `has_participant`, 1 test, mutation-checked). CQ005/007/008/031/034/042/045/057/071/074 retired as `out_of_scope` with your reasons; dehiscence confirmed not a wound development (its process was already a disorder development process). **CQ 32/65 → 35/55.** |
