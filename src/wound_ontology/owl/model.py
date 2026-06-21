"""OWLOntology — domain model wrapping an owlready2 ontology + world."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rdflib import Graph, URIRef

if TYPE_CHECKING:
    from wound_ontology.data_manager.data_manager import DataManager

try:
    from config.settings import (
        ONTOLOGY_BASE_IRI,
        ONTOLOGY_ID_PREFIX,
        ONTOLOGY_ID_START,
    )
except ImportError:
    ONTOLOGY_BASE_IRI  = "http://purl.obolibrary.org/obo/WOND_"
    ONTOLOGY_ID_PREFIX = "WOND"
    ONTOLOGY_ID_START  = 1

EXTERNAL_PREFIXES: tuple[str, ...] = (
    "http://purl.obolibrary.org/obo/",
    "http://www.w3.org/",
    "http://www.geneontology.org/",
    "http://purl.org/dc/",
    "https://purl.bioontology.org/",
)


class OWLOntology:
    """Thin wrapper around an owlready2 ontology + world providing read-only access.

    The mutable state (labels cache, rdflib bridge) is managed here, but all
    write operations live in OntologyCurator.  Lifecycle: OWLOntology.create()
    for a fresh empty ontology, OWLOntology.load(source, dm) to load from a
    file/URL, onto.save(dm, path) to persist.
    """

    def __init__(
        self,
        onto:      Any,
        world:     Any,
        base_iri:  str = ONTOLOGY_BASE_IRI,
        id_prefix: str = ONTOLOGY_ID_PREFIX,
        id_start:  int = ONTOLOGY_ID_START,
    ) -> None:
        self.onto       = onto
        self.world      = world
        self.base_iri   = base_iri
        self.id_prefix  = id_prefix
        self._counter   = id_start
        self._labels_cache: dict[str, str] | None = None
        self._rdf_graph: Graph | None = None

    # ── Read-only label access ─────────────────────────────────────────────────

    @property
    def labels(self) -> dict[str, str]:
        """``{label_lowercase: iri}`` for all classes and object properties."""
        if self._labels_cache is None:
            result: dict[str, str] = {}
            for ent in self.onto.classes():
                lbl = ent.label[0] if ent.label else ent.name
                result[str(lbl).lower()] = ent.iri
            for prop in self.onto.object_properties():
                lbl = prop.label[0] if prop.label else prop.name
                result[str(lbl).lower().replace(" ", "_")] = prop.iri
            self._labels_cache = result
        return self._labels_cache

    def label_of(self, iri: str | URIRef, lang: str = "en") -> str | None:
        """Return rdfs:label for *iri* using owlready2 world lookup."""
        entity = self.world.search_one(iri=str(iri))
        if entity is None:
            return None
        for lbl in entity.label:
            if getattr(lbl, "lang", None) == lang:
                return str(lbl)
        return str(entity.label[0]) if entity.label else None

    def iri_of_label(self, label: str, lang: str | None = None) -> str | None:
        """Return first IRI whose rdfs:label matches *label* (case-insensitive)."""
        target = label.lower().strip()
        for ent in list(self.onto.classes()) + list(self.onto.object_properties()):
            for lbl in ent.label:
                if lang is not None and getattr(lbl, "lang", None) != lang:
                    continue
                if str(lbl).lower().strip() == target:
                    return ent.iri
        return None

    def is_local(self, entity) -> bool:
        """True when the entity IRI is not from a published external ontology."""
        return not any(entity.iri.startswith(p) for p in EXTERNAL_PREFIXES)

    @staticmethod
    def safe_name(name: str) -> str:
        """Produce a valid XML/IRI local name from a human-readable label."""
        safe = name.strip().replace(" ", "_")
        safe = re.sub(r'[()"/\\:<>\'&@#%?=+,;|]', "", safe)
        safe = re.sub(r"_+", "_", safe).strip("_")
        return safe or "Unknown"

    # ── rdflib bridge (lazy, invalidated by curator when ontology changes) ──────

    @property
    def rdf_graph(self) -> Graph:
        """Lazily serialise the owlready2 ontology to an rdflib Graph."""
        if self._rdf_graph is None:
            tmp = Path(tempfile.mkstemp(suffix=".owl")[1])
            try:
                self.onto.save(file=str(tmp), format="rdfxml")
                self._rdf_graph = Graph()
                self._rdf_graph.parse(str(tmp), format="xml")
            finally:
                tmp.unlink(missing_ok=True)
        return self._rdf_graph

    # ── Factory + Persistence ─────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        iri:       str = "http://example.org/ontology",
        base_iri:  str = ONTOLOGY_BASE_IRI,
        id_prefix: str = ONTOLOGY_ID_PREFIX,
        id_start:  int = ONTOLOGY_ID_START,
        world:     Any = None,
    ) -> "OWLOntology":
        """Return an empty OWLOntology backed by a fresh owlready2 World."""
        from owlready2 import World
        w = world if world is not None else World()
        return cls(onto=w.get_ontology(iri), world=w,
                   base_iri=base_iri, id_prefix=id_prefix, id_start=id_start)

    @classmethod
    def load(
        cls,
        source: str,
        dm: "DataManager",
        world=None,
        base_iri: str | None = None,
        id_prefix: str | None = None,
        id_start: int | None = None,
        iri: str = "http://example.org/ontology",
    ) -> "OWLOntology":
        """Load an OWL file or URL via DataManager."""
        return dm.load_owl(
            source, world=world, base_iri=base_iri,
            id_prefix=id_prefix, id_start=id_start, iri=iri,
        )

    def save(self, dm: "DataManager", output_file: str | Path | None = None) -> str:
        """Save to RDF/XML via DataManager. Returns the path written."""
        return dm.save_owl(self, output_file)

    # ── Internal (used by OntologyCurator) ────────────────────────────────────

    def _next_id(self) -> str:
        id_str = f"{self._counter:07d}"
        self._counter += 1
        return id_str

    def _invalidate_caches(self) -> None:
        self._labels_cache = None
        self._rdf_graph    = None
