"""Load ontology files of various formats into a unified TargetConcept list."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

IAO_DEF      = URIRef("http://purl.obolibrary.org/obo/IAO_0000115")
OBO_SYN      = URIRef("http://www.geneontology.org/formats/oboInOwl#hasExactSynonym")
OBO_BASE     = "http://purl.obolibrary.org/obo/"
SNOMED_BASE  = "http://snomed.info/id/"


@dataclass
class TargetConcept:
    iri:        str
    label:      str
    synonyms:   list[str]          = field(default_factory=list)
    parent_iri: str | None         = None
    definition: str | None         = None


def load_target(path: Path) -> list[TargetConcept]:
    """Dispatch on extension to load an ontology file into TargetConcept list.

    Supported formats:
      .json          — SNOMED wound concepts JSON
      .obo           — OBO flat-file format
      .owl / .rdf / .ttl / .xml — any rdflib-parseable OWL/RDF format
    """
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_snomed_json(path)
    if suffix == ".obo":
        return _load_obo(path)
    if suffix in (".owl", ".rdf", ".ttl", ".xml"):
        return _load_owl(path)
    raise ValueError(f"Unsupported target format: {path.suffix!r} ({path.name})")


# ── Format-specific loaders ───────────────────────────────────────────────────

def _load_snomed_json(path: Path) -> list[TargetConcept]:
    raw = json.loads(path.read_text())
    concepts = []
    for c in raw:
        code        = c["snomed_code"]
        parent_code = c.get("parent_code", "")
        concepts.append(TargetConcept(
            iri        = SNOMED_BASE + code,
            label      = c["preferred_name"],
            synonyms   = c.get("synonyms", []),
            parent_iri = SNOMED_BASE + parent_code if parent_code else None,
            definition = c.get("definition"),
        ))
    return concepts


def _load_obo(path: Path) -> list[TargetConcept]:
    """Minimal OBO parser: non-obsolete [Term] blocks only."""
    concepts: list[TargetConcept] = []

    in_term = False
    cur_id = cur_name = cur_def = None
    cur_synonyms: list[str] = []
    cur_parents:  list[str] = []
    is_obsolete   = False

    def _commit() -> None:
        if cur_id and cur_name and not is_obsolete:
            iri        = OBO_BASE + cur_id.replace(":", "_")
            parent_iri = OBO_BASE + cur_parents[0].replace(":", "_") if cur_parents else None
            concepts.append(TargetConcept(
                iri        = iri,
                label      = cur_name,
                synonyms   = list(cur_synonyms),
                parent_iri = parent_iri,
                definition = cur_def,
            ))

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if line == "[Term]":
                _commit()
                in_term, cur_id, cur_name, cur_def = True, None, None, None
                cur_synonyms, cur_parents, is_obsolete = [], [], False
            elif line.startswith("[") and line != "[Term]":
                in_term = False
            elif in_term:
                if line.startswith("id: "):
                    cur_id = line[4:].strip()
                elif line.startswith("name: "):
                    cur_name = line[6:].strip()
                elif line.startswith("def: "):
                    m = re.match(r'def: "([^"]+)"', line)
                    if m:
                        cur_def = m.group(1)
                elif line.startswith("synonym: "):
                    m = re.match(r'synonym: "([^"]+)"', line)
                    if m:
                        cur_synonyms.append(m.group(1))
                elif line.startswith("is_a: "):
                    parent_id = line[6:].split("!")[0].strip()
                    cur_parents.append(parent_id)
                elif line == "is_obsolete: true":
                    is_obsolete = True
    _commit()
    return concepts


def _load_owl(path: Path) -> list[TargetConcept]:
    """Parse OWL/RDF and extract one TargetConcept per named, labelled class."""
    g = Graph()
    g.parse(str(path))
    concepts = []
    for cls in g.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef):
            continue
        label = g.value(cls, RDFS.label)
        if not label:
            continue
        synonyms   = [str(s) for s in g.objects(cls, OBO_SYN)]
        parents    = [str(p) for p in g.objects(cls, RDFS.subClassOf)
                      if isinstance(p, URIRef)]
        definition = g.value(cls, IAO_DEF)
        concepts.append(TargetConcept(
            iri        = str(cls),
            label      = str(label),
            synonyms   = synonyms,
            parent_iri = parents[0] if parents else None,
            definition = str(definition) if definition else None,
        ))
    return concepts
