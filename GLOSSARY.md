# Glossary

The words this project's documents, logs and commit messages use as if they were
obvious. Grouped by where you meet them. Clinical knowledge is assumed; pipeline
knowledge is not.

---

## The two curated ontologies

**WONT** — the wound ontology, `data/ground truth/ground_truth_final.owl`. Turtle,
despite the `.owl` extension. The artefact this whole project exists to build.

**MILD** — the disease ontology it imports, `../Disease ontologies/Disease proposal 2.ttl`.
Owns the disease-level vocabulary (disease course, complication, plan specification).

**curated** — written by hand, by you. The opposite of *derived*. Nothing in the
pipeline may write to a curated file; it proposes, you edit in Protégé.

**foreign class** — a class owned by an external ontology (DOID, FMA, CHEBI, HP, GO,
OBI, IAO, BFO, OGMS) that WONT or MILD imports. We never write definitions on one
(rule 34).

**mint** — create a new class with a new IRI in the `WONT_` or `MILD_` namespace.
"Minting a twin" is the failure this pipeline guards against: creating
`Granulation Tissue Formation` when `Granulation tissue formation process` already
exists.

**alt term** — `IAO_0000118`, an alternative label on a class. A demoted label stays
as one, so anything that matched the old name still finds the class.

**relatedMatch** — a `skos` link saying two classes are close but *not* the same.
A mapping that merges two classes related by `relatedMatch` contradicts an axiom
you wrote.

**plan specification** — an `IAO_0000104` information entity describing how something
is to be done. Standing naming rule: every class under it carries the words "plan
specification" in its label.

---

## The store

**concept store** — `data/cache/concept_store_*.json`. Everything extracted from
every abstract, keyed by PMID. The one record: decisions live *inside* it as
verdicts, never as deletions or side files (rule 33).

**mention** — one occurrence of a term in one abstract. "220 mentions" means the
term was extracted from 220 abstracts, not that it is important.

**entity / target** — an extracted term is an *entity*; the object of one of its
relations is a *target*. `wound — located_in: foot` has entity `wound`, target `foot`.
Both are names the mapping renames.

**triple / assertion / cell** — one relation on one entity in one abstract
(`predicate: target`, with a truth value). The store is a matrix of these; "cell"
is the matrix word for the same thing.

**verdict** — a decision recorded beside an assertion or an entity (rejected, by
whom, when). Rejecting is how things are removed; nothing is deleted.

**typing** — the BFO category an abstract gave a term (`is_a: process`). Stage-1
extraction types every term, so one term can carry several typings across
abstracts, and they can disagree.

**category** — one of the fifteen BFO names (`material entity`, `process`, `quality`,
`disposition`, `role`, `function`, `information entity`, …). A category is
*declared*, never matched by similarity (rule 20).

**continuant / occurrent** — BFO's top split. A continuant persists through time
(a wound, a dressing); an occurrent unfolds in time (healing, debridement).
Merging one into the other is the error the category guard exists to prevent:
`Necrosis Process` is an occurrent, `Necrosis` a continuant.

**category clash** — a proposed merge whose two sides are typed into disjoint BFO
branches. Evidence of either a wrong merge or a wrong typing; both matter.

---

## The term mapping

**term mapping** — `data/cache/term_mapping_*.json`. Since 2026-09-24 it is the
**ground truth**: one record per term holding everything ever decided about it.
The plain `term -> canonical` dict everything applies is a *view* of it.

**ground truth** vs **view** — the ground truth is the one file a fact is stored
in. A view is computed from it whenever asked and never stored, so it cannot go
stale or disagree. `data` (the live mapping), `pass_cache`, `verdicts`,
`subsumption_candidates`, `disagreements` and `metadata` are all views of the
mapping records. When you see two artifacts carrying the same fact, one of them
is wrong and nobody knows which — that is why the two adjudication cache files
were folded in.

**canonical** — the spelling a group of variants collapses onto, and later the
class label. `wounds`, `Wound`, `wound` all have canonical `Wound`.

**anchor** — a WONT or MILD class label put into the clustering so a store term
that means the same thing is mapped *onto the existing class* rather than minted
beside it. Historically defined as the labels that are **not** also store terms —
which is why the category guard used to go quiet whenever a class label was
common enough to be extracted.

