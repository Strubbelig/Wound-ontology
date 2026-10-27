# Instructions

Standing design rules for this pipeline. These are **decisions, not suggestions**:
they override defaults, and code that violates one is a bug even if it passes its
tests.

This file is living. Every time a universal design choice is made, it is added
here with the date it was decided. Rules are never silently rewritten — if one is
superseded, the old text stays with a note saying what replaced it and why.

Written in English. (The original pipeline carried instructions in German; they
are folded in here, in English, and this file is now the single place to look.)

Companion documents:

- `README.md` — what the project is and how to run it.
- The living pipeline reference (Artifact) — how each stage works and *why*,
  end to end: <https://claude.ai/code/artifact/57125e2f-667b-42fe-9b15-e1002c981517>
- `ontology_pipeline_upgrade_plan.md` — historical plan. Where it disagrees with
  this file or with the code, this file and the code win; the plan is not
  authoritative and is known to be wrong in places (see rule 15).

---

## 1. No silent failure

*Decided long-standing; the rule everything else is measured against.*

Nothing may fail, degrade, or drop data without saying so. A missing file, an
unparseable ontology, an empty result, a filter that removed 93% of its input —
each raises or warns, and reports the number.

The recurring bug class in this codebase is **work that quietly does less than it
claims and reports only a smaller number**. A count printed without a denominator
hides this; print both. `except Exception: pass` is never acceptable, in source
or in tests.

A parameter that no longer has an effect is the same failure in slow motion: it
advertises behaviour it does not have. Either remove it or make it announce its
own inertness.

## 2. The ConceptStore is the only thing that holds

*Decided 2026-09-03.*

If a value must survive the next run, it lives in the ConceptStore. Everything
else — the context matrix, both hierarchies, the lattices, the exported OWL — is
**derived and disposable**: it may be thrown away and recomputed at any time.

When something must be kept and cannot be re-derived, that is the signal it
belongs in the store — *not* that the derived artifact should start remembering.

*Enforced by:* `ContextMatrix.fill_nan` (verdicts go to the store, then the view
rebuilds), `ConceptStore.merge_entity_records`.

## 3. …but nothing derived is injected into the store

*Decided 2026-09-03, correcting an over-application of rule 2.*

Rule 2 says the store is what persists. It does **not** license writing derived
results back into it. The store holds what was extracted from documents. Putting
a lattice-derived edge or a curated edge into it makes the store claim something
it never extracted, and then requires a second mechanism to un-launder the
provenance on the way back out. A mechanism whose only job is to reverse the
previous mechanism means the design is wrong.

Instead: **`get_data` reads from several sources**, and provenance is a property
of *which source an edge came from*, established at read time.

| Source | Provenance stamp |
|---|---|
| ConceptStore (extracted from abstracts) | `text` |
| Curated ontologies (WONT, MILD) | `curated` |
| An accepted slice of an FCA lattice | `fca` |

*Enforced by:* `BaseHierarchy.get_data(store, curated=…, fca=…)`,
`ClassHierarchy.promote_candidates(lattice=…)`, `ConceptLattice.accept/slice`.

## 4. Curated outranks derived; a lower rank never overwrites a higher one

*Decided long-standing.*

`curated` (3) > `text` (2) > `fca` (1). `_set_edge` refuses a lower-ranked
overwrite. The ground truth is genuinely ground truth: an extraction run may not
add a parent to a curated class, restate one, or contradict one. Such edges are
counted in the merge report instead of applied.

FCA in particular is a **suggestion**: it observes that terms share attributes,
which is evidence for a superclass, not an assertion of one. `commit_fca`
defaults to `False` and stays that way.

### Rank governs removal too, not only writing

*Added 2026-09-04.*

When a reasoner finds a contradiction, the edges it implicates are **not** equal.
Drop the **lowest-ranked** evidence first, re-check, and only escalate if the
clash survives. A curated edge is quarantined only when the curated edges are
inconsistent *among themselves*.

The motivating failure: WONT asserts `Necrosis subClassOf pathological disorder`
and nothing else. Two abstracts typed Necrosis as a `Process`. BFO makes
continuant and occurrent disjoint, so the reasoner derives `Necrosis ⊑ ⊥` — and
the gate quarantined **both** edges, the curated one included. A text assertion
had removed a ground-truth axiom, which is the exact thing the ranks exist to
prevent. It cost the hierarchy 6 curated edges and produced a report claiming
WONT was internally inconsistent, when WONT was correct.

Two details that the first fix got wrong, both worth keeping in mind:

- Tier **globally**, not per child. `Dry Necrosis is_a Necrosis` is curated and
  is that child's only edge, so per child it looked like the weakest evidence
  available and went — while the text edge that made `Necrosis` unsatisfiable in
  the first place was still present. Its child was unsatisfiable only by
  inheritance. Drop one whole rank at a time across all implicated edges, so a
  cause is removed before its consequences are judged.
- An edge the caller could not stamp counts as the **lowest** rank of all: an
  edge nothing claims is the first thing to give up.

Rank buys precedence, not immunity — if the ground truth really does contradict
itself, the gate must still say so.

*Enforced by:* `ReasonerGate.check_edges(edges, sources=…)`, given
`hier._prov` by `Orchestrator.run_gate_hierarchy_edges`. The result reports
`quarantined_sources` and the higher-ranked edges it `spared`, so a rank-blind
regression is visible in the run output rather than only in the totals.

## 5. Quarantine, don't drop

*Decided long-standing.*

When the reasoner rejects something, isolate it with an explanation and commit
the rest of the batch. Nothing good is discarded because something adjacent was
bad.

*Refined by rule 33 (2026-09-12):* the isolation is a verdict written into the
store beside the assertion, not a removal into a side file. The quarantine
directory remains as the per-batch log.

## 6. Analysis artifacts are per-analysis, and builds replace

*Decided 2026-09-03.*

A derived artifact must never accumulate across runs. A build **replaces** the
previous contents; it does not merge into them.

- The context matrix is a *view* of the store: it exists because FCA needs a
  frame where the store is a dict, and because a lattice over the whole corpus is
  neither computable nor readable. A restricted build must analyse exactly the
  slice it was asked for.
- **Every subtree analysis gets its own lattice instance**, and its own FCA
  hierarchy. Reusing one instance across subtrees unions unrelated analyses.
- An empty slice clears the view rather than leaving a stale one for the next run
  to analyse.
- When a rebuild drops rows or attributes that were there a moment ago, say so,
  and say where they still exist.

Review of FCA output produces a **slice of the lattice**, and that slice is what
is fed into the class hierarchy as an `fca` source. The acceptance is a human
decision and does not evaporate because a re-run produced a slightly different
lattice — an accepted edge the current lattice no longer contains is still
applied, and reported.

*Enforced by:* `ContextMatrix.df` setter (replaces), `FCAHierarchy.get_data`
(clears before rebuilding), `Orchestrator.run_fca` (a new `ConceptLattice` and
`FCAHierarchy` per subtree, named by slug), `Orchestrator.accepted_fca_slices`.

## 7. An analysis is never fed its own output

*Decided 2026-09-03.*

The objects of the FCA context are the concepts **a source asserts** inside the
requested slice: the store, for anything an abstract mentioned, and the curated
source, for concepts hand-authored in WONT or MILD that the corpus never
discusses. Nothing else becomes an object.

A concept known only from an accepted FCA slice must **not** become a context
object, or the next lattice discovers structure it proposed itself. A concept
known only from a text-stamped hierarchy edge does not need adding — it has a
store record by construction.

The motivating failure is a pair of true statements that cannot both be enforced
naively. Removing the curated injection (rule 3) took away the store records that
gave curated-only concepts their rows, which would have collapsed the Wound
subtree from 40 objects to the handful the abstracts happen to discuss — and made
it look like thin source data rather than a missing source. Adding rows for the
whole hierarchy fixed that and broke the older invariant that scaling adds
attributes, never rows. Scoping the addition to the curated source satisfies both.

*Enforced by:* `BaseHierarchy.concepts_from(sources)` — "which concepts does
*this* source assert" is a different question from `concepts` — called with
`{SOURCE_CURATED}` in `ContextMatrix.get_data`.

## 8. A name is checked against the kind of thing it names

*Decided 2026-09-03.*

Every label the pipeline proposes as a superclass must be the **same kind** of
thing as the members it groups — their own BFO/MILD category, or an ancestor of
it. More general, never sideways.

The motivating failure: FCA named a formal concept whose extent was entirely
material wounds "Traumatic Wound Healing Disorder", and proposed every member
underneath it. Nothing downstream could catch it. The reasoner gate has nothing
to work with, because the label is newly minted and carries no axioms to clash
with, and the provenance ranks only say FCA is weak evidence — not that it is
categorically wrong. A suggestion that crosses a categorical boundary is not a
weaker suggestion; it is a wrong one.

The checks are deterministic, and a failure at any of them leaves the concept
**unnamed** so it proposes nothing — reported, never silent:

1. The name must not *be* a BFO category. Showing the model the extent's
   category stopped it proposing disorders over wounds and started it answering
   "Material entity" — the constraint read back as an answer. Compare with
   separators stripped: the categories are CamelCase and the model answers in
   prose, so a naive match passes exactly what the check exists to catch.
2. Where MILD or WONT already knows the label, **their** category must be the
   members' own category or an ancestor of it. A superclass is more general,
   never sideways. The members' category is read off the concept's intent, which
   needs no model: `is_a: materialentity` is in the intent exactly when every
   member carries it.
3. A label the ontologies do not know is **not judged this way at all**. What
   keeps a new name honest is being named top-down under an already-named
   parent, not a self-report.

**Superseded 2026-09-04:** an earlier version of this rule had the model return
the category of the name it had just invented, and checked that. It looked like a
check and was not one — unverifiable by construction whenever the label was new,
and satisfied by answering "MaterialEntity" whatever the name meant. Across five
live runs it refused no bad name and lost one good one to a missing field. The
grounded half is kept above; the self-report is gone.

### Prerequisites for `semantic_superclass_names`

*Added 2026-09-04, after the type check alone proved insufficient.*

Naming a formal concept in isolation is a guess about what a set of attributes
means, and independent guesses do not cohere. Four different concepts came back
called "Wound"; `smart_title` folded them onto one node; the lattice's own order
edges then read `Wound is_a Skin Defect is_a Wound`. "Wound is a skin wound" is
obviously incorrect, and no amount of per-name checking would have caught it,
because each name was defensible on its own.

So naming has these prerequisites, and they are the algorithm, not decoration:

1. **Top down.** General before specific, known before unknown. The most general
   concept is named first; every later concept is named with its already-named
   parent in hand. This makes the question much smaller — not "what do these
   attributes mean" but "what distinguishes THIS group from the more general one
   it sits inside" — and it makes an inverted edge unaskable, because the parent
   is fixed before the child is named.
2. **The parent is given to the model**, by name, together with the
   **differentia**: the attributes this concept has that its parent does not. A
   subclass name may never be more general than its parent's, and may not repeat
   it.
3. **Names are unique.** Two formal concepts are two classes and may not share a
   name. Enforced after the answer, not merely requested in the prompt: naming
   used to run concurrently, so every worker read the "names so far" list before
   any name existed and it was always empty.
4. **A cycle is refused**, wherever it would be written. A cycle is not a weak
   edge but an impossible one — both classes claiming to be strictly more general
   than the other. Only self-loops were caught before.
5. **FCA-derived edges are stamped `fca`**, including inside the FCA hierarchy
   itself, which used to take the `text` default and record its own suggestions
   as things a paper had asserted.

Naming is therefore **sequential** by necessity: each name is an input to the
next. That is slower than the parallel version it replaces, and worth it.

*Enforced by:* `ConceptLattice.name_is_a_grouping`,
`ConceptLattice.category_of_known_class`, `ConceptLattice.name_is_licensed`,
`ConceptLattice.name_is_unused`, and the top-down loop in
`create_superclass_names`; `BaseHierarchy._set_edge` refuses cycles;
`FCAHierarchy.get_data` stamps `SOURCE_FCA`. Categories are read off the
context's `is_a: <Category>` columns by `ConceptLattice.extent_categories`,
which ignores the `is_a: <ancestor>` columns conceptual scaling writes — those
are classes, not types, and reading one as a type would license anything.

## 9. A term has one category, decided once

*Decided 2026-09-04.*

Stage-1 typing runs per abstract, so nothing stops two abstracts typing the same
term differently. Those disagreements may **not** each become an edge. A term
gets **one** category edge, decided across the whole corpus: the most specific
category MILD says subsumes every typing it received. Where the typings share no
common ancestor, the term gets **no** category edge and goes on a review list.

Otherwise the hierarchy contradicts itself by construction and the reasoner is
left to clean up after it. `Necrosis` arrived as `MaterialEntity` from one
abstract and `Process` from two others; both became edges; BFO makes continuant
and occurrent disjoint. Measured: **42 of 48 quarantined edges were this, across
16 terms**. With reconciliation the quarantine drops to **1** — a single text
assertion contradicting a curated parent, which is a different problem and
belongs to the gate.

The store keeps every abstract's opinion. The disagreement is *data*, and rule 3
forbids a derived artifact rewriting its source; what may not survive is an
incoherent hierarchy built from it.

The irreconcilable list is the product, not the failure. It is short (27 terms)
and it is coherent: `Granulation` is both the tissue and the process that forms
it, `Infection` is a process and a disposition and a material colony,
`Adverse Events` and `Clinical Outcomes` are study-endpoint vocabulary rather
than clinical entities. Each needs splitting into distinct classes or
blocklisting — a curation decision, surfaced as 27 named terms instead of a
reasoner failure spread across 42 edges.

Note that the reconciled category is often one **no abstract proposed**:
`Process` and `ProcessBoundary` agree on `Occurrent`, which neither of them said.
So it is emitted, not selected from what was asserted.

*Enforced by:* `BaseHierarchy.get_data(..., reconcile_categories=…)`, given
`ReasonerGate.least_common_category` by `Orchestrator.run_build_hierarchies`.
The terms with no honest category land in `hier.irreconcilable` and are printed.

## 10. Undecided is not false

*Decided long-standing.*

`NaN` in the context matrix means *not decided*. It is not `false` and emphatically
not `true` — and `bool(float('nan'))` is `True`, so letting one reach the FCA
context silently asserts the attribute holds and manufactures invented
superclasses.

The lattice is therefore built twice, once reading undecided as absent and once
as present; only concepts appearing in both are certain. Anything appearing only
in the optimistic reading is a candidate and must not be committed.

Where information is genuinely complete, say so with an explicit `0` rather than
leaving a gap: an `is_a:` column is closed-world for every object the hierarchy
places, and leaving those cells undecided made scaling strictly worse than not
scaling at all.

## 11. The schema is generated from the ontologies, never hand-written

*Decided long-standing.*

A hand-maintained extraction schema drifts and ends up contradicting the ontology
it serves. The categories, the licensed relation pairs and the grounding table
are generated from MILD and WONT.

The model never emits an IRI. Grounding is an **exact-label lookup** against the
ontologies, which removes the hallucinated-identifier failure mode rather than
trying to detect it afterwards.

## 12. Ambiguity is refused, never guessed

*Decided long-standing.*

When a label is claimed by two classes at once, it is reported as ambiguous and
minted, not resolved to a coin flip. Merging through a *narrow*, *broad* or
*related* synonym is worse than a duplicate, so only exact-synonym predicates are
indexed as the same concept.

## 13. Names are normalised in exactly one way

*Decided long-standing.*

`smart_title` is the normalisation, and it preserves acronyms (`CO2`, `MRSA`,
`pH`). Comparing a normalised name against a raw one is the single most frequent
silent bug in this codebase — it has produced a matrix that matched 302 of 4180
names, a subtree restriction that discarded 93% of its own subtree, and an
inheritance pass that silently inherited nothing.

**Normalise both sides of every comparison**, and prefer a helper that cannot be
called with only one side normalised.

## 14. Superseded paths are deprecated, not deleted — and warn before doing work

*Decided 2026-08-30.*

Stored outputs, notebooks and tests reference the old paths, so they keep working.
The `DeprecationWarning` must fire **before** any of the work runs, otherwise a
run learns it used the wrong path only after the file is written. The warning
text names the replacement and says what the old path does wrong.

## 15. Measured, not estimated

*Decided long-standing.*

Figures quoted in documentation and commit messages come from real runs. When
they change, re-measure rather than guessing. Where a document states a rationale,
it is the reason recorded in the code, not a reconstruction.

This applies to the upgrade plan too: `ontology_pipeline_upgrade_plan.md` §2A.5
claims that adding superclasses as attributes means FCA "cannot contradict" the
hierarchy. It can. Superclass attributes alone left 29 hierarchy edges violated;
only with attribute inheritance did it reach 482 of 482 respected.

## 16. Tests must be capable of failing

*Decided 2026-09-01.*

An assertion that never runs is not a test. Two stale assertions survived for
months in `test_fca_on_subtree` because the lattice was empty on most runs, and
because concept naming is a live LLM call that only sometimes produces a name.

- Any contract worth having is pinned by a **deterministic** test that needs no
  model.
- Integration tests that call the model live are additional, never the only guard.
- When a test is corrected, the comment says what it used to assert and why that
  was wrong, so the distinction stays visible.

## 17. The pipeline reference stays current

*Decided 2026-08-31.*

The living reference Artifact is updated whenever the pipeline changes: revise the
affected stage in place and add a dated entry at the top of its change log.
Republish to the same URL. Keep the favicon 🩹 and the title stable.

---

## 18. An identity claim is adjudicated, never inferred from distance

*Decided 2026-09-06.*

Mapping a store term onto an existing WONT or MILD class asserts that the two
**are the same class**. It is not a similarity ranking, and it does not get a
second look downstream: once applied, the store term is gone and every axiom
built afterwards hangs off the ontology's IRI. Nothing that irreversible may
rest on a cosine number.

The measurement that settles it, over the 50 anchor mappings SapBERT proposed on
the 2026-09-05 build:

    chronic wounds            -> Chronic wound                        0.9785  right
    clean wound class. grade  -> clean-contaminated wound class.grade 0.9736  WRONG
    E. coli                   -> Escherichia coli                     0.9708  right
    Horizontal mattress suture-> Vertical mattress suture             0.9604  WRONG

The right and wrong proposals are interleaved, so no threshold separates them —
and raising it loses the good matches first, because the bad ones are
*semantically close*, which is exactly why the embedding likes them. Differential
similarity over the differing tokens was tried and fails too: it separates
horizontal/vertical (0.8466) but collapses on added tokens, word order and
abbreviations (`e` vs `escherichia` = 0.5028).

What does separate them is **what the labels differ by**:

    identical tokens (case/punctuation only) : 18 pairs, 0 wrong
    differ only by inflection (plural)       : 10 pairs, 0 wrong
    differ by CONTENT                        : 22 pairs, 7 wrong

SapBERT is exactly reliable on surface variance and exactly unreliable once a
real word changes. So `label_difference` draws that line and only the
content-differing pairs are adjudicated by the LLM, which is shown the ontology's
own `IAO_0000115` definition — the *label* is what misled the embedding, so the
label cannot also be the evidence. Where a class has no definition its named
superclasses stand in.

The model answers from a fixed enum and never emits an IRI (rule 11). Only
`same_class` becomes a mapping. `narrower` and `broader` are not failures: they
are candidate subsumption edges, saved as `mapping_subsumption_candidates` rather
than discarded (rule 5). Anything else, including a verdict outside the enum, is
refused and reported.

**The model is integral, not an enhancement.** `run_build_term_mapping` raises
when no key is configured, and `adjudicate` raises when a pair comes back
undecided twice — because the alternative is a mapping that stands only because
nobody looked at it. There is no offline mode for this step.

The deterministic guards run *first*: a mapping already refused by
`_category_compatible_mapping` never reaches the model, so the cheap check stays
authoritative and the call budget goes to genuinely undecided pairs.

Store-to-store merges are adjudicated too, but **without category hints**. This
was measured on 2026-09-06 and the first answer was wrong twice over. The
population was first quoted as 941 content-differing pairs; that counted the
whole mapping file, 86% of which is residue from earlier builds, and only **52**
of those pairs touch a term the store still holds. The first run over those 52
then reported 46% not-synonymous — inflated, because it passed the store's own
per-abstract typings in the slot where the anchor path passes the reasoner-backed
skeleton TBox, and the model started refusing on "store term is MaterialEntity,
ontology class *likely* Process". It refused `haemorrhage -> Hemorrhage` as
different BFO types. There is no ontology side on this path, so there is no
category to show: judged on labels alone the real figure is **14 of 52, 27%** —
`diabetes mellitus -> diabetes`, `deep second-degree burns -> deep second- to
third-degree burns`, `hip and knee arthroplasty -> hip or knee arthroplasty`.

The reversibility argument that had excluded them does not survive contact with
that number. It rested on `review_mapping()` undoing a bad merge, which assumes
someone walks 2141 non-identity entries; nobody ever has. Closing it costs three
model calls.

Live result over both paths, 2026-09-06: 148 pairs kept on surface form with no
call, 67 adjudicated → 45 same class, 12 subsumption candidates, 10 refused, 22
withdrawn. All seven known-bad anchor pairs were caught and no correct one lost.
The subsumption candidates are the substantive catch: `diabetes mellitus is_a
diabetes`, `deep second-degree burns is_a deep second- to third-degree burns`,
`hip and knee arthroplasty is_a hip or knee arthroplasty` — three merges that
would each have destroyed a real distinction.

**Known limitation: the verdicts are not perfectly reproducible.** At
temperature 0.0, `antiseptic preparation -> antiseptic drug` came back
`same_class` on one run and `different` on the next, with the same definition in
front of it. Three of the ten refusals are hedged in their own reason text
("may", "potential", "probable"). This is why verdicts are cached rather than
re-derived: a pair is decided once and the decision is kept. Use
`readjudicate=True` deliberately, knowing a borderline pair may flip, and treat
refusals as a review queue rather than a final answer — refusing costs one
duplicate class, which a curator can still merge.

Enforced by: `mappers/mapping_adjudicator.py` (`label_difference`, `triage`,
`adjudicate`), `LLMClient.adjudicate_mappings_batch`,
`Orchestrator._adjudicate_anchor_mappings`, `Orchestrator.ontology_definitions`.
Verdicts are cached on the entry they judge (`TermMapping.pass_cache`, rule 38);
re-ask with `readjudicate=True` after the ontologies' definitions change.

## 19. The mapping is pruned to what can still fire

*Decided 2026-09-06.*

The term mapping accumulates across builds and never forgets. On 2026-09-06 it
held 26625 entries against a store of 3727 terms, and that excess was doing two
different kinds of harm.

24441 were IDENTITY entries — a term mapped to itself, which `get()` already does
for anything unmapped. They changed no behaviour, but they were 92% of the file,
and they are why the mapping looked like an unreviewable 26k artifact rather than
the ~200 real decisions it contains. `review_mapping()` has never once been run
over it; that number is the reason. `build_from_embeddings` no longer writes them
— it persists merges only, and returns the full assignment so a caller can still
ask what happened to any term it was given.

1969 of the 2184 non-identity entries pointed at a canonical that is neither a
live store term nor an ontology label: `-125 mmHg -> -125 mm Hg`, `18% -> 18`.
Both ends had been cleaned out builds ago. Such an entry is not merely useless —
when a later abstract reintroduces the term, it renames it onto a target that
exists nowhere.

**A missing term is not the test.** After `run_apply_mapping` the mapped term is
absent from the store *by design*, and the entry must survive so the same
normalisation happens the next time that term appears. It is the CANONICAL having
died that makes an entry inert. Chains are followed rather than assumed away:
`A -> B -> C` is kept when C is alive. Exactly one chain exists in the current
file and it resolves to nothing, but correctness must not rest on that.

After pruning: **193 entries, all real merges, 177 of which can fire on a term
the store holds today.** That is what makes rule 18's review step possible at all.

Enforced by: `TermMapper.prune` (with `dry_run=True` to look first),
`TermMapper.build_from_embeddings`, called from
`Orchestrator.run_build_term_mapping`.

## 20. A BFO category is declared, never matched

*Decided 2026-09-07.*

Every extracted term is typed with one of the 15 BFO categories, and
`CATEGORY_IRI` already says which class each category name means. The exporter
must read that declaration. It may **not** look the category name up in the
label index, because a closed vocabulary with a known IRI has nothing to gain
from fuzzy matching and everything to lose from it.

It did look them up, and the lookup half-worked, which is the worst outcome:
`LabelIndex` folds punctuation and plurals but does not split CamelCase, and the
vocabulary was CamelCase (see rule 25), so the one-word names hit their BFO
label (`Process` -> BFO_0000015, `Quality` -> BFO_0000019, and six others) and
every multi-word one missed. `MaterialEntity` does not match `material entity`.
For those five, `resolve()` fell through to minting — creating a **duplicate of
a BFO class it already had**, as a fresh WONT class carrying the pipeline's own
"it has no BFO anchor" note:

| minted twin | id | children | the real class it duplicated | its children |
|---|---|---|---|---|
| MaterialEntity | WONT_0000477 | 1124 | BFO_0000040 `material entity` | 15 |
| InformationEntity | WONT_0000483 | 543 | BFO_0000031 | — |
| ImmaterialEntity | WONT_0000519 | 64 | BFO_0000141 | — |
| ProcessBoundary | WONT_0000505 | 37 | BFO_0000035 | — |
| RealizableEntity | WONT_0001322 | 2 | BFO_0000017 | — |

**This was never a defect in WONT or in BFO.** WONT is BFO-based throughout: it
parents 15 classes directly on `BFO_0000040`, uses 5 distinct BFO parents, and
contains no class labelled `MaterialEntity` at all. `material entity` was not
floating anywhere. The twins existed only in the generated
`output/owl/wont_extended.ttl`, alongside the real classes, and each twin
subclasses nothing — so the **1770** extracted classes hanging under them were
unreachable from BFO while the real BFO classes kept only their curated
children. Measured on the same inputs with the fix off and on: WONT classes with
no asserted path to `BFO_0000001 entity` fall from **1769 to 43**, 7 fewer
classes are minted, and BFO_0000040's children go from 15 to 1103. No competency
verdict changed — this repairs structure, not coverage.

The category IRIs are added to `existing_iris`, so the rule in section 3 covers
them too: an extraction run does not get to hang an axiom on BFO_0000040.

Enforced by: `owl/extend.py::CATEGORY_IRIS` and the `_resolve` short-circuit;
`test_category_names_resolve_to_their_declared_iri`,
`test_the_category_class_is_never_given_a_parent`,
`test_every_category_name_has_a_declared_iri`.

## 21. Two terms landing on one class is a merge, and is reported

*Decided 2026-09-07.*

`resolve()` folds plurals and punctuation, so two terms the hierarchy kept apart
can arrive at the same IRI — and when they do, every axiom on either becomes an
axiom on both. This is usually right (`wounds` and `Wound` are one class) and
occasionally not, but it is always a **merge**, performed at export, after every
upstream review has finished. A merge nobody is told about is exactly what rule
1 forbids, so `ExtendReport.folded` records it and the run summary counts it.

Measured on the current caches: **98 classes were claimed by two terms**, almost
all singular/plural pairs. Of the 12 classes that sit under two disjoint BFO
branches in the extended ontology, **11 are folds** — `Bacterial Load` typed
Quality meeting `Bacterial Loads` typed MaterialEntity, `CRP Level`
(InformationEntity) meeting `CRP Levels` (Quality), `Improvement` (Process)
meeting `Improvements` (Quality). The twelfth, `hormone`, arrives already
incoherent from the imports and is not ours. Rule 9 reconciles the categories of
*one* term; it cannot see two terms that only become one downstream.

The report is not the repair. Applying the mapping and rebuilding is, and doing
it took **98 folds to 20** and the branch clashes from 12 to 4 — but only after
rules 22, 23 and 24, each of which the re-run itself uncovered. Of the 20 that
remain, three are a category name meeting its own BFO label
(`['materialentity', 'material entity'] -> BFO_0000040`), which is the mechanism
working; several more are real synonym merges the lexicon should make
(`diabetes`/`diabetes mellitus` -> DOID_9351). The 3 folds that still produce an
incoherent class are plain plurals `normalize_term` does not singularize:
`Challenge`/`Challenges`, `Experience`/`Experiences`,
`Stress Concentration`/`Stress Concentrations`.

Enforced by: `ExtendReport.folded` and the `resolve`/`_resolve` split in
`owl/extend.py`; `test_two_terms_landing_on_one_class_are_reported`,
`test_a_term_resolving_to_itself_twice_is_not_a_fold`,
`test_folding_is_what_puts_one_class_under_two_categories`.

## 22. The store never normalises a category name either

*Decided 2026-09-07.*

Rule 20 says the exporter reads a BFO category rather than matching it. The same
holds one stage earlier: `ConceptStore.normalize` may not normalise a category
name. It did, and it was worse than the exporter's version of the bug, because
nothing downstream could tell.

`normalize_term` lowercases and `smart_title` cannot put CamelCase back, so
`MaterialEntity` came out of normalisation as `Materialentity`. Seven of the 15
categories are multi-word and all seven were destroyed. `get_data` decides
whether an edge is a category typing by testing `target in CATEGORY_PARENT`, and
`Materialentity` is not in it -- so **rule 9's reconciliation stopped seeing
those edges at all**. Measured across the 2026-09-07 runs:

| | store not re-mapped | after `run_apply_mapping` | with the guard |
|---|---|---|---|
| terms reconciliation sees | 1802 | 1802 | **3559** |
| conflicting typings collapsed | — | 9 | **56** |
| classes under two disjoint BFO branches | 12 | 40 | **4** |

