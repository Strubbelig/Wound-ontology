"""Turn kept placements that only restate their class into synonyms of it (rule 64).

    python -u scripts/apply_restatements.py [--write]

Reads `data/review/placement_restatement_2026-10-02.json` (the model's
same / narrower / unclear) and `data/review/placement_restatement_read_2026-10-02.txt`,
Claude's reading of every `same` row: one row id per line that is NOT a
restatement after all (kept as a subclass), `#` comments allowed. Every other
`same` row is mapped onto its class (`to`, curator `same_class`, tagged `BY`),
so the term reads as the class from then on and gives no subclass edge.
Backed up first, read back after.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

SRC = ROOT / "data" / "review" / "placement_restatement_2026-10-02.json"
READ = ROOT / "data" / "review" / "placement_restatement_read_2026-10-02.txt"
BY = "restatement check (model + Claude's reading, 2026-10-02)"


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    rows = [r for r in json.loads(SRC.read_text(encoding="utf-8"))["rows"] if r["answer"] == "same"]
    keep = set()
    for line in READ.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            keep.update(line.split())
    unknown = keep - {r["id"] for r in rows}
    if unknown:
        raise SystemExit(f"[restate] ids in the reading file that are not `same` rows: {sorted(unknown)[:10]}")
    todo = [r for r in rows if r["id"] not in keep]
    print(f"[restate] {len(rows):,} `same` rows; {len(keep):,} kept as subclasses after reading; "
          f"{len(todo):,} to map onto their class")
    if "--write" not in argv:
        for r in todo[:40]:
            print(f"[restate]   {r['term']!r} -> {r['class']!r}")
        print("[restate] dry run; --write to apply")
        return 0
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_restatements_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[restate] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    skipped = []
    for r in todo:
        t = gt.resolve(r["term"])
        if gt.is_refused(t, r["class"]):
            skipped.append(t)
            continue
        rec = gt.record(t)
        rec.update({"to": r["class"], "confidence": 1.0, "method": "curator"})
        rec.pop("retired", None)
        gt.judge(t, r["class"], curator={"verdict": "same_class", "when": when, "by": BY,
                                         "reason": f"restates its class: {r.get('reason', '')}"})
    gt._dirty()
    gt.save()
    g2 = Orchestrator().term_mapper._term_mapping
    lost = [r["term"] for r in todo if gt.resolve(r["term"]) not in skipped
            and g2.data.get(g2.resolve(r["term"])) != r["class"]]
    if lost:
        raise RuntimeError(f"[restate] {len(lost)} mapping(s) did not land: {lost[:10]}")
    print(f"[restate] written and read back: {len(todo) - len(skipped):,} mapped; "
          f"{len(skipped)} skipped as refused pairs {skipped[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
