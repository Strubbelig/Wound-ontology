# Roadmap to the thesis build

**Target.** Thesis writing starts **end of October 2026** — seven weeks from
2026-09-10 — on the extended wound ontology, with three gates closed:

1. **HermiT approves** the full merge.
2. **The ontology is on BioPortal.**
3. **The competency questions are all green.**

This file is updated every time one of the measured numbers below moves. It is
the living companion to `WONT_TODO.md` (hand edits to the curated files) and
`INSTRUCTIONS.md` (standing design rules).

---

## Priority — decided 2026-09-10

**The ontology is the deliverable. The pipeline is how it grows.**

A hand-curated class that satisfies a competency question is a legitimate
answer, not a workaround. What the pipeline is for is *growth*: more leaves,
placed under the right parent, carrying the right axioms. Those are two
different jobs and they are measured separately (next section) rather than
being made to compete for one number.

This is not a compromise position. It is how OBO ontologies are actually built:
a curator authors the upper and mid-level structure and the defining axioms,
and automated extraction populates beneath it. The curated layer is not
scaffolding to be removed — it is the part that makes everything below it
meaningful.

**And the two reinforce each other.** Every curated class is also a **mapping
anchor**: SapBERT maps extracted terms onto curated labels, so a class hand-authored
today is a landing site for every future extraction that means the same thing.
Curation raises pipeline yield. It does not spend it.

---

## Measured state

Every figure measured, never estimated (rule 15). Add a column per revision so
the trend is visible rather than asserted.

| | 2026-09-10 | 2026-09-11 | 2026-09-12 |
|---|---|---|---|
| corpus | **142 abstracts extracted** of 606 fetched — 464 unextracted, extraction started 2026-09-10 | **606 of 606 extracted** (2026-09-11 21:01) — **12,901 entities** (3.6x); 5,425 more fetched at cap 200, extraction gated on E | unchanged |
| distinct store entities | 3536 | **12,901** | unchanged |
| **CQ in-scope score** (full closure) | 6 / 65 | 6 / 65 | **15 / 65** — A + E applied by hand; checker now sees defining axioms |
| import closure (WONT + MILD + modules) | 220,252 triples, 6,169 classes, 29 foreign roots | same | **34,071 triples, 1,174 classes, 3 foreign roots** (`disease`, `unit`, `Skin`) |
| `obi_module.owl` | 16.3 MB | same | **1.0 MB** |
| WONT classes | 343 own | same | **379** (36 minted, 6 deleted) |
| class-hierarchy edges (with provenance) | 4011 — **3552 `text`**, 459 `curated` |
| entities placed under a curated WONT/MILD class | **2811 (80%)** |
| entities parked at an upper-level root | 684 (19%) |
| curated labels available as anchors (WONT + MILD, incl. alt terms) | 600 |
| **CQ in-scope score** | **6 / 65 (9%)** |
| CQ FAIL (class exists, axiom does not) | 18 |
| CQ UNRESOLVED (class does not exist) | 41 |
| CQ DECLARED (out of scope, not counted) | 8 |
| `wont_extended.ttl` | 8 Sep 14:43 — **stale**, predates the current store |
| HermiT full-merge verdict | **unknown** — deferred to P5 by decision, 2026-09-10 |
| BioPortal | WONT IRIs are already `bioportal.bioontology.org/ontologies/WONT` — submission currency **to verify** |
| working tree | uncommitted since `9553d20` |

---

## Two measures, not one

The CQ score and the pipeline's contribution are different questions, and
conflating them is what made the old plan point the wrong way.

**The CQ score measures the ontology.** It asks whether the artefact can answer
the questions it was scoped to answer. It does not care who authored a class,
and the thesis does not have to pretend it does — provenance is recorded per
edge (`text` / `curated`), so the method chapter can state exactly which is
which.

**The pipeline's contribution is its own headline number**, tracked as a trend:

| what | 2026-09-10 |
|---|---|
| edges the pipeline proposed (`text`) | **3552 of 4011 (89%)** |
| entities it placed under a curated class | **2811 of 3536 (80%)** |
| entities left parked at an upper-level root | 684 (19%) |

That last row is the one to drive down, and it is not evenly spread. All 684
hang under just **9 upper-level roots**:

| root | entities |
|---|---|
| Information Entity | 514 |
| Immaterial Entity | 61 |
| Continuant | 44 |
| Process Boundary | 32 |
| Occurrent | 15 |
| Function | 11 |
| Realizable Entity | 3 |
| Specifically Dependent Continuant | 2 |
| Independent Continuant | 2 |

Reading the contents changes what the number means. The 514 under `Information
Entity` are mostly study-methodology vocabulary the corpus is full of — *Before
After Design*, *Noninferiority Margin*, *Cinahl Ebsco*, *Population Based
Surveys*. Those belong at the top of the tree; they are not misplaced and no
curation will move them.

The other **170 are different**, and are the real pool: *Chronic
Limb-Threatening Ischemia*, *Surgical Site Infection*, *Bacterial Load*,
*Complete Wound Closure*, *Suture Removal*, *Inflammatory Phases*, *Healed*,
*Antibacterial Functionality*. Wound-domain content parked at a BFO root
because nothing more specific existed to attach it to. **Each mid-level class
curated in the right place converts some of these into properly placed
leaves** — which is the mechanism by which P1 and P2 below raise the pipeline's
own number.

---

## Where the CQ gap actually is

