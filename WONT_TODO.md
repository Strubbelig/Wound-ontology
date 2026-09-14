# Curated-ontology change list

Changes that must be made **by hand**, because the pipeline is never allowed to
write to a curated file (INSTRUCTIONS, standing rule). Two files are involved:

| file | path | note |
|---|---|---|
| **WONT** | `data/ground truth/ground_truth_final.owl` | Turtle, despite the `.owl` extension — parse with `parse_graph`, not the XML reader |
| **MILD** | `../Disease ontologies/Disease proposal 2.ttl` | imported by WONT via `owl:imports` |

**After any edit below, re-run the reasoner gate.** Every figure is measured
against the files as of the date given on it.

> **Status 2026-09-12.** Moritz applied A, most of E and part of F by hand in
> Protégé (both files re-serialised; MILD only relabels MILD_120008 and rewrites
> four disjointness axioms). Reviewed the same day: IRIs renumbered from
> `WOND_1200xx` to `WONT_0000475`–`WONT_0000510` with `extend.next_free_id`,
> definitions written for every new class, the labels below adjusted, the
> direct `owl:imports pato.owl` removed and the modules regenerated (F2). ELK
> over the skeleton: 0 unsatisfiable. Competency score 6 → **15 of 65**
> (measured on the full closure). What is still open is listed per section.

## G. Open after the 12 Sep review — the checklist to walk

*Written 2026-09-14. Everything below is measured against the files as
committed in `24fcefe` / `4517fe1` plus the review edits. Sections A–F below
keep the original reasoning; this is the residue, in one place. Tick, decide,
or strike each; nothing here is applied.*

### G1 — modelling decisions your edit left implicit

| # | what | where | my recommendation |
|---|---|---|---|
| G1.1 | **`Infected wound` (WONT_0000163) lost its `owl:equivalentClass`.** It was `Wound ⊓ participates_in some Wound infection process`; it is now a primitive subclass of the microbial-burden hub with two necessary conditions (`participates_in some 410`, `has_quality some infected`). Nothing can be *inferred* an infected wound any more. | WONT_0000163 | restore the equivalence — `≡ Wound ⊓ has_quality some infected` is the shape of its siblings, and keep `participates_in` as a necessary condition |
| G1.2 | **`infected` was minted as a determinate (WONT_0000480)**, against the note in E ("infection is participation in a process, not a quality"). Defensible — the clinical continuum sterile → contaminated → colonized → infected *is* one scale — but it is a decision, so record it in an `IAO_0000116` on 480 (there is a placeholder note there now). | WONT_0000480 | keep, and write the note |
| G1.3 | **`colonized` / `Colonized wound` (WONT_0000075) deleted**, so the continuum has a hole between contaminated and infected. | — | mint `colonized` under 478 and restore the class as `≡ Wound ⊓ has_quality some colonized` (next free id: WONT_0000511) |
| G1.4 | **`Wound co-located with impaired arterial inflow` (WONT_0000510) has no co-location axiom** — it is a bare subclass of `Wound`, so `Ischemic wound ≡ 510 ⊓ ischemic` says nothing about arteries. The venous twin `WONT_0000384` shows the shape; the natural target is `WONT_0000229 Peripheral arterial occlusive disease`. This also unblocks CQ033 once P3 lands. | WONT_0000510 | copy the 384 axiom with 229 as the co-located disorder |
| G1.5 | **`Wound dressing process` (WONT_120013) has a dangling definition**: "…has as specified output a wound covered by wound dressing", but that class (WONT_120014) was deleted and the `OBI_0000299` restriction with it. | WONT_120013 | either rewrite the definition to what the axioms now say, or restore 120014 |
| G1.6 | **Six wound-edge / wound-base determinables are asserted of `Wound` itself**: `degree of maceration` (434), `skin adherence` (451), `granulation` (452), `necrosis` (453), `fibrin coverage` (454), `epithelialization` (455) are defined as qualities *of a wound edge / wound base*, and `Wound ⊑ has_quality some <each>` now says every wound bears them directly. The bearer mismatch is exactly what the Chronic-wound bearer check in A guards against. | WONT_0000380 | remove the six; keep `size`, `closure`, `depth`, `degree of time after disease inception`, `degree of microbial burden` (those *are* wound qualities) |
| G1.7 | **`increased depth ⊑ increased size` in PATO**, so every `Deep wound` is inferred a `Large wound`. Probably not what you mean by "large". | WONT_0000507/508 | accept it, or define `Large wound` over `increased area` (**PATO_0002057**, a determinate of `area` PATO_0001323 — measured against full PATO; it is not in the module yet, so it would need the rebuild) instead of `increased size` |
| G1.8 | **Two burn-grade sets now overlap**: the Hildanus/Derganc individuals (499–503: Superficial, Superficial partial-thickness, Deep partial-thickness, Full-thickness, Partial-thickness) and the pre-existing `Burn classification grade I–IV` (WONT_0000052–56) describe the same grades. And 503 `Partial-thickness` is the *union* of 500 and 501 — an individual that is two other individuals. | WONT_0000052–56, 499–503 | merge: keep one set, make the other's labels alt terms; drop 503 or make it a class |
| G1.9 | **`Burn classification grade` (WONT_0000437) now has two subclasses** (492 Jackson zone, 495 Hildanus/Derganc grade) *and* four direct individuals (52–56) that belong to neither. | WONT_0000437 | once G1.8 is settled, retype 52–56 under 495 |
| G1.10 | **`degree of malignancy` / `benign` / `malignant` (489–491)**: `Malignant wound` now carries `has_quality some malignant` *inside* its equivalence, beside the causal-history conjunct. Redundant with the process reading, and `benign` has no class to define. Also record the PATO_0002097 near-miss (done in a `rdfs:comment` on 491). | WONT_0000182, 489–491 | either drop the `has_quality` conjunct or drop the causal-history one; not both |
| G1.11 | **A4 — the chronic branch is still empty.** `Chronic wound` has zero subclasses; the four YES rows in `data/review/chronic_decision_sheet.csv` (`Ulcus cruris venosum`, `Ulcus cruris mixtum`, `Ulcus hypertonicus Martorell`, `Arterial leg ulcer`) are not asserted. CQ001/002/006 wait on this. | WONT_0000442 | assert the four `rdfs:subClassOf wont:WONT_0000442`; decide the three CHECK rows |