**anchor mapping** — a mapping whose canonical is an ontology label. An identity
claim on an existing class: irreversible downstream, and therefore adjudicated.

**store-to-store merge** — a mapping between two extracted terms, touching no
class. A wrong one costs a duplicate term rather than a wrong class.

**SapBERT** — the biomedical sentence embedder that proposes candidate merges by
cosine similarity (threshold 0.95). It cannot tell a process from its material
bearer — their labels are nearly identical — which is why a model adjudicates
after it.

**complete linkage** — two clusters merge only if *every* cross-pair passes the
threshold, so one loose pair cannot drag two groups together.

**singular spelling** — the store's names are singular, always (`Diabetic Foot
Ulcers` is kept as `Diabetic Foot Ulcer`). A rule about the name, applied in
`normalize` after the mapping has had its say, not a decision recorded per term.

**naming singular** vs **lookup singular** — two different jobs, and conflating
them is what put `cas`, `dos` and `nurs` in line to be written into the store.
`-es` is genuinely ambiguous: `buses -> bus` drops two characters, `phases ->
phase` drops one, and the two look identical. A LOOKUP can try both candidates
and let the vocabulary decide, so `singularize` takes the first and a wrong
guess costs nothing. A NAME has to pick one and live with it, so
`naming_singular` decides by group — `-ses`/`-zes` keep the `e` (`cases ->
case`), `-ches`/`-shes`/`-xes` drop it (`searches -> search`), and the stems
that are already words (`virus`, `census`, `gas`) are listed because no suffix
separates them from `cause` or `house`. All-caps tokens are acronyms and are
left alone: `ARDS` is not the plural of `ARD`.

**inert entry** — a mapping entry whose result is what the store would produce
anyway, so it cannot change an outcome. Case-only entries were inert from the
start; plural entries became inert when the store took on the singular rule.

**fold** — compare two labels ignoring case, punctuation and plural
(`normalize_term`, and `fold` which also singularises). "Folded space" means the
graph the store actually walks: it looks a term up by its exact spelling first
and by its folded spelling second.

**surface form** vs **content difference** — how two labels differ. `identical`
(case, punctuation, spacing), `inflection` (singular/plural), or `content` (a real
word changed). Only `content` pairs are put to the model; the other two were
measured safe to accept.

**mechanical classes** — my grouping of the content pairs that are still not real
differences: **spelling** (British/American, hyphenation: `haemorrhage` /
`hemorrhage`), **word order** (`healing time` / `time to healing`), and
**abbreviation** (`MRI` / `magnetic resonance imaging`). One decision each covers
all of them.

**adjudication** — the LLM judging a proposed merge. Verdicts: `same_class`,
`narrower`, `broader` (subsumption candidates — not synonyms, but a hierarchy
hint), `different` (refused and withdrawn).

**pass cache** — the memory that stops a rebuild paying to ask the same question
twice. It used to be two files (`mapping_adjudication_*.json`,
`mapping_second_opinion_*.json`); it is now a view over the records, so asking
the model writes the answer onto the entry it is about. A cached verdict was
still a model verdict — only the second call is skipped, not the judgement.

**pass 1 / pass 2** — pass 1 is the adjudication that has run: definitions attached
for anchor pairs, no categories for store pairs. Pass 2 is a second, independent
judgement with *different* evidence (BFO categories, the continuant/occurrent rule
stated). Only rows where the two disagree go to you.

**record** — what the mapping file holds per term: the canonical, how it was
decided, whether it has been retired, and a **pair** entry for each canonical the
term has ever been judged against.

**pair** — one (term, canonical) question and everything said about it: `pass1`,
`pass2`, the curator's verdict, and any refusal. Keyed by canonical because a
term is judged against more than one — 192 of them are — and `different` about
one canonical says nothing about another.

**refuse** vs **retire** — refusing records a verdict against that exact pair,
unmaps it, and the next build honours it: a decision. Retiring only unmaps, with
a reason, for an entry that can no longer do anything — an identity, a dead
target, an inert spelling. Neither deletes: the record and its verdicts stay
either way, because the model's answer cost credits and a deleted pair is one the
next build pays to ask again. (Before the distinction existed, a curator's
refusal was re-proposed and re-approved by the next rebuild.)

**re-point** — change an entry's canonical.

**prune** — drop entries that can no longer fire: identities, and entries whose
canonical exists nowhere any more.

**chain / cycle / forest / fixed point** — `A -> B -> C` is a chain; `A -> B` with
`B -> A` is a cycle. The file must be a *forest*: every entry points at something
that is not itself mapped. The store follows exactly one hop, so a chain
half-lands the merge and a cycle undoes it. A *fixed point* is the state where
applying the mapping again changes nothing.

**family** — all the terms that collapse onto one canonical, reviewed as a unit.
`Debridement process` gathers `debridement`, `Debridement`, `debridements`,
`debridement procedures`, `debridement procedure`: five entries, one decision.
4,813 entries are 3,574 families.

**identity entry** — a mapping entry whose term and canonical are the same string.
It does nothing (an unmapped term is returned unchanged), and rule 19 removes
them; they were once 92% of the file.

**suggested** — the verdict the sheet proposes for a row, filled by rule, with the
rule stated in the `why` cell. You override it; you do not start from nothing.

**mention mass** — how many mentions a set of rows moves. Used to sort review by
consequence: the top 101 rows move half of everything.

---

## The curation lists

**methodology blocklist** — 7,757 names that are not clinical content
(`randomized controlled trial`, `SPSS`). Applied at *extraction*, by exact
lowercase name, and never again.

**keyword blocklist / whitelist** — short words matched inside a name, whole-word
only (rule 27: `rct` must not match "infa**rct**ion"). The whitelist protects names
the blocklist would otherwise catch.

**noise term** — a name rejected by shape rather than by a list (empty, numeric,
punctuation).

**blocked canonical** — a mapping whose target is on the blocklist. Renaming a good
term onto one resurrects the blocked name in the store and queues the whole family
for deletion.

---

## Reasoning and the build

**skeleton** (reasoner skeleton, skeleton TBox) — `output/owl/skeleton_tbox.ttl`:
the class hierarchy of WONT + MILD + their imports, stripped of individuals and
annotations, cached so the gates can reason quickly. It rebuilds itself when WONT
or MILD is newer, and it is what tells the pipeline which BFO category a class
belongs to. Everything that "asks the ontology a question" asks the skeleton.

**ELK / HermiT** — reasoners. ELK is fast and handles the profile the per-batch
gate needs; HermiT is complete (inverses, cardinality, universals) and is the gate
that has to come out clean before the ontology is published.

**gate** — a step that reasons over proposed content and quarantines what does not
hold. `run_gate_store_relations` for relations, `run_gate_hierarchy_edges` for
hierarchy edges.

**quarantine** — a rejection recorded in the store, re-testable later. Not a
deletion.

**provenance / stamp** — which source an edge came from (curated, FCA, lexicon),
recorded so precedence rules can be applied and so an edge can be re-judged.

**module / MIREOT / closure** — an external ontology is never imported whole: a
*module* holds only the terms used plus their ancestors (MIREOT), built by
`build_disease_proposal.sh`. The *closure* is everything that ends up loaded once
imports are resolved.

**FCA / lattice / context matrix** — Formal Concept Analysis. The context matrix is
terms × attributes; the lattice is the hierarchy that falls out of it, used as a
source of candidate superclasses.

**CQ (competency question)** — a question the ontology must be able to answer,
written as a SPARQL-checkable triple in `config/competency_questions.json`. The
score (49/49) is the measurement that says the ontology works.

---

## Process vocabulary

**P0–P6, PC** — the roadmap's phases. **PC** was the corpus extraction; **P4** is the
single derived rebuild (mapping → lists → gates → hierarchies → FCA → extend →
CQ check); **P5** is HermiT; **P6** is BioPortal.

**rule N** — a numbered standing design rule in `INSTRUCTIONS.md`, with the failure
that motivated it and the code that enforces it. "Rule 23" is cited the way a
statute is.

**mutation-checked** — after writing a test, the implementation is deliberately
broken in a specific way to confirm a *named* test fails. A test that passes
against a broken implementation tests nothing (rule 16).

**silent failure** — anything that fails, degrades or drops data without saying so.
The standing rule is that nothing may; most serious defects in this project were
quiet, not loud.

**dry run** — a step that measures and reports what it would do, and writes nothing.
Most destructive steps have one.
