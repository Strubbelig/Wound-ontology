"""OWLReasoner — TBox and ABox reasoning over OWL ontologies."""

from __future__ import annotations

from pathlib import Path

from owlready2 import World, sync_reasoner, onto_path
from rdflib import Graph, RDF, OWL


class OWLReasoner:
    """
    Runs reasoning over TBox and ABox.

    TBox reasoning uses owlready2's sync_reasoner() (Pellet/HermiT) and
    requires Java and JPype.

    ABox reasoning uses owlrl (OWL RL materialisation) over a combined
    TBox + ABox rdflib graph — no Java required.

    Usage — fluent (TBox):
        OWLReasoner().load("ontology.owl").run().save("ontology_inferred.owl")

    One-shot (TBox):
        OWLReasoner().reason("ontology.owl", "ontology_inferred.owl")

    ABox reasoning:
        OWLReasoner().expand_owlrl("tbox.owl", "abox.owl", "abox_inferred.owl")

    Via orchestrator:
        pipeline.run_reason_owl(input_file=..., output_file=...)
    """

    def __init__(self) -> None:
        self._world: World | None = None
        self._onto  = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def load(self, owl_file: str) -> "OWLReasoner":
        """Load an OWL/RDF-XML file into a fresh owlready2 World."""
        path = Path(owl_file).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Ontology file not found at {path}")
        self._world = World()
        onto_path.append(str(path.parent))
        self._onto = self._world.get_ontology(path.as_uri()).load()
        print(f"[OWLReasoner] Loaded: {path}")
        return self

    # ── TBox reasoning ─────────────────────────────────────────────────────────

    def run(self, infer_property_values: bool = True) -> "OWLReasoner":
        """Run Pellet/HermiT to materialise inferred TBox axioms (requires Java)."""
        if self._onto is None:
            raise RuntimeError("No ontology loaded — call load() first.")
        with self._onto:
            sync_reasoner(infer_property_values=infer_property_values)
        print("[OWLReasoner] TBox reasoning complete.")
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
        input_file:              str,
        output_file:             str,
        infer_property_values:   bool = True,
    ) -> None:
        """Load → reason → save in one call (TBox, requires Java)."""
        self.load(input_file)
        self.run(infer_property_values=infer_property_values)
        self.save(output_file)

    # ── ABox reasoning (OWL RL, rdflib-based, no Java required) ───────────────

    def expand_owlrl(
        self,
        tbox_file:          str,
        abox_file:          str,
        output_file:        str,
        extra_ontologies:   list[str] | None = None,
        check_consistency:  bool = True,
    ) -> bool:
        """Load TBox + ABox, run OWL RL materialisation, save expanded graph.

        Does not require Java or JPype.  rdflib does NOT follow owl:imports
        automatically, so supply *extra_ontologies* for BFO/RO/OBI/COB etc.

        Returns True if consistent (or check skipped), False if inconsistent.
        """
        try:
            import owlrl
        except ImportError as exc:
            raise ImportError(
                "owlrl is required for expand_owlrl(). "
                "Install it with: pip install owlrl"
            ) from exc

        g = Graph()
        for onto_file in (extra_ontologies or []):
            print(f"[OWLReasoner] Loading support ontology: {Path(onto_file).name}", flush=True)
            g.parse(onto_file, format="xml")
        if extra_ontologies:
            print(f"  {len(g):,} triples from {len(extra_ontologies)} support ontologies")

        print(f"[OWLReasoner] Loading TBox: {tbox_file}", flush=True)
        g.parse(tbox_file, format="xml")
        t = len(g)
        print(f"  {t:,} triples")

        print(f"[OWLReasoner] Loading ABox: {abox_file}", flush=True)
        g.parse(abox_file, format="xml")
        print(f"  +{len(g) - t:,} triples (total {len(g):,})")

        print("[OWLReasoner] Running OWL RL reasoning …", flush=True)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
        print(f"  After reasoning: {len(g):,} triples")

        consistent = True
        if check_consistency:
            incon = list(g.subjects(RDF.type, OWL.Nothing))
            if incon:
                print(f"[OWLReasoner] INCONSISTENCY: {len(incon)} individual(s) typed owl:Nothing")
                for ind in incon[:5]:
                    print(f"  {ind}")
                consistent = False
            else:
                print("[OWLReasoner] CONSISTENT — no owl:Nothing individuals.")

        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        g.serialize(destination=str(out), format="xml")
        print(f"[OWLReasoner] Saved → {out}  ({out.stat().st_size / 1e6:.1f} MB)")
        return consistent