### G2 — small things

| # | what |
|---|---|
| G2.1 | Definitions I wrote for the 36 new classes are first drafts in the house pattern — read them; the clinical thresholds (e.g. "confined to the epidermis" for first-degree) are mine, not sourced. |
| G2.2 | `Jackson burn wound zone classification` (493) carries a `dcterms:source` I added (Jackson 1953, Br J Surg) — verify. |
| G2.3 | `FMA_7163 Skin` is stubbed in WONT with no parent — one of the three remaining roots beside `entity`. Give it `rdfs:subClassOf ns1:BFO_0000040` or a UBERON path. |
| G2.4 | `unit` (UO_0000000) and `disease` (DOID_4) are the other two roots — F1's curator's call still stands. |
| G2.5 | CQ010 / CQ012 ask for `Large` / `Deep`; the ontology has PATO's `increased size` / `increased depth`. Fix in `config/competency_questions.json`, not WONT. |
| G2.6 | CQ011 `Full-thickness wound` / `full-thickness` and CQ110 `Healed wound` — you chose not to mint them (`Epithelialized wound` 506 stands in for the latter). Either add `Healed wound` as an alt term on 506 and rewrite CQ011, or mint. |
| G2.7 | `ontology_labels()` indexes `rdfs:label` only, so `2nd degree burn` (now an alt term on 483) dropped out of the naming guard's index. Pipeline-side; noted in ROADMAP. |

### Order of work

Sections are lettered in the order they were found, not the order to do them.
This is the order to do them, and it is the schedule in `ROADMAP.md`.

| do | section | what | roadmap |
|---|---|---|---|
| ~~1st~~ | **B** | **not needed** — measured 2026-09-12: all three parents are already asserted, inside `rdfs:subClassOf` intersections (`MILD_120023 ⊑ tendency ⊓ …`, `MILD_120008 ⊑ MILD_120023 ⊓ …`, `MILD_120049 ≡ MILD_120022 ⊓ …`). The 10 Sep scan only looked for *named* parents. | done |
| ~~2nd~~ | **A** | **applied 2026-09-12** (A1–A3; A4 still open) | P1 |
| ~~3rd~~ | **E** | **applied 2026-09-12** except `colonized`, `full-thickness`, `Healed wound`; two extra determinables minted (`degree of malignancy`, `acute`) | P1 |
| — | C | **withdrawn.** Do not apply the 38-axiom orphan patch | — |
| — | D | open modelling questions; D2 blocks a pipeline-side filter | P2 |
| ~~4th~~ | **F** | **F2 done 2026-09-12** (obi_module 16.3 MB → 1.0 MB; 29 foreign roots → 3). F1 is now only `unit` and `disease` — a curator's call | P1 |

---

## A. WONT — give `Chronic wound` its defining axiom

*Agreed 2026-09-10. Three edits.* **Applied 2026-09-12** with these
deviations from the text below: the determinable is `WONT_0000475 degree of
time after disease inception` (not "degree of healing progression"), its
determinates are `WONT_0000476 acute` and `WONT_0000477 chronic`, and `Wound`
carries `has_quality some` that determinable. The bearer in the definition is
"pathological disorder", so MILD can reuse the pair. **A4 is still open** —
`Chronic wound` still has zero subclasses; the four YES rows of
`data/review/chronic_decision_sheet.csv` are not asserted.

### Why

WONT_0000442 `Chronic wound` carries only a prose definition and a bare parent:

```turtle
wont:WONT_0000442 rdf:type owl:Class ;
                  rdfs:subClassOf wont:WONT_0000380 ;   # Wound
                  ns1:IAO_0000115 "A wound that has failed to progress through the phases of healing in an orderly and timely fashion."@en ;
                  skos:relatedMatch ns1:HP_0032676 ;
                  rdfs:label "Chronic wound"@en .
```

