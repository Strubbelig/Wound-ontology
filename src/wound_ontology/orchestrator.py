from __future__ import annotations
"""Orchestrator glue code for the wound ontology pipeline."""
import asyncio
import os
import pandas as pd
from dotenv import load_dotenv
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.llm.llm_client import LLMClient
from wound_ontology.connectors.pubmed_connector import PubmedConnector
from wound_ontology.store.concept_store import ConceptStore
from wound_ontology.store.store_cleaner import StoreCleaner
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy
from wound_ontology.hierarchies.fca_hierarchy import FCAHierarchy
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.fca.concept_lattice import ConceptLattice
from wound_ontology.embedding.embedder import Embedder
from wound_ontology.mappers.term_mapper import TermMapper
from wound_ontology.mappers.mapping_cleaner import MappingCleaner
from wound_ontology.owl import OWLOntology, OntologyCurator
from wound_ontology.reasoning import OWLReasoner
from wound_ontology.graph_visualizer import GraphVisualizer

load_dotenv()

try:
    from config.settings import (
        PREDICATE_DEFINITIONS as _PREDICATE_DEFINITIONS,
        PREDEFINED_HIERARCHY_FILE as _PREDEFINED_HIERARCHY_FILE,
        BFO_OWL_URL as _BFO_URL,
        RO_OWL_URL as _RO_URL,
        OBI_OWL_URL as _OBI_URL,
    )
except ImportError:
    _PREDICATE_DEFINITIONS = {}
    _PREDEFINED_HIERARCHY_FILE = None
    _BFO_URL = "http://purl.obolibrary.org/obo/bfo.owl"
    _RO_URL  = "http://purl.obolibrary.org/obo/ro.owl"
    _OBI_URL = "http://purl.obolibrary.org/obo/obi.owl"

_DEFAULT_ALLOWED_PREDICATES = [
    "is_a", "part_of", "has_quality", "occurs_in",
    "caused_by", "is_treatment_for",
]


