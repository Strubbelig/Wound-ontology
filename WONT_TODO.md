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

**Where things stand (2026-09-14).** The determinate-quality block (former
sections A and E) and the module clean-up (F2) were applied and reviewed on
2026-09-12; CQ score 6 → **15 of 65**, ELK over the skeleton 0 unsatisfiable.
The full history of that work is in `git log` (`24fcefe`, `51fce97`) and the
ROADMAP changelog; the reasoning that led to it — the PATO false friends, the
"determinate belongs to the class it defines" rule — is INSTRUCTIONS rules 31
and 34. This file now holds only what is **still open**.

Next free WONT id: **WONT_0000511** (`extend.next_free_id` — never mint in
the `WOND_` prefix or the `1200xx` band).

---

## 1. Modelling decisions — yours, not mechanical

| # | what | where | my recommendation |
|---|---|---|---|
| 1.1 | **`Infected wound` (WONT_0000163) lost its `owl:equivalentClass`.** It was `Wound ⊓ participates_in some Wound infection process`; it is now a primitive subclass of the microbial-burden hub with two necessary conditions (`participates_in some 410`, `has_quality some infected`). Nothing can be *inferred* an infected wound any more. | WONT_0000163 | restore the equivalence — `≡ Wound ⊓ has_quality some infected` is the shape of its siblings, and keep `participates_in` as a necessary condition |
| 1.2 | **`infected` was minted as a determinate (WONT_0000480)**, against the earlier advice that infection is participation in a process, not a quality. Defensible — the clinical continuum sterile → contaminated → colonized → infected *is* one scale — but it is a decision, so record it in an `IAO_0000116` on 480 (there is a placeholder note there now). | WONT_0000480 | keep, and write the note |
| 1.3 | **`colonized` / `Colonized wound` (WONT_0000075) deleted**, so the continuum has a hole between contaminated and infected. | — | mint `colonized` under 478 and restore the class as `≡ Wound ⊓ has_quality some colonized` (next free id: WONT_0000511) |
| 1.4 | **`Wound co-located with impaired arterial inflow` (WONT_0000510) has no co-location axiom** — it is a bare subclass of `Wound`, so `Ischemic wound ≡ 510 ⊓ ischemic` says nothing about arteries. The venous twin `WONT_0000384` shows the shape; the natural target is `WONT_0000229 Peripheral arterial occlusive disease`. This also unblocks CQ033 once P3 lands. | WONT_0000510 | copy the 384 axiom with 229 as the co-located disorder |
| 1.5 | **`Wound dressing process` (WONT_120013) has a dangling definition**: "…has as specified output a wound covered by wound dressing", but that class (WONT_120014) was deleted and the `OBI_0000299` restriction with it. | WONT_120013 | either rewrite the definition to what the axioms now say, or restore 120014 |
| 1.6 | **Six wound-edge / wound-base determinables are asserted of `Wound` itself**: `degree of maceration` (434), `skin adherence` (451), `granulation` (452), `necrosis` (453), `fibrin coverage` (454), `epithelialization` (455) are defined as qualities *of a wound edge / wound base*, and `Wound ⊑ has_quality some <each>` now says every wound bears them directly. The bearer is the edge or base, not the wound. | WONT_0000380 | remove the six; keep `size`, `closure`, `depth`, `degree of time after disease inception`, `degree of microbial burden` (those *are* wound qualities) |
| 1.7 | **`increased depth ⊑ increased size` in PATO**, so every `Deep wound` is inferred a `Large wound`. Probably not what you mean by "large". | WONT_0000507/508 | accept it, or define `Large wound` over `increased area` (**PATO_0002057**, a determinate of `area` PATO_0001323 — measured against full PATO; it is not in the module yet, so it would need the rebuild) instead of `increased size` |
| 1.8 | **Two burn-grade sets now overlap**: the Hildanus/Derganc individuals (499–503: Superficial, Superficial partial-thickness, Deep partial-thickness, Full-thickness, Partial-thickness) and the pre-existing `Burn classification grade I–IV` (WONT_0000052–56) describe the same grades. And 503 `Partial-thickness` is the *union* of 500 and 501 — an individual that is two other individuals. | WONT_0000052–56, 499–503 | merge: keep one set, make the other's labels alt terms; drop 503 or make it a class |
| 1.9 | **`Burn classification grade` (WONT_0000437) now has two subclasses** (492 Jackson zone, 495 Hildanus/Derganc grade) *and* four direct individuals (52–56) that belong to neither. | WONT_0000437 | once 1.8 is settled, retype 52–56 under 495 |
| 1.10 | **`degree of malignancy` / `benign` / `malignant` (489–491)**: `Malignant wound` now carries `has_quality some malignant` *inside* its equivalence, beside the causal-history conjunct. Redundant with the process reading, and `benign` has no class to define. Also record the PATO_0002097 near-miss (done in a `rdfs:comment` on 491). | WONT_0000182, 489–491 | either drop the `has_quality` conjunct or drop the causal-history one; not both |
| 1.11 | **The chronic branch is still empty** (detail in 1.11 below). `Chronic wound` has zero subclasses; the four YES rows in `data/review/chronic_decision_sheet.csv` (`Ulcus cruris venosum`, `Ulcus cruris mixtum`, `Ulcus hypertonicus Martorell`, `Arterial leg ulcer`) are not asserted. CQ001/002/006 wait on this. | WONT_0000442 | assert the four `rdfs:subClassOf wont:WONT_0000442`; decide the three CHECK rows |

