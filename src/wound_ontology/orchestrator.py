from __future__ import annotations
import asyncio
import os
import pandas as pd
from dotenv import load_dotenv
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.llm.llm_client import LLMClient
from wound_ontology.connectors.pubmed_connector import PubmedConnector
from wound_ontology.connectors.bfo_connector import BFOConnector
from wound_ontology.connectors.ro_connector import ROConnector
from wound_ontology.connectors.obi_connector import OBIConnector
from wound_ontology.store.concept_store import ConceptStore
from wound_ontology.store.store_cleaner import StoreCleaner
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy
from wound_ontology.hierarchies.fca_hierarchy import FCAHierarchy
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.fca.concept_lattice import ConceptLattice
from wound_ontology.mappers.normalization_mapper import TermMapper
from wound_ontology.mappers.mapping_cleaner import MappingCleaner
from wound_ontology.export.owl_ontology import OWLOntology
from wound_ontology.export.owl_reasoner import OWLReasoner
from wound_ontology.export.gexf_exporter import GEXFExporter
from wound_ontology.graph.knowledge_graph import KnowledgeGraph

load_dotenv()

try:
    from config.settings import (
        PREDICATE_DEFINITIONS as _PREDICATE_DEFINITIONS,
        PREDEFINED_HIERARCHY_FILE as _PREDEFINED_HIERARCHY_FILE,
    )
