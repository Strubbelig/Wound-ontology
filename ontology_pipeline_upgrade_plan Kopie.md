# Ontology-Extraction Pipeline — Upgrade Plan

Goal: add (A) SPIRES-style **entity grounding + prefix validation** and (B) a **relation-classification layer** that fixes the `is_a` vs `part_of` confusion, without disturbing the parts you already have (LLM/Pydantic extraction, SapBERT evaluation with block/whitelist, SapBERT cluster+merge, OWL transform, OWL reasoning).

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

- **Your `predicate` slot mixes two ontologically different things.** `is_a` is subsumption (`rdfs:subClassOf`), a logical relation between classes. `part_of` is an object property (`RO:0000050`). Putting both in one slot tells the model they are interchangeable choices — a direct contributor to the confusion. The fix is structural, not a better prompt.
- **You already have an FCA layer — so you already have a formal source of subsumption.** A concept lattice's order relation *is* `is_a`: a formal concept below another is a more specific subconcept. This means you do not need the LLM to produce `is_a` at all. Let FCA own the taxonomy and forbid the LLM from emitting subsumption. This is the single biggest lever on your is_a/part_of problem, and it's a layer you already run. (See §4A.)
- **SapBERT already does fuzzy entity normalization**, but it does not assign authoritative cross-ontology persistent IDs (CURIEs) with validated prefixes. That is precisely the gap SPIRES grounding fills, and it slots in cleanly *after* your merge step.

---

## 2. Target pipeline

New/changed steps marked **[NEW]** / **[CHANGE]**.

```
(1) LLM extraction → Pydantic JSON
       [CHANGE] LLM emits ONLY object-property relations + entities.
                It no longer emits is_a at all.
         - entities[]
         - relations[]      (object properties only — BFO/RO subset, NO is_a)
(1b) FCA layer (you have it) → concept lattice
       [CHANGE] treat the lattice order as the AUTHORITATIVE is_a hierarchy
         - subsumptions[] are READ OFF the lattice, not asked of the LLM
(2) SapBERT entity evaluation (unchanged)
(3) SapBERT clustering + merge (unchanged) → canonical entities
(4) [NEW] Entity grounding         — canonical entity → CURIE candidates (OAK/annotators + SapBERT)
(5) [NEW] Prefix validation        — gate CURIEs against an allowed prefix registry
(6) [NEW] BFO category typing      — assign each canonical entity a BFO top-level category
(7) [NEW] Predicate grounding+menu — per entity pair, type-filter the allowed predicate set
(8) [NEW] Relation classification  — decomposed object-property decision (part_of vs located_in, etc.)
(9) [NEW] Verification pass         — adversarial critique / majority vote; flag low-confidence
(10) OWL transformation (unchanged, but consumes FCA-derived is_a + LLM relations separately)
(11) OWL reasoning (unchanged + [CHANGE] add BFO disjointness & is_a-cycle checks)
```

Step 1b = FCA owns subsumption (your existing layer, repurposed). Steps 4–5 = the SPIRES borrow. Steps 6–9 = the relation layer (the part that actually moves your metric). Steps 10–11 are mostly reused.

Note how the is_a/part_of confusion is now split across two *different mechanisms*: subsumption is computed deterministically by FCA; object properties are extracted by the LLM. The model is never asked to choose between is_a and part_of in the same slot, because it can no longer emit is_a.

---

## 2A. Component 0 — FCA as the authoritative `is_a` source (step 1b)

You already run FCA after extraction, so the highest-leverage change costs you almost nothing: **stop asking the LLM for `is_a` and read subsumption off the concept lattice instead.**

### 2A.1 Why this works

In FCA a formal concept is a pair `(extent, intent)` — a set of objects and the set of attributes they all share. The lattice order is, by construction, subsumption: if concept `C1` sits below `C2`, then `C1`'s extent ⊆ `C2`'s extent and `C1`'s intent ⊇ `C2`'s intent — i.e. `C1 is_a C2`. This is a *deterministic, formally grounded* taxonomy derived from shared attributes, not an LLM guess. An LLM confusing is_a with part_of cannot happen here, because the LLM is not in the loop for subsumption at all.

### 2A.2 What to feed FCA as "attributes"

The lattice is only as good as the attribute set. Decide explicitly what counts as a formal attribute:

- **Good attributes for taxonomy:** intrinsic, defining properties (qualities, dispositions, has-part signatures, BFO category). These produce clean genus–differentia subsumption.
- **Keep OUT of the FCA context:** the object-property *relations* the LLM extracts (part_of, located_in, …). Mixing partonomic relations into the FCA attribute set corrupts the lattice — that is the formal echo of the same is_a/part_of conflation, just moved upstream. Object properties belong to the LLM relation channel (steps 6–9), not the FCA context.
- A pragmatic split: FCA attributes = unary predicates / qualities / `has_part` signatures; LLM relations = binary object properties between named entities.

### 2A.3 Lattice → ontology classes (the hard part)

FCA produces many formal concepts, including intensional/intermediate ones with no named label. To turn the lattice into OWL subsumption:

1. **Map named entities to their concept(s)** in the lattice (object → its object-concept).
2. **Materialize edges**: for each covering edge `C1 ≺ C2` in the lattice, emit `subClassOf(C1, C2)`.
3. **Handle unnamed intermediate concepts**: either (a) keep them as anonymous OWL class expressions defined by their intent, or (b) prune them and transitively connect their named neighbors, depending on whether you want the intermediate abstractions in the final ontology. Make this a configurable policy.
4. **Reconcile with grounded CURIEs**: if two formal concepts ground (step 4) to the same ontology term, merge them; if a lattice edge contradicts the reference ontology's own subsumption (e.g. lattice says A ⊑ B but CL says B ⊑ A), flag for review — these contradictions are valuable QA signal.

### 2A.4 Cross-check FCA against BFO categories

Once BFO typing (step 6) exists, assert that a lattice subsumption edge is only valid when child and parent share a BFO category. An FCA edge that crosses categories (a process coming out as a subclass of a material entity) signals a bad attribute in the context — surface it rather than emitting it. This is the same disjointness check used in reasoning (§5.2), applied earlier to lattice edges.

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

Critically, `is_a` is **handled separately** (see 4.3): subsumption is legal only when `subjectCategory == objectCategory`. By keeping it out of `PREDICATE_MATRIX`, you stop the model from ever picking `is_a` where an object property belongs and vice versa.

Ground the predicates too (the SPIRES discipline applied to relations): each predicate carries its CURIE (`RO:0000050`) + its textual definition. Predicate "prefix validation" = the chosen predicate must be in the allowed RO/BFO subset, exactly mirroring entity prefix validation.

### 4.3 Step 8 — Decomposed decision (subsumption-guard + object-property pick)

With FCA owning `is_a`, Stage 1 is no longer "pick is_a or part_of" — it is a **guard** that catches relations the LLM emitted which are actually subsumption in disguise, and *defers them to FCA* rather than encoding them as object properties.

**Stage 1 — Subsumption guard.** A focused call answering only: *"Is this proposed relation actually a kind-of statement that should be a subsumption?"* Force the discriminating test:

- If *every* X is a kind of Y (same BFO category, X substitutes for Y) → **drop the relation** and let it be handled by the FCA lattice / flag it as a missing lattice edge for review. Do not emit it as an object property.
- Otherwise it is a genuine object property → go to Stage 2.

Prompt scaffold (require the model to fill the blanks and state the verdict before labeling):

```
Entity X = "{x}"  (BFO: {x_cat})
Entity Y = "{y}"  (BFO: {y_cat})

Test 1 (kind-of):   "Every {x} is a kind of {y}."   true / false
Test 2 (part-of):   "A {x} is a part or component of a {y},
                     and a {x} is NOT a kind of {y}."  true / false
If categories differ, is_a is impossible.
Verdict: SUBSUMPTION | RELATION | NONE
Justify in one sentence.
```

**Stage 2 — Which object property?** Only runs if Stage 1 says RELATION. The candidate set is *already* restricted by `candidate_predicates(subj_cat, obj_cat)`, so this call picks from a short, type-legal menu with definitions attached, and returns `{predicate, confidence, justification}`.

Include 3–5 hard-negative few-shot examples chosen specifically around the failure mode, e.g.:
- `thumb is_a finger` (subsumption) vs `thumb part_of hand` (relation)
- `mitochondrion part_of cell` (relation) vs `mitochondrion is_a organelle` (subsumption)
- genitive/locative traps: "X in Y", "Y's X" → usually `part_of`/`located_in`, not `is_a`.

### 4.4 Step 9 — Verification pass

Cheap ensemble to catch residual errors:

- **Adversarial critique:** a second call framed as a skeptic — *"This triple claims `part_of`. Apply the kind-of test. Should it be `is_a`?"* Flip when it argues convincingly.
- **Self-consistency vote:** sample Stage 1+2 N=3 times at moderate temperature; take majority. Disagreement → low confidence → human-review queue.
- **Confidence routing:** anything below a confidence threshold or flagged `ambiguous` does not auto-insert; it lands in a review queue with the model's justification attached.

