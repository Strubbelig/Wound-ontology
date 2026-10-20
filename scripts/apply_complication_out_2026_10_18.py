"""Curator, 2026-10-18: complication is an epistemic label, not a class.

    python -u scripts/apply_complication_out_2026_10_18.py [--write]

"was eine Komplikation ist und was nicht, ist ein epistemisches Label, das
angehängt wird. Axiomatisch gesehen ist nämlich sonst alles eine Komplikation."
WONT's four complication classes go by the curator's own edit; this puts every
store name built on the word out of scope, so the WONT addition does not mint
them as classes. Dry by default; backs up, writes, re-exports, reads back.
"""
from __future__ import annotations
import re, shutil, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

BY = "curator, chat 2026-10-18"
WHY = "complication is an epistemic label attached afterwards, not a class (curator 2026-10-18)"
WORD = re.compile(r"\bcomplications?\b", re.IGNORECASE)


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(); gt = p.term_mapper._term_mapping
    names = set()
    for _, ents in p.store.view():
        names |= {n for n in ents if WORD.search(n)}
    recs = sorted({k for k in gt.records for n in names if k.lower() == n.lower()})
    missing = sorted(n for n in names if not any(k.lower() == n.lower() for k in recs))
    print(f"[complication] {len(names)} in-scope name(s), {len(recs)} record(s); without a record: {missing}")
    if missing:
        raise RuntimeError("names without a record cannot be ruled; nothing written")
    if "--write" not in argv:
        print("[complication] dry run; --write to apply"); return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_complication_out_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup); print(f"[complication] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    for k in recs:
        gt.gate(k, curator={"verdict": "out", "when": when, "by": BY, "reason": WHY})
    gt._dirty(); gt.save()
    print(f"[complication] gate lists re-exported: {p.export_gate_lists()}")
    p2 = Orchestrator(); g2 = p2.term_mapper._term_mapping
    lost = [k for k in recs if g2.effective_gate_verdict(k)[0] != "out"]
    left = sorted({n for _, ents in p2.store.view() for n in ents if WORD.search(n)})
    if lost or left:
        raise RuntimeError(f"[complication] did not land: {lost}; still in the view: {left[:20]}")
    print(f"[complication] written and read back: {len(recs)} record(s) out; none left in the view")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
