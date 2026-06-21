"""
Scan the concept store for occurs_in misuse.

BFO rule: occurs_in connects OCCURRENT (process) → CONTINUANT (anatomical site).
Errors:
  (A) Subject is a condition/lesion — should use 'affects' instead.
  (B) Target is not an anatomical site — triple should be dropped.

Usage:
    python scripts/scan_occurs_in.py [--store PATH] [--all] [--fix]

Options:
    --store PATH   Path to a concept_store JSON (default: latest in data/cache/)
    --all          Also show triples that look correct
    --fix          Interactive per-cluster review: convert to affects or drop
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ── Process / condition keyword sets ─────────────────────────────────────────

_PROCESS_KEYWORDS = {
    "healing", "assessment", "debridement", "irrigation", "formation",
    "response", "proliferation", "remodeling", "epithelialization",
    "revascularization", "angiogenesis", "phagocytosis", "apoptosis",
    "migration", "signaling", "regulation", "activation", "differentiation",
    "secretion", "synthesis", "production", "perfusion", "oxygenation",
    "monitoring", "evaluation", "measurement", "closure", "repair",
    "cleansing", "reconstruction", "sterilization", "disinfection",
    "transplantation", "implantation", "contraction",
    "coagulation", "hemostasis", "treatment", "therapy",
    "management", "surgery", "procedure", "operation", "biopsy",
    "inflammation", "granulation", "amputation",
}

# Omit "infection", "colonization", "contamination" — these are processes
# when used as standalone subjects (e.g. "Infection occurs_in Wound" is correct).
_CONDITION_KEYWORDS = {
    "ulcer", "wound", "injury", "disease", "syndrome",
    "disorder", "abscess", "cellulitis", "osteomyelitis", "gangrene",
    "necrosis", "scar", "fibrosis", "deficiency", "failure",
    "ischemia", "thrombosis", "embolism", "deformity", "contracture",
    "malnutrition", "neuropathy", "retinopathy", "edema", "lymphedema",
    "hematoma", "seroma", "fistula", "eschar",
    "laceration", "trauma", "fracture", "dehiscence",
    "complication",
}

# Target signals indicating the target is NOT an anatomical site → drop the triple
_NON_ANATOMICAL_SIGNALS = {
    # Patient / population
    "patient", "people", "population", "individual", "subject", "participant",
    "person", "adult", "child", "children", "pediatric", "elderly", "veteran",
    "resident", "survivor",
    # Countries / broad geography
    "uk", "china", "usa", "america", "europe", "asia", "africa", "australia",
    "canada", "germany", "france", "italy", "spain", "japan", "korea",
    # Time / periods
    "period", "year", "month", "day", "week", "date",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    # Institutions / settings
    "university", "hospital", "department", "center", "centre",
    "ward", "unit", "institute", "college", "school",
}


def _is_anatomical_target(target: str) -> bool:
    """Return True if target is plausibly an anatomical structure or site."""
    lower = target.strip().lower()
    # Condition entity → not an anatomical site
    if any(kw in lower for kw in _CONDITION_KEYWORDS):
        return False
    # Non-anatomical signal
    if any(sig in lower for sig in _NON_ANATOMICAL_SIGNALS):
        return False
    return True


# ── Subject classifier ────────────────────────────────────────────────────────

def _classify(name: str) -> tuple[str, str]:
    """Return (category, matched_keyword). category: 'process', 'condition', 'uncertain'."""
    lower = name.strip().lower()
    words = re.findall(r"[a-z]+", lower)

    # Last word being a process noun wins — handles "Wound Healing", "Wound Closure"
    if words and words[-1] in _PROCESS_KEYWORDS:
        return "process", words[-1]

    if words and words[-1].endswith("ing"):
        return "process", words[-1]

    for kw in _CONDITION_KEYWORDS:
        if kw in lower:
            return "condition", kw

    for kw in _PROCESS_KEYWORDS:
        if kw in lower:
            return "process", kw

    return "uncertain", ""


# ── Store helpers ─────────────────────────────────────────────────────────────

def _latest_store() -> Path:
    cache = ROOT / "data" / "cache"
    candidates = sorted(cache.glob("concept_store_*.json"))
    if not candidates:
        raise FileNotFoundError(f"No concept_store_*.json in {cache}")
    return candidates[-1]


def _load_occurs_in(path: Path) -> dict[str, list[tuple[str, str]]]:
    """Return {pmid: [(subject, target), ...]} for all occurs_in attributes."""
    data = json.loads(path.read_text())
    result: dict[str, list[tuple[str, str]]] = {}
    for pmid, record in data.items():
        hits = []
        for entity, attrs in record.get("entities", {}).items():
            for attr in attrs:
                if attr.startswith("occurs_in:"):
                    target = attr.split(":", 1)[1].strip()
                    hits.append((entity, target))
        if hits:
            result[pmid] = hits
    return result


def _apply_fixes(
    store_path: Path,
    to_convert: set[tuple[str, str]],
    to_drop: set[tuple[str, str]],
) -> Path:
    """
    Apply occurs_in → affects renames and drops in-place.
    Saves to a new timestamped file and returns its path.
    """
    data = json.loads(store_path.read_text())
    converted = dropped = 0

    for record in data.values():
        for entity, attrs in record.get("entities", {}).items():
            new_attrs: dict[str, float] = {}
            for attr, conf in attrs.items():
                if attr.startswith("occurs_in:"):
                    target = attr.split(":", 1)[1].strip()
                    pair = (entity, target)
                    if pair in to_drop:
                        dropped += 1
                        continue
                    if pair in to_convert:
                        new_attrs[f"affects: {target}"] = conf
                        converted += 1
                        continue
                new_attrs[attr] = conf
            record["entities"][entity] = new_attrs

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = store_path.parent / f"concept_store_{stamp}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n  ✓ {converted} occurs_in → affects")
    print(f"  ✓ {dropped} non-anatomical triples dropped")
    print(f"  Saved: {out_path.name}")
    return out_path


# ── Interactive prompt ────────────────────────────────────────────────────────

def _ask(msg: str) -> str:
    try:
        v = input(msg).strip().lower()
        if "\x1b" in v:
            return "q"
        return v
    except (KeyboardInterrupt, EOFError):
        print()
        return "q"


# ── Main ──────────────────────────────────────────────────────────────────────

def main(store_path: Path, show_all: bool, fix: bool) -> None:
    print(f"\nStore: {store_path.name}")
    triples_by_pmid = _load_occurs_in(store_path)

    agg: dict[tuple[str, str], set[str]] = defaultdict(set)
    for pmid, hits in triples_by_pmid.items():
        for subj, tgt in hits:
            agg[(subj, tgt)].add(pmid)

    total = len(agg)

    condition_clusters: dict[str, dict[str, list[tuple[str, int]]]] = defaultdict(lambda: defaultdict(list))
    uncertain_by_subj: dict[str, list[tuple[str, int]]] = defaultdict(list)
    ok: list[tuple[str, str, int]] = []

    for (subj, tgt), pmids in sorted(agg.items()):
        cls, kw = _classify(subj)
        entry = (tgt, len(pmids))
        if cls == "condition":
            condition_clusters[kw][subj].append(entry)
        elif cls == "uncertain":
            uncertain_by_subj[subj].append(entry)
        else:
            ok.append((subj, tgt, len(pmids)))

    n_condition = sum(
        sum(len(tgts) for tgts in subjs.values())
        for subjs in condition_clusters.values()
    )

    print(f"\n{'─'*70}")
    print(f"  Total distinct occurs_in triples  : {total}")
    print(f"  ✓ Looks like process (correct)    : {len(ok)}")
    print(f"  ✗ Likely CONDITION → use affects  : {n_condition}")
    print(f"  ? Uncertain                        : {sum(len(v) for v in uncertain_by_subj.values())}")
    print(f"{'─'*70}")

    def cluster_weight(kw):
        return sum(n for subjs in condition_clusters[kw].values() for _, n in subjs)

    # Accumulate fix decisions
    to_convert: set[tuple[str, str]] = set()
    to_drop: set[tuple[str, str]] = set()

    # ── Condition clusters ────────────────────────────────────────────────────

    print(f"\n{'═'*70}")
    print("  ✗ CONDITION subjects — grouped by keyword")
    if fix:
        print("  y = convert cluster to 'affects' (drop non-anatomical targets)")
        print("  n = skip cluster  |  q = quit review")
    print(f"{'═'*70}")

    abort = False
    for kw in sorted(condition_clusters, key=lambda k: -cluster_weight(k)):
        if abort:
            break
        subjs = condition_clusters[kw]
        total_kw = cluster_weight(kw)
        print(f"\n  ── keyword: '{kw}'  ({total_kw} papers, {len(subjs)} subjects) ──")

        for subj in sorted(subjs, key=lambda s: -sum(n for _, n in subjs[s])):
            parts = []
            for tgt, n in sorted(subjs[subj], key=lambda x: -x[1]):
                flag = "" if _is_anatomical_target(tgt) else "  ✗DROP"
                parts.append(f"{tgt} [{n}]{flag}")
            print(f"    {subj:<45s}  →  {'  |  '.join(parts)}")

        if fix:
            ans = _ask(f"\n  Convert '{kw}' cluster? [y/n/q] ")
            if ans == "q":
                abort = True
            elif ans == "y":
                for subj, targets in subjs.items():
                    for tgt, _ in targets:
                        if _is_anatomical_target(tgt):
                            to_convert.add((subj, tgt))
                        else:
                            to_drop.add((subj, tgt))

    # ── Uncertain ─────────────────────────────────────────────────────────────

    if uncertain_by_subj:
        print(f"\n{'═'*70}")
        print("  ? UNCERTAIN — could be process or condition, review manually")
        print(f"{'═'*70}")
        for subj in sorted(uncertain_by_subj, key=lambda s: -sum(n for _, n in uncertain_by_subj[s])):
            parts = []
            for tgt, n in sorted(uncertain_by_subj[subj], key=lambda x: -x[1]):
                flag = "" if _is_anatomical_target(tgt) else "  ✗DROP"
                parts.append(f"{tgt} [{n}]{flag}")
            print(f"    {subj:<45s}  →  {'  |  '.join(parts)}")

        if fix and not abort:
            print()
            ans = _ask("  Fix non-anatomical targets in UNCERTAIN triples too? [y/n] ")
            if ans == "y":
                for subj, targets in uncertain_by_subj.items():
                    for tgt, _ in targets:
                        if not _is_anatomical_target(tgt):
                            to_drop.add((subj, tgt))

    # ── OK (--all only) ───────────────────────────────────────────────────────

    if show_all and ok:
        print(f"\n{'═'*70}")
        print("  ✓ Looks correct (process subject)")
        print(f"{'═'*70}")
        for subj, tgt, n in sorted(ok, key=lambda x: -x[2]):
            print(f"    {subj:<45s}  →  {tgt} [{n}]")

    # ── Apply fixes ───────────────────────────────────────────────────────────

    if fix and (to_convert or to_drop):
        print(f"\n  Pending: {len(to_convert)} triples → affects, {len(to_drop)} triples → drop")
        ans = _ask("  Apply and save? [y/n] ")
        if ans == "y":
            _apply_fixes(store_path, to_convert, to_drop)
    elif fix:
        print("\n  No changes selected.")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--all", dest="show_all", action="store_true")
    parser.add_argument("--fix", action="store_true",
                        help="Interactive per-cluster review with apply")
    args = parser.parse_args()
    store_path = args.store or _latest_store()
    main(store_path, args.show_all, args.fix)
