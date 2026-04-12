from __future__ import annotations
from wound_ontology.hierarchies.base_hierarchy import BaseHierarchy
from wound_ontology.data_manager.data_manager import DataManager


class ClassHierarchy(BaseHierarchy):
    """
    is_a / subclass_of hierarchy.
      rows   = child concept
      cols   = parent concept
      value  = 1.0  →  child is_a parent
    """

    file_name = "class_hierarchy"

    @property
    def _direct_predicates(self):
        return {"is_a", "subclass_of"}

    @property
    def _inverse_predicates(self):
        return set()
