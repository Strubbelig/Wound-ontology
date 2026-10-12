# Missing wound axioms — to do (2026-10-11)

Hand edits to the curated WONT (`data/ground truth/ground_truth_final.owl`); the
pipeline never writes there. Companion to `WONT_TODO.md`, item 1.3.

**What a wound must say, and what it says now.** Measured on the 53 wound
classes (Wound and everything under it or defined on it):

| a wound should say… | today |
|---|---|
| which **structure** is damaged, and how deep | nothing structural; `Deep wound` and `Large wound` only by a quality |
| that it is **at least a skin defect**, maybe more below | nothing; `Skin wound` is one defined subclass |
| which **region** of the body | 2 of 53 classes: `Skin wound` (located in Skin), `Diabetic foot ulcer` (located in Foot) |
| **how long** | `Wound has quality some degree of time after disease inception`; `Chronic wound` defined; `Acute wound` bare |
| **why** (cause) | 11 classes `output of` a wound causing process; 13 causal classes bare |
| **how treated** | `Wound treatment process has participant some Wound`; dressing process; most treatments exist only as plans |

FMA in WONT today: 3 classes (Skin `FMA_7163`, Foot `FMA_9664`, one more).
`fma_module.owl` holds 14 classes. OFL references about 1,700 FMA classes —
"fits OFL" means the defect is described with the same FMA classes as the flap.

