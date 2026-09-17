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

**Where things stand (2026-09-16, evening).** Three rounds of hand edits
are in and reviewed. Since the morning: `Malignant wound`, `Traumatic wound`,
`Diabetic wound`, `Angiopathic wound` and `Autoimmune disease related wound`
are defined through their wound-causing process; the CDC surgical classes and
the IWII bioburden continuum are two separate axes, each with its scale, grade
individuals and wound classes; `Neoplastic wound` is gone. Review completed
the split (CDC `Clean wound` is a surgical-field class and no longer `≡ Wound ⊓
sterile`; `sterile` defines the IWII clean wound; the IWII hub's union now has
all four grades), renumbered 20 `WOND_1200xx` IRIs to `WONT_0000514–533`,
restored the parent `Autoimmune disease related wound` had lost, removed the
direct `fma.owl` import, fixed typos, wrote definitions. MILD now imports
`fma_module`. Nine CQs rewritten. Measured: **CQ 15 → 21 / 65**, ELK 0
unsatisfiable, closure 34,275 triples, roots beside `entity`: `disease`,
`unit`. Unit suite 1005 passed.

Next free WONT id: **WONT_0000534**. Mint in the `WONT_` prefix, main
series — never `WOND_`, never the `1200xx` band.

---

## 1. Modelling decisions — yours, not mechanical

| # | what | where | my recommendation |
|---|---|---|---|
| 1.1 | **`degree of malignancy` / `benign` / `malignant` (489–491) are now orphans.** `Malignant wound` is defined through `Wound causing malignant process`; nothing uses the three qualities. | WONT_0000489–491 | delete them, or keep `malignant` with a note saying it is reserved for the tumour, not the wound |
| 1.2 | **Aetiology through process mereology.** The five wound classes are now `≡ Wound ⊓ output_of some (Wound development process ⊓ has_part some <X disease process>)`. That is process-part, not causation, so it does not break MILD commitment 4 — but the three that used to be *co-location* classes (diabetic, angiopathic, autoimmune) have lost that reading: `Diabetic wound` no longer says it shares a material disease entity with a `Diabetic metabolic disorder`. Nothing is wrong; it is a change of commitment worth an `IAO_0000116` on each of the three saying why. | WONT_0000015, 0000033, 0000088 | write the note; consider keeping the co-location axiom *beside* the process one — they are independent claims |
| 1.3 | **`Pressure ulcer` has no WONT class.** CQ002 resolves to HP_0012399 (a phenotype) and fails. Your new pattern gives the shape directly: `Pressure ulcer ≡ Wound ⊓ output_of some Wound causing pressure impact process` (WONT_0000245), the way `Thermal wound ⊑ output_of some Wound causing heat impact process`. | new class | mint it (WONT_0000534) |
| 1.4 | **`Wound causing process ⊑ has_participant some FMA_62955 Anatomical entity`** — true of nearly every process; it says nothing. If the intent was "acts on the patient's tissue", `FMA_67135 Anatomical structure` is tighter; if it was "has the wound as participant", the definition already says that. | WONT_0000418 | narrow or drop |
| 1.5 | **`Diabetes mellitus type II disease process`** (520) is the only *type-specific* disease process in the file, and `Diabetic wound` is defined over it — so a wound in a type I diabetic is not a `Diabetic wound`. | WONT_0000520, 0000088 | rename to `Diabetes mellitus disease process`, or add type I and define over the parent |

## 2. Small things

| # | what |
|---|---|
| 2.1 | Definitions written in review are first drafts in the house pattern: the 36 of 12 Sep, 3 of 16 Sep (morning), and 17 of 16 Sep (evening: the ten process classes, the CDC/IWII hubs, scale and grades). The CDC grade wordings follow the CDC/NHSN surgical wound classification; the process ones are mine. |
| 2.2 | **Two roots still sit beside `entity` in the import closure**: `disease` (DOID_4) and `unit` (UO_0000000). Everything WONT and MILD use is under BFO except these two subtrees, because neither DOID nor UO places its root under BFO and the modules only carry what the sources say. Three options, one per line in MILD's import block or header: (a) `UO_0000000 ⊑ IAO_0000003 measurement unit label` — the OBI way of placing a unit under information content entity; (b) for DOID nothing — WONT deliberately links DOID terms by `skos:relatedMatch`, never subsumption, because a DOID disease is a nosological category, not the material disorder; so `DOID_4` staying outside BFO is *correct*, and should be said in an `rdfs:comment` on the MILD header rather than left to look like an oversight; (c) leave both and say nothing — the one option that is not defensible, because the next reader will re-find them. |
| 2.3 | `MILD_120028 skos:relatedMatch OGMS_0000063` is asserted in **WONT** about a **MILD** class. Harmless, but it belongs in MILD. |

---

## Log

| date | what |
|---|---|
| 2026-09-10 | File created: A (chronic axiom), B (3 MILD parents), C (orphan patch — withdrawn), D, E (determinate-quality block), F (import closure). |
| 2026-09-12 | A, E (mostly) and F2 applied by hand and reviewed; B closed as never missing. Details in ROADMAP changelog. |
| 2026-09-14 | Rewritten to hold only what is open. Previous full text in git history (`8896bf9`). |
| 2026-09-16 | Second hand edit reviewed; `fma_module` built; `located_in` allowed; chronic branch withdrawn on your ruling. |
| 2026-09-16 | Third hand edit reviewed (aetiology via process, CDC/IWII split, `Neoplastic wound` dropped). Closed: old 1.1, 1.3, 1.4, 1.5, 2.1, 2.3, 2.5, 2.6, 2.7. Your rulings recorded: grades stay individuals (old 1.2) — pipeline fixed instead (`ontology_labels()` skips individuals, includes alt terms; old 2.7); Jackson source fine (old 2.3). CQ001/002/006/010/011/012/033/091/110 rewritten; checker taught `output_of` and intersection fillers. |
