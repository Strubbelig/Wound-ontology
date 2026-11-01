"""Apply the curator's answers from the Naming Rulings page to the term dict.

    python scripts/apply_naming_rulings.py <decisions dir> --queue data/review/naming_queue_<date>.json [--write]

Mappings tab:
  same_class  map the term onto the class (or onto the class typed in the
              note), recorded as a curator judgement; terms already mapped onto
              the term follow it, so the mapping stays one hop.
  narrower    a curator judgement `narrower`, no mapping: a subtype candidate.
  different   a curator refusal of that pair, so no build proposes it again.
  unsure      nothing.
  unanswered  refused, on the curator's ruling of 2026-09-28: "all the
              unreviewed mappings are crap".
Adjectives tab: only answered words are reported here; turning a word into a
naming rule is a code change to `utils.normalise` (rules 48-53).

Dry run by default. With --write, the term dict is backed up first, saved
once, and every decision is read back from disk.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

UNANSWERED = ("curator 2026-09-28: every row of the naming review left "
              "unanswered is wrong (\"all the unreviewed mappings are crap\")")


def _load(directory: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(directory.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = doc.get("data", doc)
    return out


def main(argv: list[str]) -> int:
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    write = "--write" in argv
    decisions = _load(Path(argv[1]))
    queue = json.loads(Path(argv[argv.index("--queue") + 1]).read_text(encoding="utf-8"))
    gt = TermMappingAndGate(DataManager(), file_name="term_mapping")
    when = datetime.now().isoformat(timespec="seconds")

    def canonical_of(name: str) -> str:
        name = gt.resolve(name)
        return gt.data.get(name) or name

    plan: list[tuple[str, str, str, str]] = []        # (action, term, canonical, reason)
    tally: Counter = Counter()
    for row in queue["mappings"]:
        d = decisions.get(row["id"])
        term = gt.resolve(row["term"])
        verdict = d["verdict"] if d else "unanswered"
        tally[verdict] += 1
        if verdict == "same_class":
            target = canonical_of((d.get("note") or "").strip() or row["target"])
            plan.append(("map", term, target, "curator 2026-09-28, naming review"
                         + (f": typed {d['note'].strip()!r}" if d.get("note", "").strip() else "")))
        elif verdict == "narrower":
            plan.append(("narrower", term, canonical_of(row["target"]),
                         "curator 2026-09-28, naming review"))
        elif verdict == "different":
            plan.append(("refuse", term, canonical_of(row["target"]),
                         "curator 2026-09-28, naming review"))
        elif verdict == "unanswered":
            plan.append(("refuse", term, canonical_of(row["target"]), UNANSWERED))
    # After the adjective rule, `major SSI` IS `SSI`: a `narrower` row whose
    # term now resolves to a term another row maps as `same_class` is the
    # same concept, and the stripping decision already said so.
    mapped = {term for action, term, *_ in plan if action == "map"}
    dropped = [(t, c) for a, t, c, _ in plan if a == "narrower" and t in mapped]
    plan = [p for p in plan if not (p[0] == "narrower" and p[1] in mapped)]
    for t, c in dropped:
        print(f"[naming]   narrower {t!r} -> {c!r} dropped: the term now resolves to a mapped one")
    adjectives = {r["word"]: decisions[r["id"]] for r in queue["adjectives"] if r["id"] in decisions}

    print(f"[naming] mappings: {dict(tally)}")
    for action, term, target, _ in plan:
        if action != "refuse":
            print(f"[naming]   {action:8} {term!r} -> {target!r}")
    print(f"[naming] {sum(a == 'refuse' for a, *_ in plan)} pair(s) to refuse "
          f"({tally['unanswered']} of them unanswered)")
    print(f"[naming] adjectives answered: {len(adjectives)} of {len(queue['adjectives'])}"
          + (f" -- {sorted(adjectives)}" if adjectives else ""))
    if not write:
        print("[naming] dry run -- nothing written. Pass --write.")
        return 0

    latest = sorted((ROOT / "data" / "cache").glob("term_mapping_*.json"))[-1]
    backup = ROOT / "data" / "backup" / f"term_mapping_before_naming_rulings_{date.today()}.json"
    shutil.copy2(latest, backup)
    print(f"[naming] backed up {latest.name} -> {backup.name}")

    followed = 0
    # A row refused earlier because it was left unanswered, and answered now:
    # the new answer replaces that refusal rather than sitting beside it.
    lifted = 0
    for action, term, target, _ in plan:
        j = gt.peek(term, target)
        if (j.get("curator") or {}).get("reason") == UNANSWERED:
            gt.judgement(term, target).pop("refused", None)
            gt.judgement(term, target).pop("curator", None)
            lifted += 1
    for row in queue["mappings"]:
        d = decisions.get(row["id"])
        if d and d["verdict"] == "unsure":
            term, target = gt.resolve(row["term"]), canonical_of(row["target"])
            if (gt.peek(term, target).get("curator") or {}).get("reason") == UNANSWERED:
                gt.judgement(term, target).pop("refused", None)
                gt.judgement(term, target).pop("curator", None)
                lifted += 1
    print(f"[naming] {lifted} earlier 'unanswered' refusal(s) replaced by the answer now given")
    for action, term, target, reason in plan:
        if action == "map":
            gt.judgement(term, target).pop("refused", None)
            gt.judge(term, target, curator={"verdict": "same_class", "reason": reason, "when": when})
            rec = gt.record(term)
            rec.update({"to": target, "confidence": 1.0, "method": "curator"})
            rec.pop("retired", None)
            # Whatever was mapped onto the term follows it: one hop, no chain.
            for other, r in gt.records.items():
                if r.get("to") == term and other != term:
                    r["to"] = target
                    followed += 1
        elif action == "narrower":
            gt.judge(term, target, curator={"verdict": "narrower", "reason": reason, "when": when})
        else:
            gt.judge(term, target,
                     refused={"cause": "curator", "reason": reason, "by": "curator",
                              "when": when})
            rec = gt.record(term)
            if rec.get("to") == target:
                rec["to"] = None
    gt._dirty()
    gt.save()

    check = TermMappingAndGate(DataManager(), file_name="term_mapping")
    wrong = []
    for action, term, target, _ in plan:
        cur = (check.peek(term, target).get("curator") or {}).get("verdict")
        want = {"map": "same_class", "narrower": "narrower", "refuse": "refused"}[action]
        if cur != want or (action == "map" and check.data.get(term) != target):
            wrong.append((action, term, target, cur))
    if wrong:
        raise RuntimeError(f"[naming] {len(wrong)} decision(s) did not read back: {wrong[:5]}")
    print(f"[naming] written and read back: {len(plan)} decision(s); "
          f"{followed} mapping(s) re-pointed to follow a mapped term.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