The 41 UNRESOLVED CQs name **51 distinct concepts** with no class. Measured
against the concept store:

- **4** are label-index misses — present under a different spelling
  (`Acute Wound`/`Acute Wounds`, `Ankle-Brachial Index`/`Ankle Brachial Index`,
  `Non-Healing Wound`/`Non Healing Wounds`, `Subcutaneous Tissue`/`Subcutaneous
  Tissues`).
- **2** are present but unreachable through `fold()`: `Inflammatory Phases` and
  `Proliferative Phases` fold to `inflammatory phas` / `proliferative phas`.
  Both sit in the store today, parked under `Process Boundary`.
- **45** are absent from the store as well — never extracted, because 142
  abstracts never mentioned them. `Sepsis`, `Laceration`, `Osteomyelitis`,
  `Fascia` and `Vancomycin` are ordinary wound-care vocabulary; their absence
  is a statement about the corpus, not about the extractor.

**Of the 65 in-scope CQs, 18 sit on one pattern** — a wound subclass defined by
the determinate quality that makes it that subclass:

| predicate | CQs | unblocked by |
|---|---|---|
| `has_quality` | 13 | the determinate-quality block (P1) — 11 by axiom, 2 by correcting the question |
| `is_a … Chronic Wound` | 3 | populating the chronic branch (`WONT_TODO` 1.11) |
| `co_located_with` | 1 | class from P1 **+** `RelationType` extension (P3) |
| `is_treatment_for` | 1 | class from P1 **+** `RelationType` extension (P3) |

That is why P1 is first: it is 10 axioms of a shape WONT already carries ten
times, and it moves 16 CQs on its own.

---

## Pipeline run order — and what a WONT edit destroys

Traced through `orchestrator.py` against the notebook's canonical order. The
question this answers: **if WONT changes, is the current pipeline data trash?**

**No — but only two steps are safe, and they happen to be the expensive ones.**

| # | step | reads | writes | cost | re-run when… |
|---|---|---|---|---|---|
| 1 | `run_pubmed_search` | PubMed + `pubmed_query_list.py` | abstract database | network | **never** — purely additive |
| 2 | `run_validate_pubmed_queries` | the query list | report | small LLM | a query is added |
| 3 | **`run_extract_to_store`** | abstracts + `extraction_schema.yaml` — a **generated snapshot** of WONT + MILD (`scripts/build_extraction_schema.py`) | `concept_store_*.json` | **LLM per abstract — the expensive one** | **never** for the store; the schema **regenerates itself** at the start of this step when WONT, MILD or a module is newer (rule 32) |
| 4 | `run_build_term_mapping` | store terms **+ `ontology_labels()`** | `term_mapping_*.json` | SapBERT + LLM adjudication *(cached)* | **corpus or WONT** |
| 5 | `review_mapping`, `check_term_mapping` | the mapping | curated mapping | **manual** | corpus or WONT |
| 6 | `run_apply_mapping` | the mapping | **the store, in place** — renames recorded under `decisions.renamed` | cheap | corpus or WONT |
| 7 | `review_lists`, `cluster_blocklist`, `run_promote_clusters` | store + the lists | `config/blocklist.py`, `config/whitelist.py` | manual + SapBERT | corpus |
| 8 | `run_clean_store` | store + lists | store — **verdicts** (`blocklist`, `predicate_filter`, `prune`), nothing deleted; its own earlier verdicts lifted first | cheap | corpus, or a list changed |
| 8b | **`build_reasoner_skeleton`** | **WONT + MILD** | `output/owl/skeleton_tbox.ttl` | ~1 min | **automatic** — rebuilt when WONT or MILD is newer than the cache (rule 32) |
| 9 | `run_gate_store_relations` | store + skeleton | store — **verdicts** by `reasoner_gate`, re-heard on every run; `output/quarantine/` kept as the batch log | ELK | corpus or WONT |
| 10 | `run_build_hierarchies` | store **+ curated seed from WONT + MILD** + accepted FCA slices | `class_hierarchy_*.csv` + provenance, `mereological_hierarchy_*.csv` | cheap | corpus or WONT |
| 11 | `run_gate_hierarchy_edges` | class hierarchy + skeleton | hierarchy + quarantine | ELK | corpus or WONT |
| 12 | `run_store_fill` | store | store | **LLM per entity** | corpus |
| 13 | `run_fca` | class hierarchy | `context_matrix_*.csv`, `concept_lattice_*.pkl`, accepted slices | cheap + manual accept | corpus or WONT |
| 13b | `run_matrix_nan_fill` | context matrix | context matrix | **LLM per undecided cell** | corpus or WONT |
| 14 | `run_extend_ground_truth` | **WONT** + hierarchies + store | `output/owl/wont_extended.ttl` | cheap | corpus or WONT |
| 15 | `run_curate_owl`, `run_map_ontology`, `run_enrich_external` | extended OWL + import ontologies | extended OWL | LLM + SapBERT | corpus or WONT |
| 16 | `run_competency_check` | **WONT + MILD** + `competency_questions.json` | report | cheap | corpus or WONT |
| 17 | `run_deep_reason` | full merge | inferred OWL | **slow — HermiT** | corpus or WONT |

### What survives a WONT edit

- **The abstracts.** `run_pubmed_search` merges into one database; nothing
  invalidates it.
