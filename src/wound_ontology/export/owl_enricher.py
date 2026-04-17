from __future__ import annotations
import re
from pathlib import Path
from owlready2 import World, sync_reasoner, destroy_entity, AnnotationProperty

try:
    from config.settings import (
        ONTOLOGY_BASE_IRI, ONTOLOGY_ID_PREFIX, ONTOLOGY_ID_START,
        BFO_OWL_URL as _BFO_URL, RO_OWL_URL as _RO_URL, OBI_OWL_URL as _OBI_URL,
    )
except ImportError:
    ONTOLOGY_BASE_IRI  = "http://purl.obolibrary.org/obo/WOND_"
    ONTOLOGY_ID_PREFIX = "WOND"
    ONTOLOGY_ID_START  = 1
    _BFO_URL = "http://purl.obolibrary.org/obo/bfo.owl"
    _RO_URL  = "http://purl.obolibrary.org/obo/ro.owl"
    _OBI_URL = "http://purl.obolibrary.org/obo/obi.owl"

# OBO IRIs that must never be renamed — they belong to published ontologies
_EXTERNAL_PREFIXES = (
    "http://purl.obolibrary.org/obo/",
    "http://www.w3.org/",
    "http://www.geneontology.org/",
    "http://purl.org/dc/",
    "https://purl.bioontology.org/",
)


def _name_to_label(name: str) -> str:
    """Convert underscore or CamelCase entity name to a human-readable label."""
    label = name.replace("_", " ")
    label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label)
    label = label.strip()
    return (label[0].upper() + label[1:].lower()) if label else label


