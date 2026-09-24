# Mapping review — 2026-09-22

The 10 Sep review is kept beside this one as `MAPPING_REVIEW_2026-09-10.md`; it
was written against a 191-entry mapping over a 3,727-term store. The store is
now **98,522 terms from 6,029 abstracts**, and the mapping the 21 Sep build left
behind holds **14,101 live entries**. Everything below is about making that
reviewable rather than nominally reviewable.

`review_mapping()` asks about every one of them at an interactive prompt.
Pressing `y` fourteen thousand times is not review, so the queue is partitioned
first — by the rule the pipeline itself used to decide what to ask the model.

## How to work it — read the family sheet, not the entry sheet

`data/review/mapping_families_2026-09-23.csv` is the one to mark. One row is one
**canonical**, with every term that collapses onto it in the `terms` cell:
**4,813 entries are 3,574 families**, and the repetition is all inside the
families — `Debridement process` gathers five spellings, and that is one
decision, not five.

Every row carries a **`suggested`** verdict filled by rule, with the rule in the
`why` cell. 518 rows suggest `n`; the rest suggest `y`. The work is reading and
overriding, not deciding from nothing.

Four filters take most of it off the table in four decisions:

| filter | rows | one decision |
|---|---|---|
| `variation` = spelling / word order / abbreviation | 579 families | British/American, hyphenation, word order, acronym expansion — measured clean in an 80-row hand check |
| `process` column | 117 entries | settled: **the ontology's own label wins** (your ruling, 23 Sep), so everything pointing at a WONT class keeps its `… process` spelling |
| `blocked canonical` = yes | 319 entries | these canonicals are on the methodology blocklist; the decision belongs to `review_lists`, not here — see `blocked_canonicals_2026-09-23.csv` |
| `onto an existing class` = yes | **87 families** | the irreversible ones. This is the set worth your full attention |

`data/review/mapping_review_2026-09-23.csv` keeps the entry-level record with the
model's verdict and reason on every row, for when a family needs splitting.
`scripts/apply_review_sheet.py` reads either file.

## What is in the sheet, and what is not

`label_difference` says how two labels differ:

| | | in the sheet |
|---|---|---|
| `identical` | the same words; case, punctuation or spacing differ | no |
| `inflection` | the same words up to singular/plural | no |
| `content` | at least one word is genuinely different | **yes** |

The first two were accepted with no model call, because all 28 such pairs in the
6 Sep sample were right, and nothing since has contradicted that. That is
**9,283 entries** you are not being asked about.

The remaining **4,818 rows are `data/review/mapping_review_2026-09-22.csv`**,
ordered by consequence, not alphabetically.

## How to mark it

Two columns are yours:

| column | meaning |
|---|---|
| `keep(y/n)` | `n` withdraws the entry — the term goes back to being its own concept. `y` or blank leaves it standing. |
| `corrected canonical` | a label — re-points the entry there. **Wins over `keep`**, because saying where a term belongs is stronger than saying it does not belong here. |

```
python scripts/apply_review_sheet.py data/review/mapping_review_2026-09-22.csv           # dry run
python scripts/apply_review_sheet.py data/review/mapping_review_2026-09-22.csv --apply   # writes, then verifies
```

Both the sheet and the applier are in `scripts/` this time. The 10 Sep applier
lived in a scratchpad and is gone, which is why this sheet had to be rebuilt
from nothing.

The other columns are evidence, gathered so the decision rests on something
other than the two labels — the labels are what misled the embedding in the
first place. `LLM verdict` / `LLM reason` are the adjudication that let each row
stand; `variation` says whether the difference is a real word (`real`) or only
word order, spelling or an abbreviation; `term mentions` / `canonical mentions`
are how much corpus each side carries.

An unmarked row is not a decision. The applier says how many you left blank.

---

## Decide these first

### 1. The one merge the ontology already contradicts

```
Antiseptic agent (WONT_0000444)  ->  antiseptic drug (CHEBI_48218)
```