- **The concept store.** `run_extract_to_store` never opens
  `ground_truth_final.owl` at runtime. What it is prompted with is
  `config/extraction_schema.yaml`, generated from WONT + MILD by
  `scripts/build_extraction_schema.py` (last on 2026-09-08 from the 2026-09-04
  WONT). Three things come from that snapshot, and only one of them reaches
  the store:
  - the **category enum** (BFO/MILD upper categories) → stored as
    `is_a: <category>`. Section E does not change it.
  - the **relation enum** → stored as relations. E does not change it either
    (P3 will).
  - the **per-category lists of existing classes** offered as `grounded_to`
    targets → **not stored** (`result_to_store_entities` drops it). It is used
    by the per-batch reasoner gate, which checks a grounded term against its
    real axioms and an ungrounded one against a placeholder under its category.

  So an abstract extracted before E yields the **same store record** it would
  after E. What it loses is gate strength: `open wound` extracted today is an
  ungrounded new term checked against a placeholder; after E it would be
  recognised as `Open wound` and checked against its defining axiom. Step 4
  then maps the ungrounded term onto the class anyway — that is what the
  anchors are for. Nothing extracted before a curation edit is wasted.
- **The curated lists.** `blocklist.py` / `whitelist.py` are keyed on store
  terms, not on WONT.
- **The LLM adjudication cache** inside the term mapping — a rebuild re-asks
  only genuinely new anchor pairs, so rebuild *n* is far cheaper than rebuild 1.
- **Accepted FCA slices**, which are read from disk, not from the session.

### What a WONT edit invalidates

Steps 4, 6, 8b, 9, 10, 11, 13, 13b, 14, 16, 17 — the whole derived layer. It is
also the **cheap** layer: no step in it re-reads an abstract.

Two caveats that are not cheap:

1. **`run_apply_mapping` mutates the store in place** and title-cases it, so the
   extraction spelling is gone after the first apply. The mapping can be
   re-applied — `normalize()` folds both sides now — but the only route back to
   an earlier state is the dated snapshot in `data/cache/`.
2. **Every anchor mapping is an identity claim.** Absorbing a store term into a
   WONT class that section E is about to redefine means re-reviewing that
   decision, not just recomputing it. Step 5 is manual for a reason.

### Two snapshots of WONT, neither checked for staleness

`skeleton_tbox.ttl` (below) is one derived-from-WONT file the pipeline reused
without asking whether WONT had moved. `config/extraction_schema.yaml` is the
other, and it has no check either: generated 2026-09-08, WONT last edited
2026-09-04, so in sync today — and out of sync the moment E lands. The
consequence is quieter than the skeleton's: extraction still runs and the store
is still right, but the 14 new classes are simply not on offer as grounding
targets, so every mention of them goes through the gate as a placeholder.
Fixed 2026-09-12: `schema_builder.ensure_current()` runs first thing in
`run_extract_to_store` (rule 32). Measured on the way: a fresh build against
the 4 Sep WONT is **33 s** and differs from the 8 Sep file in one line, the
date — so the check touches an unchanged schema instead of rewriting it.

### The live defect this traced out

`build_reasoner_skeleton` reuses a cached `skeleton_tbox.ttl` whenever the file
exists, with **no staleness check against WONT**. Measured today:

| file | modified |
|---|---|
| `data/ground truth/ground_truth_final.owl` | **4 Sep 19:32** |
| `output/owl/skeleton_tbox.ttl` | **20 Aug 22:13** |

**The reasoner gate has been reasoning over a WONT that is fifteen days old.**
Both gates (steps 9 and 11) run against it. Nothing announced this. Fix in P0:
compare mtimes and rebuild, or refuse — a stale skeleton is exactly the silent
degradation the standing rule forbids.

### What this means for the order of work

Because steps 4–17 must re-run after **either** a corpus change or a WONT
change, running them repeatedly while both are still moving is wasted work.
The cheapest schedule is:

1. **Grow the corpus and extract** (steps 1–3) until coverage is where it needs
   to be. Additive, never invalidated, and independent of every curation
   decision — so this can start immediately and run all the way through.
2. **Make the WONT hand edits** (`WONT_TODO` — done 12 Sep; the residue is `WONT_TODO` §1) while extraction runs.
3. **Then run steps 4–17 once**, against the final store and the final WONT.

One refinement, decided 2026-09-11 when the cap-200 fetch turned up **5,659**
unextracted abstracts (~47 h at the measured rate): a run that long should go
through the strongest gate available. **Do E first, regenerate the extraction
schema, then start the big batch.** E is a day of hand curation; the store
would be identical either way, but every mention of the 14 new classes would
then be gate-checked against a real axiom instead of a placeholder. The 235 in
flight are small enough not to wait.

Run the derived chain in between only to *measure* — and treat those runs as
throwaway, because they are. The number they produce is real; the artefact they
produce is not the one being submitted.

---

## Critical path

Two lanes that only converge at the end, because they do not depend on each
other. **Curation** (P0–P3) is what closes the CQ gate. **Extraction** (PC) is
what the pipeline contributes, and it is the one thing that is never
invalidated by a curation decision — so it starts now and runs the whole way
through.

They meet at **P4**, the single derived rebuild.

---

### PC · Corpus and extraction — starts now, runs to 6 Oct · **lane B**

Steps 1–3 of the run order. The only steps that never have to be run twice:
abstracts merge into one database, and extraction is additive and does not read
WONT.

**Start by extracting what is already fetched.** Measured 2026-09-10 against
`data/cache/pubmed_abstracts_2026-08-24_17-39.csv`:

| | |
|---|---|
| rows in the abstract database | 860 |
| unique PMIDs | **606** |
| of those, already in the concept store | 142 |
| **already fetched, never extracted** | **464** (614 rows) |
| queries represented | 43 — all of them |
| unique PMIDs per query | **20 — min, median and max alike** |

Two things follow. First, **464 abstracts were sitting on disk unextracted**, so
the first batch of PC costs no PubMed calls at all and takes the corpus from 142
to 606 — a **4.3x** increase before a single new search. *Started 2026-09-10;
reached 371 PMIDs / 8,575 entities before the session that launched it ended
and took the process with it. Relaunched 2026-09-11 for the remaining 235.*

The runner now lives at `scripts/pc_extract.py` and logs to
`output/pc_extract.log` — not in a session scratchpad, which was wiped along
with the process. It is resumable by construction (the store is keyed by PMID),
so a killed run costs time only. Launch it detached:
`( nohup python -u scripts/pc_extract.py > output/pc_extract.log 2>&1 < /dev/null & )`.
`scripts/pc_fetch.py` is the cap-200 re-run of the query list, same pattern.

Second, every query returned *exactly* 20 PMIDs, so the search ran at
`max_results_per_query=20` — not the 200 the orchestrator defaults to, and not
the 1000 the connector allows. All 43 queries ran; each was capped at 20.
**Raising the cap and re-running the existing list is the lever, not writing new
queries** — the list already covers burns, osteomyelitis, healing phases,
scarring and vascular assessment, all of which are among the 45 absent
concepts. At a cap of 200 the same 43 queries are worth roughly 8600 rows.

- Targeted PubMed queries for the concepts the corpus is thin on.
  `config/pubmed_query_list.py` is the mechanism; `run_validate_pubmed_queries`
  is the validator, and it runs before the search, not after.
- `run_pubmed_search` → `run_extract_to_store` in batches.
- **Measure after every batch** and add a column to *Measured state*: entities,
  edges by provenance, placement rate. Placement rate against corpus size is
  the pipeline's recall curve — a thesis result in its own right, and one that
  does not depend on the CQ score at all.
- Measuring means running steps 4–17, which is fine. **Treat those runs as
  throwaway.** The number is real; the artefact is not the one being submitted.

**Exit:** a stated coverage figure — *n* of the 45 absent concepts recovered at
*m* abstracts — and, per remaining concept, a decision between another query
round and curating it by hand in P2.

---

### P0 · Land the tree, fix matching, fix the stale skeleton — 10–19 Sep

- Commit the working tree: folded pre-merge in `term_mapper`, competency
  provenance block, `TermList.match` normalisation, `dedupe`, FCA candidate
  persistence, prompt rule 31 + its 6 tests.
- **`build_reasoner_skeleton` reuses a stale skeleton with no check.**
  `skeleton_tbox.ttl` is 20 Aug; `ground_truth_final.owl` is 4 Sep. Both gates
  have been reasoning over a WONT fifteen days old, and nothing said so. Compare
  mtimes and rebuild, or refuse. This is a standing-rule violation, not a
  nice-to-have — and P1 makes it worse, because every WONT edit from here
  silently widens the gap.
- **`fold()` mis-singularises `-es` plurals.** The branch fires whenever the
  stem ends in `s/x/z/ch/sh`. Measured: **45 of 3536** store terms take it and
  **31 are wrong** across 12 head nouns (`responses→respons`, `nurses→nurs`,
  `cases→cas`, `phases→phas`, `orthoses→orthos`…); the other 14 are right
  (`processes→process`, `lenses→lens`). `buses→bus` and `phases→phase` cannot be
  told apart by suffix, so `singularize` must yield **candidates** and the
  lookup try each.
- **The CQ resolver has its own label index.** `competency.label_index()` builds
  a plain `{lower(label): iri}` dict and `_answerable` does `idx.get(...)` —
  exact match only. `utils.label_match.LabelIndex` already exists with a folded
  fallback. Rule 13 says one normalisation.
- ~~**`extraction_schema.yaml` has the same staleness hole the skeleton had.**~~
  Done 2026-09-12: `run_extract_to_store` calls `schema_builder.ensure_current()`
  first; it regenerates when WONT, MILD or a module is newer, touches rather
  than rewrites when only the date would change, and stops the process when the
  content changed (rule 32). "Regenerate the schema" is no longer a manual
  step anywhere.
- ~~Apply **`WONT_TODO` B**~~ — closed 2026-09-12 as not needed: the three
  parents were asserted all along, inside `rdfs:subClassOf` intersections.

**Exit:** the 4 label-miss CQs and the 2 phase CQs resolve, measured; the
skeleton is provably newer than WONT; full suite green; `git status` clean.

---

### P1 · The determinate-quality block — 12–26 Sep · **the big one**

> **2026-09-12 — applied by hand, reviewed, mostly done.** A1–A3 and E1–E5
> are in WONT (36 entities, `WONT_0000475`–`0000510`; see `WONT_TODO` for the
> deviations: no `colonized`, no `full-thickness`, `Epithelialized wound` in
> place of `Healed wound`, `infected` minted as a determinate, `degree of
> malignancy` added, `Infected wound` now primitive). F2 done on the way (the
> modules had to carry the PATO terms). Measured: CQ **6 → 15 / 65**; ELK over
> the skeleton 0 unsatisfiable. **Still open here:** A4 (chronic branch empty —
> CQ001/002/006), CQ010/012 (`Large`/`Deep` vs PATO's `increased size`/`depth`
> — question-file fix), CQ011 (`full-thickness`), CQ110 (`Healed wound`),
> the co-location axiom on `WONT_0000510`, and the burn-grade duplication
> (`WONT_0000052–56` beside the new Hildanus/Derganc individuals).