No `owl:equivalentClass`. The definition says "failed to progress" in English and
asserts nothing.

Ten sibling classes in WONT **already** carry a defining axiom of exactly the
shape this one needs — `X ≡ Parent ⊓ has_quality some <determinate>` — each with
a determinable/determinate pair behind it:

| defining axiom | determinable | determinate |
|---|---|---|
| `Epithelialized wound base` | degree of epithelialization | epithelialized |
| `Fibrin-covered wound base` | degree of fibrin coverage | fibrin-covered |
| `Granulating wound base` | degree of granulation | granulating |
| `Necrotic wound base` | degree of necrosis | necrotic |
| `Macerated wound edge` | degree of maceration | macerated |
| `Softened wound edge` | tissue firmness | softened |
| `Undermined wound edge` | degree of skin adherence to underlying tissue | undermined |
| `Reddened wound edge` | PATO_0000014 color | reddened |
| `Livid wound edge` | PATO_0000014 color | livid |
| `Painful …` | degree of wound pain | painful |

`Chronic wound` is the one member of that family without an axiom, **and the
determinate it needs does not exist**: there is no `chronic` quality class and no
chronicity determinable anywhere in WONT (checked against all 9 direct
`BFO_0000019` subclasses).

### A1 — decide the determinable's name

Two candidates. This is a curator's call, not a mechanical one:

- **`degree of healing progression`** *(recommended)* — names the underlying
  scale, so `acute` can join `chronic` as a sibling determinate later. WONT
  already has `Acute cutaneous wound` (HP_0032674) with nowhere to hang.
- `degree of chronicity` — parallels the `degree of maceration` → `macerated`
  naming most literally, but names the scale after one of its values, which
  leaves `acute` awkward.

### A2 — mint the pair

Next free ids: **WONT_0000475**, **WONT_0000476** (highest currently used in the
`0000xxx` band is WONT_0000474 `painful`; the `12xxxx` band runs to WONT_120084).

```turtle
###  https://bioportal.bioontology.org/ontologies/WONT/WONT_0000475
wont:WONT_0000475 rdf:type owl:Class ;
                  rdfs:subClassOf ns1:BFO_0000019 ;
                  ns1:IAO_0000115 "A quality of a wound that is the extent to which its healing proceeds through the phases of healing in an orderly and timely fashion."@en ;
                  rdfs:label "degree of healing progression"@en .


###  https://bioportal.bioontology.org/ontologies/WONT/WONT_0000476
wont:WONT_0000476 rdf:type owl:Class ;
                  rdfs:subClassOf wont:WONT_0000475 ;
                  ns1:IAO_0000115 "A degree of healing progression that qualifies its bearer as chronic."@en ;
                  rdfs:label "chronic"@en .
```

Copied structurally from WONT_0000434 / WONT_0000435 (`degree of maceration` /
`macerated`), including the definition wording pattern *"A <determinable> that
qualifies its bearer as <determinate>."*

**Minting rather than reusing PATO is deliberate.** PATO does have
`PATO_0001863 chronic`, but it is a *duration quality of a process* under
`PATO_0001309 duration` — its bearer is an occurrent, and `Wound` is a material
entity. Using it would put a process quality on a continuant. Record the
near-miss instead of repeating the check later; see **E**, "Check PATO before
minting anything", for the full measurement and the `skos:relatedMatch` line to
add here.

### A3 — add the equivalentClass axiom to WONT_0000442

Insert into the existing block (it already has the `rdfs:subClassOf`, which the
precedent classes also keep alongside the axiom):

```turtle
                  owl:equivalentClass [ owl:intersectionOf ( wont:WONT_0000380
                                                             [ rdf:type owl:Restriction ;
                                                               owl:onProperty ns1:RO_0000086 ;
                                                               owl:someValuesFrom wont:WONT_0000476
                                                             ]
                                                           ) ;
                                        rdf:type owl:Class
                                      ] ;
```

Byte-for-byte the `Macerated wound edge` pattern with the two IRIs swapped.

### A4 — populate the branch

*Added 2026-09-10, after the rule below was settled.*

**Only `Chronic wound` bears `chronic` directly.** It is the determinate that
defines that class; any other class that is chronic is chronic *by being a
subclass of it*, and inherits the quality through the A3 axiom. Asserting
`X has_quality some chronic` **and** `X subClassOf Chronic wound` is redundant —
with A3 in place the reasoner infers either from the other. The one to assert is
the subsumption.

Which matters, because **`Chronic wound` currently has zero subclasses.**
Measured: WONT_0000442 is a leaf. The whole chronic branch is empty, and 39
classes sit under `Wound` with none of them classified by course.

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

### Bearer check

The bearer is the **wound**, not the patient and not the healing process — which
is what `Wound ⊓ has_quality some chronic` says. Contrast WONT_0000473 `degree of
wound pain`, where the curator note records moving the bearer from the wound to
the patient because *"a wound does not feel"*. No such move applies here.

---

## B. MILD — three missing `subClassOf` axioms

*Found 2026-09-10. Each parent is already stated in the class's own definition;
only the axiom is missing.*