### 1.11 in full — the chronic branch

**Only `Chronic wound` bears `chronic` directly.** Any other chronic class is
chronic *by being a subclass of it* and inherits the quality through the
defining axiom, so the one thing to assert is the subsumption, never
`X has_quality some chronic` beside it.

The test is stricter than "typically chronic": *is **every** instance of X a
wound that has failed to progress?* Sheet with a proposal per row:
`data/review/chronic_decision_sheet.csv` — 4 proposed YES, 3 CHECK, 32 NO, 1 n/a.

| proposal | classes |
|---|---|
| **YES** | `Ulcus Cruris Venosum`, `Ulcus Cruris Mixtum`, `Ulcus Hypertonicus Martorell`, `Arterial Leg Ulcer` |
| **CHECK** | `Marjolin Ulcer`, `Malignant Wound`, `Neoplastic Wound` — non-healing, but primarily malignancies; and decide first whether the latter two are distinct classes at all |
| **NO** (was YES on the earlier, looser reading) | `Diabetic Wound`, `Angiopathic Wound`, `Autoimmune Disease Related Wound`, `Wound Co-Located With Impaired Venous Backflow` — each admits non-chronic instances, so the class is not subsumed even though its typical member is chronic |

Note `Ulcus Cruris Venosum` would then have three parents (`Skin wound`,
`Wound co-located with impaired venous backflow`, `Chronic wound`). That is fine
— they are independent axes — but worth seeing before asserting.

### 1.12 — should the classification grades be individuals?

They are `owl:NamedIndividual`s (38 pre-existing across 6 grade classes, plus
the 8 new Jackson / Hildanus–Derganc ones). Defensible — a grade is arguably an
instance of a grading scheme — but it has a pipeline consequence:
`Orchestrator.ontology_labels()` indexes every `rdfs:label` with no
class/individual filter, so grade labels act as SapBERT mapping anchors as
though they were classes. Decide the modelling question first (it interacts
with 1.8 and 1.9); the pipeline-side filter follows.

### 1.13 — CQ091 and CQ093 are wrong, not the ontology

`Infected wound` and `Malignant wound` were defined through a process
(participation in a wound infection process; output of a disorder development
process with a malignancy participant), and CQ093 / CQ091 ask for
`has_quality Infected` / `has_quality Malignant`. Your edit added the
`has_quality` reading beside the process one, so both CQs pass now — but see
1.1 and 1.10: if you drop the `has_quality` conjuncts again, the honest move is
to **rewrite the two questions** in `config/competency_questions.json` to the
triples the ontology asserts, as a written-down decision. Rewriting a CQ to fit
the artefact silently is how a CQ suite stops meaning anything.

---

## 2. Small things

| # | what |
|---|---|
| 2.1 | Definitions I wrote for the 36 new classes are first drafts in the house pattern — read them; the clinical thresholds (e.g. "confined to the epidermis" for first-degree) are mine, not sourced. |
| 2.2 | `Jackson burn wound zone classification` (493) carries a `dcterms:source` I added (Jackson 1953, Br J Surg) — verify. |
| 2.3 | `FMA_7163 Skin` is stubbed in WONT with no parent — one of the three remaining roots beside `entity`. Give it `rdfs:subClassOf ns1:BFO_0000040` or a UBERON path. |
| 2.4 | `unit` (UO_0000000) and `disease` (DOID_4) are the other two roots beside `entity`. `IAO_0000003 measurement unit label` is where OBI-style modelling puts units; DOID is bridged by `skos:relatedMatch` on purpose (category error otherwise). Either bridge them in MILD's import block or record in a `rdfs:comment` on the MILD header that they are unbridged by design — either is defensible, silence is not. |
| 2.5 | CQ010 / CQ012 ask for `Large` / `Deep`; the ontology has PATO's `increased size` / `increased depth`. Fix in `config/competency_questions.json`, not WONT. |
| 2.6 | CQ011 `Full-thickness wound` / `full-thickness` and CQ110 `Healed wound` — you chose not to mint them (`Epithelialized wound` 506 stands in for the latter). Either add `Healed wound` as an alt term on 506 and rewrite CQ011, or mint. |
| 2.7 | `ontology_labels()` indexes `rdfs:label` only, so `2nd degree burn` (now an alt term on 483) dropped out of the naming guard's index. Pipeline-side; noted in ROADMAP. |

---

## Log

| date | what |
|---|---|
| 2026-09-10 | File created: A (chronic axiom), B (3 MILD parents), C (orphan patch — withdrawn), D, E (determinate-quality block), F (import closure). |
| 2026-09-12 | A, E (mostly) and F2 applied by hand and reviewed; B closed as never missing. Details in ROADMAP changelog. |
| 2026-09-14 | Rewritten to hold only what is open: 13 modelling decisions, 7 small items. Everything done or withdrawn removed; the previous full text is in git history (`8896bf9`). |
