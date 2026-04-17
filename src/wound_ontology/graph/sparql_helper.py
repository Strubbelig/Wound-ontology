from __future__ import annotations
import rdflib

# ── Standard prefix block prepended to every query ───────────────────────────
_DEFAULT_PREFIXES = """\
PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:     <http://www.w3.org/2002/07/owl#>
PREFIX obo:     <http://purl.obolibrary.org/obo/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX wond:    <http://purl.obolibrary.org/obo/WOND_>
"""


def _row_to_dict(row, keys: list[str]) -> dict:
    return {k: (str(getattr(row, k)) if getattr(row, k, None) is not None else None)
            for k in keys}


class SPARQLHelper:
    """
    Named SPARQL queries for OWL ontologies, backed by an rdflib.Graph.

    All methods pre-inject a standard PREFIX block so callers never need to
    repeat rdfs:, owl:, obo:, dcterms:, wond: declarations. Additional
    prefixes can be registered with add_prefix().

    Accepts either a plain rdflib.Graph or a KnowledgeGraph (which carries
    one internally after from_owl() has been called).

    Named query methods (return list[dict] for easy iteration):
      subclasses_of(class_iri)           — all transitive subclasses
      superclasses_of(class_iri)         — direct parent classes
      find_by_label(text)               — label substring search (case-insensitive)
      classes_in_namespace(prefix)       — classes whose IRI starts with prefix
      all_classes()                      — every declared owl:Class
      restrictions_on(class_iri)         — owl:Restriction axioms for a class
      classes_with_restriction(prop_iri) — classes restricted via a property
      subjects_of_property(prop_iri)     — all ?subject → ?object pairs for a property
      citations(class_iri=None)          — dcterms:bibliographicCitation annotations
      used_properties()                  — distinct properties used in any restriction

    Raw query:
      query(sparql_str)                  — prefix block auto-prepended; returns
                                           rdflib.query.Result (iterable of rows)

    Usage:
        from wound_ontology.graph.sparql_helper import SPARQLHelper

        sq = SPARQLHelper(kg)           # kg is a KnowledgeGraph
        sq = SPARQLHelper(rdf_graph)    # or a plain rdflib.Graph

        sq.add_prefix("ofl", "https://purl.bioontology.org/ontology/OFL/")

        for row in sq.subclasses_of("http://purl.obolibrary.org/obo/WOND_0000042"):
            print(row["iri"], row["label"])

        results = sq.query('''
            SELECT ?cls WHERE { ?cls rdfs:subClassOf wond:0000042 . }
        ''')
    """

    def __init__(self, graph):
        # Accept KnowledgeGraph or plain rdflib.Graph
        if hasattr(graph, "_rdf_graph"):
            if graph._rdf_graph is None:
                raise ValueError(
                    "KnowledgeGraph has no rdflib graph — call from_owl() first."
                )
            self._g: rdflib.Graph = graph._rdf_graph
        elif isinstance(graph, rdflib.Graph):
            self._g = graph
        else:
            raise TypeError(
                f"Expected a KnowledgeGraph or rdflib.Graph, got {type(graph).__name__}"
            )
        self._extra_prefixes: dict[str, str] = {}

    # ── Prefix management ─────────────────────────────────────────────────────

    def add_prefix(self, alias: str, iri: str) -> "SPARQLHelper":
        """Register an extra PREFIX (e.g. 'ofl', 'https://…/OFL/')."""
        self._extra_prefixes[alias] = iri
        return self

    def _prefixes(self) -> str:
        extra = "".join(
            f"PREFIX {alias}: <{iri}>\n"
            for alias, iri in self._extra_prefixes.items()
        )
        return _DEFAULT_PREFIXES + extra

    # ── Raw query ─────────────────────────────────────────────────────────────

    def query(self, sparql: str) -> rdflib.query.Result:
        """
        Execute a SPARQL SELECT query with the standard prefixes auto-prepended.
        Returns an rdflib.query.Result (iterable of named-tuple rows).
        """
        return self._g.query(self._prefixes() + sparql)

    # ── Class hierarchy ───────────────────────────────────────────────────────

    def subclasses_of(self, class_iri: str, direct: bool = False) -> list[dict]:
        """
        All subclasses of class_iri.

        direct=False (default) — transitive (rdfs:subClassOf*)
        direct=True            — one hop only (rdfs:subClassOf)
        """
        step = "rdfs:subClassOf" if direct else "rdfs:subClassOf*"
        rows = self.query(f"""
            SELECT DISTINCT ?iri ?label
            WHERE {{
                ?iri {step} <{class_iri}> .
                FILTER(?iri != <{class_iri}>)
                OPTIONAL {{ ?iri rdfs:label ?label . }}
            }}
        """)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    def superclasses_of(self, class_iri: str) -> list[dict]:
        """Direct parent classes of class_iri."""
        rows = self.query(f"""
            SELECT DISTINCT ?iri ?label
            WHERE {{
                <{class_iri}> rdfs:subClassOf ?iri .
                FILTER(isIRI(?iri))
                OPTIONAL {{ ?iri rdfs:label ?label . }}
            }}
        """)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    # ── Label search ──────────────────────────────────────────────────────────

    def find_by_label(self, text: str) -> list[dict]:
        """
        Classes whose rdfs:label contains text (case-insensitive).
        Mirrors the notebook pattern of searching across label strings.
        """
        rows = self.query(f"""
            SELECT DISTINCT ?iri ?label
            WHERE {{
                ?iri a owl:Class .
                ?iri rdfs:label ?label .
                FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{text}")))
            }}
        """)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    # ── Namespace filtering ───────────────────────────────────────────────────

    def classes_in_namespace(self, prefix: str) -> list[dict]:
        """
        All owl:Class IRIs that start with prefix.
        Covers the UNION pattern from the Flap notebook (explicit classes,
        typed instances, subClassOf subjects and objects).
        """
        rows = self.query(f"""
            SELECT DISTINCT ?iri ?label
            WHERE {{
                {{
                    ?iri a owl:Class .
                }}
                UNION
                {{ [] a ?iri . }}
                UNION
                {{ [] rdfs:subClassOf ?iri . }}
                UNION
                {{ ?iri rdfs:subClassOf [] . }}
                FILTER(STRSTARTS(STR(?iri), "{prefix}"))
                OPTIONAL {{ ?iri rdfs:label ?label . }}
            }}
        """)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    def all_classes(self) -> list[dict]:
        """Every explicitly declared owl:Class with its label."""
        rows = self.query("""
            SELECT DISTINCT ?iri ?label
            WHERE {
                ?iri a owl:Class .
                FILTER(isIRI(?iri))
                OPTIONAL { ?iri rdfs:label ?label . }
            }
        """)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    # ── Property restrictions ─────────────────────────────────────────────────

    def restrictions_on(self, class_iri: str) -> list[dict]:
        """
        All owl:Restriction axioms for class_iri.
        Returns rows with property, filler, and restriction_type
        (someValuesFrom / allValuesFrom / hasValue).
        """
        rows = self.query(f"""
            SELECT DISTINCT ?property ?filler ?restriction_type
            WHERE {{
                <{class_iri}> rdfs:subClassOf ?restriction .
                ?restriction a owl:Restriction ;
                             owl:onProperty ?property .
                {{
                    ?restriction owl:someValuesFrom ?filler .
                    BIND("someValuesFrom" AS ?restriction_type)
                }} UNION {{
                    ?restriction owl:allValuesFrom ?filler .
                    BIND("allValuesFrom" AS ?restriction_type)
                }} UNION {{
                    ?restriction owl:hasValue ?filler .
                    BIND("hasValue" AS ?restriction_type)
                }}
            }}
        """)
        return [_row_to_dict(r, ["property", "filler", "restriction_type"]) for r in rows]

    def classes_with_restriction(self, property_iri: str) -> list[dict]:
        """
        All classes that carry a someValuesFrom restriction on property_iri,
        plus the filler class and its label.
        Directly mirrors the notebook's diagnostic query (cell 43).
        """
        rows = self.query(f"""
            SELECT DISTINCT ?defined_class ?class_label ?filler ?filler_label
            WHERE {{
                ?defined_class rdfs:subClassOf ?restriction .
                ?restriction a owl:Restriction ;
                             owl:onProperty <{property_iri}> ;
                             owl:someValuesFrom ?filler .
                OPTIONAL {{ ?defined_class rdfs:label ?class_label . }}
                OPTIONAL {{ ?filler         rdfs:label ?filler_label . }}
            }}
        """)
        return [_row_to_dict(r, ["defined_class", "class_label", "filler", "filler_label"])
                for r in rows]

    # ── Generic property lookup ───────────────────────────────────────────────

    def subjects_of_property(self, property_iri: str) -> list[dict]:
        """
        All (subject, object) pairs for a given property IRI.
        Mirrors the simple diagnostic query from the Flap notebook (cell 38).
        """
        rows = self.query(f"""
            SELECT ?subject ?object
            WHERE {{
                ?subject <{property_iri}> ?object .
            }}
        """)
        return [_row_to_dict(r, ["subject", "object"]) for r in rows]

    def used_properties(self) -> list[dict]:
        """
        All distinct object properties that appear in any owl:Restriction,
        with their labels. Useful for discovering what relations are modelled.
        """
        rows = self.query("""
            SELECT DISTINCT ?property ?label
            WHERE {
                [] owl:onProperty ?property .
                OPTIONAL { ?property rdfs:label ?label . }
            }
        """)
        return [_row_to_dict(r, ["property", "label"]) for r in rows]

    # ── Citations ─────────────────────────────────────────────────────────────

    def citations(self, class_iri: str | None = None) -> list[dict]:
        """
        Classes annotated with dcterms:bibliographicCitation.
        class_iri — restrict to a specific class and its subclasses (optional).
        Mirrors notebook cell 100.
        """
        if class_iri:
            scope = f"?iri rdfs:subClassOf* <{class_iri}> ."
        else:
            scope = ""
        rows = self.query(f"""
            SELECT DISTINCT ?iri ?label ?citation
            WHERE {{
                {scope}
                ?iri dcterms:bibliographicCitation ?citation .
                OPTIONAL {{ ?iri rdfs:label ?label . }}
            }}
        """)
        return [_row_to_dict(r, ["iri", "label", "citation"]) for r in rows]
