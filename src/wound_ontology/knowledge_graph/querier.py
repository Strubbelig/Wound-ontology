"""KnowledgeGraphQuerier — SPARQL-based queries over a KnowledgeGraph."""

from __future__ import annotations

from pathlib import Path

import rdflib
import rdflib.query

from .model import KnowledgeGraph

_SPARQL_DIR = Path(__file__).parent / "sparql"

_DEFAULT_PREFIXES = """\
PREFIX rdf:      <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:     <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:      <http://www.w3.org/2002/07/owl#>
PREFIX xsd:      <http://www.w3.org/2001/XMLSchema#>
PREFIX obo:      <http://purl.obolibrary.org/obo/>
PREFIX oboann:   <http://www.geneontology.org/formats/oboInOwl#>
PREFIX dcterms:  <http://purl.org/dc/terms/>
PREFIX wond:     <http://purl.obolibrary.org/obo/WOND_>
"""


def _load_query(filename: str) -> str:
    return (Path(filename) if Path(filename).is_absolute()
            else _SPARQL_DIR / filename).read_text(encoding="utf-8")


def _fill(template: str, **substitutions: str) -> str:
    for key, value in substitutions.items():
        template = template.replace("{" + key + "}", value)
    return template


def _row_to_dict(row, keys: list[str]) -> dict:
    return {k: str(getattr(row, k, "")) for k in keys}


class KnowledgeGraphQuerier:
    """Named SPARQL queries for OWL ontologies backed by a KnowledgeGraph.

    All methods pre-inject a standard PREFIX block.  Additional prefixes can
    be registered with add_prefix().

    Named query methods (return list[dict]):
      subclasses_of(class_iri)           — transitive subclasses
      superclasses_of(class_iri)         — direct parent classes
      find_by_label(text)                — label substring search
      classes_in_namespace(prefix)       — classes by IRI prefix
      all_classes()                      — every declared owl:Class
      restrictions_on(class_iri)         — owl:Restriction axioms
      classes_with_restriction(prop_iri) — classes restricted via a property
      subjects_of_property(prop_iri)     — subject→object pairs for a property
      citations(class_iri=None)          — dcterms:bibliographicCitation annotations
      used_properties()                  — distinct properties in any restriction
      label_of(iri)                      — rdfs:label string for a given IRI
      iri_of_label(label)                — first IRI matching a label

    Raw query:
      query(sparql_str)                  — auto-prepends prefix block
    """

    def __init__(self, kg: KnowledgeGraph) -> None:
        self._g = kg.graph
        self._extra_prefixes: dict[str, str] = {}

    def add_prefix(self, alias: str, iri: str) -> "KnowledgeGraphQuerier":
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
        text  = _fill(_load_query(filename), **substitutions)
        extra = "".join(
            f"PREFIX {alias}: <{iri}>\n"
            for alias, iri in self._extra_prefixes.items()
        )
        return self._g.query(extra + text)

    def query(self, sparql: str) -> rdflib.query.Result:
        """Execute arbitrary SPARQL with the standard prefix block prepended."""
        return self._g.query(self._prefixes() + sparql)

    # ── Named queries ─────────────────────────────────────────────────────────

    def subclasses_of(self, class_iri: str, direct: bool = False) -> list[dict]:
        rows = self._run("subclasses_of.sparql", class_iri=class_iri, step="rdfs:subClassOf*")
        result = [_row_to_dict(r, ["iri", "label"]) for r in rows]
        if direct:
            from rdflib import RDFS, URIRef
            direct_parents = {
                str(s)
                for s in self._g.subjects(RDFS.subClassOf, URIRef(class_iri))
            }
            result = [r for r in result if r["iri"] in direct_parents]
        return result

    def superclasses_of(self, class_iri: str) -> list[dict]:
        return [_row_to_dict(r, ["iri", "label"])
                for r in self._run("superclasses_of.sparql", class_iri=class_iri)]

    def find_by_label(self, text: str) -> list[dict]:
        return [_row_to_dict(r, ["iri", "label"])
                for r in self._run("find_by_label.sparql", text=text.lower())]

    def classes_in_namespace(self, prefix: str) -> list[dict]:
        return [_row_to_dict(r, ["iri", "label"])
                for r in self._run("classes_in_namespace.sparql", namespace=prefix)]

    def all_classes(self) -> list[dict]:
        return [_row_to_dict(r, ["iri", "label"])
                for r in self._run("all_classes.sparql")]

    def restrictions_on(self, class_iri: str) -> list[dict]:
        return [_row_to_dict(r, ["property", "filler", "restriction_type"])
                for r in self._run("restrictions_on.sparql", class_iri=class_iri)]

    def classes_with_restriction(self, property_iri: str) -> list[dict]:
        return [_row_to_dict(r, ["iri", "label", "filler"])
                for r in self._run("classes_with_restriction.sparql", property_iri=property_iri)]

    def subjects_of_property(self, property_iri: str) -> list[dict]:
        return [_row_to_dict(r, ["subject", "object"])
                for r in self._run("subjects_of_property.sparql", property_iri=property_iri)]

    def citations(self, class_iri: str | None = None) -> list[dict]:
        if class_iri:
            return [_row_to_dict(r, ["iri", "citation"])
                    for r in self._run("citations.sparql", class_iri=class_iri)]
        return [_row_to_dict(r, ["iri", "citation"])
                for r in self._run("citations.sparql", class_iri="")]

    def used_properties(self) -> list[dict]:
        return [_row_to_dict(r, ["property"])
                for r in self._run("used_properties.sparql")]

    def label_of(self, iri: str, lang: str = "en") -> str | None:
        rows = list(self._run("label_of.sparql", iri=iri))
        for row in rows:
            lbl = row.label
            if hasattr(lbl, "language") and lbl.language == lang:
                return str(lbl)
        return str(rows[0].label) if rows else None

    def iri_of_label(self, label: str, lang: str | None = None) -> str | None:
        escaped = label.replace('"', '\\"')
        lang_filter = f'FILTER(LANG(?label_val) = "{lang}")' if lang else ""
        rows = list(self._run("iri_of_label.sparql", escaped=escaped, lang_filter=lang_filter))
        return str(rows[0].iri) if rows else None