`Surgical Site Infection` came out both a disposition and a material entity. The
guard matches separator-blind, so it also **repairs** a store already damaged
and reads a cache written before rule 25.

The guard runs in both directions. A category name is declared before the
mapping is consulted, so the mapper cannot rename one; and the RESULT of a
mapping is declared too, so a term that maps *onto* a category name arrives as
that category. Without the second half the live `roles -> Role` entry would put
`Role` in the store beside the bare `role` — two spellings of one category,
which is the split rule 25 exists to end.

Enforced by: `store/concept_store.py::_declared_category` over
`llm/category_vocab.py::declared_category`;
`test_every_category_name_survives_normalization` (parametrised over all 15),
`test_normalization_repairs_a_category_already_damaged`,
`test_a_category_name_is_never_renamed_by_the_mapper`,
`test_a_term_that_maps_onto_a_category_gets_the_declared_spelling`,
`test_a_mapped_target_is_declared_too`.

## 23. The canonical is the singular spelling, and is never itself a key

*Decided 2026-09-07.*

A canonical becomes a class **label** in the exported ontology, and an OBO class
label is singular. `_rank` decides canonicality on corpus frequency, and a paper
says the plural more often for anything it counts, so the mapping held
`diabetic foot ulcer -> Diabetic foot ulcers`, `ulcer -> ulcers`,
`symptom -> symptoms`: 9 pairs among the live entries.

This was inert while the store still carried both spellings. The moment
`run_apply_mapping` reached it, the class came out labelled
`Diabetic Foot Ulcers` and **CQ001, CQ006, CQ051 and CQ054 lost the term they
resolve on** — the whole measured value of the extension dropping from 10
resolved terms to 6. Only spellings of the same term compete (`fold` folds
punctuation and singularizes), so the rule can never trade one concept for
another; an anchor is exempt, because an ontology's own label is not ours to
re-spell.

**A canonical is never itself a key.** Re-pointing `A -> B` to `B -> A` while
leaving the old entry in place makes a 2-cycle, and a resolver that walks it
writes each term onto itself — which is how a repair pass turned 9 pairs into 18
identity entries, the exact artifact rule 19 exists to remove. Remove the old
entry; do not add beside it. The invariant to check after any edit is
`data[data[k]] == data[k]` for every k, and no `k == data[k]`.

*Refined 2026-09-23, by the curator: "I always want the singular. This can be
regex too."* The rule was asked of the MAPPING, which could only deliver it
where the corpus happened to contain a singular spelling: `_canonical` picks the
singular among the cluster's members, so a term nobody ever wrote in the
singular stayed plural, and 5,072 entries existed to record `patients ->
patient` one term at a time. A regex, written down five thousand times in a file
of decisions, and the reason the mapping read as mechanical noise.

It is now a rule about the NAME, applied in `ConceptStore.normalize` to every
name it keeps, after the mapping has had its say so a plural canonical cannot
reintroduce one. `singular_spelling` produces a name rather than a key — it
keeps the label's own casing (`Diabetic Foot Ulcers -> Diabetic Foot Ulcer`) and
handles the acronym plurals no suffix rule sees (`DFUs -> DFU`, `SSIs -> SSI`),
while `singularize` underneath it protects the medical singulars that a naive
`rstrip("s")` maims: `diabetes`, `sepsis`, `necrosis`, `osteomyelitis`,
`fasciitis`, `series`, `bias`. Declared BFO categories are exempt (rule 22), so
`process` does not become `proces`.

Consequence, and the point: those 5,072 entries became inert and were pruned.
With the 3,324 case-only entries removed the same day, the mapping went from
14,047 to about 5,600 — almost entirely content decisions. `store_name` in
`concept_store.py` is the single implementation of "what does this term end up
called", used by `normalize` to rename and by `prune_inert_mappings` to decide
whether an entry changes anything; written twice they would drift, and the prune
would delete entries that were doing work.

Enforced by: `ConceptStore.store_name`, `label_match.singular_spelling`;
`tests/test_store_is_singular.py` (nineteen cases, mutation-checked: entities
not singularised, targets not singularised, naive `rstrip("s")`, acronym plurals
unhandled), `tests/test_inert_mappings.py`.

*Refined 2026-09-22: the invariant held per build, not across builds.*
`build_from_embeddings` asserts it on every run (`assignment[c] == c` for every
canonical), so no single build can violate it — but the mapping FILE is not one
build. It accumulates, and a term this build makes a canonical may be a term an
earlier build already mapped elsewhere. Measured on the 2026-09-21 build of
15,585 entries: **735 chains whose second hop really renames** and **408
two-cycles that are not case variants** — `thermal burns -> thermal burn` beside
`thermal burn -> thermal burn injuries`, `CFU -> CFUs` beside `CFUs -> CFU`.

`ConceptStore.normalize` follows exactly one hop, so both shapes fail silently
rather than loudly: a chain half-lands the merge and leaves the store holding
both names, and a cycle renames each term onto the other so nothing merges at
all. `prune` did not catch either — it follows chains to decide whether an entry
can still fire, and a chain that fires is exactly what it keeps.

`TermMapper.resolve_chains` re-points every entry onto its concept's canonical.
*(Rewritten 2026-09-26 — see below; it used to WALK each chain to its terminal,
which was the wrong shape and could not finish.)* It runs in `run_build_term_mapping` BEFORE the adjudication, because
collapsing `A -> B -> C` onto `A -> C` creates a pair no model has been asked
about, and rule 18 says no mapping onto an existing class stands unasked. It
verifies its own write and raises rather than leaving the file in the state it
exists to end. A chain that terminates at an anchor the category guard refuses
for that term is withdrawn, not walked: the guard's refusal is not to be
delivered through the back door. On the live file this re-pointed 349 entries,
broke 1,444 cycles and withdrew 10, leaving 14,131.

It folds both sides (rule 13), because the store's lookup does: it tries the
exact spelling and then `normalize_term`. `deep partial thickness skin burns ->
deep partial-thickness burns` beside `Deep partial-thickness burns -> deep
partial-thickness burn wounds` is a chain that one capital letter hides from an
exact-string walk and does not hide from the store, which found it on the next
apply. Folding FINDS the component and never rewrites the label inside one:
`Povidone Iodine -> Povidone-iodine` is left exactly as written — the mapping's
spelling of a canonical is a decision, and dropping the entry would hand the
store the unhyphenated fallback.

**A component, not a walk** *(2026-09-26).* An entry says two spellings are one
concept, and that claim is TRANSITIVE: `A -> B` and `B -> C` say A, B and C are
one thing, so "where does A end up" is not a walk, it is "which spelling does
that one thing go by". Chasing the chain was the wrong shape and it showed —
the walk ran over FOLDED nodes while the fixed-point check ran over the RAW
mapping, so **2,206 entries whose first hop folded to one node were invisible to
the resolution and visible to the check**, and the function raised rather than
finishing. The mapping is now read as connected components, and a component
cannot produce a chain or a cycle because every member points at the same
winner in one hop and the winner points nowhere. Which spelling wins:

* **one sink** — a member nothing points out of — is the canonical the mapping
  already chose, and it is NOT re-elected. Re-ranking would rename canonicals
  the curator settled: `wounds -> Wound` beside `wound -> Wound` is a finished
  star with nothing to resolve.
* **no sink** is a cycle, and it elects by `canonical_rank`.
* **several sinks** is two spellings that fold together pointing different ways
  — `patient-reported outcomes -> patient-reported outcome` beside
  `Patient-Reported Outcomes -> patient-reported outcome measure`, 27 on the
  live mapping. Transitivity makes them one thing, so they elect, and the
  losers are REPORTED: if two sinks really are different concepts the fix is to
  refuse one of the edges that joined them, not to keep a chain.

Two shapes live inside a single folded node, where the component pass draws no
edge at all. A **cycle** there (`Co-assembly <-> co-assembly`, 874 after pass 0)
elects like any other. A **chain** there (`IL‑10 -> Il10 -> il10`, with a
non-breaking hyphen, the last one standing) flattens onto the node's sink. A
one-way entry between two spellings is neither, and stays.

A curator's entry is followed, not overruled. They said these two are one
concept; if the second has since moved, following it is what honours that.

Enforced by: `TermMapper._canonical`, `TermMapper.resolve_chains`,
`canonical_rank`; `tests/test_mapping_resolve_chains.py` (25 tests,
mutation-checked: no cycle detection, one hop only, guard ignored, no
verification, winner by min rank, dry run writing, union over exact strings or
not at all, the standing canonical re-elected, a cycle not elected,
target-only spellings given entries, the winner keeping its entry, refusals
ignored, a finished star resolved anyway, a contested component unreported or
elected arbitrarily, same-fold cycles or chains left alone, a one-way same-fold
entry treated as a cycle);
`test_the_singular_spelling_is_canonical_even_when_rarer`,
`test_an_anchor_stays_canonical_however_it_is_spelled`,
`test_the_rule_never_trades_one_concept_for_another`, and
`test_without_anchors_the_frequent_store_term_wins` rewritten onto a case pair so
it still tests frequency rather than this rule.

### 23a. A singular that will be WRITTEN is chosen; one that will be looked up may be guessed

*Added 2026-09-24, from the curator's review.*

`singular_candidates` returns TWO answers for the ambiguous `-es` branch and
says why: `buses -> bus` drops two characters because the singular ends in a
sibilant, `phases -> phase` drops one because it already ends in `e`, and the
surface forms are identical. `singularize` takes the first and its docstring
called the guess harmless — correct, and only correct, **because a key is only
ever looked up**. A lookup that misses costs a miss.

Rule 23 broke that premise without noticing. Moving the singular rule into
`ConceptStore.normalize` made `singular_spelling` — and through it `singularize`
— produce the store's NAMES. A guess stopped being tried and started being
written down. Measured on the 2026-09-24 store: **938 names across 96 head
nouns, 1,722 mentions**, in line to be renamed `cas`, `dos`, `phas`, `nurs`,
`caus`, `expens`, `respons`, `diseas`. None of it had happened yet, because the
store had been restored to its pre-apply state; `run_apply_mapping` would have
done it.

The curator found it from the other end, reviewing `case -> cases`: *"canonical
is always the singular, this should have been handled by the regex."*

So the two jobs are separate functions:

* **`singularize`** — the lookup singular. Unchanged, deliberately, so `fold`
  and every folded lookup, cluster and mapping built on it answer what they
  always answered.
* **`naming_singular`** — the singular to write. One answer, decided by group:
  `-ses`/`-zes` keep the `e` (`cases -> case`), `-ches`/`-shes`/`-xes` drop it
  (`searches -> search`), and stems that are already words are LISTED
  (`_ES_STEM_IS_SINGULAR`: virus, census, gas, bias, lens) because no suffix
  separates `virus` from `caus`. All-caps tokens are acronyms and are returned
  untouched — 275 all-caps heads in the store end in S, and the suffix rules
  were eating the last letter of `POSAS`, `ARDS`, `NIRS`, `KOOS`, `LEFS`,
  `ASES` and `SBSES`.

The general form: **when a function's answer changes from being tried to being
stored, its error budget changes with it.** A docstring saying "wrong guesses
are harmless" is a claim about the callers, and it expires when a caller
changes.

Enforced by: `label_match.naming_singular`, `_ES_STEM_IS_SINGULAR`, `_SIS_TAILS`
(the open-ended `-sis` compounds: `osteosyntheses`, `sub-analyses`, and a
`meta‑analyses` spelled with a non-breaking hyphen), the all-caps guard in
`singular_spelling`. `tests/test_naming_singular.py` — 61 cases, 8 mutations,
all caught, including one that changes `singularize` along with the naming rule.

## 24. The mapping has to survive being applied

*Decided 2026-09-07.*

`run_apply_mapping` must be runnable more than once, and a correction made to the
mapping afterwards must still reach the store. Neither was true.

`ConceptStore.normalize` title-cases the store and then, on the next run, looks
the title-cased name up in a mapping keyed by the raw extraction spelling —
exact-key lookup, one side normalised, which is precisely the failure rule 13
names. Measured on the live store: **12 of 3574 terms were an exact mapping key,
where 68 matched on a normalised one.** Four fifths of the mapping's reach was
gone and nothing said so. A whole re-run of apply → build → gate → merge
collapsed 0 terms and produced a byte-identical artifact, which is what made it
visible at all.

The lookup now tries the exact key first and falls back to `normalize_term` on
both sides. A normalised key claimed by two different canonicals is **reported**,
not silently resolved to whichever came first.

*Refined 2026-09-23: surviving being applied is not the same as being applied.*
`normalize` maps a name and THEN title-cases it, so the name a pass produces can
itself be a mapping key — or fold onto one — that the same pass has already
walked past. Measured on the 6,029-abstract store: pass 1 collapsed 12,912
names, pass 2 another **1,191**, pass 3 one more, pass 4 none. One call reported
a completed apply with 1,192 merges undone, and nothing said so.

`MappingCleaner.apply` now runs `normalize` until the store stops changing and
returns how many passes that took, saying how many rounds a single pass would
have left. Not converging within ten passes raises: a mapping still moving names
after ten rewrites has not been applied, whatever state the last pass left.

Enforced by: `MappingCleaner.apply`; `tests/test_mapping_apply_converges.py`
(four tests, mutation-checked: single pass, no raise, silence about the extra
rounds).

Enforced by: `ConceptStore.normalize`'s `canonical_of`;
`test_the_mapping_still_applies_after_the_store_was_normalized`,
`test_targets_are_remapped_after_normalization_too`,
`test_the_exact_key_still_wins_over_the_normalised_one`,
`test_a_normalised_key_claimed_twice_is_reported`.

## 25. The category vocabulary is spelled the way BFO spells it

*Decided 2026-09-08.*

The 15 BFO category names are `material entity`, `process boundary`,
`specifically dependent continuant` — lowercase, words separated by spaces,
identical to the labels BFO carries. They were CamelCase until today.

Rules 20 and 22 each fixed one consequence of that CamelCase by adding a guard.
The guards were right and they stay, but they were carrying the whole load, and
the reason is worth stating plainly: **CamelCase is the one spelling
`normalize_term` cannot express.** It lowercases, and it turns `-` and `_` into
spaces — but CamelCase has no separator to turn, so `MaterialEntity` came out
*welded* as `materialentity`, not *split* as `material entity`. Every comparison
downstream then had one side normalised and one side not, which is rule 13's
failure with no way to see it. Four separate defects, one mismatch:

| where | cost |
|---|---|
| `extend.resolve` reading a category as a label | 1770 classes with no path to BFO, under 5 minted duplicates of BFO classes |
| `store.normalize` writing a category name | reconciliation blind to 7 of 15 categories; clashes 12 → 40 |
| `base_hierarchy` / `store_categories` membership tests | the same blindness, once per consumer |
| `class_hierarchy` holding both spellings | `Material Entity` (17 curated edges) and `MaterialEntity` (1138 text edges) split BFO_0000040 in two, and the exporter merged them back every run |

In this spelling `normalize_term` is **idempotent** on every category name, so
the worst a missed guard can now do is change case — and case is what the guards
already tolerate. For **14 of the 15** the name is also the ontology's own label
for the IRI it declares, so a lookup that should never happen can no longer mint
a duplicate class even when it does. The guards stop being load-bearing and
become belt-and-braces.

The fifteenth is `information entity`, which declares BFO_0000031 — whose BFO
label is `generically dependent continuant`. That name is ours, chosen because
it is what the extractor is being asked to recognise and a model will not pick
"generically dependent continuant" for a measurement datum. The consequence is
narrow but real: for this one category the second safety net does not apply, and
the declaration is the only thing placing it. It is pinned as a named exception
so a sixteenth cannot appear quietly.

Two spellings are in play downstream and both are correct:

- the **store** holds the declared vocabulary, `material entity`;
- the **hierarchy** holds class labels, which it title-cases like every other
  label, so the same category reads back as `Material Entity` — which is also
  how the curated seed spells BFO_0000040's label. That is what makes the seed
  edge and the extracted edge one edge instead of two.

Recognition is therefore **separator-blind**, and lives in exactly one place:
`llm/category_vocab.py`. `declared_category` answers for any casing or
separator — `MaterialEntity`, `Material Entity`, `Materialentity`,
`material_entity` all return `material entity`. That is not fuzzy matching: it
answers only for a string that already *is* one of the fifteen, and it is what
lets a cache written before today keep reading correctly.

`ident()` in `wound_ontology/llm/schema_builder.py` is the one place the CamelCase
form is reconstructed, for Python and LinkML identifiers that cannot hold a
space. `BFOCategory.MaterialEntity` is a member name; `'material entity'` is its
value, and only the value is ever compared or stored.

Migration, measured (`scripts/migrate_category_vocabulary.py`, 2026-09-08):
**4175** store attributes rewritten across 3559 terms, **2** terms renamed
(`Function`, `Role`), 0 merges, 0 data collapsed; **2** unreachable mapping
entries withdrawn and **1** canonical re-pointed. The hierarchies, matrix and
FCA artifacts are derived and were rebuilt, not migrated (rule 6).
`pubmed_abstracts` is never touched — an abstract that says "the healing
process" is prose, and structure is the only thing that tells the two apart.

**The rebuild changed consistency, not structure, and that is the honest
result.** Because recognition is separator-blind, the pipeline already read the
legacy store correctly, so the measured state is identical either side of the
migration: 3859 WONT classes, 45 with no path to BFO, 1130 children on
BFO_0000040, 3 classes under two disjoint BFO branches, 3553 of 3559 terms given
a category. Two things did change, both internal:

| | before | after |
|---|---|---|
| BFO classes split across two spellings in `class_hierarchy` | 3 | **0** |
| folds reported at export | 20 | **17** |

The three folds that disappeared *were* those three classes: `resolve()` was
merging `materialentity` and `material entity` onto BFO_0000040 at export, every
run, and reporting it as a fold of two pipeline terms. It was never two terms.

Enforced by: `llm/category_vocab.py`; `tests/test_category_vocabulary.py`, in
particular `test_normalisation_leaves_every_category_name_alone` and
`test_a_category_name_is_the_label_the_ontology_carries` — the two claims the
rename rests on — plus
`test_a_cache_written_under_the_old_spelling_still_reads`.

## 26. A term the ontology has a class for is not methodology
*Superseded 2026-10-25 by rule 86: the lists and the Blocker are deleted; what they decided is a verdict in TermMappingAndGate.*


*Decided 2026-09-08.*

`METHODOLOGY_BLOCKLIST` exists to drop study-design vocabulary — "randomised
controlled trial", "inclusion criteria" — and `run_clean_store` **deletes** what
it matches rather than quarantining it. It had grown to hold **33** terms that
WONT or MILD assert a class for:

| term | class |
|---|---|
| `skin` | FMA_7163 |
| `gangrene` | HP_0100758 |
| `Staphylococcus aureus` | NCBITaxon_1280 |
| `Compression therapy` | WONT_0000077 |
| `Malignancy` | WONT_0000465 |
| `Pain management` | WONT_0000222 |
| …28 more | GO, DOID, HP, CHEBI, NCBITaxon, MILD, WONT |

Nothing reported it, because a deletion by blocklist looks exactly like a term
the abstracts never mentioned. Three were live in the store (`Compression
Therapy`, `Malignancy`, `Protein`); the rest were latent.

The criterion is the ontology's own testimony and nothing softer, which is why
it can be a test rather than a one-off tidy: **if a curated source asserts a
class with this label, the term is domain vocabulary.** Moving them is not
enough on its own — the **whitelist** is what frees a term, because
`Blocker.is_blocked` consults it before both the term and keyword lists, and
`pain management`, `patient education` and `painful` are caught by the
KEYWORD_BLOCKLIST entries `pain` and `education` as well. Those keywords stay:
`pain score` really is a study instrument.

Live store terms blocked: **9 → 6**, and the remaining six are ML methodology.

Six curated labels are still rejected, all by the **noise regex** rather than a
list: `NaCl 0.9%`, `NaCl 10%` and `Wagner and Anderson grade 1D`–`4D`, where the
`\d+ ... d|day|days` rule fires on the `D` of `1D`. `is_noise` runs *before* the
whitelist, so a heuristic currently outranks an explicit human decision and
whitelisting cannot free them. Latent — 0 live store terms match the noise regex
— and pinned in `NOISE_FALSE_POSITIVES` so the gap is named rather than
rediscovered.

**Closed 2026-09-09 by rule 28.** The precedence was inverted, so a whitelist
entry now does reach these, and the `\d+ … d` rule was narrowed so a grade code
is not read as a duration. The four Wagner labels are freed by the narrowed
rule, the two NaCl labels by an explicit entry, and the exception list is now
`NOISE_MATCHED_BUT_WHITELISTED` and holds two rather than six.
`test_no_curated_class_label_is_blocked_in_effect` carries no exclusion list at
all any more: **no curated class label is blocked, full stop.**

Live store terms blocked went **6 → 13** the same day, and none of the seven is
a regression — every one is study methodology that a broad whitelist keyword had
been waving through (rule 29).

Enforced by: `tests/test_blocklist_respects_the_ontology.py`, in particular
`test_no_curated_class_label_is_blocked_in_effect`.

## 27. A name is matched whole, never as a substring
*Superseded 2026-10-25 by rule 86: the lists and the Blocker are deleted; what they decided is a verdict in TermMappingAndGate.*


*Decided 2026-09-08.*

This is the third time the same bug has been written in this codebase, so it is
now a rule. (A fourth turned up on 2026-09-09, in the row added below — the rule
was already in force by then, which is what made it findable.)

| where | the loose match | what it cost |
|---|---|---|
| `KEYWORD_WHITELIST` | `cti` matched inside a word | 287 of 3725 store terms whitelisted by coincidence — "practices", "mortality prediction" |
| `_cleanup_old_files` | `class_hierarchy_*` also matched `class_hierarchy_provenance_*` | the matrix files were always the ones deleted; the cache held 0 of them and 10 provenance files |
| `term_lists._find_block_end` | `var_name in line` matched `WHITELIST` inside `KEYWORD_WHITELIST` | every add and remove aimed at WHITELIST landed in the keyword list |
| `BlockList.assign_cluster` | `kw in lower`; `rct` matched inside "infa*rct*ion" | "myocardial infarction" filed under "Study design & trial types" — found 2026-09-09, fixed the same day |

The third is the worst of the four, because the two lists behave differently: a
keyword list matches on a word *inside* a term, so `skin` written there exempts
`skin graft`, `skin substitute` and everything else containing the word. The
list silently widens far past what was curated, and the curated list it was
meant for stays empty.

**Anchor the match.** A variable name matches a declaration, a prefix matches a
filename stem, a keyword matches on word boundaries. Where two names are in play
and one contains the other, assume they will be confused unless something stops
it — and prefer the check that cannot be written loosely over the one that
happens to be written correctly today.

Enforced by: `term_lists._declares`;
`TestListNameIsMatchedExactly` in `tests/test_term_lists_and_blocker.py`.

## 28. An explicit decision outranks a heuristic

*Decided 2026-09-09.*

`Blocker.is_blocked` used to consult the noise regex before the whitelists. A
curator could not, therefore, overrule it. `NaCl 0.9%` (WONT_0000208) and
`NaCl 10%` (WONT_0000209) are curated classes and the `\d+ %` rule rejected
both; the only available remedy was to weaken the rule for every term in the
corpus, so that one decision about two concepts had to be paid for by every
other term. Four more curated labels — Wagner and Anderson grades 1D to 4D —
were rejected by the `\d+ … d` rule reading a grade code as "1 day".

The order is now: **whitelist, then heuristic, then blocklist.** `is_noise` is a
guess about the shape of a string; a whitelist entry is a decision about a
concept, and the decision wins. The heuristic keeps deciding everything nobody
has ruled on, which is nearly all of it.

The cost is real and is the intended trade: the whitelists now carry the whole
burden of being right about what they exempt, where before the regex was a
backstop under them. That is the correct place for the burden — a whitelist
entry is written by a person and can be pointed at.

Note what this does *not* license. The four grade codes were fixed by narrowing
the regex, not by whitelisting them: a rule that is wrong should be corrected,
and the exception list is for the cases where the rule is right in general and
wrong here. Measured over the 4104 store terms and curated labels, the bare `d`
alternative matched those four and not one genuine day expression.

**When you narrow a heuristic, pin the price.** Requiring a separator means
`7d` written closed up is no longer read as a duration. That is recorded as
`test_the_price_of_narrowing_the_day_rule`, so it is a decision on the record
rather than a discovery later. The asymmetry settles which way to err: a term
wrongly let through reaches the store and can still be blocked, while
`run_clean_store` **deletes** what the blocklist matches.

Enforced by: `Blocker.is_blocked` and `Blocker.score`, which duplicate the
ladder and must move in step (`test_score_and_is_blocked_agree_about_precedence`);
`test_a_whitelist_entry_outranks_the_noise_regex`;
`test_a_grade_code_is_not_a_duration`.

## 29. An entry belongs in the list whose matching rule it can carry
*Superseded 2026-10-25 by rule 86: the lists and the Blocker are deleted; what they decided is a verdict in TermMappingAndGate.*


*Decided 2026-09-09.*

There are four curation lists and two matching rules. A **keyword** list fires
at a word start *inside* a term; a **term** list matches the whole string. An
entry filed under the wrong rule does not merely sit in the wrong place, it
means something different.

`KEYWORD_WHITELIST` had drifted into a term list wearing a keyword list's coat:
1600 of its 3186 entries were three words or more and the longest was twenty
words, because the substring bug in rule 27 sent every interactive write for
`WHITELIST` there instead. Measured across the 3559 live store terms and 550
curated labels, `wound` used as a keyword exempted 311 terms — which is how
"Wound Reporting In Animal And Human Preclinical Studies Reporting Standards"
walked past the `reporting` keyword. Of the whole 4104-term universe only 27
were candidates for blocking at all, 21 were vetoed by a whitelist, and 5326 of
the 5336 whitelist entries were the sole protector of nothing. The whitelist had
quietly switched the blocklist off.

Three shape rules, all checkable, all enforced:

1. **A keyword is short.** Three or more words is a phrase, and a phrase used as
   a keyword exempts everything containing it. It belongs in the term list.
2. **No keyword is covered by a shorter keyword.** It cannot change any outcome:
   if `short` starts a word inside `long`, then every term `long` reaches,
   `short` reaches too. Compute redundancy against the list that will *exist*,
   not the one that does — `wound bed` is redundant with `wound` only until
   `wound` is demoted.
3. **Nothing is on a whitelist and a blocklist at once.** `antimicrobial` and
   `dressing` sat on `METHODOLOGY_BLOCKLIST` and survived only by the accident
   of also being broad whitelist keywords.

**Do not judge a preventive list by its size.** 58 of the 69 `KEYWORD_BLOCKLIST`
entries match nothing in the corpus, and that is the *success* state: they match
nothing because they already worked, and the list is what stops those terms
coming back. This is not rule 19, where the mapping was pruned because its
targets no longer **existed** — a term that has not appeared yet is a different
claim from a target that is gone. Judge shape, never count.

Enforced by: `tests/test_curation_list_shape.py`.

## 30. A write to a config file is verified, never assumed
*Superseded 2026-10-25 by rule 86: the lists and the Blocker are deleted; what they decided is a verdict in TermMappingAndGate.*


*Decided 2026-09-09.*

The five curation lists persist themselves by rewriting a Python set literal in
place. `add` and `remove` returned a count and nobody checked it against the
file. Two of the five could not be removed from at all:

`_pylist_remove` deletes a line only when that line holds exactly **one** quoted
value. `KEYWORD_BLOCKLIST` (69 entries on 27 lines) and `SUSPICIOUS_KEYWORDS`
(84 on 29) were written several entries to a line, so the value it sliced out
was `regression", "propensity", "logistic` and matched nothing. **Removing from
either removed nothing, returned 0, and said nothing** — while *adding* worked,
because the writer appends one entry per line. Block a keyword interactively and
you could not unblock it. The asymmetry is what kept it invisible.

A second defect of the same shape sat underneath: the slicing was
`line.strip().rstrip('",').strip('"')`, so the one `METHODOLOGY_BLOCKLIST` entry
containing quotes — `"long hu hui" pi risk management platform`, stored escaped
— never matched either. And the writer built its line with an f-string, which
would have emitted **invalid Python** for that same term.

Three rules, in order of how much they buy:

1. **Verify the write.** After `add`, every requested term must be in the
   reloaded list; after `remove`, none of the terms that *were* present may
   remain. Set membership, not a count — a value written on two lines costs two
   line removals for one term, and `wound` and `burn` both were. A removal of a
   term that was never there stays a quiet no-op, because that is legitimate and
   is the normal case in `_save_review_results`.
2. **Parse, do not slice.** `ast.literal_eval` for reading an entry,
   `json.dumps(..., ensure_ascii=False)` for writing one. Hand-rolled quote
   surgery is how both defects above were written.
3. **One entry per line, in every literal.** The format the parser can act on.
   Enforced directly, so a list cannot drift back into a shape that silently
   disables half its own API.

The verification lives once, in `BaseList`. The five concrete classes had held
byte-identical copies of `add` and `remove`; duplication is what lets one copy
drift, and it would also have made this guard five things to keep in step.

Related: rule 27 (a name is matched whole) is the same failure at the level of
*which* list gets written; this is the same failure at the level of *whether*
the write happened. Both were invisible because a wrong write and a skipped
write look identical from the return value.