class OWLEnricher:
    """
    Post-processes the OWL file produced by OWLExporter:

      1. Load the generated OWL into a fresh owlready2 World
      2. Optionally import BFO, RO, OBI (or any custom URL)
      3. Rename local IRIs to proper ontology IRIs  (e.g. WOND_0000001)
         and assign rdfs:label from the original class name
      4. Optionally run the Pellet/HermiT reasoner (requires Java)
      5. Save the enriched OWL

    Usage — fluent API:
        OWLEnricher(base_iri="http://purl.obolibrary.org/obo/WOND_")
            .load("output/ontology.owl")
            .import_bfo()
            .import_ro()
            .rename_iris()
            .save("output/wound_ontology.owl")

    Or as a one-shot call via the orchestrator:
        pipeline.run_enrich_owl(input_file=..., output_file=...)
    """

    def __init__(
        self,
        base_iri: str = ONTOLOGY_BASE_IRI,
        id_prefix: str = ONTOLOGY_ID_PREFIX,
        id_start: int = ONTOLOGY_ID_START,
    ):
        self.base_iri  = base_iri
        self.id_prefix = id_prefix
        self._counter  = id_start
        self._world    = None
        self._onto     = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def load(self, owl_file: str) -> "OWLEnricher":
        """Load an OWL/RDF-XML file into a fresh owlready2 World."""
        path = Path(owl_file).resolve()
        self._world = World()
        self._onto  = self._world.get_ontology(f"file://{path}").load()
        print(f"[OWLEnricher] Loaded: {path}")
        return self

    # ── External imports ───────────────────────────────────────────────────────

    def import_connector(self, *connectors) -> "OWLEnricher":
        """
        Import ontologies already loaded by OntoConnector instances (BFO, RO, OBI…).
        Reuses the connector's loaded owlready2 ontology object — no second download.
        """
        for connector in connectors:
            if connector.onto is None:
                print(f"[OWLEnricher] {connector.source_name} not loaded — skipping.")
                continue
            # Adopt the connector's ontology into our world, then import it
            ext = self._world.get_ontology(connector.onto_url).load()
            if ext not in self._onto.imported_ontologies:
                self._onto.imported_ontologies.append(ext)
                print(f"[OWLEnricher] Imported via connector: {connector.source_name}")
        return self

    def import_external(self, *urls: str) -> "OWLEnricher":
        """Append one or more external ontology imports by URL (fallback without connectors)."""
        for url in urls:
            ext = self._world.get_ontology(url).load()
            if ext not in self._onto.imported_ontologies:
                self._onto.imported_ontologies.append(ext)
                print(f"[OWLEnricher] Imported: {url}")
        return self

    def import_bfo(self) -> "OWLEnricher":
        return self.import_external(_BFO_URL)

    def import_ro(self) -> "OWLEnricher":
        return self.import_external(_RO_URL)

    def import_obi(self) -> "OWLEnricher":
        return self.import_external(_OBI_URL)

    # ── External class resolution ──────────────────────────────────────────────

    def resolve_external_classes(self) -> "OWLEnricher":
        """
        Replace local classes that shadow an already-imported external class
        (BFO, RO, OBI…) with the real external class.

        For each local class whose rdfs:label (or formatted name) matches a
        class in any imported ontology:
          1. All subClassOf edges pointing to the local class are rewired to
             the matching external class.
          2. The redundant local class is destroyed.

        Call this AFTER import_connector() / import_external() and BEFORE
        rename_iris() so shadowed concepts never receive a WOND_ IRI.
        """
        # Build label → external class from all imported ontologies
        label_map: dict[str, object] = {}
        for imported_onto in self._onto.imported_ontologies:
            for cls in imported_onto.classes():
                for lbl in cls.label:
                    label_map[str(lbl).lower().strip()] = cls
                # Also index by formatted class name as fallback
                name_key = cls.name.lower().replace("_", " ").strip()
                if name_key not in label_map:
                    label_map[name_key] = cls

        if not label_map:
            print("[OWLEnricher] No imported ontologies to resolve against — skipping.")
            return self

        resolved = 0
        with self._onto:
            for local_cls in list(self._onto.classes()):
                if not self._is_local(local_cls):
                    continue
                # Determine lookup key from existing label or formatted name
                if local_cls.label:
                    key = str(local_cls.label.first()).lower().strip()
                else:
                    key = local_cls.name.lower().replace("_", " ").strip()

                ext_cls = label_map.get(key)
                if ext_cls is None:
                    continue

                # Rewire all local subClasses that list local_cls as a parent
                for other in list(self._onto.classes()):
                    if local_cls in other.is_a:
                        other.is_a.remove(local_cls)
                        if ext_cls not in other.is_a:
                            other.is_a.append(ext_cls)

                try:
                    destroy_entity(local_cls)
                    resolved += 1
                except Exception as exc:
                    print(f"[OWLEnricher] Could not destroy '{local_cls.name}': {exc}")

        print(f"[OWLEnricher] Resolved {resolved} local classes to external IRIs.")
        return self

    # ── IRI renaming + labeling ────────────────────────────────────────────────

    def rename_iris(self) -> "OWLEnricher":
        """
        Assign proper ontology IRIs to all local classes, object properties,
        data properties, and individuals.

        For each entity:
          - rdfs:label is set from the original class name (before renaming)
          - IRI is replaced with <base_iri><PREFIX_NNNNNNN>

        Entities whose IRIs start with a known external prefix (OBO, W3C, …)
        are left untouched.
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
                if self._is_local(entity):
                    original_name = entity.name
                    # Assign human-readable label before IRI changes the name
                    if not entity.label:
                        entity.label = [_name_to_label(original_name)]
                    new_id  = self._next_id()
                    new_iri = f"{self.base_iri}{new_id}"
                    try:
                        entity.iri = new_iri
                        renamed += 1
                    except Exception as e:
                        print(f"[OWLEnricher] IRI rename failed for '{original_name}': {e}")
        print(f"[OWLEnricher] Renamed {renamed} local entities.")
        return self

    # ── UMLS mapping ──────────────────────────────────────────────────────────

    def umls_mapping(self, umls_connector, max_results: int = 3) -> "OWLEnricher":
        """
        For each local WOND class, search UMLS for matching concepts and annotate
        the class with hasUMLSSynonym (CUI + preferred name).

        WOND classes are NOT replaced — the annotation is additive only.
        Call this AFTER rename_iris() so labels are already set.

        umls_connector – a connected UMLSConnector instance.
        max_results    – max UMLS hits per class (default 3).
        """
        with self._onto:
            # Declare annotation property once in this ontology
            class hasUMLSSynonym(AnnotationProperty):
                namespace = self._onto

        local_classes = [c for c in self._onto.classes() if self._is_local(c)]
        if not local_classes:
            print("[OWLEnricher] No local classes to map — skipping UMLS mapping.")
            return self

        mapped = 0
        print(f"[OWLEnricher] UMLS mapping for {len(local_classes)} classes...")
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

        print(f"[OWLEnricher] UMLS synonyms added to {mapped}/{len(local_classes)} classes.")
        return self

    # ── Reasoning ─────────────────────────────────────────────────────────────

    def run_reasoner(self, infer_property_values: bool = True) -> "OWLEnricher":
        """
        Run the Pellet/HermiT reasoner to infer new axioms.
        Requires Java and JPype to be installed.
        """
        with self._onto:
            sync_reasoner(infer_property_values=infer_property_values)
        print("[OWLEnricher] Reasoning complete.")
        return self

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, output_file: str) -> None:
        """Save the enriched ontology as RDF/XML."""
        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._onto.save(file=str(out), format="rdfxml")
        print(f"[OWLEnricher] Saved → {out}  ({out.stat().st_size:,} bytes)")

    # ── Convenience ───────────────────────────────────────────────────────────

    def enrich(
        self,
        input_file: str,
        output_file: str,
        import_bfo: bool = True,
        import_ro: bool = True,
        import_obi: bool = False,
        run_reasoner: bool = False,
    ) -> None:
        """One-shot enrichment: load → import → rename → (reason) → save."""
        self.load(input_file)
        if import_bfo:
            self.import_bfo()
        if import_ro:
            self.import_ro()
        if import_obi:
            self.import_obi()
        self.resolve_external_classes()
        self.rename_iris()
        if run_reasoner:
            self.run_reasoner()
        self.save(output_file)

    # ── Private ───────────────────────────────────────────────────────────────

    def _next_id(self) -> str:
        id_str = f"{self._counter:07d}"
        self._counter += 1
        return id_str

    def _is_local(self, entity) -> bool:
        """True when the entity IRI does not belong to a published external ontology."""
        return not any(entity.iri.startswith(p) for p in _EXTERNAL_PREFIXES)