**One rule for every item below.** A class axiom must be true of *every*
instance. "Pressure ulcers usually lie over a bony prominence", "venous ulcers
are treated with compression", "chronic means more than 4 weeks" are clinical
defaults or scheme thresholds, not axioms (Schulz et al. 2009; rule 66). Typical
sites go nowhere; treatments are stated from the treatment's side; thresholds are
information entities in the knowledge layer (MILD's threshold specification).

Syntax: Manchester-like. `≡` defining (equivalent) axiom, `⊑` subclass axiom.
Relations: `has part` BFO_0000051, `part of` BFO_0000050, `located in`
RO_0001025, `has participant` RO_0000057, `output of` RO_0002353, `has quality`
RO_0000086, `realizes` BFO_0000055, `is about` IAO_0000136. All FMA numbers
below were looked up in `../Import ontologies/fma_obo.owl` (FMA 2020-04-13).

---

## 0. Your decisions first

| # | decision | recommendation |
|---|---|---|
| D1 | **How the damaged structure is stated.** (a) `Wound ⊑ has part some (Portion of tissue and part of some X)` — the wound *contains* damaged tissue of X; (b) `Wound ⊑ part of some X` — false for a wound that reaches below X; (c) `Wound ⊑ overlaps some X`. | (a). It matches MILD: a disorder is the abnormally constituted material, so the wound has the damaged tissue as part. |
| D2 | **"Only down to the dermis"** needs a closure (`has part only …`), which is OWL DL: HermiT classifies it, ELK does not. Alternative: a quality "deepest affected layer" with values, which ELK handles. | Closure axioms; check with HermiT (the final check is HermiT anyway). |
| D3 | **"At least a skin defect" excludes some things now in WONT.** Tscherne–Oestern grades *closed* fractures with soft-tissue injury under intact skin (C0–C3); pressure injury stage 1 and deep tissue injury are intact skin; first-degree burns damage the epidermis only. | Decide per scheme: intact-skin grades are *soft-tissue injuries*, not wounds (move them under a sibling `Closed soft tissue injury`); first-degree burn stays a wound (the epidermis is damaged). |
| D4 | **`Skin wound`** becomes equivalent to `Wound` once every wound has a skin part. | Keep the class as an alternative term of `Wound` (merge); repoint its 7 children. |
| D5 | **Region classes pre-coordinated or not.** Literature names "sacral pressure ulcer", "heel ulcer", "scalp defect". | Only where the region is part of the clinical definition (leg ulcer, diabetic foot ulcer); the rest by query (`located in some X`). |
| D6 | **Where the WONT–OFL bridge axioms live.** They name classes of both ontologies. | A small bridge file importing WONT and OFL (`wont_ofl_bridge.ttl`), so neither curated file imports the other. |
| D7 | **FMA's own part relations** (`constitutional_part_of`, `regional_part_of` in fma_obo) are not BFO `part of`, so "Epidermis part of Skin" is invisible to a reasoner using BFO. | Bridge them in the module: `fma:constitutional_part_of ⊑ BFO_0000050`, `fma:regional_part_of ⊑ BFO_0000050` (rule 34: in the module, not in WONT). |

---

## 1. Foundation: FMA module and relations

| # | what | detail |
|---|---|---|
| 1.1 | **Seed the FMA module** with the classes below and regenerate (`../Disease ontologies/build_disease_proposal.sh`, rule 34). Source: `../Import ontologies/fma_obo.owl` (OBO IRIs `obo/FMA_…`, the same as OFL). | ~70 seeds; with ancestors the module grows to a few hundred classes. |
| 1.2 | **Bridge FMA's part relations** to BFO `part of` (D7). | Without it no reasoner infers a wound in the skin of the foot is in the foot. |
| 1.3 | **Property chain** `located in ∘ part of → located in` (RO has it) must be in `ro_module.owl`. | ELK supports chains; check after regenerating. |
| 1.4 | **Reuse OFL's FMA classes** where OFL already uses them (skin paddles, muscles, bones of flaps); list OFL's FMA seeds and take the overlap first. | So a flap's tissue and a defect's tissue are the same classes. |

**Layers (depth)**

| class | FMA |
|---|---|
| Skin | FMA_7163 |
| Epidermis | FMA_70596 |
| Dermis | FMA_70323 |
| Papillary layer of dermis | FMA_64776 |
| Reticular layer of dermis | FMA_64778 |
| Hypodermis | FMA_70544 |
| Subcutaneous adipose tissue | FMA_74315 |
| Superficial fascia | FMA_9630 |
| Fascia of limb (deep fascia of the limbs) | FMA_57813 — *a general "deep fascia" class: look up* |
| Skeletal muscle tissue | FMA_14069 |
| Muscle organ | FMA_5022 |
| Tendon | FMA_9721 |
| Ligament | FMA_30319 |
| Articular capsule | FMA_34836 |
| Articular cartilage | FMA_12264 |
| Periosteum | FMA_24041 |
| Bone organ | FMA_5018 |
| Bone tissue | FMA_224804 |
| Nerve | FMA_65132 |
| Blood vessel | FMA_63183 |
| Portion of tissue | FMA_9637 |
| Zone of skin | FMA_86166 |
| Surface of skin | FMA_67726 |

**Regions**

| class | FMA | class | FMA |
|---|---|---|---|
| Cardinal body part | FMA_7153 | Upper limb | FMA_7183 |
| Head | FMA_7154 | Arm | FMA_24890 |
| Scalp | FMA_46494 | Elbow | FMA_24901 |
| Face | FMA_24728 | Forearm | FMA_9663 |
| Neck | FMA_7155 | Hand | FMA_9712 |
| Trunk | FMA_7181 | Lower limb | FMA_7184 |
| Thorax | FMA_9576 | Free lower limb | FMA_24879 |
| Back | FMA_14181 | Hip | FMA_24964 |
| Abdomen | FMA_9577 | Thigh | FMA_24967 |
| Anterior abdominal wall | FMA_14627 | Knee | FMA_24974 |
| Pelvis | FMA_9578 | Leg (lower leg) | FMA_24979 |
| Perineum | FMA_9579 | Ankle | FMA_9665 |
| Buttock | FMA_25245 | Foot | FMA_9664 |
| Breast | FMA_9601 | Heel | FMA_24994 |
| Sacrum | FMA_16202 | Toe | FMA_25046 |
| Greater trochanter | FMA_32852 | Medial / lateral malleolus | FMA_35451 / FMA_35502 |
| Ischial tuberosity | FMA_17010 | *Sacral region, skin of heel* | *not in FMA under these names — look up (candidates: Surface of sacrum FMA_31692, Surface of heel FMA_25452)* |

**Skin of a region** (for "skin defect of the …")

Skin of foot FMA_37834 · Skin of sole of foot FMA_37849 · Skin of dorsum of foot
FMA_37846 · Skin of leg FMA_37828 · Skin of lower limb FMA_23102 · Skin of
buttock FMA_45285 · Skin of back FMA_10462 · Skin of trunk FMA_12167 · Skin of
abdomen FMA_22988 · Skin of breast FMA_10464 · Skin of perineum FMA_20429 · Skin
of head FMA_12166 · Skin of scalp FMA_24757 · Skin of face FMA_24758 · Skin of
hand FMA_38295.

---

## 2. Damaged structure: at least skin, maybe deeper

| # | class | axiom to add | note |
|---|---|---|---|
| 2.1 | **Wound** | `⊑ has part some (Portion of tissue and part of some Skin)` | "at least a skin defect" (D1, D3) |
| 2.2 | *new* **Epidermal wound** | `≡ Wound and has part some (Portion of tissue and part of some Epidermis)` + closure: `has part only (Portion of tissue and part of some Epidermis)` | D2 |
| 2.3 | *new* **Partial-thickness wound** | `≡ Wound and has part some (… part of some Dermis)` + closure to epidermis or dermis | |
| 2.4 | *new* **Superficial / deep partial-thickness wound** | papillary (FMA_64776) / reticular (FMA_64778) layer as the deepest | needed for burns IIa/IIb |
| 2.5 | *new* **Full-thickness wound** | `≡ Wound and has part some (… part of some Hypodermis)` | |
| 2.6 | *new* **Wound reaching fascia** | `≡ Wound and has part some (… part of some (Superficial fascia or Fascia of limb …))` | deep fascia class: look up |
| 2.7 | *new* **Wound reaching muscle** | `≡ Wound and has part some (… part of some Skeletal muscle tissue)` | |
| 2.8 | *new* **Wound reaching tendon, ligament or joint** | Tendon FMA_9721, Ligament FMA_30319, Articular capsule FMA_34836 | Wagner 2 |
| 2.9 | *new* **Wound reaching bone** | `≡ Wound and has part some (… part of some Bone organ)` | Wagner 3, burn IV, pressure stage 4 |
| 2.10 | **Deep wound** (WONT_0000508, `has quality some increased depth`) | keep the quality definition; do **not** equate it with 2.5 | depth in millimetres ≠ layer reached (an eyelid full-thickness wound is shallow) |
| 2.11 | **Soft tissue wound** (WONT_0000551, bare) | define by layer (e.g. `≡ Full-thickness wound`), or retire | FMA has no single "soft tissue" class — decide what it means |
| 2.12 | **Wound with accompanying fracture** (WONT_0000426, bare) | `⊑ has part some (… part of some Bone organ)` and a link to the fracture | fracture class: look up (e.g. HPO "Bone fracture") |
| 2.13 | **First-degree burn wound** (482) | `≡ Thermal wound and Epidermal wound` | |
| 2.14 | **Second-degree burn wound** (483) | `≡ Thermal wound and Partial-thickness wound`; split IIa/IIb on 2.4 | WONT already has the Hildanus/Derganc grade individuals |
| 2.15 | **Third-degree burn wound** (484) | `≡ Thermal wound and Full-thickness wound` | |
| 2.16 | **Fourth-degree burn wound** (485) | `≡ Thermal wound and (Wound reaching muscle or Wound reaching bone)` | |
| 2.17 | **Pressure ulcer** by depth | defined subclasses `Pressure ulcer and Partial-thickness wound` (stage 2), `… Full-thickness wound` (3), `… reaching fascia/muscle/bone` (4); stage 1 and deep tissue injury per D3 | stages themselves stay grades (§6) |
| 2.18 | **Diabetic foot ulcer** by depth | `… and Wound reaching tendon, ligament or joint` (Wagner 2), `… and Wound reaching bone` (Wagner 3) | |
| 2.19 | **Gustilo–Anderson / Tscherne–Oestern** (429, 430) | open-fracture wounds: `⊑ Wound with accompanying fracture`; Tscherne closed grades per D3 | |

## 3. Region

| # | class | axiom to add | note |
|---|---|---|---|
| 3.1 | **Wound** | `⊑ located in some Cardinal body part` (FMA_7153) | every wound is somewhere |
| 3.2 | **Arterial leg ulcer** (WONT_0000027) | `≡ Arterial insufficiency wound and located in some Leg` (FMA_24979) | now only ⊑ Skin wound |
| 3.3 | **Ulcus cruris venosum** (347) | `≡ Venous insufficiency wound and located in some Leg` | classifies automatically |
| 3.4 | **Ulcus cruris mixtum** (346) | `≡ Wound and output of some (… venous insufficiency …) and output of some (… arterial occlusive …) and located in some Leg` | |
| 3.5 | **Ulcus hypertonicus Martorell** (348) | `⊑ located in some Leg` | "laterodorsal lower leg" is typical, not universal |
| 3.6 | **Diabetic foot ulcer** (549) | exists (`located in some Foot`); check "below the ankle" (IWGDF) = Foot | |
| 3.7 | **Pressure ulcer** | no region axiom (sites are typical); optional classes per D5 (`Sacral pressure ulcer`, `Heel pressure ulcer`) | |
| 3.8 | optional, per D5 | `Scalp wound ≡ Wound and located in some Scalp` and the like | the thesis's "irradiated scalp defect" |

## 4. How long

| # | class | axiom to add | note |
|---|---|---|---|
| 4.1 | **Acute wound** (WONT_0000553, bare) | `≡ Wound and has quality some acute` (WONT_0000476) | mirrors `Chronic wound` |
| 4.2 | *new* **Chronic wound threshold specification** | `⊑ disease threshold specification` (MILD_120029), `is about some chronic`, with a threshold value (MILD_120030) per scheme (4, 6, 12 weeks) | knowledge layer; several schemes side by side |
| 4.3 | **Becoming chronic** | the moment a wound crosses the threshold as a `threshold crossing event` (MILD_120031) | MILD already has the class |
| 4.4 | **Wound** | check MILD's course pattern: `participates in some course of the disease process` (MILD_120028) if MILD states it for every disorder | then healing and non-healing are parts of the course |

## 5. Why (cause)

| # | class | axiom to add | note |
|---|---|---|---|
| 5.1 | **Thermal wound** (310) | turn `⊑ output of some Wound causing heat impact process` into `≡ Wound and output of some …` | so burns classify |
| 5.2 | **Bite wound** (044) | `≡ Wound and output of some Wound causing bite process` | *mint* the process ⊑ Wound causing trauma process |
| 5.3 | **Dog / Cat / Human bite wound** (091 / 060 / 148) | `≡ Bite wound and output of some (… has participant some (Tooth and part of some <organism>))` | NCBITaxon_9615 dog, NCBITaxon_9685 cat, NCBITaxon_9606 human; Tooth: FMA look up |
| 5.4 | **Laceration** (552) | `≡ Wound and output of some Wound causing blunt tearing process` | *mint* |
| 5.5 | **Scratch wound** (271) | `≡ Wound and output of some Wound causing scratch process` | *mint* |
| 5.6 | *new* **Surgical wound** | `≡ Wound and output of some Surgical treatment process` (WONT_0000298) or an incision process | missing; CDC classes (068, 067, 525, 526) belong under it |
| 5.7 | **CDC wound classes** | `⊑ Surgical wound` in addition to their microbial-burden parent | CDC classifies surgical wounds only |
| 5.8 | *new* **Flap donor site wound** | `≡ Surgical wound and output of some Flap transfer process` (OFL OFLID1000136) | bridge (D6) |
| 5.9 | *new* **Chemical wound** | `≡ Wound and output of some Wound causing chemical impact process`; `Wound causing acidity impact process` (004) ⊑ it | process exists, wound class does not |
| 5.10 | *new* **Radiation wound** | `≡ Wound and output of some Wound causing ionizing radiation process` | *mint*; central for reconstructive surgery |
| 5.11 | *new*, optional | **Cold injury wound** (frostbite) | |
| 5.12 | **Marjolin ulcer** (186) | `⊑ Malignant wound` and its origin in a scar or chronic wound | now only ⊑ Skin wound |
| 5.13 | **Ulcus hypertonicus Martorell** (348) | `≡ Wound and output of some (… hypertensive arteriolosclerosis process)` | *mint* the process |
| 5.14 | **Blistering skin wound** (046) | output of a blister-forming process, or a quality `blistered` | decide |
| 5.15 | **Wound with accompanying fracture** (426) | inherits trauma from `Traumatic wound`; see 2.12 | |

## 6. How treated (always from the treatment's side)

| # | class | axiom to add | note |
|---|---|---|---|
| 6.1 | every wound treatment process | check each inherits `has participant some Wound` from `Wound treatment process` (423) | debridement, closure, irrigation, offloading, cold plasma do |
| 6.2 | *new* **Negative pressure wound therapy process** | `⊑ Wound treatment process`, `realizes some Negative pressure wound therapy plan specification` (213), `has participant some (device …)` | plan exists, process does not |
| 6.3 | *new* **Skin grafting process** | `⊑ Wound closure process`, `realizes some Skin grafting plan specification` (286), `has participant some Skin graft` (285) | |
| 6.4 | *new* **Suturing process** | `⊑ Wound closure process`, `realizes some Suturing plan specification` (302), `has output some Suture in situ` (301) | |
| 6.5 | *new* **Compression therapy process** | `realizes some Compression therapy plan specification` (077) | participant "some Wound" only if defined as *wound* compression |
| 6.6 | **Flap plasty plan specification** (114) ↔ OFL | `Flap transfer process` (OFL OFLID1000136) `realizes some Flap plasty plan specification` | bridge (D6) |
| 6.7 | **OFL Closure of the flap recipient site** (OFLID10170) | `⊑ Wound closure process` (388) `and has participant some Wound` | the defect OFL's flap closes **is** a WONT wound — the link the thesis promises |
| 6.8 | **OFL Closure of the flap donor site** (OFLID10169) | `⊑ Wound closure process and has participant some Flap donor site wound` (5.8) | |
| 6.9 | **OFL Wound coverage role** (OFLID106000) | `⊑ realized in some (Wound closure process and has participant some Wound)` | |
| 6.10 | **Wound treatment plan specification** (200) | `⊑ is about some Wound` | every wound treatment plan is about a wound |

## 7. Classification layer (grades stay information)

| # | what | note |
|---|---|---|
| 7.1 | Each scheme's grades (Wagner, Shea, burn degree/zone, CDC, IWII, Gustilo–Anderson, Tscherne–Oestern) **are about** the layer- or cause-defined classes of §2 and §5; they are not themselves wound kinds | MILD commitment: classification-relative boundaries; and rule 77 |
| 7.2 | Where a grade *is* defined by a layer (burn degree, pressure stage, Wagner 1–3), state the criterion once as a specification that `is about` the depth class | optional |

## 8. Competency questions to add

| # | question (triple) |
|---|---|
| 8.1 | Which layer does a second-degree burn reach? *Second-degree burn wound — has part — part of Dermis* |
| 8.2 | Which wounds reach bone? *Wound reaching bone ⊑ …* |
| 8.3 | Where is an arterial leg ulcer? *Arterial leg ulcer — located in — Leg* |
| 8.4 | What causes a dog bite wound? *Dog bite wound — output of — Wound causing bite process* |
| 8.5 | Is a flap donor site a surgical wound? *Flap donor site wound ⊑ Surgical wound* |
| 8.6 | Which process closes the flap recipient site? *Closure of the flap recipient site ⊑ Wound closure process* |
| 8.7 | When is a wound chronic, by which scheme? *Chronic wound threshold specification — is about — chronic* |

## 9. After the edit

1. Regenerate the modules (`build_disease_proposal.sh`), check the FMA module holds the seeds of 1.1.
2. ELK over WONT + imports: 0 unsatisfiable. HermiT for the closure axioms (D2).
3. Competency questions: 49/49 must stay; the new ones of §8 pass.
4. `scripts/p4_derive.py` (or only the class tree and WONT steps) and
   `scripts/build_wont_core.py --write`: new defined classes (§2, §5) should
   collect existing wound classes and literature classes beneath them.
