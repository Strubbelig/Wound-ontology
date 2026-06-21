"""OntologyCurator — curation actions on an OWLOntology."""

from __future__ import annotations

import re
import types as python_types

from owlready2 import (
    Thing, ObjectProperty, TransitiveProperty,
    AnnotationProperty, destroy_entity, locstr,
)

from .model import OWLOntology


def _name_to_label(name: str) -> str:
    label = name.replace("_", " ")
    label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label)
    label = label.strip()
    return (label[0].upper() + label[1:].lower()) if label else label


class OntologyCurator:
    """All mutation operations on an OWLOntology — modifies in place.

    Caches on the ontology are invalidated automatically after each operation.

    Usage::

        onto    = OWLOntology.load("ground_truth.owl", dm)
        curator = OntologyCurator(onto)
        curator.normalize_label_language()
        curator.rename_iris()
        onto.save(dm, "ground_truth_curated.owl")
    """

    def __init__(self, ontology: OWLOntology) -> None:
        self.ontology = ontology

    # ── Hierarchy population ──────────────────────────────────────────────────

    def from_hierarchies(
        self,
        class_hierarchy=None,
        mereological_hierarchy=None,
        fca_hierarchy=None,
    ) -> None:
        """Populate the ontology from BaseHierarchy objects (additive)."""
        cls_reg: dict[str, object] = {}
        if class_hierarchy is not None and not class_hierarchy.df.empty:
            self._export_hierarchy(cls_reg, class_hierarchy, "ClassHierarchy")
        if mereological_hierarchy is not None and not mereological_hierarchy.df.empty:
            self._export_mereological(cls_reg, mereological_hierarchy)
        if fca_hierarchy is not None and not fca_hierarchy.df.empty:
            self._export_hierarchy(cls_reg, fca_hierarchy, "FCAHierarchy")
        self.ontology._invalidate_caches()

    # ── External imports ──────────────────────────────────────────────────────

    def import_external(self, *urls: str) -> None:
        """Import ontologies by URL into the shared World."""
        onto = self.ontology.onto
        for url in urls:
            ext = self.ontology.world.get_ontology(url).load()
            if ext not in onto.imported_ontologies:
                onto.imported_ontologies.append(ext)
                print(f"[OntologyCurator] Imported: {url}")

    # ── Enrichment ────────────────────────────────────────────────────────────

    def resolve_external_classes(self) -> None:
        """Replace local classes that shadow imported external classes."""
        onto = self.ontology.onto
        label_map: dict[str, object] = {}
        for imported_onto in onto.imported_ontologies:
            for ent in imported_onto.classes():
                for lbl in ent.label:
                    label_map[str(lbl).lower().strip()] = ent
                name_key = ent.name.lower().replace("_", " ").strip()
                if name_key not in label_map:
                    label_map[name_key] = ent

        if not label_map:
            print("[OntologyCurator] No imported ontologies — skipping resolve_external_classes.")
            return

        resolved = 0
        with onto:
            for local_cls in list(onto.classes()):
                if not self.ontology.is_local(local_cls):
                    continue
                key = (
                    str(local_cls.label.first()).lower().strip()
                    if local_cls.label
                    else local_cls.name.lower().replace("_", " ").strip()
                )
                ext_cls = label_map.get(key)
                if ext_cls is None:
                    continue
                for other in list(onto.classes()):
                    if local_cls in other.is_a:
                        other.is_a.remove(local_cls)
                        if ext_cls not in other.is_a:
                            other.is_a.append(ext_cls)
                try:
                    destroy_entity(local_cls)
                    resolved += 1
                except Exception as exc:
                    print(f"[OntologyCurator] Could not destroy '{local_cls.name}': {exc}")

        self.ontology._invalidate_caches()
        print(f"[OntologyCurator] Resolved {resolved} local classes to external IRIs.")

    def normalize_label_language(
        self,
        target_lang: str = "en",
        source_lang: str | None = None,
    ) -> None:
        """Re-tag all labels to *target_lang*."""
        onto  = self.ontology.onto
        fixed = 0
        with onto:
            for ent in list(onto.classes()) + list(onto.individuals()):
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
        self.ontology._invalidate_caches()
        print(f"[OntologyCurator] normalize_label_language: {fixed} entities re-tagged → '{target_lang}'.")

    def rename_iris(self) -> None:
        """Assign WOND_NNNNNNN IRIs to all local entities."""
        onto     = self.ontology.onto
        entities = (
            list(onto.classes())
            + list(onto.object_properties())
            + list(onto.data_properties())
            + list(onto.individuals())
        )
        renamed = 0
        with onto:
            for ent in entities:
                if self.ontology.is_local(ent):
                    original_name = ent.name
                    if not ent.label:
                        ent.label = [locstr(_name_to_label(original_name), "en")]
                    new_iri = f"{self.ontology.base_iri}{self.ontology._next_id()}"
                    try:
                        ent.iri = new_iri
                        renamed += 1
                    except Exception as e:
                        print(f"[OntologyCurator] IRI rename failed for '{original_name}': {e}")
        self.ontology._invalidate_caches()
        print(f"[OntologyCurator] Renamed {renamed} local entities.")

    def umls_mapping(self, umls_connector, max_results: int = 3) -> None:
        """Annotate local classes with hasUMLSSynonym annotations."""
        onto = self.ontology.onto
        with onto:
            class hasUMLSSynonym(AnnotationProperty):
                namespace = onto

        local_classes = [c for c in onto.classes() if self.ontology.is_local(c)]
        if not local_classes:
            print("[OntologyCurator] No local classes — skipping UMLS mapping.")
            return

        mapped = 0
        print(f"[OntologyCurator] UMLS mapping for {len(local_classes)} classes...")
        for cls in local_classes:
            label = str(cls.label.first()) if cls.label else cls.name
            hits  = umls_connector.lookup(label, max_results=max_results)
            if not hits:
                continue
            with onto:
                for cui, preferred_name in hits:
                    annotation = f"{preferred_name} (UMLS:{cui})"
                    if annotation not in cls.hasUMLSSynonym:
                        cls.hasUMLSSynonym.append(annotation)
            mapped += 1
        print(f"[OntologyCurator] UMLS synonyms added to {mapped}/{len(local_classes)} classes.")

    def normalize_labels(
        self,
        strip_whitespace: bool = True,
        title_case: bool = False,
    ) -> None:
        """Normalise rdfs:label whitespace and optionally apply title case."""
        onto = self.ontology.onto
        if onto is None:
            return
        changed = 0
        with onto:
            for ent in list(onto.classes()) + list(onto.individuals()):
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
                    changed   += 1
        self.ontology._invalidate_caches()
        print(f"[OntologyCurator] normalize_labels: {changed} entities updated.")

    # ── Private — hierarchy builders ──────────────────────────────────────────

    def _get_or_create_cls(self, cls_reg: dict, name: str):
        safe = OWLOntology.safe_name(name)
        onto = self.ontology.onto
        if safe not in cls_reg:
            with onto:
                cls = python_types.new_class(safe, (Thing,))
                if not cls.label:
                    cls.label = [name.strip()]
            cls_reg[safe] = cls
        return cls_reg[safe]

    def _export_hierarchy(self, cls_reg: dict, hierarchy, label: str) -> None:
        onto = self.ontology.onto
        with onto:
            for child in hierarchy.df.index:
                for parent in hierarchy.df.columns:
                    if hierarchy.df.at[child, parent] != 1.0:
                        continue
                    if OWLOntology.safe_name(child) == OWLOntology.safe_name(parent):
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
                            print(f"[OntologyCurator] Skipped cycle: {child} → {parent}")
        print(f"[OntologyCurator] {label}: {len(hierarchy.df.index)} concepts exported.")

    def _export_mereological(self, cls_reg: dict, mere_hier) -> None:
        onto = self.ontology.onto
        with onto:
            part_of = onto.search_one(iri="*part_of")
            if part_of is None:
                class part_of(ObjectProperty, TransitiveProperty):
                    namespace = onto
            for branch in mere_hier.df.index:
                for root in mere_hier.df.columns:
                    if mere_hier.df.at[branch, root] != 1.0:
                        continue
                    branch_cls  = self._get_or_create_cls(cls_reg, branch)
                    root_cls    = self._get_or_create_cls(cls_reg, root)
                    restriction = part_of.some(root_cls)
                    if restriction not in branch_cls.is_a:
                        branch_cls.is_a.append(restriction)
        print(f"[OntologyCurator] MereologicalHierarchy: {len(mere_hier.df.index)} concepts exported.")
