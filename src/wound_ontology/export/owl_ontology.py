from __future__ import annotations
import re
import tempfile
import types as python_types
from pathlib import Path

from rdflib import Graph, URIRef, RDFS
from owlready2 import (
    World, Thing, ObjectProperty, TransitiveProperty,
    AnnotationProperty, destroy_entity, locstr,
)

try:
    from config.settings import (
        OWL_OUTPUT_FILE as _DEFAULT_OUTPUT,
        ONTOLOGY_BASE_IRI, ONTOLOGY_ID_PREFIX, ONTOLOGY_ID_START,
        BFO_OWL_URL as _BFO_URL, RO_OWL_URL as _RO_URL, OBI_OWL_URL as _OBI_URL,
    )
except ImportError:
    _DEFAULT_OUTPUT    = (
        Path(__file__).resolve().parents[3] / "output" / "owl" / "ontology_classes.owl"
    )
    ONTOLOGY_BASE_IRI  = "http://purl.obolibrary.org/obo/WOND_"
    ONTOLOGY_ID_PREFIX = "WOND"
    ONTOLOGY_ID_START  = 1
    _BFO_URL = "http://purl.obolibrary.org/obo/bfo.owl"
    _RO_URL  = "http://purl.obolibrary.org/obo/ro.owl"
    _OBI_URL = "http://purl.obolibrary.org/obo/obi.owl"

# IRIs that belong to published external ontologies — never renamed locally
EXTERNAL_PREFIXES: tuple[str, ...] = (
    "http://purl.obolibrary.org/obo/",
    "http://www.w3.org/",
    "http://www.geneontology.org/",
    "http://purl.org/dc/",
    "https://purl.bioontology.org/",
)


def _name_to_label(name: str) -> str:
    """Convert underscore or CamelCase name to a human-readable label."""
    label = name.replace("_", " ")
    label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label)
    label = label.strip()
    return (label[0].upper() + label[1:].lower()) if label else label


