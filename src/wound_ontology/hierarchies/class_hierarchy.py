from __future__ import annotations
import pandas as pd
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


class ClassHierarchyView(ClassHierarchy):
    """The class hierarchy as a VIEW, not a stored artifact (2026-10-21).

    Curator: "Die Klassenhierarchie kann es weiterhin geben, aber einfach als
    view." Like the context matrix and the curation lists, it is derived from its
    sources whenever it is needed -- WONT + MILD (with the import modules' chains
    and BFO's tree), the concept store read through the mapping-and-gate
    register, the register's placements and the accepted FCA slices -- and the
    matrix CSV is neither written nor read. The sources are the state; there is
    no build step whose output a later step depends on.

    What is still persisted, and why:

    * the FCA review queue (``class_hierarchy_candidates``). It is not part of
      the hierarchy but the list of lattice proposals awaiting the head-word
      rule, and it must survive a session;
    * nothing of the edge gate's: its verdicts are is_a judgements by ``elk``
      in the term dict (rule 89), written by ``Orchestrator.run_gate_hierarchy_edges``
      and taken off every freshly built view with every other is_a ``no``, so a
      consumer in a later process (``scripts/build_wont_core.py``) sees the same
      gated view the extension was built from. Every gate run re-hears ELK's own;
    * a provenance snapshot (``class_hierarchy_provenance``) for the inspection
      pages (``scripts/hierarchy_explorer_page.py``). Written, never read back.
    """

    def __init__(self, data_manager: DataManager, file_name: str | None = None):
        self.dm = data_manager
        if file_name is not None:
            self.file_name = file_name
        self._df = pd.DataFrame(dtype=float)
        self._prov: dict[tuple[str, str], str] = {}
        # Provenance is rebuilt with the view by get_data; it can never be
        # "not loaded", so precedence is always in force.
        self._prov_loaded = True
        self._candidates: dict[tuple[str, str], str] = {}
        self._load_candidates()
        self.irreconcilable: dict[str, set[str]] = {}
        #: False until get_data has run on this instance.
        self.built = False
        #: True once the edge gate's standing verdicts are taken off.
        self.verdicts_applied = False

    def save(self) -> None:
        """Write the review queue only. The view itself is never stored."""
        self.save_candidates()

    def save_snapshot(self) -> None:
        """Provenance snapshot for the inspection pages. Never read back."""
        self.save_provenance()