WONT relates these two by `skos:relatedMatch` — a deliberate statement that they
are close but *not* the same class, and WONT's own definition makes its class a
**bearer** of the drug role rather than the substance. The model called it
`same_class — "Synonymous labels for the same substance"`. This is the same shape
as the 10 Sep `Wound dehiscence -> Wound dehiscence process` catch: a mapping
that contradicts an axiom you wrote. **Recommendation: `n`.**

Two more label pairs differ only by case, so they never reach the sheet, but you
should know they exist:

```
abscess    (HP_0025615)  /  Abscess    (WONT_0000472)
lymphocele (DOID_4347)   /  Lymphocele (WONT_0000470)
```

After the store's title-casing these are one name. Nothing downstream can tell
them apart, so whatever the `relatedMatch` was meant to say is not said to the
pipeline. A naming decision for you, not a mapping decision.

### 2. Two store terms mapped onto a BFO category name

```
materials  ->  material entity   (15 mentions)
Materials  ->  material entity   (2 mentions)
```

`material entity` is one of the fifteen BFO category names, and it appears 5,927
times in the store as a *typing*, not as a term. Applying these makes 17 mentions
of the word "materials" indistinguishable from the category everything else is
typed with. `ConceptStore.normalize` handles the case without crashing (it
declares the category spelling), so this is a curation call, not a bug.
**Recommendation: `n` on both.** Flagged in the sheet as `BFO category side`.

### 3. The "process" suffix, in both directions — a policy, not 66 y/n calls

65 anchor rows add or drop the head noun `process` (117 rows in the whole
sheet):

```
debridement                  -> Debridement process                   adds   (291 mentions)
wound closure                -> Wound closure process                 adds   (220)
angiogenesis                 -> Angiogenesis process                  adds   (207)
tissue regeneration          -> Tissue regeneration process           adds   (90)
…
tissue remodeling processes  -> tissue remodeling                     DROPS  (1)
dressing change process      -> Dressing change                       DROPS  (1)
```

Adding is what the `… process` naming convention wants, and every one of those
canonicals is an existing WONT class. The two that drop it are the ones to look
at hardest: WONT distinguishes a disorder from the process that produces it, and
`Dressing change` is a class in its own right. Filter the sheet on the `process`
column and decide once.

### 4. The anchor merges — the irreversible ones

**144 rows** absorb a store term into a class that already exists in WONT or
MILD. These are the identity claims: after `run_apply_mapping` the store term is
gone and the class carries its mentions, and nothing downstream can take that
back. Every one carries the model's reason and the ontology's own definition was
in front of the model when it answered.

The ones I would not wave through:

```
materials                     -> material entity              (see §2)
painful condition             -> painful                      a condition onto a quality
softening                     -> softened                     a process onto its result
Streptococcus species         -> Streptococcus                a species onto its genus
second-degree burn injury     -> Second-degree burn wound     injury and wound as synonyms
antibiotic prophylaxis        -> Prophylactic antibiotic therapy
```

The rest are mostly the `process` policy of §3, British/American spellings
(`epithelialisation`, `remodelling`, `ischaemic`), and abbreviations
(`S. aureus`, `E. coli`, `P. aeruginosa`) — fast rows.

### 5. The store-to-store merges — stop wherever you like

**4,673 rows** merge one store term into another. They touch no class, so a
wrong one costs a duplicate term rather than a wrong identity claim, and the
sheet is sorted so the consequential ones come first: the **top 300 rows carry 49% of all the mentions these merges touch**, and the tail is singletons.

Two clusters worth your eye at the top:

```
wound healing process   -> wound healing     (47 + 948 mentions)  DROPS 'process'
Diabetes mellitus       -> diabetes          (26 + 316)
Diabetes Mellitus       -> diabetes          (12 + 316)
```

`diabetes mellitus -> diabetes` was measured as **not** a synonym on 6 Sep and
withdrawn then. It came back under two capitalisations, was re-adjudicated by
the model as `same_class`, and is live again. Withdrawing the lowercase pair did
not withdraw the concept.

---

## Queues that are not this sheet

