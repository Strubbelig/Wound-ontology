"""Write the review page's two placements (curator, 2026-10-18) into the term dict.

    python -u scripts/apply_review_page_2026_10_18.py [--write]

Review page https://claude.ai/artifact/17qogz8rnhq7XuWL6uA7Q9, read back with
ArtifactData: p-disease-course "suggest", p-compound "suggest". mild.ttl renamed
MILD_120053 and dropped `compound pathological disorder`, so these placements
pointed at labels MILD no longer has. Dry by default; backs up, writes, reads back.
"""
from __future__ import annotations
import shutil, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

BY = "review page (curator, 2026-10-18)"
PLAN = [
    ("Diabetic foot ulcer occurrence", "disorder creating disease course process",
     "MILD_120053 was renamed in mild.ttl; the placement followed the old label"),
    ("metabolic syndrome", "pathological disorder", "compound pathological disorder is no longer in mild.ttl"),
    ("multiple organ dysfunction syndrome", "pathological disorder", "compound pathological disorder is no longer in mild.ttl"),
    ("psychiatric comorbidity", "pathological disorder", "compound pathological disorder is no longer in mild.ttl"),
]


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    gt = Orchestrator().term_mapper._term_mapping
    lower = {}
    for k in gt.records:
        lower.setdefault(k.lower(), set()).add(gt.resolve(k))
    when = datetime.now().isoformat(timespec="seconds")
    plan = []
    for term, cls, why in PLAN:
        hits = lower.get(term.lower(), set())
        if len(hits) != 1:
            raise RuntimeError(f"{term!r}: {len(hits)} records ({sorted(hits)}); not written")
        t = next(iter(hits))
        if gt.is_refused(t, cls):
            raise RuntimeError(f"{t!r} -> {cls!r} is refused in the term dict; resolve first")
        plan.append((t, cls, why))
        print(f"[page] narrower {t!r:42} -> {cls!r}")
    if "--write" not in argv:
        print("[page] dry run; --write to apply"); return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_review_page_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup); print(f"[page] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    for t, cls, why in plan:
        gt.judge(t, cls, curator={"verdict": "narrower", "when": when, "by": BY, "reason": why})
    gt._dirty(); gt.save()
    print(f"[page] gate lists re-exported: {Orchestrator().export_gate_lists()}")
    g2 = Orchestrator().term_mapper._term_mapping
    lost = [(t, c) for t, c, _ in plan
            if (g2.peek(g2.resolve(t), c).get("curator") or {}).get("verdict") != "narrower"]
    if lost:
        raise RuntimeError(f"[page] did not land: {lost}")
    print(f"[page] written and read back: {len(plan)} placements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
