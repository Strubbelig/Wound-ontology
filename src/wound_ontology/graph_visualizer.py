from __future__ import annotations
from pathlib import Path

import networkx as nx
import rdflib
from rdflib.namespace import RDF, RDFS, OWL


def _local_name(iri: str) -> str:
    return iri.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _namespace_of(iri: str) -> str:
    if "purl.obolibrary.org/obo/BFO" in iri: return "bfo"
    if "purl.obolibrary.org/obo/RO"  in iri: return "ro"
    if "purl.obolibrary.org/obo/OBI" in iri: return "obi"
    if "purl.obolibrary.org/obo/"    in iri: return "obo"
    if "www.w3.org"                  in iri: return "owl"
    return "local"


class GraphVisualizer:
    """
    Exports an OWL ontology to GEXF format for visualisation in Gephi
    (or any tool that reads GEXF 1.2, such as Cytoscape or sigma.js).

    Accepts an ABox instance or a plain rdflib.Graph.

    Usage:
        exporter = GraphVisualizer()
        exporter.export(abox, "output/ontology.gexf")

        # One-shot from an OWL file
        exporter.export_owl("enriched.owl", "output/ontology.gexf")

    Gephi tips:
      - Use "node_type" as a partition colour (class vs individual).
      - Use "predicate" on edges to filter by relationship type.
      - Use "namespace" to hide/show BFO, RO, OBI nodes separately.
    """

    def export(self, graph, output_file: str) -> None:
        """
        Write an rdflib.Graph (or ABox) to a GEXF file.

        Node attributes: label, iri, node_type, namespace
        Edge attributes: predicate
        """
        rdf_g = graph.graph if hasattr(graph, "graph") else graph
        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        nx_graph = self._to_networkx(rdf_g)
        nx.write_gexf(nx_graph, str(out))
        print(
            f"[GraphVisualizer] Saved → {out}  "
            f"({out.stat().st_size:,} bytes, "
            f"{nx_graph.number_of_nodes()} nodes, {nx_graph.number_of_edges()} edges)"
        )

    def export_owl(self, owl_file: str, output_file: str) -> None:
        """One-shot: parse an OWL file and write GEXF."""
        from wound_ontology.tbox_abox_reasoner.for_rdflib.abox import ABox
        self.export(ABox.from_owl(owl_file), output_file)

    @staticmethod
    def _to_networkx(g: rdflib.Graph) -> nx.DiGraph:
        """Convert an rdflib.Graph to a NetworkX DiGraph for GEXF serialisation."""
        labels: dict[str, str] = {
            str(s): str(o)
            for s, _, o in g.triples((None, RDFS.label, None))
            if isinstance(s, rdflib.URIRef)
        }

        def _label(iri: str) -> str:
            return labels.get(iri, _local_name(iri))

        nx_g = nx.DiGraph()

        def _add_node(iri: str, node_type: str) -> None:
            if iri not in nx_g:
                nx_g.add_node(
                    iri,
                    label=_label(iri),
                    iri=iri,
                    node_type=node_type,
                    namespace=_namespace_of(iri),
                )

        # subClassOf edges
        for subj, _, obj in g.triples((None, RDFS.subClassOf, None)):
            if not (isinstance(subj, rdflib.URIRef) and isinstance(obj, rdflib.URIRef)):
                continue
            s, o = str(subj), str(obj)
            _add_node(s, "class")
            _add_node(o, "class")
            nx_g.add_edge(s, o, predicate="is_a", label="is_a")

        # owl:Restriction → typed property edges
        for cls_iri, _, restriction in g.triples((None, RDFS.subClassOf, None)):
            if not isinstance(cls_iri, rdflib.URIRef):
                continue
            if (restriction, RDF.type, OWL.Restriction) not in g:
                continue
            prop_list = list(g.objects(restriction, OWL.onProperty))
            if not prop_list or not isinstance(prop_list[0], rdflib.URIRef):
                continue
            prop_label = _label(str(prop_list[0]))
            for restriction_type in (OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue):
                for filler in g.objects(restriction, restriction_type):
                    if not isinstance(filler, rdflib.URIRef):
                        continue
                    s, o = str(cls_iri), str(filler)
                    _add_node(s, "class")
                    _add_node(o, "class")
                    nx_g.add_edge(s, o, predicate=prop_label, label=prop_label)

        # object property assertions on individuals
        for subj, pred, obj in g:
            if not (isinstance(subj, rdflib.URIRef) and isinstance(obj, rdflib.URIRef)):
                continue
            if pred in (RDFS.subClassOf, RDFS.label, RDF.type,
                        OWL.onProperty, OWL.someValuesFrom,
                        OWL.allValuesFrom, OWL.hasValue):
                continue
            if "purl.org/dc" in str(pred) or "w3.org" in str(pred):
                continue
            s, o = str(subj), str(obj)
            pred_label = _label(str(pred))
            _add_node(s, "individual")
            _add_node(o, "individual")
            if not nx_g.has_edge(s, o):
                nx_g.add_edge(s, o, predicate=pred_label, label=pred_label)

        return nx_g
