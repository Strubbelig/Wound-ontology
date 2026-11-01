"""The review page's category and scope answers (curator, 2026-10-18), into the term dict.

    python -u scripts/apply_category_page_2026_10_18.py DECISIONS.json [--write]

DECISIONS.json is {"terms": {term: "cat:<category>" | "out" | "split" ...}} as read
back from https://claude.ai/artifact/17qogz8rnhq7XuWL6uA7Q9 with ArtifactData.
A BFO/MILD category name gets no ruling (it IS that category). A term that is a
WONT/MILD class keeps the ontology's category; where the answer differs it is
reported, not written. Dry by default; backs up, writes, re-exports, reads back.
"""
from __future__ import annotations
import json, shutil, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
BY = "review page (curator, 2026-10-18)"


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.store.concept_store import declared_category
    from wound_ontology.fca.concept_lattice import ConceptLattice
    from wound_ontology.mappers.term_mapping_and_gate import TERM_RULING
    dec = json.loads(Path(argv[1]).read_text(encoding="utf-8"))["terms"]
    p = Orchestrator(); gt = p.term_mapper._term_mapping
    low = {}
    for k in gt.records:
        low.setdefault(k.lower(), []).append(k)
    cat_plan, out_plan, skipped, conflict = [], [], [], []
    for term, v in sorted(dec.items()):
        recs = low.get(term.lower(), [])
        if declared_category(term):
            skipped.append((term, "is a BFO/MILD category itself")); continue
        if not recs:
            skipped.append((term, "no record")); continue
        if v == "out":
            out_plan += recs; continue
        if not v.startswith("cat:"):
            skipped.append((term, f"answer {v!r} is not a category")); continue
        cat = v[4:]
        known = ConceptLattice.category_of_known_class(term)
        if known and known != cat:
            conflict.append((term, cat, known)); continue
        cat_plan += [(k, cat) for k in recs]
    print(f"[cat] {len(cat_plan)} category ruling(s), {len(out_plan)} out; skipped {skipped}")
    print(f"[cat] answer differs from the ontology's own category (ontology kept, not written): {conflict}")
    if "--write" not in argv:
        print("[cat] dry run; --write to apply"); return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_category_page_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup); print(f"[cat] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    for k, cat in cat_plan:
        gt.set_category(k, cat, source=TERM_RULING, note=BY)
    for k in out_plan:
        gt.gate(k, curator={"verdict": "out", "when": when, "by": BY, "reason": "review page: out of scope"})
    gt._dirty(); gt.save()
    g2 = Orchestrator().term_mapper._term_mapping
    # a category belongs to the term, not to each spelling: read it back by name
    c2 = {k.lower(): v for k, v in g2.categories().items()}
    got = lambda k: c2.get(k.lower()) or c2.get(str(g2.resolve(k)).lower()) or {}
    lost = [(k, c) for k, c in cat_plan if got(k).get("verdict") != c]
    lost += [(k, "out") for k in out_plan if g2.effective_gate_verdict(k)[0] != "out"]
    if lost:
        raise RuntimeError(f"[cat] did not land: {lost}")
    print(f"[cat] written and read back: {len(cat_plan)} categories, {len(out_plan)} out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
