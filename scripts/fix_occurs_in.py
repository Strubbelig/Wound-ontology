"""
Fix occurs_in misuse in the concept store using LLM-based target classification.

Logic:
  - Condition subject + anatomical target   → rename occurs_in → affects
  - Condition subject + non-anatomical      → drop triple
  - Any subject     + non-anatomical target → drop triple  (occurs_in site must be anatomical)
  - Process subject + anatomical target     → leave (correct BFO usage)
  - Uncertain subject + anatomical target   → leave (may be a process)

Steps:
  1. Extract all unique occurs_in targets from condition-subject triples
  2. LLM classifies each as ANATOMICAL / NOT_ANATOMICAL in batches
  3. Print decisions for review
  4. Apply and save to a new timestamped store file

Usage:
    python scripts/fix_occurs_in.py [--store PATH] [--batch 60] [--dry-run]
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openai as openai_sdk

# ── Reuse subject classifier from scan_occurs_in ──────────────────────────────

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

_CONDITION_KEYWORDS = {
    "ulcer", "wound", "injury", "disease", "syndrome",
    "disorder", "abscess", "cellulitis", "osteomyelitis", "gangrene",
    "necrosis", "scar", "fibrosis", "deficiency", "failure",
    "ischemia", "thrombosis", "embolism", "deformity", "contracture",
    "malnutrition", "neuropathy", "retinopathy", "edema", "lymphedema",
    "hematoma", "seroma", "fistula", "eschar",
    "laceration", "trauma", "fracture", "dehiscence", "complication",
}


def _subject_class(name: str) -> str:
    lower = name.strip().lower()
    words = re.findall(r"[a-z]+", lower)
    if words and words[-1] in _PROCESS_KEYWORDS:
        return "process"
    if words and words[-1].endswith("ing"):
        return "process"
    if any(kw in lower for kw in _CONDITION_KEYWORDS):
        return "condition"
    if any(kw in lower for kw in _PROCESS_KEYWORDS):
        return "process"
    return "uncertain"


# ── LLM target classification ─────────────────────────────────────────────────

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


class _TargetResult(BaseModel):
    term: str
    anatomical: bool


class _TargetBatch(BaseModel):
    results: list[_TargetResult]


async def _classify_targets_llm(
    terms: list[str],
    api_key: str,
    model: str,
    batch_size: int,
) -> dict[str, bool]:
    """Return {term: is_anatomical} for every term in the list."""
    client = openai_sdk.AsyncOpenAI(api_key=api_key, base_url=_OPENROUTER_BASE_URL)
    schema = _TargetBatch.model_json_schema()
    results: dict[str, bool] = {}

    for i in range(0, len(terms), batch_size):
        batch = terms[i : i + batch_size]
        term_list = "\n".join(f"- {t}" for t in batch)
        prompt = f"""You are a biomedical ontologist. Classify each term below as ANATOMICAL or NOT_ANATOMICAL.

ANATOMICAL = a physical body structure, tissue, organ, anatomical region, or wound site.
Examples: Foot, Dermis, Sacrum, Lower Limb, Wound Bed, Surgical Site, Fascia, Skin, Bone,
          Subcutaneous Tissue, Plantar Foot, Nasal Region, Cornea, Axilla, Perineum

NOT_ANATOMICAL = everything else: diseases, conditions, patient types, time periods,
countries, institutions, clinical endpoints, populations, psychological concepts.
Examples: Diabetes, Patient, UK, Postoperative Period, Hospital, Chronic Wound,
          People With Diabetes, Bedridden, End Of Life, Type 2 Diabetes Mellitus,
          Venous Leg Ulcer, Post-Thrombotic Syndrome, Diverse Populations

Terms to classify:
{term_list}