Enforced by: `BaseList.add`, `BaseList.remove`, `BaseList._write_failed`;
`test_a_removal_that_cannot_land_raises_instead_of_returning_zero` and
`test_an_add_that_does_not_land_raises` in `tests/test_no_silent_failure.py`;
`test_every_list_literal_is_written_one_entry_per_line` and
`test_a_config_module_holds_lists_not_matching_logic` in
`tests/test_curation_list_shape.py`;
`TestEveryListCanActuallyBeRemovedFrom` in
`tests/test_term_lists_and_blocker.py`.

## 31. A determinate quality belongs to the class it defines, not to its parent

*Decided 2026-09-10.*

A quality attaches to the class it is actually true of. Two shapes, and only one
of them belongs on the parent:

- a **determinable** — `color`, `wound area`, `wound healing time` — is true of
  the parent. Every wound has *some* area, without that fixing which.
- a **determinate** — `reddened`, `macerated`, `chronic` — is true only of the
  subclass it defines, and belongs there. Test: *if X were not <quality>, would
  it still be a Y?* If no, the quality defines Y and belongs on Y.

WONT already carries this pattern ten times, in the shape
`Reddened wound edge ≡ Wound edge ⊓ has_quality some reddened`, with `reddened`
under PATO_0000014 `color` and `macerated` under `degree of maceration`. It also
carries a history-grounded determinate, `human ⊓ has_quality some PATO_0001764
increased age`, which settles the objection that a quality has to be readable at
an instant: that criterion separates quality from **disposition** (WONT says so
itself on `degree of wound pain`: *"There is always some degree of pain inhering
in the patient, which is what makes this a quality rather than a disposition
waiting to be realized"*), not quality from process-historical property.

The failure this prevents. `PREDICATE_DEFINITIONS["has_quality"]` taught the
extractor one example, `Chronic Wound has_quality Chronic`, and no rule about
where a determinate attaches. The result was measured on the live store:
`has_quality: chronic` exists on exactly **2 of 4150** entity-attribute pairs,
and in the Wound-subtree FCA context it became a column that is `True` for one
object and undecided for the other **39** — every undecided cell in a 40×16
matrix, and the sole reason 9 of 11 lattice concepts were withheld as
undecided-dependent. A determinate with no home is not a harmless extra column;
it is the only column carrying discriminating power, left unusable.

The correct repair is *not* to delete the attribute. It is to give the
determinate a class to be (WONT_0000442 `Chronic wound` has no defining axiom
and there is no `chronic` quality class), and to decide the column across the
subtree. Deleting it leaves the context with three determinables that are true
of all 39 objects, so the lattice can only re-derive the taxonomy it was handed.

Enforced by: `PREDICATE_DEFINITIONS["has_quality"]` in `config/settings.py` —
its `no` list names both errors (a determinate on the parent, a determinable on
the class a determinate defines) and carries the test above.

Related: rule 20 (a BFO category is declared, never matched) is the same
instinct one level up — where a thing sits is stated, not inferred from how it
looks.

## 32. A snapshot of the ontology checks its own age before it is used

*Decided 2026-09-12.*

Two pipeline files are derived from WONT + MILD and consumed instead of them:
`output/owl/skeleton_tbox.ttl` (what both reasoner gates reason over) and
`config/extraction_schema.yaml` with its generated `extraction_models.py` (what
every abstract is prompted with). Each is a **snapshot**, and a snapshot is
correct only while its sources have not moved. So the step that consumes one
compares modification times first and rebuilds if any source is newer — the
consumer asks, not the person who last edited the ontology, and not a
checklist.

The rule has three parts:

- **The consumer checks, not the producer.** The check runs where the snapshot
  is read (`Orchestrator.build_reasoner_skeleton`, called from
  `reasoner_gate`; `schema_builder.ensure_current`, called first thing in
  `run_extract_to_store`), because a producer that is never run cannot check
  anything.
- **Every source counts.** The schema resolves a class's BFO category through
  the import modules, so the modules directory is a source, not only WONT and
  MILD. Missing a source and calling the snapshot current is the failure in a
  new coat.
- **A rebuild that changes nothing does not dirty the tree.** The generated
  files carry a date stamp; a rebuild that differs only there is a no-op, and
  the outputs are touched, not rewritten — otherwise every WONT save would
  produce a spurious diff and the real regenerations would drown in it.

The failure: `skeleton_tbox.ttl` was found on 2026-09-10 to be **fifteen days**
older than WONT, with both gates reasoning over the old one and nothing said.
The schema had the same hole, measured in sync on 2026-09-12 only because
nobody had edited WONT since the last hand regeneration on 2026-09-08 — and
WONT_TODO E was about to add fourteen classes.

One consequence is deliberate: the generated Pydantic module is Python, already
imported by eight modules when extraction starts, and an enum cannot be swapped
under them. A rebuild that changed content therefore **stops the process** with
an instruction to restart, rather than extract with the old schema and mention
the new one. Extraction is the expensive, never-repeated step; running it
against a WONT that no longer exists is the one thing this rule exists to
prevent.

Enforced by: `tests/test_extraction_schema_freshness.py` (14 tests) and the
skeleton tests in `tests/test_no_silent_failure.py`.

## 33. The store is the one record; a rejection is a verdict in it, never a deletion

*Decided 2026-09-12, on Moritz's instruction: "Store is the sole truth. All the
others are just views."*

`concept_store_*.json` is the only record. The hierarchies, the context
matrix, the lattice and the OWL are views rebuilt from it (rule 6), and the
curated lists and the mapping are *inputs* to decisions about it. So a
decision about an assertion lives **in the store, beside the assertion**,
under the reserved record `decisions`:

- `entity_verdicts` — a whole term rejected: `{status, by, when, note}`
- `cell_verdicts` — one `(entity, triple)` rejected, across every document
  that asserted it
- `renamed` — what the mapping turned a label into, and when

Nothing an abstract said is ever `del`-ed. Three consequences:

- **One reading.** `effective_records()` in `concept_store.py` is the only
  function that applies verdicts, and every reader — the hierarchies, the
  matrix, the cleaner's scans, the gate adapter — goes through it, whether it
  was handed a `ConceptStore`, a fake with a `.dict`, or the raw dict. A
  verdict is honoured everywhere or nowhere. The `decisions` record carries no
  `entities` key on purpose, so a legacy `rec.get("entities", {})` sees
  nothing there.
- **Authored, so liftable.** Every verdict names its author (`blocklist`,
  `predicate_filter`, `prune`, `reasoner_gate`, …). `StoreCleaner.clean()`
  lifts its own earlier verdicts before deciding again, so a term whose list
  entry was withdrawn comes back; `run_gate_store_relations` lifts the gate's
  and re-tests every relation against the skeleton as it is *now* — and puts
  them back if the gate cannot run, because a skipped gate must not un-vet the
  store.
- **Undecided needs no mark.** A cell with an assertion and no verdict stands;
  a cell with no assertion is undecided (rule 10). Only rejection is written.

The failure: the 606-abstract extraction of 2026-09-10/11 had **278 entities
removed by the blocklist mid-run** (the milestone callback), visible only in
`pc_extract.log`; the reasoner gate's quarantine lived in a gitignored
directory; and the store on disk was a pure raw record (22,280 cells, all
`1.0`, no synthetic records) only because nothing past step 3 had run on it
yet. Those 278 cannot be restored — there is nothing to lift.

Measured on the switch: the effective view of the live store equals the raw
one cell for cell (22,280 = 22,280), so no downstream view moved.

Enforced by: `tests/test_store_verdicts.py` (16 tests; five mutations fail by
name — ignoring cell verdicts, a gate that skips without restoring, a cleaner
that does not lift, a normalisation that drops the verdicts' names, a gate
that does not re-hear its own verdicts).

## 34. An external term reaches the closure through a module, never through a direct import of its source

*Decided 2026-09-12.*

A curated file (WONT, MILD) imports MILD's modules and nothing else. When a
new external term is needed — a PATO determinate, a UBERON site — it is used
in the curated file and the modules are regenerated
(`../Disease ontologies/build_disease_proposal.sh --no-reason`); the module
then carries the term with its label and the axioms that ground it under BFO.
No `owl:imports <http://purl.obolibrary.org/obo/.../releases/.../x.owl>` in a
curated file, ever, and no module is hand-edited (the one exception,
`go_module.owl`'s property labels, is why the script leaves `go/chebi/dron`
alone unless told otherwise).

Two failures behind this. First, the hand edit of 2026-09-12 added a direct
import of the full `pato.owl` (21 MB, 259,922 triples) to WONT so that five
PATO classes would resolve in Protégé. The pipeline never follows a curated
file's imports (the skeleton strips them; the schema builder reads the
modules), so the five classes were invisible to every gate, and the module
build script would have seeded the whole of PATO into every module. Second,
the modules themselves had been over-extracted since June: `obi_module.owl` was
16.3 MB with 5,549 classes and 29 roots beside `entity`, none of the debris
referenced by WONT or MILD. Measured cause: a STAR extraction over a merge
that contains full `pato.owl` runs away (0.9 MB without it, 15.2 MB with);
seeding `unit` into `uo.owl` pulls in all 518 units. The fix is in the script
(FIX 3): PATO is BOT-extracted alone and *that* joins the joint STAR; DOID and
HP are MIREOT paths; `unit` is a label stub. After: 34,071 triples in the
closure, 1,174 classes, 3 foreign roots, schema rebuild 33 s → 2.6 s.

The rule cuts both ways: a module must carry **everything** the curated
files reference, with a label — the build is wrong if any external class used
by WONT or MILD comes out unlabelled — and **nothing** they do not.

*Refined 2026-09-17 — we author axioms about our own classes only.* A module
carries an external term with exactly the superclass path its owner states;
neither the build script nor MILD nor WONT adds a `subClassOf` to a class
another ontology owns, however tidy it would make the closure. Where an
owner does not place its root under BFO — `DOID_4 disease`, `UO_0000000
unit`, `FMA_62955 anatomical entity` — that root stands beside `entity`, and
the MILD header says so. The two FMA grounding axioms the build had added on
2026-09-16 were removed for this reason; the HP path that remains is quoted
from `hp.owl` and `upheno.owl`, with the citation in the script. Moritz's
wording: "we manipulate our own ontologies, not somebody else's."

Enforced by: `build_disease_proposal.sh` refuses to run if WONT or MILD
imports a release ontology directly, and aborts if the joint module exceeds
3 MB; `schema_builder.stale()` lists every module as a source, so a
regenerated module regenerates the schema (rule 32).

