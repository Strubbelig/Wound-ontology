from __future__ import annotations
import re
import tempfile
import types as python_types
from pathlib import Path

from rdflib import Graph, URIRef
from owlready2 import (
    World, Thing, ObjectProperty, TransitiveProperty,
    AnnotationProperty, destroy_entity, locstr,
    Restriction, Or, SOME,
)

try:
    from config.settings import (
        OWL_OUTPUT_FILE as _DEFAULT_OUTPUT,
        ONTOLOGY_BASE_IRI, ONTOLOGY_ID_PREFIX, ONTOLOGY_ID_START,
        BFO_OWL_URL as _BFO_URL, RO_OWL_URL as _RO_URL, OBI_OWL_URL as _OBI_URL,
    )
except ImportError:
    _DEFAULT_OUTPUT   = Path(__file__).resolve().parents[3] / "output" / "owl" / "ontology_classes.owl"
    ONTOLOGY_BASE_IRI = "http://purl.obolibrary.org/obo/WOND_"
    ONTOLOGY_ID_PREFIX = "WOND"
    ONTOLOGY_ID_START  = 1
    _BFO_URL = "http://purl.obolibrary.org/obo/bfo.owl"
    _RO_URL  = "http://purl.obolibrary.org/obo/ro.owl"
    _OBI_URL = "http://purl.obolibrary.org/obo/obi.owl"

EXTERNAL_PREFIXES: tuple[str, ...] = (
    "http://purl.obolibrary.org/obo/",
    "http://www.w3.org/",
    "http://www.geneontology.org/",
    "http://purl.org/dc/",
    "https://purl.bioontology.org/",
)


def _name_to_label(name: str) -> str:
    label = name.replace("_", " ")
    label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label)
    label = label.strip()
    return (label[0].upper() + label[1:].lower()) if label else label


