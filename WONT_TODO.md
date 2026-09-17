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

## 1. What the 43 open competency questions need

*Measured 2026-09-17 against the current closure: 22 PASS, 5 FAIL, 38
UNRESOLVED of 65 in scope. Every UNRESOLVED names a label no class carries;
every FAIL has the classes and lacks an axiom. Grouped by what has to exist,
not by question. Counts are CQs unlocked. Anything marked* is a curator's
call on whether the concept belongs in WONT at all.*

### 1.1 Not new classes — a label fix in the CQ file, or an alt term

| CQ | asks for | WONT has | fix |
|---|---|---|---|
| CQ041 | `Clean Wound` | `Clean wound according to IWII` (527) | alt term `Clean wound` on 527, or `label_fix` |
| CQ054 | `Venous Leg Ulcer` | `Ulcus cruris venosum` | `label_fix` (CQ006 already does this) |
| CQ034 | `Impaired Wound Healing` | `Wound healing disorder` | `label_fix`, or alt term |
| CQ056 | `Wound Care Procedure` | `Wound treatment process` | `label_fix` |
| CQ030 | `Sustained Mechanical Load` | `Pressure impact process` (519) | alt term on 519 |
| CQ063 | `Re-Epithelialization` | `Epithelialization process` | alt term — but see 1.4 for the other half of the triple |
| CQ004 | `Burn Injury is_a Traumatic Wound` | `Thermal wound` ⊑ `Wound` | alt term `Burn injury` on 310 **and decide*** whether thermal ⊑ traumatic (a burn is a trauma; today they are siblings) |
| CQ044 | `Group A Streptococcus` | `Streptococcus` (NCBITaxon_1301) only | reference NCBITaxon_1314 *Streptococcus pyogenes* in WONT; the module picks it up |
| CQ052 | `Vancomycin` | — | reference the CHEBI/DRON term (CHEBI_28001) in WONT; the module picks it up |

### 1.2 Anatomy — reference FMA terms, mint nothing

FMA owns these; WONT uses the IRI and `fma_module` carries the path (rule 34).
Dermis (CQ020, CQ024), subcutaneous tissue (CQ021), fascia (CQ022), plantar
foot / foot (CQ023). The four CQs then need the axiom each asks for
(`part_of` / `occurs_in`). CQ020 `Wound healing occurs_in Dermis` — check
the question: healing of a dermal wound occurs in the dermis, but healing
as such does not.

### 1.3 Classes to mint — wounds and disorders (material)