class OWLOntology:
    """
    Central data object for an OWL ontology — analogous to ConceptStore for
    the store layer.  Owns the owlready2 World and ontology lifecycle, and
    provides both construction and in-place enrichment methods.

    ── Construction ──────────────────────────────────────────────────────────

    get_data(class_hier, mere_hier, fca_hier)
        Build from internal pipeline hierarchies (replaces OWLExporter).

    load(owl_file)
        Load an existing OWL/RDF-XML file into a fresh World.

    ── In-place enrichment (replaces OWLCurator) ─────────────────────────────

    import_connector(*connectors)   — import BFO/RO/OBI from loaded connectors
    import_external(*urls)          — import by URL (fallback)
    import_bfo() / import_ro() / import_obi()
    resolve_external_classes()      — rewire + destroy local shadows of external classes
    normalize_label_language(lang)  — fix rdfs:label language tags
    rename_iris(base_iri, prefix)   — assign WOND_NNNNNNN IRIs + rdfs:labels
    umls_mapping(connector)         — annotate with hasUMLSSynonym

    ── Persistence ───────────────────────────────────────────────────────────

    save(output_file)

    ── Reasoning ─────────────────────────────────────────────────────────────

    Reasoning (Pellet/HermiT) is kept in OWLReasoner — it requires Java/JPype
    and is kept separate because it can fail for infrastructure reasons
    independent of the ontology content.

    ── Fluent API example ────────────────────────────────────────────────────

        onto = OWLOntology()
        onto.get_data(pipeline.class_hier, pipeline.mere_hier)
        onto.import_bfo().import_ro()
        onto.resolve_external_classes()
        onto.normalize_label_language()
        onto.rename_iris()
        onto.save("output/wound_ontology.owl")

    Or via the orchestrator:
        pipeline.export_to_owl()
        pipeline.run_curate_owl(input_file=..., output_file=...)
    """

    def __init__(
        self,
        iri:       str = "http://example.org/ontology",
        base_iri:  str = ONTOLOGY_BASE_IRI,
        id_prefix: str = ONTOLOGY_ID_PREFIX,
        id_start:  int = ONTOLOGY_ID_START,
    ):
        self._iri      = iri
        self.base_iri  = base_iri
        self.id_prefix = id_prefix
        self._counter  = id_start
        self._world    = World()
        self._onto     = self._world.get_ontology(iri)
        self._rg: Graph | None = None          # rdflib graph (lazy / populated by load)
        self._sparql_helper = None             # SPARQLHelper cache

    # ── Construction from hierarchies ─────────────────────────────────────────

    def get_data(
        self,
        class_hierarchy=None,
        mereological_hierarchy=None,
        fca_hierarchy=None,
    ) -> "OWLOntology":
        """
        Build OWL axioms from BaseHierarchy objects.

          class_hierarchy        → rdfs:subClassOf edges
          mereological_hierarchy → part_of existential restrictions
          fca_hierarchy          → rdfs:subClassOf edges (FCA-derived superclasses)

        Idempotent: calling again adds axioms incrementally.
        """
        cls_reg: dict[str, object] = {}

        if class_hierarchy is not None and not class_hierarchy.df.empty:
            self._export_hierarchy(cls_reg, class_hierarchy, "ClassHierarchy")

        if mereological_hierarchy is not None and not mereological_hierarchy.df.empty:
            self._export_mereological(cls_reg, mereological_hierarchy)

        if fca_hierarchy is not None and not fca_hierarchy.df.empty:
            self._export_hierarchy(cls_reg, fca_hierarchy, "FCAHierarchy")

        return self

    # ── Load from file ─────────────────────────────────────────────────────────

    def load(self, owl_file: str) -> "OWLOntology":
        """Load an OWL/RDF-XML file into a fresh owlready2 World and rdflib Graph."""
        path = Path(owl_file).resolve()
        self._world = World()
        try:
            self._onto = self._world.get_ontology(f"file://{path}").load()
        except Exception as exc:
            print(f"[OWLOntology] owlready2 import warning ({exc.__class__.__name__}) "
                  f"— using rdflib-only mode for {path.name}")
            self._onto = self._world.get_ontology(f"file://{path}")
        self._rg    = Graph()
        self._rg.parse(str(path), format="xml")
        self._sparql_helper = None
        print(f"[OWLOntology] Loaded: {path}")
        return self

    # ── External imports ───────────────────────────────────────────────────────

    def import_connector(self, *connectors) -> "OWLOntology":
        """
        Import ontologies already loaded by OntoConnector instances (BFO, RO, OBI…).
        Reuses the connector's owlready2 ontology — no second download.
        """
        for connector in connectors:
            if connector.onto is None:
                print(f"[OWLOntology] {connector.source_name} not loaded — skipping.")
                continue
            ext = self._world.get_ontology(connector.onto_url).load()
            if ext not in self._onto.imported_ontologies:
                self._onto.imported_ontologies.append(ext)
                print(f"[OWLOntology] Imported via connector: {connector.source_name}")
        return self

    def import_external(self, *urls: str) -> "OWLOntology":
        """Import ontologies by URL (fallback when connectors are not available)."""
        for url in urls:
            ext = self._world.get_ontology(url).load()
            if ext not in self._onto.imported_ontologies:
                self._onto.imported_ontologies.append(ext)
                print(f"[OWLOntology] Imported: {url}")
        return self

    def import_bfo(self) -> "OWLOntology":
        return self.import_external(_BFO_URL)

    def import_ro(self) -> "OWLOntology":
        return self.import_external(_RO_URL)

    def import_obi(self) -> "OWLOntology":
        return self.import_external(_OBI_URL)

    # ── External class resolution ──────────────────────────────────────────────

    def resolve_external_classes(self) -> "OWLOntology":
        """
        Replace local classes that shadow an already-imported external class
        (BFO, RO, OBI…) with the canonical external class.

        For each local class whose label/name matches one in an imported ontology:
          1. Rewire all subClassOf edges to the external class.
          2. Destroy the redundant local class.

        Call AFTER import_connector() and BEFORE rename_iris().
        """
        label_map: dict[str, object] = {}
        for imported_onto in self._onto.imported_ontologies:
            for cls in imported_onto.classes():
                for lbl in cls.label:
                    label_map[str(lbl).lower().strip()] = cls
                name_key = cls.name.lower().replace("_", " ").strip()
                if name_key not in label_map:
                    label_map[name_key] = cls

        if not label_map:
            print("[OWLOntology] No imported ontologies to resolve against — skipping.")
            return self

        resolved = 0
        with self._onto:
            for local_cls in list(self._onto.classes()):
                if not self.is_local(local_cls):
                    continue
                key = (str(local_cls.label.first()).lower().strip()
                       if local_cls.label
                       else local_cls.name.lower().replace("_", " ").strip())
                ext_cls = label_map.get(key)
                if ext_cls is None:
                    continue
                for other in list(self._onto.classes()):
                    if local_cls in other.is_a:
                        other.is_a.remove(local_cls)
                        if ext_cls not in other.is_a:
                            other.is_a.append(ext_cls)
                try:
                    destroy_entity(local_cls)
                    resolved += 1
                except Exception as exc:
                    print(f"[OWLOntology] Could not destroy '{local_cls.name}': {exc}")

        print(f"[OWLOntology] Resolved {resolved} local classes to external IRIs.")
        return self

    # ── Label language normalisation ───────────────────────────────────────────

    def normalize_label_language(
        self,
        target_lang: str = "en",
        source_lang: str | None = None,
    ) -> "OWLOntology":
        """
        Re-tag rdfs:labels that carry the wrong (or no) language tag.

        target_lang  — desired tag, e.g. "en" (default)
        source_lang  — if set, only fix labels whose current tag matches this
                       value (e.g. "de").  None = fix all non-target tags.

        Call BEFORE rename_iris() so corrected labels are in place.
        """
        fixed = 0
        with self._onto:
            for entity in list(self._onto.classes()) + list(self._onto.individuals()):
                new_labels, changed = [], False
                for lbl in list(entity.label):
                    lang = getattr(lbl, "lang", None)
                    if lang == target_lang:
                        new_labels.append(lbl)
                        continue
                    if source_lang is not None and lang != source_lang:
                        new_labels.append(lbl)
                        continue
                    new_labels.append(locstr(str(lbl), target_lang))
                    changed = True
                if changed:
                    entity.label = new_labels
                    fixed += 1
        print(f"[OWLOntology] normalize_label_language: {fixed} entities re-tagged → '{target_lang}'.")
        return self

    # ── IRI renaming + labeling ────────────────────────────────────────────────

    def rename_iris(self) -> "OWLOntology":
        """
        Assign proper ontology IRIs (WOND_NNNNNNN) to all local entities and
        set rdfs:label (en) from the original name.

        External entities (OBO, W3C …) are left untouched.
        Call AFTER resolve_external_classes() and normalize_label_language().
        """
        entities = (
            list(self._onto.classes())
            + list(self._onto.object_properties())
            + list(self._onto.data_properties())
            + list(self._onto.individuals())
        )
        renamed = 0
        with self._onto:
            for entity in entities:
                if self.is_local(entity):
                    original_name = entity.name
                    if not entity.label:
                        entity.label = [locstr(_name_to_label(original_name), "en")]
                    new_iri = f"{self.base_iri}{self._next_id()}"
                    try:
                        entity.iri = new_iri
                        renamed += 1
                    except Exception as e:
                        print(f"[OWLOntology] IRI rename failed for '{original_name}': {e}")
        print(f"[OWLOntology] Renamed {renamed} local entities.")
        return self

    # ── UMLS synonym mapping ───────────────────────────────────────────────────

    def umls_mapping(self, umls_connector, max_results: int = 3) -> "OWLOntology":
        """
        Annotate each local class with hasUMLSSynonym (CUI + preferred name).
        Additive — never replaces WOND IRIs.  Call AFTER rename_iris().
        """
        with self._onto:
            class hasUMLSSynonym(AnnotationProperty):
                namespace = self._onto

        local_classes = [c for c in self._onto.classes() if self.is_local(c)]
        if not local_classes:
            print("[OWLOntology] No local classes to map — skipping UMLS mapping.")
            return self

        mapped = 0
        print(f"[OWLOntology] UMLS mapping for {len(local_classes)} classes...")
        for cls in local_classes:
            label = str(cls.label.first()) if cls.label else cls.name
            hits = umls_connector.lookup(label, max_results=max_results)
            if not hits:
                continue
            with self._onto:
                for cui, preferred_name in hits:
                    annotation = f"{preferred_name} (UMLS:{cui})"
                    if annotation not in cls.hasUMLSSynonym:
                        cls.hasUMLSSynonym.append(annotation)
            mapped += 1

        print(f"[OWLOntology] UMLS synonyms added to {mapped}/{len(local_classes)} classes.")
        return self

    # ── Label normalization ───────────────────────────────────────────────────

    def normalize_labels(
        self,
        strip_whitespace: bool = True,
        title_case: bool = False,
    ) -> "OWLOntology":
        """
        Normalize ``rdfs:label`` values on all classes and individuals.

        strip_whitespace
            Collapse internal runs of whitespace to a single space and remove
            leading/trailing whitespace (default: True).
        title_case
            Apply Python ``str.title()`` after whitespace normalization
            (default: False).

        Invalidates the cached rdflib graph and SPARQLHelper so subsequent
        calls to ``rdf_graph`` / ``sparql`` reflect the updated labels.
        """
        if self._onto is None:
            return self
        changed = 0
        with self._onto:
            entities = list(self._onto.classes()) + list(self._onto.individuals())
            for entity in entities:
                new_labels, was_changed = [], False
                for lbl in list(entity.label):
                    s = str(lbl)
                    norm = re.sub(r"\s+", " ", s).strip() if strip_whitespace else s
                    if title_case:
                        norm = norm.title()
                    lang = getattr(lbl, "lang", None)
                    if norm != s:
                        new_labels.append(locstr(norm, lang or "en"))
                        was_changed = True
                    else:
                        new_labels.append(lbl)
                if was_changed:
                    entity.label = new_labels
                    changed += 1
        self._rg = None
        self._sparql_helper = None
        print(f"[OWLOntology] normalize_labels: {changed} entities updated.")
        return self

    # ── Lookup ────────────────────────────────────────────────────────────────

    def label_of(self, iri: str | URIRef, lang: str = "en") -> str | None:
        """
        Return the ``rdfs:label`` of *iri*.

        Delegates to :attr:`sparql` — prefers *lang*-tagged label, falls back
        to any label, returns ``None`` when absent.
        """
        return self.sparql.label_of(str(iri), lang=lang)

    def iri_of_label(
        self, label: str, lang: str | None = None
    ) -> URIRef | None:
        """
        Reverse label lookup — first IRI whose ``rdfs:label`` matches *label*
        (case-insensitive).  Delegates to :attr:`sparql`.
        """
        result = self.sparql.iri_of_label(label, lang=lang)
        return URIRef(result) if result else None

    # ── rdflib graph / SPARQL ─────────────────────────────────────────────────

    @property
    def rdf_graph(self) -> Graph:
        """
        rdflib.Graph representation of this ontology.

        When the ontology was created via ``load()``, the graph is already
        populated.  When created via ``get_data()`` (owlready2 construction
        path), the graph is lazily serialized from the owlready2 world on
        first access.
        """
        if self._rg is None:
            tmp = Path(tempfile.mkstemp(suffix=".owl")[1])
            try:
                self._onto.save(file=str(tmp), format="rdfxml")
                self._rg = Graph()
                self._rg.parse(str(tmp), format="xml")
            finally:
                tmp.unlink(missing_ok=True)
        return self._rg

    @property
    def sparql(self):
        """
        :class:`~wound_ontology.graph.sparql_helper.SPARQLHelper` wrapping
        the rdflib graph.  Cached — invalidated by ``normalize_labels()`` and
        re-populated on next access.
        """
        if self._sparql_helper is None:
            from wound_ontology.graph.sparql_helper import SPARQLHelper
            self._sparql_helper = SPARQLHelper(self.rdf_graph)
        return self._sparql_helper

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, output_file: str | Path | None = None) -> None:
        """Save the ontology as RDF/XML."""
        out = Path(output_file or _DEFAULT_OUTPUT)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._onto.save(file=str(out), format="rdfxml")
        print(f"[OWLOntology] Saved → {out}  ({out.stat().st_size:,} bytes)")

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def onto(self):
        """The owlready2 ontology object."""
        return self._onto

    @property
    def world(self):
        """The owlready2 World (needed for cross-world imports)."""
        return self._world

    # ── Shared helpers ────────────────────────────────────────────────────────

    def is_local(self, entity) -> bool:
        """True when the entity IRI does not belong to a published external ontology."""
        return not any(entity.iri.startswith(p) for p in EXTERNAL_PREFIXES)

    @staticmethod
    def safe_name(name: str) -> str:
        """Produce a valid XML/IRI local name from a human-readable label."""
        safe = name.strip().replace(" ", "_")
        safe = re.sub(r'[()"/\\:<>\'&@#%?=+,;|]', "", safe)
        safe = re.sub(r'_+', "_", safe).strip("_")
        return safe or "Unknown"

    # ── Private ───────────────────────────────────────────────────────────────

    def _next_id(self) -> str:
        id_str = f"{self._counter:07d}"
        self._counter += 1
        return id_str

    def _get_or_create_cls(self, cls_reg: dict, name: str):
        safe = self.safe_name(name)
        if safe not in cls_reg:
            with self._onto:
                cls = python_types.new_class(safe, (Thing,))
                if not cls.label:
                    cls.label = [name.strip()]
            cls_reg[safe] = cls
        return cls_reg[safe]

    def _export_hierarchy(self, cls_reg: dict, hierarchy, label: str) -> None:
        with self._onto:
            for child in hierarchy.df.index:
                for parent in hierarchy.df.columns:
                    if hierarchy.df.at[child, parent] != 1.0:
                        continue
                    if self.safe_name(child) == self.safe_name(parent):
                        self._get_or_create_cls(cls_reg, child)
                        continue
                    child_cls  = self._get_or_create_cls(cls_reg, child)
                    parent_cls = self._get_or_create_cls(cls_reg, parent)
                    if parent_cls not in child_cls.is_a:
                        try:
                            child_cls.is_a.append(parent_cls)
                            if Thing in child_cls.is_a:
                                child_cls.is_a.remove(Thing)
                        except TypeError:
                            print(f"[OWLOntology] Skipped cycle: {child} → {parent}")
        print(f"[OWLOntology] {label}: {len(hierarchy.df.index)} concepts exported.")

    def _export_mereological(self, cls_reg: dict, mere_hier) -> None:
        with self._onto:
            part_of = self._onto.search_one(iri="*part_of")
            if part_of is None:
                class part_of(ObjectProperty, TransitiveProperty):
                    namespace = self._onto
            for branch in mere_hier.df.index:
                for root in mere_hier.df.columns:
                    if mere_hier.df.at[branch, root] != 1.0:
                        continue
                    branch_cls = self._get_or_create_cls(cls_reg, branch)
                    root_cls   = self._get_or_create_cls(cls_reg, root)
                    restriction = part_of.some(root_cls)
                    if restriction not in branch_cls.is_a:
                        branch_cls.is_a.append(restriction)
        print(f"[OWLOntology] MereologicalHierarchy: {len(mere_hier.df.index)} concepts exported.")