class TBox:
    """
    OWL TBox backed exclusively by owlready2.

    Construction
    ------------
    TBox()                        — empty ontology
    TBox("path/to/file.owl")      — load from file
    TBox("http://…/bfo.owl")      — load from URL
    TBox(source, world=my_world)  — share an existing owlready2 World

    Multiple TBoxes that need to share imports (BFO, RO …) should all
    receive the same World instance:

        world  = World()
        tbox   = TBox("tbox.owl",  world=world)
        bfo    = TBox(_BFO_URL,    world=world)
        tbox.import_bfo()          # resolves inside the shared world

    Labels (owlready2-only, no SPARQL)
    ------------------------------------
        bfo = TBox("http://purl.obolibrary.org/obo/bfo.owl")
        bfo.labels                 # {"material entity": "http://…", …}
        bfo.label_of("http://…")   # "material entity"

    Variant generation (classmethod, returns modified TBox)
    -------------------------------------------------------
        tbox_v = TBox.generate_variants(
            TBox("tbox.owl", world=world),
            fma_onto   = TBox("fma.owl", world=world),
            has_part   = world.search_one(iri=HAS_PART_IRI),
            origin_root = world.search_one(iri=ORIGIN_ROOT_IRI),
            iri_ns     = "https://purl.bioontology.org/ontology/OFL/OFLID",
        )
        tbox_v.save("tbox_variants.owl")
    """

    def __init__(
        self,
        source:    str | None = None,
        world:     World | None = None,
        iri:       str = "http://example.org/ontology",
        base_iri:  str = ONTOLOGY_BASE_IRI,
        id_prefix: str = ONTOLOGY_ID_PREFIX,
        id_start:  int = ONTOLOGY_ID_START,
    ):
        self._world    = world if world is not None else World()
        self._iri      = iri
        self.base_iri  = base_iri
        self.id_prefix = id_prefix
        self._counter  = id_start
        self._onto     = self._world.get_ontology(iri)
        self._rg: Graph | None = None          # lazy rdflib bridge for ABox
        self._labels_cache: dict[str, str] | None = None

        if source is not None:
            self.load(source)

    # ── Classmethods ──────────────────────────────────────────────────────────

    @classmethod
    def from_hierarchies(
        cls,
        class_hierarchy=None,
        mereological_hierarchy=None,
        fca_hierarchy=None,
        world: World | None = None,
        **kwargs,
    ) -> "TBox":
        """Build a TBox from BaseHierarchy objects and return it."""
        tbox = cls(world=world, **kwargs)
        tbox.get_data(class_hierarchy, mereological_hierarchy, fca_hierarchy)
        return tbox

    @classmethod
    def generate_variants(
        cls,
        tbox: "TBox",
        fma_onto: "TBox | None" = None,
        has_part=None,
        origin_root=None,
        iri_ns: str = "",
    ) -> "TBox":
        """
        Create named variant subclasses from ``hasPart some (A ⊔ B ⊔ …)``
        union restrictions.  Operates entirely via owlready2 — no SPARQL.

        For every class C with ``∃has_part.(A ⊔ B ⊔ …)``, creates:
            C_with_A  ≡  C ⊓ ∃has_part.A
            C_with_B  ≡  C ⊓ ∃has_part.B
            …
        and removes the union restriction from C.

        Parameters
        ----------
        tbox : TBox
            The loaded TBox to extend in place.
        fma_onto : TBox, optional
            Loaded FMA TBox for resolving component labels.  Should share
            the same World as *tbox* for reliable entity identity.
        has_part : owlready2 ObjectProperty
            The hasPart property object (retrieved from the shared world).
        origin_root : owlready2 Class, optional
            If given, only classes that are (transitive) subclasses of this
            class are considered.  Prevents expanding classification axes.
        iri_ns : str
            IRI prefix used to mint new variant IRIs, e.g.
            ``"https://purl.bioontology.org/ontology/OFL/OFLID"``.
            New IRIs will be ``iri_ns + f"{n:07d}"``.

        Returns
        -------
        TBox
            The same *tbox* instance, modified in place.
        """
        if has_part is None:
            raise ValueError("has_part (owlready2 property) must be provided")

        # Collect candidate classes (optionally restricted to origin_root subtree)
        if origin_root is not None:
            candidates = cls._subclasses_of(origin_root)
        else:
            candidates = list(tbox._onto.classes())

        id_counter = [cls._find_max_id_onto(tbox._onto) + 1]

        def new_iri() -> str:
            iri = f"{iri_ns}{id_counter[0]:07d}"
            id_counter[0] += 1
            return iri

        created = 0
        with tbox._onto:
            for parent_cls in candidates:
                to_remove = []
                for restr in list(parent_cls.is_a):
                    if not isinstance(restr, Restriction):
                        continue
                    if restr.property != has_part:
                        continue
                    if restr.type != SOME:
                        continue
                    if not isinstance(restr.value, Or):
                        continue

                    parent_label = (
                        str(parent_cls.label[0]) if parent_cls.label else parent_cls.name
                    )
                    flap_base = re.sub(
                        r"\s+flap$", "", parent_label, flags=re.IGNORECASE
                    ).strip().lower()

                    for comp_cls in restr.value.Classes:
                        comp_label = cls._owlready2_label(comp_cls, fma_onto)
                        if comp_label.lower() == flap_base:
                            continue

                        variant_label = cls._make_variant_label(parent_label, comp_label)
                        safe          = TBox.safe_name(variant_label)
                        variant_cls   = python_types.new_class(safe, (Thing,))
                        variant_cls.iri   = new_iri()
                        variant_cls.label = [locstr(variant_label, "en")]
                        # Defined class: C ≡ parent ⊓ ∃has_part.component
                        variant_cls.equivalent_to = [parent_cls & has_part.some(comp_cls)]
                        if parent_cls not in variant_cls.is_a:
                            variant_cls.is_a.append(parent_cls)
                        created += 1

                    to_remove.append(restr)

                for restr in to_remove:
                    parent_cls.is_a.remove(restr)

        tbox._rg = None               # invalidate rdflib bridge cache
        tbox._labels_cache = None
        print(f"[TBox.generate_variants] Created {created} variant subclasses.")
        return tbox

    # ── Loading ────────────────────────────────────────────────────────────────

    def load(self, source: str) -> "TBox":
        """
        Load an OWL file or URL into this TBox.
        Uses the World supplied at construction — never replaces it.
        """
        is_url = source.startswith(("http://", "https://", "file://"))
        uri    = source if is_url else Path(source).resolve().as_uri()
        try:
            self._onto = self._world.get_ontology(uri).load()
        except Exception as exc:
            print(f"[TBox] owlready2 warning ({exc.__class__.__name__}) — partial load")
            self._onto = self._world.get_ontology(uri)
        self._rg           = None
        self._labels_cache = None
        print(f"[TBox] Loaded: {source}")
        return self

    # ── Build from hierarchies ─────────────────────────────────────────────────

    def get_data(
        self,
        class_hierarchy=None,
        mereological_hierarchy=None,
        fca_hierarchy=None,
    ) -> "TBox":
        """Populate from BaseHierarchy objects (idempotent — additive)."""
        cls_reg: dict[str, object] = {}
        if class_hierarchy is not None and not class_hierarchy.df.empty:
            self._export_hierarchy(cls_reg, class_hierarchy, "ClassHierarchy")
        if mereological_hierarchy is not None and not mereological_hierarchy.df.empty:
            self._export_mereological(cls_reg, mereological_hierarchy)
        if fca_hierarchy is not None and not fca_hierarchy.df.empty:
            self._export_hierarchy(cls_reg, fca_hierarchy, "FCAHierarchy")
        return self

    # ── Labels (owlready2-only, no SPARQL) ────────────────────────────────────

    @property
    def labels(self) -> dict[str, str]:
        """
        ``{label_lowercase: iri}`` for all classes and object properties.

        Covers the loaded ontology only (not imported ones).
        Cached; invalidated by load() and normalize_labels().

            bfo = TBox("http://purl.obolibrary.org/obo/bfo.owl")
            bfo.labels["material entity"]
        """
        if self._labels_cache is None:
            result: dict[str, str] = {}
            for ent in self._onto.classes():
                lbl = ent.label[0] if ent.label else ent.name
                result[str(lbl).lower()] = ent.iri
            for prop in self._onto.object_properties():
                lbl = prop.label[0] if prop.label else prop.name
                result[str(lbl).lower().replace(" ", "_")] = prop.iri
            self._labels_cache = result
        return self._labels_cache

    def label_of(self, iri: str | URIRef, lang: str = "en") -> str | None:
        """Return rdfs:label for *iri* using owlready2 world lookup."""
        entity = self._world.search_one(iri=str(iri))
        if entity is None:
            return None
        for lbl in entity.label:
            if getattr(lbl, "lang", None) == lang:
                return str(lbl)
        return str(entity.label[0]) if entity.label else None

    def iri_of_label(self, label: str, lang: str | None = None) -> str | None:
        """Return first IRI whose rdfs:label matches *label* (case-insensitive)."""
        target = label.lower().strip()
        for ent in list(self._onto.classes()) + list(self._onto.object_properties()):
            for lbl in ent.label:
                if lang is not None and getattr(lbl, "lang", None) != lang:
                    continue
                if str(lbl).lower().strip() == target:
                    return ent.iri
        return None

    # ── External imports (no connectors) ──────────────────────────────────────

    def import_external(self, *urls: str) -> "TBox":
        """Import ontologies by URL into the shared World."""
        for url in urls:
            ext = self._world.get_ontology(url).load()
            if ext not in self._onto.imported_ontologies:
                self._onto.imported_ontologies.append(ext)
                print(f"[TBox] Imported: {url}")
        return self

    def import_bfo(self) -> "TBox":
        return self.import_external(_BFO_URL)

    def import_ro(self) -> "TBox":
        return self.import_external(_RO_URL)

    def import_obi(self) -> "TBox":
        return self.import_external(_OBI_URL)

    # ── In-place enrichment ───────────────────────────────────────────────────

    def resolve_external_classes(self) -> "TBox":
        """
        Replace local classes that shadow imported external classes.
        Call after import_*() and before rename_iris().
        """
        label_map: dict[str, object] = {}
        for imported_onto in self._onto.imported_ontologies:
            for ent in imported_onto.classes():
                for lbl in ent.label:
                    label_map[str(lbl).lower().strip()] = ent
                name_key = ent.name.lower().replace("_", " ").strip()
                if name_key not in label_map:
                    label_map[name_key] = ent

        if not label_map:
            print("[TBox] No imported ontologies to resolve against — skipping.")
            return self

        resolved = 0
        with self._onto:
            for local_cls in list(self._onto.classes()):
                if not self.is_local(local_cls):
                    continue
                key = (
                    str(local_cls.label.first()).lower().strip()
                    if local_cls.label
                    else local_cls.name.lower().replace("_", " ").strip()
                )
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
                    print(f"[TBox] Could not destroy '{local_cls.name}': {exc}")

        self._labels_cache = None
        print(f"[TBox] Resolved {resolved} local classes to external IRIs.")
        return self

    def normalize_label_language(
        self,
        target_lang: str = "en",
        source_lang: str | None = None,
    ) -> "TBox":
        fixed = 0
        with self._onto:
            for ent in list(self._onto.classes()) + list(self._onto.individuals()):
                new_labels, changed = [], False
                for lbl in list(ent.label):
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
                    ent.label = new_labels
                    fixed += 1
        self._labels_cache = None
        print(f"[TBox] normalize_label_language: {fixed} entities re-tagged → '{target_lang}'.")
        return self

    def rename_iris(self) -> "TBox":
        """Assign WOND_NNNNNNN IRIs to all local entities."""
        entities = (
            list(self._onto.classes())
            + list(self._onto.object_properties())
            + list(self._onto.data_properties())
            + list(self._onto.individuals())
        )
        renamed = 0
        with self._onto:
            for ent in entities:
                if self.is_local(ent):
                    original_name = ent.name
                    if not ent.label:
                        ent.label = [locstr(_name_to_label(original_name), "en")]
                    new_iri = f"{self.base_iri}{self._next_id()}"
                    try:
                        ent.iri = new_iri
                        renamed += 1
                    except Exception as e:
                        print(f"[TBox] IRI rename failed for '{original_name}': {e}")
        self._rg = None
        self._labels_cache = None
        print(f"[TBox] Renamed {renamed} local entities.")
        return self

    def umls_mapping(self, umls_connector, max_results: int = 3) -> "TBox":
        """Annotate local classes with hasUMLSSynonym annotations."""
        with self._onto:
            class hasUMLSSynonym(AnnotationProperty):
                namespace = self._onto

        local_classes = [c for c in self._onto.classes() if self.is_local(c)]
        if not local_classes:
            print("[TBox] No local classes to map — skipping UMLS mapping.")
            return self

        mapped = 0
        print(f"[TBox] UMLS mapping for {len(local_classes)} classes...")
        for cls in local_classes:
            label = str(cls.label.first()) if cls.label else cls.name
            hits  = umls_connector.lookup(label, max_results=max_results)
            if not hits:
                continue
            with self._onto:
                for cui, preferred_name in hits:
                    annotation = f"{preferred_name} (UMLS:{cui})"
                    if annotation not in cls.hasUMLSSynonym:
                        cls.hasUMLSSynonym.append(annotation)
            mapped += 1
        print(f"[TBox] UMLS synonyms added to {mapped}/{len(local_classes)} classes.")
        return self

    def normalize_labels(
        self,
        strip_whitespace: bool = True,
        title_case: bool = False,
    ) -> "TBox":
        if self._onto is None:
            return self
        changed = 0
        with self._onto:
            for ent in list(self._onto.classes()) + list(self._onto.individuals()):
                new_labels, was_changed = [], False
                for lbl in list(ent.label):
                    s    = str(lbl)
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
                    ent.label = new_labels
                    changed += 1
        self._rg           = None
        self._labels_cache = None
        print(f"[TBox] normalize_labels: {changed} entities updated.")
        return self

    # ── rdflib bridge (output for ABox — TBox itself never queries this) ───────

    @property
    def rdf_graph(self) -> Graph:
        """
        Lazily serialize the owlready2 ontology to an rdflib Graph.
        Intended for ABox consumption (SPARQL, graph ops) — TBox never reads it.
        Cache is invalidated whenever owlready2 state changes.
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

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, output_file: str | Path | None = None) -> None:
        """Save as RDF/XML using owlready2."""
        out = Path(output_file or _DEFAULT_OUTPUT)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._onto.save(file=str(out), format="rdfxml")
        print(f"[TBox] Saved → {out}  ({out.stat().st_size:,} bytes)")

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def onto(self):
        """The owlready2 ontology object."""
        return self._onto

    @property
    def world(self):
        """The owlready2 World (shared across TBox instances)."""
        return self._world

    # ── Helpers ───────────────────────────────────────────────────────────────

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

    # ── Private — ID counter ──────────────────────────────────────────────────

    def _next_id(self) -> str:
        id_str = f"{self._counter:07d}"
        self._counter += 1
        return id_str

    # ── Private — hierarchy builders ──────────────────────────────────────────

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
                            print(f"[TBox] Skipped cycle: {child} → {parent}")
        print(f"[TBox] {label}: {len(hierarchy.df.index)} concepts exported.")

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
        print(f"[TBox] MereologicalHierarchy: {len(mere_hier.df.index)} concepts exported.")

    # ── Private — generate_variants helpers ───────────────────────────────────

    @staticmethod
    def _subclasses_of(root_cls) -> list:
        """Collect all transitive subclasses of *root_cls* via owlready2."""
        visited: set = set()
        queue = list(root_cls.subclasses())
        while queue:
            cls = queue.pop()
            if cls not in visited:
                visited.add(cls)
                queue.extend(cls.subclasses())
        return list(visited)

    @staticmethod
    def _find_max_id_onto(onto) -> int:
        """Find the highest OFLID integer across all classes in *onto*."""
        max_id = 1_000_200
        for ent in onto.classes():
            m = re.search(r"OFLID(\d+)", ent.iri)
            if m:
                max_id = max(max_id, int(m.group(1)))
        return max_id

    @staticmethod
    def _owlready2_label(entity, fma_onto: "TBox | None" = None) -> str:
        """Return a human-readable label for an owlready2 entity."""
        if entity.label:
            return str(entity.label[0])
        if fma_onto is not None:
            other = fma_onto._world.search_one(iri=entity.iri)
            if other and other.label:
                return str(other.label[0])
        return entity.name.replace("_", " ")

    @staticmethod
    def _make_variant_label(parent_label: str, component_label: str) -> str:
        base = re.sub(r"\s+flap$", "", parent_label, flags=re.IGNORECASE).strip()
        return f"{base} flap with {component_label.lower()}"
