"""
Move specific SapBERT clusters from METHODOLOGY_BLOCKLIST to WHITELIST.

Identifies clusters by their comment-header label in blocklist.py (written by
cluster_blocklist_sapbert.py), extracts all member terms, appends them to
whitelist.py, and removes them from blocklist.py.

Usage:
    python scripts/promote_clusters_to_whitelist.py [--dry-run]
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Target cluster labels (partial match is enough) ──────────────────────────
TARGET_LABELS: list[str] = [
    "bilayer hydrogel dressing · superabsorbent dressing · polymeric membrane dressing",
    "diabetes-related foot ulcer · diabetes foot ulcer · complex diabetic foot ulcer",
    "wound surface reduction · wound area reduction · wound retraction",
    "scarring wound · incomplete healing · scar healing",
    "wound stratification system · sinbad grading system · wound severity score",
]

BL_PATH = ROOT / "config" / "blocklist.py"
WL_PATH = ROOT / "config" / "whitelist.py"


def extract_and_strip_clusters(src: str) -> tuple[set[str], str]:
    """
    Parse METHODOLOGY_BLOCKLIST, collect terms belonging to target clusters,
    and return (promoted_terms, new_src_with_those_sections_removed).
    """
    # Find the METHODOLOGY_BLOCKLIST block
    start_marker = "METHODOLOGY_BLOCKLIST: set[str] = {"
    start_idx = src.index(start_marker)
    depth = 0
    end_idx = start_idx
    for i, ch in enumerate(src[start_idx:], start=start_idx):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i
                break

    header_re = re.compile(r"^\s*#\s*──\s*(.+?)\s*─+────\s*$")
    term_re    = re.compile(r"""^\s*['"](.*)['"]\s*,?\s*$""")

    lines      = src[start_idx : end_idx + 1].splitlines(keepends=True)
    promoted: set[str] = set()
    keep_lines: list[str] = []
    in_target = False

    for line in lines:
        hm = header_re.match(line)
        if hm:
            label = hm.group(1).strip()
            in_target = any(tl in label for tl in TARGET_LABELS)
            if not in_target:
                keep_lines.append(line)
            continue

        if in_target:
            tm = term_re.match(line)
            if tm:
                promoted.add(tm.group(1))
            # skip (don't keep) lines belonging to target clusters
        else:
            keep_lines.append(line)

    new_block = "".join(keep_lines)
    new_src = src[:start_idx] + new_block + src[end_idx + 1:]
    return promoted, new_src


def append_to_whitelist(new_terms: set[str]) -> int:
    src = WL_PATH.read_text()
    lines = src.splitlines()
    in_block = False
    insert_at = -1
    for i, line in enumerate(lines):
        if "WHITELIST" in line and "frozenset" in line and "{" in line:
            in_block = True
        if in_block and "})" in line.strip():
            insert_at = i
            break
    if insert_at == -1:
        raise RuntimeError("Could not find WHITELIST closing brace")

    # Load current whitelist to skip duplicates
    import importlib
    import config.whitelist as _wl
    importlib.reload(_wl)
    existing = _wl.WHITELIST

    truly_new = sorted(t.lower() for t in new_terms if t.lower() not in existing)
    if not truly_new:
        return 0

    new_lines = ["    # ── promoted from blocklist ──────────────────────────────────────────"]
    new_lines += [f'    "{t}",' for t in truly_new]
    lines = lines[:insert_at] + new_lines + lines[insert_at:]
    WL_PATH.write_text("\n".join(lines) + "\n")
    return len(truly_new)


def main(dry_run: bool) -> None:
    src = BL_PATH.read_text()
    promoted, new_src = extract_and_strip_clusters(src)

    print(f"\nPromoting {len(promoted)} terms from 5 clusters:")
    for label in TARGET_LABELS:
        print(f"  • {label}")

    if dry_run:
        print("\n[dry-run] Terms that would be promoted (first 30):")
        for t in sorted(promoted)[:30]:
            print(f"    {t}")
        if len(promoted) > 30:
            print(f"    ... and {len(promoted) - 30} more")
        print("\n[dry-run] No files written.")
        return

    # Count remaining blocklist terms
    import re as _re
    remaining = len(_re.findall(r"""^\s*['"]""", new_src, _re.MULTILINE))
    print(f"\nRemoving from blocklist: {len(promoted)} terms  ({remaining} remain)")

    BL_PATH.write_text(new_src)
    print(f"  ✓ blocklist.py updated")

    added = append_to_whitelist(promoted)
    print(f"  ✓ whitelist.py: {added} new terms added")
    print(f"\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