---

## 5. Changes to existing components

### 5.1 Step 1 — extraction output (CHANGE)

Because FCA now owns subsumption (§2A), the LLM no longer emits `is_a` at all. Its output drops the predicate-as-taxonomy role and produces only entities and object-property relations.

```python
class Relation(BaseModel):        # object properties only — is_a is IMPOSSIBLE to express here
    subject: str
    predicate: str                # validated against RO/BFO subset (no subClassOf in the set)
    object: str

class Extraction(BaseModel):
    entities: list[GroundedEntity]
    relations: list[Relation]
    # subsumptions are NOT here — they come from the FCA lattice (§2A.3)
```

Subsumption (`Subsumption{child, parent}`) is produced by the FCA → OWL step (§2A.3), not by the LLM. Update the extraction prompt to remove any mention of "is a / kind of / subclass" and to ask only for relationships between distinct entities. Removing `subClassOf` from the allowed predicate set means a hallucinated `is_a` now fails predicate prefix-validation outright (§4.2) instead of silently entering the KB.

### 5.2 Step 11 — reasoning (CHANGE, small)

You already run a reasoner. Add two checks that specifically catch this failure mode:

- **BFO disjointness axioms:** assert the BFO top-level categories are pairwise disjoint. Then any `is_a` that crosses categories (e.g. a process asserted as a subclass of a material entity) becomes an inconsistency the reasoner flags automatically.
- **`is_a` cycle detection:** a subsumption cycle (A ⊑ B ⊑ A) almost always signals a `part_of` that was mislabeled `is_a`. Detect and route to review.

The reasoner won't catch "wrong but consistent" labels — those are the verification pass's job (step 9) — but it cheaply catches the category-violating subset.

---

## 6. Phased rollout

**Phase 0 — instrumentation (do first).** Build a labeled gold set of ~150–300 triples from your own corpus, hand-annotated for correct predicate (esp. is_a vs part_of). Without this you can't tell whether any change helped. Record current precision/recall per predicate as the baseline.

**Phase 1 — let FCA own is_a (highest ROI, lowest effort).** Implement §2A + §5.1: remove `is_a` from the LLM's allowed predicates, derive subsumption from the concept lattice (§2A.3), and add the lattice→OWL materialization. This is the change that most directly kills your is_a/part_of confusion, and you already run FCA. Re-measure.

**Phase 2 — BFO typing + predicate menu (steps 6–7).** Add category assignment and the type matrix; also use it to validate FCA lattice edges (§2A.4). This makes most wrong object properties impossible. Re-measure.

**Phase 3 — subsumption guard + object-property classification + verification (steps 8–9).** Add the Stage-1 guard (defer disguised subsumption to FCA) and Stage-2 object-property disambiguation (e.g. part_of vs located_in between two material entities), plus the verification pass. Re-measure.

**Phase 4 — grounding + prefix validation (steps 4–5).** Add OAK grounding and prefix gating. Lower urgency for your relation problem, but it upgrades entity quality and gives predicate grounding for free. Re-measure entity grounding accuracy separately.

**Phase 5 — reasoning hardening (5.2).** Add BFO disjointness + cycle detection.

Order matters: Phases 1–3 target your actual bottleneck and should come before the grounding work, even though grounding is the "SPIRES" part you asked to add.

---

## 7. Evaluation

- **Relation metric:** per-predicate precision/recall on the Phase-0 gold set, with a dedicated confusion matrix for `is_a` vs `part_of` (your primary KPI).
- **Grounding metric:** % of entities grounded, % prefix-valid, manual audit of a sample for correct CURIE (mirror SPIRES §2.1).
- **End-to-end:** run the reasoner; count inconsistencies and is_a cycles before vs after.
- **Review-queue rate:** fraction auto-inserted vs flagged — track that confidence routing isn't dumping everything to humans.

---

## 8. What you are deliberately NOT taking from SPIRES

- Its prompt-generation/templating machinery — you already have Pydantic-constrained extraction.
- Its recursive nested-extraction loop — adopt only if your entities have real sub-structure (e.g. quantity → {value, unit}); otherwise skip.
- SPIRES as a framework wrapper — you're borrowing two ideas (OAK grounding + prefix validation), not restructuring around OntoGPT.

The net: ~80% of the new value is in Components B (relation layer) + the structural split, which SPIRES does **not** give you; ~20% is the grounding/prefix borrow, which it does.
```