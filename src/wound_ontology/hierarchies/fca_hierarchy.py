from __future__ import annotations
from wound_ontology.hierarchies.base_hierarchy import BaseHierarchy


class FCAHierarchy(BaseHierarchy):
    """
    is_a hierarchy derived from a ConceptLattice.

    Each named lattice concept becomes a node; upper-neighbor edges
    in the lattice become subClassOf (child is_a parent) edges here.

    Populated via build_from_lattice() — not from the ExtractionCache.
    """

    file_name = "fca_hierarchy"

    @property
    def _direct_predicates(self):
        return {"is_a"}

    @property
    def _inverse_predicates(self):
        return set()

    def get_data(self, lattice) -> None:
        """
        Populate this hierarchy from a named ConceptLattice.

        For each lattice concept with a name, its upper neighbors
        (more general concepts) become its parents in the hierarchy.
        Unnamed concepts (no .name or name not a plain string) are skipped.
        """
        added = 0
        for concept in lattice:
            child_name = getattr(concept, 'name', None)
            if not isinstance(child_name, str) or not child_name:
                continue
            for upper in concept.upper_neighbors:
                parent_name = getattr(upper, 'name', None)
                if not isinstance(parent_name, str) or not parent_name:
                    continue
                self._set_edge(child_name, parent_name)
                added += 1
        print(f"[FCAHierarchy] {added} edges added from lattice.")
