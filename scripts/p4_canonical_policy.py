"""Hold the existing mapping to the three canonical rules (P4 step 2b).

Rules and their measurements are in `TermMapper.enforce_canonical_policy`:
the ontology's own label wins, an identity claim on a class faces the category
guard, and a blocked name is never a canonical.

Run without --apply for a dry run. The blocked entries are written to
data/review/ as a work item for review_lists: a plural whose singular is
blocklisted is a gap in the list, not a mapping decision.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import pandas as pd
from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
from wound_ontology.orchestrator import Orchestrator


def main(argv: list[str]) -> None:
    dry = "--apply" not in argv
    p = Orchestrator(entrez_email=ENTREZ_EMAIL,
                     allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    print(f"\n=== canonical policy (dry_run={dry}) — {len(p.term_mapper.mapping):,} entries ===")
    rep = p.term_mapper.enforce_canonical_policy(
        label_spellings=p.ontology_label_spellings(),
        blocked=p.blocked_names(),
        accept_mapping=p._category_compatible_mapping(p.ontology_labels()),
        dry_run=dry,
    )
    print({k: v for k, v in rep.items() if not k.endswith("entries")})
    print(f"entries now: {len(p.term_mapper.mapping):,}")

    if rep["blocked_entries"]:
        from wound_ontology.utils.string_utils import smart_title as _title
        freq = p._collect_store_terms_with_freq()          # once, not per row
        df = pd.DataFrame(
            [{"term": t, "blocked canonical": c,
              "mentions on the canonical now": freq.get(_title(c), freq.get(c, 0)),
              "mentions on the term now": freq.get(_title(t), freq.get(t, 0))}
             for t, c in rep["blocked_entries"]]
        ).sort_values("mentions on the canonical now", ascending=False)
        out = ROOT / "data" / "review" / f"blocked_canonicals_{time.strftime('%Y-%m-%d')}.csv"
        if not dry:
            df.to_csv(out, index=False)
            print(f"[policy] {len(df)} entr(ies) pointing at a blocklisted canonical → {out}")
        else:
            print(f"[policy] {len(df)} term(s) would be written to {out.name}")
        print(df.head(15).to_string(index=False))
    if rep["refused_entries"]:
        print("\n[policy] refused as the wrong kind of thing:")
        for t, c, tgt in rep["refused_entries"][:20]:
            print(f"    {t!r} -> {tgt!r} (was {c!r})")


if __name__ == "__main__":
    main(sys.argv)
