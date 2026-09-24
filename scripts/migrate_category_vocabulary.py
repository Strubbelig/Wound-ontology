# -*- coding: utf-8 -*-
"""One-time migration: rewrite stored BFO category names to BFO's own spelling.

Decided 2026-09-08. The category vocabulary was CamelCase (`MaterialEntity`)
and is now spelled the way BFO spells it (`material entity`). See INSTRUCTIONS
rule 25 for why.

The pipeline reads a category through `declared_category`, which is
separator-blind, so a store written under the old spelling is *understood*
without this script. What it is not is *consistent*: the store would keep
saying `MaterialEntity` while everything written after today says `material
entity`, and the next `normalize()` would rewrite 4000-odd attributes as a side
effect of an unrelated run. Rule 1 -- a rewrite that large is stated, measured
and dated, not discovered.

Touches the concept store and the term mapping. It does NOT touch the
hierarchies, the context matrix or the FCA artifacts: those are derived, and
rule 6 says a build replaces them. Run `run_build_hierarchies()` afterwards.
It never touches `pubmed_abstracts` -- an abstract that says "the healing
process" is prose, not a category, and structure is the only thing that tells
them apart.

Dry run by default; pass --apply to write.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "src"))

from wound_ontology.llm.category_vocab import declared_category  # noqa: E402


def migrate_store(store) -> dict:
    """Rewrite every category name in the store to its declared spelling."""
    attrs_changed: collections.Counter = collections.Counter()
    entities_renamed: dict[str, str] = {}
    entity_merges: dict[str, list[str]] = {}
    attr_merges: dict[str, list[str]] = {}

    new_dict: dict = {}
    for pmid, rec in store.dict.items():
        new_rec = dict(rec)
        entities = rec.get("entities", {})
        new_entities: dict[str, dict[str, float]] = {}
        for entity, attrs in entities.items():
            declared = declared_category(entity)
            new_entity = declared if declared is not None else entity
            if new_entity != entity:
                entities_renamed[entity] = new_entity

            merged: dict[str, float] = new_entities.get(new_entity, {})
            if new_entity in new_entities:
                entity_merges.setdefault(new_entity, []).append(entity)

            for triple, value in attrs.items():
                new_triple = triple
                if ": " in triple:
                    pred, target = triple.split(": ", 1)
                    d = declared_category(target)
                    if d is not None and d != target:
                        new_triple = f"{pred}: {d}"
                        attrs_changed[f"{target} -> {d}"] += 1
                if new_triple in merged and merged[new_triple] != value:
                    attr_merges.setdefault(new_triple, []).append(triple)
                merged[new_triple] = max(merged.get(new_triple, 0.0), value)
            new_entities[new_entity] = merged

        new_rec["entities"] = new_entities
        new_dict[pmid] = new_rec

    return {
        "dict": new_dict,
        "attrs_changed": attrs_changed,
        "entities_renamed": entities_renamed,
        "entity_merges": entity_merges,
        "attr_merges": attr_merges,
    }


def restale_canonicals(mapping: dict[str, str]) -> dict[str, str]:
    """Entries whose canonical is a category spelled the old way.

    `roles -> Role` still fires -- `roles` is not a category -- but it hands
    back a spelling nothing else writes any more. Re-point it at the declared
    name so the mapping and the store agree on one string.
    """
    out = {}
    for k, v in mapping.items():
        d = declared_category(v)
        if d is not None and d != v and declared_category(k) is None:
            out[k] = d
    return out


def dead_mapping_entries(mapping: dict[str, str]) -> dict[str, str]:
    """Mapping entries a declared category makes unreachable.

    `role -> Role` fired when `Role` was the category spelling. It cannot fire
    now: `role` IS the category, so `clean_entity` declares it and returns
    before the mapping is consulted. Rule 19 -- the mapping is pruned to what
    can still fire, so an entry that cannot is removed rather than left to look
    like a rule nobody enforces.
    """
    return {k: v for k, v in mapping.items() if declared_category(k) is not None}


def main() -> None:
    apply = "--apply" in sys.argv

    from wound_ontology.orchestrator import Orchestrator

    p = Orchestrator()
    store = p.store

    before_attrs = sum(len(a) for r in store.dict.values()
                       for a in r.get("entities", {}).values())
    before_entities = len({e for r in store.dict.values()
                           for e in r.get("entities", {})})

    result = migrate_store(store)

    print("\n─── concept store ─────────────────────────────────────────────")
    print(f"  distinct terms       : {before_entities}")
    print(f"  attributes           : {before_attrs}")
    total = sum(result["attrs_changed"].values())
    print(f"  category attributes rewritten: {total}")
    for k, n in result["attrs_changed"].most_common():
        print(f"      {k:52s} {n:6d}")
    if result["entities_renamed"]:
        print(f"  terms renamed        : {len(result['entities_renamed'])}")
        for a, b in sorted(result["entities_renamed"].items()):
            print(f"      {a!r} -> {b!r}")
    else:
        print("  terms renamed        : 0")
    for label, d in (("term merges", result["entity_merges"]),
                     ("attribute merges", result["attr_merges"])):
        if d:
            print(f"  {label}: {len(d)}")
            for k, v in sorted(d.items()):
                print(f"      {k!r} <- {v}")
        else:
            print(f"  {label}: 0")

    after_attrs = sum(len(a) for r in result["dict"].values()
                      for a in r.get("entities", {}).values())
    after_entities = len({e for r in result["dict"].values()
                          for e in r.get("entities", {})})
    print(f"  after: {after_entities} terms, {after_attrs} attributes "
          f"({before_entities - after_entities} term(s), "
          f"{before_attrs - after_attrs} attribute(s) collapsed)")

    print("\n─── term mapping ──────────────────────────────────────────────")
    mapping = dict(p.term_mapper.mapping)
    dead = dead_mapping_entries(mapping)
    restale = restale_canonicals(mapping)
    print(f"  entries              : {len(mapping)}")
    print(f"  unreachable under the declared vocabulary: {len(dead)}")
    for k, v in sorted(dead.items()):
        print(f"      {k!r} -> {v!r}   (withdraw)")
    print(f"  canonical spelled the old way: {len(restale)}")
    for k, v in sorted(restale.items()):
        print(f"      {k!r} -> {mapping[k]!r} becomes {v!r}")

    if not apply:
        print("\ndry run — nothing written. Pass --apply to write.")
        return

    store.dict = result["dict"]
    store.save()
    print("\nstore written.")

    if dead or restale:
        removed = p.term_mapper.withdraw(
            *dead, reason="canonical is a retired category name") if dead else 0
        if restale:
            p.term_mapper._report_skipped(
                p.term_mapper._term_mapping.add_batch(
                    restale,
                    {k: {"standard": v, "confidence": 1.0,
                         "method": "declared-category"} for k, v in restale.items()},
                ), "the category migration")
        p.term_mapper.save()
        for k, v in restale.items():
            got = p.term_mapper.map(k)
            if got != v:
                raise RuntimeError(f"mapping {k!r} is {got!r}, expected {v!r}")
        print(f"mapping: withdrew {removed} unreachable entr(ies), re-pointed "
              f"{len(restale)}; {len(p.term_mapper.mapping)} remain, verified.")

    print("\nNow rebuild the derived artifacts:  run_build_hierarchies()")


if __name__ == "__main__":
    main()
