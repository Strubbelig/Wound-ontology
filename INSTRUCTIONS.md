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

## Adding to this file

When a universal design choice is made:

1. Add a numbered rule with the date it was decided.
2. State the rule first, then the concrete failure that motivated it — the
   failure is what makes the rule memorable and checkable.
3. If it supersedes an existing rule, keep the old text and note what replaced it.
4. Where the rule has teeth in the code, name the function or file that enforces
   it, so the rule and its enforcement can be checked against each other.
