# Mapping review — 44 rows

The live mapping holds **191** entries, and **0** of them are identities — rule 19 pruned those.
**60** differ from their canonical only in case; of the **131** that differ by more, **87** differ
only by plural or punctuation once case is set aside. Those 147 are the partition
the 6 Sep measurement already settled — all 28 such pairs in that sample were correct, which
is why they are kept with no model call at all. Pressing `y` 87 times is not review.

That leaves **44 where a real word changed.** They are in `mapping_review.csv`, sorted with the
decisive ones first.

## How to use it

Two columns are yours:

| column | meaning |
|---|---|
| `keep(y/n)` | `n` withdraws the entry — the term goes back to being its own concept. `y` or blank leaves it. |
| `corrected canonical` | a label — re-points the entry there. Wins over `keep`, because saying where it should go is stronger than saying it should not go here. |

Then:

```
python apply_review_sheet.py mapping_review.csv           # dry run
python apply_review_sheet.py mapping_review.csv --apply   # writes, then verifies
```

Everything else in the sheet is evidence, gathered so the decision is made on something other
than the labels — the labels are what misled the embedding in the first place. `LLM verdict
(6 Sep)` and `LLM reason` are the adjudication that let each pair stand; **42 of 44 carry one**,
and that adjudication was recorded at the time as a review queue, not a final answer.

An unmarked row is not a decision. The applier says how many you left blank.

---

## 1. The ontology contradicts it — rows 1–2

I swept all 191 entries for pairs the curated ontologies **already relate by an axiom**. If WONT
says how two classes stand to each other, they are two things and the merge is wrong. Exactly one
pair came back, under two casings:

```
Wound dehiscence          -> Wound dehiscence process
wound dehiscence          -> Wound dehiscence process
```

WONT asserts:

```
WONT_0000392  Wound dehiscence
    subClassOf  pathological disorder
    subClassOf  'is specified output of' some Wound dehiscence process

WONT_0000433  Wound dehiscence process
    subClassOf  disorder development process
```

A disorder and the process that produces it, in disjoint BFO branches, related by an explicit
axiom. Merging them makes a class the specified output of itself. The 6 Sep model said
`same_class — "Same process, 'process' is redundant"`, and again on the second casing
`"Duplicate of pair 3, same process."` It was wrong both times, and this is the failure mode the
adjudication note warned about: *refusing costs one duplicate class; a wrong `same_class` cannot
be recovered.*

**My recommendation: `n` on both.**

## 2. Merging one existing class into another — rows 3–4

Not store-term-onto-class, which is the ordinary case. Both sides are already curated classes,
so the mapping is asserting the ontologies contain a duplicate.

```
Antiseptic agent (WONT_0000444)  ->  antiseptic drug (CHEBI_48218)
    WONT : "A material used for wound treatment that bears the antiseptic drug role."
    CHEBI: "A substance used locally on humans and other animals to destroy harmful
            microorganisms or to inhibit their activity."
```
WONT's class is defined *in terms of* the drug role rather than as the drug — a bearer, not the
substance. Worth your judgement; the definitions do not obviously say "same thing".

```
Cutaneous wound (HP_0032674)  ->  Skin wound (WONT_0000441)
    HP   : "a disruption of normal anatomic structure and function of the skin…"
    WONT : "A wound whose disrupted tissue is skin."
```
These do read as the same class. A cross-ontology identity claim, but a defensible one.

## 3. Never adjudicated at all — rows 5–6

Two entries carry no 6 Sep verdict, so nothing has ever checked them:

```
metronidazole and ciprofloxacin solution -> Ciprofloxacin and Metronidazole solution
Injuries Material Entity                 -> Injury Material Entity
```

The first is a word-order variant of a combination product. The second is a sense-split label
(`split_irreconcilable_terms` output) whose plural head noun `fold` cannot see, which is why it
landed here rather than among the 87.

## 4. The mapping normalises "process" in both directions — rows 7–13

This is a policy question, not seven independent y/n calls:

```
debridement                  -> Debridement process              adds
granulation tissue formation -> Granulation process              adds
keloid development           -> Keloid development process       adds
surgical wound debridement   -> Surgical wound debridement process  adds
wound closure                -> Wound closure process            adds
wound treatment              -> Wound treatment process          adds
wound healing process        -> wound healing                    DROPS
```

Six add the head noun `process`, one removes it. Whatever the right convention is, it should be
one convention — and row 12 going the other way is the one to look at hardest, since WONT
generally distinguishes a disorder from its process (see §1).

## 5. A bare adjective given an invented head noun — rows 14–17

```
electrodiagnostic  -> Electrodiagnostic studies
endovascular       -> endovascular approach
gastrointestinal   -> gastrointestinal tract
immunocompromised  -> immunocompromised states
```

Defensible — an adjective alone is not a term, so the extraction produced something that has to
go somewhere. But the mapping is choosing *which* noun, and `gastrointestinal` → the anatomical
tract is a different call from `endovascular` → a procedural approach.

## 6. Probable spelling and punctuation variants — rows 18–27

British/American, slash-vs-and, and a few singulars: `haemorrhage → Hemorrhage`,
`paediatric → pediatric`, `histopathological → histopathologic`,
`growth factor/blood-derived therapies → growth factor and blood-derived therapies`. These sit
here only because `fold` cannot see a one-letter change. Fast `y`s, most likely.

Two are not spelling: `adjunctive therapy → adjunct therapy` and
`systemic inflammatory disorders → systemic inflammatory disease` — *disorder* and *disease* are
distinguished in OGMS, so that one is a real call.

## 7. The rest — rows 28–44

Ordinary content merges with a 6 Sep verdict behind each. The ones I would not wave through:

- `Diabetic foot disease -> diabetic foot` — a disorder onto an anatomical site
- `WBC level -> WBC count` — a level and a count are different measurements
- `ultrasonography -> ultrasound` — the modality onto the wave
- `advanced wound management -> advanced wound care`
- `microvascular dysfunction -> microvascular impairment`

`E. coli → Escherichia coli`, `S. aureus → Staphylococcus aureus`, `trauma wounds → Traumatic
wound`, `risk of infection → infection risk` look plainly right.

---

## After you mark it

Withdrawals and re-points only change the mapping file. The store still holds the old spellings
until:

```
run_apply_mapping()  ->  run_build_hierarchies()  ->  run_extend_ground_truth()
```

That chain is now applicable more than once (INSTRUCTIONS rule 24) — before that fix a correction
made here could not have reached the store at all, which is the reason this review is worth doing
now rather than a week ago.