* **969 refusals** — the model said `different` and the build already withdrew
  them: 947 on 21 Sep (`output/p4_mapping.log`) and 22 more today, on pairs the
  chain resolution had created (`output/p4_readjudicate.log`). No action. The
  22 are worth reading as evidence that resolving and re-asking was the right
  order: `granulations -> Granulation process`, `autoimmune disorder ->
  Autoimmune disease`, `inflammation -> inflammatory`, all of them material
  entity against process or disposition.
* **968 subsumption candidates** — 960 in
  `data/cache/mapping_subsumption_candidates_2026-09-21_23-24.csv` and 8 more in
  today's file, written in `Class` / `Parent class` shape. Not synonyms, but not
  nothing. **Only 9 of them involve a curated class** (`wound debridement` under
  `Surgical wound debridement process`, `antiseptic` under `antiseptic drug`,
  `scarring process` under `Pathological scarring process`, …); the other 951
  are store term over store term and belong to the hierarchy step, not to
  minting.
* **The 51 anchor mappings the category guard refused** before the model was
  even asked (`Wound Dressing -> Wound dressing`, `laceration -> Laceration`).
  These were refused because the store's own typing of the term contradicts the
  class's BFO category — worth a look only if you think the store's typing is
  the thing that is wrong.

## Applied — 2026-09-23

`run_apply_mapping` has been run. The store went from **98,522 distinct terms to
84,418**: 14,104 names disappeared into another, 15,386 renames are logged in
the store's own decision record (`decisions.renamed`, each stamped
`by="mapping"`), and 176,360 entity records remain. No mapping entry still fires
on any live name, so the store is at the mapping's fixed point.

**The sheet was unmarked when this ran**, so everything below — including the
three rows recommended `n` — went in as it stood. That is what the backup is
for: `data/backup/concept_store_pre_mapping_2026-09-22.json` is the pre-apply
store, byte-identical to the cache original and outside the ten-version
rotation, with `data/backup/README.md` saying how to go back. Mark the sheet,
restore, re-apply, and the merges you refused are gone.

Two things the apply itself uncovered, both fixed:

* **One chain only a fold could see.** `deep partial thickness skin burns ->
  deep partial-thickness burns` beside `Deep partial-thickness burns -> deep
  partial-thickness burn wounds`: one capital letter hid it from the exact-string
  resolution, and the store's own folded lookup found it. `resolve_chains` now
  walks folded, as the store does.
* **One pass was not the whole apply.** `normalize` maps a name and then
  title-cases it, so a name a pass produces can be a key that pass has already
  walked past. Pass 1 collapsed 12,912 names, pass 2 another **1,191**, pass 3
  one more, pass 4 none — and the run had been reporting a finished apply after
  pass 1. `MappingCleaner.apply` now runs to convergence and says how many
  rounds a single pass would have left (INSTRUCTIONS rule 24, refined).

## One defect fixed before this sheet was written

The 21 Sep mapping was not a forest. Every single build writes one — the
clustering asserts it — but the **file accumulates across builds**, and a term
this build makes a canonical may be a term an earlier build already mapped
elsewhere. Measured: **735 chains whose second hop really renames** and **408
two-cycles that are not case variants**.

`ConceptStore.normalize` follows exactly one hop, so both shapes failed quietly:
a chain half-landed the merge (`thermal burns -> thermal burn` beside
`thermal burn -> thermal burn injuries` leaves the store holding both names), and
a cycle undid itself (`CFU -> CFUs` beside `CFUs -> CFU` renames each onto the
other and merges nothing).

`TermMapper.resolve_chains` now re-points every entry onto its terminal and
breaks each cycle with the same rule that picks a cluster's canonical. On this
file: **349 re-pointed, 1,444 cycles broken, 10 withdrawn** because their chain
ended at a class the category guard refuses for that term (`granulation ->
Granulation process` among them). 15,585 entries became 14,131.

The pairs the resolution created were then sent back through the adjudication,
because a pair no model has seen is exactly what rule 18 forbids: 4,818 pairs,
of which all but 30 came back from the cache, and **30 more entries were
withdrawn** — 22 refused outright and 8 turned into subsumption candidates.
14,131 became **14,101**, and nothing in the mapping is now unasked.
