from __future__ import annotations
import re
from pathlib import Path

import networkx as nx
import rdflib
from rdflib.namespace import RDF, RDFS, OWL

# ── RDF namespace shorthands ──────────────────────────────────────────────────
_OBO  = "http://purl.obolibrary.org/obo/"
_W3C  = "http://www.w3.org/2002/07/owl#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"

# Predicates in the ConceptStore that map to semantic edge types
_STORE_PREDICATES = {
    "is_a", "part_of", "has_quality", "occurs_in",
    "caused_by", "is_treatment_for",
}


def _local_name(iri: str) -> str:
    """Last segment of an IRI — used as a fallback node label."""
    return iri.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _namespace_of(iri: str) -> str:
    """Classify an IRI into a broad namespace bucket."""
    if "purl.obolibrary.org/obo/BFO" in iri:
        return "bfo"
    if "purl.obolibrary.org/obo/RO"  in iri:
        return "ro"
    if "purl.obolibrary.org/obo/OBI" in iri:
        return "obi"
    if "purl.obolibrary.org/obo/"    in iri:
        return "obo"
    if "www.w3.org"                  in iri:
        return "owl"
    return "local"


class KnowledgeGraph:
    """
    A property graph (NetworkX DiGraph) built from an OWL ontology or from
    the internal wound-ontology pipeline structures (ConceptStore + hierarchies).

    Nodes  — concepts / classes / individuals / properties
             attributes: label, iri, node_type, namespace
    Edges  — typed semantic relationships
             attributes: predicate (is_a / part_of / has_quality / …)

    Three construction paths:

      1. from_owl(owl_file)
         Parses OWL/RDF with rdflib. Extracts subClassOf edges and unpacks
         owl:Restriction axioms (someValuesFrom / allValuesFrom) into typed
         edges. Labels come from rdfs:label.

      2. from_store(store, *hierarchies)
         Builds from the internal ConceptStore (all predicates) and any number
         of BaseHierarchy objects. No OWL file required.

      3. Both combined — call from_store() then from_owl() to merge.

    SPARQL:
      kg.sparql(query)  — executes against the rdflib graph loaded by from_owl().

    Filtering:
      kg.filter_by_namespace(prefix)  — returns a new KG restricted to nodes
                                         whose IRI starts with prefix.
      kg.subgraph(root_label)         — all nodes reachable from root in the DiGraph.

    Inspection:
      kg.stats()             — node/edge counts by type
      kg.find(label)         — all nodes whose label contains the search string
      kg.neighbours(node_id) — successors + predecessors with edge labels
    """

    def __init__(self):
        self._graph:     nx.DiGraph         = nx.DiGraph()
        self._rdf_graph: rdflib.Graph | None = None

    # ── Construction ──────────────────────────────────────────────────────────

    def from_owl(self, owl_file: str) -> "KnowledgeGraph":
        """
        Parse an OWL/RDF-XML file and add its semantic structure to the graph.

        Extracts:
          - rdfs:subClassOf between named classes → is_a edges
          - owl:Restriction (someValuesFrom / allValuesFrom) → typed property edges
          - rdfs:label for node display names

        Keeps the rdflib.Graph in self._rdf_graph for SPARQL queries.
        """
        path = Path(owl_file).resolve()
        g = rdflib.Graph()
        g.parse(str(path), format="xml")
        self._rdf_graph = g

        # ── Step 1: collect labels ────────────────────────────────────────────
        labels: dict[str, str] = {}
        for s, _, o in g.triples((None, RDFS.label, None)):
            if isinstance(s, rdflib.URIRef):
                labels[str(s)] = str(o)

        def _label(iri: str) -> str:
            return labels.get(iri, _local_name(iri))

        def _add_node(iri: str, node_type: str) -> None:
            if iri not in self._graph:
                self._graph.add_node(
                    iri,
                    label=_label(iri),
                    iri=iri,
                    node_type=node_type,
                    namespace=_namespace_of(iri),
                )

        # ── Step 2: subClassOf edges between named classes ────────────────────
        for subj, _, obj in g.triples((None, RDFS.subClassOf, None)):
            if not (isinstance(subj, rdflib.URIRef) and isinstance(obj, rdflib.URIRef)):
                continue
            s, o = str(subj), str(obj)
            _add_node(s, "class")
            _add_node(o, "class")
            self._graph.add_edge(s, o, predicate="is_a", label="is_a")

        # ── Step 3: owl:Restriction → typed property edges ────────────────────
        # Pattern: ?cls rdfs:subClassOf [ owl:onProperty ?prop ;
        #                                 owl:someValuesFrom ?filler ] .
        for cls_iri, _, restriction in g.triples((None, RDFS.subClassOf, None)):
            if not isinstance(cls_iri, rdflib.URIRef):
                continue
            if (restriction, RDF.type, OWL.Restriction) not in g:
                continue
            # Resolve property
            prop_list = list(g.objects(restriction, OWL.onProperty))
            if not prop_list or not isinstance(prop_list[0], rdflib.URIRef):
                continue
            prop_iri   = str(prop_list[0])
            prop_label = _label(prop_iri)

            # someValuesFrom / allValuesFrom / hasValue
            for restriction_type in (OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue):
                for filler in g.objects(restriction, restriction_type):
                    if not isinstance(filler, rdflib.URIRef):
                        continue
                    s, o = str(cls_iri), str(filler)
                    _add_node(s, "class")
                    _add_node(o, "class")
                    self._graph.add_edge(
                        s, o,
                        predicate=prop_label,
                        label=prop_label,
                    )

        # ── Step 4: object property assertions on individuals ─────────────────
        for subj, pred, obj in g:
            if not (isinstance(subj, rdflib.URIRef) and isinstance(obj, rdflib.URIRef)):
                continue
            if pred in (RDFS.subClassOf, RDFS.label, RDF.type,
                        OWL.onProperty, OWL.someValuesFrom,
                        OWL.allValuesFrom, OWL.hasValue):
                continue
            # Only include semantic object properties (skip metadata predicates)
            if "purl.org/dc" in str(pred) or "w3.org" in str(pred):
                continue
            s, o = str(subj), str(obj)
            pred_label = _label(str(pred))
            _add_node(s, "individual")
            _add_node(o, "individual")
            if not self._graph.has_edge(s, o):
                self._graph.add_edge(s, o, predicate=pred_label, label=pred_label)

        print(f"[KnowledgeGraph] from_owl: {self._graph.number_of_nodes()} nodes, "
              f"{self._graph.number_of_edges()} edges loaded from {path.name}")
        return self

    def from_store(self, store, *hierarchies) -> "KnowledgeGraph":
        """
        Build from a ConceptStore and any number of BaseHierarchy objects.

        All predicate:target pairs in the store become typed edges.
        Hierarchy DataFrames add is_a / part_of edges as a complementary source.
        """
        # ── ConceptStore → edges ───────────────────────────────────────────────
        for pmid_data in store.dict.values():
            for entity, attrs in pmid_data.get("entities", {}).items():
                entity = entity.strip()
                if entity not in self._graph:
                    self._graph.add_node(
                        entity, label=entity, iri="", node_type="concept", namespace="local"
                    )
                for triple, value in attrs.items():
                    if value != 1.0 or ":" not in triple:
                        continue
                    pred, target = triple.split(":", 1)
                    pred   = pred.strip().lower().replace(" ", "_")
                    target = target.strip()
                    if pred not in _STORE_PREDICATES:
                        continue
                    if target not in self._graph:
                        self._graph.add_node(
                            target, label=target, iri="", node_type="concept", namespace="local"
                        )
                    if not self._graph.has_edge(entity, target):
                        self._graph.add_edge(entity, target, predicate=pred, label=pred)

        # ── Hierarchy DataFrames → edges ───────────────────────────────────────
        for hier in hierarchies:
            df = hier.df
            pred = getattr(hier, "_predicate_label", "is_a")
            for child in df.index:
                for parent in df.columns:
                    if df.at[child, parent] == 1.0:
                        for node in (child, parent):
                            if node not in self._graph:
                                self._graph.add_node(
                                    node, label=node, iri="",
                                    node_type="concept", namespace="local"
                                )
                        if not self._graph.has_edge(child, parent):
                            self._graph.add_edge(child, parent, predicate=pred, label=pred)

        print(f"[KnowledgeGraph] from_store: {self._graph.number_of_nodes()} nodes, "
              f"{self._graph.number_of_edges()} edges")
        return self

    # ── SPARQL ────────────────────────────────────────────────────────────────

    def sparql(self, query: str):
        """
        Execute a SPARQL SELECT query against the rdflib graph (requires from_owl()).

        Returns an rdflib.query.Result iterable of result rows.

        Example:
            results = kg.sparql('''
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
                SELECT ?cls ?label
                WHERE { ?cls rdfs:subClassOf* <http://example.org/Wound> .
                        ?cls rdfs:label ?label . }
            ''')
            for row in results:
                print(row.cls, row.label)
        """
        if self._rdf_graph is None:
            raise RuntimeError(
                "No rdflib graph available — call from_owl() before sparql()."
            )
        return self._rdf_graph.query(query)

    # ── Filtering ─────────────────────────────────────────────────────────────

    def filter_by_namespace(self, prefix: str) -> "KnowledgeGraph":
        """
        Return a new KnowledgeGraph containing only nodes whose IRI starts
        with prefix (e.g. 'http://purl.obolibrary.org/obo/WOND_').
        Edges are kept only when both endpoints are retained.
        """
        kept = {n for n, d in self._graph.nodes(data=True)
                if d.get("iri", "").startswith(prefix) or prefix in d.get("label", "")}
        kg = KnowledgeGraph()
        kg._graph = self._graph.subgraph(kept).copy()
        kg._rdf_graph = self._rdf_graph
        return kg

    def subgraph(self, root_label: str) -> "KnowledgeGraph":
        """
        Return a new KnowledgeGraph with only the nodes reachable (as
        descendants or ancestors in is_a edges) from the node matching root_label.
        """
        # Find root node id
        root_ids = [n for n, d in self._graph.nodes(data=True)
                    if d.get("label", "").lower() == root_label.lower()
                    or n.lower() == root_label.lower()]
        if not root_ids:
            print(f"[KnowledgeGraph] subgraph: no node matching '{root_label}'")
            kg = KnowledgeGraph()
            return kg

        root = root_ids[0]
        # All descendants (nodes that can reach root via directed path = subtypes)
        descendants = nx.ancestors(self._graph, root) | {root}
        # Also include direct parents so root itself has context
        descendants |= set(self._graph.successors(root))

        kg = KnowledgeGraph()
        kg._graph = self._graph.subgraph(descendants).copy()
        kg._rdf_graph = self._rdf_graph
        return kg

    # ── Inspection ────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return a summary dict of node/edge counts by type."""
        node_types: dict[str, int] = {}
        for _, d in self._graph.nodes(data=True):
            t = d.get("node_type", "unknown")
            node_types[t] = node_types.get(t, 0) + 1

        edge_types: dict[str, int] = {}
        for _, _, d in self._graph.edges(data=True):
            p = d.get("predicate", "unknown")
            edge_types[p] = edge_types.get(p, 0) + 1

        return {
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "node_types": node_types,
            "edge_types":  edge_types,
        }

    def find(self, label: str) -> list[tuple[str, dict]]:
        """Return all (node_id, attrs) whose label contains the search string."""
        label_lower = label.lower()
        return [
            (n, d) for n, d in self._graph.nodes(data=True)
            if label_lower in d.get("label", "").lower()
        ]

    def neighbours(self, node_id: str) -> dict:
        """
        Return a dict with 'parents' and 'children' lists for a node,
        each entry being (neighbour_id, predicate).
        """
        return {
            "parents": [
                (s, self._graph[s][node_id].get("predicate", ""))
                for s in self._graph.predecessors(node_id)
            ],
            "children": [
                (t, self._graph[node_id][t].get("predicate", ""))
                for t in self._graph.successors(node_id)
            ],
        }

    def print_stats(self) -> None:
        s = self.stats()
        print(f"[KnowledgeGraph] {s['nodes']} nodes | {s['edges']} edges")
        print(f"  Node types : {s['node_types']}")
        print(f"  Edge types : {s['edge_types']}")

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    @property
    def nodes(self):
        return self._graph.nodes(data=True)

    @property
    def edges(self):
        return self._graph.edges(data=True)
