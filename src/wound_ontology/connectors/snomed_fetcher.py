"""Fetch wound-related SNOMED CT concepts from the UMLS UTS API.

Performs a BFS expansion from wound-domain seed terms, stopping semantically
when body-site precoordination is detected rather than at a fixed depth.

Stopping logic (applied during BFS before enqueueing each child)
----------------------------------------------------------------
Rule 1 — Laterality: "of left / right / bilateral" → discard.
Rule 2 — Precoordination of immediate parent: "Laceration of trunk" when parent
          is "Laceration" → discard (body-site narrowing is instance-level).
Rule 3 — Global precoordination (post-hoc): any "X of Y" where X exists in the
          collected set is removed as a safety net.

Requirements: UMLS_API_KEY in .env  (https://uts.nlm.nih.gov/uts/signup-login)
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from collections import deque
from pathlib import Path

import requests

# ── Domain constants ──────────────────────────────────────────────────────────

SEED_TERMS: list[str] = [
    "wound", "chronic wound", "acute wound", "complex wound",
    "open wound", "closed wound", "penetrating wound",
    "ulcer", "pressure ulcer", "pressure injury", "diabetic foot ulcer",
    "venous leg ulcer", "arterial ulcer", "neuropathic ulcer", "foot ulcer",
    "burn", "burn injury", "thermal burn", "chemical burn",
    "electrical burn", "radiation burn", "scald",
    "laceration", "abrasion", "contusion", "avulsion",
    "puncture wound", "crush injury", "degloving",
    "surgical wound", "incision and drainage", "wound dehiscence",
    "anastomotic leak", "surgical site infection",
    "cellulitis", "wound infection", "necrotizing fasciitis",
    "osteomyelitis", "abscess", "gangrene",
    "wound healing", "granulation tissue", "eschar", "slough",
    "biofilm", "scar", "keloid", "hypertrophic scar",
    "wound contraction", "fibrosis",
    "debridement", "skin graft", "flap", "wound dressing",
    "negative pressure wound therapy", "hyperbaric oxygen", "wound closure",
    "fistula", "sinus tract", "seroma", "hematoma",
    "wound complication", "delayed wound healing",
]

_WOUND_KW: frozenset[str] = frozenset({
    "wound", "ulcer", "burn", "laceration", "abrasion", "contusion",
    "avulsion", "puncture", "dehiscence", "eschar", "slough", "granulat",
    "biofilm", "scar", "keloid", "debrid", "dressing", "skin graft",
    "cellulitis", "infect", "necrosis", "necrotizing", "abscess", "gangrene",
    "heal", "fistula", "seroma", "hematoma", "integumentary", "skin incision",
    "blister", "vesicle", "maceration", "pressure injur", "pressure ulcer",
    "surgical site", "flap", "wound closure", "negative pressure", "drainage",
})

# SNOMED codes whose BFS subtrees are too broad — non-wound descendants pruned
_BROAD_SEED_CODES: frozenset[str] = frozenset({
    "34896006",  # Incision — seeds entire surgical-incision taxonomy
})

_LATERALITY_RE = re.compile(r"\bof\s+(left|right|bilateral)\b", re.IGNORECASE)

MAX_DEPTH_SAFETY = 8   # runaway guard; semantic rules fire first
PAGE_SIZE        = 100
DELAY            = 0.07   # ~14 req/s (UMLS rate limit: 20/s)
BASE_URL         = "https://uts-ws.nlm.nih.gov/rest"
VERSION          = "current"
SAB              = "SNOMEDCT_US"


# ── Semantic filter helpers (pure, no network) ────────────────────────────────

def normalize(name: str) -> str:
    """Strip SNOMED qualifiers: (disorder)/(morphology) suffixes and ' - category'."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    name = re.sub(r"\s+-\s+[\w][\w-]*$", "", name)
    return name.lower().strip()


def is_laterality(name: str) -> bool:
    return bool(_LATERALITY_RE.search(name))