except ImportError:
    _PREDICATE_DEFINITIONS = {}
    _PREDEFINED_HIERARCHY_FILE = None

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
        self.bfo           = BFOConnector(self.dm)
        self.ro            = ROConnector(self.dm)
        self.obi           = OBIConnector(self.dm)
        self.store         = ConceptStore(self.dm, "concept_store")
        self.cleaner       = StoreCleaner(self.allowed_predicates)
        self.class_hier    = ClassHierarchy(self.dm)
        self.mere_hier     = MereologicalHierarchy(self.dm)
        self.fca_hier      = FCAHierarchy(self.dm)
        self.context_matrix = ContextMatrix(self.dm, "context_matrix")
        self.lattice       = ConceptLattice(self.dm, self.context_matrix)
        self.entity_mapper   = TermMapper(self.dm, file_name="entity_mapping", mapper_name="Entity mapper")
        self.target_mapper   = TermMapper(self.dm, file_name="target_mapping", mapper_name="Target mapper")
        self.mapping_cleaner = MappingCleaner(self.entity_mapper, self.target_mapper, self.allowed_predicates)
        self.reasoner      = OWLReasoner()
        self.gexf          = GEXFExporter()

    def _run_sync(self, coroutine):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coroutine)

    # ── Extraction ─────────────────────────────────────────────────────────────

    def run_pubmed_search(self, queries: str | list[str], max_results_per_query: int = 200):
        """Fetch abstracts for one or more PubMed queries, merging into one database."""
        self.pubcon.get_data(queries, max_results_per_query)

    async def _normalization_milestone(self, store) -> None:
        """
        Periodic callback: clean junk, build term mappings for review.
        Does NOT apply normalize() — call pipeline.mapping_cleaner.apply(store) after review.
        Safe to await mid-extraction because _dict writes only happen in the calling loop.
        """
        # 1. Remove blocklisted entities and rogue predicates
        cleaner = StoreCleaner(self.allowed_predicates)
        report = cleaner.clean(store)
        StoreCleaner.print_report(report)

        # 2. Collect entity names and attribute targets separately
        entity_terms: list[str] = []
        target_terms: list[str] = []
        seen_entities: set[str] = set()
        seen_targets: set[str] = set()
        for pmid_data in store.dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                if entity not in seen_entities:
                    entity_terms.append(entity)
                    seen_entities.add(entity)
                for triple in attrs.keys():
                    if ":" in triple:
                        tgt = triple.split(":", 1)[1].strip()
                        if tgt not in seen_targets:
                            target_terms.append(tgt)
                            seen_targets.add(tgt)

        # 3. Build mappings for new terms only (mappers skip already-known terms)
        await self.entity_mapper.get_data(entity_terms, self.llm)
        await self.target_mapper.get_data(target_terms, self.llm)

        print("\n[Orchestrator] Mapping ready for review — "
              "run pipeline.mapping_cleaner.review_mappings() then "
              "pipeline.mapping_cleaner.apply(pipeline.store).")

    def run_extract_to_store(self, batch_size=10, use_bfo_attributes=True,
                             max_consecutive_failures=20, max_vocab_hints=300,
                             clean_after: bool = True,
                             normalize_every: int = 1000):
        """
        Extract entities from PubMed abstracts → ConceptStore.

        use_bfo_attributes       – if True, BFO anchor classes are passed to the LLM
                                   as candidate is_a targets so every entity gets
                                   classified against them.
        max_consecutive_failures – circuit breaker: abort if this many results in a row
                                   are permanent failures (all retries exhausted).
        max_vocab_hints          – cap on targets/attributes sent per prompt (most frequent).
        clean_after              – if True, run StoreCleaner immediately after extraction.
        normalize_every          – run clean+normalize+apply every N new entity mentions
                                   during extraction so vocab hints stay compact.
                                   0 = disable mid-extraction normalization.
        """
        bfo_anchors = self.bfo.get_anchor_names() if use_bfo_attributes else []
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
            on_milestone=self._normalization_milestone if normalize_every > 0 else None,
        ))
        if clean_after:
            print("\n[Orchestrator] Running post-extraction store clean...")
            self.run_clean_store()

    def run_clean_store(self, extra_blocked_entities: set[str] | None = None) -> None:
        """Remove out-of-scope entities and invalid predicates from the ConceptStore."""
        cleaner = StoreCleaner(self.allowed_predicates, extra_blocked_entities)
        report = cleaner.clean(self.store)
        StoreCleaner.print_report(report)

    def llm_scan_entities(
        self,
        top_n: int = 1000,
        llm_batch_size: int = 150,
        display_batch_size: int = 500,
        threshold_pct: float = 20.0,
    ) -> None:
        """LLM-powered scan of the top_n most frequent entities."""
        cleaner = StoreCleaner(self.allowed_predicates)
        cleaner.llm_scan_entities(
            self.store, self.llm,
            top_n=top_n,
            llm_batch_size=llm_batch_size,
            display_batch_size=display_batch_size,
            threshold_pct=threshold_pct,
        )

    # ── Hierarchies ────────────────────────────────────────────────────────────

    def run_build_hierarchies(self, predefined_df: pd.DataFrame | None = None, normalize: bool = True) -> None:
        """
        Build ClassHierarchy and MereologicalHierarchy from the ConceptStore.

        predefined_df – DataFrame with 'Class' and 'Parent class' columns.
                        When None, automatically loads from PREDEFINED_HIERARCHY_FILE
                        (data/raw/predefined_concept_hierarchy.csv) if it exists.
        normalize     – if True, build LLM-based term normalization mapping and
                        apply it to the whole store before reading hierarchies.
        """
        if predefined_df is None and _PREDEFINED_HIERARCHY_FILE is not None:
            from pathlib import Path as _Path
            p = _Path(_PREDEFINED_HIERARCHY_FILE)
            if p.exists():
                predefined_df = pd.read_csv(p, usecols=["Class", "Parent class"])
                print(f"[Orchestrator] Loaded {len(predefined_df)} predefined edges from {p.name}")

        if predefined_df is not None:
            self.store.get_data(predefined_df)

        if normalize:
            entity_terms = list({
                entity
                for pmid_data in self.store.dict.values()
                for entity in pmid_data.get("entities", {}).keys()
            })
            target_terms = list({
                triple.split(":", 1)[1].strip()
                for pmid_data in self.store.dict.values()
                for attrs in pmid_data.get("entities", {}).values()
                for triple in attrs.keys()
                if ":" in triple
            })
            self._run_sync(self.entity_mapper.get_data(entity_terms, self.llm))
            self._run_sync(self.target_mapper.get_data(target_terms, self.llm))
            self.store.normalize(
                entity_mapper=self.entity_mapper,
                target_mapper=self.target_mapper,
            )

        self.class_hier.get_data(self.store)
        self.mere_hier.get_data(self.store)

        self.class_hier.save()
        self.mere_hier.save()

        print(f"ClassHierarchy        : {len(self.class_hier.concepts)} concepts, "
              f"roots={self.class_hier.roots[:3]}")
        print(f"MereologicalHierarchy : {len(self.mere_hier.concepts)} concepts, "
              f"roots={self.mere_hier.roots[:3]}")

    # ── FCA ────────────────────────────────────────────────────────────────────

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
        predicates   – restrict to these store predicates (e.g. ['has_quality']).
                       None = all predicates.
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

            # Wire extent entities → named FCA superclass into ClassHierarchy
            # so that FCA-derived groupings appear in the final OWL alongside
            # the predefined taxonomy.
            added = 0
            for concept in self.lattice.lattice:
                name = getattr(concept, 'name', None)
                if not isinstance(name, str) or not name:
                    continue
                # Normalise casing to match BaseHierarchy convention
                if hasattr(concept, 'name'):
                    concept.name = name.strip().title()
                    name = concept.name
                for entity in concept.extent:
                    self.class_hier._set_edge(str(entity), name)
                    added += 1
            if added:
                self.class_hier._df = self.class_hier._df.copy()  # defragment
                self.class_hier.save()
                print(f"FCA → ClassHierarchy  : {added} extent→superclass edges merged.")
        else:
            print("FCAHierarchy          : skipped (empty lattice).")

    def run_store_fill(self, batch_size: int = 20, entity_batch: int = 5, max_entities: int | None = None, max_attrs_per_entity: int = 80) -> None:
        """
        Fill every missing attribute for each entity in the ConceptStore via LLM.
        Run this AFTER normalize() and BEFORE FCA so enrichment flows everywhere.
        """
        print(f"Filling missing store attributes (concurrency={batch_size}, entity_batch={entity_batch})...")
        self._run_sync(self.store.fill_missing_attributes(
            self.llm, batch_size=batch_size, entity_batch=entity_batch,
            max_entities=max_entities, max_attrs_per_entity=max_attrs_per_entity,
        ))

    def run_matrix_nan_fill(self, batch_size=20, entity_batch=5):
        """Fallback: fill NaNs directly on the FCA context matrix (post-FCA)."""
        print(f"Evaluating missing relations (concurrency={batch_size}, entity_batch={entity_batch})...")
        self._run_sync(self.context_matrix.fill_nan(self.llm, batch_size=batch_size, entity_batch=entity_batch))

    # ── Export ─────────────────────────────────────────────────────────────────

    def export_to_owl(self, output_file=None):
        onto = OWLOntology()
        onto.get_data(self.class_hier, self.mere_hier, self.fca_hier)
        onto.save(output_file)

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
        Curate an OWL file: assign proper ontology IRIs (WOND_NNNNNNN),
        add rdfs:labels, import BFO/RO/OBI via connectors, and optionally
        annotate with UMLS cross-references.

        For reasoning over the curated file use run_reason_owl().
        """
        onto = OWLOntology().load(input_file)

        connectors = []
        if import_bfo:
            connectors.append(self.bfo)
        if import_ro:
            connectors.append(self.ro)
        if import_obi:
            connectors.append(self.obi)
        if connectors:
            onto.import_connector(*connectors)

        onto.resolve_external_classes()
        onto.normalize_label_language(target_lang="en")
        onto.rename_iris()
        if umls_api_key:
            from wound_ontology.connectors.umls_connector import UMLSConnector
            umls = UMLSConnector(self.dm, api_key=umls_api_key)
            onto.umls_mapping(umls, max_results=umls_max_results)
        onto.save(output_file)

    def run_reason_owl(
        self,
        input_file: str,
        output_file: str,
        infer_property_values: bool = True,
    ) -> None:
        """
        Run the Pellet/HermiT reasoner over an enriched OWL file and save
        the result with materialised inferences.

        Requires Java and JPype. Call AFTER run_curate_owl().
        """
        self.reasoner.reason(
            input_file,
            output_file,
            infer_property_values=infer_property_values,
        )

    def export_to_gexf(
        self,
        output_file: str,
        input_owl: str | None = None,
    ) -> None:
        """
        Export the wound ontology as a GEXF file for Gephi / Cytoscape.

        Two modes:
          input_owl=None   — build the KnowledgeGraph from the in-memory
                             ConceptStore + class/mereological/FCA hierarchies.
                             Use this right after run_build_hierarchies() /
                             run_fca(), without needing an OWL file.

          input_owl="path" — parse the given OWL/RDF file with rdflib. Use
                             this after export_to_owl() or run_curate_owl()
                             to get the fully enriched graph with WOND IRIs.

        The resulting GEXF encodes node attributes (label, iri, node_type,
        namespace) and edge attributes (predicate) so Gephi can colour and
        filter by relationship type and ontology namespace.
        """
        if input_owl:
            self.gexf.export_owl(input_owl, output_file)
        else:
            self.gexf.export_store(
                self.store,
                self.class_hier,
                self.mere_hier,
                self.fca_hier,
                output_file=output_file,
            )

    def build_knowledge_graph(self, input_owl: str | None = None) -> KnowledgeGraph:
        """
        Build and return a KnowledgeGraph for programmatic use (SPARQL,
        subgraph extraction, neighbourhood inspection).

        input_owl=None  — from in-memory store + hierarchies.
        input_owl="…"   — from an OWL/RDF file (supports SPARQL).
        """
        if input_owl:
            return KnowledgeGraph().from_owl(input_owl)
        return KnowledgeGraph().from_store(
            self.store, self.class_hier, self.mere_hier, self.fca_hier
        )

    # ── Full pipeline ──────────────────────────────────────────────────────────

    def run_full_pipeline(self, query, max_results=50, predefined_df=None):
        self.run_pubmed_search(query, max_results)
        self.run_extract_to_store()
        self.run_build_hierarchies(predefined_df)
        self.export_to_owl()