`WONT_TODO` **A** (chronic) and **E** (the other fourteen). One pattern:
`X ≡ Wound ⊓ has_quality some <determinate>`. Measured against WONT + MILD +
the import modules **and against the full PATO** (259 922 triples):

| to author | count |
|---|---|
| PATO determinates already there — **reuse, do not mint** | 4 — `open` PATO_0000610, `closed` PATO_0000608, `increased size` PATO_0000586, `increased depth` PATO_0001596 |
| PATO stubs to add to WONT's import block | 5 (the four above plus `closure` PATO_0000136) |
| WONT classes to mint | **14** — 2 determinables, 5 determinates, 7 wound classes |
| `equivalentClass` axioms to write | **10** |
| alt terms instead of new classes | 2 — `Chronic non-healing wound`, `Non-healing wound` on WONT_0000442 |

Checking PATO first removed four mintings and found two **false friends**:
`PATO_0000956 sterile` is a *fertility* quality (children `male sterile`,
`female sterile`) and `PATO_0001863 chronic` is a *duration quality of a
process*, so its bearer is an occurrent while `Wound` is a material entity.
Neither can be used. That check also confirms A2's decision to mint a WONT
`chronic` rather than import PATO's.

It also found that **two classes are already better defined than the CQs ask
for**: `Infected wound` is `Wound ⊓ participates_in some wound infection
process` and `Malignant wound` is defined through its causal history, while
CQ093 and CQ091 ask for `has_quality`. The ontology is right; those two
questions need rewriting, as a written-down decision in
`config/competency_questions.json` — not a WONT edit, and not something to do
quietly.

Then **A4** — populate the chronic branch, which today has zero subclasses.
Sheet at `data/review/chronic_decision_sheet.csv`.

**CQ yield:** 11 from E, 3 from A4 (CQ001, CQ002, CQ006) = **14 by curation**;
2 more (CQ091, CQ093) by the question-file decision; 2 more (CQ033, CQ050)
unblocked here but still waiting on P3.

**Exit:** 14 CQs move to PASS, measured by re-running `run_competency_check`;
HermiT clean on the edited WONT — ten new defining axioms on one parent is
exactly where a bearer mistake surfaces.

---

### P2 · Curate the remaining CQ classes — 26 Sep – 10 Oct

The residue of the 45 absent concepts, after P1 and after whatever the
continuous track has recovered. Each one authored the way P1's are: a real
parent, a real definition, a defining axiom where the class has one. A bare
`rdfs:label` that makes a CQ pass is not the deliverable.

Work in the order the CQs weight them, and record for each whether it was
curated or recovered by extraction — that split is a thesis figure.

**Exit:** every remaining UNRESOLVED CQ is either PASS or deliberately
`DECLARED` out of scope, with the reason written down.

---

### P3 · Extend `RelationType` — 29 Sep – 13 Oct

**Withdrawn 2026-09-17 (curator).** `is_treatment_for` is not needed: an agent *participates in* a treatment process and the wound participates in every wound treatment process — both relations already in `RelationType`. `co_located_with` was retired for the complication pattern (rule 35), `occurs_in` for `has_participant` (CQ100). No CQ tests a relation the extractor cannot produce any more; measured 2026-09-17: 48 / 53 PASS, the 5 open are FMA anatomy references. The table below is the state that motivated the item.

**9 of the 18 FAILs test relations the extractor structurally cannot produce:**

| predicate | FAILs | in `RelationType`? |
|---|---|---|
| `is_a` | 5 | yes |
| `is_treatment_for` | 5 | **no** |
| `co_located_with` | 2 | **no** |
| `occurs_in` | 2 | **no** |
| `part_of` | 2 | yes |
| `has_quality` | 2 | yes |

`is_treatment_for` and `occurs_in` are listed in `config/settings.py` under
"legacy stores only; no RelationType produces these"; `co_located_with` appears
only in the competency module. Until `RelationType` carries them with IRIs and
domain/range, those 9 cannot pass by any amount of corpus work or curation.

**Exit:** `RelationType` extended and gated; the 9 re-measured.

---

### P4 · The single derived rebuild — 10–14 Oct · **the lanes converge**

Steps 4–17 of the run order, once, against the final store and the final WONT.
Everything before this point was either additive (PC) or curation (P0–P3);
this is where they become one artefact.

Order matters and the dependency table is the order:

1. `build_reasoner_skeleton()` — first, because both gates read it (it rebuilds
   on its own when WONT or MILD is newer; `force=True` only if you distrust mtimes).
2. `run_build_term_mapping` → `review_mapping` → `run_apply_mapping`.
   **The review is manual and is the long pole of this phase**: section E
   redefines classes that store terms have already been absorbed into, so those
   adjudications need re-reading, not just recomputing.
3. `review_lists` → `run_clean_store`.
4. `run_gate_store_relations` → `run_build_hierarchies` →
   `run_gate_hierarchy_edges`.
5. `run_store_fill` → `run_fca` → `run_matrix_nan_fill`.
6. `run_extend_ground_truth` → `run_curate_owl` / `run_map_ontology` /
   `run_enrich_external`.
