from __future__ import annotations
"""Orchestrator glue code for the wound ontology pipeline."""
import asyncio
import os
import re
from collections import Counter
import pandas as pd
from wound_ontology.utils.string_utils import smart_title
from wound_ontology.hierarchies.base_hierarchy import SOURCE_FCA as _SOURCE_FCA
from wound_ontology.hierarchies.base_hierarchy import SOURCE_CURATED as _SOURCE_CURATED
from dotenv import load_dotenv
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.llm.llm_client import LLMClient
from wound_ontology.connectors.pubmed_connector import PubmedConnector
from wound_ontology.store.concept_store import ConceptStore
from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy, ClassHierarchyView
from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy
from wound_ontology.hierarchies.fca_hierarchy import FCAHierarchy
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.fca.concept_lattice import ConceptLattice
from wound_ontology.embedding.embedder import Embedder
from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
from wound_ontology.mappers.term_mapper import TermMapper, canonical_rank
from wound_ontology.owl import OWLOntology, OntologyCurator
from wound_ontology.reasoning import OWLReasoner
from wound_ontology.graph_visualizer import GraphVisualizer

load_dotenv()

try:
    from config.settings import (
        ALLOWED_PREDICATES as _DEFAULT_ALLOWED_PREDICATES,
        PREDICATE_DEFINITIONS as _PREDICATE_DEFINITIONS,
        BFO_OWL_URL as _BFO_URL,
        RO_OWL_URL as _RO_URL,
        OBI_OWL_URL as _OBI_URL,
    )
except ImportError as _exc:
    # Not harmless. _PREDICATE_DEFINITIONS feeds the extraction prompt's rule
    # block; empty means the model is asked to pick predicates with no guidance
    # at all, and the only symptom is worse extraction nobody attributes to this.
    import warnings as _warnings
    _warnings.warn(
        f"config.settings could not be imported ({_exc}). Falling back to EMPTY "
        "predicate definitions — extraction prompts will carry no predicate "
        "rules. Fix the import before trusting any run.",
        RuntimeWarning, stacklevel=2,
    )
    _DEFAULT_ALLOWED_PREDICATES = ["is_a"]
    _PREDICATE_DEFINITIONS = {}
    _BFO_URL = "http://purl.obolibrary.org/obo/bfo.owl"
    _RO_URL  = "http://purl.obolibrary.org/obo/ro.owl"
    _OBI_URL = "http://purl.obolibrary.org/obo/obi.owl"

# NOTE: _DEFAULT_ALLOWED_PREDICATES now comes from config.settings above. It used
# to be a five-entry literal defined right here, whose own comment pointed at
# config/settings.py without importing it. The cleaner then DELETED any attribute
# whose predicate was not on this list (the store's view drops it now, rule 86), so that literal silently deleted 19 of the
# 26 relation types two-stage extraction emits -- has_part, participates_in,
# inheres_in, has_disposition, the BFO backbone MILD is built on -- leaving only
# is_a, part_of and has_quality. Measured on a 142-abstract pilot: 316 relation
# cells destroyed, reported only as a "rogue predicate" tally nobody reads.
# On the import-failure path the fallback is now ["is_a"] rather than a plausible
# short list: losing everything is noticed, losing 19 of 26 is not.


