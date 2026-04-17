from __future__ import annotations
from pathlib import Path
from owlready2 import World, sync_reasoner


class OWLReasoner:
    """
    Runs the Pellet/HermiT reasoner over an OWL file and saves the result.

    Requires Java and JPype to be installed.

    Usage — fluent API:
        OWLReasoner()
            .load("output/ontology.owl")
            .run()
            .save("output/ontology_inferred.owl")

    Or one-shot:
        OWLReasoner().reason("output/ontology.owl", "output/ontology_inferred.owl")

    Or via the orchestrator:
        pipeline.run_reason_owl(input_file=..., output_file=...)
    """

    def __init__(self):
        self._world = None
        self._onto  = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def load(self, owl_file: str) -> "OWLReasoner":
        """Load an OWL/RDF-XML file into a fresh owlready2 World."""
        path = Path(owl_file).resolve()
        self._world = World()
        self._onto  = self._world.get_ontology(f"file://{path}").load()
        print(f"[OWLReasoner] Loaded: {path}")
        return self

    # ── Reasoning ─────────────────────────────────────────────────────────────

    def run(self, infer_property_values: bool = True) -> "OWLReasoner":
        """
        Run the Pellet/HermiT reasoner to materialise inferred axioms.
        Must call load() first.
        """
        if self._onto is None:
            raise RuntimeError("No ontology loaded — call load() first.")
        with self._onto:
            sync_reasoner(infer_property_values=infer_property_values)
        print("[OWLReasoner] Reasoning complete.")
        return self

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, output_file: str) -> None:
        """Save the reasoned ontology as RDF/XML."""
        if self._onto is None:
            raise RuntimeError("No ontology loaded — call load() first.")
        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._onto.save(file=str(out), format="rdfxml")
        print(f"[OWLReasoner] Saved → {out}  ({out.stat().st_size:,} bytes)")

    # ── One-shot convenience ───────────────────────────────────────────────────

    def reason(
        self,
        input_file: str,
        output_file: str,
        infer_property_values: bool = True,
    ) -> None:
        """Load → reason → save in one call."""
        self.load(input_file)
        self.run(infer_property_values=infer_property_values)
        self.save(output_file)