7. `run_competency_check`.

**Exit:** `wont_extended.ttl` newer than every cache it derives from; the CQ
score and the contribution figures measured on that one build; nothing in
`data/cache/` older than the WONT edit that preceded it.

---

### P5 · HermiT — 14–19 Oct

The per-batch gate uses ELK, which cannot express inverse properties,
cardinality or universal restrictions. `run_deep_reason` runs HermiT over the
full merge and is the gate that has to be clean.

**`run_deep_reason` does not work as written.** Measured 2026-09-10, before the
run was called off as premature — two independent blockers, both fixable, both
to be fixed *in* P5 and not before:

1. **It cannot read the input.** `OWLReasoner.load` uses
   `owlready2.get_ontology(...).load()`, which parses RDF/XML, OWL/XML and
   ntriples — not Turtle. `wont_extended.ttl` and `ground_truth_final.owl` are
   both Turtle. The merge has to be serialised to RDF/XML first, with
   `owl:imports` stripped and the closure inlined, because owlready2 resolves
   imports by filename and ignores `catalog-v001.xml`.
2. **The default heap is too small.** owlready2 launches HermiT at
   `-Xmx2000M`. On the 240 292-triple merge (9633 classes, 312 individuals)
   that dies with `java.lang.OutOfMemoryError: Java heap space` inside
   `QuasiOrderClassification`, after 168 s — and `world.inconsistent_classes()`
   then returns an empty list, so **the failure reads as a clean result.**
   Set `owlready2.reasoning.JAVA_MEMORY` explicitly, and treat an empty
   unsatisfiable set after a raised reasoner as unknown, never as zero.

The second one is a silent-failure defect in its own right: a crashed reasoner
that reports "0 unsatisfiable classes" is exactly the degradation the standing
rule forbids.

- Re-run after each WONT hand edit — the curated files are the usual source of
  a continuant/occurrent clash, and P1–P2 are all curated edits.

**"No unsatisfiable classes" is the wrong exit criterion, and the code already
says so.** `build_reasoner_skeleton`'s docstring records that *"the full import
closure carries 54 pre-existing unsatisfiable classes"* — which is why the gate
reasons over a stripped skeleton instead. Those 54 are not ours to fix and will
not disappear.

**Exit:** the full merge is **consistent**, and its unsatisfiable set is a
subset of the pre-existing import-closure set — measured, with the baseline
taken *before* P1. Any class WONT or MILD owns that turns up unsatisfiable is a
defect to fix, not to exclude.

---

### P6 · BioPortal — 20–26 Oct

- Verify what is currently published under
  `bioportal.bioontology.org/ontologies/WONT` and how it was submitted.
- Submit the P5 build with a version IRI, licence, and description.
- Confirm BioPortal's own parser accepts it — its validation is stricter than a
  local `rdflib` parse and will reject things HermiT tolerated.

**Exit:** the extended ontology resolves on BioPortal at a citable version.

---

### P7 · Freeze and measure — 27–31 Oct

- Final `run_competency_check` against the submitted build.
- Final figures: corpus size, entities, classes curated vs extracted, edges by
  provenance, placement rate, CQ score before/after, HermiT verdict, BioPortal
  version.
- Update the pipeline reference artifact (rule 17) so the method chapter has a
  current description to draw on.

**Exit:** writing starts.

---

## What is most likely to slip

| risk | why | what it costs | mitigation |
|---|---|---|---|
| **HermiT finds unsats late** | the deep check has not run against the current store, and P1–P2 add 10 defining axioms on one parent | P5 → P6 slip, and P6 has a hard external dependency | take the baseline at the **start of P5**, on the pre-P1 build, not before — a baseline against a corpus and an ontology that are both still moving measures nothing. Deliberately deferred 2026-09-10. |
| **P1 curation is slower than 10 axioms suggests** | each needs a definition, a bearer decision, and a parent — the `degree of wound pain` note shows how much thought one takes, and PATO turned up two false friends in one pass | the 16 CQs it carries | the pattern is fixed and already exists ten times; copy structurally, decide only the names |
| **BioPortal submission mechanics** | external service, unknown current state | the whole tail | verify in P0, not in P6 |
| **9 FAILs blocked on `RelationType`** | structural, not incidental | 9 CQs | P3 is scheduled in parallel, not after |
| **The derived rebuild (P4) is dirtier than it looks** | section E redefines classes that store terms have already been absorbed into, so the mapping review is re-reading decisions, not recomputing them | P4 slips into P5's window, and P6 has a hard external dependency | keep every measuring run throwaway, so only the last review is load-bearing; the LLM adjudication cache means rebuild *n* is far cheaper than rebuild 1 |
| **The stale skeleton has already cost something** | both gates have reasoned over a 20 Aug WONT since 4 Sep; quarantine decisions made in that window were made against the wrong ontology | unknown until re-measured | fix the staleness check in P0, then re-run both gates and diff the quarantine |
| **Curated / extracted split gets muddled** | if provenance is not recorded per class, the method chapter cannot state it | credibility of the whole result | provenance is already per-edge (`text` / `curated`); keep it that way and never let a curated edit be written by code |

---

## How this file is maintained

1. Add a column to **Measured state** whenever a number moves; never overwrite
   the previous column — the trend is the evidence.
2. Record what *caused* the movement next to it. "CQ 6 → 22" is a number;
   "CQ 6 → 22 after the determinate-quality block" is a result.
