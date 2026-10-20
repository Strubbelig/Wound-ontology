"""Curator, 2026-10-18: earlier burn mappings that contradict rule 79 are corrected.

    python -u scripts/apply_burn_synonyms_2026_10_18.py [--write]

Asked in chat ("Ja, so korrigieren"): a burn wound is a burn injury, not the same
class; a scald is a thermal wound, not a burn; WONT's label is the name.
Dry by default; backs up, writes, re-exports the gate lists, reads back.
"""
from __future__ import annotations
import shutil, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

BY = "curator, chat 2026-10-18 (rule 79)"
NOT_SAME = "a burn wound is a burn injury, not the same class (rule 79)"
REFUSE = [
    ("Burn injury", "burn wound", NOT_SAME),
    ("burn wound", "Burn injury", NOT_SAME),
    ("acute burn wound", "Burn injury", NOT_SAME),
    ("acute burn injury", "acute burn wound", NOT_SAME),
    ("second-degree burn injury", "Second-degree burn wound", NOT_SAME),
    ("burn injury treatment", "burn treatment", "treatment of a burn injury is not the burn wound's treatment (rule 79)"),
    ("partial-thickness scald", "Second-degree burn wound", "a scald is a thermal wound, not a burn (rule 79)"),
    ("Second-degree burn wound", "2nd degree burn", "WONT's label is the name; the spelling maps onto it"),
]
SAME = [("2nd degree burn", "Second-degree burn wound")]


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(); gt = p.term_mapper._term_mapping
    for t, c, _ in REFUSE + [(a, b, "") for a, b in SAME]:
        if t not in gt.records:
            raise RuntimeError(f"{t!r} has no record; nothing written")
        print(f"[burn] {'same  ' if (t, c) in SAME else 'refuse'} {t!r:30} -> {c!r:28} now -> {gt.records[t].get('to')!r}")
    if "--write" not in argv:
        print("[burn] dry run; --write to apply"); return 0
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_burn_synonyms_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup); print(f"[burn] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    for t, c, why in REFUSE:
        gt.refuse(t, c, reason=why, by=BY)
    for t, c in SAME:
        rec = gt.record(t)
        rec.update({"to": c, "confidence": 1.0, "method": "curator"}); rec.pop("retired", None)
        gt.judge(t, c, curator={"verdict": "same_class", "when": when, "by": BY,
                                "reason": "WONT's label is the name (rule 36)"})
    gt._dirty(); gt.save()
    print(f"[burn] gate lists re-exported: {p.export_gate_lists()}")
    g2 = Orchestrator().term_mapper._term_mapping
    lost = [(t, c) for t, c, _ in REFUSE if not (g2.peek(t, c).get("refused")) or g2.records[t].get("to") == c]
    lost += [(t, c) for t, c in SAME if g2.records[t].get("to") != c]
    if lost:
        raise RuntimeError(f"[burn] did not land: {lost}")
    chains = [(a, b, g2.data[b]) for a, b in g2.data.items() if b in g2.data and g2.data[b] != b]
    print(f"[burn] written and read back: {len(REFUSE)} refused, {len(SAME)} set; chains left: {chains}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
