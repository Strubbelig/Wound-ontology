"""Build the data file the mapping review UI reads.

One record per FAMILY — the terms that collapse onto one canonical — carrying
everything needed to decide it without opening anything else: both model
verdicts, the rule's suggestion and why, the flags, and, where the canonical is
a curated class, that class's own definition. The definition is the point: an
anchor mapping is a permanent identity claim on an existing class, and the label
is what misled the embedder in the first place.

Families already decided carry the verdict, so the UI shows the review's real
remaining length instead of asking again.

    python scripts/review_ui_data.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import pandas as pd                                          # noqa: E402
from wound_ontology.orchestrator import Orchestrator         # noqa: E402

SECTION = {"1 the ontology already relates these": 1,
           "2 onto an existing class": 2,
           "3 store term onto store term": 3}


def _clean(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def main() -> int:
    fam_path = sorted((ROOT / "data" / "review").glob("mapping_families_*.csv"))[-1]
    row_path = sorted((ROOT / "data" / "review").glob("mapping_review_*.csv"))[-1]
    fam = pd.read_csv(fam_path).fillna("")
    rows = pd.read_csv(row_path).fillna("")
    print(f"[ui] {fam_path.name}: {len(fam):,} families; {row_path.name}: {len(rows):,} rows")

    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    defs = p.ontology_definitions()
    onto_cat = p.ontology_categories()

    # the row sheet carries the per-term section and both verdicts
    by_canonical: dict[str, list[dict]] = {}
    for _, r in rows.iterrows():
        by_canonical.setdefault(str(r["canonical"]), []).append(r)

    out = []
    for i, (_, f) in enumerate(fam.iterrows()):
        canonical = str(f["canonical"])
        terms = [t.strip() for t in str(f["terms"]).split(" ; ") if t.strip()]
        members = by_canonical.get(canonical, [])
        section = SECTION.get(_clean(members[0]["section"]) if members else "", 3)

        # per-term evidence, and any verdict already recorded
        tm = []
        for t in terms:
            j = gt.peek(t, canonical)
            row = next((r for r in members if str(r["term"]) == t), None)
            tm.append({
                "t": t,
                "p1": (j.get("pass1") or {}).get("verdict", ""),
                "p2": (j.get("pass2") or {}).get("verdict", ""),
                "r1": (j.get("pass1") or {}).get("reason", "")[:180],
                "r2": (j.get("pass2") or {}).get("reason", "")[:180],
                "cv": (j.get("curator") or {}).get("verdict", ""),
                "mn": int(row["term mentions"]) if row is not None and str(row["term mentions"]).strip() else 0,
            })
        decided = [m["cv"] for m in tm if m["cv"]]
        out.append({
            "i": i,
            "c": canonical,
            "n": int(f["n"]),
            "m": int(f["mentions"]),
            "s": section,
            "v": _clean(f["variation"]),
            "dis": int(f["passes disagree"] or 0),
            "sug": _clean(f["suggested"]),
            "why": _clean(f["why"]),
            "llm": _clean(f["LLM reason"])[:200],
            "blk": _clean(f["blocked canonical"]) == "yes",
            "alt": _clean(f["canonical is an alt term of"]),
            "proc": _clean(f["process"]),
            "ax": _clean(members[0]["ontology axiom"]) if members else "",
            "bfo": _clean(members[0]["BFO category side"]) if members else "",
            "def": (defs.get(canonical.strip()) or "")[:400],
            "cat": onto_cat.get(canonical.strip()) or "",
            "terms": tm,
            "done": decided[0] if decided else "",
        })

    payload = {
        "built": date.today().isoformat(),
        "source": fam_path.name,
        "live_entries": len(gt.data),
        "families": out,
    }
    dest = ROOT / "data" / "review" / f"review_ui_{date.today()}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    done = sum(1 for f in out if f["done"])
    print(f"[ui] {len(out):,} families, {done:,} already decided, "
          f"{sum(1 for f in out if f['s'] == 2):,} onto an existing class, "
          f"{sum(1 for f in out if f['dis']):,} with a pass disagreement, "
          f"{sum(1 for f in out if f['def']):,} carrying a class definition")
    print(f"[ui] wrote {dest.relative_to(ROOT)}  ({dest.stat().st_size/1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
