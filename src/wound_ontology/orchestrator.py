from __future__ import annotations
import asyncio
import os
import pandas as pd
from dotenv import load_dotenv
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.llm.llm_client import LLMClient
from wound_ontology.connectors.pubmed_connector import PubmedConnector
from wound_ontology.connectors.bfo_connector import BFOConnector
from wound_ontology.cache.concept_store import ConceptStore
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy
from wound_ontology.hierarchies.fca_hierarchy import FCAHierarchy
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.fca.concept_lattice import ConceptLattice
from wound_ontology.mappers.normalization_mapper import TermMapper
from wound_ontology.export.owl_exporter import OWLExporter

load_dotenv()

try:
    from config.settings import PREDICATE_DEFINITIONS as _PREDICATE_DEFINITIONS
except ImportError:
    _PREDICATE_DEFINITIONS = {}

_DEFAULT_ALLOWED_PREDICATES = [
    "is_a", "part_of", "has_quality", "occurs_in",
    "caused_by", "is_treatment_for",
]


class Orchestrator:
    def __init__(
        self,
        google_api_key: str = None,
        entrez_email: str = None,
        allowed_predicates: list = None,
        base_path=None,
    ):
        google_api_key     = google_api_key     or os.getenv("GOOGLE_API_KEY", "")
        entrez_email       = entrez_email       or os.getenv("ENTREZ_EMAIL", "")
        allowed_predicates = allowed_predicates or _DEFAULT_ALLOWED_PREDICATES

        self.dm = DataManager(**({"base_path": base_path} if base_path else {}))
        self.llm = LLMClient(google_api_key)

        self.pubcon        = PubmedConnector(self.dm, entrez_email)
        self.bfo           = BFOConnector(self.dm)
        self.store         = ConceptStore(self.dm, "concept_store")
        self.class_hier    = ClassHierarchy(self.dm)
        self.mere_hier     = MereologicalHierarchy(self.dm)
        self.fca_hier      = FCAHierarchy(self.dm)
        self.context_matrix = ContextMatrix(self.dm, "context_matrix")
        self.lattice       = ConceptLattice(self.dm, self.context_matrix)
        self.term_mapper   = TermMapper(self.dm)
        self.exporter      = OWLExporter(
            self.dm,
            class_hierarchy=self.class_hier,
            mereological_hierarchy=self.mere_hier,
            fca_hierarchy=self.fca_hier,
        )
        self.allowed_predicates = allowed_predicates

    def _run_sync(self, coroutine):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coroutine)

    # ── Extraction ─────────────────────────────────────────────────────────────

    def run_pubmed_search(self, queries: str | list[str], max_results_per_query: int = 50):
        """Fetch abstracts for one or more PubMed queries, merging into one database."""
        self.pubcon.get_data(queries, max_results_per_query)

    def run_extract_to_store(self, batch_size=10, use_bfo_attributes=True):
        """
        Extract entities from PubMed abstracts → ConceptStore.

        use_bfo_attributes – if True, BFO anchor classes are passed to the LLM
                             as candidate is_a targets so every entity gets
                             classified against them.
        """
        bfo_anchors = self.bfo.get_anchor_names() if use_bfo_attributes else []
        if bfo_anchors:
            print(f"Using BFO anchor classes as is_a target candidates: {bfo_anchors}")
        print("Starting LLM Extraction...")
        self._run_sync(self.store.add_llm_extracts(
            self.pubcon.database, self.llm, self.allowed_predicates, batch_size,
            extra_targets=bfo_anchors,
            predicate_definitions=_PREDICATE_DEFINITIONS,
        ))

    # ── Hierarchies ────────────────────────────────────────────────────────────

    def run_build_hierarchies(self, predefined_df: pd.DataFrame = None, normalize: bool = True) -> None:
        """
        Build ClassHierarchy and MereologicalHierarchy from the ConceptStore.

        predefined_df – optional DataFrame with 'Class' and 'Parent class' columns.
                        Ingested into the store as is_a triples before normalization.
        normalize     – if True, build LLM-based term normalization mapping and
                        apply it to the whole store before reading hierarchies.
        """
        if predefined_df is not None:
            self.store.get_data(predefined_df)

        if normalize:
            all_terms = list({
                term
                for pmid_data in self.store.dict.values()
                for entity, attrs in pmid_data.get("entities", {}).items()
                for term in [entity] + [
                    triple.split(":", 1)[1].strip()
                    for triple in attrs.keys()
                    if ":" in triple
                ]
            })
            self._run_sync(self.term_mapper.get_data(all_terms, self.llm))
            self.store.normalize(self.term_mapper)

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
        subtree_root: str = None,
        hierarchy=None,
        predicates: list = None,
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
                self.class_hier.save()
                print(f"FCA → ClassHierarchy  : {added} extent→superclass edges merged.")
        else:
            print("FCAHierarchy          : skipped (empty lattice).")

    def run_matrix_nan_fill(self, batch_size=15):
        print(f"Evaluating missing relations (Parallel Waves of {batch_size})...")
        self._run_sync(self.context_matrix.fill_nan(self.llm, batch_size=batch_size))

    # ── Export ─────────────────────────────────────────────────────────────────

    def export_to_owl(self):
        self.exporter.create_owl()

    # ── Full pipeline ──────────────────────────────────────────────────────────

    def run_full_pipeline(self, query, max_results=50, predefined_df=None):
        self.run_pubmed_search(query, max_results)
        self.run_extract_to_store()
        self.run_build_hierarchies(predefined_df)
        self.export_to_owl()