| class | IRI | its definition begins | missing axiom |
|---|---|---|---|
| disease predisposition | MILD_120023 | "**A tendency** inhering in a person, grounded in a material basis…" | `rdfs:subClassOf mild:MILD_120005` (tendency) |
| genetic predisposition | MILD_120008 | "**A disease predisposition** that has as material basis a pathogenic genetic variant." | `rdfs:subClassOf mild:MILD_120023` |
| compound pathological disorder | MILD_120049 | "**A pathological disorder** that has as part a pathological disorder." | `rdfs:subClassOf mild:MILD_120022` |

MILD's own model commitment 4 already spells the first one out: *"…the
predisposition layer — MILD_120023 disease predisposition, **a MILD_120005
tendency**, with the responsible abnormality attached by MILD_120094 has a
material basis…"*

**Do not touch the other parentless entries.** Of 73 classes in the file, 22 are
parentless: these 3, and 19 external import stubs (`BFO_`, `COB_`, `HP_`,
`IAO_`, `NCBITaxon_`, `OBI_`, `OGMS_`, `UO_`, `UPHENO_`), which are parentless
by design.

### Why this is a WONT problem too

WONT_0000449 `advanced age wound-healing predisposition` is
`rdfs:subClassOf mild:MILD_120023`. With MILD_120023 parentless, that chain stops
dead. It is the **only** one of the 10 MILD IRIs WONT references with no parent
at all: the other 9 each reach either a BFO class directly (`BFO_0000015`,
`BFO_0000040`) or an external stub the import closure grounds (`COB_0000082`,
`IAO_0000030`, `OBI_0001930`, `OGMS_0000045`).

---

## C. WITHDRAWN — do **not** apply the 38-axiom "orphan" patch

*Retracted 2026-09-10.*

An earlier analysis in this project reported "39 curated classification-grade
leaves with no parent" and produced a patch of 38 `rdfs:subClassOf` axioms
(`scratchpad/wont_orphan_patch.ttl`). **That finding was wrong. The patch must
not be applied.**

Measured: all 38 subjects are `owl:NamedIndividual`, not classes — and all 38
are **already** `rdf:type` the very class the patch proposed as their
`rdfs:subClassOf` parent. For example:

```turtle
wont:WONT_0000052 rdf:type owl:NamedIndividual ,
                          wont:WONT_0000437 ;          # Burn classification grade
                 rdfs:label "Burn classification grade I"@en .
```

The patch would have asserted `rdfs:subClassOf` on an individual — forcing
punning, and duplicating in a broken form a relation that is already present and
correct. WONT has **zero** WONT-owned parentless classes.

The detector was looking for `rdfs:subClassOf` on every subject and flagging
whatever lacked it. A `NamedIndividual` correctly has none.

The 38 break down as: 16 Wagner and Anderson grades, 5 Burn, 5 Gustilo and
Anderson, 4 Shea, 4 Tscherne and Oestern, 4 CDC surgical.

---

## D. Open — decide before editing

### D1. ~~The `chronic` column, 40 wound types~~ — settled

The question this sheet asked ("which wound types bear the quality chronic")
was the wrong one. Settled 2026-09-10: **only `Chronic wound` does.** The column
is therefore `TRUE` for 1 object and `FALSE` for the other 39, with no review
needed, and the sheet has been rewritten to ask the question that survives —
which classes belong *under* `Chronic wound`. See **A4**.

The FCA consequence, measured on the Wound subtree:

| context | undecided | certain concepts | withheld as candidate-only |
|---|---|---|---|
| as it stands | 39 | 2 | 9 |
| the column filled 39 x `FALSE` | 0 | **12** | 0 |
| the column deleted | 0 | 11 | 0 |

So filling it does beat deleting it — but only by 1 net concept, and not by
grouping anything. An attribute true of exactly one object can only produce
concepts whose extent is a subset of that one object: the two the filled column
adds are the singleton `{Chronic Wound}` and the bottom concept. What filling
actually buys is a decided store, a defensible axiom, and the 9 previously
withheld concepts becoming certain.

Representational limit worth keeping: the boolean matrix cannot distinguish
*"the determinate does not hold"* from *"only the determinable applies"*
(`Wound`, `Skin Wound`, `Traumatic Wound`). Both encode as `FALSE`. Correct for
FCA, lossy as a record.

### D2. Should the classification grades be individuals?

They are 38 `owl:NamedIndividual`s across 6 grade classes (see C). That is a
defensible choice — a grade is arguably an instance of a grading scheme — but it
has a consequence worth deciding deliberately: `Orchestrator.ontology_labels()`
collects **every** `rdfs:label` in the file with no filter on whether the subject
is a class or an individual, so all 38 grade labels are in use as SapBERT
mapping anchors as though they were classes. A store term matching one of them
maps onto an individual.

Decide the modelling question first; the pipeline-side filter follows from it,
and that half is not a WONT change.

---

## E. WONT — the determinate-quality block, fourteen more times

*Added 2026-09-10. The same pattern as **A**, applied to the rest of the family.
This is **P1** in `ROADMAP.md` and carries 16 competency questions.*

**Applied 2026-09-12, as follows** (ids are the renumbered ones):

