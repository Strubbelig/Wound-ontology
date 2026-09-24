# Pre-apply backup — 2026-09-22

The state of the store and the mapping immediately before the first
`run_apply_mapping()` of the P4 derived rebuild.

| file | what |
|---|---|
| `concept_store_pre_mapping_2026-09-22.json` | `data/cache/concept_store_2026-09-21_04-33.json` — 6,029 PMIDs, 98,522 distinct terms, no mapping applied |
| `term_mapping_pre_apply_2026-09-22.json` | `data/cache/term_mapping_2026-09-22_07-26.json` — 14,101 entries, the mapping that was applied |

`data/cache/` keeps only the last ten versions of each artifact, so the
pre-apply store leaves the cache after ten further store writes. This copy does
not rotate.

**To go back:** copy the store back into `data/cache/` under a NEWER timestamp
than anything there (the loader takes the latest), correct the mapping with
`scripts/apply_review_sheet.py`, and run `run_apply_mapping()` again. Applying
is repeatable (INSTRUCTIONS rule 24); splitting a merge that has already been
applied is not — that is what this copy is for.
