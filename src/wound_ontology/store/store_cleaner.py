from __future__ import annotations
import asyncio
import re
from collections import Counter, defaultdict

_SUSPICIOUS_KEYWORDS: frozenset[str] = frozenset({
    # Study design & reporting
    "study", "trial", "review", "analysis", "cohort", "survey",
    "registry", "database", "record", "protocol", "guideline",
    "report", "reporting", "documentation",
    # Study participants & groups
    "group", "arm", "patient", "participant", "subject",
    "control", "intervention", "allocation", "randomization",
    "sample", "population", "cohort",
    # Outcomes & statistics
    "outcome", "endpoint", "result", "finding", "data",
    "score", "scale", "index", "rate", "ratio", "percentage",
    "mean", "median", "odds", "hazard", "confidence", "p-value",
    "follow-up", "baseline", "duration",
    # Admin / healthcare context
    "hospital", "admission", "discharge", "stay", "cost",
    "age", "gender", "sex", "bmi", "comorbidity",
    "mortality", "morbidity", "survival",
    # Methodology terms
    "method", "methodology", "technique", "approach", "strategy",
    "criteria", "inclusion", "exclusion", "consent",
    "bias", "limitation", "heterogeneity", "blinding",
    # Animal / basic science
    "model", "assay", "vitro", "vivo", "murine", "rodent",
    "pcr", "rrna", "sequencing", "staining", "immunohistochemistry",
    "macrophage", "fibroblast", "keratinocyte", "cytokine",
    # Demographics / admin
    "age", "race", "sex", "ethnicity", "nurse", "physician",
    "knowledge", "attitude", "satisfaction", "safety",
    # Bibliometric
    "pubmed", "scopus", "prospero", "prisma", "cochrane",
    "regression", "hazard", "propensity", "heterogeneity",
})

_METHODOLOGY_BLOCKLIST: set[str] = {
    # ── Study designs ──────────────────────────────────────────────────────────
    "study", "review", "systematic review", "scoping review",
    "systematic literature review", "literature review",
    "meta-analysis", "meta analysis",
    "randomized controlled trial", "randomised controlled trial", "rct",
    "randomized clinical trial", "randomised clinical trial",
    "clinical trial", "randomized trial", "randomised trial",
    "cohort study", "retrospective study", "prospective study",
    "cross-sectional study", "retrospective cohort study",
    "prospective cohort study", "observational study",
    "case-control study", "case control study", "case series", "case report",
    # ── Study components & groups ──────────────────────────────────────────────
    "control group", "intervention group", "study group", "comparison group",
    "treatment group", "placebo group", "experimental group",
    "intervention", "sample", "sample size", "population",
    # ── Bibliometric / database terms ─────────────────────────────────────────
    "pubmed", "scopus", "prospero", "prisma", "prisma guidelines",
    "strobe", "strobe checklist", "cochrane",
    # ── Statistical / analytical methods ──────────────────────────────────────
    "logistic regression", "multivariate logistic regression",
    "propensity score matching", "propensity score",
    "hazard ratio", "odds ratio", "relative risk",
    "auc", "receiver operating characteristic", "roc curve",
    "sensitivity analysis", "subgroup analysis", "heterogeneity",
    "risk of bias", "funnel plot", "forest plot",
    "statistical analysis", "multivariate analysis",
    "analysis", "regression", "correlation",
    # ── Generic clinical/admin ─────────────────────────────────────────────────
    "patient", "participant", "subject",
    "follow-up", "follow-up period", "follow up",
    "outcome", "outcome measure", "primary outcome", "secondary outcome",
    "endpoint", "data", "result", "method", "methodology",
    "inclusion criteria", "exclusion criteria",
    "informed consent", "ethics", "ethical approval",
    "limitation", "bias",
    "protocol", "guideline", "guidelines",
    # ── Demographics / noise ──────────────────────────────────────────────────
    "age", "race", "sex", "ethnicity", "gender",
    "nurse", "nursing staff", "healthcare professional",
    "healthcare worker", "clinician", "physician",
    "knowledge", "attitude", "practice", "theory",
    "patient satisfaction", "patient safety",
    # ── Animal / basic science ────────────────────────────────────────────────
    "rat model", "mouse model", "murine model", "animal model",
    "in vitro", "in vivo", "ex vivo",
    "wound healing assay", "scratch assay",
    "qrt-pcr", "qpcr", "rt-pcr", "pcr",
    "16s rrna", "16s rrna gene sequencing", "rrna sequencing",
    "cd31", "alpha-sma", "alpha smooth muscle actin",
    "macrophage polarization",
    "macrophage", "fibroblast", "keratinocyte",
    "oxidative stress", "reactive oxygen species", "ros",
}


