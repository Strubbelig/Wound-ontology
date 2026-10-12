"""A term the curated ontology has a class for is in scope (rule 26). Idempotent.

The scope pass of 2026-09-28 answered `out` for fifteen names that WONT or
MILD assert a class for -- `Planimetry`, `Vascular assessment process`,
`herpes zoster`, `inflamed`, `ischemic`, `therapeutic role` -- and for the
category names. The curator authored those classes; a class is the curator's
answer to "does the ontology carry this?". This writes that answer where the
gate reads it, as a `curator` verdict `by: "ontology label"`, on every term
whose folded spelling is a curated label and whose own verdict is not already
`in`. Nothing else is touched.

    python scripts/gate_ontology_labels.py [--write]
"""
from __future__ import annotations

import shutil
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str]) -> int:
    from rdflib.namespace import RDFS

    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.hierarchies.curated_seed import default_curated_sources
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    from wound_ontology.utils.label_match import fold
    from wound_ontology.utils.rdf_io import parse_graph

    write = "--write" in argv
    labels: dict[str, str] = {}
    sources, _ = default_curated_sources()
    for src in sources:
        for _, _, o in parse_graph(src).triples((None, RDFS.label, None)):
            if str(o).strip():
                labels.setdefault(fold(str(o).strip()), str(o).strip())

    gt = TermMappingAndGate(DataManager(), file_name="term_mapping")
    todo = []
    for term in list(gt.records):
        if gt.is_alias(term) or fold(term) not in labels:
            continue
        verdict, source = gt.own_gate_verdict(term)
        if verdict == "out":
            todo.append((term, source, labels[fold(term)]))
    print(f"[labels] {len(labels):,} curated labels; {len(todo)} term(s) naming one "
          f"are out of scope: {[t for t, *_ in todo]}")
    if not write:
        print("[labels] dry run -- nothing written. Pass --write.")
        return 0
    latest = sorted((ROOT / "data" / "cache").glob("term_mapping_*.json"))[-1]
    shutil.copy2(latest, ROOT / "data" / "backup" / f"term_mapping_before_label_scope_{date.today()}.json")
    when = datetime.now().isoformat(timespec="seconds")
    for term, source, label in todo:
        gt.gate(term, curator={"verdict": "in", "by": "ontology label",
                               "reason": f"WONT/MILD assert a class labelled {label!r} "
                                         f"(rule 26); overrides {source} 'out'",
                               "when": when})
    gt.save()
    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    wrong = [t for t, *_ in todo if check.own_gate_verdict(t) != ("in", "curator")]
    if wrong:
        raise RuntimeError(f"[labels] did not read back: {wrong}")
    print(f"[labels] written and read back: {len(todo)} term(s) now in scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