**Refinement, 2026-09-17 (evening): no definitions on foreign classes,
either.** The same ownership applies to annotations: neither WONT nor MILD
carries an `IAO_0000115` definition for a class it does not own. A copied
definition is a second source for the same text (it drifts from the owner's
release and the module already carries the owner's), and a written one puts
words in another ontology's mouth. Sixty-five such definitions were found in
WONT on 2026-09-17 — every one a duplicate of what the module carries — and
removed; a foreign class in a curated file is a bare declaration (a stub the
module fills in), plus at most a `skos:relatedMatch` or an `rdfs:comment`
explaining a bridge. Moritz's wording: "never write definitions for foreign
classes, so nor MILD nor WONT."

## 35. A complication is a disorder put out by a process of another disease's course — never a relation between two disorders

*Decided 2026-09-17, with Moritz.*

The shape, used for every aetiological wound class in WONT:

```
X wound ≡ Wound ⊓ output_of some (Wound development process
                                   ⊓ has_part some Wound causing X process)
Wound causing X process ≡ X disease process ⊓ Wound causing process
```

`output_of` is RO_0002353, not OBI_0000312 `is_specified_output_of`: a
wound development process is not a planned process, and *specified* output
belongs to planned processes only (classification and diagnostic results
keep OBI_0000312). The causal order lives in the processes, where MILD
licenses it (commitment 4; MILD_120053 "disease course process putting out
disorders as part of a complication"); no causal relation between the two
disorders is asserted, and none is needed.

The failure this replaces. From June to 17 Sep five classes said
`Wound ⊓ part_of some (material disease entity ⊓ has_part some <disorder>)`
and were labelled *co-located with*. Read against MILD's own definition —
"which disorders compose one disease is fixed by the diagnostic
classification assigned to them, not by an intrinsic unity criterion" — that
axiom asserted only that a diagnostic classification files the two under one
disease. It said nothing about mechanism, and its name promised a spatial
adjacency (definitions even said "in the same limb") that the logic never
stated. Moritz's objection that made this visible: a plaque in the iliac
artery and an ischaemic ulcer on the toe share no material entity, yet the
ulcer is plainly a complication of the arteriopathy. The complication
pattern says exactly that; co-location could not.

The five classes are `Angiopathic wound`, `Autoimmune disease related
wound`, `Diabetic wound`, `Venous insufficiency wound` (was *Wound
co-located with impaired venous backflow*) and `Arterial insufficiency
wound` (was *… impaired arterial inflow*); `Traumatic wound`, `Thermal
wound`, `Malignant wound` and `Pressure ulcer` already had the shape. The
competency predicate `co_located_with` became `complication_of`, evaluated
by `complication_holds()` in `evaluation/competency.py`.

Enforced by: `tests/test_competency.py::test_complication_is_not_vacuous`
(the three ways a process can be "of" a disease — subclass, has_participant,
direct output — and two refusals; mutation-checked).

## 36. The ontology's own label is the canonical, and every identity claim faces the guard

*Decided 2026-09-23, by the curator: "the ontology's own label always wins."*

Where a canonical names a class that WONT or MILD already has, the canonical is
that class's **own spelling**. The mapping held `Necrosis Process -> necrosis`
where WONT spells it `Necrosis`, `debridement surgery -> surgical debridement`
where it is `Surgical debridement`, `wounds -> wound` where it is `Wound`: 88
entries canonicalising an existing class under a spelling the class does not use.
Downstream each one mints a twin of a class that already exists, which is the
failure the anchors were introduced to prevent.

**The rule is also what makes the category guard work.**
`_category_compatible_mapping` refuses a merge whose two sides sit in disjoint
BFO branches, and it is consulted only for ANCHORS — the ontology labels that are
**not** also store terms. So it went quiet exactly when a class label was common
enough in the corpus to be extracted: `Necrosis Process` [process] ->
`Necrosis` [material entity], the pair its own docstring names as its reason for
existing, was never once put to it. Measured on the 2026-09-22 mapping: five such
merges, two of them the docstring's own examples, and `Necrosis Process` had
already been applied to the store.

Two changes make the guard see it. Its lookup of the class's category **folds**
(exact spelling first, then `normalize_term`), because it is consulted with
whatever spelling the mapping carries and `necrosis` resolved to nothing at all —
which the guard reads as "no information" and allows. And the canonical is
re-spelled to the class label, which also turns a store-to-store merge into the
anchor mapping it always was.

Only `rdfs:label` is re-spelled onto, never an alt term. WONT's alt terms are
largely HISTORICAL labels: the 17 Sep renaming moved 31 classes to "… plan
specification" and kept the old names as alt terms, so `Negative pressure wound
therapy` is an alt term of `Negative pressure wound therapy plan specification`
and also the plain name of the therapy process. Resolving alt terms to their
class's label moved store terms for the THERAPY onto the PLAN SPECIFICATION, an
information entity — 101 re-spellings, the first three exactly that. An alt term
is how the lexicon FINDS a class; it is not a name to rename onto. Where two
classes answer to one folded name (DOID's `necrotizing fasciitis`, WONT's
`Necrotizing fasciitis`), ours wins; without a rule the winner came out of dict
order and flipped between runs. Only a **content**
difference is put to the guard (`label_difference`, the partition the adjudication
already uses): asking it about `Pressure ulcers -> Pressure ulcer` refused 19 good
inflections whose store typing happened to be contradictory.

Two neighbours of the rule, both measured the same day:

* **A blocked name is never quietly made a canonical.** The methodology blocklist
  is applied at extraction, by exact lowercase name, and never again — while rule
  23 makes the canonical singular. `patients` is not on the list and `patient` is,
  so the mapping renamed the survivor back onto the blocked name: **462 store
  names arrived that way carrying 7,201 mentions**, which `run_clean_store` would
  remove along with everything merged into them. The pass does not repair this —
  withdrawing would leave the variant standing as its own concept, and whether the
  list or the merge is wrong (`intervention` yes, `tissue repair` almost certainly
  not) is a `review_lists` decision. It reports them, with counts, as a work item.
* **Re-spelling can turn an entry into an identity** (`Wound -> wound` becomes
  `Wound -> Wound`); rule 19 removes those. Exactly equal, not folded:
  `Povidone Iodine -> Povidone-iodine` folds to itself and is still doing work,
  because without it the store falls back to `normalize_term` and loses the hyphen.

Enforced by: `TermMapper.enforce_canonical_policy`,
`Orchestrator.ontology_label_spellings`, `Orchestrator.blocked_names`, called from
`run_build_term_mapping` between `resolve_chains` and the adjudication — before it,
because re-spelling creates pairs no model has seen (rule 18).
`tests/test_ontology_anchors.py::test_the_guard_knows_the_class_under_the_store_s_spelling`
(mutation-checked against an exact-only lookup), and
`tests/test_canonical_policy.py` (eleven tests, mutation-checked: no re-spelling,
guard not consulted, guard asked about inflections, blocked canonical ignored,
case-sensitive block, identity folded instead of exact, verification removed, dry
run writing).

## 37. The mapping is a record, and a refusal is a verdict in it

*Decided 2026-09-24, from the curator's question: "why does it have to be a
separate csv? why not just more data in the mapping dict?"*

Everything known about one mapping entry used to live in four artifacts: the
decision in `term_mapping_*.json`, the model's verdict in
`mapping_adjudication_*.json`, the second opinion in
`mapping_second_opinion_*.json`, the flags and the curator's marks in a review
CSV. Three of those are derivable. **One was not, and it was being thrown away.**

`withdraw()` deleted the entry. Nothing recorded that a human had refused it or
why, so the next `build_from_embeddings` re-proposed the merge, the adjudication
cache answered `same_class` for it from memory, and the refusal was gone. The
category guard's refusals survived a rebuild -- they are re-applied every build
from `refused_mappings` -- and the curator's did not. An evening of review,
erased by the next run of a step that runs whenever the store changes.

This is rule 33 (the store is the one record; a rejection is a verdict in it,
never a deletion) applied to the artifact it had never been applied to.

The file now holds one RECORD per term:

```
{"to": "Wound", "method": …, "confidence": …,
 "pass1": {"verdict": …, "reason": …},      # what the model said, with the
 "pass2": {"verdict": …, "reason": …},      #   ontology's definitions / with categories
 "curator": {"verdict": …, "reason": …, "when": …},
 "refused": {"material entity": {"reason": …, "by": "curator", "when": …}}}
```

Four things make it safe to do this to the most-read file in the pipeline:

1. **`data` stays `dict[str, str]`.** It is a projection over the records, so
   `ConceptStore.normalize`, `DataFrame.rename` and every caller of
   `TermMapper.mapping` are untouched. The format change stops at `TermMapping`.
2. **A refused term is absent from the projection**, exactly as a deleted entry
   used to be, so nothing downstream can act on a refusal by accident.
3. **`refused` is keyed by CANONICAL, not by term.** Refusing `materials ->
   material entity` must not stop `materials` ever mapping onto anything.
4. **The old flat file still loads** and is migrated in memory, written as
   records by the next save. A migration that has to be remembered is one that
   gets forgotten.

`remove()` still exists and still deletes, for entries that can no longer do
anything -- identities, dead targets, inert spellings (rules 19 and 23). The
distinction is the point: **a mechanical prune deletes, a decision is recorded.**

> **Superseded in part by rule 38 (2026-09-24.)** The record now keeps every
> verdict under the CANONICAL it is about (`pairs`), not at the term level, and
> `remove()` became `retire()`: a mechanical prune unmaps the entry and keeps
> the record, because deleting it also threw away model verdicts the pair had
> cost credits to obtain. What rule 37 decided -- a decision is a verdict, never
> a deletion -- is unchanged and is what rule 38 extends.

Enforced by: `TermMapping.refuse` / `is_refused` / `record`,
`TermMapper.refuse`, the standing-refusal check in
`TermMapper.build_from_embeddings`, and the verification in
`scripts/apply_review_sheet.py` that every refusal it applied reads back as
recorded. `tests/test_mapping_prune.py::test_a_curator_refusal_survives_the_next_build`,
`::test_a_refusal_is_about_the_pair_not_the_term`,
`::test_the_old_flat_file_still_loads` — mutation-checked against a build that
ignores standing refusals, a refusal keyed by term, a refusal that leaves the
entry mapped, and a flat file that is not migrated.

## 38. The mapping file is the ground truth; everything else about the mapping is a view

*Decided 2026-09-24.*

`TermMapping` holds one record per term carrying **everything** anyone ever
decided about it, and every other artifact about the mapping is COMPUTED from
those records on demand. Nothing about a mapping is stored twice.

```
"debridement": {
  "to": "Debridement process", "method": …, "confidence": …,
  "retired": {"reason": …, "when": …},          # unmapped mechanically
  "pairs": {                                     # keyed by CANONICAL
     "Debridement process": {
        "pass1":   {"verdict": "same_class", "reason": …},
        "pass2":   {"verdict": "same_class", "reason": …},
        "curator": {"verdict": "refused",    "reason": …, "when": …},
        "refused": {"reason": …, "by": "curator", "when": …}},
     "Wound care process": {"pass1": {"verdict": "different", "reason": …}}}}
```

The views, all recomputed per call, none stored: `data` (the live
`term -> canonical` every consumer uses), `pass_cache(name)` (the adjudicator's
cache interface), `verdicts(name)`, `judged(name)`, `subsumption_candidates()`,
`disagreements()`, `metadata`, `standards`, `originals`.

**The failure.** `mapping_adjudication_*.json` (pass 1) and
`mapping_second_opinion_*.json` (pass 2) were the model's memory across builds.
Rule 37 then copied each verdict onto the record as well -- two homes for one
fact, two writers, nothing keeping them equal. Three things were wrong with the
split, all measured on the 2026-09-24 file:

* **2,548 of the 7,224 judged terms were not in the mapping at all.** Their
  verdicts existed only inside a cache file nothing downstream reads. A term
  re-proposed by a later build would find its own verdict — but a curator
  reading the record would not.
* **192 terms had been judged against more than one canonical.** `pass1` on the
  record could only hold one of them, so the record's copy was lossy by
  construction, and a verdict about `materials -> material entity` said nothing
  about `materials -> Wound dressing material` while sitting where both would
  read it.
* **`mapping_subsumption_candidates_*.csv` was written from the RUN, not the
  record.** 979 pairs stand judged `narrower`/`broader`, but a build writes only
  what it re-asked: the 2026-09-21 build wrote 960 rows and the 2026-09-22 build
  wrote 8, because the other 952 were answered from the cache and so were never
  in that run's report. Candidate subsumption edges, still true, silently absent
  from the artifact whose whole job is to carry them.

**The rule in practice.**

1. A verdict is written where the decision lives. `pass_cache(name)` is a
   `MutableMapping` over the records keyed `term \x1f canonical`
   (`mapping_adjudicator.pair_key`, one implementation, imported by both). A
   cache MISS must not create the record it missed.
2. `readjudicate` stops the cache READING, not writing — every pair is asked
   again and the new answers still land on the record.
3. A mechanical prune RETIRES: `to` becomes `None`, a `retired` reason is
   stamped, and every verdict stays. `forget()` deletes outright and nothing in
   the pipeline calls it.
4. A write that would overwrite a standing refusal does not happen silently:
   `add` raises (`override=True` is the deliberate reversal, and it clears the
   refusal), `add_batch` skips and RETURNS the skipped pairs, and every caller
   prints them.
5. An artifact derived from the mapping is written from the view, so it carries
   the whole record and not one run's worth of it.

Enforced by: `wound_ontology/mappers/term_mapping.py` (the record and every
view), `mapping_adjudicator.pair_key`, `Orchestrator._adjudicate_anchor_mappings`
(which no longer loads or saves a cache file),
`scripts/p4_fold_caches.py` (the one-time import, verified by reading back from
disk). `tests/test_mapping_ground_truth.py` — 29 tests, mutation-checked against
a cache miss that creates records, verdicts left at the term level, a retire
that deletes, an `add` that ignores a refusal, an `add_batch` that writes one, a
subsumption view built from one pass or one run, an `import_pass` that
overwrites a conflict, and a second key format.

## 39. A review carries the curator's decision exactly, or it refuses to carry it

*Decided 2026-09-25.*

A review sheet is the one place a human's judgement enters the pipeline. Every
step between the box they typed in and the record must be faithful or loud.
Rehearsing the 2026-09-24 review — 1,612 families decided on a phone — against
the real data found three ways it was neither.

1. **A target that does not read as a LABEL is refused, not written.** The
   curator typed `wound healing is a class in the onto and everything should
   merge into that` into "where does this belong instead". Applied as typed it
   would have minted a 74-character class name and pointed 995 mentions at it,
   and nothing downstream could have caught it: `add` takes any string, and a
   canonical nobody recognises looks exactly like one nobody has curated yet.
   `review_ui_pull.label_shaped` rejects a target over eight words or holding a
   finite verb; the run stops and names the family. `--resolve INDEX=VERDICT`
   is how the reading is then recorded, with the original words kept in `why`,
   because reading prose is an interpretation and the record should show it.

2. **A decision on a family reaches the CANONICAL too.** 18 of the 19 re-points
   in that review were a plural canonical being singularised. Moving only the
   members left `silver-containing dressings` standing beside
   `silver-containing dressing`, still holding its own mentions — the decision
   defeated by the shape of the sheet. `expand_families` adds the canonical as a
   member whenever a correction MOVES the family, and only then: `y` and `n`
   change no mapping, and a canonical is the target of its pairs, not one of them.

3. **A correction that names two terms is not a reversal.** Case-insensitive
   matching exists so a curator can type a name back by hand. `type 2 diabetes`
   gathers both `Diabetes Mellitus type 2` and `diabetes mellitus type 2`, and
   the correction `Diabetes mellitus type 2` named both — so both rows read
   themselves as the chosen one and each wrote an inverse entry for the same
   canonical, the second overwriting the first. Two spellings cannot both be the
   name typed back, so the fallback fires only when it identifies ONE, matching
   is scoped to the family, and anything else is a re-point onto what the
   curator actually wrote, reported by name.

4. **A sheet cell says what it says.** `N/A -> NA` and `Na+ -> NA` are live
   mapping entries, and pandas reads `NA`, `N/A`, `None`, `null` and `nan` as
   missing by default. Family 3200 showed in the UI with no canonical and no
   terms, and `.fillna("")` would have applied any decision on it to the empty
   string. Every script that reads a review sheet passes
   `keep_default_na=False`.

5. **An approval is verified like any other write.** `TermMapper.judge` no
   longer saves — the bulk acceptance wrote 2,105 verdicts and saved the whole
   4.4 MB record after each one, 9 GB and twenty minutes for a second's work —
   so the caller saves once. An approval changes no mapping, so the entry reads
   back identical whether or not it landed; the applier therefore reads the
   `curator` verdict back off the reloaded file and raises if it is not there.

Enforced by: `scripts/review_ui_pull.py` (`label_shaped`, `parse_resolutions`),
`scripts/apply_review_sheet.py` (`expand_families`, `decisions().ambiguous`, the
approval read-back), `scripts/mapping_review_sheet.py` and
`scripts/review_ui_data.py` (`keep_default_na=False`),
`wound_ontology/mappers/term_mapper.judge`.
`tests/test_review_prose_target.py` — 30 tests, mutation-checked against a
missing length test, a missing verb test, prose applied anyway, the original
words dropped, an unresolved verdict accepted, an unchecked resolution target,
and a swallowed positional argument.
`tests/test_review_family_move.py` — 17 tests, mutation-checked against a
canonical that never joins its family, one that joins on `y`/`n`, a duplicated
canonical, an ambiguous correction read as a reversal, an unreported ambiguity,
matching scoped to the whole sheet, and an exact term that stops winning.
`tests/test_review_sheet_na_terms.py` — 12 tests, mutation-checked against each
of the three readers dropping `keep_default_na=False`.

## 40. Whether a term belongs is a verdict on its record, beside where it belongs

*Since 2026-10-25 (rule 86) the record is the only place: the two exact lists it was exported to, the keyword lists and the Blocker are deleted.*


*Decided 2026-09-25. Extends rule 38 to the second question asked about a term.*

`TermMapping` became `TermMappingAndGate`, and its record now answers both
questions anyone asks about a term:

```
"silver sulfadiazine": {
  "to": "Silver sulfadiazine", "pairs": { … },      # WHERE it belongs
  "gate": {                                          # WHETHER it belongs
    "rule":    {"verdict": "out", "by": "METHODOLOGY_BLOCKLIST",
                "when": "imported 2026-09-25; provenance unknown"},
    "pass1":   {"verdict": "out", "score": 0.94, "near": "sulfadiazine assay"},
    "pass2":   {"verdict": "in",  "reason": "a topical antimicrobial for burns"},
    "curator": {"verdict": "in",  "reason": …, "when": …}}}
```

**The failure.** Scope was decided in two Python literals — `METHODOLOGY_BLOCKLIST`
(7,757 entries) and `WHITELIST` (2,684) — written by a cosine threshold
(`cos ≥ 0.92` auto-blocks) and an LLM batch, straight into source files. No
verdict, no reason, no date, no author, so nothing distinguishes an auto-block at
0.921 from a decision the curator meant. Three consequences, all measured:

* **201 of the 1,612 families the curator reviewed by hand on 2026-09-24 had a
  canonical the blocklist already rejects.** They approved 167 of them. One
  family in eight of an evening spent on concepts the pipeline had deleted,
  because nothing in front of them said so.
* The list had swallowed `silver sulfadiazine`, `photobiomodulation`,
  `tissue repair`, `collagen synthesis`, `bone healing` and `vac therapy`.
* The LLM pass whitelisted every term it did not name
  (`llm_kept = [e for e in queue if e not in processed]`), so a short answer for
  a batch of 50 was 50 permanent decisions nobody made.

**The rules.**

1. **Precedence is curator, then the passes, then the rule.** Rule 28 again: an
   explicit decision outranks a heuristic, and a model is a heuristic.
2. **Passes that contradict each other decide nothing** and fall through to the
   rule. That is the whole reason for having two — a disagreement is a question
   for the curator, and answering it by picking a pass throws away the only
   signal saying the term needs looking at. `gate_disagreements()` is the queue.
3. **A `rule` verdict keeps the position the list it came from had** — behind the
   whitelist keywords. The fold is a MOVE, not a ruling: putting `rule` ahead of
   the keywords changed two terms (`abusive head trauma`,
   `absence of vaginal cleansing right before surgery`), and a migration that
   changes a decision is a migration that lost one.
4. **The KEYWORD lists are not in the gate and never will be.** A keyword matches
   strings nobody has seen — `Blocker` applies the 69 of them to all 96,243 store
   names — so it cannot be a per-term record. Rule 29.
5. **The collaborator is tested `is not None`, never for truth.**
   `TermMappingAndGate.__len__` counts the live MAPPING, so a gate holding ten
   thousand scope verdicts and no mappings is falsy; `if self.gate` turned the
   gate off and left the lists deciding, silently.
6. **`gate()` does not save.** A pass writes thousands; the caller saves once,
   as with `judge` (rule 39.5).

**Verified, not assumed.** After the fold, `Blocker` condemns exactly the same
**4,138 of the store's 96,243 names** as before, with an identical `score()`
distribution — the decisions moved and not one of them changed. `blocked_names()`
now reads `gated("out")`, so a curator who lets a term back in sees it reflected
in the review sheet, which also gained a `gate says` column naming the source.

7. **The two exact lists are a GENERATED VIEW, and say so.** *(2026-09-25,
   later.)* `config/blocklist.py` and `config/whitelist.py` are printed from
   `gated("out")` / `gated("in")` by `term_lists.export_gate_lists`, behind a
   banner naming the record as the place to change. Every list write in
   `StoreCleaner` funnels through four methods in `BaseCleaner`, and those now
   write the record and re-export. A "remove" under a gate is the other half of
   an append, never a deletion on its own: it confirms the paired write landed
   and RAISES when called alone, because a silent no-op is what
   `BlockKeywordList.remove` used to be. Section headers survive because each
   entry carries `gate.rule.section`; hand-written prose does not, so the two
   blocks that existed moved above the declarations where module documentation
   belongs. Verified: membership identical across the round trip for all four
   lists, and `Blocker` still condemns the same 4,138 names.

8. **The gate matches the way the lists always have.** `TermList.match`
   lowercases, strips a trailing parenthetical and runs `normalize_term`
   (rule 13); an exact-match gate answered about `cohort` and said nothing about
   `Cohort`, and **92,683 of the store's 96,243 names looked undecided to the
   gate against 77,317 to the lists**. `gate_verdict` now falls back to the
   normalised spelling — `normalize_term` alone, because it already lowercases
   and strips, and a second implementation of one rule is the bug family
   rules 25–29 exist for. Enumeration (`gated`, `gate_disagreements`) uses
   `own_gate_verdict` and does NOT fall back, or every export would add the
   alias spellings to the file and the next export would add theirs.

9. **A pass contradicting a KEYWORD is invisible to `gate_disagreements`.** Only
   150 of the 4,138 blocked store names are blocked by the exact list; 3,988 are
   blocked by one of the 69 keywords, which are rules and not on the record, so
   there is nothing on the record for a pass to contradict.
   `Orchestrator.gate_overrides()` is the view that sees it: every term whose
   fate the gate changes against the lists alone, with the verdict, the source,
   the reason and the mention count.

10. **The exported list carries membership, not precedence.** An exact-list
    entry is matched BEHIND the whitelist keywords; a `curator` or `pass`
    verdict is matched AHEAD of them. So a pass saying `out` about a
    keyword-whitelisted term blocks it, and the literal alone does not —
    4 terms on 2026-09-25. `Blocker(gate=...)` is the authority; a consumer
    reading `METHODOLOGY_BLOCKLIST` without a gate is reading a good
    approximation, not the decision. `gate_overrides()` is what lists the gap.

**Not yet done, and named so it is not mistaken for done:** the review of what
`gate_overrides()` turns up is the curator's, not the passes'. A pass verdict
outranks every rule by design, so an unreviewed pass 2 run silently rewrites the
blocklist — which is why the overrides are reported before anything downstream
consumes them.

Enforced by: `wound_ontology/mappers/term_mapping_and_gate.py`
(`gate`, `gate_verdict`, `gated`, `gate_disagreements`, `GATE_VERDICTS`,
`GATE_SOURCES`), `wound_ontology/store/blocker.py` (`gate_verdict`, the order in
`is_blocked`), `wound_ontology/store/base_cleaner.py` (`gate=`),
`Orchestrator.blocked_names` / `gate_sources`,
`scripts/p4_fold_lists_into_gate.py` (the one-time move, SPENT, verified by
reading back from disk). `tests/test_gate.py` — 34 tests, mutation-checked
against a curator who does not outrank, contradicting passes that pick one,
passes that do not outrank the rule, a view ignoring precedence or accepting a
nonsense verdict, undetected or unordered disagreements, an unknown source or
verdict accepted, a gate that saves per verdict, truthiness instead of
`is not None`, a Blocker ignoring the gate, a `rule` verdict jumping the
whitelist keywords, and a `peek_gate` that creates a record.

## 41. Pass 0: a rule settles it, or nothing does

*Decided 2026-09-25, extended 2026-09-26. **Where its answers are written
changed on 2026-09-26 — see rule 43.** Everything below about WHICH spelling
wins still stands; what changed is that the answer is applied to the label
rather than recorded as a mapping entry.*

Before any SapBERT call and before any model call, the deterministic methods are
exhausted. A model is never paid to notice that `Surgical Site Infection` and
`surgical site infections` are one thing.

**The failure.** The mapping was matching spellings with embeddings and an
adjudicator, and the curator kept seeing plural-to-singular merges come back as
model verdicts. Measured on the 2026-09-25 store: of 96,243 terms, **9,650 are a
pure spelling variant of another** — 5,638 needing only the singular rule, 3,027
case alone, 584 a hyphen, 272 British spelling — and the mapping had found
2,820. The other 6,830 were queued for a model.

**The five steps, in this order** (`mappers/pass0.py`):

1. the head noun to the singular (`singular_spelling`, rule 23a);
2. British to American (`utils/spelling.py`);
3. the curator's preferred vocabulary (`canonical_vocabulary`, rules 48–49);
4. case, hyphens and punctuation folded (`fold`);
5. group on the result; every member maps onto one name.

Singular BEFORE spelling. `Statistical Analyses` becomes `Statistical Analysis`
and the noun never reaches the British-verb reading of `analyses` that `breame`
answers with `analyzes`, which would then singularise to `analyze`.

**The rules.**

1. **Two layers for spelling, and the second needs evidence.** `breame` is a
   dictionary of known pairs and knows what not to touch — `exercise`,
   `surprise`, `advertise`, `comprise`, `expertise` all survive it. It is
   general English, so it misses `oedema`, `haematoma`, `ischaemia`,
   `epithelialisation`. The morphological patterns that catch those are
   guarded twice: nothing above Zipf 4.5 is touched, and the candidate must be
   strictly commoner than the original. Guarded only by "the result occurs in
   the corpus" they produced `toe -> te`, `four -> for`,
   `anaerobic -> anerobic` and `expertise -> expertize` — the last because a
   typo in one abstract made `expertize` occur. **The corpus is not evidence.**
2. **A dictionary is not evidence either.** `/usr/share/dict/words` is Webster
   1934; it lists `oesophageal` as ordinary English and blocked a rewrite that
   should happen. Frequency says which spelling won; a wordlist says which was
   once standard.
3. **`breame` is wrong about five medical words** and they are held back:
   `disc` (intervertebral, optic, and DISC DIFFUSION), `aesthetic` (the
   American Society for *Aesthetic* Plastic Surgery), `gases` (the plural;
   `gasses` is the verb), `gauge`, `fillet`. Found by listing all 144
   conversions the corpus triggers and reading them.
4. **The canonical is chosen by `canonical_rank`, which must be a TOTAL order.**
   `Derived Indices` and `derived indices` tie on anchor, frequency, word count
   and length, and `max()` over a set then returns whichever the process's hash
   seed iterated first. Two runs chose different canonicals; pass 0 found it by
   failing to converge, wanting to rewrite 773 groups it had just written. The
   term itself is now the last component of the rank.
5. **An ontology label is never respelled.** It wins as canonical (rule 36) and
   is kept exactly as the ontology writes it, plural or not. Rule 23a is advice
   to the curator, not a licence to rewrite what they wrote.
6. **A lone spelling is respelled too** *(2026-09-26, the curator's call)*.
   `wounds` with no `wound` anywhere still becomes `wound`. Counted apart from
   the groups, because settling a choice between spellings and rewriting the
   only spelling there is are different acts: 22,724 of the former, 9,578 of
   the latter.
7. **`fold` strips a trailing parenthetical, so the group is checked before it
   is merged.** `vitamin (role)` is not `vitamin` — a role class is not the
   substance. Exactly one group on this corpus, and it is that one.
8. **The target is followed to its end before it is written.** Pass 0 picks a
   canonical from the spellings it can see, and that spelling may already be
   mapped onward, often by a curator whose entry pass 0 must not touch. Writing
   the pair anyway makes a CHAIN, and `ConceptStore.normalize` follows exactly
   one hop, so the merge half-lands. A curator's entry is followed rather than
   overruled: they said these two are one concept, and if the second has moved,
   following it is what honours that.
9. **It is idempotent**, so it runs after extraction and again before matching.
   Two iterations reach a fixed point on the live store.

**Known limitation, measured:** a title-cased acronym plural does not fold onto
the acronym. `singularize('dfus')` is `'dfus'` — the stem is not a word, so no
suffix rule recognises it — and the extractor title-cases acronyms, so `Dfus`
cannot reach `DFU`. **8 terms** on this corpus; pinned by an `xfail`.

Enforced by: `wound_ontology/mappers/pass0.py`,
`wound_ontology/utils/spelling.py`, `Orchestrator.run_pass0_normalise`,
`canonical_rank`. `tests/test_pass0.py` — 32 tests, mutation-checked against a
missing singular or spelling step, the steps reordered, a missing or
always-firing parenthetical guard, an anchor that loses or gets respelled,
already-mapped or curator-ruled pairs overwritten, unfixed iteration order, a
singleton left alone, a self-mapping, an unfollowed target and an unterminated
walk. `tests/test_spelling.py` — 96 tests, mutation-checked against a missing
`breame` layer, a missing frequency floor or comparison, dropped casing, each
pattern family removed, the medical exceptions dropped, and the unanchored
`our` rule removed or unguarded.

## 42. A normalisation runs until it stops moving, and a spelling it mints is not assumed to exist

**Decided 2026-09-26.**

Two halves of one mistake, both found by the same crash.

**(a) One pass is not a fixed point.** The mapper groups terms by `fold` and
names each group with `_canonical`, which may MINT a spelling per rule 23a. A
minted spelling need not fold to the key of the group that minted it:
`multi-drug resistant bacterias` folds to `multi drug resistant bacteria` and
mints `multi-drug resistant bacteria`, whose own fold is
`multi drug resistant bacterium` — the key of a **different** group, the one
holding `multi-drug-resistant bacterium`. One pass leaves them as two terms and
sends both to SapBERT as two concepts.

Measured on the 2026-09-26 corpus: **649 of 90,435 groups** mint a canonical
that belongs to another group, and **16 pairs of canonicals fold together** —
`Autoimmune disease`/`autoimmune disease`,
`mitogen-activated protein kinase`/`mitogen activated protein kinase`,
`foreign-body response`/`foreign body response`. Folding again until the set
stops moving takes **3 rounds** and removes **622** spellings from the 90,435
sent to the model.

This is rule 41's ninth clause — *it is idempotent* — applied to the mapper,
and the curator's transitivity rule of 2026-09-25: a term folded in round 1
onto a spelling round 2 folds again must end at the **final** spelling, not the
intermediate. Follow every chain to its end; a chain that closes on itself maps
nothing and is reported, never dropped in silence.

**(b) A canonical is not necessarily an embedded term.** The clustering is
indexed by the terms that went to the model. A minted canonical is in no
cluster, so `assignment[c]` and `term_to_idx[c]` have no entry for it. Two
builds died there — first the forest assertion, then the metadata step — each
after fifty minutes of embedding. The canonical maps to itself; an identity
entry needs no metadata, because it is dropped from the merges anyway; and a
merge **onto** a minted spelling is scored against the cluster member the
spelling was minted from, which is embedded. A confidence nobody computed is
never written: if that member is unknown too, it raises.

With (a) in force the clustered path mints nothing at all — measured: 0 of
89,813 — so (b) is defence, and it is exercised by a normaliser that oscillates
on purpose.

**A cache that outlives one run must not be writable by a test.** The vector
store keeps one row per term forever, so a unit test embedding `alpha one` with
a toy embedder would put a made-up vector under a real name and the next real
run would reuse it instead of asking SapBERT. An autouse fixture redirects the
store for the whole suite. The previous cache was keyed by the whole term list
and could only be hit by an identical list, which is why this hazard is new.

Enforced by: `TermMapper.build_from_embeddings` (the fold rounds, the chain
resolution, `minted_from`), `TermMapper._embeddings_for` and
`_vector_store_paths`, and `tests/conftest.py`'s
`_vector_store_stays_out_of_data_cache`. `tests/test_term_mapper.py` — 5 tests,
mutation-checked against a single fold round, no chain resolution, a store that
is never reused or is trusted when its rows and names disagree, identity
entries not skipped, the canonical index looked up without a guard, a silent
non-convergence, a silent cycle, and a minted canonical with no self-entry.


## 43. Pass 0 renames the label, and it renames it everywhere a term string lives

**Decided 2026-09-26.** The curator: *pass 0 should not create another mapping,
it should change the labels right at the spot* — and then *it should be applied
to the concept store AND the termmapping dict just to make sure nothing slipped
through*.

**What it replaced.** Pass 0 wrote its answers into the term mapping: 32,302
entries of the form `Surgical Site Infections -> Surgical Site Infection`. Two
costs, both paid elsewhere.

The record a curator reads filled up with mechanical respellings, burying the
few hundred decisions that need eyes — the same complaint that already kept
identity entries out of the file, arriving through a different door.

And the store went on holding the spelling the extractor produced, so every
later step had to carry the mapping around to know what a term was really
called. The term-mapping build had to inject **23,220 canonicals that were not
store strings** into its clustering, with frequencies borrowed from whatever
pointed at them, purely because pass 0's answers lived in the mapping instead
of in the store. That injection is what pushed the term set past 121,000 and
into the two crashes of rule 42.

**The rule.** Pass 0 produces RENAMES, and applies them in place:

* **the concept store** — entity names, the target half of every predicate
  triple, and the keys of both verdict books, all in one traversal. They have
  to move together: a rejection written against `diabetic foot ulcers` stops
  applying the moment the entity is renamed, and the term comes back. Two names
  landing on one keep the strongest evidence per triple, and the first verdict.
  Every rename is stamped in the store's own `renamed` book with `by="pass0"`,
  so the extractor's spelling stays recoverable — nothing is deleted (rule 33).
* **the term mapping** — the record's key, its live target, the canonicals its
  `pairs` are keyed by, and its gate section. All four, or the record comes
  apart: the verdicts are about a PAIR, so respelling a canonical without them
  detaches every judgement a model or a curator ever made about it. Two records
  landing on one key merge, first-come winning every tie; two that point at
  DIFFERENT canonicals are a real disagreement and are reported, never resolved
  quietly; an entry whose target has become its own key is **deleted**.

**A gate source that contradicts ITSELF across merged spellings decides
nothing.** Merging two records folds their gate verdicts together, and the
first version let first-come win per source — so when two spellings of one term
carried the same source answering differently, one side vanished. **10 of them
on the 2026-09-26 data**: `pain score`, `pain assessment`, `pain-management
technique`, `predictive factor`, `traditional measurement` and `injury model`,
where pass 2 said `in` of one spelling and `out` of another; and
`quality-adjusted life year`, `quick disability of the arm, shoulder and hand`,
`self-injection of paraffin` and `wide-awake local anesthesia no tourniquet
technique`, where the imported lists had the same concept on the blocklist
under one spelling and the whitelist under another — invisible until pass 0
merged the spellings.

Contradicting passes already decide nothing and fall through, because a
disagreement is the only signal that says a term needs a person (rule 40). A
source contradicting itself is the same situation, so it is treated the same
way: the source is removed from the gate, both sides are kept in
`gate_contested`, and the count is printed. Merging spellings turned ten
invisible contradictions into ten visible questions, which is the point; the
one thing it must not do is pick one quietly.

**An identity mapping is deleted, not retired** (curator, 2026-09-26: *you can
delete the sole spelling mappings — after normalising they are identity
mappings*). Rule 37 keeps a retired entry because it carries verdicts that cost
credits to obtain, and that reasoning does not reach here: a verdict about the
pair *(term, term)* is a verdict about the spelling question pass 0 has just
settled by rule. The record goes with the entry **unless** it also carries a
gate verdict (whether the term belongs at all, rule 40) or a judgement about
some OTHER canonical — those are different decisions that happen to live on the
same record, and both counts are reported separately.

**The per-label half runs at ingestion** (curator, 2026-09-26: *it should be run
after every concept extraction on the new extract*). `clean_entity_str` and
`clean_target_str` — the one gate every ingestion path goes through — apply the
singular and American rules the moment an extract arrives, because they are a
pure function of the label and have no reason to wait for a maintenance pass.
The half that elects one spelling per group still needs the whole store and
still runs as that pass. Those two functions had been byte-identical copies of
each other, which is how the store came to hold `Tumor` as a subject beside
`Tumours` as an object.

**Only one of the two would be worse than either.** Normalising the store alone
leaves the mapping holding spellings the rules reject, and the next apply puts
them back.

**Two guards moved.** A refusal on record used to be enforced by `add_batch` on
the way into the mapping. Nothing writes to the mapping any more, so pass 0
checks refusals and curator rulings itself — a rule does not overrule a person
(rule 28). A declared BFO category keeps the spelling BFO gives it (rule 22).

**Chains are revealed, not created.** `A -> B` beside `b -> C` was already a
chain, because `B` and `b` are one term and the spelling hid it. The count of
live entries whose target is itself a key is reported after every rename, so
`resolve_chains` is known to be owed rather than discovered downstream.

Enforced by: `mappers/pass0.pass0_renames`, `ConceptStore.apply_renames` and
the `_rewrite_names` traversal it shares with `normalize`,
`TermMappingAndGate.apply_renames`, `Orchestrator.run_pass0_normalise` (which
reads both files back off disk and raises if a renamed spelling survives in
either). `tests/test_pass0.py` and `tests/test_pass0_applies_in_place.py` —
16 mutations, all caught: targets or verdict keys left behind, renames not
recorded, weaker evidence winning a merge, mapping keys, targets or pair
canonicals not renamed, a merge that overwrites instead of absorbing, a gate
dropped on a merge, identities left live, target conflicts resolved in silence,
chains uncounted, refusals or curator rulings ignored, declared categories
elected against, and mapping-only strings left out of the grouping.


## 44. One normaliser

**Decided 2026-09-26.** The curator, watching the third one being debugged:
*why are there several functions for normalising? One is enough.*

There were three — `normalised_label`, `group_key` and `character_key` — each
hand-rolling the same steps in its own order. Every bug in them was the same
bug: a new one disagreeing with the old ones about where a step goes. In one
afternoon that produced four, all on live data:

| symptom | disagreement |
|---|---|
| `Ulcers (DFU)` never reached `ulcer` | parenthetical stripped *after* singularising |
| `Case` and `cases` read as two strings | the *lookup* singulariser (`cases` → `cas`) instead of the naming one |
| `DFU` and `DFUs` held apart | lowercased *before* the acronym rule could fire |
| `OUTCOME MEASURES` held apart from `outcome measure` | lowercased *after* it |

So the order of the steps, and what each class of character is worth, live in
exactly one function — `utils/normalise.normalise(label)` — which answers three
questions at once because they are three projections of one pipeline:

* **`name`** — what the term should be CALLED. Singular head (rule 23a), then
  British to American (rule 41), then the curator's preferred vocabulary
  (rules 48–49), in that order, keeping the writer's case and any parenthetical.
* **`key`** — what two spellings of one term SHARE. `fold` of the name, so the
  singular and British rules are already applied and two spellings cannot
  disagree about them.
* **`strict`** — the key, keeping every character `fold` would throw away.

`strict` earns its place: `normalize_term` strips *all* punctuation, and that is
how `Na+` meets `NA`, `Phase I/II` meets `Phase III`, `JAK/STAT` meets `Jakstat`
and `P < 0.05` meets `P > 0.05`. Two labels with the same `key` and a different
`strict` are not two spellings of one term, they are two terms that met by
losing a character. Pass 0 **splits** such a group rather than refusing it —
one odd member (`patient's` beside `Patients`, `patient`, `patients`) used to
hold the whole group back, 1,132 of them on live data.

The three fields are computed on first use and held, because the ingestion path
asks for `name` 179,000 times and never wants the other two.

**Not collapsed, and why:** `normalize_term`, `fold`, `singularize` and
`naming_singular` remain. They are the *steps* this function is built from, not
competing answers to the same question, and `fold` in particular is the key
every other index in the project is already written against. Folding them in
would change stored keys, so it is a measurement, not a refactor.

**What the ontology labels taught the singulariser.** Checking all 1,888 labels
in WONT, MILD and the imported modules against the normaliser — a test set it
had never seen — found two defects that were live in the store from the moment
ingestion started normalising:

* **Latin present participles used as species epithets** end `-ans`/`-ens`
  exactly as `clinicians`, `pathogens`, `specimens` and `regimens` do, and no
  suffix rule separates them. The store held `Candida albican`, `Serratia
  marcescen`, `Clostridium perfringen`, `thromboangiitis obliteran`,
  `Achromobacter xylosoxidan`, `Mycobacterium ulceran`, `Pseudomona`,
  `erysipela`, `glan`, `den`. Listed in `_INVARIANT`, for the same reason
  `_ES_STEM_IS_SINGULAR` is a list.
* **A token with an internal capital** is an acronym or a chemical name and its
  case is not ours to normalise. The round trip through the lowercase
  `naming_singular` was destroying it: `miRNAs` came back `mirna` and `iGAS`
  came back `iga`. Only a trailing LOWERCASE `s` is a plural on such a token; a
  trailing capital `S` is part of it.

**The ontology's own labels are not normalised** (measured 2026-09-26, and the
reason is in the data). Of the 58 changes the normaliser would make to the
imported modules, **every one is wrong**: 20 are OBO relation labels, which are
verbs by convention (`regulates` → `regulate`, `precedes` → `precede`); two are
proper nouns (`Waters` is Waters Corporation, `Helicos` is Helicos
BioSciences); eleven are ChEBI class plurals that name a class of derivatives
and are distinct from the singular class; four are taxa (`Bacteria` →
`Bacterium`, `Homo sapiens` → `Homo sapien`); and four are not class labels at
all but `rdfs:label` on anonymous axiom-annotation nodes. Editing them would
also mean the modules no longer match upstream, which is the one thing module
extraction exists to guarantee.

There is no matching problem to fix by doing it: the anchor match goes through
`key`, which normalises both sides identically, and rule 36 keeps the ontology's
own spelling as the canonical. The one real consequence runs the other way —
WONT's four British labels pull the store back to British against rule 41 — and
that is a curation decision about four labels in a curated file, not a pipeline
step.

Enforced by: `utils/normalise.py`, `ConceptStore.clean_entity_str` /
`clean_target_str`, `utils/label_match._INVARIANT` and `singular_spelling`.
`tests/test_pass0.py`, `tests/test_pass0_applies_in_place.py`,
`tests/test_naming_singular.py`.


## 45. A timeout belongs to the transport, not to a wrapper around it

**Decided 2026-09-26.** The term-mapping build stopped dead for **3h40m** and
nothing said so. The evidence when it was finally checked: 4h03m elapsed
against **7m52s of CPU — 2.5 seconds of it in the last two hours** — no open
sockets at all, no pending timers, and the main thread parked in
`select_kqueue_control_impl`. An event loop waiting on an empty kqueue is not
slow, it is awaiting a future that nothing will ever complete.

**Why the timeout did not save it.** `asyncio.wait_for` does not abort a
request. It CANCELS the inner task and then *awaits the cancellation
finishing*. If the HTTP client's teardown never finishes, `wait_for` hangs
after its own timeout has already fired, and nothing wrapped around it can
help, because the await that never returns is inside the timeout mechanism
itself. The log's last two lines were a timeout and a recovery; the call after
them never opened a socket, which is what waiting for a connection slot looks
like — a cancelled request can leave its slot in the pool un-returned.

**The rule.** The budget goes to the transport, which enforces it without
cancelling anything:

* `timeout=httpx.Timeout(default, connect=…, pool=…)` on the client. `pool` is
  the one that matters here: without it, the call after a leaked slot waits
  forever and opens nothing.
* the per-call budget (240s for extraction, 360s for the batch judgements)
  is passed to the REQUEST, not only to the wrapper, or the transport enforces
  the default instead.
* `max_retries=0` on the SDK client. It retries twice by default, inside our
  own budget, which multiplies the wall time and makes `[LLM] Retry 1` a lie
  about how many attempts were made. Retrying is `_execute_with_retry`'s job.
* `wait_for` stays, with slack, as a BACKSTOP. If it ever fires now, that is a
  defect worth seeing, not a normal timeout — so it must not race the thing it
  is backing up.

**What it cost, measured:** nothing, as it happened. The clustering had been
saved at 11:05 (records 51,745 → 54,249, live 37,300 → 40,479) and the
adjudication had banked no verdicts at all (pass1 7,423 and pass2 4,813, byte
for byte what they were before the run). But that was luck, not design: four
hours of a run that reports progress only at the end is four hours of nothing
to show.

**The general rule behind it:** a step that can wait forever must be able to
say so. "No silent failure" covers hanging as well as failing — a process at
0% CPU with no output is indistinguishable from a working one unless something
is watching the difference.

Enforced by: `LLMClient.__init__` and `LLMClient._call_json`.
`tests/test_llm_timeout.py` — 6 tests, 6 mutations, all caught: no transport
timeout, no pool timeout, a connect leash as long as the read leash, the SDK's
retries left on, the per-call budget not reaching the request, and a backstop
that races the transport instead of backing it up.


## 46. A word boundary is not a spelling difference

**Decided 2026-09-27.** The curator, handed `intraabdominal complication` →
`intra-abdominal complication` to adjudicate by hand: *why. this should have
been treated by the dehyphenation in string normalize.*

It should have been. It was not, and the reason is one character.
`normalize_term` turns a hyphen into a **space**:

```
intra-abdominal complication  →  "intra abdominal complication"
intraabdominal complication   →  "intraabdominal complication"
```

Two keys, two groups, two terms — so pass 0 had nothing to say, the clustering
proposed the pair at cosine 0.97, the two gate passes disagreed about it, and a
person was asked to rule on a hyphen. Worse, the *Unicode* hyphen is deleted
rather than spaced (`[^\w\s]` does not spare U+2011), so one spelling of one
word folded two different ways depending on which dash character the author
typed: `re-tear` → `re tear`, `re‑tear` → `retear`.

**The rule.** Hyphen, space and nothing are three ways of writing one seam, and
a seam is not a character a spelling is allowed to differ in. `key` and
`strict` therefore carry **no spaces at all**. The seam is closed **last**,
after the head noun is singularised, because `singular_spelling` needs the
words to still be words — close it first and `antimicrobial agents` has no head
to make singular.

`strict` closes it too, and must: `key` merging a group that `strict` splits
straight back apart over the very difference `key` merged on is not a rule, it
is two rules disagreeing (rule 44). What `strict` still keeps is every
character `fold` *discards* — `p < 0.05` stays apart from `p > 0.05`, `Na+`
from `NA`, `Phase I/II` from `Phase III` — and those groups are held back for a
person exactly as before.

**What it was hiding, measured on the 2026-09-26 store and mapping.** Pass 0
had been applied and was at a fixed point but for 19 groups the mapping build
had since added. With the seam closed it finds **522 groups with more than one
spelling, 526 renames** — so **503 groups, 888 store names**, were sitting
apart over a hyphen. They are not marginal: `health care provider` /
`healthcare provider`, `anti-microbial activity` / `antimicrobial activity`,
`end point` / `endpoint`, `bed sore` / `bedsore`, `MMP-1` / `MMP1`,
`post-operative wound` / `postoperative wound`. **Ten of the 695 pairs in the
open curator queue** were this and nothing else.

The groups held back by a discarded character go 162 → 189: the wider key
introduces 27 more groups that `strict` then splits — `organ space` versus
`organ/space`, `JAK-STAT` versus `JAK/STAT`, `p = 0.001` versus `p < 0.001`.
That is the guard working, not a regression.

**Not changed:** `fold` and `normalize_term` themselves. `fold` splits on
spaces to find the head noun, and `LabelIndex` and the keyword lists are built
on it; the boundary rule belongs where the question *"are these two spellings
of one term?"* is asked, which is `Normalised`. One consequence is left
standing and named: the ontology label index still matches on `fold`, so an
ontology class written `health care provider` does not meet a store term
written `healthcare provider` until pass 0 has renamed one onto the other.

### What closing the seam broke, and what it cost to fix

Merging the groups handed the ELECTION a question it had never been asked.
`canonical_rank` ends in word count — *a longer label is the more specific of
two spellings* — and inside a seam group that reasoning is false by
construction: the members are the same words with the boundary somewhere else,
so an extra word is not more specific, it is a boundary in the wrong place.

`Cumberland Ankle Instability Tool` and `Cumberl and Ankle Instability Tool`
each appear in exactly one abstract. The corpus said nothing, the extra word
won, and pass 0 was about to rename the instrument onto the typo.

**So when the corpus is silent, the language is asked**: among the members that
tie on being an ontology label and on corpus frequency, a tokenisation that
invents a word the language has never seen loses to one that does not
(`pass0.invented_words`, on `spelling.zipf`). It is the last word *before* word
count and it never reaches past frequency — `postradiation`, `antibiofilm` and
`intraobserver` are in no general-English list either, and a medical corpus
that writes them is entitled to them. Measured over the whole 2026-09-26
store it changes **exactly one election out of 522**: that one.

`spelling._zipf` became `spelling.zipf`, public and `lru_cache`d — one
accessor, two callers, rather than a second import of `wordfreq` (rule 44).

Enforced by: `utils/normalise.Normalised.key` and `.strict`;
`mappers/pass0.invented_words` and the election in `_elect`.
`tests/test_pass0.py` — 8 tests, 8 mutations, all caught. The seam: the key
keeping its spaces (the bug itself), `strict` keeping its spaces (the split
undoing the merge), the seam closed before the head noun is singularised, and
`strict` reduced to the key so it stops guarding the discarded characters. The
election: no lexicon at all, the lexicon reaching past the corpus count, the
lexicon preferring the invented word, and a digit run counted as a word.


## 47. A decision is stored with the question it answers, and applying it is a write that is read back

**Decided 2026-09-27.** The Contradiction Queue came back with 705 answers.
Applying them found three defects, in the step between a person deciding and
the record holding the decision. None of them was a bug in what the curator
said; all three were ways of losing it.

**The decision did not carry its question.** The page stored what the curator
SAID -- term, verdict, note -- and not what it ASKED, so a pair decision
arrived with no canonical. Reading it back off the live mapping does not work,
because these pairs are in the queue precisely because the two passes
disagreed and the adjudicator WITHDREW the mapping: **634 of the 695 pair
decisions resolved to nothing** and printed `NO CANONICAL ... skipped`. The
fix has two halves, and both matter. The applier can be handed the queue
payload and match on the row id (`--queue`), checking the term as well as
reading the canonical, because the ids are positional and a payload rebuilt
against a different queue would file every verdict against the wrong pair. And
the NEXT page stores the question in the answer: the Canonical Tie-Breaks page
writes the spellings it asked about into each decision document, so its
applier needs nothing but the folder.

**A confirmation was a note, not a mapping.** `same_class` wrote the verdict
onto the pair and left the mapping withdrawn, so **135 of the 499
confirmations changed nothing a build would see**. A verdict that agrees with
a proposal has to reinstate it.

**A batch collided with itself.** The check for "is this canonical already
spoken for?" read the mapping as it stood BEFORE the batch, where nothing had
written yet. Two pairs of reversals each claimed one canonical --
`inflammation level` and `inflammatory level` both onto `levels of
inflammation`, `near-infrared radiation` and `near-infrared light` both onto
`near-infrared` -- and the second write replaced the first. **Of 179
reversals, 177 landed.** The read-back caught the two; the point of the fix is
that the read-back should have nothing to catch.

**Every clash check asked about the SOURCE, and none about the target.** A
mapping has to bottom out in a name, and `A -> B -> A` bottoms out nowhere.
`orthopedics -> orthopedic` was standing, the queue confirmed `orthopedic ->
orthopedics`, the source was free, every check passed -- and the write closed
a two-cycle. **26 of them**, none of which existed before that run. So the
question is not asked of the graph as it IS but of the graph as it WILL BE:
the batch's own edges, minus the arrows the batch removes, over what stands.
31 edges closed a loop and were held back. What that cost is worth saying
exactly: **29 of the 30 loops were already joined under one name**, pointing
the other way, so the curator's ruling that they are one class was already
true and only the choice of name differed. One was not -- three spellings of
a chronic leg ulcer, joined in a ring -- and that one is a real open question.

**660 of the 695 pairs already carried a curator verdict** from the phone
review of 2026-09-25, in that review's own vocabulary -- `kept`, `refused`,
`repointed` -- and 79 of them said `refused` where the queue now said
`reverse`. The same person, looking again with the two passes' reasoning in
front of them. The new verdict stands; the old one moves to `curator_history`
rather than being overwritten out of existence (rule 33).

**The rule.** A queue that answers questions must store the question with the
answer. Applying the answers is a write, and a write is verified by reading it
back -- every kind of it, not the kinds that were easy to check. What cannot
be written is NAMED and handed back to the curator, because a page stops
offering a row the moment it is answered: a decision this step drops is not
deferred, it is one the curator believes they made and will never be asked for
again.

**What it came to.** 705 decisions: 10 gate verdicts, 475 confirmations live
again, 16 refusals, 173 reversals, 1 subsumption candidate, and **30 rows
named as clashes** rather than guessed at. Those 30 went back as 28 canonical
tie-breaks -- one class, several names, which name does it keep -- and came
back answered, 54 spellings repointed onto 28 canonicals, no clash and nothing
held.

Enforced by: `scripts/apply_contradiction_verdicts.py` (`_with_queue`,
`confirmation_clashes`, `reversal_clashes`, `record_curator`) and
`scripts/apply_canonical_tiebreaks.py` (`plan`, `apply_writes`), each read
back off disk before it reports success.
`tests/test_contradiction_verdicts.py` -- 32 tests, 18 mutations;
`tests/test_canonical_tiebreaks.py` -- 12 tests, 11 mutations. All caught,
two of them only after the check they aimed at was lifted out of `main` into
a function a test can reach -- which is the other half of the rule: a step
that cannot be tested without the whole store will be tested by the live
data, once, in production.


## 48. A repeated naming decision is a Pass 0 rule, not another queue row

**Decided 2026-09-27.** The curator settled three recurrent names globally:

* `limb` is written `extremity` (and `limbs` as `extremities`);
* `strategy` is written `approach` (and `strategies` as `approaches`);
* `wound management` is written `wound care`.

The adjudication record already contains 17 limb/extremity, 12
strategy/approach and 21 care/management same-class pairs. Asking again for
every compound does not add judgment; it makes the curator repeat one. Once a
choice is universal and directional, Pass 0 owns it and applies it to new
terms before any model or review queue sees them.

This is a preferred-name layer, not permission to run a thesaurus over the
store. `management` changes only immediately after `wound`; `case management`
and `pain management` remain management. Word boundaries keep `limbic` out.
Case and plural number are preserved. The layer runs after singularisation and
American spelling and before the group key is made, and it is used by both
`name` and `strict`; changing only the name would let the character guard split
the two preferred-name variants straight back apart. An ontology's own label
still keeps its exact wording under rule 36.

Enforced by: `utils.normalise.canonical_vocabulary` and
`utils.normalise.Normalised`; `tests/test_pass0.py` covers case, plurals,
hyphenated phrases, grouping, frequency not overruling the preferred name,
idempotence through the existing fixed-point test, and the management/limbic
boundaries.


## 49. Thirty recurrent same-class choices are preferred vocabulary

**Decided 2026-09-27.** After the first three preferred-name rules, the curator
approved the next thirty recurrent choices mined from the adjudication record:

| old | preferred | old | preferred |
|---|---|---|---|
| technique | method | cutaneous | skin |
| evaluation | assessment | trauma | injury |
| testing | test | inflammation (modifier) | inflammatory |
| cellular (modifier) | cell | diabetes (modifier) | diabetic |
| infectious (modifier) | infection | surgery (modifier) | surgical |
| specimen | sample | value | level |
| alteration | change | action | activity |
| feature | characteristic | full | complete |
| usage | use | bony (modifier) | bone |
| operation | surgery | microbiological | microbial |
| pharmacological | pharmacologic | physiological | physiologic |
| previous | prior | dermatological | dermatologic |
| radiological | radiologic | oncological | oncologic |
| histopathologic | histopathological | numerical | numeric |
| preventative | preventive | post-surgical / postsurgical | postoperative |

Singular and plural forms are explicit where English does not derive the target
mechanically (`actions` → `activities`, `traumas` → `injuries`). The six
noun/adjective choices fire only when followed by a noun-like token and not a
relation or construction such as `inflammation in`, `cellular and`, or
`diabetes-related`; Pass 0 is choosing a compound's name, not rewriting prose.
All replacements preserve ordinary lower, title and upper case, and the same
function is applied to `name` and `strict` so the character guard cannot undo
the grouping.

Enforced by: `utils.normalise.CANONICAL_WORDS`, `CANONICAL_MODIFIERS`,
`canonical_vocabulary`; `tests/test_pass0.py` has one naming case for every
approved rule plus modifier-boundary, grouping and fixed-point coverage.


## 50. Every abstract keeps what it actually said, through every rename

> **Superseded the same day by rule 51.** The `as_extracted` book existed only
> because the store was rewritten in place. Rule 51 stops rewriting it, so what
> an abstract said IS the store, and the book, its carry-through and its
> backfill script are gone. The failure below is still why rule 51 exists.

**Decided 2026-09-27.** The curator: *if the mapping applies there is no
provenance check — we don't know what was extracted and what it was mapped
into.*

Each document in the concept store carries `as_extracted`: `{the name as the
store now spells it: [the strings the extractor wrote that now read as that
name]}`. It is written at ingestion, before a single character is cleaned, and
every rename carries it forward: the normalisation, pass 0, the mapping apply
and the sense split. Two spellings merging keep both origins. The global
`renamed` book still says WHY a name moved; the per-document book says WHAT
this abstract wrote. Neither can stand in for the other.

**The failure.** The only trace was the global `renamed` book, and it had four
holes, all measured on the 2026-09-27 store:

* **It was global.** Keyed by the old name, it could say `Diabetic Foot Ulcers
  -> Diabetic Foot Ulcer`, but once `DFU` merged into the same name, nothing
  said which of the two a given abstract had used.
* **The literal string was gone at ingestion.** `clean_entity_str` strips the
  parenthetical and singularises before anything is stored, so `Diabetic Foot
  Ulcers (DFUs)` never reached the file.
* **Target renames were not recorded.** `_rewrite_names` stamped entity names
  only; 1,808 names the store holds today could be traced to their snapshot
  spelling only by their spelling key, because they had only ever moved as
  targets.
* **`by: "mapping"` named no decision.** A mapping rename now carries
  `evidence`: the entry, the canonical, its method, and the pass and curator
  verdicts on the pair. A name renamed twice keeps the first rename under
  `history` instead of overwriting it.

**The sense split** (`split_irreconcilable_terms`) renames per abstract, so the
global book, keyed by the old name, could never hold it. Only the per-document
book can.

**The existing store was seeded from the earliest snapshot, and says so.** The
extractor's literal strings for the 6,029 abstracts ingested before this rule
were never kept. `scripts/p4_backfill_as_extracted.py` seeded each book from the
2026-09-22 snapshot, taken before the first mapping apply, and stamped every
such document `as_extracted_from` with that source. A literal string and a
snapshot spelling are never presented as the same thing. Alignment was complete:
215,819 snapshot names followed the rename book to a current name, 1,808
matched by pass 0's spelling key, none were ambiguous, and every one of the
214,813 current names received an origin.

Enforced by: `concept_store.AS_EXTRACTED`, `note_extracted`, `carry_extracted`;
both ingestion paths; `ConceptStore._rewrite_names` (the book, and target
renames recorded); `ConceptStore.record_rename` (`evidence`, `history`);
`ConceptStore.normalize` (the mapping entry as evidence);
`split_irreconcilable_terms`. `tests/test_extraction_provenance.py` has 9 tests,
mutation-checked against: no carry through a rename, a carry that keeps one
origin of a merge, target renames unrecorded, no history, no carry through the
split, ingestion dropping a target's origin, no mapping evidence, and a repeated
rename overwriting the first stamp.


## 51. The concept store is evidence; every decision about a term lives in the term dict

**Decided 2026-09-27.** The curator, on seeing the store hold a `decisions`
record beside the PMIDs: *doesn't that make the concept store and the term
mapper dict overlap weirdly? … as it is right now is not to my liking.*

**The rule.** Two records and one view:

* **The concept store** holds what each abstract said and nothing else. One
  record per PMID (plus synthetic evidence such as `predefined`), entities and
  relations as extracted. It is never rewritten after it arrives. No key other
  than evidence sits in it; a file that still holds a `decisions` record is
  refused on load, because its verdicts would otherwise be silently ignored.
* **The term mapping and gate dict** holds every decision about a term, on
  that term's record: `spelling` (an ALIAS -- this string is now written
  differently, by whom, when), the mapping (`to`, `pairs`), the gate,
  `rejected` (the store rejection of the whole term), `relations` (rejected
  relations of it), `senses` (the per-category split).
  *(Since 2026-10-26, rule 87: the per-category split is `to` itself, one
  name per category, and `relations` also holds the decided `is_a`.)* An alias carries
  nothing but its spelling; `apply_renames` moves every decision to the new
  spelling and leaves the alias. A write addressed to an alias lands on its
  current spelling.
