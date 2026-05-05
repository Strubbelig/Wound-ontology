from __future__ import annotations
import importlib
import re
from pathlib import Path

import config.blocklist as _blocklists_module
from config.blocklist import METHODOLOGY_BLOCKLIST as _METHODOLOGY_BLOCKLIST
from config.blocklist import SUSPICIOUS_KEYWORDS as _SUSPICIOUS_KEYWORDS
from config.blocklist import WHITELIST as _WHITELIST


class BaseCleaner:
    """
    Shared base for StoreCleaner and MappingCleaner.

    Provides blocklist/whitelist management, scoring, interactive review helpers,
    and persistence methods for config/blocklists.py.

    The blocklist and whitelist are updated by writing back to the source file
    `config/blocklists.py`, so changes are immediately reflected by reloading the module.
    """

    def __init__(
        self,
        allowed_predicates: list[str],
        extra_blocked_entities: set[str] | None = None,
    ):
        self.allowed_predicates: set[str] = set(allowed_predicates)
        self._extra_blocked: set[str] = extra_blocked_entities or set()
        self.blocked_entities: set[str] = _METHODOLOGY_BLOCKLIST | self._extra_blocked
        self.whitelist: frozenset[str] = _WHITELIST

    def _reload_lists(self) -> None:
        """Reload blocklists from disk — changes to blocklists.py take effect without a kernel restart."""
        importlib.reload(_blocklists_module)
        self.blocked_entities = _blocklists_module.METHODOLOGY_BLOCKLIST | self._extra_blocked
        self.whitelist = _blocklists_module.WHITELIST

    # ── Classification helpers ────────────────────────────────────────────────

    def _is_blocked(self, term: str) -> bool:
        lower = term.strip().lower()
        # Remove parenthetical suffixes like "(study)" for matching purposes.
        base = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
        if lower in self.whitelist or base in self.whitelist:
            return False
        # Block if either the full cleaned string or the stripped base is in the blocklist.
        return lower in self.blocked_entities or base in self.blocked_entities

    def _score(self, term: str) -> float:
        """Higher = more likely out-of-scope. Blocklisted → 100. Whitelisted → 0."""
        lower = term.strip().lower()
        base = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
        if lower in self.whitelist or base in self.whitelist:
            return 0.0
        if lower in self.blocked_entities or base in self.blocked_entities:
            return 100.0
        # For non-explicit terms, score based on suspicious keywords.
        # The heuristic is intentionally conservative: each keyword match adds weight.
        tokens = set(re.split(r"[\s\-_/(),]+", lower))
        score = len(tokens & _SUSPICIOUS_KEYWORDS) * 3.0
        for kw in _SUSPICIOUS_KEYWORDS:
            if " " in kw and kw in lower:
                score += 2.0
        return score

    # ── Interactive review helpers ────────────────────────────────────────────

    @staticmethod
    def _prompt(msg: str) -> str:
        """input() wrapper: maps ESC key and Ctrl-C/EOF to the sentinel 'esc'."""
        try:
            val = input(msg)
            if "\x1b" in val and val.replace("\x1b", "").strip() == "":
                return "esc"
            return val
        except (KeyboardInterrupt, EOFError):
            print()
            return "esc"

    def _review_to_whitelist(self, items: list[str], label: str) -> None:
        """Per-item: y = move to WHITELIST, n = keep blocked, s = skip, ESC = exit."""
        to_whitelist: set[str] = set()
        print(f"  {len(items)} blocked {label}(s) to review")
        print(f"  y = valid concept → WHITELIST  |  n = keep blocked  |  s = skip  |  ESC = exit\n")
        for item in items:
            answer = self._prompt(f"  '{item}' in scope? [y/n/s] ").strip().lower()
            if answer == "esc":
                print("  Exiting review.")
                break
            if answer == "y":
                to_whitelist.add(item)
        if to_whitelist:
            added = self._append_to_whitelist(to_whitelist)
            print(f"\n  ✓ {added} {label}(s) moved to WHITELIST.")
        kept = len(items) - len(to_whitelist)
        if kept:
            print(f"  {kept} {label}(s) kept blocked or skipped.")

    def _review_to_blocklist(self, items: list[str], label: str) -> None:
        """Per-item: y = keep in whitelist, n = move to BLOCKLIST + remove from whitelist, s = skip, ESC = exit."""
        to_block: set[str] = set()
        print(f"  {len(items)} whitelisted {label}(s) to review")
        print(f"  y = keep in whitelist  |  n = move to BLOCKLIST  |  s = skip  |  ESC = exit\n")
        for item in items:
            answer = self._prompt(f"  '{item}' still in scope? [y/n/s] ").strip().lower()
            if answer == "esc":
                print("  Exiting review.")
                break
            if answer == "n":
                to_block.add(item)
        if to_block:
            added_bl = self._append_to_blocklist(to_block)
            removed_wl = self._remove_from_whitelist(to_block)
            print(f"\n  ✓ {added_bl} {label}(s) added to BLOCKLIST, {removed_wl} removed from WHITELIST.")
        kept = len(items) - len(to_block)
        if kept:
            print(f"  {kept} {label}(s) kept in whitelist or skipped.")

    def _save_review_results(
        self, to_block: set[str], to_whitelist: set[str], apply_hint: str = ""
    ) -> None:
        if to_block:
            added = self._append_to_blocklist(to_block)
            print(f"\n  ✓ {added} new terms written to METHODOLOGY_BLOCKLIST.")
        if to_whitelist:
            added = self._append_to_whitelist(to_whitelist)
            print(f"  ✓ {added} new terms written to WHITELIST.")
        if (to_block or to_whitelist) and apply_hint:
            print(f"  Run pipeline.cleaner.{apply_hint}(pipeline.store) to apply.")

    # ── Blocklist / whitelist persistence ────────────────────────────────────

    @staticmethod
    def _blocklist_path() -> Path:
        return Path(__file__).resolve().parents[3] / "config" / "blocklists.py"

    @staticmethod
    def _append_to_blocklist(new_terms: set[str]) -> int:
        """Append new_terms to METHODOLOGY_BLOCKLIST in config/blocklists.py."""
        path = BaseCleaner._blocklist_path()
        lines = path.read_text().splitlines()
        in_block = False
        insert_at = -1
        for i, line in enumerate(lines):
            if "METHODOLOGY_BLOCKLIST" in line and "{" in line:
                in_block = True
            if in_block and line.strip() == "}":
                insert_at = i
                break
        if insert_at == -1:
            raise RuntimeError("Could not find METHODOLOGY_BLOCKLIST closing brace in blocklists.py")
        importlib.reload(_blocklists_module)
        truly_new = sorted(t.lower() for t in new_terms if t.lower() not in _blocklists_module.METHODOLOGY_BLOCKLIST)
        if not truly_new:
            return 0
        new_lines = ['    # ── added interactively ─────────────────────────────────────────────']
        new_lines += [f'    "{term}",' for term in truly_new]
        lines = lines[:insert_at] + new_lines + lines[insert_at:]
        path.write_text("\n".join(lines) + "\n")
        return len(truly_new)

    @staticmethod
    def _append_to_whitelist(new_terms: set[str]) -> int:
        """Append new_terms to WHITELIST in config/blocklists.py."""
        path = BaseCleaner._blocklist_path()
        lines = path.read_text().splitlines()
        in_block = False
        insert_at = -1
        for i, line in enumerate(lines):
            if "WHITELIST" in line and "frozenset" in line and "{" in line:
                in_block = True
            if in_block and "})" in line.strip():
                insert_at = i
                break
        if insert_at == -1:
            raise RuntimeError("Could not find WHITELIST closing brace in blocklists.py")
        importlib.reload(_blocklists_module)
        truly_new = sorted(t.lower() for t in new_terms if t.lower() not in _blocklists_module.WHITELIST)
        if not truly_new:
            return 0
        new_lines = [f'    "{term}",' for term in truly_new]
        lines = lines[:insert_at] + new_lines + lines[insert_at:]
        path.write_text("\n".join(lines) + "\n")
        return len(truly_new)

    @staticmethod
    def _remove_from_whitelist(terms: set[str]) -> int:
        """Remove terms from WHITELIST in config/blocklists.py."""
        path = BaseCleaner._blocklist_path()
        lines = path.read_text().splitlines()
        to_remove = {t.strip().lower() for t in terms}
        in_block = False
        filtered: list[str] = []
        removed = 0
        for line in lines:
            if "WHITELIST" in line and "frozenset" in line:
                in_block = True
            if in_block and "})" in line.strip():
                in_block = False
                filtered.append(line)
                continue
            if in_block and line.strip().startswith('"'):
                val = line.strip().rstrip('",').strip('"')
                if val in to_remove:
                    removed += 1
                    continue
            filtered.append(line)
        path.write_text("\n".join(filtered) + "\n")
        return removed
