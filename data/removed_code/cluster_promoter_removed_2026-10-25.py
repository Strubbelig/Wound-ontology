"""Move named SapBERT clusters from METHODOLOGY_BLOCKLIST to WHITELIST.

Identifies clusters by their comment-header label in blocklist.py (written by
the reclustering step), extracts all member terms, appends them to whitelist.py,
and removes them from blocklist.py.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path


def extract_and_strip_clusters(
    src: str,
    target_labels: list[str],
) -> tuple[set[str], str]:
    """Parse METHODOLOGY_BLOCKLIST, collect terms in target clusters, return cleaned src.

    Args:
        src:           Full text of blocklist.py.
        target_labels: Partial cluster-header strings to match (any substring match).

    Returns:
        (promoted_terms, new_src) — the promoted terms and the blocklist source
        with those cluster sections removed.
    """
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
    term_re   = re.compile(r"""^\s*['"](.*)['"]\s*,?\s*$""")

    lines     = src[start_idx : end_idx + 1].splitlines(keepends=True)
    promoted: set[str] = set()
    keep_lines: list[str] = []
    in_target = False

    for line in lines:
        hm = header_re.match(line)
        if hm:
            label     = hm.group(1).strip()
            in_target = any(tl in label for tl in target_labels)
            if not in_target:
                keep_lines.append(line)
            continue

        if in_target:
            tm = term_re.match(line)
            if tm:
                promoted.add(tm.group(1))
        else:
            keep_lines.append(line)

    new_src = src[:start_idx] + "".join(keep_lines) + src[end_idx + 1:]
    return promoted, new_src


def append_to_whitelist(new_terms: set[str], wl_path: Path) -> int:
    """Add *new_terms* to the WHITELIST frozenset in *wl_path*.

    Skips terms already present.  Returns the number of terms actually added.
    """
    import config.whitelist as _wl
    importlib.reload(_wl)
    existing = _wl.WHITELIST

    truly_new = sorted(t.lower() for t in new_terms if t.lower() not in existing)
    if not truly_new:
        return 0

    src   = wl_path.read_text()
    lines = src.splitlines()
    insert_at = -1
    in_block  = False
    for i, line in enumerate(lines):
        if "WHITELIST" in line and "frozenset" in line and "{" in line:
            in_block = True
        if in_block and "})" in line.strip():
            insert_at = i
            break
    if insert_at == -1:
        raise RuntimeError("Could not find WHITELIST closing brace in whitelist.py")

    new_lines = [
        "    # ── promoted from blocklist ──────────────────────────────────────────",
    ] + [f'    "{t}",' for t in truly_new]
    lines = lines[:insert_at] + new_lines + lines[insert_at:]
    wl_path.write_text("\n".join(lines) + "\n")
    return len(truly_new)