* **The view** (`ConceptStore.view` / `records`) is the evidence resolved
  through the term dict: raw string → spelling (aliases followed) → mapping
  (exact key, then folded) → verdicts → senses. `mapped=False` stops at the
  spelling, which is what the mapping build and pass 0 read. Everything
  downstream reads the view.

**What changed in practice.**

* Pass 0 no longer rewrites the store: a rename is an alias in the term dict.
  The mapping is no longer "applied" to the store: the view reads the live
  mapping. The sense split writes `senses`, and the view renames each mention
  by the category its own abstract gave it.
* Ingestion stores the extractor's literal string and records its cleaned
  name (parenthetical stripped, singular, American) as a spelling `by:
  "ingestion"` -- except for a string the store already holds or one that
  carries a decision, which pass 0 owns: an alias re-spells a string in EVERY
  abstract, and `vitamins`, an ontology label, must stay `vitamins`.
* The view does not title-case. Pass 0 elects one spelling per term and
  records it; title-casing in `normalize` had been undoing that election. A
  case-only or plural mapping entry is therefore no longer inert -- as
  `prune_inert_mappings` predicted it would be the day the store stopped
  title-casing.
* Provenance is a lookup, not a book: `ConceptStore.trace(name)` lists the
  strings the abstracts wrote that resolve to the name, their PMIDs, each
  spelling step with its author, and the mapping entry and verdicts that sent
  it there.

**The migration** (`scripts/p4_split_evidence_and_decisions.py`, one-time):
the evidence is the 2026-09-22 snapshot, taken before the first mapping apply,
because the extractor's literal strings for these 6,029 abstracts were never
kept -- each record says so in `evidence_from`. The store's rename book became
38,262 aliases; 695 more were reconstructed for strings that had moved only as
relation targets before target renames were recorded, and are marked so; 27
book entries recorded renames a later decision reversed (pass 0's
`histopathological → histopathologic` before rule 49 turned it round, the
`action potential` repair) and are kept as `spelling_reversed` history on the
current name rather than as aliases, since an alias would re-spell today's
name into the one it replaced. 2,330 rejected entities and 6,436 rejected
cells moved onto their terms' records. **Nothing was written until the view
reproduced the store exactly -- 6,029 records, 265,687 cells, with the
rejections applied and with them shown -- and the files were read back from
disk and checked again.**

**Scope is the gate's, read live** *(2026-09-28, the curator: "merge into
gate")*. The 2,330 `rejected` terms and 6,436 rejected relations were all
written `by: "blocklist"` on 2026-09-20 -- the cleaner's copy of the lists'
answer, frozen, deciding the question the gate decides. They are removed
(`scripts/p4_merge_rejections_into_gate.py`, the removed verdicts kept in
`data/backup/store_blocklist_rejections_removed_2026-09-28.json`), and the view
asks the gate for every term and every relation target through
`ConceptStore.scope` -- the cleaner's Blocker, so gate verdicts, the exact lists
and the keywords in rule 40's order. `clean_entities` and `clean_targets` now
report and write nothing. `rejected` and `relations` remain for verdicts that
are NOT about scope: the predicate filter, the prune, the reasoner gate.
Measured when it was applied: 331 terms came back (rejected then, in scope now:
`pain score`, `donor site`, `MRSA`), 2,394 left (out of scope now, never
rejected: `patient`, `complication`, `risk factor`), and the names downstream
went from 79,755 to 77,692. The largest leavers were out on an exact-list entry
with no author, which is why gate pass 2's `unaudited` queue runs next.

Enforced by: `ConceptStore.view` / `resolver` / `trace` / `_spell_ingested` /
`_scope_test` (`scope`),
the refusal in `ConceptStore.__init__`, `store_name`;
`TermMappingAndGate.spell` / `resolve` / `is_alias` / `aliases`, the alias
handling in `apply_renames` and `_absorb`, `record()` resolving aliases;
`Orchestrator.run_pass0_normalise` (one write, aliases skipped as terms).
`tests/test_evidence_and_decisions.py` (14 tests) plus the rewritten store,
pass 0, splitting, singular and inert-mapping tests, mutation-checked against
12 breakages: no alias for undecided strings, relation targets not respelled,
`record()` not resolving aliases, `spell` overwriting decisions, a merge
dropping a rejection, the alias not written, ingestion re-spelling a settled
name, a view ignoring spelling, mapping or cell verdicts, a legacy file
accepted, and verdicts matched on the final name only.



## 52. A category name is never gated, and a spelling decision can be reversed

**Decided 2026-09-28.** Two things found the same afternoon.

*Categories.* Gate pass 2 was run over the undecided names, and the fifteen
BFO category names (`process`, `material entity`, `quality`, ...) were among
them, because every abstract types its terms with `is_a: <category>` and a
category name is therefore a relation TARGET like any other. The model
answered `out` for all of them ("generic upper-level class, not
wound-specific"). The view drops a cell whose target is out of scope (rule
51), so that one answer removed **every typing in the store** -- 179,497
cells -- and with it the category that the mapping guard, the hierarchies and
the reasoner gate read. Nothing raised; two guard tests failed because
`Necrosis Process` no longer had a category to refuse on. A category is
declared, never matched (rule 20) and never renamed (rule 22); it is also
never gated. The view treats a declared category as in scope whatever the gate
says, and pass 2 no longer asks about one. The 13 pass-2 answers already on
record are left as written and have no effect.

*Reversal.* The curator reversed rule 49's -ic choices (below). Pass 0 had
written `pharmacological X -> pharmacologic X` as an alias; renaming
`pharmacologic X` back made that alias point at itself, and `apply_renames`
refused the whole write as a clash. A rename that sends the current spelling
back onto its own alias now retires the alias into `spelling_reversed` on the
restored record, which is the shape the rule 51 migration already used for 27
such strings.

*Rule 49 amended (curator, 2026-09-28: "exactly the other way").* The -ic /
-ical pairs are written -ical: `dermatologic -> dermatological`, `oncologic ->
oncological`, `pharmacologic -> pharmacological`, `physiologic ->
physiological`, `radiologic -> radiological`, and new `biologic(s) ->
biological(s)`, with the product name `XCM BIOLOGIC` protected.
`histopathological` already pointed this way; `numerical -> numeric` is
unchanged and is the one pair still pointing to -ic.

Enforced by: `ConceptStore._scope_test` (declared categories exempt),
`scripts/p4_gate_pass2.py` `wanted()`, the reversal branch in
`TermMappingAndGate.apply_renames`, `utils.normalise.CANONICAL_WORDS` and
`PROTECTED_PHRASES`. Tests: `test_a_bfo_category_is_never_out_of_scope` (4),
`test_a_spelling_decision_can_be_reversed`,
`test_a_reversed_spelling_with_no_decisions_leaves_no_empty_record`,
`test_ical_is_the_preferred_form` (4), `test_biologics_in_the_plural_become_biologicals`,
`test_a_product_name_keeps_its_biologic`, and the flipped rule-49 cases;
mutation-checked against 7 breakages, all caught.


**Added 2026-09-30.** Nor is a category class ever the subject of an abstract's
relation in the reasoner gate. `tendency --has realization--> therapy`, from
one abstract about the bare word, was asserted on MILD's tendency class; once
`therapy` was ruled an information entity the class became unsatisfiable,
and so did every tendency and every curated class that mentions one -- 7,361
classes, 20,844 relations quarantined. The gate now holds such a relation
back by name before reasoning (`ReasonerGate.check`;
`test_a_relation_on_a_category_class_is_held_back_not_reasoned`), and a
timed-out `robot explain` is reported instead of aborting the run.

The same night showed the general form of that failure: one relation that is
wrong by itself on a hub term (`healing --has as process boundary at end-->
completely healed`, a quality where an instant is required) makes the hub
unsatisfiable, and the gate's "drop every relation touching an unsatisfiable
term" then quarantined 20,777 relations. Found by delta debugging down to six
relations. The gate now first asserts every relation on a fresh copy of its
subject and object (category and grounding only) and reasons once: a copy
that is unsatisfiable is a relation wrong on its own, and it alone is held
back before the batch is reasoned (`_locally_inconsistent`;
`test_a_relation_wrong_on_its_own_is_held_back_without_taking_its_neighbours`).

## 53. A treatment approach is a therapy; NPWT has one name

**Decided 2026-09-28 (curator).** Three more preferred names, applied by pass 0.

*Therapy.* `... approach`, `... strategy` and `... intervention` are written
`... therapy` -- but only as the HEAD noun and only where the word names a
treatment. Measured first: the three words sit in 1,570 names, and a blanket
rename writes `search therapy`, `coping therapy`, `diagnostic therapy`,
`surgical therapy` for an access route, and `therapeutic therapy`. So:
`therapeutic`/`treatment` + the word collapse to `therapy`; a prevention or
preventive strategy is `prophylaxis`, which WONT models as a plan
specification apart from treatment; and the word stays where the modifier is
method (search, coping, implementation, GRADE, design, evaluation,
assessment, research, statistical, educational, management, care ...), an
access route (surgical, open, invasive, endoscopic, anterior ...) or a time
point (pre-/post-intervention). Outside the head, rule 48's strategy ->
approach still applies. Applied: 1,205 renames; `interventions` alone was 141
mentions and `surgical intervention` 97.

*NPWT.* NPWT, VAC, V.A.C., vacuum therapy, vacuum-assisted closure and
negative pressure therapy are `negative pressure wound therapy`, inside
compounds too (`VAC dressing`); a trailing therapy/treatment is absorbed.
Vacuum sealing drainage is a different technique, and the endoscopic and
endoluminal vacuum procedures for gut leaks are too. `NPWT` itself (101
mentions) had never been merged with its expansion.

*-ical.* `numeric -> numerical` joins rule 52's flip, so every -ic/-ical pair
now points to -ical.

Enforced by: `utils.normalise._therapy_head` and the `THERAPY_*` sets,
`_npwt` / `NPWT_SYNONYM`, `CANONICAL_WORDS`. Tests in `tests/test_pass0.py`:
`test_a_treatment_approach_is_a_therapy` (18), `test_vac_and_vacuum_therapy_are_npwt`
(13), `test_what_is_not_npwt_keeps_its_name` (4); mutation-checked against 7
breakages (each exception set, the collapse, the whole rule, the therapy
absorption, the endoscopic exemption, the numerical flip), all caught.

*`diabetes mellitus` (found the same day).* Rule 49's modifier choice
`diabetes -> diabetic` fired on `diabetes mellitus` and wrote `diabetic
mellitus` into 28 names (259 mentions), because `mellitus` looked like the
noun it modifies. `mellitus` and `insipidus` are now blockers
(`test_diabetes_mellitus_is_a_name_not_a_modifier`). Fixing the rule did not
fix the names: pass 0 normalises the CURRENT spelling, and `diabetic mellitus`
no longer contains anything the rule touches. A rule that wrote a wrong name
therefore needs a one-off correction of the names it wrote -- done here as 19
renames `by: "pass0 correction ..."`, 17 of them reversing the pass-0 alias.
`ConceptStore.apply_renames({})` also returns a full report now; pass 0 with
nothing to do had crashed printing it.


## 54. A leading grade or word of praise is not part of the name

**Decided 2026-09-28 (curator, Naming Rulings page, one row per word).** 40
leading words are stripped by pass 0 -- the praise and filler words (`novel`,
`effective`, `optimal`, `key`, `advanced`, `conventional`, `standard` ...) and,
on the curator's choice, the grades as well (`massive`, `severe`, `mild`,
`moderate`, `large`, `extensive`, `major`, `minor` ...): `massive rotator cuff
tear` is a rotator cuff tear. `small` and `big` are left alone; `giant` is
kept and the name recorded as a `narrower` subtype of the name without it.

Stripped from the front only, repeatedly (`severe, extensive burns` -> `burn`),
never from a one-word name, never before a function word (`standard of care`),
and never from a name that starts with an exception: the curator's own
(`major amputation`, `Large wound` -- a defined WONT class --, `moderate to
severe`, `current smoker`, `mild cognitive impairment` ...) and a second list of
fixed names the review never showed because they were out of scope when the
page was built (`standard deviation`, `multiple sclerosis`, `major adverse`
event composites, `traditional Chinese medicine`, `new onset`). Applied: 2,128
renames; a `narrower` answer whose term the strip turned into an already-mapped
term (`major SSI` -> `SSI`) is dropped, since it is now that term.

Enforced by: `utils.normalise._strip_leading_adjectives`, `LEADING_ADJECTIVES`,
`LEADING_ADJECTIVE_EXCEPTIONS`; `test_a_leading_grade_or_praise_is_stripped`
(14), mutation-checked against 3 breakages (the whole rule, the exceptions, the
function-word guard).

