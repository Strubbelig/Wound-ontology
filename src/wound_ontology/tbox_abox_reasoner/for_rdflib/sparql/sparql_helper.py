from __future__ import annotations
from pathlib import Path
import rdflib

# ── Standard prefix block prepended to every raw query() call ────────────────
_DEFAULT_PREFIXES = """\
PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:     <http://www.w3.org/2002/07/owl#>
PREFIX obo:     <http://purl.obolibrary.org/obo/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX wond:    <http://purl.obolibrary.org/obo/WOND_>
"""

_SPARQL_DIR = Path(__file__).parent


def _load_query(filename: str) -> str:
    return (_SPARQL_DIR / filename).read_text(encoding="utf-8")


def _fill(template: str, **substitutions: str) -> str:
    """Replace {placeholder} markers without touching SPARQL { } group delimiters."""
    for key, value in substitutions.items():
        template = template.replace("{" + key + "}", value)
    return template


def _row_to_dict(row, keys: list[str]) -> dict:
    return {k: (str(getattr(row, k)) if getattr(row, k, None) is not None else None)
            for k in keys}


class SPARQLHelper:
    """
    Named SPARQL queries for OWL ontologies, backed by an rdflib.Graph.

    All methods pre-inject a standard PREFIX block so callers never need to
    repeat rdfs:, owl:, obo:, dcterms:, wond: declarations. Additional
    prefixes can be registered with add_prefix().

    Accepts either a plain rdflib.Graph or an ABox instance (which exposes
    its graph via the .graph property).

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

        sq = SPARQLHelper(abox)         # abox is an ABox instance
        sq = SPARQLHelper(rdf_graph)    # or a plain rdflib.Graph

        sq.add_prefix("ofl", "https://purl.bioontology.org/ontology/OFL/")

        for row in sq.subclasses_of("http://purl.obolibrary.org/obo/WOND_0000042"):
            print(row["iri"], row["label"])

        results = sq.query('''
            SELECT ?cls WHERE { ?cls rdfs:subClassOf wond:0000042 . }
        ''')
    """

    def __init__(self, graph):
        if isinstance(graph, rdflib.Graph):
            self._g: rdflib.Graph = graph
        elif hasattr(graph, "graph") and isinstance(graph.graph, rdflib.Graph):
            # Accepts ABox or any wrapper that exposes a .graph property
            self._g = graph.graph
        else:
            raise TypeError(
                f"Expected rdflib.Graph or an object with a .graph property, "
                f"got {type(graph).__name__}"
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

    def _run(self, filename: str, **substitutions: str) -> rdflib.query.Result:
        """Load a .sparql file, substitute placeholders, prepend extra prefixes, execute."""
        text = _fill(_load_query(filename), **substitutions)
        extra = "".join(
            f"PREFIX {alias}: <{iri}>\n"
            for alias, iri in self._extra_prefixes.items()
        )
        return self._g.query(extra + text)

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
        rows = self._run("subclasses_of.sparql", class_iri=class_iri, step=step)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    def superclasses_of(self, class_iri: str) -> list[dict]:
        """Direct parent classes of class_iri."""
        rows = self._run("superclasses_of.sparql", class_iri=class_iri)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    # ── Label search ──────────────────────────────────────────────────────────

    def find_by_label(self, text: str) -> list[dict]:
        """Classes whose rdfs:label contains text (case-insensitive)."""
        rows = self._run("find_by_label.sparql", text=text)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    # ── Namespace filtering ───────────────────────────────────────────────────

    def classes_in_namespace(self, prefix: str) -> list[dict]:
        """
        All owl:Class IRIs that start with prefix.
        Covers the UNION pattern from the Flap notebook (explicit classes,
        typed instances, subClassOf subjects and objects).
        """
        rows = self._run("classes_in_namespace.sparql", prefix=prefix)
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    def all_classes(self) -> list[dict]:
        """Every explicitly declared owl:Class with its label."""
        rows = self._run("all_classes.sparql")
        return [_row_to_dict(r, ["iri", "label"]) for r in rows]

    # ── Property restrictions ─────────────────────────────────────────────────

    def restrictions_on(self, class_iri: str) -> list[dict]:
        """
        All owl:Restriction axioms for class_iri.
        Returns rows with property, filler, and restriction_type
        (someValuesFrom / allValuesFrom / hasValue).
        """
        rows = self._run("restrictions_on.sparql", class_iri=class_iri)
        return [_row_to_dict(r, ["property", "filler", "restriction_type"]) for r in rows]

    def classes_with_restriction(self, property_iri: str) -> list[dict]:
        """
        All classes that carry a someValuesFrom restriction on property_iri,
        plus the filler class and its label.
        """
        rows = self._run("classes_with_restriction.sparql", property_iri=property_iri)
        return [_row_to_dict(r, ["defined_class", "class_label", "filler", "filler_label"])
                for r in rows]

    # ── Generic property lookup ───────────────────────────────────────────────

    def subjects_of_property(self, property_iri: str) -> list[dict]:
        """All (subject, object) pairs for a given property IRI."""
        rows = self._run("subjects_of_property.sparql", property_iri=property_iri)
        return [_row_to_dict(r, ["subject", "object"]) for r in rows]

    def used_properties(self) -> list[dict]:
        """
        All distinct object properties that appear in any owl:Restriction,
        with their labels. Useful for discovering what relations are modelled.
        """
        rows = self._run("used_properties.sparql")
        return [_row_to_dict(r, ["property", "label"]) for r in rows]

    # ── Label / IRI lookup ────────────────────────────────────────────────────

    def label_of(self, iri: str, lang: str = "en") -> str | None:
        """
        Return the rdfs:label of iri.

        Prefers the label tagged with lang; falls back to any label when no
        language-tagged match is found. Returns None when no label exists.
        """
        rows = list(self._run("label_of.sparql", iri=iri))
        for row in rows:
            if getattr(row.label, "language", None) == lang:
                return str(row.label)
        return str(rows[0].label) if rows else None

    def iri_of_label(self, label: str, lang: str | None = None) -> str | None:
        """
        Reverse label lookup — return the IRI string of the first subject whose
        rdfs:label matches label (case-insensitive).

        lang
            When given, only labels with this language tag are considered.
            None (default) matches any language tag.
        Returns None when no match is found.
        """
        escaped     = label.replace("\\", "\\\\").replace('"', '\\"')
        lang_filter = f'FILTER(LANG(?label_val) = "{lang}")' if lang else ""
        rows = list(self._run("iri_of_label.sparql", escaped=escaped, lang_filter=lang_filter))
        return str(rows[0].iri) if rows else None

    # ── Citations ─────────────────────────────────────────────────────────────

    def citations(self, class_iri: str | None = None) -> list[dict]:
        """
        Classes annotated with dcterms:bibliographicCitation.
        class_iri — restrict to a specific class and its subclasses (optional).
        """
        scope = f"?iri rdfs:subClassOf* <{class_iri}> ." if class_iri else ""
        rows = self._run("citations.sparql", scope=scope)
        return [_row_to_dict(r, ["iri", "label", "citation"]) for r in rows]
