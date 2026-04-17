from __future__ import annotations
import types as python_types
from pathlib import Path
from owlready2 import get_ontology, Thing, ObjectProperty, TransitiveProperty
from wound_ontology.data_manager.data_manager import DataManager

_DEFAULT_OWL_OUTPUT = Path(__file__).resolve().parents[3] / "output" / "owl" / "ontology_classes.owl"


class OWLExporter:
    def __init__(
        self,
        data_manager,
        class_hierarchy=None,
        mereological_hierarchy=None,
        fca_hierarchy=None,
        iri="http://example.org/ontology",
    ):
        self.dm         = data_manager
        self.onto       = get_ontology(iri)
        self.class_hier = class_hierarchy
        self.mere_hier  = mereological_hierarchy
        self.fca_hier   = fca_hierarchy

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _safe_name(name: str) -> str:
        """Produce a valid XML/IRI local name from a human-readable label."""
        import re as _re
        safe = name.strip()
        # Replace characters that are invalid in XML names / IRIs
        safe = safe.replace(" ", "_")
        safe = _re.sub(r'[()"/\\:<>\'&@#%?=+,;|]', "", safe)
        # Collapse multiple underscores
        safe = _re.sub(r'_+', "_", safe).strip("_")
        return safe or "Unknown"

    def _get_or_create_cls(self, cls_reg: dict, name: str):
        safe = self._safe_name(name)
        if safe not in cls_reg:
            with self.onto:
                cls = python_types.new_class(safe, (Thing,))
                # Preserve the original human-readable label before owlready2
                # lowercases the class name — OWLCurator will prefer this label.
                if not cls.label:
                    cls.label = [name.strip()]
            cls_reg[safe] = cls
        return cls_reg[safe]

    def _export_hierarchy(self, cls_reg: dict, hierarchy, label: str) -> None:
        """
        Generic DataFrame hierarchy → subClassOf axioms.
        df[child, parent] == 1.0  →  child subClassOf parent
        """
        with self.onto:
            for child in hierarchy.df.index:
                for parent in hierarchy.df.columns:
                    if hierarchy.df.at[child, parent] == 1.0:
                        if self._safe_name(child) == self._safe_name(parent):
                            self._get_or_create_cls(cls_reg, child)  # entity exists as owl:Thing
                            continue
                        child_cls  = self._get_or_create_cls(cls_reg, child)
                        parent_cls = self._get_or_create_cls(cls_reg, parent)
                        if parent_cls not in child_cls.is_a:
                            try:
                                child_cls.is_a.append(parent_cls)
                                # Remove the implicit owl:Thing now that a real parent exists
                                if Thing in child_cls.is_a:
                                    child_cls.is_a.remove(Thing)
                            except TypeError:
                                # owlready2 rejects edges that would create an
                                # inheritance cycle (transitive, not just direct)
                                print(f"[OWLExporter] Skipped cycle: {child} → {parent}")
        print(f"{label} exported: {len(hierarchy.df.index)} concepts.")

    def _export_mereological_hierarchy(self, cls_reg: dict) -> None:
        """
        MereologicalHierarchy → part_of existential restrictions.
        df[branch, root] == 1.0  →  branch subClassOf (part_of some root)
        """
        with self.onto:
            part_of = self.onto.search_one(iri="*part_of")
            if part_of is None:
                class part_of(ObjectProperty, TransitiveProperty):
                    namespace = self.onto

            for branch in self.mere_hier.df.index:
                for root in self.mere_hier.df.columns:
                    if self.mere_hier.df.at[branch, root] == 1.0:
                        branch_cls = self._get_or_create_cls(cls_reg, branch)
                        root_cls   = self._get_or_create_cls(cls_reg, root)
                        restriction = part_of.some(root_cls)
                        if restriction not in branch_cls.is_a:
                            branch_cls.is_a.append(restriction)
        print(f"MereologicalHierarchy exported: {len(self.mere_hier.df.index)} concepts.")

    # ── Public API ─────────────────────────────────────────────────────────────

    def create_owl(self, output_file=_DEFAULT_OWL_OUTPUT) -> None:
        """Export all available sources to a single OWL/RDF-XML file."""
        cls_reg: dict = {}

        if self.class_hier is not None and not self.class_hier.df.empty:
            self._export_hierarchy(cls_reg, self.class_hier, "ClassHierarchy")

        if self.mere_hier is not None and not self.mere_hier.df.empty:
            self._export_mereological_hierarchy(cls_reg)

        if self.fca_hier is not None and not self.fca_hier.df.empty:
            self._export_hierarchy(cls_reg, self.fca_hier, "FCAHierarchy")

        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        self.onto.save(file=str(output_file), format="rdfxml")
        print(f"OWL saved: {output_file}")
