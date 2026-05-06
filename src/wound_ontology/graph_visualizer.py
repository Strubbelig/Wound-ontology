from __future__ import annotations
from pathlib import Path

import networkx as nx

from wound_ontology.graph.knowledge_graph import KnowledgeGraph


class GraphVisualizer:
    """
    Exports a KnowledgeGraph to GEXF format for visualisation in Gephi
    (or any tool that reads GEXF 1.2, such as Cytoscape or sigma.js).

    GEXF encodes node attributes (label, iri, node_type, namespace) and
    edge attributes (predicate) so that Gephi can colour and filter the
    graph by relationship type and namespace on load.

    Usage:

        # From an already-built KnowledgeGraph
        exporter = GraphExporter()
        exporter.export(kg, "output/wound_ontology.gexf")

        # One-shot directly from an OWL file
        exporter.export_owl("output/ontology_enriched.owl",
                            "output/wound_ontology.gexf")

        # One-shot from ConceptStore + hierarchies (no OWL needed)
        exporter.export_store(store, class_hier, mere_hier,
                              output_file="output/wound_ontology.gexf")

        # Via the orchestrator
        pipeline.export_to_gexf(input_owl=..., output_file=...)

    Gephi tips:
      - Open the .gexf file directly in Gephi (File → Open).
      - Use "node_type" as a partition colour to distinguish classes from
        individuals and external ontology nodes.
      - Use "predicate" on edges to filter by relationship type (is_a,
        part_of, has_quality …).
      - Use "namespace" to hide/show BFO, RO, OBI classes separately.
    """

    # ── Primary export ────────────────────────────────────────────────────────

    def export(self, kg: KnowledgeGraph, output_file: str) -> None:
        """
        Write a KnowledgeGraph to a GEXF file.

        Node attributes written: label, iri, node_type, namespace
        Edge attributes written: predicate (= relationship type)
        """
        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)

        # NetworkX's GEXF writer requires string node attributes; ensure types.
        g = self._prepare_graph(kg.graph)
        nx.write_gexf(g, str(out))
        print(f"[GraphExporter] Saved → {out}  "
              f"({out.stat().st_size:,} bytes, "
              f"{g.number_of_nodes()} nodes, {g.number_of_edges()} edges)")

    # ── One-shot convenience ──────────────────────────────────────────────────

    def export_owl(self, owl_file: str, output_file: str) -> None:
        """
        One-shot: parse an OWL/RDF file, build a KnowledgeGraph, write GEXF.
        """
        kg = KnowledgeGraph().from_owl(owl_file)
        self.export(kg, output_file)

    def export_store(
        self,
        store,
        *hierarchies,
        output_file: str,
    ) -> None:
        """
        One-shot: build from ConceptStore (+ optional hierarchy objects) and
        write GEXF. Use when you want to visualise the pipeline graph before
        exporting to OWL.
        """
        kg = KnowledgeGraph().from_store(store, *hierarchies)
        self.export(kg, output_file)

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _prepare_graph(graph: nx.DiGraph) -> nx.DiGraph:
        """
        Return a copy of the graph with all node/edge attributes cast to types
        that NetworkX's GEXF writer accepts (strings and primitives only).
        """
        g = nx.DiGraph()

        for node, attrs in graph.nodes(data=True):
            g.add_node(
                str(node),
                label     = str(attrs.get("label",     node)),
                iri       = str(attrs.get("iri",       "")),
                node_type = str(attrs.get("node_type", "unknown")),
                namespace = str(attrs.get("namespace", "local")),
            )

        for src, tgt, attrs in graph.edges(data=True):
            g.add_edge(
                str(src),
                str(tgt),
                predicate = str(attrs.get("predicate", "related_to")),
                label     = str(attrs.get("label",     attrs.get("predicate", "related_to"))),
            )

        return g
