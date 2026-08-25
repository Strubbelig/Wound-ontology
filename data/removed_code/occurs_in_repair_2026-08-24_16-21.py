"""The occurs_in repair path, removed from the live pipeline on 2026-08-24.

It fixed a defect only the LEGACY free-text extractor could produce: that
extractor emitted `occurs_in` (BFO_0000066, which demands an occurrent) with
disorder subjects. No RelationType in the two-stage schema emits `occurs_in`
at all, so a store built by the current extractor cannot contain the defect,
and running the repair spends LLM calls to find nothing.

Kept verbatim because this project is not under version control.

INCOMPLETE: the store_cleaner.py half (three keyword frozensets, five pure
helpers, scan_occurs_in / fix_occurs_in / print_occurs_in_report) was deleted
by an earlier pass that crashed before writing this file, so it is not
captured here. It was code slated for deletion either way.
"""

# ===== src/wound_ontology/llm/llm_client.py :: classify_anatomical_targets =====
    async def classify_anatomical_targets(
        self,
        terms: list[str],
        batch_size: int = 60,
    ) -> dict[str, bool]:
        """Classify terms as ANATOMICAL (True) or NOT_ANATOMICAL (False).

        Used by the occurs_in fixer to decide which targets are valid BFO
        process locations versus conditions, patient types, time periods, etc.
        Returns {term: is_anatomical} for every term in *terms*.
        """
        import json as _json
        schema = OccursInTargetBatch.model_json_schema()
        results: dict[str, bool] = {}

        for i in range(0, len(terms), batch_size):
            batch     = terms[i : i + batch_size]
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
{_json.dumps(schema, indent=2)}"""

            parsed = await self._execute_with_retry(
                self._call_json, prompt, OccursInTargetBatch, temperature=0.0
            )
            for r in parsed.results:
                results[r.term] = r.anatomical
            print(
                f"  Classified {min(i + batch_size, len(terms))}/{len(terms)} targets...",
                end="\r",
            )

        print()
        return results


# ===== src/wound_ontology/orchestrator.py :: run_fix_occurs_in =====
    def run_fix_occurs_in(self, batch_size: int = 60, dry_run: bool = False) -> None:
        """Fix occurs_in misuse via LLM-based anatomical target classification.

        Disorders with anatomical targets → renamed to part_of.
        Conditions or any subject with non-anatomical targets → dropped.
        Process subjects with anatomical targets → left unchanged (correct BFO).

        dry_run: classify and print decisions but do not modify the store.
        """
        stats = self._run_sync(
            self.cleaner.fix_occurs_in(self.store, self.llm, batch_size=batch_size, dry_run=dry_run)
        )
        if not dry_run:
            print(f"[Orchestrator] Store saved — {stats}")

    # ── Hierarchies ────────────────────────────────────────────────────────────



# ===== src/wound_ontology/orchestrator.py :: run_scan_occurs_in =====
    def run_scan_occurs_in(self, show_all: bool = False) -> dict:
        """Scan the concept store for occurs_in misuse and print a report.

        Classifies every occurs_in (subject, target) pair as:
          process  — correct BFO usage (left unchanged)
          disorder — should use 'part_of' (flagged)
          uncertain — manual review recommended

        Returns the report dict.  To apply fixes use run_fix_occurs_in().
        """
        report = self.cleaner.scan_occurs_in(self.store, show_all=show_all)
        StoreCleaner.print_occurs_in_report(report)
        return report


