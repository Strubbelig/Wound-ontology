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

**Where things stand (2026-09-17, night).** Measured: **CQ 49 / 49** — every
in-scope competency question passes; 24 declared out of scope with the
reason on each. ELK 0 unsatisfiable, closure 34,856 triples, 168 external
terms all labelled, unit suite 1009 passed. Nothing on this list needs
Protégé right now.

Next free WONT id: **WONT_0000591**; next free MILD id: **MILD_120101**.
Mint in the `WONT_` / `MILD_` prefix — never `WOND_`. (Protégé:
Preferences → New entities → set the prefix and the 7-digit counter once.)

---

## 1. Open

| # | what | why |
|---|---|---|
| 1.1 | **`Wound pain` is an alt term of WONT_0000415 `degree of wound pain`** — decide whether to move it. The class is a *quality*, defined as "the extent of the pain that patient feels"; wound pain is the pain, its degree is a determinate quality of it (rule 31). Either the alt term belongs on a `Wound pain` class that does not exist yet, or the class's definition is broader than its label. 4 store mentions ride on it. | found 2026-09-23 while reviewing which mapping canonicals are alt terms rather than labels |
| 1.2 | **Seventeen `… process` alt terms sit on imported classes** — `Angiogenesis process` on GO's `angiogenesis`, `Hemostasis process` on `hemostasis`, `Proliferation process` on `cell population proliferation`, and so on. Nothing is wrong with them, but they make your ruling ("the ontology's own label wins") point at GO's spelling for 211 + 96 + 91 + 28 + 26 mentions, against WONT's own `… process` convention. One policy call; see §0 of `data/review/MAPPING_REVIEW.md`. | same review |
| 1.3 | **Missing wound axioms**: damaged structure and depth, "at least a skin defect", region, duration, cause, treatment, and the WONT–OFL bridge, with FMA seeds looked up in `fma_obo.owl`. Seven decisions (D1–D7) first. See `WONT_AXIOM_TODO.md`. | your ask, 2026-10-11: "FMA_OBO has to be reused heavily" |

Nothing else. The rest comes from the ROADMAP (P4 derived rebuild, P5 HermiT,
P6 BioPortal), not from the CQs.

## 2. Standing notes

| # | what |
|---|---|
| 2.1 | Every class under a plan specification carries "plan specification" in its name (decision 17 Sep); the previous label stays as an alt term. |
| 2.2 | Definitions written in review are first drafts in the house pattern. Never on a foreign class (rule 34, refined 17 Sep). |
| 2.3 | Modules are build outputs; if Protégé asks to save one, say no. |

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
| 2026-09-17 | **Night.** 31 classes under plan specification renamed "… plan specification" (old labels as alt terms; `Method used for X` → `X plan specification`); `Hypertrophic scarring process` folded into `Excessive collagen deposition process` (older IRI 154 kept, alt term, now ⊑ `Scarring process`), `Hypertrophic scar output_of` it; `Inflammation process` (590) minted, `Inflammatory phase is_about` it; `Diabetic foot ulcer ≡ Diabetic wound ⊓ located_in some Foot` (FMA_9664, module rebuilt), checker gained `located_in`; CQ020/021/024 retired. Two renamed labels whitelisted. **CQ 48/52 → 49/49.** |
| 2026-10-11 | Item 1.3 added: `WONT_AXIOM_TODO.md` (missing wound axioms, FMA seeds, OFL bridge). |