class StoreCleaner:
    """
    Removes out-of-scope entities and invalid predicates from a ConceptStore.

    Two cleaning operations:
      - Entity blocklist  : removes methodology/study-design entities by name.
      - Predicate filter  : strips attributes whose predicate is not in allowed_predicates.
      - Empty-entity prune: removes entities left with zero true attributes after the above.

    Usage::

        cleaner = StoreCleaner(allowed_predicates=ALLOWED_PREDICATES)
        report  = cleaner.clean(store)
        cleaner.print_report(report)
    """

    def __init__(
        self,
        allowed_predicates: list[str],
        extra_blocked_entities: set[str] | None = None,
    ):
        self.allowed_predicates: set[str] = set(allowed_predicates)
        self.blocked_entities: set[str] = _METHODOLOGY_BLOCKLIST | (extra_blocked_entities or set())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_blocked(self, entity_name: str) -> bool:
        lower = entity_name.strip().lower()
        if lower in self.blocked_entities:
            return True
        # Strip trailing parenthetical abbreviation: "Randomized Controlled Trial (RCT)"
        base = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
        return base in self.blocked_entities

    def _pred(self, attr: str) -> str:
        return attr.split(":", 1)[0].strip()

    # ── Main entry point ──────────────────────────────────────────────────────

    def clean(self, store) -> dict:
        """
        Clean the ConceptStore in-place and save it.

        Returns a report dict with counts of what was removed.
        """
        stats: dict[str, int] = defaultdict(int)
        rogue_pred_counts: dict[str, int] = defaultdict(int)
        blocked_entity_examples: list[str] = []

        for key, pmid_data in store._dict.items():
            entities: dict = pmid_data.get("entities", {})
            to_delete: list[str] = []

            for entity, attrs in list(entities.items()):

                # 1. Blocklist check
                if self._is_blocked(entity):
                    to_delete.append(entity)
                    stats["blocked_entities"] += 1
                    if len(blocked_entity_examples) < 20:
                        blocked_entity_examples.append(entity)
                    continue

                # 2. Strip rogue predicates
                rogue = [a for a in list(attrs) if self._pred(a) not in self.allowed_predicates]
                for attr in rogue:
                    del attrs[attr]
                    rogue_pred_counts[self._pred(attr)] += 1
                    stats["rogue_predicates_removed"] += 1

                # 3. Prune entities left with no true attributes
                if not any(v == 1.0 for v in attrs.values()):
                    to_delete.append(entity)
                    stats["empty_entities_pruned"] += 1

            for entity in to_delete:
                del entities[entity]

        store.save()

        return {
            **dict(stats),
            "rogue_predicate_breakdown": dict(rogue_pred_counts),
            "blocked_entity_examples": blocked_entity_examples,
        }

    # ── Candidate scanning ────────────────────────────────────────────────────

    def _score(self, entity: str) -> float:
        """
        Higher score = more likely out-of-scope.
        Blocklisted names score 100. Others are scored by suspicious keyword hits.
        """
        lower = entity.strip().lower()
        base = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()

        if lower in self.blocked_entities or base in self.blocked_entities:
            return 100.0

        tokens = set(re.split(r"[\s\-_/(),]+", lower))
        score = len(tokens & _SUSPICIOUS_KEYWORDS) * 3.0

        # Partial substring hits for multi-word keywords not caught by tokenisation
        for kw in _SUSPICIOUS_KEYWORDS:
            if " " in kw and kw in lower:
                score += 2.0

        return score

    def _collect_ranked(self, store) -> list[tuple[str, int, float, list[str]]]:
        """
        Return all unique entities sorted by (score desc, freq desc).
        Each tuple: (entity_name, pmid_count, score, sample_true_attrs).
        """
        freq: Counter = Counter()
        sample_attrs: dict[str, list[str]] = {}

        for pmid_data in store._dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                freq[entity] += 1
                if entity not in sample_attrs:
                    sample_attrs[entity] = [
                        a for a, v in attrs.items() if v == 1.0
                    ][:4]

        ranked = [
            (entity, count, self._score(entity), sample_attrs.get(entity, []))
            for entity, count in freq.items()
        ]
        ranked.sort(key=lambda x: (-x[2], -x[1]))
        return ranked

    def scan_candidates(
        self,
        store,
        llm,
        top_n: int = 1000,
        llm_batch_size: int = 150,
        display_batch_size: int = 500,
        threshold_pct: float = 20.0,
    ) -> None:
        """
        Use the LLM to evaluate the ``top_n`` most frequent entities and flag those
        inappropriate for a wound ontology.

        Only the top_n entities by PMID frequency are sent to the LLM — this focuses
        evaluation on the terms that have the most impact on the ontology.
        Entities already in the blocklist are pre-flagged without an LLM call.
        If more than ``threshold_pct`` % of a display batch are flagged, the next
        batch is shown automatically.

        After reviewing, purge with::

            pipeline.run_clean_store(extra_blocked_entities={"term1", "term2", ...})
        """
        # Collect all entities sorted by frequency descending
        ranked_raw = self._collect_ranked(store)
        by_freq = sorted(ranked_raw, key=lambda x: -x[1])
        total_entities = len(by_freq)

        # Separate blocked from non-blocked before selecting top_n
        # so the top_n quota is filled exclusively by non-blocked entities
        pre_blocked = [r for r in by_freq if r[2] == 100.0]
        non_blocked = [r for r in by_freq if r[2] < 100.0]

        candidates = non_blocked[:top_n]
        rest       = non_blocked[top_n:]

        print(f"[StoreCleaner] Evaluating top {len(candidates)} most frequent "
              f"non-blocked entities (of {total_entities} total) via LLM "
              f"(batches of {llm_batch_size})...")
        print(f"  Pre-blocked (in blocklist)      : {len(pre_blocked)}")
        print(f"  Sending to LLM                  : {len(candidates)}")
        print(f"  Below top {top_n}, not evaluated: {len(rest)}")

        # Load cached eval if available
        llm_flagged: set[str] = set()
        dm = getattr(store, "dm", None)
        cached_eval: dict = {}
        if dm is not None:
            cached_eval = dm.load_latest_json("scope_eval") or {}

        # Entities already evaluated in a previous scan — skip LLM call for them
        already_evaluated: set[str] = set(cached_eval.keys())
        llm_flagged = {e for e, v in cached_eval.items() if v}
        to_evaluate = [r for r in candidates if r[0] not in already_evaluated]

        if already_evaluated:
            print(f"  Reusing cached eval for {len(already_evaluated)} entities "
                  f"({len(to_evaluate)} new to evaluate).")

        # LLM evaluation for new entities — saves after every batch
        async def _run_llm():
            n_batches = (len(to_evaluate) + llm_batch_size - 1) // llm_batch_size
            for i in range(0, len(to_evaluate), llm_batch_size):
                chunk = to_evaluate[i : i + llm_batch_size]
                batch_num = i // llm_batch_size + 1
                batch_input = [(e, c, a) for e, c, _, a in chunk]
                try:
                    flagged = await llm.classify_scope_batch(batch_input)
                    flagged_set = set(flagged)
                    llm_flagged.update(flagged_set)
                    for entity, _, _, _ in chunk:
                        cached_eval[entity] = entity in flagged_set
                    done = min(i + llm_batch_size, len(to_evaluate))
                    print(f"  LLM batch {batch_num}/{n_batches}: "
                          f"{done}/{len(to_evaluate)} evaluated, "
                          f"{len(flagged)} flagged in this batch.")
                except Exception as exc:
                    print(f"  LLM batch {batch_num}/{n_batches} failed ({exc}) — skipped.")
                finally:
                    if dm is not None:
                        dm.save_as_json(cached_eval, "scope_eval")

        asyncio.get_event_loop().run_until_complete(_run_llm())
        print(f"  Eval saved ({len(cached_eval)} entities total).")

        # Build final ranked list:
        #   tier0 — blocklist hits (definitely out)
        #   tier1 — LLM-confirmed inappropriate from top_n
        #   tier2 — LLM-cleared from top_n (evaluated, passed)
        #   tier3 — below top_n (not evaluated)
        tier0 = sorted(pre_blocked,                                      key=lambda x: -x[1])
        tier1 = sorted([r for r in candidates if r[0] in llm_flagged],  key=lambda x: -x[1])
        tier2 = sorted([r for r in candidates if r[0] not in llm_flagged], key=lambda x: -x[1])
        tier3 = sorted(rest,                                             key=lambda x: -x[1])
        ranked = tier0 + tier1 + tier2 + tier3

        flagged_total = len(tier0) + len(tier1)
        print(f"\n[StoreCleaner] Total flagged as inappropriate: "
              f"{flagged_total} / {total_entities} "
              f"({100 * flagged_total / max(total_entities, 1):.1f}%)")

        # Display in batches
        for start in range(0, len(ranked), display_batch_size):
            batch = ranked[start : start + display_batch_size]
            batch_num = start // display_batch_size + 1

            print(f"\n{'='*80}")
            print(f"  SCOPE SCAN — Batch {batch_num}  "
                  f"(#{start + 1}–{start + len(batch)} of {len(ranked)})")
            print(f"  ✗ = blocklist  |  ! = LLM flagged  |  · = clean")
            print(f"{'='*80}")
            print(f"  {'#':>5}  {'Freq':>4}  {'Flag':4}  Entity  →  sample true attributes")
            print(f"  {'-'*5}  {'-'*4}  {'-'*4}  {'-'*62}")

            n_flagged_in_batch = 0
            for rank, (entity, freq, score, attrs) in enumerate(batch, start=start + 1):
                if score == 100.0:
                    flag, n_flagged_in_batch = " ✗ ", n_flagged_in_batch + 1
                elif entity in llm_flagged:
                    flag, n_flagged_in_batch = " !  ", n_flagged_in_batch + 1
                else:
                    flag = " ·  "
                attr_str = ", ".join(attrs) if attrs else "—"
                print(f"  {rank:>5}  {freq:>4}  {flag}  {entity}  →  {attr_str}")

            flagged_pct = 100 * n_flagged_in_batch / len(batch)
            print(f"\n  Flagged in this batch: {n_flagged_in_batch}/{len(batch)} ({flagged_pct:.1f}%)")

            if start + display_batch_size >= len(ranked):
                print("  [End of store — all entities shown]")
                break

            if flagged_pct > threshold_pct:
                print(f"  > {threshold_pct:.0f}% flagged → showing next batch automatically...\n")
            else:
                print(f"  ≤ {threshold_pct:.0f}% flagged — stopping. "
                      "Call scan_candidates() again to see more.")
                break

        print(f"\nTo purge identified entities, run:")
        print('  pipeline.run_clean_store(extra_blocked_entities={"term1", "term2", ...})')

    # ── Reporting ─────────────────────────────────────────────────────────────

    @staticmethod
    def print_report(report: dict) -> None:
        print("[StoreCleaner] Cleaning complete")
        print(f"  Blocked entities removed   : {report.get('blocked_entities', 0)}")
        print(f"  Rogue predicates stripped  : {report.get('rogue_predicates_removed', 0)}")
        print(f"  Empty entities pruned      : {report.get('empty_entities_pruned', 0)}")
        breakdown = report.get("rogue_predicate_breakdown", {})
        if breakdown:
            top = sorted(breakdown.items(), key=lambda x: -x[1])[:10]
            print(f"  Rogue predicate breakdown  : {dict(top)}")
        examples = report.get("blocked_entity_examples", [])
        if examples:
            print(f"  Blocked entity examples    : {examples[:10]}")