3. When a phase closes, keep its text and mark it closed with the exit figure.
4. Every figure measured, never estimated (rule 15).

---

## Changelog

| date | what |
|---|---|
| 2026-09-17 | **Ownership extended to annotations.** WONT carried 65 `IAO_0000115` definitions on classes it does not own (CHEBI, DOID, GO, HP, PATO, OBI, COB, IAO) — every one a duplicate of the module's; removed, rule 34 refined. Also: `Method used for medical condition treatment` and a `prophylaxis plan specification` moved into MILD (120099/120100), hypertrophic scar off the disorder branch, `Wound care procedure` dropped, DOID `relatedMatch` on sepsis/osteomyelitis, CQ022 retired. Measured: **CQ 48 / 52**, closure 34,787, 167 external terms labelled, ELK 0, 1009 tests. |
| 2026-09-17 | **Treatment and phase CQs rewritten on the curator's rulings; P3 withdrawn.** Nine `is_treatment_for` CQs → an agent `participates_in` a treatment process (dressing → wound dressing process, vancomycin → antibiotic administration process, mattress/footwear → pressure offloading process) or a process `has_participant Wound`; `Wound treatment process ⊑ has_participant some Wound`. Four phase CQs → what the classification scheme says (`Proliferative phase is_about Granulation tissue formation process`; `Inflammatory phase is_a Wound healing phase`), the checker reading individuals (rdf:type step, plain assertions; 2 tests, mutation-checked). CQ044/073 retired. Measured: **CQ 48 / 53**, ELK 0 unsatisfiable, closure 34,721 triples, 1009 unit tests. Left: the five FMA anatomy references. |
| 2026-09-17 | **Ten CQs retired on curator rulings, three answered.** Premises rejected and recorded as `out_of_scope` with reasons (NF and abscess are not wounds; laceration not acute by definition; DFU, impaired healing, sepsis, dehiscence not complications by definition; colonization is a grade; irrigation not part of cleansing) — in-scope denominator 65 → **55**. Burn ⊑ trauma, `Wound complication disorder`, `has_participant` in the checker. Measured: **CQ 35 / 55**, ELK 0 unsatisfiable, 1007 unit tests. |
| 2026-09-17 | **Complication pattern and the sixth curation round.** Co-location retired for MILD's complication pattern (rule 35); `output_of` on unplanned processes; venous/arterial classes renamed. Then 44 hand-minted classes reviewed and renumbered to `WONT_0000544–587` (wounds, disorders, phases, interventions, diagnostics, criteria, roles/functions), `threshold specification` moved to MILD (`MILD_120098`) because MILD had been made to depend on WONT. Fourteen CQ label fixes, CQ003/CQ056 rewritten. Measured: **CQ 21 → 22 → 32 / 65**, closure 34,661 triples, 165 external terms all labelled, ELK 0 unsatisfiable, 441 WONT classes + 48 individuals. What is left is in `WONT_TODO` §1: 13 curator's calls, 4 anatomy references, and the `is_treatment_for` decision (9 CQs). |
| 2026-09-16 | **Three more rounds of hand curation reviewed.** `colonized` and the CDC/IWII bioburden split, aetiology via wound-causing processes, `Neoplastic wound` dropped; 23 new entities renumbered `WOND_1200xx` → `WONT_0000511–533` (the `WOND_` prefix keeps recurring from Protégé's entity-creation default — check it each round). Review fixes: venous co-location axiom restored (cut, not copied); `arterial-inflow wound ⊑ PAOD` removed; `Autoimmune disease related wound` had lost its parent; CDC `Clean wound` freed from `≡ Wound ⊓ sterile`; IWII hub union completed. `fma_module` built (Skin → Anatomical entity, grounded under material entity), MILD imports it. **The chronic branch will never be populated** — no wound class is chronic by definition, every wound starts acute — so CQ001/002/006 were rewritten, plus CQ010/011/012/033/091/110; the checker learned `output_of` and intersection fillers. `ontology_labels()` now skips individuals (grades stay individuals by decision) and includes alt terms. Measured: **CQ 15 → 21 / 65**, closure 34,275 triples, roots beside `entity`: `disease`, `unit`. |
| 2026-09-12 | **WONT/MILD hand edit reviewed; modules regenerated (F2).** Moritz applied `WONT_TODO` A and most of E in Protégé. Review: 36 `WOND_1200xx` IRIs renumbered to `WONT_0000475`–`0000510` with `extend.next_free_id`; definitions written for all 36; `Wound ⊑ has_quality some epithelialized` removed; a definition that had landed on `skos:relatedMatch` moved; Jackson's zones relabelled as zones; direct `owl:imports pato.owl` removed. `build_disease_proposal.sh` FIX 3: the 16.3 MB `obi_module` was STAR running away over full `pato.owl` (measured: 0.9 MB without it, 15.2 MB with) — PATO is now BOT-extracted alone first, DOID/HP are MIREOT paths, `unit` a stub; closure 220,252 → **34,071 triples**, 29 foreign roots → 3, schema rebuild 33 s → 2.6 s, every external class WONT/MILD uses labelled. CQ checker taught to see restrictions inside `owl:equivalentClass` (they entail the subClassOf form) — 1 test, mutation-checked. **CQ 6 → 15 / 65.** B closed as not needed (parents were inside intersections). |
| 2026-09-12 | **The store is the one record (rule 33).** Blocklist, predicate filter, prune and reasoner gate now write *verdicts* into the store's `decisions` record instead of deleting; one `effective_records()` applies them for every reader; verdicts are authored and liftable, so un-blocking a term and re-hearing a quarantined triple against a newer WONT both work. Measured: live store 606 docs / 22,280 cells, effective view identical to raw (no verdicts yet); the 278 entities the blocklist removed mid-extraction are gone for good. 16 tests, 5 mutations fail by name. |
| 2026-09-12 | **Schema staleness closed** (the last open P0 item besides B): the builder moved into the package as `llm/schema_builder.py`, `run_extract_to_store` regenerates it when any source is newer; 14 tests, 4 mutation-checked by name. Measured: rebuild 33 s, current schema identical to a fresh build apart from the date. The full-suite run of 2026-09-12 also found and fixed the `Skin grafting → Skin graft` guard hole (a contradicted typing read as unknown). |
| 2026-09-10 | Created. Baseline measured: 142 abstracts, CQ 6/65, 47 of 51 unresolved concepts absent from the store, 9 of 18 FAILs blocked on `RelationType`. |
| 2026-09-11 | **PC batch 1 complete: all 606 fetched abstracts extracted, 12,901 distinct entities** (from 3,536). Two interruptions on the way — the provider went unresponsive and the circuit breaker aborted at 469 after 22 consecutive timeouts, exactly as designed; and a relaunch picked up the cap-200 CSV and started the unauthorised big batch, killed after one PMID; the runner now takes a PMID-restriction file. |
| 2026-09-11 | Found and fixed: `add_llm_extracts` queued rows, not PMIDs, so a paper found by three queries went to the model three times and the last answer silently overwrote the first — 193 calls for 136 PMIDs measured; the cap-200 batch would have wasted 1,974 of 7,536 calls. Deduped on PMID, folded count announced, 4 tests, mutation-checked. |
| 2026-09-11 | Cap-200 fetch done in 3 min, 0 errors: 606 → **6,031 unique PMIDs** (9,351 rows), **5,659 unextracted**. Big-batch extraction gated on E + schema regeneration, by decision. Found `extraction_schema.yaml` is a WONT snapshot with no staleness check — same class as the skeleton; only the gate weakens, not the store. Added to P0. |
| 2026-09-11 | PC extraction relaunched for the remaining 235 after the first run died with its session at 371 PMIDs / 8,575 entities. Runner moved into `scripts/`, logs into `output/`. Cap-200 fetch of the same 43 queries started in parallel (`scripts/pc_fetch.py`). |
| 2026-09-10 | **PC started.** The abstract database holds 606 unique PMIDs across all 43 queries and only 142 were in the store, so 464 were fetched and never extracted — 614 rows now running through `run_extract_to_store`, at no PubMed cost. Every query returned exactly 20 PMIDs: the search ran at a cap of 20, so re-running the same list at 200 is the next lever. |
| 2026-09-10 | **P0 done and verified: 118 tests pass.** `fold()` now yields candidates instead of guessing once; the CQ resolver uses the shared `LabelIndex` (rule 13); `build_reasoner_skeleton` compares mtimes and `reasoner_gate` routes through it. All 8 new tests mutation-checked — restoring either defect fails them by name. One existing test changed meaning and was rewritten: `Chronic Wounds` used to be reported as a missing class and now resolves. |
| 2026-09-10 | **Environment hazard, hit and cleared:** 18 files in the tree were dataless iCloud placeholders (`st_blocks == 0`) — including the corpus CSV and three modules on the Orchestrator's import path. Reads block indefinitely at 0% CPU and `brctl download` returns 0 without materialising; forcing a full read of each one worked. 8 remain evicted, none on the extraction path (`ro.owl`, `uo.owl`, three superseded `ground_truth_*` copies, two stale caches). Worth knowing before the next stall: it looks like a hang, not an error. |
| 2026-09-10 | HermiT baseline called off as premature — the corpus and the ontology are both still moving, so it is deferred to the start of P5. Measured on the way out: `run_deep_reason` cannot read Turtle and OOMs at owlready2's default 2 GB heap, and reports an empty unsatisfiable set when it does. Both recorded in P5. |
| 2026-09-10 | Pipeline run order traced end to end and added. The concept store and the abstracts survive a WONT edit — extraction never reads WONT — so the derived layer (steps 4–17) is what a curation change costs, and it is the cheap layer. Critical path split into two lanes converging on a single derived rebuild (P4). Found `build_reasoner_skeleton` reusing a skeleton 15 days older than WONT, with no staleness check. |
| 2026-09-10 | P1 re-scoped after checking the full PATO: 4 determinates reused instead of minted, 2 false friends found (`sterile` is fertility, `chronic` is process duration), and `Infected wound` / `Malignant wound` found already better defined than CQ093/CQ091 ask. |
| 2026-09-10 | **Rewritten for the stated priority: the ontology over the pipeline proof.** Hand curation moved onto the critical path (P1, P2); corpus expansion demoted from "the long pole" to a continuous non-gating track; the pipeline given its own measure (3552/4011 edges, 2811/3536 placed) instead of sharing the CQ score. Re-measured: 45 absent, not 47 — `Inflammatory Phases` and `Proliferative Phases` are in the store, unreachable through `fold()`. 684 parked entities resolved to 9 roots, of which 514 are methodology vocabulary and 170 are the real curation pool. |
