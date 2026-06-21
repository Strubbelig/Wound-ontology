# Ontology-Extraction Pipeline — Upgrade Plan

Goal: add (A) SPIRES-style **entity grounding + prefix validation**, (B) a **relation-classification layer** that fixes the `subclass_of` vs `part_of` confusion, and (C) the transferable parts of **LLM ontology-prompting**, without disturbing the parts you already have (LLM/Pydantic extraction, FCA layer, SapBERT evaluation with block/whitelist, SapBERT cluster+merge, OWL transform, OWL reasoning).

---

## 1. Current pipeline (as you described it)

```
(1) LLM extraction → Pydantic JSON
       entities + attributes{ predicate, target }
       (already-extracted entities/attrs fed back into prompt)
(1b) Formal Concept Analysis layer — objects × attributes → concept lattice
(2) SapBERT entity evaluation  — blocklist / whitelist filtering
(3) SapBERT clustering + merge — mapping dictionary → canonical entities
(4) OWL transformation
(5) OWL validation / reasoning
```

Three structural facts drive everything below:

- **Your `predicate` slot mixes two ontologically different things.** `subclass_of` is subsumption (`rdfs:subClassOf`), a logical relation between classes. `part_of` is an object property (`RO:0000050`). Putting both in one slot tells the model they are interchangeable choices — a direct contributor to the confusion. The fix is structural, not a better prompt.
- **You already have an FCA layer — so you already have a formal source of subsumption.** A concept lattice's order relation *is* `subclass_of`: a formal concept below another is a more specific subconcept. The design is **LLM-as-evidence, FCA-as-judge**: the LLM still proposes `subclass_of`, but its proposals enter the FCA formal context as *attributes* (tiered by trust) rather than as final edges, and the lattice — gated by BFO categories and the reasoner — is the sole arbiter that emits subsumption. This reclaims the LLM's taxonomic knowledge (and fills FCA's attribute gaps) without reinstating the subclass_of/part_of failure mode. This is the single biggest lever on your subclass_of/part_of problem, and it's a layer you already run. (See §2A.)
- **SapBERT already does fuzzy entity normalization**, but it does not assign authoritative cross-ontology persistent IDs (CURIEs) with validated prefixes. That is precisely the gap SPIRES grounding fills, and it slots in cleanly *after* your merge step.

---

## 2. Target pipeline

New/changed steps marked **[NEW]** / **[CHANGE]**.

```
(1) LLM extraction → Pydantic JSON
       [CHANGE] LLM emits entities, object-property relations, AND candidate subclass_of
                — but candidate subclass_of is EVIDENCE, not a final edge.
         - entities[]
         - relations[]        (object properties only — BFO/RO subset)
         - candidate_subclass_of[]    (LLM-proposed subsumption → routed into FCA attributes)
(1b) FCA layer (you have it) → concept lattice = the JUDGE
       [CHANGE] formal context fuses tiered-trust attributes:
                intrinsic properties + predefined-table superclasses (hard)
                + LLM candidate_subclass_of (soft). Lattice order = the subclass_of hierarchy.
         - subsumptions[] are READ OFF the lattice, gated by BFO + reasoner
(2) SapBERT entity evaluation (unchanged)
(3) SapBERT clustering + merge (unchanged) → canonical entities
(4) [NEW] Entity grounding         — canonical entity → CURIE candidates (OAK/annotators + SapBERT)
(5) [NEW] Prefix validation        — gate CURIEs against an allowed prefix registry
(6) [NEW] BFO category typing      — assign each canonical entity a BFO top-level category
(7) [NEW] Predicate grounding+menu — per entity pair, type-filter the allowed predicate set
(8) [NEW] Relation classification  — decomposed object-property decision (part_of vs located_in, etc.)
                                     with definition-grounded, label-anonymized prompting
(9) [NEW] Verification pass         — adversarial critique / majority vote; flag low-confidence
(10) OWL transformation (unchanged, but consumes FCA-derived subclass_of + LLM relations separately)
(11) OWL reasoning (unchanged + [CHANGE] add BFO disjointness & subclass_of-cycle checks)
```

Step 1b = FCA owns subsumption (your existing layer, repurposed). Steps 4–5 = the SPIRES borrow. Steps 6–9 = the relation layer (the part that actually moves your metric). Steps 10–11 are mostly reused.

Note how the subclass_of/part_of confusion is now defused rather than banned: object properties are extracted by the LLM; subsumption is *adjudicated* by FCA. The LLM's subclass_of proposals enter as soft attributes, so a mislabeled part_of becomes one noisy attribute among many — washed out by the closure operator and the other evidence, or surfaced as an anomaly — instead of a wrong final edge.

---

## 2A. Component 0 — FCA as the `subclass_of` JUDGE; LLM subclass_of as evidence (step 1b)

You already run FCA after extraction, so the highest-leverage change costs you almost nothing: **the LLM proposes `subclass_of`, but the concept lattice decides it.** LLM proposals enter the formal context as attributes (tiered by trust, §2A.5a); the lattice — gated by BFO categories and the reasoner — emits the final subsumption edges. This is strictly better than either "LLM owns subclass_of" (hallucination, subclass_of/part_of confusion) or "FCA owns subclass_of alone" (attribute-gap brittleness, can't place attribute-poor entities).

### 2A.1 Why this works

In FCA a formal concept is a pair `(extent, intent)` — a set of objects and the set of attributes they all share. The lattice order is, by construction, subsumption: if concept `C1` sits below `C2`, then `C1`'s extent ⊆ `C2`'s extent and `C1`'s intent ⊇ `C2`'s intent — i.e. `C1 subclass_of C2`. This is a *deterministic, formally grounded* taxonomy derived from shared attributes.

The LLM's role is **evidence, not adjudication**. Because its `subclass_of` proposals enter as attributes rather than as edges, three good things happen: (i) its real taxonomic knowledge ("hepatocyte subclass_of cell") is reclaimed instead of discarded; (ii) it can place entities that have too few intrinsic attributes for FCA to position on its own (the LLM-supplied superclass attribute *is* the signal that lets the lattice place them); and (iii) a mislabeled `part_of→subclass_of` is just one noisy attribute, defanged by the closure operator and the BFO/reasoner gate rather than emitted as a wrong edge. The LLM never emits a *final* subsumption edge — preserving the safety of the original "FCA owns subclass_of" design while recovering its lost signal.

### 2A.2 What to feed FCA as "attributes"

The lattice is only as good as the attribute set. Three sources feed it (their trust tiers are formalized in §2A.5a):

- **Intrinsic, defining properties** (qualities, dispositions, has-part signatures, BFO category). These produce clean genus–differentia subsumption. *Medium-high trust.*
- **Predefined-table superclasses** (§2A.5). Each known superclass becomes a `subclass-of-<Class>` attribute. *Hard / ground-truth trust.*
- **LLM candidate subclass_of** (the new evidence channel). Each LLM-proposed superclass becomes a `subclass-of-<Class>` attribute on the entity's row. *Soft trust — must corroborate or clear the reasoner before an edge resting on it alone is accepted.*
- **Keep OUT of the FCA context:** the object-property *relations* the LLM extracts (part_of, located_in, …). Mixing partonomic relations into the FCA attribute set corrupts the lattice — that is the formal echo of the same subclass_of/part_of conflation, just moved upstream. Object properties belong to the LLM relation channel (steps 6–9), not the FCA context.

Note the LLM contributes to FCA in two distinct ways: **`subclass-of-X` attributes** (taxonomic evidence, allowed) versus **binary object-property relations** (kept out). Only the former enters the formal context.

### 2A.3 Lattice → ontology classes (the hard part)

FCA produces many formal concepts, including intensional/intermediate ones with no named label. To turn the lattice into OWL subsumption:

1. **Map named entities to their concept(s)** in the lattice (object → its object-concept).
2. **Materialize edges**: for each covering edge `C1 ≺ C2` in the lattice, emit `subClassOf(C1, C2)`.
3. **Handle unnamed intermediate concepts**: either (a) keep them as anonymous OWL class expressions defined by their intent, or (b) prune them and transitively connect their named neighbors, depending on whether you want the intermediate abstractions in the final ontology. Make this a configurable policy.
4. **Reconcile with grounded CURIEs**: if two formal concepts ground (step 4) to the same ontology term, merge them; if a lattice edge contradicts the reference ontology's own subsumption (e.g. lattice says A ⊑ B but CL says B ⊑ A), flag for review — these contradictions are valuable QA signal.

### 2A.4 Cross-check FCA against BFO categories

Once BFO typing (step 6) exists, assert that a lattice subsumption edge is only valid when child and parent share a BFO category. An FCA edge that crosses categories (a process coming out as a subclass of a material entity) signals a bad attribute in the context — surface it rather than emitting it. This is the same disjointness check used in reasoning (§5.2), applied earlier to lattice edges.

### 2A.5 Do NOT use FCA alone — the three-layer hierarchy

FCA on its own is brittle: a concept lattice is only as good as its formal context, and **gaps in attribute assignment** collapse or invent concepts. FCA is therefore the *bottom* discovery layer, not the whole taxonomy. The class hierarchy is built from three sources, top to bottom:

```
BFO            (upper ontology — material entity, process, quality, …)   = typing layer (step 6)
  ▲ subclass_of
domain classes (your predefined subclass/superclass table)               = asserted backbone (ground truth)
  ▲ subclass_of
FCA-discovered fine structure (concept lattice)                          = fills below/between the backbone
  ▲ instance_of
extracted entities
```

**Filling the attribute gaps (the brittleness fix):**

- **Attribute exploration (Ganter).** The textbook remedy for incomplete contexts. It poses implication questions — "does every object with attributes {A,B} also have C?" — and fills missing incidences. Classically a human expert answers; here the **LLM answers the implication questions**. This is a far better use of the LLM than asking it for `subclass_of` directly: it is constrained, local, and checkable.
- **Imputation.** Use SapBERT similarity to impute obviously-missing attributes before building the lattice (entities very close in embedding space likely share attributes one of them is missing).

**Integrating your predefined subclass/superclass table (the key technique):**

*Conceptual scaling by superclass attributes.* For each object in the formal context, add **all of its known superclasses** (from your table) as additional formal attributes. Consequences:

1. The lattice is now *guaranteed* to respect your predefined hierarchy — two objects sharing a superclass-attribute are forced into the correct order, so FCA cannot contradict the table.
2. FCA still discovers *additional* structure from the remaining attributes, below and between your asserted edges.
3. The asserted backbone props up the skeleton exactly where attribute assignment is sparse, mitigating §2A.5's brittleness.

Alternative (looser coupling): treat the table as an **asserted backbone (ground truth)** emitted directly to OWL, and let FCA only *propose new* edges not already in the table; route proposals to review before merging. Use this if you don't want FCA to ever restructure asserted edges.

### 2A.5a Tiering the FCA attributes by trust (LLM-as-evidence, FCA-as-judge)

All three attribute sources flow into one formal context, but they are **not equally trustworthy**, so each attribute carries a trust tier. The lattice fuses them; the tier governs how an emitted edge is gated before it is accepted.

| Tier | Source | Attribute | Gate before accepting an edge that depends on it |
|---|---|---|---|
| **T0 — hard (ground truth)** | predefined subclass/superclass table | `subclass-of-<Class>` | none; asserted backbone, may be emitted directly to OWL |
| **T1 — derived (formal)** | intrinsic properties (qualities, has-part, BFO) | the property itself | accept if BFO-category-consistent (§2A.4) and reasoner-clean (§5.2) |
| **T2 — soft (evidence)** | LLM candidate subclass_of | `subclass-of-<Class>` | accept only if **corroborated** (also supported by ≥1 T0/T1 attribute) OR it clears BFO + reasoner *and* a confidence threshold; else → review queue |

Adjudication rules:

1. **Compute the lattice over all tiers together** — fusion happens in one closure computation, not three separate runs. (Optionally weight/annotate edges with the highest tier that supports them.)
2. **Provenance per edge.** For each emitted `subClassOf`, record which attributes (and tiers) produced it. An edge supported by T0 or T1 is auto-accepted; an edge resting *only* on T2 attributes is held for the gate.
3. **T2-only gate.** A purely LLM-evidenced edge must (a) pass the BFO-category check (§2A.4), (b) introduce no reasoner inconsistency or subclass_of cycle (§5.2), and (c) exceed a confidence threshold (e.g. agreement across N samples, §4.3a verification). Otherwise it goes to the review queue rather than the KB.
4. **Conflict = signal.** If a T2 attribute would force an edge that contradicts a T0 edge or a reference-ontology subsumption (§2A.3.4), do not silently drop it — flag it. These conflicts are the highest-value QA output: either the LLM is wrong (discard) or your table/ontology has a gap (fix it).
5. **Mislabeled part_of is contained.** Because a stray `part_of→subclass_of` enters only as a single T2 attribute, it cannot by itself produce an accepted edge (rule 3 stops it) and will usually be outvoted by the intrinsic/T0 attributes — the failure mode is contained, not reintroduced.

Net effect: you get the LLM's taxonomic recall *and* the formal layer's precision, with a tunable trust dial (raise the T2 threshold for precision, lower it for recall).

### 2A.6 BFO as the schema? Upper layer, not instance schema

Your reading of SPIRES is correct — every extracted entity is an instance of a schema class — but **BFO is the wrong granularity to be that schema.** BFO's ~35 classes are all upper-level abstractions; if BFO *were* the schema, every entity would just be an instance of "process" or "material entity." That is *typing*, not domain modeling, and you'd throw away all domain detail.

The correct pattern (standard across OBO ontologies): BFO is the **upper anchor**, your domain classes specialize it.

- The **extraction schema** = your domain classes (from the predefined table), each declared `subclass_of` a BFO class.
- **Entities** are instances of *domain* classes, not of BFO directly.
- **BFO typing (step 6)** does double duty: it is the typing layer *and* the upper anchor that every domain class hangs from, which is what makes the predicate matrix (step 7) and the disjointness checks (§2A.4, §5.2) work.

So: yes, BFO is in the schema — as its top — but the classes entities instantiate are your BFO-anchored domain classes, with FCA discovering structure beneath them.

---

## 3. Component A — SPIRES-style grounding + prefix validation (steps 4–5)

### 3.1 What grounding adds on top of SapBERT

| Layer | Role | Output |
|---|---|---|
| SapBERT (you have it) | dense-embedding fuzzy match; merges surface variants/synonyms into one cluster | canonical cluster |
| **Grounding [NEW]** | assign that cluster an authoritative persistent ID across one or more ontologies | CURIE(s) e.g. `CL:0000540` |
| **Prefix validation [NEW]** | gate: is the CURIE's prefix allowed for this entity class? | accept / reject / flag |

SapBERT answers "are these the same thing?"; grounding answers "what is the official ID of that thing?"; prefix validation answers "is that ID from a source we trust for this class?". They are complementary, not redundant.

### 3.2 Grounding implementation

Use OAK (Ontology Access Kit) — the same library OntoGPT/SPIRES grounds with — rather than adopting SPIRES wholesale.

```python
from oaklib import get_adapter

class Grounder:
    def __init__(self, class_to_resources: dict[str, list[str]]):
        # e.g. {"Cell": ["sqlite:obo:cl"], "Disease": ["sqlite:obo:mondo"], ...}
        self.adapters = {res: get_adapter(res)
                         for ress in class_to_resources.values() for res in ress}
        self.class_to_resources = class_to_resources

    def ground(self, label: str, entity_class: str) -> list["Candidate"]:
        cands = []
        for res in self.class_to_resources.get(entity_class, []):
            for curie in self.adapters[res].basic_search(label):
                cands.append(Candidate(curie=curie,
                                       label=self.adapters[res].label(curie),
                                       source=res, method="lexical"))
        return cands
```

Reconciliation policy when SapBERT and the lexical grounder disagree (common, and worth handling explicitly):

1. Lexical exact-match on a primary/synonym label → accept.
2. Else SapBERT top candidate above a cosine threshold → accept, tag `method="sapbert"`.
3. Else if both produce candidates but they conflict → keep both, mark `ambiguous=True`, send to human review queue.
4. Else ungrounded → keep as a free-text leaf (do not fabricate an ID; SPIRES's key discipline is "never invent an identifier").

### 3.3 Prefix validation

This is the cheap, high-value SPIRES gate. Maintain an allow-list per entity class, with prefixes drawn from BioRegistry (uppercase, canonical form).

```python
ALLOWED_PREFIXES = {
    "Cell":     {"CL"},
    "Disease":  {"MONDO", "MESH", "DOID"},
    "Chemical": {"CHEBI", "DRUGBANK", "MESH"},
    "Process":  {"GO"},
    # ...
}

def validate_prefix(candidate, entity_class) -> bool:
    prefix = candidate.curie.split(":", 1)[0].upper()
    return prefix in ALLOWED_PREFIXES.get(entity_class, set())
```

Rules:
- Normalize all prefixes through BioRegistry (`bioregistry.normalize_prefix`) so `MeSH`, `mesh`, `MSH` all collapse to `MESH`.
- A grounded candidate whose prefix fails validation is **rejected, not silently kept** — this is the behavior that stops hallucinated/garbage IDs entering the KB.
- Log every rejection with the original label + offending CURIE; this log is your grounding-quality dashboard.

### 3.4 Pydantic schema additions

```python
class GroundedEntity(BaseModel):
    text: str                       # original span
    canonical_label: str            # post-SapBERT merge
    entity_class: str
    curie: Optional[str] = None     # grounded ID, prefix-validated
    grounding_method: Optional[Literal["lexical", "sapbert", "manual"]] = None
    bfo_category: Optional[str] = None   # filled in step 6
    ambiguous: bool = False
    review_required: bool = False
```

---

## 4. Component B — Relation-classification layer (steps 6–9)

This is where your real bottleneck lives. Four sub-parts.

### 4.1 Step 6 — BFO category typing

Assign every canonical entity exactly one BFO top-level category. This is the lever that makes everything downstream mechanical.

Minimal category set (BFO 2.0):

```
ContinuantIndependentMaterial   (object, object aggregate, fiat part)
ContinuantIndependentImmaterial (site, spatial region, boundary)
ContinuantQuality
ContinuantRealizable            (role, disposition, function)
ContinuantGenericallyDependent
OccurrentProcess
OccurrentTemporal               (temporal/spatiotemporal region, process boundary)
```

How to assign: a dedicated single-purpose LLM call (or a small classifier) per canonical entity — *not* combined with relation extraction. Cache by CURIE so each grounded entity is typed once. If the entity is grounded to an OBO term, you can often read the BFO category directly from the ontology's upper-level alignment instead of asking the LLM at all (preferred when available).

### 4.2 Step 7 — Type-driven predicate menu

Encode RO/BFO domain–range constraints as a compatibility matrix. For an ordered pair `(subjectCategory, objectCategory)`, return only the predicates that are *type-legal*. This shrinks the menu before the LLM ever chooses, so it physically cannot pick most wrong answers.

```python
# (subject_category, object_category) -> allowed predicates
PREDICATE_MATRIX = {
  ("OccurrentProcess", "OccurrentProcess"):
        {"BFO:part_of", "RO:preceded_by"},
  ("OccurrentProcess", "ContinuantIndependentMaterial"):
        {"RO:occurs_in", "RO:has_participant"},
  ("ContinuantIndependentMaterial", "ContinuantIndependentMaterial"):
        {"BFO:part_of", "RO:located_in", "RO:derives_from"},
  ("ContinuantQuality", "ContinuantIndependentMaterial"):
        {"RO:inheres_in"},
  ("ContinuantRealizable", "ContinuantIndependentMaterial"):
        {"RO:inheres_in"},
  # ...
}

def candidate_predicates(subj_cat, obj_cat):
    return PREDICATE_MATRIX.get((subj_cat, obj_cat), set())
```

Critically, `subclass_of` is **not in `PREDICATE_MATRIX`** — subsumption never travels through the object-property channel. The LLM may still *propose* subclass_of, but only via the separate `candidate_subclass_of` evidence channel that feeds FCA (§2A.2, §2A.5a), where the lattice adjudicates it. Keeping subsumption out of the relation menu is what stops the model from emitting `subclass_of` as if it were an object property (and vice versa).

Ground the predicates too (the SPIRES discipline applied to relations): each predicate carries its CURIE (`RO:0000050`) + its textual definition. Predicate "prefix validation" = the chosen predicate must be in the allowed RO/BFO subset, exactly mirroring entity prefix validation.

### 4.3 Step 8 — Decomposed decision (subsumption-guard + object-property pick)

With FCA adjudicating `subclass_of`, Stage 1 is no longer "pick subclass_of or part_of" — it is a **router** that catches relations which are actually subsumption in disguise and **redirects them into the `candidate_subclass_of` evidence channel** (§2A.2) rather than encoding them as object properties.

**Stage 1 — Subsumption router.** A focused call answering only: *"Is this proposed relation actually a kind-of statement?"* Force the discriminating test:

- If *every* X is a kind of Y (same BFO category, X substitutes for Y) → **remove it from the relations channel and emit it as a `candidate_subclass_of` attribute** (a T2 soft attribute, §2A.5a) for FCA to adjudicate. Do not emit it as an object property.
- Otherwise it is a genuine object property → go to Stage 2.

**Stage 2 — Which object property?** Only runs if Stage 1 says it is a genuine relation. The candidate set is *already* restricted by `candidate_predicates(subj_cat, obj_cat)`, so this call picks from a short, type-legal menu with definitions attached, and returns `{predicate, confidence, justification}`.

Include 3–5 hard-negative few-shot examples chosen specifically around the failure mode, e.g.:
- `mitochondrion part_of cell` (relation) vs `mitochondrion subclass_of organelle` (subsumption → deferred to FCA)
- genitive/locative traps: "X in Y", "Y's X" → usually `part_of`/`located_in`, not subsumption.
- `part_of` vs `located_in` between two material entities (the residual hard case the type matrix can't split).

### 4.3a Adapting "ontology-prompting" — definition-grounded, label-anonymized predicates

Borrowed from the LLM ontology-prompting line of work (Lawrence; Ontogenia / CQbyCQ). The transferable insight: an LLM conforming to an ontology keys off the **textual definitions**, not the relation's label string — anonymizing the IRIs and supplying descriptions preserves quality. This is directly useful because your `part_of` over-prediction is partly **label-frequency bias**: "part of" is a salient, common token the model reaches for. Two concrete adaptations to step 8 (do **not** adopt the "whole ontology in one prompt" framing — your grounding layer scales better):

**(a) Definition-grounded predicate menu.** Every candidate predicate is presented with its RO/BFO definition plus one positive and one hard-negative example, not just its name:

```
Choose the single relation between SUBJECT and OBJECT.

P_a — definition: "a is part of b: a is a continuant that is a
      proper or improper part of continuant b at all times a exists."
      example: mitochondrion → cell.   NOT: organelle → cell (that is kind-of).
P_b — definition: "a is located in b: a is an independent continuant
      whose location is b, without being part of b."
      example: bacterium → gut lumen.
...
Answer with the label and the phrase from its definition that justifies it.
```

**(b) Anonymized-label debiasing (the high-value trick for your problem).** Replace the human predicate names with opaque tokens (`P_a`, `P_b`, …) in the prompt, keeping only the definitions and examples. This forces the choice on *meaning* and removes the model's tendency to grab the familiar string "part of." Map the chosen token back to its CURIE after the call.

This is cheap to A/B test: run step 8 with named predicates vs. anonymized+definition predicates against the Phase-0 gold set and compare the part_of/located_in (and any residual subsumption-leak) confusion rates. Keep whichever wins; in the ontology-prompting literature the definition-grounded variant generally wins.

**(c) Competency questions (optional, scoping).** Borrow the CQbyCQ idea only as a *scoping/validation* aid: maintain a list of competency questions the ontology must answer, and use them to decide which relations are in-scope and to sanity-check coverage — not as the extraction mechanism itself.

### 4.4 Step 9 — Verification pass

Cheap ensemble to catch residual errors:

- **Adversarial critique:** a second call framed as a skeptic — *"This triple claims `part_of`. Could it instead be `located_in`, or is it actually a kind-of statement that belongs to the taxonomy?"* Flip/defer when it argues convincingly.
- **Self-consistency vote:** sample Stage 1+2 N=3 times at moderate temperature; take majority. Disagreement → low confidence → human-review queue.
- **Confidence routing:** anything below a confidence threshold or flagged `ambiguous` does not auto-insert; it lands in a review queue with the model's justification attached.

---

## 5. Changes to existing components

### 5.1 Step 1 — extraction output (CHANGE)

FCA *adjudicates* subsumption (§2A), but the LLM still contributes subclass_of as **evidence** on a separate channel. The output therefore has three parts: entities, object-property relations, and `candidate_subclass_of` (which never becomes a final edge directly — it enters the FCA formal context as a T2 soft attribute, §2A.5a).

```python
class Relation(BaseModel):        # object properties only — never subsumption
    subject: str
    predicate: str                # validated against RO/BFO subset (no subClassOf)
    object: str

class CandidateSubClassOf(BaseModel):    # LLM taxonomic EVIDENCE, not a final edge
    child: str                    # entity
    parent: str                   # proposed superclass (grounded class)
    confidence: float = 1.0       # feeds the T2 gate in §2A.5a

class Extraction(BaseModel):
    entities: list[GroundedEntity]
    relations: list[Relation]
    candidate_subclass_of: list[CandidateSubClassOf]   # → routed into FCA attributes (§2A.2)
```

Each `CandidateSubClassOf(child, parent)` is converted to an `subclass-of-<parent>` attribute on the child's row in the FCA formal context. It is **not** emitted as OWL `subClassOf` directly — the lattice decides whether an edge results, and the T2 gate (§2A.5a) decides whether that edge is accepted or sent to review. Keep `subClassOf` out of the `relations` predicate set so subsumption can only travel through this evidence channel, never the object-property channel. Update the extraction prompt to ask for *kind-of statements* and *relationships* as two clearly separate lists (the §4.3a definition-grounded framing applies to the relation list).

### 5.2 Step 11 — reasoning (CHANGE, small)

You already run a reasoner. Add two checks that specifically catch this failure mode:

- **BFO disjointness axioms:** assert the BFO top-level categories are pairwise disjoint. Then any `subclass_of` (now produced only by FCA) that crosses categories becomes an inconsistency the reasoner flags automatically — a direct QA check on the lattice.
- **`subclass_of` cycle detection:** a subsumption cycle (A ⊑ B ⊑ A) almost always signals a `part_of` that leaked into the taxonomy. Detect and route to review.

The reasoner won't catch "wrong but consistent" labels — those are the verification pass's job (step 9) — but it cheaply catches the category-violating subset.

---

## 6. Phased rollout

**Phase 0 — instrumentation (do first).** Build a labeled gold set of ~150–300 triples from your own corpus, hand-annotated for correct predicate (esp. subclass_of vs part_of vs located_in). Without this you can't tell whether any change helped. Record current precision/recall per predicate as the baseline.

**Phase 1 — FCA adjudicates subclass_of, LLM feeds evidence (highest ROI, lowest effort).** Implement §2A + §5.1: move `subclass_of` out of the object-property channel into the `candidate_subclass_of` evidence channel; route LLM subclass_of, predefined-table superclasses, and intrinsic properties into one formal context as **tiered-trust attributes** (§2A.5a); derive subsumption from the lattice (§2A.3) and add the lattice→OWL materialization with the T2 gate. This is the change that most directly kills your subclass_of/part_of confusion while keeping the LLM's taxonomic recall, and you already run FCA. Re-measure. *(Tuning knob: start with a strict T2 threshold for precision, then relax for recall.)*

**Phase 2 — BFO typing + predicate menu (steps 6–7).** Add category assignment and the type matrix; also use it to gate FCA lattice edges (§2A.4, §2A.5a). This makes most wrong object properties impossible. Re-measure.

**Phase 3 — subsumption router + object-property classification + verification (steps 8–9).** Add the Stage-1 router (redirect disguised subsumption into the `candidate_subclass_of` channel), Stage-2 object-property disambiguation with the definition-grounded/anonymized prompting (§4.3a), and the verification pass. Re-measure, including the named-vs-anonymized A/B test.

**Phase 4 — grounding + prefix validation (steps 4–5).** Add OAK grounding and prefix gating. Lower urgency for your relation problem, but it upgrades entity quality and gives predicate grounding for free. Re-measure entity grounding accuracy separately.

**Phase 5 — reasoning hardening (5.2).** Add BFO disjointness + cycle detection.

Order matters: Phases 1–3 target your actual bottleneck and should come before the grounding work, even though grounding is the "SPIRES" part you asked to add.

---

## 7. Evaluation

- **Relation metric:** per-predicate precision/recall on the Phase-0 gold set, with a dedicated confusion matrix for `subclass_of` vs `part_of` vs `located_in` (your primary KPI).
- **Prompting A/B:** named predicates vs. definition-grounded + anonymized-label predicates (§4.3a) on the same gold set.
- **Grounding metric:** % of entities grounded, % prefix-valid, manual audit of a sample for correct CURIE (mirror SPIRES §2.1).
- **End-to-end:** run the reasoner; count inconsistencies and subclass_of cycles before vs after.
- **Review-queue rate:** fraction auto-inserted vs flagged — track that confidence routing isn't dumping everything to humans.

---

## 8. What you are deliberately NOT taking from SPIRES / ontology-prompting

- SPIRES's prompt-generation/templating machinery — you already have Pydantic-constrained extraction.
- SPIRES's recursive nested-extraction loop — adopt only if your entities have real sub-structure (e.g. quantity → {value, unit}); otherwise skip.
- SPIRES/OntoGPT as a framework wrapper — you're borrowing two ideas (OAK grounding + prefix validation), not restructuring around it.
- Ontology-prompting's **"whole ontology in one prompt"** framing — it does not scale, has no grounding/merge/reasoner, and you already beat it on consistency. You take only its *definition-grounded, label-anonymized* prompting insight (§4.3a).

The net: most of the new value is in FCA-owns-subsumption (§2A) + the relation layer (§4) + the definition/anonymized prompting trick (§4.3a) — none of which SPIRES or naive ontology-prompting gives you. The grounding/prefix borrow (§3) is a clean but secondary add.

---

## 9. Appendix — alternatives and build-vs-borrow

The framing that matters: **no single framework fits this pipeline wholesale**, because it is already more specialized (BFO-anchored, FCA-based, OWL-reasoned) than any off-the-shelf tool targets. SPIRES/OntoGPT itself is only worth two components (§3). The question is therefore *best-of-breed per component*, not *which framework to adopt*. Three options stand out.

### 9.1 DeepOnto (KRR-Oxford) — best-fit drop-in for grounding + taxonomy-gap completion

Maintained, pip-installable (`pip install deeponto`), industrial adoption (Samsung Research UK, Madrid Digital). Two relevant modules:

- **BERTMap** — BERT-based ontology *alignment*. Maps your entities/classes onto reference ontologies; better than ad-hoc OAK lexical grounding for class-level alignment. Works unsupervised or **semi-supervised — it can take your predefined subclass table as seed mappings**. Data augmentation from external ontologies helps when concept labels are sparse.
- **BERTSubs** — predicts *missing subsumptions* for ontology completion (and across ontologies for alignment). This **directly addresses the FCA attribute-gap problem (§2A.5)**: where sparse attributes leave holes in the lattice, BERTSubs proposes the missing `subclass_of` edges, which you then validate against BFO categories (§2A.4) and the reasoner (§5.2).

Fit: this is the best-fit *drop-in* for the two things SPIRES doesn't really cover — grounding/alignment and subsumption completion — while staying in OWL.
Trade-off: BERT-based, so you supply/fine-tune embeddings rather than zero-shotting an LLM. Given you already run SapBERT, this is familiar.
Where it slots in: alongside/instead of §3 grounding, and as a gap-filler feeding §2A.3.
Pilot first: **run BERTSubs against the Phase-0 gold set** — lowest-effort, highest-relevance test.

### 9.2 Relational Concept Analysis (RCA) — best-fit research direction, extends your FCA

RCA extends FCA to handle *links between objects*, not just object×attribute tables. It iterates over interconnected lattices and produces structures mapping onto description-logic concepts **and roles** — i.e. it can formalize *relations* (part_of, located_in) in the same lattice machinery that currently gives you only taxonomy.

Fit: the most natural upgrade *because it builds on your existing FCA investment* rather than bolting on an LLM; in principle it can handle `part_of` structurally instead of asking the LLM at all, unifying §2A and §4 under one formalism.
Trade-off: tooling is research-grade and sparse vs. DeepOnto — expect to implement more yourself. An elegant direction, not a turnkey library. (Graph-FCA is a related multi-relational extension worth a look if RCA's iterative scaling is awkward for your data.)
Where it slots in: a longer-term replacement/augmentation of the §2A FCA layer that also absorbs part of §4.

### 9.3 LLMs4OL (2025 challenge) — the right map, not a tool

Its four tasks mirror this pipeline almost exactly: Text2Onto, **Term Typing** (= BFO typing, step 6), **Taxonomy Discovery** (= FCA/subsumption), and **Non-Taxonomic Relation Extraction** (= the §4 relation layer). Use it to mine methods and as a benchmark to evaluate against — it is a shared task, not an installable framework.

### 9.4 Considered and set aside

- **REBEL / DeepKE** (trained relation-extraction models): don't speak BFO/RO or your custom schema; no grounding into your ontologies. Not a fit.
- **Neo4j LLM KG Builder / Microsoft GraphRAG / iText2KG**: build property-graph KGs, not OWL ontologies with reasoning. Below your rigor bar.
- **OntoKG, Ontogenia / CQbyCQ**: useful *ideas* (already harvested in §4.3a), not better frameworks for your stack.

### 9.6 Scale note

At 10k+ entities and 10k+ attributes, RCA (§9.2) likely becomes intractable (relational scaling explodes the attribute space). Prefer **DeepOnto BERTSubs** for subsumption completion at this scale — pairwise scoring over a *blocked* candidate set scales far better than full RCA fixpoint iteration. See §10.

### 9.5 Recommendation

Keep your bespoke pipeline. Borrow at the component level, in this order:
1. **DeepOnto BERTSubs** — pilot against the gold set to fill FCA taxonomy gaps (§2A.5). Highest near-term payoff.
2. **DeepOnto BERTMap** — for entity/class grounding seeded by your predefined table, as an alternative or complement to OAK (§3).
3. **RCA** — evaluate as a medium-term direction to fold relations into your FCA formalism.
4. **LLMs4OL tasks** — adopt as your evaluation scaffold.

---

## 10. Scale — 10k+ entities, 10k+ attributes

This scale invalidates several naive implementations above. Each affected component and its required adaptation:

### 10.1 FCA can explode — but density saves you (§2A)

A formal context yields up to $2^{\min(|G|,|M|)}$ concepts; at $10\text{k}\times10\text{k}$ the naive lattice is unbounded. In practice concept count tracks **density**, not size, and real entity×attribute tables are sparse (each entity has a few of the 10k attributes). Required steps, in order:

1. **Measure the fill ratio first.** This determines whether anything below is even needed.
2. **Clarify + reduce the context** (lossless): remove duplicate columns and attributes implied by others before building the lattice. Often shrinks $|M|$ substantially.
3. **Iceberg / frequent-concept lattice:** keep only concepts whose extent support ≥ a minimum threshold. Discards the long tail of rare concepts (which you don't want as classes anyway).
4. **Use a scalable algorithm** (In-Close4/5, FCbO), not a textbook AddIntent.
5. **Partition, don't globalize:** run FCA *per BFO category* (step 6) or *per predefined-backbone subtree*, not one global lattice. The backbone (§2A.5) carries the skeleton; FCA only refines locally. This is the single biggest tractability win.

### 10.2 Relation layer must NOT be O(n²) (§4)

10k entities ⇒ ~50M unordered pairs. An LLM call per pair is impossible. **Candidate-pair blocking is mandatory** — only classify pairs that are:

- proposed by the extraction step (the LLM already linked them), or
- co-occurring in the same sentence/passage, or
- embedding-near via SapBERT (top-k nearest neighbors per entity).

This caps relation-classification calls at ~thousands. Apply the same blocking to DeepOnto BERTSubs candidate subsumptions — never score all $10\text{k}^2$ pairs.

### 10.3 RCA → downgrade to BERTSubs (§9.2)

Full RCA fixpoint iteration is likely intractable here (attribute blow-up). If used at all: restrict scaling operators to $\exists$ only, apply support thresholds, cap at 1–2 iterations. Otherwise prefer DeepOnto BERTSubs for subsumption completion.

### 10.4 Attribute exploration doesn't scale (§2A.5)

Full attribute exploration over 10k attributes is exponential in the number of implication questions, LLM-assisted or not. Restrict it to **small, uncertain sub-contexts** (a single BFO branch where the lattice looks wrong), or replace it entirely with embedding-based imputation. Never run it globally.

### 10.5 Extraction feedback loop breaks the context window (§5.1)

Feeding *all* already-extracted entities back into the prompt is fine at hundreds but impossible at 10k+ (names alone ≈ 100k+ tokens, before attributes). Switch to **retrieval-conditioned extraction**: inject only the top-k *relevant* prior entities (SapBERT-retrieved) into each extraction prompt, not the whole set. This also improves extraction quality by reducing distractor context.

### 10.6 Cost/throughput hygiene

- **Cache by CURIE:** BFO typing (step 6), grounding (step 4), and predicate menus (step 7) are computed once per *canonical grounded entity*, not per mention.
- **Batch** LLM calls (typing, relation classification) rather than one request each.
- **Persist** the grounding lexicon and BFO-type assignments across runs so re-processing the corpus is incremental, not from scratch.
```