"""Which store relations hold for every instance of their subject (rules 66, 88).

A relation `C R T` read as `C SubClassOf R some T` is `all` when the axiom is
true of every instance of C, `no` otherwise. The instance reading answers `yes`
or `no` on the relation in the term dict (rules 66, 89;
`TermMappingAndGate.read_relations`, until 2026-10-30 in `result.json` files
beside it); the curator's word on the relation comes first (rules 69, 72): an
axiom the curator added is `all`, a relation the curator left out is `no`.

Every name goes through the store's resolver, as the export does: the readings
were made on the names of their day, and a later rename must reach them.
"""
from __future__ import annotations

from wound_ontology.utils.string_utils import smart_title

RANK = {"no": 0, "some": 1, "all": 2}


def key(subject: str, predicate: str, value: str, resolve=None) -> tuple[str, str]:
    """(subject, "predicate: value") in the shape ContextMatrix uses, folded for lookup."""
    if resolve is not None:
        subject, value = resolve(subject)[1], resolve(value)[1]
    pred = str(predicate).strip().lower().replace(" ", "_")
    return smart_title(str(subject)), f"{pred}: {str(value).strip()}".lower()


def load_verdicts(store) -> tuple[dict, dict]:
    """{(subject, attribute): (verdict, source)} and a report of how it was built.

    The verdicts are the term dict's: the instance reading's answer on each
    relation, and the author's word where he gave one (rules 69, 72), which
    counts over the reading. His decisions of the review pages were read from
    `curator_axioms_2026-10-03.json` and `new_class_relation_decisions.json`
    until 2026-10-30, when they moved into the term dict.
    """
    from wound_ontology.mappers.judgements import AUTHOR, RELATION_READER, current, rank
    resolve = store.resolver(mapped=True) if store is not None and hasattr(store, "resolver") else None
    terms = getattr(store, "terms", None)
    if terms is None or not hasattr(terms, "read_relations"):
        raise RuntimeError("inheritance by universality needs the term dict's instance reading (rule 66); "
                           "this store carries no term dict")
    judged = terms.read_relations(RELATION_READER)
    if not judged:
        raise RuntimeError(f"no relation in the term dict carries a judgement of {RELATION_READER}: "
                           f"inheritance by universality needs the reading (rule 66)")
    verdicts: dict[tuple[str, str], tuple[str, str]] = {}
    conflicts: list[dict] = []
    curator = overridden = 0
    for subj, pred, tgt, axiom, j in judged:
        k = key(subj, pred, tgt, resolve)
        v = "all" if axiom else "no"
        if rank(j) == AUTHOR:
            curator += 1
            js = ((terms.records.get(subj) or {}).get("relations") or {}).get(f"{pred}: {tgt}") or []
            read = current([x for x in js if x["by"] == RELATION_READER])
            overridden += bool(read and read["verdict"] != j["verdict"])
        if k in verdicts and verdicts[k][0] != v:
            conflicts.append({"relation": k, "verdicts": [verdicts[k], (v, j["by"])]})
            if RANK[v] >= RANK[verdicts[k][0]]:
                continue
        verdicts[k] = (v, f"term dict, {j['by']}")
    report = {"folders": ["the term dict"], "rows": len(judged),
              "relations": len(verdicts), "curator": curator,
              "curator_overrides_reading": overridden, "conflicts": conflicts}
    return verdicts, report
