from __future__ import annotations
from wound_ontology.hierarchies.base_hierarchy import BaseHierarchy
from wound_ontology.data_manager.data_manager import DataManager


class MereologicalHierarchy(BaseHierarchy):
    """
    part_of hierarchy.
      rows   = branch (more specific / part)
      cols   = root   (more general / whole)
      value  = 1.0  →  branch part_of root
    """

    file_name = "mereological_hierarchy"

    @property
    def _direct_predicates(self):
        return {"part_of"}

    @property
    def _inverse_predicates(self):
        return set()
