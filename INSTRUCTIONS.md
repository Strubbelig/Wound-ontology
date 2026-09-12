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
Verdicts are cached in `mapping_adjudication`; re-ask with `readjudicate=True`
after the ontologies' definitions change.

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

Enforced by: `TermMapper._canonical`;
`test_the_singular_spelling_is_canonical_even_when_rarer`,
`test_an_anchor_stays_canonical_however_it_is_spelled`,
`test_the_rule_never_trades_one_concept_for_another`, and
`test_without_anchors_the_frequent_store_term_wins` rewritten onto a case pair so
it still tests frequency rather than this rule.

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

`ident()` in `scripts/build_extraction_schema.py` is the one place the CamelCase
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

## Adding to this file

When a universal design choice is made:

1. Add a numbered rule with the date it was decided.
2. State the rule first, then the concrete failure that motivated it — the
   failure is what makes the rule memorable and checkable.
3. If it supersedes an existing rule, keep the old text and note what replaced it.
4. Where the rule has teeth in the code, name the function or file that enforces
   it, so the rule and its enforcement can be checked against each other.