| class | shape | CQs |
|---|---|---|
| **Diabetic foot ulcer** | `≡ Diabetic wound ⊓ located_in some <FMA foot>` | CQ023, CQ031, CQ051, CQ082 — **4**, the single most valuable class |
| **Surgical site infection** | ⊑ `Wound infection process`? or a disorder — decide*; CQ003 asks for the process (`is_a wound complication process`), CQ080 treats it | CQ003, CQ080 |
| **Soft tissue wound** | ⊑ `Wound`; `Necrotizing fasciitis` (WONT's own, not the DOID stub) ⊑ it | CQ005 |
| **Laceration** and **Acute wound** | `Acute wound ≡ Wound ⊓ has_quality some acute` (476) — a quality-defined class is fine; only *subclasses* under a course class were the error; `Laceration ⊑ Traumatic wound` | CQ008 |
| **Foreign body wound** + **Foreign body** | `Foreign body wound ≡ Wound ⊓ output_of some (WDP ⊓ has_part some Wound causing foreign body process)`; `Foreign body` ⊑ material entity | CQ043 |
| **Hypertrophic scar** (the disorder; WONT has only the scarring *process*) | ⊑ `MILD_120022`, output_of some `Hypertrophic scarring process` | CQ075 (+ 1.5) |
| **Sepsis**, **Osteomyelitis** | disorders/diseases; CQ071 and CQ073 ask `is_a Infectious complication` / `is_a wound complication process` — a disorder is not a process, so either mint a material **Wound complication** (⊑ MILD_120051-style: a disorder that is output_of some wound-course process) and put `Wound dehiscence`, `Sepsis`, `Osteomyelitis` under it, or rewrite CQ071–073 to `complication_of Wound` | CQ071, CQ072, CQ073 |
| **Peripheral neuropathy** | disorder (DOID has it — reference, don't mint) + `Wound causing neuropathic disease process` on the rule-35 shape | CQ031 |

### 1.4 Classes to mint — processes

| class | shape | CQs |
|---|---|---|
| **Wound healing phase** + **Inflammatory phase**, **Proliferative phase** (and hemostasis, remodelling for completeness) | `Wound healing phase ⊑ process ⊓ part_of some Wound healing process`; each phase ⊑ it | CQ062–065 — **4** |
| **Granulation tissue formation** | ⊑ `Wound healing phase` or ⊑ `Proliferative phase` | CQ062 |
| **Bacterial colonization process** | ⊑ process, has_participant some Bacteria; `Wound infection process` and `Wound biofilm` (exists) then need `complication_of` axioms on it | CQ042, CQ045 |
| **Excessive collagen deposition process** | ⊑ process, part_of some `Hypertrophic scarring process` | CQ075 |

### 1.5 Classes to mint — interventions, devices, diagnostics

All the `is_treatment_for` rows also wait on `RelationType` gaining
RO_0002606 (ROADMAP P3); the class alone moves them UNRESOLVED → FAIL.

| class | kind | CQs |
|---|---|---|
| **Surgical debridement** | ⊑ `Debridement process` (WONT has mechanical and biosurgical; not surgical) | CQ053 |
| **Pressure offloading** | ⊑ `Wound treatment process` | CQ055 |
| **Prophylactic antibiotic therapy** | ⊑ treatment process (WONT has `topical antibiotic therapy`) | CQ080 |
| **Pressure redistribution mattress**, **Therapeutic footwear** | ⊑ device (`Wound dressing`'s sibling under the WONT device branch) | CQ081, CQ082 |
| **Bacterial culture process** | ⊑ `Wound diagnostic process` | CQ101 |
| **Vascular assessment process** + **Ankle-brachial index measurement** | ⊑ `Wound diagnostic process` | CQ102 |
| **Wound photography process** | ⊑ `Wound documentation process` | CQ104 |
| **Wound healing criterion** + **Complete epithelialization** | ICE (⊑ IAO_0000030) — or rewrite CQ113 to `Epithelialized wound has_quality epithelialized`, which is what WONT asserts | CQ113 |

### 1.6 Axioms only — the five FAILs

| CQ | needs | note |
|---|---|---|
| CQ007 `Abscess is_a Wound` | one `rdfs:subClassOf` — **decide*** | `Abscess` (472) ⊑ pathological disorder today. Is an abscess a wound? |
| CQ050 `NPWT is_treatment_for Chronic wound` | an `RO_0002606` restriction on NPWT — and the relation in `RelationType` (P3) | first `is_treatment_for` axiom in the file |
| CQ057 `wound irrigation process part_of wound cleansing process` | one restriction | siblings today |
| CQ074 `Wound dehiscence complication_of wound infection process` | rule-35 shape: `Wound dehiscence ≡ … output_of some (Wound dehiscence process ⊓ has_part some (Wound infection process ⊓ Wound causing process))` — **decide*** whether dehiscence is a *wound* development at all | |
| CQ100 `clinical wound assessment occurs_in Wound` | question is wrong: `occurs_in` takes a site, a wound is a material entity. Rewrite to `has_participant` / `is_about`. | CQ file |

### 1.7 Totals

Mint ≈ **30 classes** (9 material, 8 process, 13 intervention/diagnostic),
reference **7 foreign terms** (4 FMA, 1 NCBITaxon, 1 CHEBI/DRON, 1 DOID),
**9 CQ-file fixes**, **5 axioms**, **3 curator's calls** (abscess, thermal ⊑
traumatic, dehiscence). Ceiling if all of it lands and P3 adds
`is_treatment_for`: 65 / 65. Without P3: 55.

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