class Orchestrator:
    def __init__(
        self,
        openrouter_api_key: str | None = None,
        openrouter_model: str | None = None,
        entrez_email: str | None = None,
        allowed_predicates: list | None = None,
        base_path=None,
        # Legacy keyword args kept for backwards compatibility — ignored.
        google_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
    ):
        openrouter_api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        entrez_email       = entrez_email       or os.getenv("ENTREZ_EMAIL", "")
        allowed_predicates = allowed_predicates or _DEFAULT_ALLOWED_PREDICATES

        self.dm  = DataManager(**({"base_path": base_path} if base_path else {}))
        llm_kwargs = {"api_key": openrouter_api_key}
        if openrouter_model:
            llm_kwargs["model_id"] = openrouter_model
        self.llm = LLMClient(**llm_kwargs)

        self.allowed_predicates = allowed_predicates
        self.pubcon        = PubmedConnector(self.dm, entrez_email)
        self.store         = ConceptStore(self.dm, "concept_store")
        self.cleaner       = StoreCleaner(self.allowed_predicates)
        self.class_hier    = ClassHierarchy(self.dm)
        self.mere_hier     = MereologicalHierarchy(self.dm)
        self.fca_hier      = FCAHierarchy(self.dm)
        self.context_matrix = ContextMatrix(self.dm, "context_matrix")
        self.lattice       = ConceptLattice(self.dm, self.context_matrix)
        self.term_mapper     = TermMapper(self.dm, file_name="term_mapping", mapper_name="Term mapper")
        self.mapping_cleaner = MappingCleaner(self.term_mapper, allowed_predicates=self.allowed_predicates)
        self._embedder: Embedder | None = None
        self.reasoner      = OWLReasoner()
        self.graph_exporter = GraphVisualizer()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _run_sync(self, coroutine):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coroutine)

    def _ensure_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder()
        return self._embedder

    def _collect_store_terms_with_freq(self, store=None) -> dict[str, int]:
        store = store or self.store
        freq: dict[str, int] = {}
        for pmid_data in store.dict.values():
            seen_in_pmid: set[str] = set()
            for entity, attrs in pmid_data.get("entities", {}).items():
                if entity not in seen_in_pmid:
                    freq[entity] = freq.get(entity, 0) + 1
                    seen_in_pmid.add(entity)
                for triple in attrs.keys():
                    if ":" in triple:
                        target = triple.split(":", 1)[1].strip()
                        if target not in seen_in_pmid:
                            freq[target] = freq.get(target, 0) + 1
                            seen_in_pmid.add(target)
        return freq

    async def _mapping_milestone(self, store) -> None:
        """Periodic callback during extraction: clean store and rebuild term mapping."""
        cleaner = StoreCleaner(self.allowed_predicates)
        report  = cleaner.clean(store)
        StoreCleaner.print_report(report)

        freq = self._collect_store_terms_with_freq(store)
        self.term_mapper.build_from_embeddings(
            list(freq.keys()),
            embedder=self._ensure_embedder(),
            similarity_threshold=0.95,
            frequencies=freq,
        )
        print("\n[Orchestrator] Mapping milestone complete.")

    # ── Phase 1: Extraction ────────────────────────────────────────────────────
    # Noise filtering (units, pure symbols) is applied automatically during
    # the milestone callback and again in run_clean_store().

    def run_pubmed_search(self, queries: str | list[str], max_results_per_query: int = 200):
        """Fetch abstracts for one or more PubMed queries, merging into one database."""
        self.pubcon.get_data(queries, max_results_per_query)

    def run_extract_to_store(
        self,
        batch_size: int = 10,
        use_bfo_attributes: bool = True,
        max_consecutive_failures: int = 20,
        max_vocab_hints: int = 300,
        normalize_every: int = 1000,
    ):
        """
        Extract entities from PubMed abstracts into the ConceptStore.

        Noise terms (units, pure symbols, abbreviations) are filtered
        automatically via the milestone callback every normalize_every mentions.
        Set normalize_every=0 to disable mid-extraction filtering.
        """
        bfo_anchors = list(OWLOntology.load(_BFO_URL, self.dm).labels.keys()) if use_bfo_attributes else []
        if bfo_anchors:
            print(f"Using BFO anchor classes as is_a target candidates: {bfo_anchors}")
        print("Starting LLM Extraction...")
        self._run_sync(self.store.add_llm_extracts(
            self.pubcon.database, self.llm, self.allowed_predicates, batch_size,
            extra_targets=bfo_anchors,
            predicate_definitions=_PREDICATE_DEFINITIONS,
            max_consecutive_failures=max_consecutive_failures,
            max_vocab_hints=max_vocab_hints,
            milestone_every=normalize_every,
            on_milestone=self._mapping_milestone if normalize_every > 0 else None,
        ))

    # ── Phase 2: Mapping ───────────────────────────────────────────────────────

    def run_build_term_mapping(self, similarity_threshold: float = 0.95) -> dict:
        """
        Build a SapBERT cosine-similarity mapping that clusters near-duplicate terms.

        The most frequent term in each cluster becomes the canonical form.
        Follow up with review_mapping(), then run_apply_mapping().
        """
        freq = self._collect_store_terms_with_freq()
        print(f"[Orchestrator] Building term mapping from {len(freq)} unique store terms "
              f"(threshold={similarity_threshold})...")
        mapping = self.term_mapper.build_from_embeddings(
            list(freq.keys()),
            embedder=self._ensure_embedder(),
            similarity_threshold=similarity_threshold,
            frequencies=freq,
        )
        print("[Orchestrator] Mapping built — call review_mapping() to inspect and curate.")
        return mapping

    def review_mapping(self) -> None:
        """
        Inspect and curate the term mapping before applying it to the store.

        Runs sequentially:
          1. List all mappings (informational).
          2. Interactive review of auto-merged clusters.
          3. List suspicious mappings (informational).
          4. Interactive review of remaining mappings.
        """
        self.mapping_cleaner.list_mappings()
        self.mapping_cleaner.review_merged_mappings()
        self.mapping_cleaner.list_suspicious_mappings()
        self.mapping_cleaner.review_mappings()

    def check_term_mapping(self, threshold: float = 0.95) -> list[dict]:
        """Re-evaluate term mappings with SapBERT and flag potential false merges.

        Reads the live term_mapper.mapping dict and embeds every non-identity
        (term, canonical) pair.  Reports entries whose cosine similarity falls
        below threshold — these are potentially wrong merges.

        Returns a list of flagged dicts: {term, canonical, cosine, string_sim}.
        """
        from wound_ontology.mappers.mapping_checker import check_mapping, print_report

        mapping = self.term_mapper.mapping
        non_id  = {t: c for t, c in mapping.items() if t != c}
        print(f"Non-identity entries : {len(non_id)}")

        flagged = check_mapping(mapping, self._ensure_embedder(), threshold)
        print_report(flagged, len(non_id), threshold)
        return flagged

    def run_apply_mapping(self) -> None:
        """Apply the reviewed term mapping to the store (normalise all entity and target names)."""
        self.mapping_cleaner.apply(self.store)

    # ── Phase 3: Curation ─────────────────────────────────────────────────────

    def review_lists(
        self,
        high_threshold: float = 0.92,
        low_threshold: float = 0.40,
        save_skipped: bool = False,
        llm_batch_size: int = 50,
        recluster: bool = False,
        bl_clusters: int = 40,
        wl_clusters: int = 25,
    ) -> None:
        """
        Interactively review and curate entities in the store.

        Targets are intentionally not cleaned here — they are normalised and
        clustered to canonical forms by run_build_term_mapping() + run_apply_mapping().

        Runs sequentially:
          1. Validate blocklist/whitelist exclusivity.
          2. Entities: score ≥ high_threshold → auto-block; score < low_threshold → skip;
             in between → manual review.
          3. Auto-blocked entities in store — allow to whitelist exceptions.
          4. Whitelisted entities — allow to move to blocklist.
          5. Recluster both lists with SapBERT K-means (only if recluster=True).

        Call run_clean_store() afterwards to apply changes.
        """
        self.cleaner._abort_review = False
        self.cleaner._reload_lists()
        embedder = self._ensure_embedder()

        self.cleaner._check_list_exclusivity(embedder, threshold=0.92)
        self.cleaner.review_susp_entities(self.store, embedder=embedder,
                                          high_threshold=high_threshold,
                                          low_threshold=low_threshold,
                                          save_skipped=save_skipped,
                                          llm=self.llm,
                                          llm_batch_size=llm_batch_size,
                                          run_sync=self._run_sync)
        self.cleaner.review_blocked_entities(self.store)
        self.cleaner.review_good_entities(self.store)

        if recluster:
            self.recluster_lists(bl_clusters=bl_clusters, wl_clusters=wl_clusters)

    def cluster_blocklist(self, dry_run: bool = False) -> None:
        """Print a cluster summary of METHODOLOGY_BLOCKLIST and optionally rewrite
        blocklist.py with cluster-headed sections.

        dry_run=True  → print summary only, no file written.
        dry_run=False → rewrite METHODOLOGY_BLOCKLIST in config/blocklist.py.
        """
        self.cleaner.blocker.recluster(dry_run=dry_run)

    def recluster_lists(self, bl_clusters: int = 40, wl_clusters: int = 25) -> None:
        """Recluster blocklist and whitelist with SapBERT K-means."""
        embedder = self._ensure_embedder()

        print("\n[recluster] Blocklist...")
        self.cleaner.blocker.recluster_sapbert(embedder, n_clusters=bl_clusters)

        print("\n[recluster] Whitelist...")
        self.cleaner.blocker.recluster_whitelist_sapbert(embedder, n_clusters=wl_clusters)

    # ── Phase 4: Filtering ─────────────────────────────────────────────────────

    def run_clean_store(self, extra_blocked_entities: set[str] | None = None) -> None:
        """Remove out-of-scope entities, invalid predicates, and empty entities from the store."""
        cleaner = StoreCleaner(self.allowed_predicates, extra_blocked_entities)
        report = cleaner.clean(self.store)
        StoreCleaner.print_report(report)

    # ── Hierarchies ────────────────────────────────────────────────────────────

    def run_build_hierarchies(self, predefined_df: pd.DataFrame | None = None) -> None:
        """
        Build ClassHierarchy and MereologicalHierarchy from the ConceptStore.

        predefined_df – optional DataFrame with 'Class' and 'Parent class' columns.
                        When None, loads from PREDEFINED_HIERARCHY_FILE if configured.
        """
        if predefined_df is None and _PREDEFINED_HIERARCHY_FILE is not None:
            from pathlib import Path as _Path
            p = _Path(_PREDEFINED_HIERARCHY_FILE)
            if p.exists():
                predefined_df = pd.read_csv(p, usecols=["Class", "Parent class"])
                print(f"[Orchestrator] Loaded {len(predefined_df)} predefined edges from {p.name}")

        if predefined_df is not None:
            self.store.get_data(predefined_df)

        self.class_hier.get_data(self.store)
        self.mere_hier.get_data(self.store)
        self.class_hier.save()
        self.mere_hier.save()

        print(f"ClassHierarchy        : {len(self.class_hier.concepts)} concepts, "
              f"roots={self.class_hier.roots[:3]}")
        print(f"MereologicalHierarchy : {len(self.mere_hier.concepts)} concepts, "
              f"roots={self.mere_hier.roots[:3]}")

    # ── Enrichment ─────────────────────────────────────────────────────────────

    def run_store_fill(
        self,
        batch_size: int = 20,
        entity_batch: int = 5,
        max_entities: int | None = None,
        max_attrs_per_entity: int = 80,
    ) -> None:
        """Fill missing store attributes for each entity via LLM. Run after run_apply_mapping()."""
        print(f"Filling missing store attributes (concurrency={batch_size}, entity_batch={entity_batch})...")
        self._run_sync(self.store.fill_missing_attributes(
            self.llm, batch_size=batch_size, entity_batch=entity_batch,
            max_entities=max_entities, max_attrs_per_entity=max_attrs_per_entity,
        ))

    def run_fca(
        self,
        subtree_root: str | None = None,
        hierarchy=None,
        predicates: list | None = None,
        batch_size: int = 10,
    ) -> None:
        """
        Build FCA matrix → concept lattice → FCAHierarchy.

        subtree_root – restrict entities to the subtree of this concept.
        hierarchy    – which hierarchy to use for subtree lookup (default: class_hier).
        predicates   – restrict to these store predicates; None = all predicates.
        """
        hier = hierarchy or self.class_hier
        entities = hier.subtree_of(subtree_root) if subtree_root else None

        self.context_matrix.get_data(self.store, entities=entities, predicates=predicates)

        async def _internal():
            self.lattice.get_data_and_run_fca()
            await self.lattice.create_superclass_names(self.llm, batch_size=batch_size)

        self._run_sync(_internal())

        if self.lattice.lattice is not None:
            self.fca_hier.get_data(self.lattice.lattice)
            self.fca_hier.save()
            print(f"FCAHierarchy          : {len(self.fca_hier.concepts)} concepts, "
                  f"roots={self.fca_hier.roots[:3]}")

            added = 0
            for concept in self.lattice.lattice:
                name = getattr(concept, 'name', None)
                if not isinstance(name, str) or not name:
                    continue
                if hasattr(concept, 'name'):
                    concept.name = name.strip().title()
                    name = concept.name
                for entity in concept.extent:
                    self.class_hier._set_edge(str(entity), name)
                    added += 1
            if added:
                self.class_hier._df = self.class_hier._df.copy()
                self.class_hier.save()
                print(f"FCA → ClassHierarchy  : {added} extent→superclass edges merged.")
        else:
            print("FCAHierarchy          : skipped (empty lattice).")

    def run_matrix_nan_fill(self, batch_size: int = 20, entity_batch: int = 5) -> None:
        """Fallback: fill NaNs directly on the FCA context matrix (post-FCA)."""
        print(f"Evaluating missing relations (concurrency={batch_size}, entity_batch={entity_batch})...")
        self._run_sync(self.context_matrix.fill_nan(
            self.llm, batch_size=batch_size, entity_batch=entity_batch,
        ))

    def review_mere_relations(self, batch_size: int = 50) -> None:
        """
        LLM-validate every part_of edge in the mereological hierarchy.

        Each (child, part_of, parent) triple is classified as:
          keep  – valid anatomical/physical part_of → left unchanged
          is_a  – subtype relation mislabelled as part_of →
                  removed from mere_hier, added to class_hier
          drop  – wrong in both directions → removed from mere_hier

        Both hierarchies are saved after correction.
        Re-run after run_build_hierarchies() to keep corrections current.
        """
        df = self.mere_hier.df
        if df.empty:
            print("Mereological hierarchy is empty.")
            return

        # Collect all edges as (child, parent)
        triples: list[tuple[str, str]] = []
        for child in df.index:
            for parent in df.columns[df.loc[child] == 1.0]:
                triples.append((child, parent))

        if not triples:
            print("No part_of edges found.")
            return

        print(f"[review_mere_relations] Validating {len(triples)} part_of edges "
              f"in batches of {batch_size}...")

        async def _run():
            results = []
            total = (len(triples) + batch_size - 1) // batch_size
            for i in range(0, len(triples), batch_size):
                batch = triples[i:i + batch_size]
                bn = i // batch_size + 1
                print(f"  batch {bn}/{total} ({len(batch)} triples)...", flush=True)
                results.extend(await self.llm.validate_mere_batch(batch))
            return results

        results = self._run_sync(_run())

        kept = dropped = reclassified = 0
        for r in results:
            child, parent, verdict = r.child, r.parent, r.verdict.strip().lower()
            if verdict == "keep":
                kept += 1
                continue
            # Remove from mere_hier
            if child in self.mere_hier._df.index and parent in self.mere_hier._df.columns:
                self.mere_hier._df.at[child, parent] = 0.0
            if verdict == "is_a":
                self.class_hier._set_edge(child, parent)
                reclassified += 1
            else:
                dropped += 1

        self.mere_hier.save()
        self.class_hier.save()
        print(f"\n[review_mere_relations] done — "
              f"kept={kept}, reclassified as is_a={reclassified}, dropped={dropped}. "
              f"Both hierarchies saved.")

    # ── Export ─────────────────────────────────────────────────────────────────

    def export_to_owl(self, output_file=None) -> None:
        """Export ClassHierarchy, MereologicalHierarchy, and FCAHierarchy to OWL."""
        onto = OWLOntology.create()
        OntologyCurator(onto).from_hierarchies(self.class_hier, self.mere_hier, self.fca_hier)
        onto.save(self.dm, output_file)

    def run_curate_owl(
        self,
        input_file: str,
        output_file: str,
        import_bfo: bool = True,
        import_ro: bool = True,
        import_obi: bool = False,
        umls_api_key: str | None = None,
        umls_max_results: int = 3,
    ) -> None:
        """
        Curate an OWL file: assign IRIs, add labels, import BFO/RO/OBI,
        and optionally annotate with UMLS cross-references.
        """
        onto    = OWLOntology.load(input_file, self.dm)
        curator = OntologyCurator(onto)

        if import_bfo:
            curator.import_external(_BFO_URL)
        if import_ro:
            curator.import_external(_RO_URL)
        if import_obi:
            curator.import_external(_OBI_URL)

        curator.resolve_external_classes()
        curator.normalize_label_language(target_lang="en")
        curator.rename_iris()
        if umls_api_key:
            from wound_ontology.connectors.umls_connector import UMLSConnector
            umls = UMLSConnector(self.dm, api_key=umls_api_key)
            curator.umls_mapping(umls, max_results=umls_max_results)
        onto.save(self.dm, output_file)

    def run_enrich_external(
        self,
        input_file: str,
        output_file: str | None = None,
        onto_dir: str | None = None,
        dry_run: bool = False,
    ) -> None:
        """Patch wrong external IRIs and enrich external classes with labels.

        Reads *input_file*, applies IRI patches and label/definition lookup
        from local source-ontology files, then writes to *output_file*
        (defaults to overwriting *input_file*).

        onto_dir: path to folder containing bfo-core.owl, cob.owl, iao.owl,
                  obi.owl, pato.owl, go.obo.  Defaults to IMPORT_ONTO_DIR
                  from config/settings.py.
        """
        from rdflib import Graph
        from wound_ontology.owl.external_enricher import ExternalEnricher

        try:
            from config.settings import IMPORT_ONTO_DIR as _default_onto_dir
        except ImportError:
            _default_onto_dir = None

        resolved_onto_dir = onto_dir or _default_onto_dir
        if resolved_onto_dir is None:
            raise ValueError("onto_dir must be provided or IMPORT_ONTO_DIR set in config/settings.py")

        out = output_file or input_file
        with open(input_file) as fh:
            first = fh.read(300)
        fmt = "turtle" if first.strip().startswith("@") else "xml"

        print(f"Loading {input_file} …")
        g = Graph()
        g.parse(input_file, format=fmt)
        print(f"  {len(g)} triples, format={fmt}")

        stats = ExternalEnricher(resolved_onto_dir).enrich(g, dry_run=dry_run)

        if dry_run:
            print("\n[dry-run] No files written.")
            return

        g.serialize(out, format=fmt)
        print(f"\nWritten → {out}  ({len(g)} triples)")
        print(f"Stats: {stats}")

    def fetch_snomed_concepts(
        self,
        out_dir: str = "data/reference",
        prune_only: bool = False,
        rebuild_from_cache: bool = False,
    ) -> list[dict]:
        """Fetch wound-related SNOMED CT concepts from the UMLS UTS API.

        Requires UMLS_API_KEY in .env.

        out_dir:            where to write snomed_wound_concepts.json/csv and cache.
        prune_only:         re-apply semantic filters to existing output (no API calls).
        rebuild_from_cache: re-filter the BFS cache (no API calls, re-reads SEED_TERMS).

        Returns the final concept list.
        """
        from wound_ontology.connectors.snomed_fetcher import SnomedFetcher
        from pathlib import Path as _Path
        import os

        api_key = os.getenv("UMLS_API_KEY", "")
        root    = _Path(self.dm.base_path) if hasattr(self.dm, "base_path") and self.dm.base_path else _Path(".")
        out     = _Path(out_dir) if _Path(out_dir).is_absolute() else root / out_dir

        fetcher = SnomedFetcher(api_key=api_key, out_dir=out)
        if prune_only:
            return fetcher.prune()
        if rebuild_from_cache:
            return fetcher.rebuild_cache()
        return fetcher.fetch()

    def align_ontology(
        self,
        source_owl: str,
        target: str,
        out_dir: str,
        method: str = "sapbert+lexical",
        top_k: int = 5,
        close_thresh: float = 0.70,
        extend: bool = True,
        enrich: bool = True,
        dry_run: bool = False,
    ):
        """Align source_owl to any target ontology (SNOMED JSON, OBO, or OWL).

        target: path to the target file (.json / .obo / .owl).
        out_dir: directory for output files (candidates CSV, SSSOM TSV, extended OWL).
        method: "lexical", "sapbert", or "sapbert+lexical" (default).
        extend: mint WOND stubs for target concepts without a source match.
        enrich: copy rdfs:label, IAO def, and xrefs from target into matched source classes.

        Prints unmatched source classes (your own classes with no target mapping).
        Returns AlignmentResult for further inspection.
        """
        from wound_ontology.alignment.aligner import Aligner
        from pathlib import Path as _Path
        from datetime import datetime

        root = _Path(self.dm.base_path) if hasattr(self.dm, "base_path") and self.dm.base_path else _Path(".")

        def _resolve(p: str) -> _Path:
            pp = _Path(p)
            return pp if pp.is_absolute() else root / pp

        embedder = self._ensure_embedder() if "sapbert" in method else None
        aligner  = Aligner(_resolve(source_owl), embedder=embedder)
        result   = aligner.align(
            _resolve(target),
            method=method,
            top_k=top_k,
            close_thresh=close_thresh,
        )

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        out   = _resolve(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        aligner.write_candidates(result, out / f"alignment_candidates_{stamp}.csv")
        aligner.write_sssom(result,      out / f"alignment_{stamp}.sssom.tsv")

        ext_owl = out / f"source_extended_{stamp}.owl"
        if extend:
            aligner.extend(result, ext_owl, dry_run=dry_run)
        if enrich:
            enrich_path = ext_owl if ext_owl.exists() else _resolve(source_owl)
            aligner.enrich(result, enrich_path, dry_run=dry_run)

        if result.unmatched_source:
            print(f"\n[align_ontology] {len(result.unmatched_source)} source classes "
                  f"have no mapping in {_resolve(target).name}:")
            for iri in result.unmatched_source[:20]:
                label = next((k for k, v in result.source_label_index.items()
                              if v == iri), str(iri))
                print(f"  {label}")
            if len(result.unmatched_source) > 20:
                print(f"  ... and {len(result.unmatched_source) - 20} more")

        return result

    def run_reason_owl(
        self,
        input_file: str,
        output_file: str,
        infer_property_values: bool = True,
    ) -> None:
        """Run the Pellet/HermiT reasoner over an OWL file and save materialised inferences."""
        self.reasoner.reason(
            input_file,
            output_file,
            infer_property_values=infer_property_values,
        )

    def export_to_gexf(self, output_file: str, input_owl: str) -> None:
        """Export the ontology as GEXF for Gephi/Cytoscape."""
        self.graph_exporter.export_owl(input_owl, output_file)

    def build_knowledge_graph(self, input_owl: str):
        """Load an OWL/RDF file and return a KnowledgeGraph for SPARQL queries and graph traversal."""
        from wound_ontology.knowledge_graph import KnowledgeGraphRepository
        return KnowledgeGraphRepository().load(input_owl)


    def plot_hierarchy(
        self,
        hierarchy=None,
        output_file: str = "class_hierarchy.html",
        height: str = "900px",
        root: str | None = None,
        max_nodes: int = 300,
    ) -> None:
        """
        Render a hierarchy as an interactive pyvis graph in the notebook.

        hierarchy   – BaseHierarchy instance; defaults to class_hier.
        output_file – HTML file written alongside the notebook.
        root        – restrict to the subtree under this concept.
        max_nodes   – cap on number of nodes rendered (default 300).
                      The full graph has 4500+ nodes which crashes vis.js.
                      Use root= to focus on a subtree instead.
        """
        try:
            from pyvis.network import Network
        except ImportError:
            print("pyvis not installed — run: pip install pyvis")
            return
        import networkx as nx

        hier = hierarchy or self.class_hier
        df   = hier.df
        if df.empty:
            print("Hierarchy is empty — run the pipeline first.")
            return

        if root:
            subtree = hier.subtree_of(root)
            df = df.loc[
                df.index.isin(subtree),
                df.columns.isin(subtree),
            ]

        G = nx.DiGraph()
        for concept in df.index:
            for parent in df.columns[df.loc[concept] == 1.0]:
                G.add_edge(concept, parent)

        if G.number_of_nodes() > max_nodes:
            print(f"  Graph has {G.number_of_nodes()} nodes — truncating to {max_nodes}.")
            print(f"  Use root='<concept>' to focus on a subtree, e.g. root='Wound'.")
            keep = list(G.nodes)[:max_nodes]
            G = G.subgraph(keep).copy()

        from pathlib import Path as _Path
        out = _Path(output_file)

        net = Network(
            height=height,
            width="100%",
            directed=True,
            cdn_resources="in_line",
        )
        net.from_nx(G)
        out.write_text(net.generate_html(), encoding="utf-8")
        print(f"[plot_hierarchy] {G.number_of_nodes()} nodes, "
              f"{G.number_of_edges()} edges → {out}")