def _slugify(name: str) -> str:
    """Subtree root -> a file-name fragment. Used to scope per-analysis artifacts."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    return slug or "unnamed"



#: A placed term becomes a class only when this many abstracts mention it
#: (curator, 2026-10-02). Below it the placement stays on record, unbuilt.
PLACEMENT_MIN_ABSTRACTS = 2

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
        # The term dict is built before the store, because every decision about
        # a term lives in it and the store is read THROUGH it (rule 51). Scope
        # comes from it alone: no list, no Blocker (rule 86). The cleaned store
        # is the view, `store.cleaned`, recomputed on every read.
        _term_mapping      = TermMappingAndGate(self.dm, file_name="term_mapping")
        self.store         = ConceptStore(self.dm, "concept_store", terms=_term_mapping)
        self.store.allowed_predicates = self.allowed_predicates
        # The class hierarchy is a VIEW (2026-10-21): derived from its sources on
        # first use, never read from or written to a matrix CSV. See
        # ClassHierarchyView and refresh_class_hierarchy().
        self._class_hier: ClassHierarchyView | None = None
        # The mereological hierarchy left the pipeline the same day: its text
        # part_of edges were never exported (rule 66). Built on demand only.
        self._mere_hier: MereologicalHierarchy | None = None
        self.context_matrix = ContextMatrix(self.dm, "context_matrix")
        # Replaced per analysis by run_fca; these are the "no analysis yet" ones.
        # `lattices` / `fca_hiers` keep every analysis of this session by subtree,
        # while `lattice` / `fca_hier` always point at the most recent.
        self.fca_hier      = FCAHierarchy(self.dm)
        self.lattice       = ConceptLattice(self.dm, self.context_matrix)
        self.lattices: dict[str, ConceptLattice] = {}
        self.fca_hiers: dict[str, FCAHierarchy] = {}
        # What the last run_fca did with every name it made (rule 79): the
        # head-word rule's verdicts with reasons, the names withheld before it,
        # and the report they were written to. Empty until run_fca has named.
        self.fca_head_rule: dict = {}
        self.term_mapper     = TermMapper(_term_mapping, name="Term mapper")
        self._embedder: Embedder | None = None
        self.reasoner      = OWLReasoner()
        self.graph_exporter = GraphVisualizer()

    # ── Internal helpers ───────────────────────────────────────────────────────

    # ── The class hierarchy as a view (2026-10-21) ─────────────────────────────

    @property
    def class_hier(self) -> ClassHierarchyView:
        """The class hierarchy VIEW, derived from its sources on first use.

        Curator, 2026-10-21: the hierarchies are not needed as a pipeline stage;
        the concept store read through the mapping-and-gate register is what the
        FCA works on. The is_a structure the FCA needs (wound subtree, conceptual
        scaling) and the extension needs (subclass edges) is therefore a view of
        WONT + MILD, the store, the register's placements and the accepted FCA
        slices -- built here when first asked for, rebuilt by
        refresh_class_hierarchy() or the edge gate, never loaded from disk.
        """
        if self._class_hier is None:
            self.refresh_class_hierarchy()
        return self._class_hier

    @class_hier.setter
    def class_hier(self, value) -> None:
        self._class_hier = value

    @property
    def mere_hier(self) -> MereologicalHierarchy:
        """The mereological hierarchy, built in memory on demand.

        Not a pipeline stage any more (2026-10-21): its text part_of edges were
        never exported (rule 66), and the FCA reads part_of from the store. Kept
        for review_mere_relations and the inspection scripts.
        """
        if self._mere_hier is None:
            self._mere_hier = MereologicalHierarchy(self.dm)
            self._mere_hier.get_data(self.store)
        return self._mere_hier

    @mere_hier.setter
    def mere_hier(self, value) -> None:
        self._mere_hier = value

    def _run_sync(self, coroutine):
        """Run a coroutine from sync code, in a notebook or under pytest.

        The old body was ``asyncio.get_event_loop().run_until_complete(...)``.
        ``get_event_loop()`` is deprecated and no longer creates a loop when the
        thread has none — it raises ``RuntimeError: There is no current event
        loop``. That never showed up in a notebook (Jupyter always has a loop,
        and cell 4 calls ``nest_asyncio.apply()``) but it breaks under pytest as
        soon as pytest-asyncio has torn its loop down, which made the failure
        depend on test *order*: these tests passed alone and failed in the full
        suite. Nobody saw it because the integration tests that trigger it were
        being skipped.

        Inside a running loop we must use ``run_until_complete`` rather than
        ``asyncio.run`` — that is the re-entrant path nest_asyncio patches, and
        ``asyncio.run`` would refuse outright.
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:  # silent-ok: asyncio offers no has_running_loop();
            running = None    # the RuntimeError IS the answer "no loop", and the
                              # next line branches on it rather than continuing.

        if running is not None:
            # Notebook / nest_asyncio: re-enter the loop we are already inside.
            return running.run_until_complete(coroutine)

        # No loop in this thread: asyncio.run creates one and disposes of it
        # cleanly, which is what pytest between-test teardown expects.
        return asyncio.run(coroutine)

    def _ensure_embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder()
        return self._embedder

    def _collect_store_terms_with_freq(self, store=None) -> dict[str, int]:
        store = store or self.store
        freq: dict[str, int] = {}
        # The terms as they are WRITTEN, before the mapping merges them: the
        # build proposes those merges (rule 51's view, `mapped=False`).
        for _, entities in store.view(mapped=False, include_rejected=True):
            seen_in_pmid: set[str] = set()
            for entity, attrs in entities.items():
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
        """Periodic callback during extraction: rebuild the term mapping. Nothing
        is cleaned: the view reads scope from the term dict (rule 86)."""
        freq = self._collect_store_terms_with_freq(store)
        self.term_mapper.build_from_embeddings(
            list(freq.keys()),
            embedder=self._ensure_embedder(),
            similarity_threshold=0.95,
            frequencies=freq,
        )
        print("\n[Orchestrator] Mapping milestone complete.")

    # ── Phase 1: Extraction ────────────────────────────────────────────────────
    # Nothing is filtered at extraction (rule 86): every string is stored as
    # extracted, and a number with a unit gets `out` from the term dict's
    # `noise_rule`, as a verdict.

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

        use_bfo_attributes and max_vocab_hints are inert here: this always runs the
        schema-constrained two-stage path, which prompts with the generated BFO
        category tree rather than with store vocabulary. Both are kept in the
        signature because the deprecated free-text path still consumes them, and
        both announce their inertness rather than pretending to work.
        """
        # The prompt is built from config/extraction_schema.yaml, a generated
        # snapshot of WONT + MILD. Regenerate it here if the ontologies have
        # moved since, so no abstract is ever extracted against a WONT older
        # than the one on disk. The generated Pydantic module was already
        # imported when this process started, and a Python enum cannot be
        # swapped under the eight modules that bound it, so a rebuild that
        # changed anything stops here rather than extract with the old one.
        from wound_ontology.llm import schema_builder
        outcome = schema_builder.ensure_current()
        if outcome == "rewritten":
            raise RuntimeError(
                "[Orchestrator] The extraction schema was REGENERATED from "
                "WONT + MILD and differs from the one this process imported. "
                "Nothing was extracted. Restart the Python process (or kernel) "
                "and run again; it will then extract with the current schema."
            )

        # add_llm_extracts runs the schema-constrained two-stage path, whose prompts
        # carry the generated BFO category tree rather than store vocabulary. Loading
        # bfo.owl here (~11s) only to pass labels nothing reads would be dead work, so
        # the load is skipped and the inert flag is stated rather than left implied.
        bfo_anchors: list[str] = []
        if use_bfo_attributes:
            print("[Orchestrator] use_bfo_attributes has no effect on the "
                  "schema-constrained path: the model is given the generated BFO "
                  "category tree, not store vocabulary hints. bfo.owl not loaded.")
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

    def ontology_labels(self, sources=None) -> set[str]:
        """Every name a WONT or MILD *class* answers to: its rdfs:label and its
        IAO_0000118 alternative terms.

        Used as SapBERT anchors, so a store term that means the same as an
        existing class is mapped onto it rather than minted beside it, and by
        the FCA naming guard to decide whether a label is one the ontologies
        know.

        Two exclusions, both decided 2026-09-16. Individuals are skipped: the
        classification grades (`Burn classification grade I`, `Zone of
        stasis`, the CDC and IWII grades) are owl:NamedIndividuals by design,
        and a store term mapped onto one of them would be mapped onto an
        instance, not a class. Alt terms are included: when a label is demoted
        to an alt term (`2nd degree burn` became one of `Second-degree burn
        wound`) the concept has not left the ontology, and the anchor must not
        leave with it.
        """
        from rdflib import OWL, RDF, RDFS, URIRef

        from wound_ontology.utils.rdf_io import parse_graph
        alt = URIRef("http://purl.obolibrary.org/obo/IAO_0000118")
        if sources is None:
            from wound_ontology.hierarchies.curated_seed import default_curated_sources
            sources, _ = default_curated_sources()
        labels: set[str] = set()
        for src in sources:
            g = parse_graph(src)
            individuals = set(g.subjects(RDF.type, OWL.NamedIndividual))
            for pred in (RDFS.label, alt):
                for s, _, o in g.triples((None, pred, None)):
                    if s in individuals:
                        continue
                    text = str(o).strip()
                    if text:
                        labels.add(text)
        return labels

    def ontology_categories(self, skeleton=None) -> dict[str, str]:
        """{ontology label -> BFO category}, read from the skeleton TBox.

        WONT and MILD alone do not resolve: `Necrosis` reaches its category only
        through BFO classes that live in the import closure. The skeleton already
        carries that backbone for the reasoner gate, so it is what answers here.

        A label whose chain reaches no category is simply absent — unknown, not
        uncategorised, and callers must treat it that way.
        """
        from pathlib import Path

        from rdflib import RDFS, URIRef

        from wound_ontology.llm.extraction_models import CATEGORY_IRI
        from wound_ontology.utils.rdf_io import parse_graph

        path = skeleton or (Path(__file__).resolve().parents[2]
                            / "output" / "owl" / "skeleton_tbox.ttl")
        g = parse_graph(path)
        by_iri = {v: k for k, v in CATEGORY_IRI.items()}
        out: dict[str, str] = {}
        for subj, _, obj in g.triples((None, RDFS.label, None)):
            label = str(obj).strip()
            if not label or label in out:
                continue
            seen, stack = set(), [subj]
            while stack:
                node = stack.pop()
                if str(node) in by_iri:
                    out[label] = by_iri[str(node)]
                    break
                for parent in g.objects(node, RDFS.subClassOf):
                    if isinstance(parent, URIRef) and parent not in seen:
                        seen.add(parent)
                        stack.append(parent)
        return out

    def ontology_definitions(self, sources=None) -> dict[str, str]:
        """{ontology label -> its IAO_0000115 textual definition}.

        This is what the anchor adjudication judges on. The LABEL is what misled
        SapBERT into proposing `clean wound classification grade` ->
        `clean-contaminated wound classification grade`; the definition is where
        the two come apart. A class with no definition is simply absent, and the
        adjudicator is told so rather than shown an empty string.
        """
        from rdflib import RDFS, URIRef

        from wound_ontology.utils.rdf_io import parse_graph
        if sources is None:
            from wound_ontology.hierarchies.curated_seed import default_curated_sources
            sources, _ = default_curated_sources()
        iao = URIRef("http://purl.obolibrary.org/obo/IAO_0000115")
        out: dict[str, str] = {}
        for src in sources:
            g = parse_graph(src)
            for subj, _, obj in g.triples((None, iao, None)):
                text = str(obj).strip()
                if not text:
                    continue
                for label in g.objects(subj, RDFS.label):
                    key = str(label).strip()
                    if key and key not in out:
                        out[key] = text
        return out

    def ontology_parents(self) -> dict[str, list[str]]:
        """{ontology label -> the labels of its named superclasses}.

        Context for the anchor adjudication where a class carries no textual
        definition — only 8 of the 20 classes in the current content bucket do.
        A parent is weaker evidence than a definition but it is the ontology's
        own word on what kind of thing the class is, which is exactly what the
        model is being asked to weigh the label against.
        """
        from wound_ontology.hierarchies.curated_seed import (
            default_curated_sources, load_curated_edges,
        )

        sources, label_sources = default_curated_sources()
        df = load_curated_edges(sources, label_sources)
        out: dict[str, list[str]] = {}
        for child, parent in zip(df["Class"], df["Parent class"]):
            out.setdefault(str(child), []).append(str(parent))
        return out

    def store_typings(self) -> dict[str, set[str]]:
        """{store term -> every BFO category any abstract typed it as}.

        Stage-1 typing runs per abstract, so one term can carry several. This
        is the raw record; `store_categories` reconciles it.
        """
        from wound_ontology.llm.category_vocab import declared_category
        from wound_ontology.utils.string_utils import smart_title

        typings: dict[str, set[str]] = {}
        # UNMAPPED: the typing belongs to the term as written. Read through the
        # mapping, a term mapped onto another has no typing of its own, so the
        # category guard -- which asks exactly about such pairs -- saw
        # `Necrosis Process` as untyped, allowed `Necrosis Process -> Necrosis`,
        # and the accepted mapping then hid the evidence that should have
        # refused it (2026-09-28, the rebuild after rule 51 made the store a view).
        def _unmapped():
            for key, ents in self.store.view(mapped=False):
                for entity, attrs in ents.items():
                    for triple, value in attrs.items():
                        yield key, entity, triple, value
        for _, entity, triple, value in _unmapped():
            if value != 1.0 or ":" not in triple:
                continue
            pred, target = triple.split(":", 1)
            if pred.strip().lower().replace(" ", "_") not in ("is_a", "subclass_of"):
                continue
            declared = declared_category(target.strip())
            if declared is not None:
                typings.setdefault(smart_title(entity.strip()), set()).add(declared)
        return typings

    def store_categories(self) -> dict[str, str]:
        """{store term -> its reconciled BFO category}, or absent if undecided.

        Absent covers two different situations, and `_category_compatible_mapping`
        needs to tell them apart: a term no abstract ever typed, and a term typed
        into branches that agree on nothing below `entity`. Use `store_typings`
        for the raw record.
        """
        out: dict[str, str] = {}
        for term, cats in self.store_typings().items():
            agreed = (next(iter(cats)) if len(cats) == 1
                      else self.reasoner_gate.least_common_category(cats))
            if agreed:
                out[term] = agreed
        return out

    def ontology_label_spellings(self) -> dict[str, str]:
        """{folded name a class answers to -> that class's rdfs:label}.

        The curator's rule of 2026-09-23: where a canonical names an existing
        class, the class's own spelling is the canonical. Folded, because the
        store's spelling is exactly what hides the class -- `necrosis` for
        `Necrosis`, `surgical debridement` for `Surgical debridement`.

        Only `rdfs:label` is re-spelled onto. An ALT TERM is left exactly as it
        is, and that is a decision about THIS ontology, not about alt terms in
        general: WONT's alt terms are largely HISTORICAL LABELS. The 17 Sep
        renaming moved 31 classes to "… plan specification" and kept the old
        names as alt terms, so `Negative pressure wound therapy` is an alt term
        of `Negative pressure wound therapy plan specification` -- and also the
        plain name of the therapy process. Resolving alt terms to their class's
        label moved store terms for the THERAPY onto the PLAN SPECIFICATION, an
        information entity: measured, 101 re-spellings of which the first three
        were exactly that. An alt term is how the lexicon FINDS a class; it is
        not a canonical to rename onto.
        """
        from rdflib import OWL, RDF, RDFS

        from wound_ontology.hierarchies.curated_seed import default_curated_sources
        from wound_ontology.utils.rdf_io import parse_graph
        from wound_ontology.utils.string_utils import normalize_term

        sources, _ = default_curated_sources()
        primary: dict[str, str] = {}                    # IRI -> rdfs:label
        for src in sources:
            g = parse_graph(src)
            individuals = set(g.subjects(RDF.type, OWL.NamedIndividual))
            for subj, _, obj in g.triples((None, RDFS.label, None)):
                if subj in individuals or (subj, RDF.type, OWL.Class) not in g:
                    continue
                primary.setdefault(str(subj), str(obj).strip())

        # Two classes can answer to one folded name: DOID spells it
        # `necrotizing fasciitis`, WONT `Necrotizing fasciitis`. Ours wins --
        # it is the ontology being built, and without a rule the winner came
        # out of dict order and flipped between runs.
        def ours_first(item: tuple[str, str]) -> tuple[int, str]:
            iri, label = item
            return (0 if ("WONT_" in iri or "MILD_" in iri) else 1, label)

        out: dict[str, str] = {}
        for _, label in sorted(primary.items(), key=ours_first):
            out.setdefault(normalize_term(label), label)
        return out

    def blocked_names(self) -> set[str]:
        """Names the GATE condemns, lowercased.

        The mapping must not rename a surviving variant onto a name the gate
        puts out, so it is held here and the mapping refuses to. Read off the
        gate, the only place scope is decided since the lists went (rule 86): a
        curator who lets `silver sulfadiazine` back in sees it here at once.
        """
        return {t.strip().lower() for t in self.term_mapper.gated("out")}

    def run_pass0_normalise(self, *, dry_run: bool = True,
                            quiet: bool = False) -> dict:
        """PASS 0: fix the names a rule can settle, before any model runs.

        **It renames, it does not map** (curator, 2026-09-26: *pass 0 should
        not create another mapping, it should change the labels right at the
        spot*), and it renames in BOTH places a term string lives -- the
        concept store and the term mapping -- *just to make sure nothing
        slipped through*. Normalising only the store would leave the mapping
        holding spellings the rules reject, and the next apply would put them
        back.

        The curator's rule of 2026-09-25: exhaust the deterministic methods
        first, and never pay a model to notice that `Surgical Site Infection`
        and `surgical site infections` are one thing. Measured on the
        2026-09-25 store, **9,650 of the 96,243 terms are a pure spelling
        variant of another** -- 5,638 needing only the singular rule, 3,027 case
        alone, 584 a hyphen, 272 British spelling -- against 2,820 that the
        mapping had found.

        Five deterministic steps, in this order:

        1. the head noun to the singular (`singular_spelling`, rule 23a);
        2. British to American (`utils.spelling`, rule 41);
        3. the curator's preferred vocabulary (`canonical_vocabulary`, rules 48–49);
        4. case, hyphens and punctuation folded (`fold`);
        5. group on the result, and map every member onto one name.

        Singular BEFORE spelling, because `Statistical Analyses` goes to
        `Statistical Analysis` and the noun never reaches the British-verb
        reading of `analyses` that would make it `analyze`.

        The surviving spelling is chosen by `canonical_rank` -- an ontology
        label beats any store term (rule 36), then corpus frequency -- and is
        then itself singularised and Americanised, unless it is an ontology
        label, which is kept exactly as the ontology writes it.

        Nothing here asks a person's leave, and that is deliberate (curator,
        2026-09-26: *there is no place for any disagreement with the pass 0
        renaming*). The guard that skipped a pair a curator had ruled on was
        measured before it was removed: all 385 such pairs were pure spelling,
        so the guard was not protecting a decision, it was preserving a second
        spelling of one. A declared BFO category keeps the spelling BFO gives it
        (rule 22), and a group whose members stop agreeing once their
        parentheticals are put back is reported rather than merged, because
        `fold` strips those and `vitamin (role)` is not `vitamin`.

        Idempotent, so it runs after extraction and again before matching.
        """
        from collections import Counter

        from wound_ontology.llm.category_vocab import declared_category
        from wound_ontology.mappers.pass0 import pass0_renames

        freq: Counter = Counter()
        targets: set[str] = set()
        for _, entities in self.store.view(mapped=False, include_rejected=True):
            for name, attrs in entities.items():
                freq[name] += 1
                for triple in attrs:
                    if ":" in triple:
                        targets.add(triple.split(":", 1)[1].strip())

        gt = self.term_mapper._term_mapping
        # Every string the MAPPING holds as well, so nothing slips through: its
        # keys, its live targets and the canonicals its pair verdicts are keyed
        # by. A canonical that only the mapping knows about is still a term,
        # and leaving it unnormalised is how an un-singularised spelling gets
        # put back the next time the mapping is applied.
        others: set[str] = set(targets)
        for term, rec in gt.records.items():
            if gt.is_alias(term):
                continue                    # a spelling already decided (rule 51)
            others.add(term)
            if rec.get("to"):
                others.add(rec["to"])
            others.update(rec.get("pairs") or {})

        renames, report = pass0_renames(
            freq, {str(a) for a in self.ontology_labels()}, others,
            declares=declared_category,
            named=self.term_mapper._term_mapping.named())
        if not quiet:
            print(f"[pass0] {report['groups']:,} group(s) with more than one "
                  f"spelling, {report['respelled']:,} lone spelling(s) respelled; "
                  f"{report['to write']:,} rename(s) to apply, "
                  f"{report['minted']:,} spelling(s) nobody wrote")
            print(f"[pass0] held back: {len(report['characters']):,} group(s) "
                  f"held together only by a discarded character, "
                  f"{len(report['unsafe']):,} with two different parentheticals, "
                  f"{len(report['ontology sense']):,} on an ontology label's own "
                  f"parenthetical, {len(report['declared']):,} declaring two "
                  f"categories")
        if dry_run:
            print("[pass0] dry run — nothing written. Pass dry_run=False to apply.")
            return report

        # The store first: it is the record, and the mapping is a view of what
        # is still to be decided about it.
        # One write (rule 51): the term dict records every rename as an alias
        # and moves the decisions; the evidence is not touched.
        report["store"] = report["mapping"] = self.store.apply_renames(renames, by="pass0")
        if not quiet:
            st, mp = report["store"], report["mapping"]
            print(f"[pass0] store: {st['renamed']:,} name(s) renamed, "
                  f"{st['entities']:,} entity records, "
                  f"{st['merged verdicts']:,} verdict(s) merged")
            print(f"[pass0] mapping: {mp['keys renamed']:,} key(s), "
                  f"{mp['targets renamed']:,} target(s) and "
                  f"{mp['pair keys renamed']:,} pair key(s) renamed; "
                  f"{mp['records merged']:,} record(s) merged; "
                  f"{mp['identities dropped']:,} entr(ies) dropped as pure "
                  f"spelling ({mp['records deleted']:,} record(s) gone entirely, "
                  f"the rest kept for a gate or another canonical)")
            if mp["chains"]:
                print(f"[pass0] {mp['chains']:,} live entr(ies) now point at a "
                      f"term that is itself mapped — the rename revealed chains "
                      f"the spelling was hiding; resolve_chains is owed a run.")
        if report["mapping"]["gate conflicts"]:
            clashes = report["mapping"]["gate conflicts"]
            print(f"[pass0] {len(clashes)} merged record(s) carry a gate source "
                  f"that contradicts ITSELF across the spellings; that source now "
                  f"decides nothing and both sides are kept in `gate_contested`:")
            for term, source, kept, dropped in clashes[:10]:
                print(f"[pass0]     {term!r}: {source} said both {kept!r} and {dropped!r}")
        if report["mapping"].get("locked targets"):
            locked = report["mapping"]["locked targets"]
            print(f"[pass0] {len(locked)} merged record(s) mapped onto a target their "
                  f"own pair locks; the mapping is withdrawn, the lock stands:")
            for term, target in locked[:10]:
                print(f"[pass0]     {term!r} -/-> {target!r}")
        if report["mapping"]["target conflicts"]:
            conflicts = report["mapping"]["target conflicts"]
            print(f"[pass0] {len(conflicts)} merged record(s) pointed at DIFFERENT "
                  f"canonicals; the first is live and both are kept in `pairs`:")
            for term, kept, lost in conflicts[:10]:
                print(f"[pass0]     {term!r} -> {kept!r} (also claimed {lost!r})")

        # Read both back off disk. A rename that did not land is a term the
        # rest of the pipeline still sees in the old spelling, and it would
        # only show up as a mysterious duplicate class weeks later.
        fresh = Orchestrator()
        left_in_store = {n for _, ents in fresh.store.view(mapped=False, include_rejected=True)
                         for e, attrs in ents.items()
                         for n in [e, *(t.split(":", 1)[1].strip() for t in attrs if ":" in t)]
                         if n in renames}
        fresh_gt = fresh.term_mapper._term_mapping
        left_in_mapping = {t for t in fresh_gt.records
                           if t in renames and not fresh_gt.is_alias(t)}
        if left_in_store or left_in_mapping:
            raise RuntimeError(
                f"[pass0] {len(left_in_store)} name(s) in the store and "
                f"{len(left_in_mapping)} key(s) in the mapping still hold a "
                f"spelling pass 0 renamed: "
                f"{sorted(left_in_store)[:3]} {sorted(left_in_mapping)[:3]}")
        print(f"[pass0] {len(renames):,} rename(s) applied and verified against "
              f"both files on disk.")
        return report

    def gate_sources(self) -> dict[str, str]:
        """`lowercased name -> which source condemned it`, for the review sheets."""
        return {t.strip().lower(): src
                for t, src in self.term_mapper.gated("out").items()}

    def prune_inert_mappings(self, *, dry_run: bool = True) -> dict:
        """Drop entries whose result is what the store would produce anyway.

        `ConceptStore.normalize` title-cases every name it keeps, so an entry
        that only changes case cannot change an outcome: `Healing -> healing`
        and no entry at all both leave `Healing` in the store. Measured
        2026-09-23: **3,324 of 14,047 entries** are inert in exactly that way,
        a quarter of the file, and they are why the mapping reads as mostly
        mechanical noise.

        What is NOT inert, and is often mistaken for it:

        * **plural** — 5,072 entries. `normalize_term` folds case and
          punctuation; it does not singularise. Without `patients -> patient`
          the store keeps `Patients` AND `Patient` as two names. The mapping is
          the only place singularisation reaches the store, which is why rule 23
          lives there and not in a regex: which spelling is canonical is decided
          on corpus frequency over a cluster, and a recorded entry can be
          withdrawn in review where a hard-coded rule cannot.
        * **punctuation** — 844 entries. The fallback strips it, so the entry is
          what keeps `Povidone-iodine` and `Bates-Jensen Wound Assessment Tool`
          from coming out unhyphenated.

        Inertness is measured against the store's own cleaner rather than
        guessed, and it is relative to the casing policy: were the store to stop
        title-casing, these entries would matter again. That is the same footing
        as rule 19's identity entries, which are inert only because `get()`
        returns an unmapped term unchanged.
        """
        # The store's own answer to "what is this term called", not a second
        # implementation of it: a prune that modelled the rule slightly
        # differently would delete entries that are doing work.
        from wound_ontology.store.concept_store import store_name

        mapping = self.term_mapper.mapping
        inert = [t for t, c in mapping.items()
                 if t != c and store_name(t, c) == store_name(t)]
        report = {"inert": len(inert), "kept": len(mapping) - len(inert)}
        if not inert:
            print("[Orchestrator] no inert entries — every mapping changes a name.")
            return report
        verb = "would drop" if dry_run else "dropped"
        print(f"[Orchestrator] {verb} {len(inert):,} entr(ies) whose canonical is "
              f"what the view calls the term anyway; {report['kept']:,} kept.")
        for t in inert[:5]:
            print(f"[Orchestrator]     {t!r} -> {mapping[t]!r} — both give "
                  f"{store_name(t)!r}")
        if not dry_run:
            self.term_mapper.withdraw(
                *inert, reason="the view already gives the term this name")
        return report

    def _category_compatible_mapping(self, anchors: set[str]):
        """Refuse an anchor mapping that crosses a categorical boundary.

        SapBERT cannot separate a process from its material bearer — their labels
        are nearly identical — so it proposed `Necrosis Process -> Necrosis`,
        `Skin grafting -> Skin graft`, `wound dehiscence -> Wound dehiscence
        process`. Mapping is synonymy, so the two must not sit in disjoint
        branches; one being an ancestor of the other is fine, since that is the
        same thing said more coarsely.

        Where either side's category is unknown the mapping is ALLOWED: there is
        no information to refuse on, and refusing on a guess would throw away the
        lexical variants the anchors exist to catch.

        "Unknown" means never typed. A term typed into branches that cannot be
        reconciled -- `Skin Grafting` as both `material entity` and `process`,
        which the 606-abstract corpus produced on 2026-09-12 -- is not unknown;
        it is known to straddle exactly the boundary this guard exists to hold.
        `store_categories` drops such a term as undecided, and treating that as
        "no information" let `Skin grafting -> Skin graft` through: the guard
        refused the mapping on 142 abstracts and accepted it on 606, because a
        contradiction had appeared and was read as silence. Contradicted terms
        are REFUSED.

        BFO category names are never mapped at all. They appear in the store as
        `is_a: process` targets, and mapping one onto a term would hand every
        reconciliation and split downstream a name that is no longer a category.
        The test is separator-blind, so it also catches a store still carrying
        the pre-2026-09-08 CamelCase spelling.
        """
        from wound_ontology.llm.category_vocab import is_category
        from wound_ontology.llm.extraction_models import CATEGORY_PARENT
        from wound_ontology.utils.string_utils import normalize_term, smart_title

        onto_cat = self.ontology_categories()
        # Folded as well as exact. The guard is consulted with whatever spelling
        # the mapping carries, and a store-spelled label (`necrosis` for
        # `Necrosis`) used to resolve to nothing at all -- which the guard reads
        # as "no information" and allows. That is how
        # `Necrosis Process -> necrosis` reached the store.
        onto_cat_folded: dict[str, str] = {}
        for label, cat in onto_cat.items():
            onto_cat_folded.setdefault(normalize_term(label), cat)
        typings = self.store_typings()
        store_cat = self.store_categories()
        contradicted = {term for term in typings if term not in store_cat}

        def ancestors(cat: str) -> set[str]:
            chain, cur = {cat}, CATEGORY_PARENT.get(cat)
            while cur:
                chain.add(cur)
                cur = CATEGORY_PARENT.get(cur)
            return chain

        def accept(term: str, canonical: str) -> bool:
            if is_category(term):
                return False
            key = smart_title(term.strip())
            if key in contradicted:
                return False
            a = store_cat.get(key)
            b = onto_cat.get(canonical.strip()) or onto_cat_folded.get(
                normalize_term(canonical))
            if a is None or b is None:
                return True
            return b in ancestors(a) or a in ancestors(b)

        return accept

    def run_build_term_mapping(self, similarity_threshold: float = 0.95,
                               use_ontology_anchors: bool = True,
                               readjudicate: bool = False) -> dict:
        """
        Build a SapBERT cosine-similarity mapping that clusters near-duplicate terms.

        The most frequent term in each cluster becomes the canonical form — unless
        the cluster contains an ONTOLOGY LABEL, which always wins.

        Anchoring on WONT and MILD labels closes a gap that had been open in both
        directions: SapBERT was given only store terms, so it could merge
        "Complication" with "Complications" but never reach WONT's existing
        "Wound complication process"; and the merge-time lexicon knew the ontology
        labels but matched them by string alone, so "Granulation" never reached
        "Granulation process". Terms fell between the two and were minted as twins
        of classes that already existed.

        Pass use_ontology_anchors=False for the old store-only behaviour. That
        is not a way around the adjudication below: with no anchors the mapping
        makes no claim about an existing class at all, so there is nothing to
        adjudicate — only store terms merging with each other, which
        review_mapping() can still undo.

        Every anchor mapping SapBERT proposes is then ADJUDICATED by the LLM
        unless the two labels differ only by case, punctuation or plural. The
        model is not an optional refinement here: mapping a store term onto an
        existing class is an identity claim that cannot be undone downstream, and
        cosine similarity was measured to be incapable of making it. If the model
        cannot be reached, this raises rather than returning a mapping nobody
        checked. Pass readjudicate=True to re-ask pairs already in the cache.

        Follow up with review_mapping(), then run_apply_mapping().
        """
        if not self.llm.has_credentials:
            raise RuntimeError(
                "[Orchestrator] run_build_term_mapping needs the LLM: anchor "
                "mappings are adjudicated by it, and no OPENROUTER_API_KEY is set. "
                "Set the key — there is no offline mode for this step, because a "
                "mapping built without it would silently absorb store terms into "
                "the wrong existing classes."
            )
        freq = self._collect_store_terms_with_freq()
        # Every canonical the mapping ALREADY uses joins the clustering, with
        # the frequency of everything that points at it. Pass 0 mints a
        # canonical that no abstract wrote -- `wounds` and `Wounds` collapse
        # onto `wound` -- and a clustering that only saw store strings would
        # not know `wound` exists, would re-canonicalise its members onto a
        # spelling that does, and would undo 22,475 singularisations without
        # saying so. Inheriting the members' frequency is what makes
        # `canonical_rank` keep choosing it.
        inherited: dict[str, int] = {}
        for term, canonical in self.term_mapper.mapping.items():
            inherited[canonical] = inherited.get(canonical, 0) + freq.get(term, 0)
        minted = 0
        for canonical, carried in inherited.items():
            if canonical not in freq:
                freq[canonical] = carried
                minted += 1
            else:
                freq[canonical] = max(freq[canonical], carried)
        if minted:
            print(f"[Orchestrator] {minted:,} canonical(s) the mapping uses are not "
                  f"store strings; added to the clustering with the frequency of "
                  f"what points at them.")
        anchors: set[str] = set()
        terms = list(freq.keys())
        if use_ontology_anchors:
            anchors = self.ontology_labels() - set(terms)
            terms += sorted(anchors)
            print(f"[Orchestrator] {len(anchors)} ontology label(s) added as anchors "
                  f"— a store term clustering with one is mapped onto it.")
        print(f"[Orchestrator] Building term mapping from {len(freq)} unique store terms "
              f"(threshold={similarity_threshold})...")
        accept = None
        if anchors:
            accept = self._category_compatible_mapping(anchors)
        self.term_mapper.build_from_embeddings(
            terms,
            embedder=self._ensure_embedder(),
            similarity_threshold=similarity_threshold,
            frequencies=freq,
            anchors=anchors,
            accept_mapping=accept,
        )
        refused = getattr(self.term_mapper, "refused_mappings", [])
        if refused:
            print(f"[Orchestrator] {len(refused)} anchor mapping(s) refused as the "
                  f"wrong kind of thing:")
            for term, onto in refused[:15]:
                print(f"[Orchestrator]     {term!r} -> {onto!r}")
        # The file never forgot: entries survive every rebuild, so one written
        # against a store that has since been re-extracted still fires. Dropping
        # the provably inert ones is what makes the rest reviewable.
        self.term_mapper.prune(set(freq), self.ontology_labels() if anchors else frozenset())
        # ...and it never forgot the SHAPE either: a canonical this build chose
        # may be a term an earlier build had already mapped elsewhere, leaving
        # `A -> B -> C` and `A <-> B` in a file every single build writes as a
        # forest. `normalize` follows one hop, so a chain half-lands the merge
        # and a cycle undoes it — both without a word.
        #
        # This runs BEFORE the adjudication, not after: resolving `A -> B -> C`
        # to `A -> C` creates a pair no model has seen, and the whole point of
        # the adjudication is that no mapping onto an existing class stands
        # unasked. Withdrawing entries afterwards cannot re-create a chain --
        # removing an edge never makes a path -- so the order is safe in the
        # other direction.
        self.term_mapper.resolve_chains(frequencies=freq, anchors=anchors,
                                        accept_mapping=accept)
        # The ontology's own label wins (curator, 2026-09-23), which also puts
        # the identity claim in front of the category guard: a canonical spelled
        # the store's way (`necrosis`) hid it from a guard that only ever sees
        # anchors, and anchors exclude every label the corpus also uses.
        self.term_mapper.enforce_canonical_policy(
            label_spellings=self.ontology_label_spellings(),
            blocked=self.blocked_names(),
            accept_mapping=self._category_compatible_mapping(self.ontology_labels()),
        )
        self._adjudicate_anchor_mappings(anchors, readjudicate=readjudicate)
        mapping = self.term_mapper.mapping
        print("[Orchestrator] Mapping built — call review_mapping() to inspect and curate.")
        return mapping

    def _adjudicate_anchor_mappings(self, anchors: set[str],
                                    readjudicate: bool = False) -> dict:
        """Send the anchor mappings SapBERT cannot decide to the LLM.

        Anchor mappings are the irreversible ones: absorbing a store term into an
        existing WONT or MILD class is a permanent identity claim. Cosine distance
        cannot make it. On the 2026-09-05 build the good and bad proposals were
        interleaved between 0.96 and 0.98, so no threshold separates them — but
        what the labels differ BY does. 28 of 50 differed only by case,
        punctuation or plural, and every one of those was right; all seven wrong
        ones were among the 22 where a real word changed. Only content-differing
        pairs are asked about, with the ontology's own definition attached.

        Store-to-store merges are adjudicated as well, in a SECOND call that
        passes no categories. They were excluded at first on the grounds that a
        wrong one is reversible through review_mapping() -- which assumes somebody
        walks 2141 non-identity entries, and nobody has. Measured over the 52
        live content-differing pairs: 14 were not synonyms, among them
        `diabetes mellitus -> diabetes` and `hip and knee arthroplasty -> hip or
        knee arthroplasty`.

        The categories are withheld on purpose. There is no ontology side here, so
        the only categories available are the store's own per-abstract typings --
        the noisy input the pipeline exists to reconcile. Passing them in the slot
        the anchor path fills from the skeleton TBox pushed the model into
        refusing on "store term is a material entity, ontology class LIKELY a process",
        and it threw out `haemorrhage -> Hemorrhage` as a category clash. Same 52
        pairs, no categories: 46% not-synonymous became 27%.
        """
        from wound_ontology.mappers import mapping_adjudicator as adj

        # Read from the FILE, not from what this build returned: the file
        # accumulates, so entries written by an earlier build are equally capable
        # of firing and equally in need of a verdict.
        mapping = self.term_mapper.mapping
        live = set(self._collect_store_terms_with_freq())
        non_identity = {t: c for t, c in mapping.items() if t != c}
        anchor_pairs = {t: c for t, c in non_identity.items() if c in anchors}
        # A store-to-store pair is only worth a call while both ends can still
        # occur: 1969 of the file's non-identity entries point at a canonical that
        # no longer exists anywhere, and adjudicating those would spend the budget
        # on decisions that can never fire.
        store_pairs = {t: c for t, c in non_identity.items()
                       if c not in anchors and (t in live or c in live)}
        if not anchor_pairs and not store_pairs:
            return mapping
        # The cache IS the records (rule 38). `mapping_adjudication_*.json` was a
        # second home for the same fact, with nothing keeping the two equal;
        # `pass_cache` reads and writes the entry the verdict is about.
        # `readjudicate` stops it reading, not writing: every pair is asked
        # again and the new answers still land on the record.
        cache = self.term_mapper._term_mapping.pass_cache("pass1", read=not readjudicate)
        # The verdicts go to disk as they arrive. The 2026-09-26 build spent
        # four hours here and banked nothing, because the only save was after
        # the loop and the loop never finished.
        report = self._run_sync(adj.adjudicate(
            anchor_pairs, self.llm,
            store_categories=self.store_categories(),
            ontology_categories=self.ontology_categories(),
            definitions=self.ontology_definitions(),
            parents=self.ontology_parents(),
            cache=cache,
            checkpoint=self.term_mapper.save,
            label="anchor pairs",
        ))
        # No categories on this path, deliberately. See the docstring: the store's
        # own per-abstract typings are not an ontology, and passing them here made
        # the model refuse `haemorrhage -> Hemorrhage` on a category clash.
        report.extend(self._run_sync(adj.adjudicate(
            store_pairs, self.llm, cache=cache,
            checkpoint=self.term_mapper.save,
            label="store pairs",
        )))
        self.term_mapper.save()
        print(f"[Orchestrator] Anchor adjudication: {report.summary()}.")

        # A curator's verdict on the pair outranks pass 1 (rule 28). The report
        # carries CACHED verdicts too, so without this every re-run withdrew
        # again each pair the curator had put back over pass 1's objection --
        # 75 of them on 2026-09-27, all from that day's contradiction queue.
        gt = self.term_mapper._term_mapping
        not_same = report.refused + report.subsumption_candidates
        from wound_ontology.utils.string_utils import normalize_term as _norm

        def ruled(t: str, c: str) -> bool:
            # The curator's verdict may sit on the pair under the spelling it
            # was given (`Angiogenesis process`) while the live mapping has
            # since been re-spelled to the class label (`angiogenesis`), so
            # the LIVE pair is asked too (2026-09-28: `bone infection ->
            # Osteomyelitis` and `formation of blood vessel` were withdrawn
            # over the curator's same_class that way).
            # `check` wrote under `curator` until 2026-10-24 and counted here.
            live = gt.data.get(t)
            def said(j: dict) -> bool:
                return bool(j.get("curator") or j.get("check"))
            if said(gt.peek(t, c)) or (live and said(gt.peek(t, live))):
                return True
            keys = {_norm(c)} | ({_norm(live)} if live else set())
            return any(_norm(k) in keys and said(j)
                       for k, j in (gt.record(t).get("pairs") or {}).items())

        def is_live(t: str, c: str) -> bool:
            # Only the mapping pass 1 objected to is withdrawn: `withdraw`
            # unmaps the TERM, and a term since mapped elsewhere must keep it.
            live = gt.data.get(t)
            return bool(live) and _norm(live) == _norm(c)

        overruled = [(t, c) for t, c, _, _ in not_same if ruled(t, c)]
        withdrawn = [t for t, c, _, _ in not_same if not ruled(t, c) and is_live(t, c)]
        if overruled:
            print(f"[Orchestrator] {len(overruled)} pair(s) pass 1 did not confirm "
                  f"stay as they are: the curator ruled on them, and a ruling "
                  f"outranks a pass.")
        if withdrawn:
            n = self.term_mapper.withdraw(
                *withdrawn, reason="pass 1 did not confirm the two as the same class")
            print(f"[Orchestrator] withdrew {n} anchor mapping(s) the model did not "
                  f"confirm as the same class.")
        for term, onto, verdict, reason in report.refused:
            print(f"[Orchestrator]   REFUSED   {term!r} -> {onto!r}  [{verdict}] {reason}")
        for term, onto, verdict, reason in report.subsumption_candidates:
            arrow = "is_a" if verdict == "narrower" else "has subclass"
            print(f"[Orchestrator]   SUBCLASS  {term!r} {arrow} {onto!r}  — {reason}")
        # A VIEW of the record, not of this run. The old version wrote only what
        # this build happened to re-ask, so a pair judged `narrower` in September
        # vanished from the file in October the moment the cache answered it from
        # memory — the candidate edge was still true and no longer written down.
        rows = self.term_mapper.subsumption_candidates()
        if rows:
            self.dm.save_as_csv(pd.DataFrame(rows), "mapping_subsumption_candidates")
            fresh = len(report.subsumption_candidates)
            print(f"[Orchestrator] {len(rows)} subsumption candidate(s) on record "
                  f"({fresh} of them judged in this run) — these are not synonyms "
                  f"but they are not nothing; review before minting.")
        return self.term_mapper.mapping

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
        """Read the store through the term mapping. Nothing is rewritten (rule 51)."""
        self.store.normalize(mapper=self.term_mapper)

    # ── Phase 3: Concept analysis ─────────────────────────────────────────────

    def _judge_fca_proposals(self, proposals, withheld: dict[str, list[str]] | None = None) -> int:
        """Rule 79: the head-word rule decides the concept analysis's edges.

        Every edge from a member to its concept's name, and every edge still
        queued from an earlier run, is judged by the curator's head-word rule
        (wound_ontology.hierarchies.head_rule). Licensed edges are promoted and
        recorded on this lattice's accepted slice, so the next build reads them
        back as the `fca` source and the edge check reasons over them; refused,
        synonym and open edges leave the queue and are listed in a report under
        output/, never shown to the curator one by one. `withheld` names the
        concepts run_fca kept from the rule ({why: [name, ...]}); they go into
        the same report, so every name the model made is accounted for there
        (rule 1). The report's content is also kept as self.fca_head_rule.
        Returns how many were promoted.
        """
        import json as _json
        from datetime import datetime as _dt
        from wound_ontology.hierarchies import head_rule as HR
        from config.settings import PROJECT_ROOT as _BP
        from pathlib import Path

        # Every name under its CURRENT spelling: a rename since the proposal
        # (2026-10-18: `Venous Ulcer` -> `Venous Wound`, `burn` -> `burn wound`)
        # must not bring the old spelling back as a class of its own. A store
        # term goes through the store's resolver; a name only the model gave
        # goes through the same vocabulary rules pass 0 applies.
        from wound_ontology.utils.normalise import canonical_vocabulary as _cv
        _resolve = self.store.resolver(mapped=True)

        def _current(name: str) -> str:
            now = _resolve(name)[1]
            if str(now).lower() == str(name).lower():
                now = _cv(name)
            return smart_title(now)

        def _cur_pairs(pairs):
            return [(_current(c), _current(p)) for c, p in pairs]

        proposals = _cur_pairs(proposals)
        queued = _cur_pairs(self.class_hier.candidates)
        # The slice accepted so far is judged again: a later ruling (or a
        # curator's "no" on one edge) withdraws what it no longer licenses;
        # an edge under an old spelling is withdrawn and comes back renamed.
        accepted = sorted(self.lattice.accepted)
        known = [str(x) for x in self.class_hier.df.index] if not self.class_hier.df.empty else []
        curator = {}
        for f in sorted((Path(_BP) / "data" / "review").glob("fca_edge_decisions_*.json")):
            for e in _json.loads(f.read_text(encoding="utf-8"))["edges"]:
                curator[(e["child"], e["parent"])] = e["verdict"]
        verdicts = HR.sort_proposals(list(proposals) + queued + _cur_pairs(accepted), known=known, curator=curator)
        # The model's names among themselves and against the ladder's own
        # classes: `Burn Injury ⊑ Injury`, `Diabetic Ulcer ⊑ Wound`. Nobody
        # proposes these, and a new name without a checked parent stays out of
        # the core with everything under it.
        names = sorted({r["as"] for r in verdicts[HR.LICENSED]})
        anchors = sorted(set(names) | {"Wound", "Injury"})
        between = HR.sort_proposals([(a, b) for a in names for b in anchors if a != b], known=known, curator=curator)
        verdicts["between_names"] = between[HR.LICENSED]
        licensed = [(smart_title(r["child"]), smart_title(r["as"]))
                    for r in verdicts[HR.LICENSED] + between[HR.LICENSED]]
        withdraw = sorted(set(accepted) - set(licensed))
        if withdraw:
            self.lattice.withdraw(withdraw)
            for child, parent in withdraw:
                if self.class_hier._prov.get((child, parent)) == _SOURCE_FCA:
                    if child in self.class_hier.df.index and parent in self.class_hier.df.columns:
                        self.class_hier.df.at[child, parent] = 0.0
                    self.class_hier._prov.pop((child, parent), None)
            print(f"FCA → head-word rule  : {len(withdraw)} edge(s) withdrawn from the accepted slice, "
                  f"no longer licensed, e.g. {withdraw[:3]}")
        for child, parent in licensed:
            self.class_hier.propose_edge(child, parent, _SOURCE_FCA)
        promoted = self.class_hier.promote_candidates(only=set(licensed), lattice=self.lattice) if licensed else 0
        dropped = list(self.class_hier.candidates)
        for key in dropped:
            self.class_hier._candidates.pop(key, None)
        self.class_hier.save_candidates()
        stamp = _dt.now().strftime("%Y-%m-%d_%H-%M")
        # The project's output/ only for the project's own cache; a test's
        # DataManager writes beside its own files (2026-10-18: two test runs
        # wrote reports into output/, and the next --skip-fca read one of them).
        from config.settings import BASE_PATH as _CACHE
        real = Path(self.dm.base_path).resolve() == Path(_CACHE).resolve()
        out = (Path(_BP) / "output" if real else Path(self.dm.base_path)) / f"fca_head_rule_{stamp}.json"
        withheld = {k: sorted(set(v)) for k, v in (withheld or {}).items() if v}
        report = {"made": stamp, "proposals": len(proposals), "queued_before": len(queued),
                  "accepted_before": len(accepted), "withdrawn": withdraw, **verdicts,
                  "withheld": withheld}
        out.write_text(_json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        _json.loads(out.read_text(encoding="utf-8"))
        self.fca_head_rule = {**report, "report": str(out)}
        n = {k: len(v) for k, v in verdicts.items()}
        print(f"FCA → head-word rule  : {n['between_names']} edge(s) between the model's names "
              f"(e.g. {[(r['child'], r['as']) for r in verdicts['between_names'][:3]]})")
        print(f"FCA → head-word rule  : {len(proposals)} new proposal(s) + {len(queued)} queued from earlier runs: "
              f"{n[HR.LICENSED]} licensed ({promoted} promoted), {n[HR.REFUSED]} refused, "
              f"{n[HR.SYNONYM]} synonym, {n[HR.OPEN]} open (head word not ruled yet). "
              f"Nothing is left for review; every edge and its reason -> {out}")
        for k in (HR.REFUSED, HR.OPEN):
            for r in verdicts[k][:5]:
                print(f"    {k}: {r['child']} ⊑ {r['as']} -- {r['reason']}")
        for why, names_ in withheld.items():
            print(f"FCA → head-word rule  : {len(names_)} name(s) withheld before the rule ({why}), "
                  f"listed in the report: {names_[:5]}")
        return promoted

    def accepted_fca_slices(self) -> list[list[tuple[str, str]]]:
        """Every reviewed lattice slice on disk, one list per subtree analysis.

        FCA output is a suggestion until a human accepts it; the acceptance is
        recorded as a slice of the lattice it came from (see
        ConceptLattice.accept). Those slices are this hierarchy's `fca` source.
        Read from disk rather than from this session's objects, so a build picks
        up reviews done in an earlier session.
        """
        slices: list[list[tuple[str, str]]] = []
        for prefix in self.dm.list_prefixes("concept_lattice_*_accepted", "json"):
            raw = self.dm.load_latest_json(prefix) or []
            if raw:
                slices.append([(str(a), str(b)) for a, b in raw])
        if slices:
            total = sum(len(x) for x in slices)
            print(f"[Orchestrator] {total} accepted FCA edge(s) from "
                  f"{len(slices)} reviewed lattice slice(s).")
        return slices

    def refresh_class_hierarchy(
        self,
        predefined_df: pd.DataFrame | None = None,
        curated_sources=None,
        curated_label_sources=None,
        include_rejected: bool = False,
    ) -> ClassHierarchyView:
        """
        Derive the class hierarchy VIEW from its sources and return it.

        Replaces run_build_hierarchies (2026-10-21). Nothing is saved but a
        provenance snapshot for the inspection pages; the mereological hierarchy
        is no longer built. The edge gate's standing verdicts are taken off the
        result unless `include_rejected` -- which the gate itself asks for, so
        that every edge is heard again.

        predefined_df – DataFrame with 'Class' and 'Parent class' columns. When
                        None (the default) the curated seed edges are read from
                        the ontologies named by `curated_sources`. Pass an empty
                        DataFrame to build with no curated edges at all.
        curated_sources       – ontologies to read subsumption from.
                                Default: WONT ground truth + MILD.
        curated_label_sources – files consulted for LABELS only, so imported
                                parents (BFO, COB, IAO, OBI...) can be named.
                                Default: the MILD import modules.

        There is no predefined-hierarchy CSV any more. The table that used to
        live at data/raw/predefined_concept_hierarchy.csv was merged into WONT
        and MILD, and for a while nothing read it back: the curated tier of the
        curated > text > fca precedence sat empty, so an FCA suggestion could
        contradict a hand-authored parent with no rank check to stop it.
        """
        if predefined_df is None:
            from wound_ontology.hierarchies.curated_seed import (
                load_curated_edges, default_curated_sources,
            )
            if curated_sources is None:
                curated_sources, _default_labels = default_curated_sources()
                if curated_label_sources is None:
                    curated_label_sources = _default_labels
            predefined_df, _rep = load_curated_edges(
                curated_sources, curated_label_sources or (), report=True,
            )
            print("[Orchestrator] Curated seed edges read from "
                  f"{', '.join(os.path.basename(str(s)) for s in curated_sources)}:")
            print(_rep.summary())

        # Each source is read in its own right and stamped by where it came from.
        # Curated edges used to be pushed through the ConceptStore first, which
        # made the store assert 459 edges it had never extracted and then needed
        # a second pass to correct the attribution. The original reason for that
        # detour — so the FCA matrix would see curated edges — is gone: conceptual
        # scaling supplies those is_a attributes from the hierarchy itself.
        fca_slices = self.accepted_fca_slices()
        # Stage-1 typing runs per abstract, so one term can arrive with several
        # BFO categories. Emitting all of them made the hierarchy contradict
        # itself by construction and left the reasoner to clean up: 42 of 48
        # quarantined edges were exactly that. Reconcile to the category MILD
        # says subsumes them all, and give no category edge where there is none.
        # The `placed` source (rule 59, written by scripts/apply_placements.py):
        # extracted terms under existing WONT/MILD classes, checked and kept.
        placed = self.term_mapper._term_mapping.placements()
        # Evidence cut (curator, 2026-10-02: 76% of the placed terms occur in
        # one abstract -- "wound exploration", "wound scanning" -- "so many
        # nonsense terms"; answer: ">=2 abstracts"). A term below the cut keeps
        # its placement in the term dict, it just does not become a class.
        seen = {}
        for key, ents in self.store.view():
            for name in ents:
                seen.setdefault(name, set()).add(key)
        kept = [(t, c) for t, c in placed if len(seen.get(t, ())) >= PLACEMENT_MIN_ABSTRACTS]
        print(f"[Orchestrator] {len(placed):,} placement edge(s) in the term dict; "
              f"{len(kept):,} kept by the evidence cut (>= {PLACEMENT_MIN_ABSTRACTS} abstracts), "
              f"{len(placed) - len(kept):,} below it (kept in the term dict, not built).")
        placed = kept
        # The module classes a placement hangs from need their own parents, or
        # they float at the top (`planned process`): add the import modules'
        # chains above exactly those classes, stamped curated like WONT/MILD.
        if curated_label_sources:
            from wound_ontology.hierarchies.curated_seed import module_ancestry
            gtm = self.term_mapper._term_mapping
            used = {((gtm.peek(t, c).get("curator") or {}).get("iri")) for t, c in placed} - {None}
            chains = module_ancestry(used, curated_label_sources)
            if len(chains):
                predefined_df = pd.concat([predefined_df, chains], ignore_index=True).drop_duplicates()
            print(f"[Orchestrator] module ancestry above {len(used):,} placement parent(s): "
                  f"{len(chains):,} edge(s) added to the curated tier.")
            # BFO is the top ontology: its whole tree, curated (2026-10-03, see
            # curated_seed.bfo_edges). Before this, role sat under quality and
            # disposition, function, realizable entity had no parent.
            from wound_ontology.hierarchies.curated_seed import bfo_edges
            bfo = bfo_edges(curated_label_sources)
            predefined_df = pd.concat([predefined_df, bfo], ignore_index=True).drop_duplicates()
            print(f"[Orchestrator] BFO: {len(bfo):,} edge(s) of BFO's own tree (and the two "
                  f"non-BFO extraction categories) added to the curated tier.")
        view = self._view_factory(self.dm)
        view.get_data(
            self.store, curated=predefined_df, fca=fca_slices,
            reconcile_categories=self.reasoner_gate.least_common_category,
            placed=placed,
        )
        view.built = True
        view.verdicts_applied = False
        if not include_rejected:
            self._apply_edge_verdicts(view)
            view.verdicts_applied = True
        view.save_snapshot()
        self._class_hier = view

        print(f"ClassHierarchy (view) : {len(view.concepts)} concepts, "
              f"roots={view.roots[:3]}")
        print(f"ClassHierarchy sources: {view.provenance_summary()}"
              + ("" if view.verdicts_applied else "  (edge-gate verdicts NOT applied: re-hearing)"))
        return view

    def run_build_hierarchies(self, *args, **kwargs) -> ClassHierarchyView:
        """Deprecated (2026-10-21): the hierarchies are no longer a pipeline stage.

        Kept so old notebooks and scripts still run. It derives the class
        hierarchy VIEW (refresh_class_hierarchy) and builds no mereological
        hierarchy; nothing is written but the provenance snapshot.
        """
        print("[Orchestrator] run_build_hierarchies() is deprecated: the class hierarchy "
              "is a view now. Deriving it with refresh_class_hierarchy().")
        return self.refresh_class_hierarchy(*args, **kwargs)

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
        commit_fca: bool = False,
        scale: bool = True,
        min_support: int = 1,
        inherit: str = "class_level",
        unknown: str = "absent",
        name: bool = True,
    ) -> None:
        """
        Build FCA matrix → concept lattice → FCAHierarchy.

        inherit      – "class_level" (default) | "all" | "none": which of an
                       ancestor's own attributes pass to its subclasses (rule
                       65, see ContextMatrix.get_data). Chosen on the Wound
                       subtree by scripts/fca_inheritance_compare.py: "all"
                       and "class_level" proposed the same groupings, but under
                       "all" each dragged in 20-52 descendants that state none
                       of the shared attributes (1% of the grouping's cells
                       their own, against 22%).
        unknown      – "absent" (default, rule 65): a property no abstract
                       states does not hold, for FCA; "both": the open-world
                       dual build, certain vs. candidate concepts.
        name         – False builds the lattice without naming its concepts
                       (no model calls), e.g. to compare settings first.

        subtree_root – restrict entities to the subtree of this concept.
        hierarchy    – which hierarchy to use for subtree lookup (default: class_hier).
        predicates   – restrict to these store predicates; None = all predicates.
        commit_fca   – write lattice-derived superclasses straight into class_hier.
                       Default False: FCA does not assert subsumption, it observes
                       that a set of terms share attributes, which is evidence for
                       a superclass rather than a statement of one. Suggestions are
                       recorded as review candidates; promote them with
                       `class_hier.promote_candidates(lattice=self.lattice)`. Pass
                       the lattice: the acceptance is recorded as a slice of it,
                       and that slice is the `fca` source the next
                       run_build_hierarchies() reads back.
        scale        – conceptual scaling: add each object's superclasses to the
                       context as `is_a:` attributes. Default True.

                       Without it the hierarchy only ever chose which *rows*
                       appeared; it had no say in the result, because FCA orders
                       objects by attribute-set containment alone. Two entities
                       in a curated subclass relation that share no measured
                       attribute came out as unrelated siblings, so the lattice
                       could propose a structure cutting straight across the
                       taxonomy. With scaling, a subclass's attributes are a
                       strict superset of its parent's and the order is forced
                       to agree, while FCA stays free to find structure between
                       and below the asserted edges.

                       Pass scale=False for the unscaled context, e.g. to see
                       what the attributes alone suggest.
        """
        hier = hierarchy or self.class_hier
        entities = hier.subtree_of(subtree_root) if subtree_root else None

        # One lattice and one FCA hierarchy per analysis (rule 6). Reusing a
        # single instance across subtrees unioned unrelated analyses: the FCA
        # hierarchy never cleared itself, so a Wound-subtree run was still
        # present while a different subtree was being analysed, and the saved
        # CSV was the union of every analysis ever run.
        slug = _slugify(subtree_root) if subtree_root else "all"
        self.lattice = ConceptLattice(self.dm, self.context_matrix,
                                      f"concept_lattice_{slug}")
        self.fca_hier = FCAHierarchy(self.dm, f"fca_hierarchy_{slug}")
        self.lattices[slug] = self.lattice
        self.fca_hiers[slug] = self.fca_hier
        print(f"[Orchestrator] FCA analysis '{slug}': "
              f"lattice='{self.lattice.file_name}', "
              f"hierarchy='{self.fca_hier.file_name}'.")

        self.context_matrix.get_data(
            self.store, entities=entities, predicates=predicates,
            scale_hierarchy=hier if scale else None,
            min_support=min_support,
            inherit=inherit,
        )
        if unknown != "absent":
            self.context_matrix.nan_report()

        async def _internal():
            self.lattice.get_data_and_run_fca(unknown=unknown)
            if name:
                await self.lattice.create_superclass_names(self.llm, batch_size=batch_size)

        self._run_sync(_internal())

        if self.lattice.lattice is not None:
            self.fca_hier.get_data(self.lattice.lattice)
            self.fca_hier.save()
            print(f"FCAHierarchy          : {len(self.fca_hier.concepts)} concepts, "
                  f"roots={self.fca_hier.roots[:3]}")

            added = skipped_uncertain = proposed = 0
            proposals: list[tuple[str, str]] = []
            # Names that never reach the head-word rule, kept for its report so
            # a named concept is never dropped without a trace (rule 1).
            withheld: dict[str, list[str]] = {"undecided": [], "no members": []}
            for concept in self.lattice.lattice:
                name = getattr(concept, 'name', None)
                if not isinstance(name, str) or not name:
                    continue
                # A concept that exists only because an undecided cell was read as
                # "true" is a candidate, not a fact. It must not become an asserted
                # superclass. See ConceptLattice.get_data_and_run_fca.
                if not self.lattice.is_certain(concept):
                    skipped_uncertain += 1
                    withheld["undecided"].append(smart_title(name))
                    continue
                if hasattr(concept, 'name'):
                    concept.name = smart_title(name)
                    name = concept.name
                if not commit_fca and not len(concept.extent):
                    withheld["no members"].append(name)
                for entity in concept.extent:
                    if commit_fca:
                        if self.class_hier._set_edge(str(entity), name, source=_SOURCE_FCA):
                            added += 1
                    else:
                        proposals.append((str(entity), name))
            if not commit_fca:
                proposed = self._judge_fca_proposals(proposals, withheld=withheld)
            if added:
                self.class_hier._df = self.class_hier._df.copy()
                self.class_hier.save()
                print(f"FCA → ClassHierarchy  : {added} extent→superclass edges merged "
                      f"(source='{_SOURCE_FCA}'; curated and text edges were not overwritten).")
            if proposed:
                self.class_hier.save()
            if skipped_uncertain:
                print(f"FCA → ClassHierarchy  : {skipped_uncertain} concept(s) withheld "
                      f"as undecided-dependent.")
            if self.lattice.candidate_intents:
                self.lattice.candidate_summary()
        else:
            print("FCAHierarchy          : skipped (empty lattice).")

    def run_matrix_nan_fill(self, batch_size: int = 20, entity_batch: int = 5) -> None:
        """Resolve the undecided cells of the current FCA view (post-FCA).

        The verdicts go into the ConceptStore, not into the matrix: the matrix is
        a view and is rebuilt from the store afterwards, so a verdict kept only
        here would not survive the next run_fca.
        """
        print(f"Evaluating missing relations (concurrency={batch_size}, entity_batch={entity_batch})...")
        self._run_sync(self.context_matrix.fill_nan(
            self.llm, store=self.store, batch_size=batch_size, entity_batch=entity_batch,
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
        """Export the hierarchies to a standalone OWL file.

        .. deprecated::
           Use :meth:`run_extend_ground_truth` instead.

        This builds a *parallel* ontology from an empty ``OWLOntology.create()``:
        it never reads ``ground_truth_final.owl``, so every class is minted with
        a fresh WONT id counting from 1, including ones WONT already curates and
        ones the imports already define. "Wound" comes out as a new class rather
        than WONT_0000380, and nothing merges back into WONT. There is also no
        lexicon here, so the BFO/MILD duplicate-minting that
        ``extend_ground_truth`` now avoids is unavoidable on this path.

        Kept working because stored outputs and tests still reference it.
        """
        import warnings
        warnings.warn(
            "Orchestrator.export_to_owl builds a parallel ontology from an empty "
            "one: every class is minted afresh, existing WONT ids are not reused, "
            "and imported classes are duplicated. Use run_extend_ground_truth(), "
            "which uses the ground truth as its base and resolves against it.",
            DeprecationWarning, stacklevel=2,
        )
        onto = OWLOntology.create()
        OntologyCurator(onto).from_hierarchies(
            self.class_hier, self.mere_hier, self.fca_hier, store=self.store,
        )
        onto.save(self.dm, output_file)

    def run_extend_ground_truth(
        self,
        output_file: str | None = None,
        touch_existing: bool = False,
        include_fca: bool = False,
        lexicon=None,
    ):
        """Merge pipeline findings into a copy of the WONT ground truth.

        This is the step that was missing: ``export_to_owl`` builds a parallel
        ontology from nothing, so the pipeline never actually extended WONT.
        Here the ground truth is the base, existing terms resolve to their real
        IRIs, and only genuinely new terms are minted -- in the WONT namespace,
        continuing from the highest id in use.

        ``touch_existing`` is False by default: an extraction run may not add,
        restate or contradict an axiom on a curated class. Those edges are
        counted in the report instead of applied.

        ``lexicon`` defaults to MILD + the import modules, so a term defined in
        an import resolves to its own IRI instead of being minted as a WONT
        duplicate. Pass ``lexicon=()`` to mint everything unresolved.
        """
        from pathlib import Path as _Path

        from wound_ontology.owl.extend import extend_ground_truth
        from config.settings import GROUND_TRUTH_TTL, PROJECT_ROOT

        out = _Path(output_file) if output_file else (
            _Path(PROJECT_ROOT) / "output" / "owl" / "wont_extended.ttl"
        )
        # Rule 66 (2026-10-03): only what was shown sound goes in.
        #  * relations: the ones read as true of every instance, nothing else --
        #    not the store's 26,372 and not the mereological hierarchy's text
        #    part_of edges, which nobody read;
        #  * subclass edges: curated and placed whole; a text edge only when its
        #    child is named in >= PLACEMENT_MIN_ABSTRACTS abstracts (the cut of
        #    rule 64, applied here to text as well).
        import json as _json
        read = _Path(PROJECT_ROOT) / "data" / "review" / "relation_universality_2026-10-02" / "result.json"
        if not read.exists():
            raise FileNotFoundError(f"{read} is missing: the WONT addition takes only read relations "
                                    f"(rule 66); run scripts/compile_universality.py")
        axioms = _json.loads(read.read_text(encoding="utf-8"))["axioms"]
        # The reading was done on the names of its day; a later rename (rule 70:
        # `ulcer` is now `Wound`) must reach it, or the export mints the old
        # name as a class of its own. Every name goes through the store's
        # resolver, the same one the view uses.
        resolve = self.store.resolver(mapped=True)
        relations = [(resolve(a["subject"])[1], a["predicate"], resolve(a["value"])[1]) for a in axioms]
        renamed = sum(1 for a, r in zip(axioms, relations) if (a["subject"], a["value"]) != (r[0], r[2]))
        if renamed:
            print(f"[Orchestrator] {renamed} read relation(s) carry a name renamed since the reading; "
                  f"exported under the current name")
        named = {}
        for key, ents in self.store.view():
            for name in ents:
                named.setdefault(smart_title(name), set()).add(key)
        edges, cut = [], Counter()
        for child in self.class_hier.df.index:
            for parent in self.class_hier.parents_of(child):
                if child == parent:
                    continue
                src = self.class_hier.source_of(child, parent) or "text"
                if src == "text" and len(named.get(smart_title(child), ())) < PLACEMENT_MIN_ABSTRACTS:
                    cut["text, child in < 2 abstracts"] += 1
                    continue
                if src == "fca" and not include_fca:
                    cut["fca, not included"] += 1
                    continue
                edges.append((str(child), str(parent)))
                cut[f"kept {src}"] += 1
        print(f"[Orchestrator] WONT addition input: {len(relations)} read relation(s) (rule 66); "
              f"subclass edges {dict(cut)}")
        # Rule 71: persistent ids for minted classes. A renamed class keeps its
        # id through its former spellings (the term dict's aliases).
        from wound_ontology.owl.id_registry import IdRegistry
        from wound_ontology.utils.normalise import normalise as _normalise
        registry = IdRegistry(_Path(PROJECT_ROOT) / "data" / "registry" / "wont_ids.json",
                              namespace="https://bioportal.bioontology.org/ontologies/WONT/")
        tdict = self.term_mapper._term_mapping
        live_keys = {_normalise(n).key for c, p in edges for n in (c, p)} | \
                    {_normalise(n).key for s_, _p, t_ in relations for n in (s_, t_)}
        former: dict[str, list[str]] = {}
        for old in tdict.aliases():
            now = tdict.resolve(old)
            if now != old:
                former.setdefault(_normalise(now).key, []).append(old)
        from wound_ontology.owl.extend import IMPORT_SKIP, other_names
        report = extend_ground_truth(
            ground_truth=GROUND_TRUTH_TTL,
            output=out,
            class_hier=self.class_hier,
            class_edges=edges,
            relations=relations,
            touch_existing=touch_existing,
            lexicon=lexicon,
            registry=registry,
            # A former spelling counts only once it is no longer a name of its
            # own in this build; otherwise two live classes would be merged.
            former_names=lambda term: [f for f in former.get(_normalise(term).key, ())
                                       if _normalise(f).key not in live_keys],
            # Rule 74: a term no import defines is looked for under the class the
            # term dict maps it onto (it IS that class), else under its former
            # spellings (`sample from organism` was OBI's `specimen from organism`).
            import_names=other_names(tdict),
            import_skip=IMPORT_SKIP,
        )
        print(f"[Orchestrator] found in an import under another name (rule 74): "
              f"{ {t: f'{o} -> {i.rsplit(chr(47), 1)[-1]}' for t, (o, i) in sorted(report.resolved_other_name.items())} }")
        registry.save(backup_dir=_Path(PROJECT_ROOT) / "data" / "backup" / "registry")
        # The next free WONT id, for Protégé's new-entity counter (curator:
        # "I'll reset Protégé every time").
        import re as _re
        used = [int(m.group(1)) for iri in registry.entries
                for m in [_re.search(r"WONT_(\d+)$", iri)] if m]
        from wound_ontology.owl.extend import next_free_id as _nfi
        import rdflib as _rdflib
        _gt = _rdflib.Graph(); _gt.parse(str(GROUND_TRUTH_TTL), format="turtle")
        nxt = max([_nfi(_gt) - 1, *(u for u in used if u < 100000)]) + 1
        free_file = out.parent / "NEXT_FREE_WONT_ID.txt"
        free_file.write_text(f"WONT_{nxt:07d}\n", encoding="utf-8")
        assert free_file.read_text(encoding="utf-8").strip() == f"WONT_{nxt:07d}"
        print(f"[Orchestrator] next free WONT id: WONT_{nxt:07d} (set Protégé's counter to {nxt}; "
              f"written to {free_file.name})")
        ch = registry.changes
        print(f"[Orchestrator] ids (rule 71): {ch['reused']:,} kept, {ch['issued']:,} issued, "
              f"{ch['renamed']:,} under a new name, {len(ch['merged'])} merged into another "
              f"(obsolete, replaced_by); registry {len(registry.entries):,} entries, read back")
        print(f"[Orchestrator] Extended ground truth -> {out}")
        print(report.summary())
        return report

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
        """Enrich external classes in a mapped OWL file with labels and definitions.

        For every non-WOND OBO class in *input_file*, looks up rdfs:label and
        IAO:0000115 from local source-ontology files and writes them in-place.
        Writes to *output_file* (defaults to overwriting *input_file*).

        onto_dir: path to local ontology files.  Defaults to IMPORT_ONTO_DIR
                  from config/settings.py.
        """
        from wound_ontology.owl.ontology_mapper import OntologyMapper

        try:
            from config.settings import IMPORT_ONTO_DIR as _default_onto_dir
        except ImportError:
            _default_onto_dir = None

        resolved_onto_dir = onto_dir or _default_onto_dir
        if resolved_onto_dir is None:
            raise ValueError("onto_dir must be provided or IMPORT_ONTO_DIR set in config/settings.py")

        mapper = OntologyMapper(onto_dir=resolved_onto_dir)
        stats  = mapper.enrich_external(input_file, output_file, dry_run=dry_run)
        if not dry_run:
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
        Returns MapResult for further inspection.
        """
        from wound_ontology.owl.ontology_mapper import OntologyMapper
        from pathlib import Path as _Path
        from datetime import datetime

        root = _Path(self.dm.base_path) if hasattr(self.dm, "base_path") and self.dm.base_path else _Path(".")

        def _resolve(p: str) -> _Path:
            pp = _Path(p)
            return pp if pp.is_absolute() else root / pp

        mapper = OntologyMapper()
        result = mapper.align(
            _resolve(source_owl),
            _resolve(target),
            method=method,
            top_k=top_k,
            threshold=close_thresh,
        )

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        out   = _resolve(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        mapper.write_candidates(result, out / f"alignment_candidates_{stamp}.csv")
        mapper.write_sssom(result,      out / f"alignment_{stamp}.sssom.tsv")

        ext_owl = out / f"source_extended_{stamp}.owl"
        if extend:
            mapper.extend(result, ext_owl, dry_run=dry_run)
        if enrich:
            enrich_path = ext_owl if ext_owl.exists() else _resolve(source_owl)
            mapper.enrich(result, enrich_path, dry_run=dry_run)

        if result.unmatched:
            print(f"\n[align_ontology] {len(result.unmatched)} source classes "
                  f"have no mapping in {_resolve(target).name}:")
            for iri in result.unmatched[:20]:
                label = next((k for k, v in result.source_label_index.items()
                              if v == iri), str(iri))
                print(f"  {label}")
            if len(result.unmatched) > 20:
                print(f"  ... and {len(result.unmatched) - 20} more")

        return result

    # ── Competency questions (C8) ──────────────────────────────────────────

    def run_competency_check(self, ontology_file: str | None = None,
                             with_imports: bool = True, write_report: bool = True):
        """Run config/competency_questions.json as executable queries.

        Turns the CQ file from prompt text into a measurement of whether the
        ontology answers the questions it was built for. Verdicts are PASS,
        FAIL, UNEXPRESSIBLE (the CQ uses a relation this ontology deliberately
        rejects, so it can never pass as written), UNRESOLVED (a term in the
        triple has no class with that label) and DECLARED (out of scope, nothing
        tested — deliberately NOT counted as a pass).
        """
        import rdflib
        from wound_ontology.evaluation import load_questions, run_suite
        from wound_ontology.evaluation.competency import (
            in_scope_score, report as _report,
        )
        from config.settings import (
            GROUND_TRUTH_TTL as _GT, MILD_TTL as _MILD,
            MILD_MODULES_DIR as _MODS, PROJECT_ROOT as _ROOT,
        )

        from pathlib import Path as _P

        g = rdflib.Graph()
        sources: list[str] = []
        if ontology_file:
            g.parse(str(ontology_file))
            sources.append(str(ontology_file))
        else:
            # The pipeline's own output, not the ground truth it started from.
            # This defaulted to GROUND_TRUTH_TTL, so every report ever written
            # measured WONT + MILD and stopped -- the extension's contribution,
            # which is the entire point of running the pipeline, was never in
            # the number and had to be measured by hand.
            extended = _P(_ROOT) / "output" / "owl" / "wont_extended.ttl"
            if extended.exists():
                g.parse(str(extended), format="turtle")
                sources.append(f"{extended.name} (contains the ground truth as its base)")
            else:
                g.parse(str(_GT), format="turtle")
                sources.append(f"{_P(_GT).name}")
                print("[Orchestrator] WARNING: output/owl/wont_extended.ttl does not "
                      "exist, so this measures the GROUND TRUTH, not the pipeline's "
                      "output. Run run_extend_ground_truth() first if that is not "
                      "what you meant.")
        # MILD and the modules whichever file was named (2026-09-28): with an
        # explicit `ontology_file` they used to be skipped, and the extended
        # WONT scored 44/49 -- `Foot`, `Wound Healing`, `increased area` and
        # `prophylaxis plan specification` all live in the imports.
        if True:
            g.parse(str(_MILD), format="turtle")
            sources.append(_P(_MILD).name)
            if with_imports:
                skipped: list[str] = []
                mods = sorted(_MODS.glob("*_module.owl"))
                for m in mods:
                    try:
                        g.parse(str(m))
                    except Exception as exc:
                        skipped.append(f"{m.name}: {exc}")
                        print(f"  ! skipped {m.name}: {exc}")
                sources.append(f"{len(mods) - len(skipped)} of {len(mods)} MILD import modules"
                               + (f" ({len(skipped)} unparseable)" if skipped else ""))

        results = run_suite(g, load_questions(_ROOT / "config" / "competency_questions.json"))
        text = _report(results)
        # A score is only interpretable next to what it was measured over. The
        # report carried none, which is how a stale one went unnoticed.
        provenance = ("measured over:\n" + "\n".join(f"  - {s}" for s in sources)
                      + f"\n  = {len(g)} triples")
        print(provenance)
        print(text)
        if write_report:
            out = _ROOT / "output" / "competency_report.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("# Competency question report\n\n```\n" + provenance
                           + "\n\n" + text + "\n```\n", encoding="utf-8")
            print(f"[Orchestrator] Report → {out}")
        p, n = in_scope_score(results)
        return results, (p, n)

    # ── Reasoner gate (C7) ─────────────────────────────────────────────────

    def build_reasoner_skeleton(self, force: bool = False) -> str:
        """Build (or reuse) the skeleton TBox the per-batch gate reasons over.

        MILD + WONT own axioms + an explicit BFO backbone, imports stripped.
        The full import closure carries 54 pre-existing unsatisfiable classes,
        so a gate reasoning over it would fire on every batch; the skeleton has
        none, which means anything it reports was caused by the batch.
        """
        from wound_ontology.reasoning.skeleton import build_skeleton
        from config.settings import (
            GROUND_TRUTH_TTL as _GT, MILD_TTL as _MILD,
            REASONER_SKELETON as _SK,
        )
        from pathlib import Path as _P

        missing = [str(s) for s in (_GT, _MILD) if not _P(s).exists()]
        if missing:
            raise FileNotFoundError(
                "[Orchestrator] build_reasoner_skeleton cannot read its sources: "
                + ", ".join(missing) + ". The skeleton IS WONT + MILD; there is "
                "no degraded skeleton worth building without them."
            )

        # The cached skeleton is only valid while it is newer than what it was
        # derived from. Reusing it on existence alone was measured to fail
        # exactly that way on 2026-09-10: skeleton_tbox.ttl 20 Aug 22:13 against
        # a ground_truth_final.owl of 4 Sep 19:32, so BOTH gates had spent
        # fifteen days reasoning over a WONT that no longer existed -- and said
        # nothing. Rebuild instead, and announce which source moved.
        if _P(_SK).exists() and not force:
            cached = _P(_SK).stat().st_mtime
            from config.settings import MILD_MODULES_DIR as _MODS
            newer = [s for s in (_GT, _MILD, *sorted(_P(_MODS).glob("*_module.owl")))
                     if _P(s).stat().st_mtime > cached]
            if not newer:
                print(f"[Orchestrator] Reusing skeleton TBox at {_SK}")
                return str(_SK)
            for src in newer:
                print(f"[Orchestrator] Skeleton TBox is STALE: {_P(src).name} is "
                      f"newer than {_P(_SK).name} — rebuilding.")
        from config.settings import MILD_MODULES_DIR as _MODS
        _mods = sorted(_P(_MODS).glob("*_module.owl"))
        if not _mods:
            raise FileNotFoundError(f"no import modules in {_MODS}: the skeleton takes BFO's axioms "
                                    f"and the relations' domains and ranges from them (rule 66)")
        path, n = build_skeleton(_GT, _MILD, _SK, modules=_mods)
        print(f"[Orchestrator] Skeleton TBox built: {path} ({n} triples)")
        return str(path)

    @property
    def reasoner_gate(self):
        """Lazily constructed per-batch gate.

        Goes through build_reasoner_skeleton() rather than pointing straight at
        REASONER_SKELETON, because the staleness check lives there and this is
        the only place the skeleton is ever consumed. Taking the path directly
        is what let a fifteen-day-old skeleton stay in service.
        """
        if getattr(self, "_gate", None) is None:
            from wound_ontology.reasoning.gate import ReasonerGate
            self._gate = ReasonerGate(self.build_reasoner_skeleton())
        return self._gate

    GATE_AUTHOR = "reasoner_gate"

    def run_gate_store_relations(self, store=None, quarantine: bool = True,
                                 apply: bool = True):
        """Reason over the store's RELATIONS, before any hierarchy is built.

        A quarantined triple is REJECTED in the store -- a verdict by
        `reasoner_gate` beside the assertion -- not deleted. With `apply`, the
        gate's own earlier verdicts are lifted first, so the run re-tests every
        relation against the skeleton as it is NOW: a triple quarantined
        against last month's WONT gets its hearing again. If the gate then
        cannot run, the lifted verdicts are put back; a skipped gate must not
        turn into an un-vetted store.

        The sibling gate, `run_gate_hierarchy_edges`, runs at the other end of
        the pipeline and checks `is_a` edges. The two are not redundant: they see
        different axioms and they fail at different costs.

        * This gate sees `∃R.Filler` restrictions and nothing else -- `Wound
          has_quality Debridement` is a continuant/occurrent clash the reasoner
          rejects instantly, and it is invisible to a gate that only reads is_a.
        * The edge gate sees subsumption, which arrives from three sources
          (curated CSV, text, FCA) that never pass through the extraction schema.

        Running here also means a bad relation is caught BEFORE it feeds the FCA
        lattice and the hierarchies. A relation quarantined at the far end has
        already shaped the concept lattice that produced the is_a edges, so the
        damage outlives the axiom that caused it.
        """
        from config.settings import QUARANTINE_DIR as _Q
        from wound_ontology.llm.extraction_adapter import (
            describe_gate_inputs,
            normalize_predicate,
            store_to_gate_inputs,
        )

        st = store or self.store
        lifted = st.lift_decisions(self.GATE_AUTHOR) if apply else None
        entities, relations, report = store_to_gate_inputs(
            st, resolve_conflict=self.reasoner_gate.least_common_category)
        print("[Orchestrator] " + describe_gate_inputs(entities, relations, report)
              .replace("\n", "\n[Orchestrator] "))

        if report.get("reconciled"):
            print(f"[Orchestrator] {len(report['reconciled'])} term(s) were typed "
                  f"differently by different abstracts and retreated to the category "
                  f"MILD says subsumes them all. They ARE gated, at that category:")
            for lab, (cats, agreed) in sorted(report["reconciled"].items())[:20]:
                print(f"[Orchestrator]     {lab}: {', '.join(cats)} -> {agreed}")
        if report["conflicting"]:
            print(f"[Orchestrator] *** {len(report['conflicting'])} term(s) were typed "
                  f"in ways with NO common ancestor among the assignable categories "
                  f"(e.g. continuant vs occurrent). There is no honest category for "
                  f"them, so they are NOT gated: ***")
            for lab, cats in sorted(report["conflicting"].items())[:20]:
                print(f"[Orchestrator]     {lab}: {', '.join(cats)}")
        if report["unlicensed"]:
            print(f"[Orchestrator] *** {len(report['unlicensed'])} relation(s) violate "
                  f"the category-pair licensing table. They are still gated -- the "
                  f"reasoner is the authority -- but the schema disagrees: ***")
            for s_, p_, o_ in report["unlicensed"][:20]:
                print(f"[Orchestrator]     {s_} --{p_}--> {o_}")

        if not relations:
            print("[Orchestrator] No gateable relations. This is NOT a clean result "
                  "unless the store is genuinely empty -- see the counts above.")
            if lifted:
                n = st.restore_decisions(lifted)
                print(f"[Orchestrator] {n} earlier gate verdict(s) put back.")
            return None

        try:
            result = self.reasoner_gate.check(entities, relations)
        except BaseException:
            # `lift_decisions` has already saved the store without the gate's
            # verdicts. On 2026-10-07 the check crashed here and its 14
            # rejections stayed lifted: the next run took them as never made.
            if lifted:
                n = st.restore_decisions(lifted)
                print(f"[Orchestrator] *** the reasoner check failed; {n} earlier "
                      f"gate verdict(s) put back before stopping. ***")
            raise
        print(f"[Orchestrator] {result.summary()}")
        if result.without_individuals:
            print(f"[Orchestrator] *** WONT's named individuals were set aside for "
                  f"{len(result.without_individuals)} reasoner run(s), because a class "
                  f"those relations emptied holds one of them and an empty class with "
                  f"a member is a contradiction that names no culprit. The emptied "
                  f"classes are named instead and their relations held back as usual: ***")
            for note in result.without_individuals:
                print(f"[Orchestrator]     {note}")
        if result.skipped:
            print(f"[Orchestrator] *** GATE DID NOT RUN: {result.skipped} ***\n"
                  f"[Orchestrator] *** All {len(relations)} relation(s) were accepted "
                  f"WITHOUT being checked. This is not a clean result. ***")
            if lifted:
                n = st.restore_decisions(lifted)
                print(f"[Orchestrator] {n} earlier gate verdict(s) put back.")
            return result

        if apply and (result.quarantined_relations or result.quarantined_entities):
            # A quarantined triple is ONE axiom but many store cells: the store is
            # keyed by document, so the same assertion sits under every abstract
            # that made it. A cell verdict is keyed by (entity, triple) and so
            # covers every document at once; the assertions stay in the file.
            doomed = {(r.subject, f"{normalize_predicate(r.predicate.value)}: {r.object}")
                      for r in result.quarantined_relations}
            hit = {(e, t) for _, e, t, _ in st.assertions() if (e, t) in doomed}
            n = st.reject_cells(hit, by=self.GATE_AUTHOR,
                                note=(result.explanation or "unsatisfiable under the skeleton")[:200])
            print(f"[Orchestrator] Rejected {n} triple(s) the reasoner quarantined; "
                  f"the assertions stay in the store with the verdict beside them.")
            missed = doomed - hit
            if missed:
                print(f"[Orchestrator] *** {len(missed)} quarantined triple(s) were "
                      f"NOT found in the store and could not be removed. The gate "
                      f"and the store disagree about what is in it: ***")
                for lab, key in sorted(missed)[:20]:
                    print(f"[Orchestrator]     {lab} | {key}")
            if result.quarantined_entities:
                print(f"[Orchestrator] {len(result.quarantined_entities)} term(s) were "
                      f"quarantined by the reasoner but LEFT IN THE STORE -- removing a "
                      f"term is a curation decision, not a reasoning one. See the "
                      f"quarantine file.")

        if quarantine:
            from wound_ontology.reasoning.gate import ReasonerGate as _RG
            path = _RG.write_quarantine(result, _Q, tag="store_relations")
            if path:
                print(f"[Orchestrator] Quarantined relations → {path}")
        return result

    #: What a fresh view is built as. A class attribute so a test can hand in a
    #: stand-in without touching the derivation itself.
    _view_factory = ClassHierarchyView

    #: Where the edge gate's verdicts live: one record per gate run, replaced in
    #: full each time (every edge is re-heard), read by every freshly built view.
    EDGE_VERDICTS = "class_hierarchy_edge_verdicts"
    EDGE_GATE_AUTHOR = "reasoner_gate_edges"

    def _edge_verdicts(self) -> list[dict]:
        """The edge gate's standing rejections, as the last gate run wrote them."""
        raw = self.dm.load_latest_json(self.EDGE_VERDICTS)
        if raw is None:
            return []
        if not isinstance(raw, dict) or not isinstance(raw.get("rejected", []), list):
            raise ValueError(
                f"[Orchestrator] {self.EDGE_VERDICTS} is not an edge-verdict record "
                f"(expected {{'when': ..., 'rejected': [...]}}, got {type(raw).__name__}). "
                f"Building the view without it would bring rejected edges back unseen.")
        return list(raw.get("rejected", []))

    def _apply_edge_verdicts(self, view) -> int:
        """Take the edge gate's standing verdicts off a freshly built view.

        A curated edge is never taken off: it is the curator's to remove, and the
        gate's rank-aware check drops weaker evidence first anyway. One that
        carries a verdict is kept and named, so the conflict cannot go unseen.
        """
        n, gone, spared = 0, 0, []
        for v in self._edge_verdicts():
            c, p = smart_title(str(v["child"])), smart_title(str(v["parent"]))
            present = (c in view.df.index and p in view.df.columns
                       and view.df.at[c, p] == 1.0)
            if not present:
                gone += 1
                continue
            if view._prov.get((c, p)) == _SOURCE_CURATED:
                spared.append((c, p))
                continue
            view.df.at[c, p] = 0.0
            view._prov.pop((c, p), None)
            n += 1
        print(f"[Orchestrator] class hierarchy view: {n} edge(s) taken off by the edge "
              f"gate's standing verdicts"
              + (f"; {gone} verdict(s) name an edge no source asserts any more" if gone else "")
              + ".")
        if spared:
            print(f"[Orchestrator] *** {len(spared)} curated edge(s) carry an edge-gate "
                  f"verdict and were KEPT -- removing a curated edge is a curation "
                  f"decision, not a reasoning one: ***")
            for c, p in spared[:10]:
                print(f"[Orchestrator]     {c} is_a {p}")
        return n

    def _write_edge_verdicts(self, result, sources: dict) -> None:
        """Replace the edge gate's verdict record with this run's rejections."""
        from datetime import datetime as _dt
        note = (result.explanation or "unsatisfiable under the skeleton")[:200]
        rows = [{"child": c, "parent": p, "source": sources.get((c, p)) or "unstamped",
                 "by": self.EDGE_GATE_AUTHOR, "note": note}
                for c, p in result.quarantined]
        self.dm.save_as_json({"when": _dt.now().isoformat(timespec="seconds"),
                              "rejected": rows}, self.EDGE_VERDICTS)
        print(f"[Orchestrator] edge-gate verdicts replaced: {len(rows)} rejected edge(s) "
              f"on record ({self.EDGE_VERDICTS}).")

    def run_gate_hierarchy_edges(self, hierarchy=None, quarantine: bool = True,
                                 apply: bool = True):
        """Reason over the committed is_a edges and quarantine the inconsistent ones.

        This is where the gate matters most. Extracted relations are already
        filtered by the category-pair table, but is_a edges are not: the curated
        CSV and the FCA lattice bypass the extraction schema entirely. The table
        is also blind to same-category disjointness — `Wound base`, `Wound edge`
        and `Wound pocket` are all `material entity` yet pairwise disjoint.
        """
        from wound_ontology.reasoning.gate import ReasonerGate
        from config.settings import QUARANTINE_DIR as _Q

        # The view is rebuilt WITH the edges an earlier run rejected, so every edge
        # gets its hearing again against the skeleton as it is now -- the rule the
        # store gate follows with lift_decisions: a verdict reached against last
        # month's WONT is not a verdict about today's.
        own_view = hierarchy is None
        hier = self.refresh_class_hierarchy(include_rejected=True) if own_view else hierarchy

        # Edges come from the dataframe, which is what is actually committed.
        # This used to read hier._prov, i.e. only edges carrying provenance --
        # and provenance is absent on a first run or whenever the CSV is missing.
        # On live data that meant 5054 committed edges, 0 in _prov, so the gate
        # printed "No committed edges to gate", returned clean, and had inspected
        # nothing at all. A gate that reports success without looking is worse
        # than no gate.
        df = hier.df
        edges = [] if df.empty else [
            (str(c), str(p))
            for c in df.index for p in df.columns
            if df.at[c, p] == 1.0 and str(c) != str(p)
        ]
        if not edges:
            print("[Orchestrator] No committed edges in the hierarchy — nothing to gate. "
                  "If you expected edges here, the hierarchy did not load.")
            return None
        stamped = sum(1 for e in edges if e in hier._prov)
        print(f"[Orchestrator] Gating {len(edges)} committed edge(s); "
              f"{stamped} carry provenance, {len(edges) - stamped} do not.")

        # Hand the gate the provenance so a clash is resolved by dropping the
        # weakest evidence first. Without it the gate is rank-blind: WONT's
        # curated `Necrosis subClassOf pathological disorder` was quarantined
        # alongside the text-asserted `Necrosis is_a Process` that contradicted
        # it, which is a lower-ranked source overriding a higher one.
        result = self.reasoner_gate.check_edges(edges, sources=dict(hier._prov))
        print(f"[Orchestrator] {result.summary()}")
        if result.quarantined_sources:
            import collections as _c
            by_src = _c.Counter(v or "unstamped"
                                for v in result.quarantined_sources.values())
            print(f"[Orchestrator] quarantined by provenance: {dict(by_src)}")
        if result.spared:
            print(f"[Orchestrator] {len(result.spared)} higher-ranked edge(s) kept "
                  f"because a weaker edge on the same child was dropped instead:")
            for child, parent in result.spared[:10]:
                src = hier._prov.get((child, parent), "unstamped")
                print(f"[Orchestrator]     {child} is_a {parent}  [{src}]")
        if result.skipped:
            print(f"[Orchestrator] *** GATE DID NOT RUN: {result.skipped} ***\n"
                  f"[Orchestrator] *** All {len(edges)} edge(s) were accepted WITHOUT "
                  f"being checked. This is not a clean result. ***")
            if own_view:
                n = self._apply_edge_verdicts(hier)
                hier.verdicts_applied = True
                print(f"[Orchestrator] the earlier edge verdicts stay in force ({n} applied).")
            return result

        sources_before = dict(hier._prov)
        for child, parent in result.quarantined:
            if child in hier.df.index and parent in hier.df.columns:
                hier.df.at[child, parent] = 0.0
            hier._prov.pop((child, parent), None)
        if own_view:
            hier.verdicts_applied = True
            if apply:
                self._write_edge_verdicts(result, sources_before)
            hier.save_snapshot()
        if result.quarantined:
            if quarantine:
                d = _Q
                d.mkdir(parents=True, exist_ok=True)
                from datetime import datetime as _dt
                import json as _json
                p = d / f"edges_{_dt.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
                p.write_text(_json.dumps({
                    "unsatisfiable": result.unsatisfiable,
                    "edges": result.quarantined,
                    "explanation": result.explanation,
                }, indent=2), encoding="utf-8")
                print(f"[Orchestrator] Quarantined edges → {p}")
        return result

    def run_deep_reason(self, input_file: str, output_file: str) -> None:
        """On-demand HermiT check over the FULL merge (slow, complements the gate).

        The per-batch gate uses ELK, which cannot express inverse properties,
        cardinality or universal restrictions. Run this when you want those
        checked, not on every batch.
        """
        print("[Orchestrator] Deep reasoning (HermiT, full merge) — this is slow.")
        self.reasoner.reason(input_file, output_file)

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


    # ── OWL grounding / replacement ────────────────────────────────────────────

    def run_replace_upper_stubs(
        self,
        source_file: str,
        output_file: str | None = None,
        dry_run: bool = False,
    ) -> None:
        """Replace WOND_120xxx structural stubs with their external OBO IRIs.

        Rewrites every rdfs:subClassOf that pointed to a stub, removes the stub
        and any artifact axioms, and anchors WOND_0000249 to BFO:0000015.

        source_file: source TTL/OWL file (usually data/raw/*.ttl).
        output_file: destination (default: overwrite source_file).
        """
        from wound_ontology.owl.upper_stub_replacer import UpperStubReplacer
        UpperStubReplacer().run(source_file, output=output_file, dry_run=dry_run)

    def run_map_ontology(
        self,
        owl_file: str,
        output_file: str | None = None,
        onto_dir: str | None = None,
        targets: list[str] | None = None,
        method: str = "lexical",
        mode: str = "replace",
        threshold: float = 0.90,
        use_synonyms: bool = False,
        model: str = "openrouter/deepseek/deepseek-v4-flash",
        schema_path: str | None = None,
        cache_path: str | None = None,
        candidates_path: str | None = None,
        sssom_path: str | None = None,
        top_k: int = 5,
        dry_run: bool = False,
    ) -> None:
        """Map source OWL classes to target ontology concepts.

        Replaces run_ground_wond_classes (method="ontogpt", mode="subclass"),
        run_replace_wond_classes (method="lexical", mode="replace"), and
        run_sapbert_ground (method="sapbert", mode="replace"/"subclass").

        Args:
            owl_file:         Source OWL/Turtle file.
            output_file:      Output path (default: overwrite owl_file).
            onto_dir:         Directory with local OBO/OWL files.
                              Defaults to IMPORT_ONTO_DIR in config/settings.py.
            targets:          Ordered list of ontology keys; order = priority.
                              None → DEFAULT_PRIORITY from ontology_mapper.
            method:           "lexical" | "sapbert" | "ontogpt" | "llm"
            mode:             "replace" | "xref" | "subclass"
                              Ignored for method="ontogpt" (always subclass).
            threshold:        Minimum cosine similarity for sapbert/llm.
            use_synonyms:     Match against hasExactSynonym (lexical method).
            model:            LiteLLM / OpenRouter model for ontogpt or llm.
            schema_path:      OntoGPT schema YAML (method="ontogpt").
                              Defaults to GROUNDING_SCHEMA in config/settings.py.
            cache_path:       JSON cache for ontogpt/llm (avoids re-calling LLM).
            candidates_path:  Optional CSV of top-K candidates per source class.
            sssom_path:       Optional SSSOM TSV of best matches.
            top_k:            Candidate count for sapbert/llm.
            dry_run:          Print plan without writing any files.
        """
        from wound_ontology.owl.ontology_mapper import OntologyMapper
        from pathlib import Path as _Path

        try:
            from config.settings import IMPORT_ONTO_DIR as _default_onto_dir
        except (ImportError, AttributeError):
            _default_onto_dir = None

        resolved_onto = onto_dir or _default_onto_dir

        # schema_path fallback for ontogpt
        resolved_schema = schema_path
        if method == "ontogpt" and not resolved_schema:
            try:
                from config.settings import GROUNDING_SCHEMA
                resolved_schema = GROUNDING_SCHEMA
            except (ImportError, AttributeError):
                resolved_schema = str(
                    _Path(owl_file).parents[2] / "config" / "grounding_schema.yaml"
                )

        OntologyMapper(onto_dir=resolved_onto).run(
            source_owl=owl_file,
            output_path=output_file,
            targets=targets,
            method=method,
            mode=mode,
            threshold=threshold,
            use_synonyms=use_synonyms,
            model=model,
            schema_path=resolved_schema,
            cache_path=cache_path,
            candidates_path=candidates_path,
            sssom_path=sssom_path,
            top_k=top_k,
            dry_run=dry_run,
        )

    # ── PubMed query validation ────────────────────────────────────────────────

    def run_validate_pubmed_queries(
        self,
        queries: list[str] | None = None,
        sample_n: int = 5,
        max_retries: int = 2,
        delay: float = 0.4,
        out_path: str | None = None,
    ) -> list:
        """Validate PubMed search queries for wound-ontology scope.

        For each query: fetches a sample of abstracts, asks Claude Haiku to
        evaluate scope, and revises failing queries (up to max_retries times).

        queries:     List of query strings; defaults to config/pubmed_query_list.py.
        sample_n:    Abstracts per query to sample.
        max_retries: Max revision attempts per failing query.
        out_path:    JSON report output path (default: scripts/query_validation_report.json).
        """
        from wound_ontology.connectors.pubmed_query_validator import PubMedQueryValidator
        import os as _os
        from pathlib import Path as _Path

        if queries is None:
            from config.pubmed_query_list import PUBMED_SEARCH
            queries = PUBMED_SEARCH

        email   = _os.getenv("ENTREZ_EMAIL", "")
        api_key = _os.getenv("OPENROUTER_API_KEY", "")
        if not email:
            raise RuntimeError("ENTREZ_EMAIL is not set in .env")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set in .env")

        if out_path is None:
            try:
                from config.settings import PROJECT_ROOT as _root
            except ImportError:
                _root = _Path(__file__).resolve().parents[3]
            out_path = str(_Path(_root) / "scripts" / "query_validation_report.json")

        return PubMedQueryValidator(email, api_key).run(
            queries,
            sample_n=sample_n,
            max_retries=max_retries,
            delay=delay,
            out_path=out_path,
        )

    # ── UML generation ─────────────────────────────────────────────────────────

    def generate_uml(self, out_dir: str = "docs/uml") -> None:
        """Generate PlantUML class and package diagrams with pyreverse.

        Requires: pip install pylint  (ships pyreverse).
        Output .puml files are written to *out_dir*.
        Preview in VS Code with the jebbs.plantuml extension (Alt+D).
        """
        import subprocess
        from pathlib import Path as _Path

        try:
            from config.settings import PROJECT_ROOT as _root
        except ImportError:
            _root = _Path(__file__).resolve().parents[3]

        src_dir = _Path(_root) / "src" / "wound_ontology"
        out     = _Path(out_dir) if _Path(out_dir).is_absolute() else _Path(_root) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        cmd = [
            "pyreverse",
            "--output", "plantuml",
            "--project", "wound_ontology",
            "--colorized",
            "--filter-mode", "PUB_ONLY",
            "--output-directory", str(out),
            str(src_dir),
        ]
        print(f"Running pyreverse on {src_dir} …")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError("pyreverse failed — is pylint installed? (pip install pylint)")
        print(f"Generated in {out}:")
        for f in sorted(out.glob("*.plantuml")):
            print(f"  {f.name}")
        print("\nOpen a .plantuml file in VS Code and press Alt+D to preview.")

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
