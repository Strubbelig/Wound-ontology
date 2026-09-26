from __future__ import annotations
import re
from pathlib import Path

from wound_ontology.store.blocker import Blocker


class BaseCleaner:
    """
    Shared base for StoreCleaner and MappingCleaner.

    Owns a Blocker instance for all list-based classification and persistence.
    Provides interactive review helpers that call back into the Blocker's lists.
    """

    def __init__(
        self,
        allowed_predicates: list[str],
        extra_blocked_entities: set[str] | None = None,
        gate=None,
    ):
        self.allowed_predicates: set[str] = set(allowed_predicates)
        self._extra_blocked: set[str]     = extra_blocked_entities or set()
        # `gate` is the TermMappingAndGate record. Given one, its verdicts
        # outrank the two exact lists, because they carry a reason and an author
        # and the lists do not. Given none, the lists decide exactly as before.
        self.blocker                       = Blocker(gate=gate)
        self._abort_review: bool           = False

    # ── Convenience properties (keep callers working without changes) ──────────

    @property
    def blocked_entities(self) -> frozenset[str]:
        return self.blocker.terms._terms | self._extra_blocked

    @property
    def whitelist(self) -> frozenset[str]:
        return self.blocker.white_terms._terms

    def _reload_lists(self) -> None:
        self.blocker.reload()

    # ── Classification helpers (delegate to Blocker) ──────────────────────────

    def _is_blocked(self, term: str) -> bool:
        if self._extra_blocked:
            lower = term.strip().lower()
            base  = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
            if lower in self._extra_blocked or base in self._extra_blocked:
                return True
        return self.blocker.is_blocked(term)

    def _score(self, term: str) -> float:
        if self._extra_blocked:
            lower = term.strip().lower()
            base  = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
            if lower in self._extra_blocked or base in self._extra_blocked:
                return 100.0
        return self.blocker.score(term)

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
        """Per-item: y = move to WHITELIST, n = keep blocked, s = skip, q = quit all."""
        if self._abort_review:
            return
        added = 0
        print(f"  {len(items)} blocked {label}(s) to review")
        print(f"  y = valid concept → WHITELIST  |  n = keep blocked  |  s = skip  |  q = quit all\n")
        for item in items:
            answer = self._prompt(f"  '{item}' in scope? [y/n/s/q] ").strip().lower()
            if answer in ("esc", "q"):
                self._abort_review = True
                print("  Exiting review.")
                break
            if answer == "y":
                n = self._append_to_whitelist({item})
                self._remove_from_blocklist({item})
                self._reload_lists()
                added += n
        if added:
            print(f"\n  ✓ {added} {label}(s) moved to WHITELIST.")
        kept = len(items) - added
        if kept:
            print(f"  {kept} {label}(s) kept blocked or skipped.")

    def _review_to_blocklist(self, items: list[str], label: str) -> None:
        """Per-item: y = keep in whitelist, n = move to BLOCKLIST + remove from whitelist."""
        if self._abort_review:
            return
        added_bl = 0
        print(f"  {len(items)} whitelisted {label}(s) to review")
        print(f"  y = keep in whitelist  |  n = move to BLOCKLIST  |  s = skip  |  q = quit all\n")
        for item in items:
            answer = self._prompt(f"  '{item}' still in scope? [y/n/s/q] ").strip().lower()
            if answer in ("esc", "q"):
                self._abort_review = True
                print("  Exiting review.")
                break
            if answer == "n":
                n_bl = self._append_to_blocklist({item})
                self._remove_from_whitelist({item})
                self._reload_lists()
                added_bl += n_bl
        if added_bl:
            print(f"\n  ✓ {added_bl} {label}(s) added to BLOCKLIST.")
        kept = len(items) - added_bl
        if kept:
            print(f"  {kept} {label}(s) kept in whitelist or skipped.")

    def _save_review_results(
        self, to_block: set[str], to_whitelist: set[str], apply_hint: str = ""
    ) -> None:
        if to_block:
            added   = self._append_to_blocklist(to_block)
            removed = self._remove_from_whitelist(to_block)
            print(f"\n  ✓ {added} new terms written to METHODOLOGY_BLOCKLIST"
                  + (f", {removed} removed from WHITELIST" if removed else "") + ".")
        if to_whitelist:
            added   = self._append_to_whitelist(to_whitelist)
            removed = self._remove_from_blocklist(to_whitelist)
            print(f"  ✓ {added} new terms written to WHITELIST"
                  + (f", {removed} removed from METHODOLOGY_BLOCKLIST" if removed else "") + ".")
        if (to_block or to_whitelist) and apply_hint:
            print(f"  Run pipeline.cleaner.{apply_hint}(pipeline.store) to apply.")

    # ── Persistence (delegate to Blocker's lists) ─────────────────────────────

    # Every list write in StoreCleaner funnels through these four. With a gate
    # they write the RECORD and re-export the literal, so the decision has an
    # author and a reason and the file is a printout of it (rule 40). Without
    # one they edit the literal directly, exactly as before.

    def _gate_write(self, terms: set[str], verdict: str, reason: str) -> int:
        from datetime import datetime
        when = datetime.now().isoformat(timespec="seconds")
        n = 0
        for term in terms:
            if self.blocker.gate_verdict(term)[0] == verdict:
                continue
            self.blocker.gate.gate(term, curator={"verdict": verdict,
                                                  "reason": reason, "when": when})
            n += 1
        if n:
            self.blocker.gate.save()
            self._export_gate_lists()
            self._reload_lists()
        return n

    def _export_gate_lists(self) -> None:
        """Reprint the two literals from the gate, so the view keeps up."""
        from wound_ontology.store.term_lists import export_gate_lists
        export_gate_lists(self.blocker.gate, quiet=True)

    def _append_to_blocklist(self, new_terms: set[str]) -> int:
        if self.blocker.gate is None:
            return self.blocker.terms.add(new_terms)
        return self._gate_write(new_terms, "out", "blocked during list review")

    def _append_to_whitelist(self, new_terms: set[str]) -> int:
        if self.blocker.gate is None:
            return self.blocker.white_terms.add(new_terms)
        return self._gate_write(new_terms, "in", "kept during list review")

    def _remove_from_blocklist(self, terms: set[str]) -> int:
        """Under a gate this is a CHECK, not a write.

        Every caller pairs it with `_append_to_whitelist` on the same terms, and
        under the gate that one write already settles the verdict — a term the
        gate answers `in` is absent from `gated("out")` by construction. So
        nothing is left to remove, and the honest thing is to confirm it rather
        than report a removal that did not happen. An unpaired call raises,
        which is what a silent no-op would have hidden.
        """
        if self.blocker.gate is None:
            return self.blocker.terms.remove(terms)
        return self._confirm_not(terms, "out")

    def _remove_from_whitelist(self, terms: set[str]) -> int:
        if self.blocker.gate is None:
            return self.blocker.white_terms.remove(terms)
        return self._confirm_not(terms, "in")

    def _confirm_not(self, terms: set[str], verdict: str) -> int:
        still = sorted(t for t in terms if self.blocker.gate_verdict(t)[0] == verdict)
        if still:
            raise RuntimeError(
                f"{len(still)} term(s) still read {verdict!r} after the paired "
                f"write that should have changed them: {still[:5]}. Under the "
                f"gate a removal is the other half of an append, never a "
                f"deletion on its own.")
        return len(terms)

    # ── Misc (kept for StoreCleaner compatibility) ────────────────────────────

    @staticmethod
    def _seen_path() -> Path:
        return Path(__file__).resolve().parents[3] / "data" / "cache" / "seen_entities.json"

    @staticmethod
    def _load_seen() -> set[str]:
        import json
        p = BaseCleaner._seen_path()
        if not p.exists():
            return set()
        return set(json.loads(p.read_text()).get("seen", []))

    @staticmethod
    def _save_seen(seen: set[str]) -> None:
        import json
        p = BaseCleaner._seen_path()
        p.write_text(json.dumps({"seen": sorted(seen)}, indent=2))
