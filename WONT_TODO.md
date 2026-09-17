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

**Where things stand (2026-09-17, night).** Sixth hand edit reviewed: 44 of
the 31 listed classes plus the therapy scaffolding landed (`WONT_0000544–587`
after renumbering; `WOND_1200xx` and 6-digit `WONT_0006xx` were both minted —
set the Protégé counter). Review fixes are listed in the log. `threshold
specification` moved to MILD (`MILD_120098`): MILD had been made a subclass
of a WONT class through a relative IRI, and MILD never imports WONT. Measured:
**CQ 32 / 65** (27 FAIL, 6 UNRESOLVED, 8 DECLARED), ELK over the skeleton 0
unsatisfiable, closure 34,661 triples, all 165 external terms labelled, unit
suite 1006 passed. Four blocklist entries (`sepsis`, `osteomyelitis`,
`vancomycin`, `inflammatory phase`) removed because WONT now asserts classes.

Next free WONT id: **WONT_0000588**; next free MILD id: **MILD_120099**.
Mint in the `WONT_` / `MILD_` prefix — never `WOND_`. (Protégé:
Preferences → New entities → set the prefix and the 7-digit counter once.)

---

## 1. What the 33 open competency questions still need

*Measured 2026-09-17 (night): 32 PASS, 27 FAIL, 6 UNRESOLVED of 65. Grouped
by what has to happen. Items marked* are curator's calls.*

### 1.1 Curator's calls — one decision each, then one axiom or one CQ rewrite

| CQ | today | the call* |
|---|---|---|
| CQ004 `Thermal wound is_a Traumatic wound` | siblings under `Wound` | is a burn a trauma? If yes, one `rdfs:subClassOf`. |
| CQ005 `Necrotizing fasciitis is_a Soft tissue wound` | label resolves to the DOID stub (a disease) | mint WONT's own `Necrotizing fasciitis` ⊑ `Soft tissue wound` (551) — or rewrite: NF is an infection, its wound is a *complication*. Also unlocks CQ044 (needs `Wound causing … process has_participant some Group A Streptococcus` (547)). |
| CQ007 `Abscess is_a Wound` | ⊑ pathological disorder | is an abscess a wound? |
| CQ008 `Laceration is_a Acute wound` | `Acute wound` (553) ⊑ `Wound`, no defining axiom | under "every wound starts acute" an `Acute wound` class is hard to give a definition. Either `≡ Wound ⊓ has_quality some acute` + `Laceration ⊑ has_quality some acute`, or rewrite CQ008 to `Laceration is_a Traumatic wound` (passes today). |
| CQ031 `Diabetic foot ulcer complication_of peripheral nervous system disease` | DFU (549) ⊑ `Diabetic wound`; `Wound causing neuropathic disease process` (560) exists on the rule-35 shape | is *every* DFU neuropathic? If yes: `DFU ⊑ output_of some (WDP ⊓ has_part some 560)`. If not, the CQ overstates. |
| CQ034 `Wound healing disorder complication_of Diabetic metabolic disorder` | 408 has no axiom | same shape as the wounds, with `Impaired wound healing process` (544) as the development process — if you hold that a healing disorder is *output of* impaired healing. |
| CQ042 / CQ045 `… complication_of Bacterial colonization process` | 566 ⊑ process, nothing links it | `Wound infection process ⊑ has_part some 566`? The checker wants `output_of` on the subject; an infection *process* is not an output. Rewrite both to `has_part` / `preceded_by`. |
| CQ057 `wound irrigation process part_of wound cleansing process` | siblings | irrigation is a *kind* of cleansing: `411 ⊑ 387` and rewrite to `is_a`. |
| CQ062–065 phases | `Wound healing phase` (561) is a classification grade (ICE) with four individuals (562–565), as you built it | an ICE is not `part_of` a process and a process is not `is_a` an ICE, so all four CQs fail *by design*. Either (a) rewrite them to what the scheme says — `Proliferative phase is_about Granulation tissue formation process` — which needs the checker to read individuals, or (b) add the four fiat process parts (`Inflammation process part_of some wound healing` …) beside the scheme, as discussed on 17 Sep. (b) passes all four with no checker change. |
| CQ071 `Sepsis is_a Infectious complication` | 558 ⊑ material disease entity | not every sepsis is a wound complication. Rewrite to `Sepsis complication_of Wound`? That needs the pattern on Sepsis, which is equally false in general. Recommend: out of scope, or a `Wound related sepsis` class. Same for CQ073 `Osteomyelitis` (559). |
| CQ072 `Wound dehiscence is_a Wound complication` | dehiscence ⊑ pathological disorder; `Wound complication` (557) ⊑ MILD_120051 material *disease* entity | disorder vs disease. Either a disorder-level sibling (`Wound complication disorder`) or accept that dehiscence is the disorder inside a wound-complication disease. |
| CQ074 `Wound dehiscence complication_of wound infection process` | — | is dehiscence a *wound development*? (open since 16 Sep) |
| CQ100 `clinical wound assessment occurs_in Wound` | — | question is wrong: a wound is not a site. Rewrite to `has_participant`. |

### 1.2 Anatomy — reference FMA terms, mint nothing (unchanged)

Dermis (CQ020, CQ024), subcutaneous tissue (CQ021), fascia (CQ022), plantar
foot / foot (CQ023): use the FMA IRI in WONT, `fma_module` picks up the path.
Then each CQ needs its `part_of` / `occurs_in` axiom.

### 1.3 `is_treatment_for` — nine CQs (050–055, 080–082), one decision

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