| done | what |
|---|---|
| E1 | 5 PATO stubs in WONT; the logic now comes through `pato_module`/`obi_module` (F2), not a direct `owl:imports pato.owl` |
| E2 | `degree of microbial burden` (478) with `contaminated` 479, `infected` 480, `sterile` 486 — **`colonized` was not minted; `infected` was, against the advice above.** `degree of tissue perfusion` 487 / `ischemic` 488. `full-thickness` not minted. Extra: `degree of malignancy` 489 with `benign` 490 / `malignant` 491. |
| E3 | `Open wound` 504, `Closed wound` 505, `Large wound` 507, `Deep wound` 508, `Ischemic wound` 509 (≡ `Wound co-located with impaired arterial inflow` 510 ⊓ ischemic), `Epithelialized wound` 506 (in place of `Healed wound`; axiom on `epithelialized` added in review). No `Full-thickness wound`. |
| E4 | `Clean wound` ≡ Wound ⊓ sterile. `Contaminated wound` and `Infected wound` are *subclasses* of a new hub `WONT_0000481 Wound with recognized microbial burden` (≡ Wound ⊓ has_quality some (contaminated ∪ infected), disjoint with `Clean wound`); each carries `has_quality some <its determinate>` as a necessary condition only. **`Infected wound` lost its `owl:equivalentClass`** in the process — it is primitive now. `Colonized wound` (WONT_0000075) was deleted. |
| E5 | both alt terms on `Chronic wound` |

Still open from this section: CQ010/CQ012 (`Large`/`Deep` name the PATO
terms `increased size`/`increased depth` — a CQ-file fix), CQ011
(`full-thickness`), CQ110 (`Healed wound`), CQ033 (needs `Peripheral Artery
Disease` spelled as WONT has it, plus the co-location axiom on 510 — the venous
twin `WONT_0000384` shows the shape; the natural target is `WONT_0000229`).
Note PATO's own axiom `increased depth ⊑ increased size`: every `Deep wound`
is inferred a `Large wound`. Decide whether that is wanted.

### Why this is one job and not fourteen

Of the 65 in-scope CQs, **18 sit on a single shape**: a wound subclass defined
by the determinate quality that makes it that subclass.

| predicate | CQs | which |
|---|---|---|
| `has_quality` | 13 | CQ010–013, CQ040, CQ041, CQ090–093, CQ110–112 |
| `is_a … Chronic Wound` | 3 | CQ001, CQ002, CQ006 — these are **A4** |
| `co_located_with` | 1 | CQ033 — needs the class from here **and** `RelationType` (roadmap P3) |
| `is_treatment_for` | 1 | CQ050 — same |

### Check PATO before minting anything

Measured against the full `../Import ontologies/pato.owl` (259 922 triples).
**Four determinates already exist and must be reused, not minted:**

| need | PATO term | note |
|---|---|---|
| open | **PATO_0000610** `open` | determinate of PATO_0000136 `closure` |
| closed | **PATO_0000608** `closed` | same determinable — the pair is already modelled |
| large | **PATO_0000586** `increased size` | determinate of PATO_0000117 `size`, already stubbed in WONT |
| deep | **PATO_0001596** `increased depth` | determinate of PATO_0001595 `depth`, already stubbed in WONT |

`PATO_0000136 closure` comes with `open` and `closed` as its two determinates
already — exactly the structure this block needs, authored by someone else.

**And two PATO terms are false friends. Do not use either:**

- **PATO_0000956 `sterile`** is a **fertility** quality: *"inhering in a bearer
  by virtue of the bearer's being incapable of initiating, sustaining, or
  supporting reproduction"*, with children `male sterile` and `female sterile`.
  A clean wound is not infertile.
- **PATO_0001863 `chronic`** is a **duration quality of a process**: *"inhering
  in a bearer by virtue of the bearer's having slow progressive course of
  indefinite duration"*, under PATO_0001309 `duration`. Its bearer is an
  occurrent. `Wound` is a material entity (WONT_0000380 ⊑ MILD_120022), so
  `Wound ⊓ has_quality some PATO_0001863` puts a process quality on a
  continuant — the clash HermiT exists to find.

  **This confirms A2.** Mint the WONT `chronic` as planned, and record the
  near-miss the way WONT already records them, rather than leaving the next
  reader to rediscover it:

  ```turtle
  wont:WONT_0000476 skos:relatedMatch ns1:PATO_0001863 ;
                    rdfs:comment "PATO_0001863 chronic is a duration quality of a process; this one qualifies the wound itself. Bridged, not subsumed."@en .
  ```

- **PATO_0002097 `neoplastic, malignant`** is a **disposition** inhering in a
  tumour — see the CQ091 row below.

### Two classes are already defined, and better than the CQ asks

Checked before proposing anything: `Infected wound` and `Malignant wound`
already carry `owl:equivalentClass` axioms, and neither uses `has_quality`.

