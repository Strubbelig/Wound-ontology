from __future__ import annotations
from pathlib import Path
from owlready2 import World, sync_reasoner
from rdflib import Graph, RDF, OWL


class Reasoner:
    """
    Runs reasoning over TBox and ABox.

    TBox reasoning uses owlready2's sync_reasoner() (Pellet/HermiT) and
    requires Java and JPype.

    ABox reasoning uses owlrl (OWL RL materialisation) over a combined
    TBox + ABox rdflib graph — no Java required.

    Usage — fluent API (TBox):
        Reasoner()
            .load("output/ontology.owl")
            .run()
            .save("output/ontology_inferred.owl")

    Or one-shot (TBox):
        Reasoner().reason("output/ontology.owl", "output/ontology_inferred.owl")

    Or ABox reasoning:
        Reasoner().expand_owlrl("tbox.owl", "abox.owl", "abox_inferred.owl")

    Or via the orchestrator:
        pipeline.run_reason_owl(input_file=..., output_file=...)
    """

    def __init__(self):
        self._world = None
        self._onto  = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def load(self, owl_file: str) -> "Reasoner":
        """Load an OWL/RDF-XML file into a fresh owlready2 World."""
        path = Path(owl_file).resolve()
        self._world = World()
        self._onto  = self._world.get_ontology(f"file://{path}").load()
        print(f"[Reasoner] Loaded: {path}")
        return self

    # ── TBox reasoning ─────────────────────────────────────────────────────────

    def run(self, infer_property_values: bool = True) -> "Reasoner":
        """
        Run the Pellet/HermiT reasoner to materialise inferred TBox axioms.
        Must call load() first.
        """
        if self._onto is None:
            raise RuntimeError("No ontology loaded — call load() first.")
        with self._onto:
            sync_reasoner(infer_property_values=infer_property_values)
        print("[Reasoner] TBox reasoning complete.")
        return self

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, output_file: str) -> None:
        """Save the reasoned ontology as RDF/XML."""
        if self._onto is None:
            raise RuntimeError("No ontology loaded — call load() first.")
        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        self._onto.save(file=str(out), format="rdfxml")
        print(f"[Reasoner] Saved → {out}  ({out.stat().st_size:,} bytes)")

    # ── One-shot convenience ───────────────────────────────────────────────────

    def reason(
        self,
        input_file: str,
        output_file: str,
        infer_property_values: bool = True,
    ) -> None:
        """Load → reason → save in one call (TBox, requires Java)."""
        self.load(input_file)
        self.run(infer_property_values=infer_property_values)
        self.save(output_file)

    # ── ABox reasoning (OWL RL, rdflib-based, no Java required) ───────────────

    def expand_owlrl(
        self,
        tbox_file: str,
        abox_file: str,
        output_file: str,
        check_consistency: bool = True,
    ) -> bool:
        """
        Load TBox + ABox, run OWL RL materialisation via ``owlrl``, and save
        the fully expanded graph as RDF/XML.  Does not require Java or JPype.

        Parameters
        ----------
        tbox_file : str
            Path to the TBox OWL file.
        abox_file : str
            Path to the ABox OWL file.
        output_file : str
            Destination for the merged + inferred OWL file.
        check_consistency : bool
            If True (default), report whether any individual is typed
            ``owl:Nothing`` (indicates inconsistency).

        Returns
        -------
        bool
            True if consistent (or check skipped), False if inconsistent.
        """
        try:
            import owlrl
        except ImportError as exc:
            raise ImportError(
                "owlrl is required for expand_owlrl(). "
                "Install it with: pip install owlrl"
            ) from exc

        g = Graph()
        print(f"[Reasoner] Loading TBox: {tbox_file}", flush=True)
        g.parse(tbox_file, format="xml")
        t = len(g)
        print(f"  {t:,} triples")

        print(f"[Reasoner] Loading ABox: {abox_file}", flush=True)
        g.parse(abox_file, format="xml")
        print(f"  +{len(g) - t:,} triples (total {len(g):,})")

        print("[Reasoner] Running OWL RL reasoning …", flush=True)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
        print(f"  After reasoning: {len(g):,} triples")

        consistent = True
        if check_consistency:
            incon = list(g.subjects(RDF.type, OWL.Nothing))
            if incon:
                print(f"[Reasoner] INCONSISTENCY: {len(incon)} individual(s) typed owl:Nothing")
                for ind in incon[:5]:
                    print(f"  {ind}")
                consistent = False
            else:
                print("[Reasoner] CONSISTENT — no owl:Nothing individuals.")

        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        g.serialize(destination=str(out), format="xml")
        print(f"[Reasoner] Saved → {out}  ({out.stat().st_size / 1e6:.1f} MB)")
        return consistent