**Extended 2026-10-25 (curator: "diese ganzen adjektive wie poorer oder severly
sollten eigentlich schon lange gelöscht sein"; "dann lösch neben large auch
large-scale").** The same words compared, superlative or as an adverb are
stripped too (`_GRADED_FORMS`: `poorer`, `worse`, `worst`, `best`, `larger`,
`milder`, `severely`, `mildly`, `moderately`, `markedly`, `extensively`,
`potentially`, `appropriately`, `excess`), and `large-scale` whole
(`LEADING_COMPOUNDS`). Not `poorly`: `poorly controlled diabetes` and `poorly
vascularized tissue` would become their opposite. Not `newly`, `currently`,
`conventionally`: they do not grade. New exceptions are fixed names: `worst
itch` (a scale), `best corrected visual acuity`, `best practice`, `BEST-CLI`,
`moderately differentiated` (a tumour grade), `extensively drug-resistant`,
`largest Lyapunov exponent`, `larger wound` (as `large wound`).

**Never at a hyphen.** A hyphen makes one compound modifier, not a grade and
its noun. The rule cut there from 2026-09-28 to 2026-10-25, and 81 spellings
had become names nobody wrote: `Vessel vasculitis` for `large-vessel
vasculitis`, `Stage pressure ulcer`, `Of-care dressing`, `To-moderate
sarcopenia`. Repaired by `scripts/apply_adjective_forms_2026_10_25.py`: 50 cut
names renamed back, 7 kept where the abstracts wrote the short form too (`Risk`,
`Stage`) with only the hyphenated spellings freed. Two curator verdicts of the
same morning that kept a graded term apart from its base (`Burn patient` broader
than `Severely burned patient`) moved to `curator_history`: the rule makes them
one class. Tested in `test_a_leading_grade_or_praise_is_stripped`.


## 55. A rebuild never undoes a curator's mapping, under any spelling

**Decided 2026-09-28**, after the first rebuild following the day's reviews undid
curator decisions three ways, none of them loudly:

1. *Cycles.* The curator made `microRNA` the name (`miRNA -> microRNA`); the
   rebuild re-proposed `microRNA -> miRNA`, the two formed a cycle, and the
   frequency election retired the curator's entry. `resolve_chains` now elects
   the target of a curator-ruled live pair; and a curator's reversal also
   refuses the backward pair, so it is not proposed again.
2. *Spelling of the pair.* `bone infection -> Osteomyelitis` was ruled under
   the spelling the review showed; the rebuild re-spelled the canonical to the
   class label, and pass 1's cached `narrower` on the new spelling withdrew the
   mapping. The withdrawal now looks for a curator verdict on any pair whose
   key folds to the live target, and withdraws only the live mapping it objects
   to, never a term since mapped elsewhere.
3. *Typings read through the mapping.* The category guard asked for the
   typing of `Necrosis Process` in the MAPPED view, where an accepted mapping
   onto `Necrosis` had already absorbed it -- so it found none, allowed the
   mapping, and the mapping hid the evidence. `store_typings` reads the
   unmapped view. A sweep then withdrew the 21 live mappings the guard refuses
   and no curator ruled on.

Enforced by: `TermMapper.resolve_chains` (cycle election),
`Orchestrator._adjudicate_anchor_mappings` (`ruled`, `is_live`),
`Orchestrator.store_typings`, `scripts/apply_scope_notes.py` (reversal
refuses). Tests: `test_a_cycle_elects_the_curators_target_over_the_commoner_spelling`,
`test_a_curator_ruling_under_the_old_spelling_still_protects_the_live_pair`
(both mutation-checked), and the live guard tests in
`tests/test_ontology_anchors.py`, which caught (3).


## 56. Rule 49's `trauma -> injury` is withdrawn

**Decided 2026-09-28 (curator: "Trauma into injury is wrong").** A trauma is the
event; an injury is what it leaves. The word rule is removed from
`CANONICAL_WORDS` (`test_trauma_is_not_renamed_injury`), and what it had
written was undone by `scripts/revert_trauma_rule.py`, because pass 0 cannot
see a rule that no longer matches the current spelling (the rule 53 lesson):
233 names built only from trauma strings were renamed back with their
decisions (`psychological injury` -> `psychological trauma`); in 56 names that
also held genuine injury strings (`head injury` from `head trauma` and `head
injury`) only the 78 trauma strings were given their own name, which starts
without a scope decision. Read back: no string the abstracts wrote with
`trauma` resolves to a name with `injury`.

The same day the curator put the bare words `injury` and `treatment` back in
scope (a `curator` verdict), reversing the merged-scope ruling that had put
them out; names containing either word keep their own decisions.

## 57. A decided category is a term decision; a head rule settles only a dispute

*Storage superseded 2026-10-26 by rule 87: the decision is the decided `is_a` cell in `relations`, no longer a `category` section. What it decides and how the view applies it are unchanged.*

**Decided 2026-09-29.** When the abstracts type a term irreconcilably (a
process in one, a material entity in another) the term has no category and
cannot be placed. A person's decision about it lives in the term dict as the
record's `category` section (`verdict`, `source`, `by`, `note`, `when`), and
the view types every mention of the term with it: a category cell at or below
the decision stands, every other category cell is replaced by the decision, a
mention the abstract gave no category keeps none, and a non-category `is_a`
(`is_a: Wound`) is untouched. The concept store keeps what each abstract said
(rule 50). When the view stops at the spelling, a synonym takes its
canonical's decision.

Precedence: a WONT/MILD class keeps the ontology's category; a `term ruling`
outranks a `head rule: <word>` and is never overwritten by one
(`set_category` returns `kept`); a later term ruling replaces a head rule and
keeps it under `history`. Two spellings decided differently are reported as
`category conflicts` when they merge.

Head rules (`config/category_head_rules.py`, the Signature Words page): the
head word is the word before the first preposition, else the last. **A head
rule decides only a term whose abstracts disagree irreconcilably** (curator:
"disputes only"). Measured before applying: 601 disputes settled, but 2,406
terms every abstract typed alike would have flipped (`systolic blood
pressure` quality -> information entity), so the rule does not reach them.

`temporal region` (BFO_0000008, under occurrent, disjoint from process) was
added as a category the same day for `operative time`, `hospital stay`, `time
to healing` -- a stretch of time, not what happens in it.

Applied by `scripts/apply_category_rulings.py` (dry by default, backup, read
back from the file and from the view); measured by
`scripts/measure_head_rules.py`. Tests: `tests/test_category_decisions.py`.

## 58. No abbreviations, and no guessing which string is one

**Decided 2026-09-30 (curator: "no abbreviations ever"; "no guessing here").**
A term that is only an abbreviation is never a class name. Which string is
one is decided by a typographic rule, not a model: one token, no lowercase
letter except a plural `s`, at least two capitals (digits and `- / & + .`
allowed) -- `TEN`, `TEWL`, `PT/OT`, `20CRW`. Such a term goes out of scope,
or is mapped to its full form when the full form is known without guessing
(the curator named it: `AKI -> acute kidney injury`). A curator's own ruling
on an abbreviation stands and is reported (`MRI` was ruled a material
entity). Strings the rule misses because they hold lowercase letters
(`iNPWT`, `SSc`, `PI3K/Akt`) are the curator's to rule, not the rule's.

The full form is read from the abstracts (Schwartz & Hearst, plus a check
that the long form spells the letters word by word, which refuses
`protective equipment` for PPE): `scripts/expand_abbreviations.py`. Then the
curator's rule (2026-09-30): **no full form in any abstract -> out of scope;
abstracts defining it as different things -> out of scope (`PI` = pressure
injury / plaque index / povidone-iodine, `FG`, `SSD`); one concept spelled
differently -> kept under one full form (`PAD` artery/arterial, `VAS`)**
(`scripts/apply_abbreviation_rulings.py`). Measured: of 1,556 in-scope
abbreviation-only names, 825 renamed, 726 out, 5 already ruled.

## 59. A placement stands only after a second check; a refused parent is kept as a suggestion

**Decided 2026-10-01 (curator: "these have to be checked again, maybe with a
better model, maybe you check all of them yourself").** The placement model's
answer (`is_a` / `same` / `none` against the ten nearest WONT/MILD/module
classes) is a proposal, never a decision. Every `is_a` and `same` answer gets
exactly one independent second check before it is used:

* the most reliable 2,309 (an `is_a` mentioned in two or more abstracts whose
  parent shares a word with the term or sits at SapBERT >= 0.65, and every
  `same` at >= 0.75) get a yes/no question to the model, one statement at a
  time (`scripts/p4_verify_placements.py`): 1,510 + 203 yes, 453 + 143 no;
* the other 16,150 were read row by row by Claude
  (`data/review/placement_selfcheck_2026-10-01/verdicts_XX.txt`): 4,100
  parents refused, 79 replaced by one of the offered alternatives, 89 `same`
  demoted to `is_a`;
* 143 answers name no offered class or none at all and are dropped.

A refused parent is not deleted: the term becomes a `candidate` with the
refused parent kept as `suggested`, so a curator sees what was proposed. A
term the model placed nowhere stays `unplaced`. The join is
`scripts/merge_placement_checks.py` (refuses on a row in both checks, a row
with two verdicts, or an alternative whose label resolves to other than one
class; writes `placement_merged_2026-10-01.json` and reads it back): 13,453
placed, 310 synonyms, 4,696 candidates, 15,055 unplaced, 143 dropped.

The failure that motivated it: the sandbox review found generic parents
taking whatever was near them -- procedures under biological processes,
brain injuries under `Traumatic wound`, risk scales under `Wound
classification grade`, anatomical regions under `spatial region` -- at
10-30% of rows per chunk, worst under `planned process`, `polymer`,
`tissue remodeling` and `Wound`.

A reply that hits the token cap is reported and its rows left unanswered;
a rerun with `--batch-size 5` asks only those (7 batches, 140 rows, on
2026-10-01).

**Then every verify row was read by Claude too (curator: "do it").** The
model's yes/no is a check, not the last word: `placement_verifycheck_2026-10-01/`
holds the 2,305 rows still current, with the model's answer and reason on
each line; Claude lists only where it disagrees (`n:Y` accept against a
model no, `n:0` refuse against a model yes, `n:I`, `n:1..4`), an unlisted row
agrees. Disagreement measured: 200 of 2,305 (8.7%) -- 89 refused that the
model accepted (procedures under biological processes such as `rotator cuff
repair < Tissue repair process`, scar and risk scales under `Wound
classification scale`, `PI ...` abbreviations, non-wound infections), 68
accepted that it refused (mostly wording objections: `material complication
disease entity`, misspellings, `-ation` forms), 41 `same` demoted to `is_a`.
The merge takes Claude's verdict where one is listed. After it: 13,446
placed, 331 synonyms, 4,680 candidates, 15,055 unplaced, 143 dropped.

**ELK before anything is written (curator: "what does elk have to say").**
`scripts/elk_check_placements.py` asserts every `placed`/`synonym` outcome on
the skeleton TBox -- the term as a fresh class under its own category and
under its parent (or equivalent to its class) -- and reasons once with ELK.
2026-10-01: 13,778 asserted, 0 unsatisfiable placements, 0 existing classes
made unsatisfiable; the check was shown to fire by injecting a process under
`Wound` (ELK names it). ELK can only catch a placement that contradicts its
category; a consistent but wrong parent is what the row-by-row reading is for.

**Order (curator, 2026-10-01: "we do fca first"):** placements are written
into the term dict, then FCA runs, and only then is the WONT addition built
-- never placements straight into `wont_extended_core.ttl`.

## 60. A label is never mapped away (rule 36, closing its gap)

**Found 2026-10-01** while asking why placement `same` answers slipped the
mapping. Anchors are the labels no abstract wrote; a label an abstract DID
write is ranked by corpus frequency like any store string and can lose:
18 WONT/MILD labels pointed at a store spelling (`Wound treatment process ->
wound therapy`, `Impaired wound healing process -> impaired wound healing`,
`Wound healing by primary intention process -> Wound healing by primary
intention`), three against a curator who had kept the label direction (a
rule 55 breach too). Rule 1 of the canonical policy only re-spells what
folds to a label, so it never saw them.

`TermMapper.enforce_canonical_policy` rule 4 turns such an entry round: the
store spelling and everything mapped onto it map onto the label, the label is
unmapped with the reason on record. A curator's direction (`method: curator`,
or `reverse` on the opposite pair) is held and reported (`painful -> painful
condition`, `threshold value -> threshold`); a turned-round claim the category
guard refuses only unmaps the label. Every build runs it. Tests:
`tests/test_canonical_policy.py` (rule 4, four tests, mutation-checked).
Applying it to the current file alone, without rules 1-3's other pending
changes: `scripts/apply_label_restore.py --write` -- written and read back
2026-10-01: 16 labels canonical again, 27 entries onto them.

The same day the curator refused 12 kept merges whose canonical adds a
qualifier that narrows the meaning (`wound healing -> impaired wound
healing`, `injury -> traumatic injury`, `mobility -> reduced mobility`,
`oxidative stress -> high oxidative stress`, ...): a review-page keep of a
whole cluster at one timestamp let the broader term through with its
narrower siblings. Found by listing every mapping whose canonical's words
strictly contain the term's (704) and reading the added word. Written with
`scripts/curator_refuse_pair.py` (refused, not deleted; the old `kept` under
`curator_history`).

## 61. Disorder wins; pressure injury is pressure ulcer -- inside every name

**Decided 2026-10-02 (curator: "illness, disorder, pathology, disease,
condition and dysfunction are used completely interchangably" -- "disorder
wins. condition can stay where it is a condition"; "pressure ulcer and
pressure injury are the sam thing. still, there is sacral pressure ulcer and
sacral pressure injury").** Two pass 0 rules in `canonical_vocabulary`, applied
inside compound names as the NPWT rule is (rule 53):

* `pressure injury/injuries -> pressure ulcer(s)` (`_pressure_ulcer`): 161
  names, 20 of them merging with an existing pressure-ulcer name.
* `disease, illness, pathology, dysfunction -> disorder` (`_disorder`). Kept:
  eponyms (`Crohn's disease`, `Buerger disease`), fixed names (`multiple organ
  dysfunction syndrome`, `critical illness`, `illness perception`), `pathology`
  the discipline (`surgical pathology`, `pathology report`), and proper names of
  institutions, classifications and instruments (`Centers for Disease Control`,
  `International Classification of Diseases`, `Global Burden of Disease`,
  `Ocular Surface Disease Index`) -- `DISORDER_KEEP`. `condition` becomes
  `disorder` only in the 90-odd names listed in `DISORDER_CONDITION`, read one
  by one from the 233 that use it; `wound condition`, `hypoxic condition`,
  `culture condition` name a state and stay.
* A WONT/MILD label keeps its own word (`Autoimmune disease`): pass 0 keeps
  labels as written and the variants join it.

Applied by pass 0: 1,060 renames, 48 groups merged (`skin condition`, `skin
disease`, `skin dysfunction`, `skin pathology` -> `skin disorder`). The first
run also renamed 40-odd proper names (`Centers for Disorder Control`); the
phrases were then protected and 33 names given back their word
(`scripts/restore_disease_proper_names.py`, reversal through `apply_renames`).

Found on the way: a rename did not reach the sense labels of a two-senses
ruling (`biopsy` -> `biopsy specimen`, renamed to `biopsy sample` on 09-27), so
the view kept writing the old spelling. `apply_renames` now renames sense
labels too (`test_a_rename_reaches_the_sense_labels_of_a_two_senses_ruling`).

## 62. No abbreviations, widened: mixed case, and inside names

**Decided 2026-10-02 (curator: "there are still abbreviations like MSC-Exo and
i-PRF" -- "keep microRNA send the rest out" -- "inside names too please").**
Rule 58's typographic test missed abbreviations holding lowercase letters.

* **Whole names** (`scripts/expand_abbreviations.py --wide`, then
  `scripts/apply_abbreviation_wide.py`): one token with a run of two or more
  capitals. Every row read; the rule of 2026-09-30 applied: 90 mapped onto
  their full form (`i-PRF -> injectable platelet-rich fibrin`; three corrected
  where the match lost a word: `sTBI -> severe traumatic brain injury`), 246
  out of scope, `microRNA` kept.
* **Inside names** (`scripts/expand_abbreviations_inside.py`): every part of a
  name holding two capitals in a row (Roman numerals, chemical formulas such
  as `CO2`, isoform suffixes such as `factor-BB`, and `microRNA` excepted) is
  written out from, in order, the name's OWN abstracts (an abbreviation means
  what its papers say: a corpus-wide lookup had made `4-HNE` "human neutrophil
  elastase"), rule 58's decision on that abbreviation, and an exact synonym the
  ontology lists for one class (`RNA`, `NK cell`). One form -> renamed (pass 0
  style, alias kept); none or several -> the name goes out. Applied: 2,116
  renamed, 1,026 out of scope.

**Incident, same day.** A dry run of the inside-names script wrote 1,026
out-of-scope verdicts: a helper named `write` shadowed the script's `--write`
flag. The term dict file it saved was moved to `data/quarantine` and the
previous version (byte-identical to the backup taken one step earlier) became
the latest again; nothing of it remained. The flag is now `DO_WRITE` and the
write path re-checks `--write` in `argv`.

**Second incident, same day: the renames were wrong where nobody had read
them.** Checking the newly placed names turned up `Z-deep neck abscess-binding
protein 1`; a read of all 2,116 renames found about 120 wrong. Causes, and what
replaced them (version 2 of the script, every changed row read):

* *A whole-name decision taken from one abstract, used for every name.* `DNA`
  had been defined once as `deep neck abscess` (PMID 41841442) and rule 58
  mapped it so; seven of its eight abstracts mean the molecule, and every
  `... DNA` name followed (`cell-free deep neck abscess`). Likewise
  `alpha-SMA -> alpha-supplementary motor area`, `SOD activity -> semiocclusive
  dressing activity`. Every rule-58 decision whose term is used in more
  abstracts than define it was checked by reading each undefined use: 22 are
  used for different things in their own abstracts (`NLR` = neutrophil ratio /
  negative likelihood ratio, `DF` = diabetic foot / dermal fibroblast, `PM`,
  `TM`, `CAD`, ...) and go out (`WHOLE_OUT`); `DNA` is mapped to
  `deoxyribonucleic acid`, the meaning of 7 of 8 abstracts and of the corpus's
  own definition (PMID 42579608).
* *The shortest tail.* Schwartz & Hearst took `level laser therapy` for LLLT,
  `saphenous vein` for SSV. `spelled_definitions` (in
  `expand_abbreviations.py`) takes the tail that spells the abbreviation letter
  by letter with one content word per letter where it can (`low-level laser
  therapy`), and refuses sentence fragments and a long form holding its own
  short form (`the APG group`). Whole names corrected the same way: `LLLT`,
  `OOT`, `PEGDA`, `PPC`, `PI-DGAME`.
* *The fill from elsewhere.* A part the name's abstracts leave undefined may
  still be filled from the whole corpus, but only when every spelled
  definition there and the curator's decision name ONE concept, and every such
  fill was read: 40-odd borrowed a meaning that is not the paper's (`AMP-activated
  protein kinase -> antimicrobial peptide-...`, `HO-1 -> heterotopic
  ossification-1`, `Braden QD -> quantum dots`) and are refused by name
  (`READ_OUT`).
* *Smaller faults.* Doubled words (`wound bed score score`), abbreviations left
  inside the written-out form (`enhanced PRP`), a token and its part replaced
  over each other (`...stem cellsnchymal stem cell`), `IL` read as a Roman
  numeral (so `IL-6` was never written out), full-width brackets. The curator's
  one-concept lists (KEEP, 2026-09-30 and 2026-10-02) and the abbreviations the
  curator kept as names (`RNA`, `MRI`, besides `microRNA`) now count inside
  names too.

Applied (`--write`, read back): 441 renamed (330 of them first-run outs that the
corrected reading writes out; their out lifted), 56 out, 6 whole names
remapped, 22 whole names out. Report: `output/abbreviation_inside_v2_2026-10-02.json`.

**And a scope leak.** Scope is pooled over a concept (rule 28), so an
abbreviation ruled out while still mapped onto its full form put the full form
out: `DF` took `diabetic foot` with it, `%TBSA` `total body surface area`,
`BMP-2` `Bone Morphogenetic Protein 2` (26 full forms). A rule-58 out now
unmaps the abbreviation (`scripts/fix_out_leaks.py`, refusal kept); `NLR`, `EC`,
`GF`, whose full form's curator `in` had swallowed the out, unmapped the same
way. The disorder rule's protected phrases gained `disease-modifying` and
`coronavirus disease` (8 names given back their word).

**Review page, three outcomes per term (curator, 2026-10-02).** On the
superclass/synonym review page a term is *accepted* (the class stands),
*refused* (the class is wrong; the term stays in scope and keeps it only as a
suggestion), or *excluded* ("add a button to exclude a term. some are not
necessary or unspecific nonsense like clinical method"): the term itself is
not wanted and goes out of scope, as a curator gate verdict. The step that
writes the page's decisions into the term dict must honour all three. The
page edits a copy of what it loads: stored documents come back read-only, and
editing them in place made every click on an already-decided group fail
silently.

## 63. One class per label

**Decided 2026-10-02 (curator: "wont has its own disease class. dont reuse
ogms. same with the protein class. we dont need several class of several
ontologies with the same name that have some wont classes as children").** 17
labels exist in more than one ontology of the class pool, and WONT itself holds
bare HP/DOID copies (`Abscess`, `Pressure ulcer`, `Osteomyelitis`,
`Lymphocele`) beside its WONT_ class. A superclass or synonym target is always
the one class for its label: the ground truth's own copy (its WONT_ class
first), then MILD, then COB, then UBERON. OGMS `disease` (a disposition) is
replaced by MILD `material disease entity`, where the curator's ruling of
2026-09-29 already sends the word; the 89 terms placed under it are retyped
material entity. Enforced in `scripts/merge_placement_checks.py`
(`one_class`, `REDIRECT`): 425 targets redirected. ELK then found one term
whose typing contradicted the WONT class it now sat under (`cervicofacial
abscess`, typed disposition), retyped with the reason (`RETYPE`). The import
modules themselves still carry the duplicate classes; removing them is module
work (rule 34).

## 64. Placements enter the hierarchy as `placed`, behind an evidence cut

**Decided 2026-10-02 (curator: "go on with what we have now and work through
the rest with fca and proper ontology at the end"; then, on the first view of
the tree, "so many nonsense terms" -- ">=2 abstracts" -- restatements "check
and convert").**

* **Applied as the page stood** (`scripts/apply_placements.py`): a kept
  superclass becomes the pair judgement `placement: {verdict: narrower}`
  (13,143: 3,809 accepted, 9,334 by the page's default "accepted unless
  refused"); an accepted synonym is mapped (318); a refusal is a refused pair;
  an exclusion a curator gate `out`. Undecided synonyms would not be mapped
  (none were left).
* **A fourth hierarchy source, `placed`**, ranked curated (4) > placed (3) >
  text (2) > fca (1): checked twice, so above what one abstract implied; not
  authored, so below WONT/MILD. Read from `TermMappingAndGate.placements()`
  (refused pairs, mapped terms and out-of-scope terms give no edge) by
  `run_build_hierarchies` into `BaseHierarchy.get_data(placed=...)`.
* **Evidence cut**: a placed term becomes a class only when
  `PLACEMENT_MIN_ABSTRACTS = 2` abstracts mention it. 76% of the placements
  (9,997 of 13,146) rest on one abstract; below the cut the placement stays in
  the term dict, unbuilt, and comes back the moment a second abstract names
  the term.
* **Restatements**: a kept placement that only renames its class ("wound
  assessment" under Wound diagnostic process) is not a subclass. Each kept
  placement is asked `same / narrower / unclear`
  (`scripts/p4_restatement_check.py`), every `same` is read by Claude, and the
  confirmed ones become synonyms of the class.
* First ELK run on the rebuilt hierarchy: 216 edges quarantined, all `text`
  (typings that contradicted a placement); every placed edge kept.
* The hierarchy reads WONT/MILD subclass axioms only, so classes the
  placements use from the import modules (`planned process`, `1-D extent`)
  appear without a parent -- to be fixed before the build.

## 65. FCA reads an unstated property as absent; ancestors pass down only corroborated attributes

**Decided 2026-10-02 (curator: "Absent = false"; on inheritance: "class level
only inheritance and everything inheritance, that I don't make a guess but a
data driven choice").**

* **Closed world, for FCA only.** A property no abstract states of a class is
  read as not holding, one lattice is built, and every concept is certain
  (`ConceptLattice.get_data_and_run_fca(unknown="absent")`, the `run_fca`
  default). The cells read that way are counted and printed. The ontology
  itself stays open world; FCA output is a suggestion that is reviewed anyway.
  Motivated by the Wound subtree: the open-world dual build left 23% of the
  context undecided and gave 1 certain concept, 0 named.
* **Evidence cut on attributes** (`ContextMatrix.get_data(min_support=2)`): a
  measured attribute counts only when two abstracts state it of that object.
  `Wound` is named in 1,013 abstracts and carried 207 attributes, 145 of them
  from one abstract each (`skin itching`).
* **Class-level inheritance** (`inherit="class_level"`, the `run_fca`
  default). An ancestor's attribute passes to its subclasses only when its own
  descendants state it significantly more often than everything outside its
  subtree does: one-sided Fisher exact test over every store entity with
  measured attributes, Benjamini-Hochberg at FDR 0.05
  (`ContextMatrix._class_level_attributes`, every test kept in
  `inheritance_tests`). An attribute that no descendant can corroborate (none
  has measured attributes) is not inherited. No cut on the share of the
  ancestor's abstracts: the top attribute of `Wound`, `wound area`, is in 3.2%
  of them, so any guessed share decides the outcome by itself.
* **Chosen by measurement** (`scripts/fca_inheritance_compare.py`, output
  `data/review/fca_inheritance_comparison_2026-10-02.json`). On the Wound
  subtree, 322 objects × 94 measured attributes:

  | inherit | inherited cells | hierarchy edges contradicted | concepts | new groupings | members' own cells |
  |---|---|---|---|---|---|
  | all | 20,564 | 0 / 326 | 47 | 5 | 1% |
  | class_level | 11,231 | 174 / 326 | 53 | 5 | 22% |
  | none | 0 | 197 / 326 | 93 | 18 | 100% |

  `all` and `class_level` propose the same groupings, but under `all` each one
  pulls in 20 to 52 descendants that state none of the shared attributes.
  `class_level` keeps the groupings and drops the passengers. The contradicted
  edges cost nothing downstream: `fca` is the lowest-ranked source and enters
  only after review. `none` gives more groupings, but 9 of its 18 rest on
  `part_of: <a wound class>`, a misread subclass statement (below).
* **Limit, measured:** only 29 of the 322 Wound classes have any attribute
  (has_quality, part_of, has_participant, has_disposition, inheres_in) stated
  in two abstracts. FCA can only group among those.
* **Open:** `part_of` between a wound and a wound class (`Heel Pressure Ulcer
  part_of Pressure ulcer`, `Wound part_of Wound`) is a misread `is_a` and
  passes the class-level test. It must not become a part_of axiom in the WONT
  addition.

## 66. Few good axioms over many bad ones: a relation enters the ontology only when both ends are typed right

**Decided 2026-10-02 (curator: "Has quality contamination, which might be a
material entity, makes no sense ontologically ... I'd rather take little nodes
and edges and add them to the onto than bad ones").**

* **Precision over recall.** A relation that cannot be shown sound stays out,
  even when it might have grouped correctly in FCA.
* **Typing check on both ends** (`scripts/relation_typing_check.py`, output
  `data/review/relation_typing_check_2026-10-02.json`). A term's OWN category
  (its most specific BFO ancestor in the class hierarchy, read against a fixed
  BFO tree) must be what the predicate requires (RO/BFO domain and range:
  has_quality -> quality, has_disposition -> disposition, inheres_in ->
  specifically dependent continuant to independent continuant, part_of /
  has_part -> both ends of one kind, ...). Verdicts: ok / violates /
  undetermined. Only `ok` may become an axiom.
* **Measured on the store view, 26,372 relations:** 21,061 ok, 2,097 violate,
  3,214 undetermined. With >= 2 abstracts: 1,349, of which 1,007 ok, 107
  violate, 235 undetermined. Examples: `Wound has_quality contamination`
  (contamination typed material entity) violates while `Wound has_quality
  contaminated` passes -- the two are not synonyms; `Diabetic foot ulcer
  has_quality material disease entity` (6 abstracts) violates.
* **Wrong values are dropped, not repaired.** Of 156 wrongly typed values on
  has_quality / has_disposition / has_function / has_role, 4 have a same-stem
  term of the right category, and the main one (`time to healed`) is junk.
* **Why ELK did not catch it:** the skeleton TBox carries no domain or range
  for RO_0000086 has quality, BFO_0000197 inheres in or RO_0000091 has
  disposition, so a restriction with a material filler on has quality clashes
  with nothing. The relation gate (`run_gate_store_relations`) last ran
  2026-10-01, before the renames of rules 61-63.
* **Found on the way:** the class hierarchy puts Role under Quality (BFO: under
  realizable entity) and leaves Disposition, Function, Realizable Entity and
  Process Boundary without a parent.
* **Still open:** one abstract's report about a wound is not a property of
  every wound (`Wound has_quality contaminated`: there are clean wounds). The
  export (`owl/extend.py`) writes every store relation as `C SubClassOf R some
  T` and 23,392 of its 24,621 relations rest on one abstract; the class-level
  test of rule 65 inherited `contamination` to every wound, because enrichment
  is not universality. A relation needs a universality reading (all / some)
  before it becomes an axiom.
* **Universality, read by Claude 2026-10-02** (curator: "do it yourself").
  Every one of the 1,007 relations with >= 2 abstracts and both ends typed
  right was read as the axiom it would become, `C SubClassOf R some T`
  (criteria in `data/review/relation_universality_2026-10-02/README.txt`,
  verdicts in `verdicts_*.txt`, joined and checked by
  `scripts/compile_universality.py`): **203 all, 537 some, 267 no.** Only
  `all` may become an axiom. Of the `no`: 180 are subclass statements misread
  as part-hood (`Acute wound part_of Wound`, `amputation part_of surgical
  procedure`, `antibiotic has_part meropenem`), 26 self-loops, 7 the wrong
  bearer (`Wound pain inheres_in Wound`: the pain is the patient's). `some` is
  where the abstracts report instances: `Wound has_quality contaminated`,
  `X participates_in wound healing` (141 of 150 participates_in rows),
  every causal link (42 of 45).

## 67. BFO is whole and right everywhere; the WONT addition is built from checked edges and read relations only

**Decided 2026-10-03 (curator: "why the heck is role under quality. BFO is the
top onto of WONT. WONT and all modules end up as a schema for extraction and in
the concept store, so every BFO class should be in there and with correct
hierarchy"; on the export and the domain/range axioms: "do it").**

* **Why role sat under quality.** The class hierarchy is keyed by label.
  obi_module states ChEBI `role` (CHEBI_50906) under PATO `quality`
  (PATO_0000001), carried over from pato.owl on purpose so the ChEBI leaf
  module is grounded. Module ancestry (rule 64) climbed from a placement parent
  into ChEBI `role` and wrote its parent as the parent of the one `Role` node,
  stamped curated. BFO's own `role ⊑ realizable entity` never entered: the
  hierarchy read subsumption from WONT + MILD only, and those hold no BFO
  axiom. Now a non-BFO class carrying a BFO label is not climbed
  (`curated_seed.module_ancestry`, reported), and BFO's tree comes from BFO.
* **All of BFO in the modules.** Seeded by use, the module closure held 20 of
  BFO 2020's 36 classes and 19 of its 35 edges (no object, site, fiat object
  part, object aggregate, history, relational quality, spatial and temporal
  region subtypes, fiat boundaries). `build_disease_proposal.sh` FIX 4 seeds
  BFO core whole; after the rebuild 36/36 and 35/35, only obi_module changed
  (+16 classes). `bfo_module.owl`, `iao_module.owl` and `ro_module.owl` are
  June leftovers MILD does not import.
* **All of BFO in the hierarchy** (`curated_seed.bfo_edges`, called by
  `run_build_hierarchies`): BFO's 35 edges plus the two extraction categories
  that are not BFO labels -- `information entity` (typed BFO_0000031) under
  generically dependent continuant, `tendency` (MILD_120005) under realizable
  entity -- stamped curated. Every BFO node now has exactly its BFO parent.
* **All of BFO in the extraction schema** (`schema_builder.collect`): the 20 BFO
  classes that are not typing categories are grounding targets under the
  category their BFO ancestry gives them; `entity` is the root and not a
  target. The 16 typing categories are unchanged.
* **The reasoner skeleton takes BFO and the relations from the modules**
  (`skeleton.add_bfo_and_relation_axioms`): BFO's 35 edges, 39 disjointness
  pairs, and rdfs:domain / rdfs:range of every exported relation as RO / BFO /
  IAO / OBI declare them (15 domains, 14 ranges). ELK is OWL 2 EL: an
  intersection keeps its named members (`inheres in` range independent
  continuant), a union is left out and reported (`concretizes`, `occupies
  temporal region` domains). The skeleton is stale when a module is newer.
  Tested: `X has_quality some material disease entity`, `X has_quality some
  process` and `X participates_in some material entity` are now unsatisfiable;
  `X has_quality some quality` is not.
* **Withheld until rule 68 (2026-10-03), now restored:** RO's range of `has disposition`
  (disposition). MILD makes disposition, role and tendency pairwise disjoint,
  and WONT/MILD bear `wound infecting tendency` by `has disposition`
  (Staphylococcus aureus, Escherichia coli, WONT_120019 pathogen with wound
  infecting tendency), so with the range those three and MRSA infection are
  unsatisfiable. The ground truth is not changed here.
* **The export** (`run_extend_ground_truth`, `owl/extend.py`): relations are
  only the 203 read as true of every instance (rule 66), never the store and
  never the mereological hierarchy's unread part_of edges; `store` and
  `relations` together are refused. Subclass edges: curated and placed whole, a
  text edge only when its child is named in >= 2 abstracts. (2026-10-27: the
  mereological hierarchy is gone, with its LLM review and its export branches,
  to `data/removed_code/*_removed_2026-10-27.py`: part_of reaches the FCA as an
  attribute read from the cleaned store, and WONT only as a read relation --
  15 of the 266 part_of statements read.)
* **The core** (`scripts/build_wont_core.py`, replacing `split_extension.py`,
  whose head-noun and unreviewed-candidate placements were not checked): a new
  class enters only through a `placed` edge to a curated class or to another
  core class, with its BFO typing; no text is_a edge; a read relation only when
  its filler is curated, a category or in the core. ELK then settles it
  (`elk_unsat`): a new class it finds unsatisfiable loses its relations, then,
  if still unsatisfiable, goes to the candidates; one only below an
  unsatisfiable curated class stays and is reported.
* **The edge gate had been calling an inconsistent hierarchy clean.**
  `ReasonerGate._unsatisfiable` ignored ROBOT's exit code, so "the ontology is
  inconsistent" came back as no unsatisfiable class: 36,644 edges "clean" while
  `Allergy` sat under disposition and material disease entity. It now raises
  unless ELK listed classes. The inconsistency itself came from WONT's 48 named
  individuals (Wagner grades, burn zones) under classes the text edges emptied;
  the edge graph now carries no individuals (the gate asks which CLASSES an
  edge empties). And the gate blamed only the empty class's own edges, so the
  cause on ANOTHER class went free: `Nutrient is_a Material Entity` (text)
  leaves nothing that can be protein's `has role some nutrient`, and 31 placed
  children of Protein were dropped. Before a placed or curated edge goes, the
  gate now asks ROBOT for one explanation per root unsatisfiable class and
  drops the lower-ranked edges it names (`_explained_pairs`).
  Result: **1,127 edges quarantined, all text; every curated (882) and placed
  (3,107) edge kept; the 35,517 kept edges have 0 unsatisfiable classes.**
* **Built 2026-10-03:** 7,299 minted, **3,095 in the core** (3,083 placed
  edges, 2,070 BFO typings, 55 read relations; `Negative Pressure Wound
  Therapy Dressing` lost its relation, whose filler had resolved to the NPWT
  *plan specification*), 4,204 candidates under their category in
  `wont_candidates.ttl`. 82 read relations sit on existing WONT classes and are
  withheld (WONT is never altered), 63 on candidate classes, 2 point outside
  the core. ELK over the core and its import closure: 11 unsatisfiable -- the
  ground truth's own 4 (above, `has disposition` with a tendency) and 7 new
  classes placed under them (MRSA, MSSA, MDR S. aureus, S. aureus isolate,
  ESBL E. coli, Acinetobacter baumannii, burn-wound pathogen).

## 68. A tendency is borne by `has tendency`, never by `has disposition`

**Decided 2026-10-03 (curator: "separate has tendency relation").**

* MILD makes disposition, role and tendency pairwise disjoint, and RO_0000091
  `has disposition` has the range disposition. WONT bore `wound infecting
  tendency` (WONT_120018) by RO_0000091 on Staphylococcus aureus, Escherichia
  coli and in the definition of WONT_120019 pathogen with wound infecting
  tendency, so under its own import closure WONT had 4 unsatisfiable classes
  (those three and WONT_0000447 MRSA infection) -- ELK, and HermiT after 2 h
  57 min, agreed.
* **MILD_120101 `has tendency`** (MILD): subproperty of RO_0000053 `has
  characteristic` (range specifically dependent continuant, which a tendency
  is), domain independent continuant, range MILD_120005 tendency; not a
  subproperty of RO_0000091, whose range would reimpose disposition.
* **The three axioms in WONT now use it** -- the one change made to
  `ground_truth_final.owl` by this pipeline, on the curator's ruling, three
  lines, backed up in `data/backup/has_tendency_2026-10-03/`. WONT under its
  import closure: 0 unsatisfiable classes (ELK).
* `has disposition` stays in the extraction schema (`schema_builder.
  REQUIRED_PATTERNS`, material entity -> disposition): the relation list is
  derived from WONT/MILD usage, and with its last WONT use gone it had dropped
  out silently although the store holds 102 such relations. `has_tendency` is
  in ALLOWED_PREDICATES. The skeleton carries RO's range of `has disposition`
  again.
* **The shift in the store** (curator: "do the has disposition to has tendency
  shift for tendency targets"; `scripts/shift_has_tendency.py`): a
  `has_disposition` cell reads as `has_tendency` when its value's most
  frequent typing across the store is tendency and the abstracts asserting the
  pair do not type it disposition or function. 124 of 216 pairs shift (risk
  factor 42, amputation risk 12, risk of infection 10, ...). A first draft
  followed the asserting abstract's typing alone and would have made
  `Osteomyelitis`, `Smoking` and `diabetic peripheral neuropathy`
  tendencies. The store is not edited: each shifted cell carries a
  `repredicated` decision in the term dict (`ConceptStore.repredicate_cells`),
  which the view applies (`_cell_predicate`); the assertion stays as the
  abstract wrote it. `relation_typing_check.py` knows `has_tendency`.
* **Why the old extraction made them:** the schema licensed `has disposition`
  for material entity -> tendency, learned from exactly the three WONT axioms
  this rule corrected.

## 69. Relations on existing WONT classes: the curator decides, and a wound-wide quality goes on Wound once

**Decided 2026-10-03 (curator: "I wouldn't be categorical. Show these in a UI
for my judgement"; "most of these axioms are true for wound, not only pressure
ulcer. The axioms will be inherited by wound subclasses anyway"; "wound
healing and wound healing process are the same").**

* The export withholds every axiom on a curated class (`touch_existing=False`,
  rule 67): 82 of the 203 read relations. They were put before the curator
  (https://claude.ai/artifact/BRc7QuBRBmXJV4tXcCun8A; data
  `data/review/withheld_relations_2026-10-03.json`, built by
  `scripts/withheld_relations_data.py`, which resolves and mints against the
  CORE -- minting against WONT's own counter reused the core's ids and made 18
  relations look unsatisfiable that were not), each with its PMIDs, the class
  each end resolves to, and ELK's verdict for that axiom alone.
* **A quality every wound has is asserted once, on Wound**, and inherited:
  area, size, depth (PATO), length, volume (WONT), age (PATO, ticked as the
  wound's age), degree of microbial burden (WONT's class; the curator unticked
  `bacterial load` and `bacterial burden`). Bearer-specific names (wound
  surface area, ulcer area, burn size, burn wound depth, ...) were unticked:
  no axiom, no mapping. Per-subclass statements of these qualities give no
  axiom.
* **A WONT plan specification stands for the process that realizes it** where
  the abstracts speak of the act: dressing change -> Wound Dressing Change
  (WONT_0007699), negative pressure wound therapy -> Application Of Negative
  Pressure Wound Therapy (WONT_0001008), surgical debridement -> Surgical
  wound debridement process (WONT_0000299), antibiotic therapy -> Antibiotic
  administration process (WONT_0000589). (All 10 relations ELK rejected were
  this mismatch.)
* `scripts/apply_axiom_review.py` turns the page's database into
  `data/review/curator_axioms_2026-10-03.json` (47 axioms: 7 on Wound, 40
  single; 6 left out, 2 undecided) and records the identities in the term
  dict (`wound healing process` = `wound healing`, `wound age` = `age`).
  `build_wont_core.py` adds every curator axiom to the core, brings a filler
  that is only a candidate into the core with its BFO typing (8), and never
  drops a curator axiom: if ELK rejects one the build stops and names it.
  Result: core 3,103 new classes, 0 unsatisfiable (ELK).

## 70. Ulcer and wound are one term; ulceration is ulcer; leg is lower extremity

**Decided 2026-10-04 (curator: "we should do something against the ulcer vs.
wound synonym" -- asked how, "same class (synonyms)"; ulceration "same as
ulcer"; "leg should be converted to lower extremity always, because the
suggested FCA edges are only that. basically non expressive nonsense").**

* **Inside every name** (`normalise.canonical_vocabulary`, so it also holds for
  every future extraction): `ulceration(s)` -> `ulcer(s)` (`_ulceration`);
  `leg` and `lower leg` -> `lower extremity`, `legs` -> `lower extremities`
  (`_lower_extremity`). Kept as written (`LEG_KEEP`, read one by one from the
  356 names using the word): `upper leg` (the thigh); instruments, scales and
  studies (FLACC, Leg Ulcer Measurement Tool, Venous Leg Ulcer Self-efficacy
  Tool, European leg ulcer series, the HEALS trial, the S2k guideline);
  programmes (Leg Club); tests, exercises and procedures (straight leg raise,
  single-leg hop / stance / squat, leg press, leg extension, short-leg cast
  and splint, cross-leg flap and anastomosis, in-bed leg cycling, leg muscle
  pump).
* **Ulcer and wound** are one term in what two spellings share
  (`Normalised.key` and `.strict`, `_ulcer_is_wound`), never in a name: pass 0
  groups `X ulcer` with `X wound` and elects one name -- an ontology label
  first (rule 36; `Diabetic foot ulcer`, `Chronic wound`, `venous wound`),
  then the spelling more abstracts use. A lone `gastric ulcer` keeps its word.
  A WONT/MILD label is never renamed: `Venous leg ulcer` keeps `leg`, and
  `venous lower extremity ulcer` joins it.
* Applied 2026-10-04 by pass 0: 543 renames (208 ulcer <-> wound, 199 leg,
  97 ulceration, 62 respellings already owed); the bare `ulcer` (297
  abstracts) is now `Wound`. A second pass writes 0.
* **Found on the way:** `resolve_chains` let the category guard withdraw a
  mapping the curator had ruled (`wound healing process` = `wound healing`,
  2026-10-03; two ROC-curve names and `undermining border` since 2026-09-27).
  A curator `same_class` ruling now outranks the guard (`ruled` in
  `TermMapper.resolve_chains`); the six withdrawn rulings were restored.
* The gate list files are views of the term dict (rule 51); after a rename
  they are rewritten (`term_lists.export_gate_lists`), or
  `test_the_live_files_and_the_live_gate_agree` fails.
* The FCA nesting page (https://claude.ai/artifact/FNFH2gPgddHPECcPDBj1gb) is
  superseded: its edges were this naming problem, not structure.
* **Minted WONT ids are not stable across builds.** The export numbers new
  classes from WONT's highest id on every run, so after the renames
  WONT_0004067 was `Ligamentous Rupture`, not `Length`, and the curator axiom
  "every wound has some length" emptied Wound and 983 classes below it (ELK:
  inconsistent through WONT's individuals). Curator axioms now refer to a
  minted class by NAME, through the term dict (current name first); only
  WONT's own and imported IRIs are kept as IRIs (`build_wont_core.py`,
  `stable_or_by_name`). A curator axiom WONT already states is skipped
  (7 of 49). The id registry of rule 71 now keeps minted ids stable.
* The read relations (rule 66) carry the names of their day; the export now
  passes every name through the store's resolver (`run_extend_ground_truth`),
  so `ulcer` exports as `Wound` (19 relations renamed) instead of being
  minted as a class of its own.
* The core builder now sees through an inconsistent result as the gate does
  (`elk_unsat` re-reasons without WONT's individuals and names the empty
  classes) and stops with the failing graph saved when a curated class goes
  empty. Result 2026-10-04: 2,954 new classes, 0 unsatisfiable (ELK); 10
  placed edges dropped by the gate where a merged record brought two
  contradicting placements.

## 71. A minted WONT id belongs to its class for good

**Decided 2026-10-04 (curator: "fix the unstable numbering").**

* The export used to number minted classes from WONT's highest id on every
  run; any change upstream moved every id after it (rule 70: WONT_0004067
  became `Ligamentous Rupture`). An id that moves cannot be published, cited
  or reviewed against.
* **`data/registry/wont_ids.json`** (`owl/id_registry.py`, `IdRegistry`) maps
  what a name shares with its spellings (`Normalised.key`) to one IRI. The
  export (`extend_ground_truth(registry=..., former_names=...)`, built by
  `run_extend_ground_truth`) asks it before minting:
  * seen before -> the same id;
  * renamed -> the same id, found through the term dict's aliases (a former
    spelling counts only when it is no longer a name of its own in that build,
    so two live classes are never merged);
  * two registered classes joined by a rename -> one id survives (the one
    registered under the current name, else the older) and the other is
    marked `obsolete`, `replaced_by` the survivor -- never reused, never
    silently dropped (OBO practice);
  * new -> the next number after every id ever issued.
* **WONT's main series continues consecutively** (curator, 2026-10-04: "I'll
  reset Protégé every time"): a new id is the next number after WONT's own
  highest id and after every id the registry ever issued. After each export
  the next free id is printed and written to
  `output/owl/NEXT_FREE_WONT_ID.txt`, for Protégé's new-entity counter. If a
  hand-made WONT class ever takes an id the registry holds, the export stops
  and names it (`registry id ... is a curated class in the ground truth`)
  rather than letting two classes share an IRI. (A separate block from
  WONT_0500000 was used for one hour and discarded before anything was
  published.)
* A label changes only on a real rename, not between case variants of one
  name meeting in one build.
* Seeded 2026-10-04: 7,212 ids, WONT_0000591 to WONT_0007802, consecutive
  after WONT's own WONT_0000590; next free WONT_0007803. Two consecutive
  exports gave identical (IRI, label) for every minted class (0 issued, 0
  merged on the second). The registry is backed up before every write
  (`data/backup/registry/`) and read back after it.
* 2026-10-06: a title-cased hyphenated label lost its final s in the key
  (`Retro-Rectus` -> `retrorectu`, but `retro-rectus` -> `retrorectus`;
  `singular_spelling` read the capital after the hyphen as an acronym's).
  Fixed in `label_match.singular_spelling`; the five registry entries keyed
  the old way (Complete-Thickness, Extremity-Loss, Neo-Epidermis,
  Pro-Angiogenesis, Retro-Rectus) got the corrected key added, the old one
  kept. All 7,212 ids answer to both spellings of their label
  (`tests/test_hyphen_title_case.py`).
* Open: once ids are published, an obsolete id should appear in the release as
  a deprecated class with `term replaced by` (IAO_0100001); nothing has been
  published yet, so none is emitted.

## 72. Nothing goes into the WONT addition that the curator has not seen

**Decided 2026-10-05 (curator, on the 44 relations on new classes: "have i
ever reviewed these?" -- no, only Claude had read them -- "make the page yes.
and everything else that could be worth my judgement should be in this ui
too").**

* A relation from the abstracts on a **new** class goes into the addition only
  when the curator marked it "add". `scripts/build_wont_core.py` reads
  `data/review/new_class_relation_decisions.json`; every other such relation
  is held out and listed in `core_build_report.json` ("relations held for the
  curator"). Claude's reading of a relation as true in every case is
  evidence for the curator, not a decision. (Relations on existing WONT
  classes already needed the curator: rule 69.)
* Everything else worth a person's judgement is collected by
  `scripts/judgement_queue_data.py` into one list and shown on one page
  (`scripts/judgement_queue_page.py`): those relations; new classes whose name
  is a label or exact synonym of an existing class; parents whose missing
  parent keeps classes out; terms whose every parent the reasoner
  contradicted; classes in only because a curator axiom names them; parents
  the abstracts suggest for existing WONT/MILD classes (notes for WONT's next
  revision only -- WONT is not changed).
* Decisions live in the page's shared store and are read back with
  ArtifactData before anything is applied; an item's id is stable across
  rebuilds (`item_id`), so a decision survives a new version of the page.
* Write to the curator in plain words, not in the pipeline's own terms
  ("given a parent class", not "adjudicated placement").

## 73. A decision is written to the record that exists, found without case, or not at all

**Decided 2026-10-07 (applying the judgement queue).**

* A page shows a built class's label ("Cell Process"); the term dict keys its
  record by the spelling in the abstracts ("cell process"). `record()` creates
  an empty record for a spelling it does not know, so a decision written under
  the page's spelling lands where no view reads it and is lost without a word.
  An applier matches the page's name to the term dict's keys without case,
  follows aliases (`resolve`), and writes only when that gives exactly one
  current spelling. No record, or more than one: the run names the term and
  writes nothing for it (`scripts/apply_judgement_queue.py`).
* After writing, the applier reads back every decision AND says which written
  parents still do not count (`placements()`): a term out of scope or mapped
  onto a class takes the parent onto its record but not into the build.
  Found on the first run: `sample` (out of scope by the methodology list) and
  `disorder course` (already mapped onto MILD's course of the disease process).
* The same holds for the class side of a pair: Likert scale's placement was
  keyed `categorical level specification`, and a refusal written as
  `Categorical Level Specification` refused a pair nobody reads. The applier
  matches the pair's class without case too, and refuses to guess when a record
  holds one class under two spellings.

## 74. A renamed import is still the import

**Decided 2026-10-07 (the judgement queue's "waiting for a parent" section).**

* The naming rules rename inside the pipeline (specimen -> sample, value ->
  level, cellular -> cell, action -> activity, disease -> disorder). An
  imported class's own label is not renamed, so after the rename the export
  found `sample from organism` nowhere and minted OBI_0001479 again as a WONT
  class with no parent; 14 imported classes were twinned this way, and seven of
  them (cell process 50, scalar level specification 5, sample from organism 4,
  cell anatomical entity 3, processed sample, sample and sample collection
  process 2 each) kept 68 checked classes out of the WONT addition.
* `extend_ground_truth(import_names=...)`: a term no import defines is looked
  for under its other names -- the class the term dict maps it onto (it IS that
  class), else its former spellings -- and used only when every name that
  answers gives the same class. Every such match is listed in the run
  (`resolved_other_name`); the 14 of the first run were each read.
* Never through DOID (`import_skip`): curator, on Metabolic Disorder, "Dont
  reuse doid".
* A curator's "leave them out" for the children of such a parent is written as
  refusals of those child -> parent pairs, so the fix does not bring them in.

## 75. An inconsistent ontology is asked again without WONT's individuals, and that is said

**Decided 2026-10-08 (the relation gate stopped `p4_derive.py` on 2026-10-07).**

* WONT holds 48 named individuals (Shea, Wagner, Gustilo grades, zones of a
  burn). When relations empty a class one of them is a member of, ELK reports
  no unsatisfiable class but "the ontology is inconsistent", which names no
  culprit. On 2026-10-07 that stopped the relation gate, and the rebuild ran
  without it (`p4_derive_2026-10-07b.log`).
* Every reasoner call of the gate (`ReasonerGate._unsatisfiable`) now does what
  `build_wont_core.elk_unsat` already did: on "inconsistent" it asks again
  without the individuals (`gate.without_individuals`), so the emptied classes
  are named and their relations held back as usual. It says so in the run, in
  `GateResult.without_individuals` and in the quarantine file
  (`asked_without_individuals`), naming each individual and the emptied class
  it sits in. The explanation is asked of the same graph without individuals.
* It still stops when nothing can be named: inconsistent with no individuals
  in the graph, or inconsistent without them too, or no class empty once they
  are out. Any other ELK failure is never taken for an inconsistency.
* A clean result still means consistent WITH the individuals: the last pass
  only ends on an empty answer, and an inconsistent graph never gives one.
* **A crashed check puts its earlier verdicts back.** `run_gate_store_relations`
  lifts the gate's own verdicts and saves before re-checking; the crash of
  2026-10-07 left its 14 rejections lifted in the saved store. It now restores
  them before the error goes on, and says so.
* Tested: `tests/test_gate_individuals.py` (including a real ELK run on WONT's
  `Shea classification grade`).

## 76. The relation check holds back causes, not everything near an empty class

**Decided 2026-10-09 (curator: "ok, do it", on the 20,363 held back).**

* With the individuals out of the way (rule 75), the check of 2026-10-08 ran
  through and held back **20,363 of 24,584 relations** (10-01: 14). Since
  rule 67 the reasoner knows what each relation connects (`inheres in` wants
  a property, `is about` a piece of information, `has quality` a quality).
  31 terms got relations asking for two kinds at once (`wound size` inheres
  in a wound AND is about something), so they went empty; `Wound has quality
  wound size` emptied Wound, and through Wound 6,756 classes, MILD's core
  among them. The check held back every relation touching an empty class at
  once, so the knock-ons went with the causes.
* An empty class makes everything that must have one empty too. Most empty
  classes are knock-ons; the check must find the few relations that empty a
  class by themselves. `ReasonerGate._causes`, each pass, in one reasoner run
  over the batch without the suspect relations, tests on a fresh copy of the
  subject:
  * each relation on an empty class against its REAL target -- empty means it
    clashes with what the target is (`X has quality report`, the report being
    about something);
  * for a term with none of those, its relations two relation types at a time
    -- empty means the two ask for incompatible kinds. **Both groups are held
    back**: which one the abstracts got wrong is the curator's call, not a
    guess (rule 12, rule 66).
  Then the batch is asked again; knock-ons come back by themselves.
* **A loop hides its cause unless the empty target is replaced by its kind.**
  The first version found 196 causes on 2026-10-09 (empty classes 6,756 ->
  6,721) and then none, and fell back to holding back 20,348. Measured: with
  the relations pointing AT an empty class removed, nothing is empty -- every
  empty class was empty only through another. A loop: `X has quality note`
  needs a quality, `note is about X` makes the note a piece of information,
  so X is empty and the note, being about X, too; each probe saw an empty
  target and proved nothing. A target that is empty is now a stand-in with
  the target's category or class and one bare relation of each type it has
  (`∃is about.Thing`): its kind, without its emptiness.
* **A timed-out ROBOT is ended whole** (`gate._run_robot`). `robot` is a
  script that starts Java; `subprocess.run` killed only the script, and the
  explanation that timed out on 2026-10-08 09:10 was still reasoning 25 hours
  later at ~180 % CPU. ROBOT now runs in its own process group, and a timeout
  ends the group.
* Only when no cause is found does a pass fall back to holding back every
  relation that touches an empty class, and it says so ("the old way. Expect
  collateral loss"). Classes still empty when the check stops are printed and
  kept in `GateResult.still_empty` and the quarantine file (rule 1); before,
  "cannot attribute further" ended the check without a word.
* **Two relation types clash whatever they point at**, so that test uses
  `Thing` as target, never the real one: `pressure ulcer stage` inheres in
  Pressure ulcer AND is about pressure ulcer stage -- itself -- and against its
  own (empty) self as target the clash proved nothing; 6,702 classes, Wound
  among them, stayed empty (`robot explain` on Wound found it in 10 s). All of
  a term's relation types together are tried too.
* Tested with the real reasoner on a small ontology with BFO's disjointness
  and the RO/IAO domains and ranges (`tests/test_gate_individuals.py`): the
  clashing relations go, the knock-ons stay -- two kinds at once, a clash with
  the target's kind, a loop, a term about itself.
* **Result, 2026-10-09** (`p4_derive_2026-10-09b.log`): 1,268 of 24,584 held
  back -- 6 on a category class, 999 wrong on their own, **263 causes** (72
  against what their target is, 191 on 30 terms asking for two kinds at once;
  59 on `risk factor` alone) -- 23,316 kept, nothing left empty, two passes.
  Edge check 1,124 held back, 35,236 kept; competency questions 49/49. The
  WONT core is unchanged (3,048 classes, 0 unsatisfiable): it takes only
  placed edges and the 203 read relations, which this check never touched.
* **The causes go to the curator** (rule 72; curator, 2026-10-09: "Yes
  please"). `GateResult.causes` records each one with its sides: a term asked
  to be two kinds (the statements of each relation type), or a statement whose
  target is the wrong kind (the target's statements that make it so, found by
  `ReasonerGate._target_blame`). Written for the real store to
  `data/review/relation_clashes_2026-10-09.json` (same 1,268 held back as the
  real run, checked), shown as the section "Statements that contradict each
  other" of the judgement page (`judgement_queue_data.py`, 102 items: 72
  statements, 30 terms). Almost all have `is about` on one side. A decision
  is to become a curator rejection of the side named wrong (which the relation
  check then never sees, so the other side comes back); not applied yet.

## 77. A score, grade or stage is information about a thing, never its quality; a curator's decision reaches every statement of its type

**Decided 2026-10-10 (curator, on the first 50 contradicting statements: "Many
problematic axioms are the same type"; notes: "Ulcer grade is an information
entity", "Biomarker is a role of a molecule", "A gene itself is not a
biomarker", "Low risk is completely subjective").**

* **`X has quality T` is wrong when T is information about X**: a grade,
  stage, score, type, classification, characteristic, composition, culture
  result, rate of an event, or a judgement such as "low risk". 39 of 39 such
  statements the curator saw were left out (`Wound has quality ulcer grade`,
  `Pressure ulcer has quality stage 4`, `Wound has quality wound type`). A
  measured property stays a quality: `exudate has quality exudate volume`,
  `Wound exudate has quality exudate amount` were kept, and their stray
  `is about exudate` was dropped instead.
* **A process is not the end or start point of another process**
  (`anticoagulation therapy has as process boundary at end complete
  resolution`: out).
* **`has role biomarker` belongs to a molecule** (erythropoietin, interleukin-10,
  microRNA, 25-hydroxyvitamin D: kept), not to a gene (out). All of them were
  held back by two stray statements, `biomarker is about deep vein thrombosis`
  and `biomarker is about periorbital necrotizing fasciitis`; those two went.
* **Same type, applied by Claude and labelled so.** 12 undecided statements
  of exactly these types were held out under the author `same type as the
  curator's decisions`, each with the decision it follows
  (`data/review/relation_clash_decisions_2026-10-10.json`). Anything doubtful
  stays with the curator: a ratio (`collagen type I/III ratio`), a value
  (`660 nm`), a disease as quality (`Malignancy`), `slough component has role
  biomarker`, and all 30 terms asked to be two kinds.
* **Not by word rule.** Of 1,744 `has quality` statements that passed the
  check, 113 name their target like information, but many are real
  properties (a dressing's moisture vapor transmission rate, a wound's
  duration); a word list would drop good statements (rule 27). Only 9 of the
  113 come from >= 2 abstracts, the least a relation needs to reach WONT.
* Written by `scripts/apply_clash_decisions.py` (backup, one write per author,
  every decision read back): 58 statements held out (46 curator, 12 same
  type), and the curator's note "neuropathy is the disease, so a material
  entity" as a term ruling for `diabetic peripheral neuropathy`. The relation
  check lifts only its own verdicts, so these stand through every rebuild;
  `scripts/run_relation_check.py` re-runs the check alone.
* **Result** (`relation_check_2026-10-10.log`): one pass, nothing left empty;
  1,202 held back, 23,324 kept (24,584 less the 58). The kept biomarker and
  exudate statements are back in, and so is `slough component has role
  biomarker`, which nothing contradicts any more. Left for the curator (35):
  4 single statements and 31 terms asked to be two kinds -- one new, a
  consequence of a keep: `microRNA has role biomarker` (kept) against
  `microRNA is about wound tissue`. Page republished from
  `data/review/relation_clashes_2026-10-10.json` (`scripts/relation_clashes_for_review.py`).
* **Second round, all 35 decided** (`relation_clash_decisions_2026-10-10b.json`):
  100 statements held out by the curator; 10 terms the curator said to
  delete ("Delete it"; `stage 3`: "alone is nothing") are out of scope by a
  curator verdict -- burn/injury/wound characteristic, sign, stage 3,
  taxonomic and tissue composition, wound healing status, wound parameter,
  wound status. The kept sides decide the kind: a measured property keeps
  `inheres in` (wound size, volume, width, duration, total body surface area
  -- "a wound area, thus a quality"), a stage or score keeps `is about`
  (pressure ulcer stage, wound pain score, pH level, granulation tissue
  coverage, closure rate).
* **Its six consequences** (`…_2026-10-10c.json`, author `same type`): four
  `has quality` statements pointing at a term the curator had just ruled
  information (`Pressure ulcer has quality pressure ulcer stage`, `Wound has
  quality pH level`, …) and two `… has quality Skin` (Skin kept as a material
  thing).
* **Result** (`relation_check_2026-10-10c.log`): no empty class, and no
  inconsistency with WONT's individuals any more; 1,005 held back (6 on a
  category class, 999 wrong on their own), 23,384 kept. Curator notes kept
  for later, not applied: red-spectrum laser "has quality wave length below
  xx nm"; skin perfusion pressure "inheres in blood flow" (the kept statement
  says extremity); wound pain score "belongs to the other scores next to the
  wound scores" (a parent); wound-related symptom "is a symptom".

## 78. A refused model account stops the step before it saves

**Decided 2026-10-11 (the rebuild of that day).**

* `p4_derive_2026-10-11.log`: every one of the 91 concept-naming calls failed
  with "Error code: 402 ... This request requires more credits" (364
  attempts, none recovered). `create_superclass_names` printed one line per
  failure, named 0, saved a lattice without names over the named one of
  2026-10-09 (14 names), and the run ended ALL DONE (rule 1).
* Now a 401/402/403 from the model service raises at the first refusal, before
  anything is saved; any other failure is counted and reported as "N of M
  concept(s) could not be named", and naming none at all raises
  (`tests/test_name_category_guard.py`).
* The unnamed output of 2026-10-11 is in `data/cache/failed_fca_naming_2026-10-11/`
  (moved, not deleted), so the latest lattice on disk is again the named one
  of 2026-10-09. The WONT core, the class tree and the competency questions do
  not use the named concepts and are sound from that run (3,046 new classes,
  0 unsatisfiable; 49/49).

## 79. A superclass from the concept analysis must pass the head-word rule; the curator rules on head words, not on edges

**Decided 2026-10-18 (curator, on the review page of the 17 October run: "Mir
gefällt diese Auswahl gar nicht. Das hätte vorher gelöst sein sollen. Einiges
sind Synonyme. Wound is an injury. Burn wound is a burn injury is an injury
und burn wound is a wound aber nicht wound is a burn injury. Aber auch Blast
wound is a blast injury is an injury.").**

* A label is read as modifiers + head word (`deep second-degree burn wound` =
  {deep, second, degree, burn} + wound). An edge child ⊑ parent is licensed
  only when the parent's head is the child's head or above it on the head
  ladder (wound ⊑ injury) and the parent carries no modifier the child lacks.
  So burn wound ⊑ burn injury ⊑ injury and burn wound ⊑ wound, but never
  wound ⊑ burn injury.
* The curator's rulings on head words (2026-10-18), in
  `config/head_word_rules.py`: a bare burn is a burn wound; ulcer and tear are
  a wound only on skin ("gastric ulcer ... ist keine Wunde im Sinne WONT",
  "tendon tear nicht"); laceration and abrasion are always skin, so wounds;
  avulsion is an injury, not a wound per se; lesion, disorder and defect are
  collective names and never a superclass.
* Second round, the same day (review page and chat):
  * A wound is structural damage to the tissue, not only tissue that is
    missing: "ein blister ist für mich schon eine Wunde, weil die Haut
    strukturellen Schaden genommen hat, sonst wäre eine drittgradige
    Verbrennungswunde keine Wunde". So blister, bulla and epidermal
    detachment are wounds.
  * A burn is a flame burn and so a thermal wound; a scald is a thermal wound
    and not a burn ("keine Flamme im Spiel"); a sunburn is a radiation wound,
    not a thermal and not a burn wound; burn lesion is burn wound; thermal
    damage names the injuring process, never the wound.
  * defect is too vague to place anything, as child or parent.
  * fracture ⊑ injury, an open or compound fracture ⊑ wound; frostbite ⊑
    injury, not a burn; snakebite is a bite wound; an ulcer without a site is
    a skin ulcer (the corpus is wound literature); a tear without a site is an
    injury, a perineal tear a wound; a burn off skin (ocular surface) is an
    injury, not a wound; ulcus cruris is leg ulcer; the CDC wound classes are
    surgical wounds; Injury ⊑ pathological disorder (MILD_120022), the
    curator's axiom.
  * A curator's verdict on one edge outranks the rule for that edge
    (`data/review/fca_edge_decisions_*.json`: "Abdominal Injury ⊑ Injury" no).
  * The accepted slice is judged again every run, so a later ruling withdraws
    what it no longer licenses. `p4_derive.py --skip-fca` judges the last
    run's proposals again without naming the concepts anew.
* `trauma` is not a head-word synonym of `injury`: the curator ruled on
  2026-10-02 that trauma is `Trauma process`, a process. The first version of
  this rule assumed the synonym, merged the model's name `Injury` into the
  existing `Trauma`, and the export made 300 wounds subclasses of a process;
  the core build stopped on it. The edge check had not seen it, because it
  reasons over hierarchy names, not over what the term dict maps them to.
* WONT's own synonyms decided against the rule, and the curator struck them
  (2026-10-18): `Trauma process` (WONT_0000338) carried the alternative term
  "injury", `Thermal wound` (WONT_0000310) "Burn injury"; the export matches
  names by WONT's synonyms, so the model's `Injury` became the process. Injury
  is the material outcome (Wound ⊑ Injury ⊑ pathological disorder), burn
  injury its own class (burn wound ⊑ burn injury ⊑ injury; a scald is a
  thermal wound, not a burn injury). The curator edits WONT; the pipeline does not.
* The model's names are also judged among themselves and against Wound and
  Injury (`Burn Injury ⊑ Injury`, `Diabetic Ulcer ⊑ Wound`), so a new name has
  a checked parent; listed as `between_names` in the report.
* Two labels with the same reading are one concept, not an edge
  (`Ischemic Wounds` is `Ischemic Wound`; `Diabetes-Related Ulcer` and
  `Diabetic Ulcer` are one name).
* A head word the rulings do not place cannot be judged; its edges are not
  proposed (rule 66). The curator rules on the head word once; every edge
  that depends on it then follows.
* Licensed edges are promoted without a page and recorded on the lattice's
  accepted slice, which amends rule 72 for this one kind of edge: the
  curator's decision is the rule, not each edge. They are still reasoned
  over: `scripts/p4_derive.py` runs the is_a edge check again after the
  concept analysis.
* Every proposal and its verdict is written to `output/fca_head_rule_*.json`,
  and the run prints the counts (rule 1). The WONT addition takes these edges
  (`run_extend_ground_truth(include_fca=True)` in `p4_derive.py`); before rule
  79 it left all FCA edges out, because they were unchecked.
* The report accounts for every name the model made, not only for edges
  (2026-10-18, curator): a name refused for all its members stays there with
  its reason, and a name `run_fca` keeps from the rule (undecided-dependent,
  or without members) is listed under `withheld`. A refusal is not written to
  the store or the term dict: it is the rule applied to the curator's
  rulings, a view (rules 33, 51). The run keeps the same content as
  `Orchestrator.fca_head_rule`, and `test_fca_on_subtree` accepts a name that
  is committed, queued, or in the report. Failure: on 2026-10-18 the test
  found `Skin And Soft Tissue Injury` (refused for Acute Wound and Chronic
  Wound: "says ['and', 'skin', 'soft', 'tissue']") in neither the hierarchy
  nor the review queue, because the test predated rule 79 and its emptied queue.
* A licensed edge also hangs a class into the core like a checked placement
  (`scripts/build_wont_core.py`, 2026-10-20). Before, the core took `placed`
  edges only, so all licensed edges reached just the full extension and
  `Burn Injury` (under `Injury`) never reached the core; with them the core
  has 2,996 new classes (+17), ELK 0 unsatisfiable.
* In the edge check an FCA edge gives way after a text edge and before a
  placed one (`ReasonerGate.check_edges`, rank 2.5). At its old rank 1 the
  check dropped all 436 licensed edges of 2026-10-18 first whenever their
  child was unsatisfiable through a text edge elsewhere; with 2.5, 6 went.
* Failure that motivated it: on 2026-10-17 the review page asked the curator
  to judge 352 proposed edges, all to names the model had given formal
  concepts (`Injury`, `Secondary Healing Burn Depth`, `Total Body Surface
  Area Burn`), among them `Burn Wound ⊑ Electrical Burn Wound` and
  `Wound ⊑ Cutaneous Disorder`. A probe of this rule on them: 193 licensed,
  54 refused, 39 refused as collective names, 1 synonym, 65 open.
* Enforced by `wound_ontology/hierarchies/head_rule.py` (`judge`,
  `sort_proposals`), `Orchestrator._judge_fca_proposals`, and
  `tests/test_head_rule.py`. `Wound ⊑ Injury` itself is the curator's axiom
  in `data/review/curator_axioms_2026-10-03.json` (a plain subclass axiom,
  read by `scripts/build_wont_core.py`), not a change to WONT.

## 80. Complication is an epistemic label, not a class; ulcer is wound inside names; burn is burn wound

**Decided 2026-10-18 (curator, chat).**

* "Was eine Komplikation ist und was nicht, ist ein epistemisches Label, das
  angehängt wird. Axiomatisch gesehen ist nämlich sonst alles eine
  Komplikation." WONT keeps no complication classes: the curator's edit
  removes `Wound complication`, `Wound complication disorder`, `Wound
  complication process` and `Material used for wound complication
  prevention`, and re-parents their children (prepared as
  `data/review/ground_truth_final_proposed_2026-10-18.owl` with its `.diff`;
  the pipeline does not write WONT). Every store name built on the word (169
  records) is out of scope (`scripts/apply_complication_out_2026_10_18.py`),
  so the WONT addition does not mint them. CQ003 ("Is a surgical site
  infection a type of wound complication?") is out of scope for the same
  reason; CQ030/032/033 stay -- they test MILD's process pattern, only their
  relation is named `complication_of`.
* Rule 70 is completed: "da sollte nicht mehr ulcer überall stehen". Inside
  every name `ulcer(s)` -> `wound(s)` (`normalise._ulcer_to_wound`, last in
  `canonical_vocabulary`, then the rules once more: `ulcer management` ->
  `wound care`), except an ulcer off skin (gastric, oral, corneal ...), a
  fixed eponym (Marjolin, Martorell, Kennedy, Buruli ...), an instrument,
  scale or study name, and a name built on WONT's own labels (pressure ulcer,
  diabetic foot ulcer, arterial leg ulcer, Marjolin ulcer). 549 renames.
* Like ulcer and wound, `burn`, `burn wound`, `burn lesion` and `thermal
  burn` are one term in what spellings share (`_burn_is_burn_wound`); pass 0
  names the thing `... burn wound` and keeps `burn care`, `burn depth`. Not
  after `non-`. 46 renames. Eight earlier mappings that said burn injury =
  burn wound, or scald = burn, were refused with the curator's assent
  (`scripts/apply_burn_synonyms_2026_10_18.py`).
* Injury is structural damage to a tissue or an organ, whatever its cause
  (curator, 2026-10-20, choosing the pathology sense over the
  external-cause sense; a venous leg ulcer is a wound and has no external
  cause). WONT gains `Injury` (WONT_0007817, under pathological disorder,
  Wound under it) and `Traumatic injury` (WONT_0007237, EquivalentTo: Injury
  and ('output of' some 'Trauma process')), keeping the ids the extension's
  id registry had given them.
* **WONT is now a dated file** (curator, 2026-10-20: "bitte ersetze nicht,
  sondern erstelle eine neue Datei mit Datum hinten dran"):
  `data/ground truth/ground_truth_final_2026-10-20.owl`. The pipeline reads it
  through `config/settings.GROUND_TRUTH_TTL`, as does `scripts/thesis_figures.py`;
  `ground_truth_final.owl` is the state of 2026-10-18 and stays as it is.
  Older one-off scripts still name the old file in their own constants.
* MILD's complication classes are gone too (curator, 2026-10-20: "die können
  alle weg"): `material complication disease entity` (MILD_120051),
  `complication disease process` (MILD_120092), `disease complication
  diagnostic result` (MILD_120050). MILD is now a dated file as well,
  `Disease ontologies/mild_2026-10-20.ttl` (`config/settings.MILD_TTL`, the
  WONT catalog's MILD import, `build_disease_proposal.sh`); `mild.ttl` stays as
  it was. The 87 placements onto those classes are refused
  (`scripts/apply_mild_complication_2026_10_20.py`), and `complicated` /
  `uncomplicated diabetes mellitus` are out of scope. The pattern itself stays:
  `disorder creating disease course process` (MILD_120053), a disorder that is
  the output of a process in another disease's course. MILD's header comment
  (commitment 4 b) still speaks of complications; it is the curator's text.
* Jargon out of scope: Spearman's rank correlation, skin loss, total skin loss,
  skin breakdown (`scripts/apply_scope_out_2026_10_18.py`).
* A review page lists only real questions (memory: check before asking): no
  BFO category names (disposition, function ...), no WONT/MILD classes, no
  term already ruled, only terms in scope; `disposition` is never preselected.

## 81. A name is in sentence case: lowercase, capital first letter, abbreviations and names kept

Decided 2026-10-24 (curator, on the thesis text "Sie wandelt in Kleinschreibung
mit großem erstem Buchstaben und klammert Abkürzungen von dieser Regel aus":
"änder den code"). Until then the writer's own case was kept, and case was only
folded for comparison: on the 2026-10-20 term dict 38,888 spelling targets were
all lowercase and 1,101 Title Case (`3S Intraoperative Pressure Ulcer Risk
Assessment Scale`), beside WONT, which writes `Surgical debridement`.

* `utils.normalise.sentence_case` is the last step of `Normalised.name`, after
  the singular, the American spelling and the preferred vocabulary (the
  singular rule reads case: `DFUs` is an acronym plural only with its capitals).
* Left exactly as written: a word with a capital after its first letter
  (`MRSA`, `pH`, `mRNA`, `NaCl`), a word with a digit (`Ki67`), a single letter
  or a letter's plural (`T cell`, `the 5 Ps`), a short symbol before a number
  (`Bcl-2`). The first letter is raised only on a plain lowercase ASCII word.
* A capitalised word after the first keeps its capital when it is a name: in
  `utils/proper_nouns.py` (generated by `scripts/build_proper_nouns.py` from the
  strings authors and WONT/MILD wrote with a deliberate mid-name capital: 80 %
  of occurrences, 3 strings, plus the rows read and settled there) or a chemical
  element symbol. A name too rare for the list loses its capital mid-name.
* Untouched: a declared BFO category (rule 22, also when the singular makes one
  of a plural: `processes` -> `process`), and every WONT/MILD label (rule 36).
* `singular_spelling` reads an acronym plural only with two capitals or more:
  `Is`, `As`, `Vs` are words, and as `Is` the name of `is` was cut to `I`.
* Tested in `tests/test_sentence_case.py`.

## 82. First the cluster, then its name: one question per pair verdict, the name a decision of its own

*Decided 2026-10-24, by the curator: "es sollte zunächst um die cluster
formierung gehen. danach sollte ein term aus dem cluster herausgepickt werden."*

* **A pair verdict answers one question** -- how does the term stand to the
  class -- in four words for every source: `same_class`, `narrower`,
  `broader`, `different` (`PAIR_VERDICTS`). The sources are `pass1`, `pass2`,
  `check` and `curator` (`PAIR_SOURCES`). `TermMappingAndGate.judge` refuses
  anything else.
* **The name of a cluster is a decision on the chosen term**
  (`name: {by, instead_of, reason, when}`, `decide_name`, `named`). Every
  election reads it: `canonical_rank(..., named=)` ranks ontology label, then
  a person's choice, then the corpus count (`build_from_embeddings`,
  `resolve_chains`, pass 0). A later choice for the same cluster supersedes the
  earlier, which stays as history.
  *Superseded 2026-10-25 by rule 85: there is no `name` section; the name is
  `to`, and that a person chose it is their `same_class` on the pair.*
* **A lock (`refused`) says "not this cluster" and why**, in `cause` from
  `LOCK_CAUSES`: curator, rule 58, target removed, placement refused. A
  refusal writes a relation only when one was said (`refuse(verdict=)`).
  *Superseded 2026-10-25 by rule 84: there is no lock; the curator's verdict
  keeps a pair apart.*
* **`placement` is a curator entry** with the class `iri` (curator: "die
  beiden kann man wunderbar zu curator mergen"). A place in the hierarchy is
  the curator's `narrower` WITH an `iri` (`placements()`); a `narrower` without
  one is a subtype noted in passing.
* **The restatement check is `check`**, not `curator`: a model read by Claude
  did not become the curator by writing under that name.
* **A merge never keeps a mapping onto a target its own pair locks**
  (`apply_renames`, `locked_mappings()` must be empty).

What it replaced. The curator's entry said `kept`, `refused`, `reverse`,
`reversed`, `repointed`: answers mixed with actions, `reverse`/`reversed` the
same act written by two scripts. A reversal was a lock on the old direction,
which a rebuild naming the cluster through a third member walked past: on
2026-10-20, 41 of the curator's chosen names were not the name, and 30 pairs
were locked and mapped at once. Migrated by `scripts/migrate_pair_schema.py`
(backup `data/backup/term_mapping_before_pair_schema_2026-10-24_19-31.json`).
Tested in `tests/test_pair_schema.py` and `tests/test_placements_view.py`.

## 83. A measure of one wound is in scope; a statistic over a group of wounds is not

*Decided 2026-10-24, by the curator ("I agree with all", on the contested-scope
list that drew this line).*

* **In:** a quantity a single wound has -- `percentage of wound healed`,
  `relative wound area reduction`, `wound duration`, `time to re-epithelialization`.
* **Out:** the same quantity summarised over a cohort -- `mean wound area`,
  `average wound area` (and `median ...` by the same token). The ontology
  carries the wound's area; the mean of it is a result of a study.

The failure: `mean wound area` and `average wound area` were among the 287
terms on which one source had said both `in` and `out` across spellings
(`gate_contested`), and pass 2 had argued each way on different days ("clinical
sign/quality of a wound" against "the statistical mean of ulcer area"). With
the line drawn, the 31 of those terms with no applicable verdict were decided
by the curator the same day (`by: "curator, chat 2026-10-24 (contested
scope)"`, backup `data/backup/term_mapping_before_contested_scope_2026-10-24_20-04.json`);
none of the 287 is left without one.

## 84. No lock beside the verdict: the curator's answer keeps a pair apart

*Decided 2026-10-25, by the curator: "'gehört nicht in diesen cluster' und
'nicht unter dieser Klasse' sind für mich 'different'. lösch die relationen mit
entfernter MILD zielklasse einfach. ... wenn ich das auch noch aufgelöst
bekomme, ist refused überflüssig."*

* **A curator verdict of `narrower`, `broader` or `different` (`APART`) is what
  keeps a pair out of one cluster.** `is_refused` reads it; no build, chain
  resolution or merge maps a term onto a class the curator keeps it apart from.
  A placement (`narrower` with an `iri`) therefore can never merge into its
  parent.
* **`refuse` writes that verdict** -- `different` unless someone said narrower
  or broader -- and unmaps. `judge(refused=...)` raises. A pair onto a class the
  ontologies no longer have is deleted, not refused.
* Superseded: rule 82's lock `refused` with its `cause`. On load, any old lock
  moves to `lock_history`; one without a curator verdict reads as `different`.

The failure: the lock and the verdict were two fields that could say different
things. On 2026-10-24, 271 of the 308 locks carried no verdict at all -- 132
"not this cluster" with no relation named, 87 onto MILD classes that were gone,
35 from rule 58, 17 refused placements -- and 12,901 placed pairs carried a
`narrower` with no lock, so nothing kept a rebuild from merging a placed term
into its parent. Resolved the same morning: 149 locks became the curator's
`different`, the 87 pairs were deleted, and the 35 rule-58 locks were ruled one
by one (30 `different`: misread or ambiguous abbreviations; 5 `same_class` and
mapped onto the full form, the rule-58 `out` withdrawn: `BMP-2`, `FGF-23`,
`MAPK-signaling`, `PANoptosome`, `miRNA-194`). Backups
`data/backup/term_mapping_before_locks_to_verdicts_2026-10-25_08-06.json` and
`..._before_rule58_locks_2026-10-25_08-11.json`.

## 85. The name of a cluster is `to`; a person's choice is their `same_class` on the pair

*Decided 2026-10-25, by the curator: "ich finde den key name für vom Autor
gewählte Begriffe sinnlos. das ist schon to" and "nachvollziehbar bleibt es auch
wenn du an to die entscheidungsmetadaten knüpfst".*

* **No `name` section.** The name of a cluster is the term its members' `to`
  points at. That a person chose it is the curator's `same_class`, with `by`,
  `when` and `reason`, on each loser's pair onto it (`decide_name`). `named()`
  is derived from those pairs and never stored. On load, an old `name` section
  becomes that pair verdict; a choice it had replaced stays in `name_history`.
* **A name stays the name.** `canonical_rank(term, anchors, freq, named,
  heads)` ranks ontology label, a person's choice, the current name
  (`heads()`), then the corpus count. A rebuild does not rename a cluster
  because a member grew more frequent; only an ontology label or a person does.
* **No automatic step withdraws a mapping the curator confirmed.** `retire`
  skips a mapping that carries the curator's `same_class` and prints it.
* **`split_synonyms()` must be empty**: no pair the curator called
  `same_class` may sit in two clusters. The one standing exception is two
  ontology labels naming the same thing (`Ulcus cruris venosum` / `Venous leg
  ulcer`, both WONT labels): the term dict cannot map a label away (rule 36),
  so that is a finding for whoever edits WONT.

The failure: on 2026-10-25, 237 pairs the curator had called `same_class` sat
in two clusters -- withdrawn later by pass 1 dissent, by a prune that did not
follow a respelling, by spelling and category sweeps -- so `Klebsiella` and
`Klebsiella spp.` would have been two classes. And a stored `name` and `to`
could say different things. Repaired by `scripts/rejoin_confirmed_synonyms.py`
after Claude read every planned merge: 17 were wrong, and the wrong link was
mostly not the confirmed pair but a mapping beside it (`Gram-negative bacilli`
= `Gram-negative bacillus` is right; `Gram-negative bacillus` -> `Bacillus
species` was not). The curator's answers to those and to 9 held cases are in
`scripts/apply_rejoin_decisions_2026_10_25.py`; then 205 merges. Backups
`data/backup/term_mapping_before_rejoin_decisions_2026-10-25_18-29.json` and
`..._before_rejoin_2026-10-25_18-33.json`. Tested in `tests/test_pair_schema.py`.

## 86. The concept store is never changed; TermMappingAndGate holds every decision, and there are no lists

*Decided 2026-10-25, by the curator: "Conceptstore ist der concept store und
wird nie verändert, kein blocking, gating oder irgendwas und auch keine liste.
blocker wird gelöscht termmappingandgate hält alle entscheidungen und schluckt
die listen wenn listeneinträge im termmapping fehlen. alle listen werden
gelöscht. die statistikbegriffe sind teil des mapping. weiterhin versucht
SapBERT, vorauszuwählen, was passt und was nicht." -- "pass1, pass2 etc. des
gating bleiben erhalten." -- "(a)" -- "der bereinigte store soll termmapping
nutzen und ein view des concept store sein, der sich bei jedem nutzen neu
berechnet. eine property eben." -- "store cleaner und mapping cleaner kannst
du glaube ich auch löschen".*

* **The concept store stores every extracted string.** No list and no rule
  filters at extraction (`add_llm_extracts`, `_extract_schema_constrained`): whether a
  string belongs is a verdict, never a gap in the evidence.
* **The cleaned store is a view**: `ConceptStore.cleaned`, recomputed on every
  read. It is the evidence read through TermMappingAndGate -- names resolved
  by the mapping, terms and relation targets the gate puts out left out,
  rejected cells left out -- plus two rules applied live, never written: a
  relation whose predicate the schema does not allow (`allowed_predicates`)
  is left out, and an entity nothing affirms anywhere in the store is left
  out (a denial stays where the term is asserted elsewhere).
* **Scope is the gate's effective verdict and nothing else**: `curator`, then
  `pass2` (the model), `pass1` (SapBERT's nearest neighbour at 0.95), `rule`.
  Pooled over the cluster, so one spelling of an in-scope concept is not
  dropped on its own (it was: `Plain radiograph`, a spelling of `Plain
  X-ray`, in one abstract).
* **One rule over strings stays, in code**: `noise_rule` (a number with a
  unit, or no letter at all). A new term that matches gets `out` from the
  `rule` source in `scripts/p4_gate_pass1.py`, before SapBERT; a curator's
  `in` beats it (`NaCl 0.9%`).
* **Deleted** (to `data/removed_code/*_removed_2026-10-25.py`):
  `config/blocklist.py`, `config/whitelist.py`, `config/suspicious_list.py`,
  `store/blocker.py`, `store/term_lists.py`, `store/store_cleaner.py`,
  `store/base_cleaner.py`, `store/cluster_promoter.py`,
  `mappers/mapping_cleaner.py`; the orchestrator's `export_gate_lists`,
  `gate_lists_drift`, `gate_overrides`, `review_mapping`, `review_lists`,
  `cluster_blocklist`, `recluster_lists`, `run_promote_clusters`,
  `run_clean_store`. `run_apply_mapping` only sets the mapping the view reads.

How the lists were swallowed (`data/removed_code/absorb_lists_2026_10_25_spent_2026-10-25.py`,
backup `data/backup/term_mapping_before_absorb_lists_2026-10-25_19-23.json`):
every entry of the two exact lists already had a verdict of its own; 238
keyword and suspicious entries without a record got one (the statistics
words `out`, the whitelist keywords `in`, the suspicious ones none); what the
keywords decided about store terms became a `rule` verdict naming the keyword
(51 kept out, e.g. `Standardized form` by `standardized`; 41 let in over the
old list entry, e.g. `Maggot debridement therapy`, the old verdict in
`rule_history`); 184 measurements got the noise rule. The view through
TermMappingAndGate alone then equalled the Blocker's term for term, checked
before the save and after the read-back.

The failure that made it necessary: the lists were a view of the gate since
2026-09-25 and still decided things. The Blocker read a whitelist keyword
ahead of the gate's own `rule` verdict, so `Abusive head injury` was `out` on
its record and `in` in every view, and nothing on the record said why; the
store dropped blocklisted strings at extraction, so an `out` withdrawn later
had nothing to bring back; and a new domain would have needed lists of its
own, where the scope passes need only its description.

## 87. A decided category is the is_a it settles; a term used for two things points at one name per category

*Decided 2026-10-26, by the curator: "category macht keinen sinn wenn es is_a
gibt, senses auch nicht gut. to: sollte dann zwei begriffe enthalten je
nachdem. und es sollte zwei neue einträge für biopsy sample und biopsy
material geben." -- on where the category goes: "in pairs gibt es is_a:
target. dahinter kann man metadaten einreihen." -- names: "Biopsy procedure +
Biopsy material"; the material sense: "In aufnehmen".*

* **The category is a relation.** A person's decision about the BFO category
  a term names (rule 57) is written as the `is_a` cell it settles, in the
  term's `relations`, with the metadata behind it:
  `"is_a: material entity": {"status": "decided", "source", "by", "note", "when", "history"}`.
  The abstracts' `is_a` cells in the concept store are what each abstract
  said; the decided cell is the one answer where they disagree. At most one
  decided `is_a` per term. `set_category` / `categories()` read and write it;
  the view applies it exactly as before (rule 57).
* **A decided `is_a` is not a verdict on a cell.** `reject_cells` and
  `repredicate_cells` do not overwrite it (reported), and `lift_decisions`
  leaves it.
* **A split is where the term points.** A term the abstracts use for two
  things has `to: {"<category>": "<name>", ...}` instead of a `senses`
  section: `Biopsy -> {process: Biopsy procedure, material entity: Biopsy
  material}`. Each name is a term with a record of its own, and no name is
  the split term itself. The view gives each mention the name for the
  category its own abstract typed it as, BEFORE it reads the verdicts, so the
  scope of `Biopsy material` decides about its mentions; a mention typed with
  no category, or with two, keeps the unsplit name. A split term is absent
  from `data` (no ONE name), is a member of each of its names' clusters (their
  scope pools what was said about it), and is never overwritten by a machine
  mapping (`add_batch` skips it, `add` raises, `retire` keeps it).
* **Old files load**: `_load` moves a `category` section into `relations` and
  a `senses` section into `to`, and says how many; a term that had both a
  one-name `to` and senses stops the load.

Applied by `scripts/apply_rule87_biopsy_2026_10_26.py` (1,090 categories moved;
the Biopsy split renamed from `Biopsy` / `Biopsy sample`; the curator's
placement under OBI's sample collection process moved onto `Biopsy
procedure`; `Biopsy material` in). Tests: `tests/test_rule87_is_a_and_split_to.py`.
Then, the same day (curator: "ja, beides so machen"), by
`scripts/apply_biopsy_rulings_2026_10_26.py`: `Biopsy sample` (and its
spellings `biopsy specimen(s)`) maps onto `Biopsy material` with the curator's
`same_class` (21 mentions of the material sense now, 16 + 5); and the head
rule `biopsy` is `process`, no longer `material entity`, so `Wound biopsy`
(placed under WONT's wound specimen procurement by biopsy process) and `Skin
biopsy` are procedures.

Why: a `category` section beside `relations` decided an `is_a` under another
name, and a `senses` section beside `to` said where the term points in a
second place. Two places for one decision is how the term dict and the store
drifted before rule 51.

## Adding to this file

When a universal design choice is made:

1. Add a numbered rule with the date it was decided.
2. State the rule first, then the concrete failure that motivated it — the
   failure is what makes the rule memorable and checkable.
3. If it supersedes an existing rule, keep the old text and note what replaced it.
4. Where the rule has teeth in the code, name the function or file that enforces
   it, so the rule and its enforcement can be checked against each other.
