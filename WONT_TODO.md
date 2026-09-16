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

**Where things stand (2026-09-16).** The determinate-quality block (former
sections A and E) and the module clean-up (F2) were applied and reviewed on
2026-09-12; CQ score 6 → **15 of 65**, ELK over the skeleton 0 unsatisfiable.
The full history of that work is in `git log` (`24fcefe`, `51fce97`) and the
ROADMAP changelog; the reasoning that led to it — the PATO false friends, the
"determinate belongs to the class it defines" rule — is INSTRUCTIONS rules 31
and 34. The second round of hand edits
(2026-09-16: `colonized` back, co-location axiom on the arterial class,
`Large wound` over `increased area`, edge determinables moved to `Wound edge`,
the old burn grades I–IV dropped) was reviewed the same day; `FMA_7163 Skin`
now has its BFO path through a new `fma_module`. Closure 34,182 triples, roots
beside `entity`: `disease`, `unit`. CQ still 15 / 65, ELK 0 unsatisfiable.
This file holds only what is **still open**.

Next free WONT id: **WONT_0000514** (`extend.next_free_id` — never mint in
the `WOND_` prefix or the `1200xx` band).

---

## 1. Modelling decisions — yours, not mechanical

| # | what | where | my recommendation |
|---|---|---|---|
| 1.1 | **`Malignant wound` (WONT_0000182) carries `has_quality some malignant` *inside* its equivalence, beside the causal-history conjunct** (output of a disorder development process with a malignancy participant). Two definitions in one; and `benign` (490) defines nothing. | WONT_0000182, 489–491 | drop one conjunct — the quality reading matches the siblings, the process reading is the more careful one; not both |
| 1.2 | **Classification grades as individuals.** The 38 pre-existing grade individuals plus the 8 Jackson / Hildanus–Derganc ones. Defensible, but `Orchestrator.ontology_labels()` indexes every `rdfs:label` with no class/individual filter, so grade labels act as SapBERT anchors as though they were classes. | 6 grade classes | decide once; the pipeline-side filter follows |
| 1.3 | **Two unrelated "contaminated"s.** `Contaminated wound` (78) and `Clean contaminated wound` (67) are the **CDC surgical wound classes** (clean / clean-contaminated / contaminated / dirty — the operative field: was a viscus entered, was there spillage), already present as grade individuals `WONT_120081–84`. The IWII bioburden continuum (sterile → contaminated → colonized → infected) is a different axis. Both now sit under the `Wound with recognized microbial burden` hub with `has_quality some contaminated`: a clean-contaminated colectomy wound is not "contaminated" in the IWII sense. | WONT_0000067, 0000078, 0000481 | keep 78 as the IWII class (it is now defined that way) and move 67 out of the hub — it belongs with the CDC grades, or goes |
| 1.4 | **CQ001 / CQ002 / CQ006 are wrong questions.** They ask `Diabetic Foot Ulcer / pressure ulcer / Venous Leg Ulcer is_a Chronic Wound`. Your ruling (2026-09-16): **no wound class is chronic by definition — every wound starts acute**, so `Chronic wound` correctly has zero subclasses and nothing may be asserted under it. The three CQs need rewriting in `config/competency_questions.json` (e.g. to the co-location or `has_quality` facts that *are* true of the class), as a recorded decision. `data/review/chronic_decision_sheet.csv` is retired. | CQ file | rewrite; do not touch WONT |
| 1.5 | **CQ091 / CQ093** pass today only because `Malignant wound` and `Infected wound` carry `has_quality` conjuncts beside their process readings. If 1.1 drops the quality conjunct on 182, rewrite CQ091 to the process triple rather than letting it fail silently. | CQ file | tie to 1.1 |

## 2. Small things

| # | what |
|---|---|
| 2.1 | **Add `owl:imports <http://purl.obolibrary.org/obo/wond/modules/fma_module.owl>` to the MILD header** (one line in `Disease proposal 2.ttl`, beside the other twelve). The module exists and both catalogs point at it; the pipeline reads it already (it globs `*_module.owl`), but Protégé and the merged MILD will not see it until MILD imports it. |
| 2.2 | Definitions I wrote for the new classes (36 on 12 Sep, 3 on 16 Sep) are first drafts in the house pattern — the clinical thresholds (e.g. "confined to the epidermis" for first-degree) are mine, not sourced. |
| 2.3 | `Jackson burn wound zone classification` (493) carries a `dcterms:source` I added (Jackson 1953, Br J Surg) — verify. |
| 2.4 | `unit` (UO_0000000) and `disease` (DOID_4) are the two roots left beside `entity`. `IAO_0000003 measurement unit label` is where OBI-style modelling puts units; DOID is bridged by `skos:relatedMatch` on purpose (subsumption would be a category error). Either bridge them in MILD's import block or record in a `rdfs:comment` on the MILD header that they are unbridged by design — either is defensible, silence is not. |
| 2.5 | CQ010 / CQ012 ask for `Large` / `Deep`; the ontology has PATO's `increased area` / `increased depth`. Fix in `config/competency_questions.json`, not WONT. |
| 2.6 | CQ011 `Full-thickness wound` / `full-thickness` and CQ110 `Healed wound` — not minted (`Epithelialized wound` 506 stands in for the latter). Either add `Healed wound` as an alt term on 506 and rewrite CQ011, or mint. |
| 2.7 | `ontology_labels()` indexes `rdfs:label` only, so `2nd degree burn` (alt term on 483) dropped out of the naming guard's index. Pipeline-side; noted in ROADMAP. |

---

## Log

| date | what |
|---|---|
| 2026-09-10 | File created: A (chronic axiom), B (3 MILD parents), C (orphan patch — withdrawn), D, E (determinate-quality block), F (import closure). |
| 2026-09-12 | A, E (mostly) and F2 applied by hand and reviewed; B closed as never missing. Details in ROADMAP changelog. |
| 2026-09-14 | Rewritten to hold only what is open. Previous full text in git history (`8896bf9`). |
| 2026-09-16 | Second hand edit reviewed: 3 new entities renumbered `WOND_1200xx` → `WONT_0000511–513`; the venous class's defining axiom restored (it had been cut, not copied, when the arterial one was written); `Wound co-located with impaired arterial inflow ⊑ Peripheral arterial occlusive disease` removed (a wound is not a disease); the four wound-*base* determinables moved from `Wound` to `Wound base`, matching your move of the edge ones; `colonized` added to the hub's union (a colonized wound was required to be contaminated-or-infected); direct `owl:imports pato.owl` removed again. `fma_module` built (MIREOT path Skin → Anatomical entity, grounded under BFO_0000040). `located_in` (RO_0001025) entered the extraction schema because Skin now has a BFO category — added to `ALLOWED_PREDICATES`. **1.11 (populate the chronic branch) withdrawn** on your ruling. Closed: old 1.1, 1.3–1.9, 2.3. |