def is_precoord_of_parent(child_name: str, parent_name: str) -> bool:
    """True when child is the parent narrowed to a body site."""
    cn = normalize(child_name)
    pn = normalize(parent_name)
    if cn.startswith(pn + " of ") or cn.startswith(pn + "s of "):
        return True
    if cn.startswith(pn + " with ") and " of " in cn[len(pn) + 5:]:
        return True
    return False


def is_wound_relevant(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in _WOUND_KW)


def global_precoord_filter(concepts: list[dict]) -> list[dict]:
    """Remove 'X of Y' concepts where X already exists in the set (post-hoc safety net)."""
    names = {normalize(c["preferred_name"]) for c in concepts}
    kept, removed = [], 0
    for c in concepts:
        cn = normalize(c["preferred_name"])
        m  = re.match(r"^(.+?)\s+of\s+\S", cn)
        if m:
            before_of = m.group(1).strip()
            base      = re.sub(r"\s+with\b.*$", "", before_of).strip()
            if before_of in names or (base != before_of and base in names):
                removed += 1
                continue
        kept.append(c)
    print(f"  Global precoord filter removed {removed} concepts.")
    return kept


# ── SnomedFetcher ─────────────────────────────────────────────────────────────

class SnomedFetcher:
    """Fetches wound-related SNOMED CT concepts from the UMLS UTS API.

    Outputs (in out_dir):
      snomed_wound_concepts.json       — final concept list
      snomed_wound_concepts.csv        — same as TSV for spreadsheet use
      snomed_wound_concepts_cache.json — resumable BFS cache

    Usage:
        fetcher = SnomedFetcher(api_key, out_dir)
        concepts = fetcher.fetch()           # full BFS fetch
        concepts = fetcher.prune()           # improve existing output (no API)
        concepts = fetcher.rebuild_cache()   # re-filter from cache (no API)
    """

    def __init__(self, api_key: str, out_dir: Path) -> None:
        if not api_key:
            raise ValueError(
                "UMLS API key required — add UMLS_API_KEY to .env "
                "(https://uts.nlm.nih.gov/uts/signup-login)"
            )
        self.api_key  = api_key
        self.out_dir  = Path(out_dir)
        self._json    = self.out_dir / "snomed_wound_concepts.json"
        self._csv     = self.out_dir / "snomed_wound_concepts.csv"
        self._cache   = self.out_dir / "snomed_wound_concepts_cache.json"

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict) -> dict | None:
        params["apiKey"] = self.api_key
        try:
            r = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=30)
            if r.status_code == 200:
                return r.json().get("result", {})
            if r.status_code == 404:
                return None
            print(f"  HTTP {r.status_code} — {endpoint}", file=sys.stderr)
        except Exception as exc:
            print(f"  Request error: {exc}", file=sys.stderr)
        return None

    def _paginated(self, endpoint: str, params: dict) -> list[dict]:
        params["pageSize"] = PAGE_SIZE
        items: list[dict] = []
        page = 1
        while True:
            params["pageNumber"] = page
            result = self._get(endpoint, dict(params))
            if result is None:
                break
            batch = result if isinstance(result, list) else result.get("results", [])
            if not batch:
                break
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            page += 1
            time.sleep(DELAY)
        return items

    def _search(self, term: str) -> list[dict]:
        items = self._paginated(
            f"/search/{VERSION}",
            {"string": term, "sabs": SAB, "returnIdType": "sourceUi"},
        )
        time.sleep(DELAY)
        return items

    def _concept_detail(self, code: str) -> dict:
        result = self._get(f"/content/{VERSION}/source/{SAB}/{code}", {})
        time.sleep(DELAY)
        if not result:
            return {}
        cui = result.get("concept", "").rstrip("/").split("/")[-1]
        return {
            "snomed_code":    code,
            "preferred_name": result.get("name", ""),
            "cui":            cui,
            "semantic_types": [st.get("name", "") for st in result.get("semanticTypes", [])],
        }

    def _children(self, code: str) -> list[tuple[str, str]]:
        items = self._paginated(
            f"/content/{VERSION}/source/{SAB}/{code}/children", {}
        )
        time.sleep(DELAY)
        return [(item["ui"], item.get("name", ""))
                for item in items if item.get("ui") and item["ui"] != "NONE"]

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict]:
        if self._cache.exists():
            return json.loads(self._cache.read_text(encoding="utf-8"))
        return {}

    def _save_cache(self, concepts: dict[str, dict]) -> None:
        self._cache.write_text(
            json.dumps(concepts, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── Output ────────────────────────────────────────────────────────────────

    def _write(self, records: list[dict]) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        fields = ["snomed_code", "preferred_name", "parent_code",
                  "depth", "cui", "semantic_types"]
        with open(self._csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in records:
                w.writerow({**r, "semantic_types": "; ".join(r.get("semantic_types", []))})
        self._json.write_text(
            json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  Saved {len(records)} concepts → {self._json.name}")

    # ── Broad-seed subtree pruning ────────────────────────────────────────────

    def _prune_broad_subtrees(
        self,
        records: list[dict],
        cache: dict[str, dict],
    ) -> tuple[list[dict], int]:
        by_code: dict[str, dict] = {c["snomed_code"]: c for c in records}
        children_of: dict[str, list[str]] = {}
        for code, c in cache.items():
            pc = c.get("parent_code", "")
            if pc:
                children_of.setdefault(pc, []).append(code)

        removed: set[str] = set()
        for seed_code in _BROAD_SEED_CODES:
            queue: deque[str] = deque(children_of.get(seed_code, []))
            seen:  set[str]   = set()
            while queue:
                code = queue.popleft()
                if code in seen:
                    continue
                seen.add(code)
                if code in by_code and not is_wound_relevant(by_code[code].get("preferred_name", "")):
                    removed.add(code)
                queue.extend(children_of.get(code, []))

        return [c for c in records if c["snomed_code"] not in removed], len(removed)

    def _cascade_orphan_removal(
        self,
        records: list[dict],
        surviving: set[str],
    ) -> tuple[list[dict], int]:
        removed: set[str] = set()
        while True:
            round_n = 0
            for c in records:
                code = c["snomed_code"]
                if code in removed:
                    continue
                pc = c.get("parent_code", "")
                if (pc and pc not in surviving
                        and not is_wound_relevant(c.get("preferred_name", ""))):
                    removed.add(code)
                    surviving.discard(code)
                    round_n += 1
            if round_n == 0:
                break
        return [c for c in records if c["snomed_code"] not in removed], len(removed)

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch(self) -> list[dict]:
        """Full BFS fetch from UMLS API. Resumes from cache if present.

        Returns the final filtered concept list and writes JSON/CSV to out_dir.
        """
        self.out_dir.mkdir(parents=True, exist_ok=True)
        all_concepts: dict[str, dict] = self._load_cache()
        visited: set[str] = set(all_concepts)
        if visited:
            print(f"  Resuming — {len(visited)} concepts already in cache.")

        # Step 1: seed search
        seed_codes: set[str] = set()
        print(f"[1/3] Seed search — {len(SEED_TERMS)} terms...")
        for i, term in enumerate(SEED_TERMS, 1):
            print(f"  ({i}/{len(SEED_TERMS)}) {term!r}", end=" ", flush=True)
            hits = self._search(term)
            new  = [h["ui"] for h in hits if h.get("ui") and h["ui"] != "NONE"]
            seed_codes.update(new)
            print(f"→ {len(new)} hits  (total: {len(seed_codes)})")

        # Step 2: BFS with semantic stopping
        queue: deque[tuple[str, int, str, str]] = deque(
            (code, 0, "", "") for code in seed_codes if code not in visited
        )
        skipped_lat = skipped_pre = processed = 0
        print("[2/3] BFS traversal...")
        while queue:
            code, depth, parent_code, parent_name = queue.popleft()
            if code in visited:
                continue
            visited.add(code)

            detail = self._concept_detail(code)
            if not detail.get("preferred_name"):
                detail["snomed_code"] = code
            concept_name = detail.get("preferred_name", "")
            detail["parent_code"] = parent_code
            detail["depth"]       = depth
            all_concepts[code]    = detail
            processed += 1

            if processed % 50 == 0:
                print(f"  processed={processed}  queue={len(queue)}  "
                      f"found={len(all_concepts)}  "
                      f"skipped(lat={skipped_lat} pre={skipped_pre})", flush=True)
                self._save_cache(all_concepts)

            if depth >= MAX_DEPTH_SAFETY:
                continue

            for child_code, child_name in self._children(code):
                if child_code in visited:
                    continue
                if is_laterality(child_name):
                    visited.add(child_code)
                    skipped_lat += 1
                    continue
                if is_precoord_of_parent(child_name, concept_name):
                    visited.add(child_code)
                    skipped_pre += 1
                    continue
                queue.append((child_code, depth + 1, code, concept_name))

        self._save_cache(all_concepts)
        print(f"\n  BFS done: {len(all_concepts)} concepts collected. "
              f"Skipped: {skipped_lat} laterality, {skipped_pre} precoordination.")

        # Step 3: post-hoc filters
        print("[3/3] Post-hoc filters...")
        records = [c for c in all_concepts.values() if c.get("preferred_name")]
        records = global_precoord_filter(records)
        records = [r for r in records if not is_laterality(r.get("preferred_name", ""))]
        records.sort(key=lambda r: r.get("preferred_name", "").lower())
        print(f"  Final concept count: {len(records)}")
        self._write(records)
        return records

    def prune(self) -> list[dict]:
        """Improve existing output without re-querying the API.

        Three passes: broad-seed subtree pruning, global precoord filter,
        cascade orphan removal. Requires both JSON output and cache to exist.
        """
        if not self._json.exists():
            raise FileNotFoundError(f"Output not found: {self._json}")
        if not self._cache.exists():
            raise FileNotFoundError(f"Cache not found: {self._cache}")

        data  = json.loads(self._json.read_text(encoding="utf-8"))
        cache = json.loads(self._cache.read_text(encoding="utf-8"))
        print(f"Pruning {len(data)} concepts...")

        records, n1 = self._prune_broad_subtrees(data, cache)
        print(f"  Step 1 — broad-seed subtree prune: {n1} removed.")

        records = global_precoord_filter(records)
        records, n3 = self._cascade_orphan_removal(
            records, {c["snomed_code"] for c in records}
        )
        print(f"  Step 3 — cascade orphan removal: {n3} removed.")

        records = [r for r in records if not is_laterality(r.get("preferred_name", ""))]
        records.sort(key=lambda r: r.get("preferred_name", "").lower())
        print(f"  Final count: {len(records)}  (removed {len(data) - len(records)} of {len(data)})")
        self._write(records)
        return records

    def rebuild_cache(self) -> list[dict]:
        """Rebuild the final concept set from cache using all current filters.

        Use after changing SEED_TERMS, _WOUND_KW, or filter logic to avoid
        a full re-fetch. Requires the cache to exist.
        """
        if not self._cache.exists():
            raise FileNotFoundError(f"Cache not found: {self._cache}")

        cache = json.loads(self._cache.read_text(encoding="utf-8"))
        print(f"Rebuilding from {len(cache)} cache entries...")

        records = [c for c in cache.values() if c.get("preferred_name")]
        records = [r for r in records if not is_laterality(r.get("preferred_name", ""))]
        records = global_precoord_filter(records)
        print(f"  After base filters: {len(records)}")

        records, n1 = self._prune_broad_subtrees(records, cache)
        print(f"  Step 1 — broad-seed subtree prune: {n1} removed.")

        records = global_precoord_filter(records)
        records, n3 = self._cascade_orphan_removal(
            records, {c["snomed_code"] for c in records}
        )
        print(f"  Step 3 — cascade: {n3} removed.")

        records = [r for r in records if not is_laterality(r.get("preferred_name", ""))]
        records.sort(key=lambda r: r.get("preferred_name", "").lower())
        print(f"  Final count: {len(records)}")
        self._write(records)
        return records