Respond with valid JSON only matching this schema exactly:
{json.dumps(schema, indent=2)}"""

        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = _TargetBatch.model_validate_json(raw)
        for r in parsed.results:
            results[r.term] = r.anatomical

        print(f"  Classified {min(i + batch_size, len(terms))}/{len(terms)} targets...", end="\r")

    print()
    return results


# ── Store helpers ─────────────────────────────────────────────────────────────

def _latest_store() -> Path:
    cache = ROOT / "data" / "cache"
    candidates = sorted(cache.glob("concept_store_*.json"))
    if not candidates:
        raise FileNotFoundError(f"No concept_store_*.json in {cache}")
    return candidates[-1]


def _collect_triples(data: dict) -> dict[tuple[str, str], str]:
    """Return {(subject, target): subject_class} for all occurs_in triples."""
    pairs: dict[tuple[str, str], str] = {}
    for record in data.values():
        for entity, attrs in record.get("entities", {}).items():
            cls = _subject_class(entity)
            for attr in attrs:
                if attr.startswith("occurs_in:"):
                    target = attr.split(":", 1)[1].strip()
                    key = (entity, target)
                    # condition > uncertain > process priority
                    existing = pairs.get(key, "process")
                    priority = {"condition": 2, "uncertain": 1, "process": 0}
                    if priority[cls] > priority[existing]:
                        pairs[key] = cls
    return pairs


def _apply(
    data: dict,
    to_convert: set[tuple[str, str]],
    to_drop: set[tuple[str, str]],
) -> tuple[dict, int, int]:
    converted = dropped = 0
    for record in data.values():
        for entity, attrs in list(record.get("entities", {}).items()):
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
    return data, converted, dropped


# ── Main ──────────────────────────────────────────────────────────────────────

def main(store_path: Path, batch_size: int, dry_run: bool) -> None:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY env var not set.")
        sys.exit(1)

    print(f"\nStore: {store_path.name}")
    data = json.loads(store_path.read_text())

    all_pairs = _collect_triples(data)
    condition_pairs  = {p for p, c in all_pairs.items() if c == "condition"}
    uncertain_pairs  = {p for p, c in all_pairs.items() if c == "uncertain"}

    # Unique targets that need LLM classification:
    # - all condition-subject targets (to decide convert vs drop)
    # - all uncertain-subject targets (non-anatomical ones will be dropped)
    targets_to_classify = sorted({
        tgt for (_, tgt) in condition_pairs | uncertain_pairs
    })

    print(f"  Condition-subject triples : {len(condition_pairs)}")
    print(f"  Uncertain-subject triples : {len(uncertain_pairs)}")
    print(f"  Unique targets to classify: {len(targets_to_classify)}")
    print(f"\nClassifying targets via LLM (batch={batch_size})...")

    anatomical: dict[str, bool] = asyncio.run(
        _classify_targets_llm(targets_to_classify, api_key, _DEFAULT_MODEL, batch_size)
    )

    # ── Build fix sets ────────────────────────────────────────────────────────

    to_convert: set[tuple[str, str]] = set()
    to_drop: set[tuple[str, str]] = set()

    for subj, tgt in condition_pairs:
        if anatomical.get(tgt, True):
            to_convert.add((subj, tgt))
        else:
            to_drop.add((subj, tgt))

    for subj, tgt in uncertain_pairs:
        if not anatomical.get(tgt, True):
            to_drop.add((subj, tgt))
        # anatomical target with uncertain subject → leave as occurs_in

    # ── Print decisions ───────────────────────────────────────────────────────

    anat_terms  = sorted(t for t, a in anatomical.items() if a)
    non_anat    = sorted(t for t, a in anatomical.items() if not a)

    print(f"\n{'─'*70}")
    print(f"  ✓ ANATOMICAL ({len(anat_terms)} targets) — condition triples → affects")
    print(f"{'─'*70}")
    for t in anat_terms:
        print(f"    {t}")

    print(f"\n{'─'*70}")
    print(f"  ✗ NOT ANATOMICAL ({len(non_anat)} targets) — all triples → DROP")
    print(f"{'─'*70}")
    for t in non_anat:
        print(f"    {t}")

    print(f"\n{'─'*70}")
    print(f"  Pending: {len(to_convert)} triples → affects  |  {len(to_drop)} triples → drop")
    print(f"{'─'*70}")

    if dry_run:
        print("\n[dry-run] No changes written.")
        return

    ans = input("\n  Apply and save? [y/n] ").strip().lower()
    if ans != "y":
        print("  Aborted.")
        return

    data, converted, dropped = _apply(data, to_convert, to_drop)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = store_path.parent / f"concept_store_{stamp}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n  ✓ {converted} occurs_in → affects")
    print(f"  ✓ {dropped} non-anatomical triples dropped")
    print(f"  Saved: {out_path.name}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--batch", type=int, default=60,
                        help="Targets per LLM call (default: 60)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify and report but do not write")
    args = parser.parse_args()
    main(args.store or _latest_store(), args.batch, args.dry_run)