| class | existing axiom | the CQ asks for |
|---|---|---|
| **WONT_0000163** `Infected wound` | `Wound ⊓ RO_0000056 some WONT_0000410` (participates in a wound infection process) | CQ093 `has_quality Infected` |
| **WONT_0000182** `Malignant wound` | `Wound ⊓ OBI_0000312 some (MILD_120021 ⊓ RO_0000057 some WONT_0000465)` (output of a disorder development process with a malignancy participant) | CQ091 `has_quality Malignant` |

**The ontology is right and the questions are wrong.** Infection is
participation in a process, not a quality of the wound; malignancy is a
disposition of a tumour (PATO_0002097), reached through the wound's causal
history. Adding `has_quality` axioms to make these two pass would make the
ontology worse to make a number better.

**Decision needed (curator's call, not mechanical):** rewrite CQ091 and CQ093
in `config/competency_questions.json` to the triples the ontology actually
asserts. That is a change to the question file, not to WONT — but it must be a
deliberate, written-down decision, because rewriting a competency question to
match the artefact is otherwise how a CQ suite stops meaning anything.

### E1 — import the four PATO determinates

Add stubs in the existing PATO block, in the style WONT already uses for
PATO_0000117 and PATO_0001595 (label + `IAO_0000115`, no local parent):
**PATO_0000136** `closure`, **PATO_0000610** `open`, **PATO_0000608** `closed`,
**PATO_0000586** `increased size`, **PATO_0001596** `increased depth`.

### E2 — mint two determinables and five determinates

Next free ids after **A** (which takes WONT_0000475/0476): **WONT_0000477**
onward.

| id | label | parent | kind |
|---|---|---|---|
| WONT_0000477 | degree of microbial burden | `ns1:BFO_0000019` | determinable |
| WONT_0000478 | sterile | WONT_0000477 | determinate |
| WONT_0000479 | contaminated | WONT_0000477 | determinate |
| WONT_0000480 | colonized | WONT_0000477 | determinate |
| WONT_0000481 | degree of tissue perfusion | `ns1:BFO_0000019` | determinable |
| WONT_0000482 | ischemic | WONT_0000481 | determinate |
| WONT_0000483 | full-thickness | `ns1:PATO_0001595` (depth) | determinate |

`degree of microbial burden` is the clinical continuum — sterile →
contaminated → colonized — and giving it one determinable is what lets the
three be siblings rather than three unrelated qualities. **`infected` is
deliberately not a fourth**: see the table above.

Definitions follow the house pattern, *"A &lt;determinable&gt; that qualifies its
bearer as &lt;determinate&gt;."* On WONT_0000478 add:

```turtle
                  rdfs:comment "PATO_0000956 sterile is a fertility quality and is deliberately not used here."@en .
```

### E3 — mint seven wound classes

All `rdfs:subClassOf wont:WONT_0000380` (Wound), each with the defining axiom.

| id | label | ≡ Wound ⊓ `RO_0000086` some | CQ |
|---|---|---|---|
| WONT_0000484 | Large wound | `ns1:PATO_0000586` increased size | CQ010 |
| WONT_0000485 | Full-thickness wound | WONT_0000483 full-thickness | CQ011 |
| WONT_0000486 | Deep wound | `ns1:PATO_0001596` increased depth | CQ012 |
| WONT_0000487 | Open wound | `ns1:PATO_0000610` open | CQ013 |
| WONT_0000488 | Closed wound | `ns1:PATO_0000608` closed | CQ112 |
| WONT_0000489 | Ischemic wound | WONT_0000482 ischemic | CQ092, CQ033 |
| WONT_0000490 | Healed wound | WONT_0000463 epithelialized | CQ110 |

`Healed wound` needs **no new quality at all** — `epithelialized`
(WONT_0000463) and its determinable `degree of epithelialization`
(WONT_0000455) both already exist. It is one axiom.

`Ischemic wound` is also the class CQ033 needs before `co_located_with` can be
asked; compare the existing `Wound co-located with impaired venous backflow`,
which is the same shape on the venous side.

### E4 — three axioms on classes that already exist

These three have the class and lack the axiom, exactly like `Chronic wound` in
**A**:

| class | ≡ Wound ⊓ `RO_0000086` some | CQ |
|---|---|---|
| WONT_0000068 `Clean wound` | WONT_0000478 sterile | CQ041 |
| WONT_0000078 `Contaminated wound` | WONT_0000479 contaminated | CQ040 |
| WONT_0000075 `Colonized wound` | WONT_0000480 colonized | — |

`Colonized wound` has no CQ behind it. Do it anyway: leaving one member of a
three-way determinable undefined is how the next inconsistency gets in.

### E5 — two alt terms, not two classes

CQ090 asks about `Chronic Non-Healing Wound` and CQ111 about `Non-Healing
Wound`. Neither is a new class — both are `Chronic wound` under another name,
and `competency.label_index()` already indexes `IAO_0000118` alt terms. Two
lines on WONT_0000442:

```turtle
                  ns1:IAO_0000118 "Chronic non-healing wound"@en ,
                                  "Non-healing wound"@en ;
```

Minting them as classes instead would create two synonyms of `Chronic wound`
sitting beside it as siblings, which is worse than the missing class.

### Worked example — the shape every one of these takes

```turtle
###  https://bioportal.bioontology.org/ontologies/WONT/WONT_0000487
wont:WONT_0000487 rdf:type owl:Class ;
                  rdfs:subClassOf wont:WONT_0000380 ;
                  owl:equivalentClass [ owl:intersectionOf ( wont:WONT_0000380
                                                             [ rdf:type owl:Restriction ;
                                                               owl:onProperty ns1:RO_0000086 ;
                                                               owl:someValuesFrom ns1:PATO_0000610
                                                             ]
                                                           ) ;
                                        rdf:type owl:Class
                                      ] ;
                  ns1:IAO_0000115 "A wound that affords unobstructed passage into the underlying tissue."@en ;
                  rdfs:label "Open wound"@en .
```

### Totals

| | count |
|---|---|
| PATO stubs to import (E1) | 5 |
| WONT classes to mint (E2 + E3) | **14** — WONT_0000477 … WONT_0000490 |
| `equivalentClass` axioms (E3 + E4) | **10** |
| alt terms (E5) | 2 |
| CQs closed by this section | **11** (CQ010–013, CQ040, CQ041, CQ090, CQ092, CQ110, CQ111, CQ112) |
| CQs needing a **question** decision instead | 2 (CQ091, CQ093) |
| CQs unblocked here but still waiting on `RelationType` | 2 (CQ033, CQ050) |

Together with **A4** (CQ001, CQ002, CQ006) that is **16 of 65** moved by hand
curation, against a current score of 6.

### After applying

Run HermiT, not just ELK. Ten new `equivalentClass` axioms on one parent is
precisely where a bearer mistake shows up, and two of the determinates
(`open`/`closed`) come from a PATO branch WONT has never used before.

---

## F. The import closure — 32 roots beside `entity`

*Found 2026-09-11 from the Protégé tab-indented export of the full closure
(`tab indented hierarchy Mild and Wont.rtf`, 89 568 lines). This is the deeper
form of the parentless problem B was the tip of.*

`owl:Thing` has **33 direct children**. One is `entity (BFO:0000001)`, carrying
5 328 distinct classes and every WONT and MILD class. The other 32 are import
stubs with no parent anywhere in the closure, and between them they hold
**~700 classes disconnected from BFO**:

| root | classes under it | referenced by WONT/MILD | declared in |
|---|---|---|---|
| `disease (DOID:4)` | 135 | 19 stubs, all via `skos:relatedMatch` (8) + their own annotations | `obi_module.owl` |
| `unit (UO:0000000)` | 518 | 1 — `unit` itself, in a `someValuesFrom` | `obi_module.owl`, `uo_module.owl` |
| `symptom (SYMP:0000462)` | 38 | 0 | `obi_module.owl` |
| `processual entity (UBERON:0000000)` | 13 | 0 | `obi_module.owl` |
| 4 organisms — *S. aureus, Streptococcus, P. aeruginosa, E. coli* (NCBITaxon) | 4 | **4**, via `subClassOf`/`someValuesFrom` | `ncbitaxon_module.owl` |
| 24 leaf stubs — 6 OMIM, 2 SO, 2 CLM (no label), NBO, *prion*, 11 UO prefixes (giga…atto) | 24 | 0 | `obi_module.owl` |

**The curated layer is clean.** Measured: **zero** WONT or MILD classes have a
disconnected import as their only parent, and the DOID stubs are attached with
`skos:relatedMatch` — WONT's own comment on `WONT_0000470` says why: *"asserting
rdfs:subClassOf between them is a category error, so the relation is recorded
as skos:relatedMatch instead."* That commitment is already in force. The
problem is closure hygiene, not modelling.

Why it still matters: BioPortal will render 33 roots; the 54 pre-existing
unsatisfiable classes the skeleton docstring mentions live in this debris; and
the pipeline's "placed under a curated class" figure counts a landing on a DOID
or UO class as placed when it is not BFO-grounded.

### F1 — bridge the five that are actually used

Full `obi.owl` leaves these parentless too (checked), so the bridge has to be
MILD's own axiom, in MILD's import block:

```turtle
# organisms — COB_0000022 organism is in the closure and is a material entity
<http://purl.obolibrary.org/obo/NCBITaxon_1280> rdfs:subClassOf <http://purl.obolibrary.org/obo/COB_0000022> .
<http://purl.obolibrary.org/obo/NCBITaxon_1301> rdfs:subClassOf <http://purl.obolibrary.org/obo/COB_0000022> .
<http://purl.obolibrary.org/obo/NCBITaxon_287>  rdfs:subClassOf <http://purl.obolibrary.org/obo/COB_0000022> .
<http://purl.obolibrary.org/obo/NCBITaxon_562>  rdfs:subClassOf <http://purl.obolibrary.org/obo/COB_0000022> .
```

`unit (UO:0000000)` is a curator's call. `IAO_0000003 measurement unit label`
is in the closure and is where OBI-style modelling puts units (an information
content entity). Decide that, or leave `unit` outside BFO deliberately and say
so in a comment — either is defensible; silence is not.

### F2 — the debris — **done 2026-09-12**

Root cause, measured: STAR over a merge that contains full `pato.owl` runs
away (six upper sources alone 0.9 MB; with `pato.owl` added 15.2 MB; with
`uo.owl` added 1.4 MB — every one of the 518 units, because `unit` is seeded).
`build_disease_proposal.sh` (FIX 3) now BOT-extracts PATO on its own first
and merges that module into the joint STAR; `unit` is a label stub; DOID and
HP are MIREOT paths to `disease` / `Phenotypic abnormality`; the one UBERON
term (`mucosa`) is a MIREOT path to `material entity`; the two ChEBI roots are
seeded so the ChEBI leaf module stays grounded. The script refuses to run if
WONT or MILD imports a full release ontology, and if the joint module exceeds
3 MB. `go/chebi/dron` are not rebuilt unless `--leaf-modules` is passed.

| | before | after |
|---|---|---|
| `obi_module.owl` | 16.3 MB, 5 549 classes | 1.0 MB, 248 classes |
| closure (WONT + MILD + modules) | 220 252 triples, 6 169 classes | 34 071 triples, 1 174 classes |
| roots beside `entity` | 29 foreign | 3: `disease`, `unit`, `Skin` (FMA_7163, WONT's own stub) |
| schema rebuild | 33 s | 2.6 s |

The four organisms are grounded (`NCBITaxon_2 ⊑ OBI_0100026 organism ⊑
material entity` via `ncbitaxon_module` + `obi_module`), so **F1 reduces to
`unit` and `disease`** — and to `FMA_7163 Skin`, which WONT stubs without a
parent.

27 roots and ~690 classes that nothing in WONT or MILD references, all pulled
into `obi_module.owl` by the extraction signature. Two options:

- **Regenerate `obi_module.owl` with a tighter signature** (the module is 16 MB
  against 1.4 MB for the next largest — it is over-extracted). The DOID island
  should shrink to the 19 stubs WONT actually bridges to, and SYMP, UBERON, SO,
  MIM, CLM, NBO and the UO prefixes should vanish.
- Or leave it and **record it**: a `rdfs:comment` on the MILD ontology header
  naming the 32 foreign roots as unbridged by design.

The first is the real fix. Do it *after* E, so one HermiT run covers both.

### F3 — after either

Nothing to run by hand any more. The skeleton rebuilds itself when a gate
next reads it, and the extraction schema regenerates itself when extraction
next starts (rule 32; both compare modification times against WONT, MILD and
the modules). If the schema changed, extraction stops once and asks for a
process restart — that is the signal that the edit reached the prompt.

---

## Log

| date | what |
|---|---|
| 2026-09-10 | A added (chronic determinable/determinate + defining axiom) |
| 2026-09-10 | B added (3 MILD axioms) |
| 2026-09-10 | C added — earlier 38-axiom orphan patch retracted as invalid |
| 2026-09-10 | D1, D2 opened |
| 2026-09-10 | A4 added; D1 settled — only `Chronic wound` bears `chronic`, so the review question became subsumption |
| 2026-09-10 | **E added** — the determinate-quality block: 5 PATO stubs, 14 classes to mint, 10 axioms, 2 alt terms, 11 CQs closed. Order-of-work table added at the top. |
| 2026-09-10 | Measured against full PATO: `open`/`closed`/`increased size`/`increased depth` already exist and are reused; `PATO_0000956 sterile` (fertility) and `PATO_0001863 chronic` (process duration) are false friends and are not. A2's decision to mint confirmed. |
| 2026-09-11 | **F added** — the import closure has 32 parentless roots beside `entity`, ~700 disconnected classes, only 24 of them used by the curated layer, and zero curated classes affected. Closure hygiene, not modelling. |
| 2026-09-11 | **B reported applied, but `Disease proposal 2.ttl` on disk is unchanged since 17 Aug** (96 501 bytes) and none of the three axioms is in it. No `.ttl`/`.owl` anywhere in the tree was modified in the last two days. Unsaved in Protégé, or saved elsewhere — to resolve before anything downstream reads MILD. |
| 2026-09-10 | Found that `Infected wound` and `Malignant wound` already carry better axioms than CQ093/CQ091 ask for — flagged as a question-file decision, not a WONT edit |
| 2026-09-12 | **B closed as not needed** — the three parents were there all along, inside intersections. |
| 2026-09-12 | **A, E (mostly), F2 applied by hand and reviewed.** 36 new WONT entities renumbered WONT_0000475–510; every new class defined; `Wound ⊑ has_quality some epithelialized` removed (a determinate of the wound *base*); definition that had landed on `skos:relatedMatch` moved to IAO_0000115; Jackson "grades" relabelled as zones; `Jackson burn wound zone model` renamed `… classification` because `model` is a blocked keyword (`test_blocklist_respects_the_ontology` caught it). Modules regenerated; CQ score 6 → 15/65. |
| 2026-09-14 | **G added** — the consolidated checklist of what the 12 Sep review left open: 11 modelling decisions, 7 small items. |
| 2026-09-12 | CQ checker now sees a restriction inside an `owl:equivalentClass` intersection (it entails the `rdfs:subClassOf` form); before, all ten precedent classes and every new one read as FAIL. |
