"""Patch wrong external IRIs and enrich external classes with labels/definitions.

Two-step enrichment applied to a serialised OWL graph:

  Step 1 — IRI patches
    Replaces four incorrect/obsolete OBO IRIs that were produced by wrong
    entries in the original UPPER_KNOWN mapping:
      IAO_0000002  → IAO_0000109  (measurement datum)
      IAO_0000244  → OBI_0000938  (categorical measurement datum)
      OBI_0000011  → COB_0000082  (planned process)
      OBI_0000968  → COB_0001300  (device)

  Step 2 — Label enrichment
    For every non-WOND class in the graph, looks up rdfs:label and
    IAO:0000115 (textual definition) from local source-ontology files and
    writes them in-place.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

OBO_BASE  = "http://purl.obolibrary.org/obo/"
WOND_BASE = "http://purl.obolibrary.org/obo/WOND_"
IAO_DEF   = URIRef(OBO_BASE + "IAO_0000115")

IRI_PATCHES: dict[URIRef, URIRef] = {
    URIRef(OBO_BASE + "IAO_0000002"): URIRef(OBO_BASE + "IAO_0000109"),
    URIRef(OBO_BASE + "IAO_0000244"): URIRef(OBO_BASE + "OBI_0000938"),
    URIRef(OBO_BASE + "OBI_0000011"): URIRef(OBO_BASE + "COB_0000082"),
    URIRef(OBO_BASE + "OBI_0000968"): URIRef(OBO_BASE + "COB_0001300"),
}

HARDCODED_LABELS: dict[URIRef, dict[str, str | None]] = {
    URIRef(OBO_BASE + "DRON_00000001"): {"label": "drug product",          "def": None},
    URIRef(OBO_BASE + "DRON_00000005"): {"label": "clinical drug product", "def": None},
}


class _Source(NamedTuple):
    prefix: str
    filename: str
    fmt: str


_SOURCE_TEMPLATES: list[_Source] = [
    _Source("BFO",  "bfo-core.owl", "xml"),
    _Source("COB",  "cob.owl",      "xml"),
    _Source("IAO",  "iao.owl",      "xml"),
    _Source("OBI",  "obi.owl",      "xml"),
    _Source("PATO", "pato.owl",     "xml"),
    _Source("GO",   "go.obo",       "obo"),
]


class ExternalEnricher:
    """Patch IRIs and enrich external-class labels from local ontology files."""

    def __init__(self, onto_dir: str | Path) -> None:
        self.onto_dir = Path(onto_dir)

    def enrich(
        self,
        graph: Graph,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Apply patches and label enrichment in place. Returns stats dict."""
        stats: dict[str, int] = {
            "patched": 0, "added_labels": 0, "added_defs": 0, "missing": 0,
        }
        self._patch_iris(graph, stats, dry_run)
        ext_iris = self._collect_external_iris(graph)
        print(f"\nStep 2 — enriching {len(ext_iris)} external classes:")
        lookup = self._build_lookup(ext_iris)
        self._enrich_labels(graph, ext_iris, lookup, stats, dry_run)
        return stats

    # ── Step 1 ────────────────────────────────────────────────────────────────

    def _patch_iris(self, g: Graph, stats: dict, dry_run: bool) -> None:
        print("\nStep 1 — patching obsolete/wrong external IRIs:")
        for old_iri, new_iri in IRI_PATCHES.items():
            old_short = str(old_iri).split("/obo/")[1]
            new_short = str(new_iri).split("/obo/")[1]
            affected = (
                list(g.triples((None, None, old_iri)))
                + list(g.triples((old_iri, None, None)))
            )
            if not affected:
                print(f"  {old_short}  → (not present, skipping)")
                continue
            print(f"  {old_short:20s} → {new_short}  ({len(affected)} triple(s))")
            if not dry_run:
                g.add((new_iri, RDF.type, OWL.Class))
                for s, p, o in list(g.triples((None, None, old_iri))):
                    g.remove((s, p, o))
                    g.add((s, p, new_iri))
                for s, p, o in list(g.triples((old_iri, None, None))):
                    g.remove((s, p, o))
                    g.add((new_iri, p, o))
                stats["patched"] += len(affected)
        print(f"  {stats['patched']} triples updated")

    # ── Step 2 helpers ────────────────────────────────────────────────────────

    def _collect_external_iris(self, g: Graph) -> set[URIRef]:
        ext: set[URIRef] = set()
        for s in g.subjects(RDF.type, OWL.Class):
            if isinstance(s, URIRef) and self._is_external(str(s)):
                ext.add(s)
        for _, _, o in g.triples((None, RDFS.subClassOf, None)):
            if isinstance(o, URIRef) and self._is_external(str(o)):
                ext.add(o)
        return ext

    @staticmethod
    def _is_external(iri: str) -> bool:
        return iri.startswith(OBO_BASE) and not iri.startswith(WOND_BASE)

    def _build_lookup(self, needed: set[URIRef]) -> dict[URIRef, dict]:
        lookup: dict[URIRef, dict] = {
            iri: HARDCODED_LABELS[iri]
            for iri in needed
            if iri in HARDCODED_LABELS
        }
        remaining = needed - set(lookup)

        by_prefix: dict[str, list[URIRef]] = {}
        for iri in remaining:
            local = str(iri).split("/obo/")[1]
            pfx   = local.split("_")[0]
            by_prefix.setdefault(pfx, []).append(iri)

        for src in _SOURCE_TEMPLATES:
            batch = by_prefix.get(src.prefix, [])
            if not batch:
                continue
            path = self.onto_dir / src.filename
            if not path.exists():
                print(f"  {src.prefix}: {path.name} not found — skipping")
                continue
            print(f"  {src.prefix}: loading {path.name} …", end=" ", flush=True)
            g = _parse_obo_file(path) if src.fmt == "obo" else _parse_owl_file(path)
            print(f"{len(g)} triples")
            for iri in batch:
                lbl  = g.value(iri, RDFS.label)
                defn = g.value(iri, IAO_DEF)
                if lbl:
                    lookup[iri] = {"label": str(lbl), "def": str(defn) if defn else None}
        return lookup

    def _enrich_labels(
        self,
        g: Graph,
        ext_iris: set[URIRef],
        lookup: dict[URIRef, dict],
        stats: dict,
        dry_run: bool,
    ) -> None:
        missing = 0
        for iri in sorted(ext_iris, key=str):
            short = str(iri).split("/obo/")[1]
            info  = lookup.get(iri)
            if not info:
                print(f"  {short:25s}  NOT FOUND in source ontologies")
                missing += 1
                continue
            label = info["label"]
            defn  = info.get("def")
            print(f"  {short:25s}  {label!r}" + ("  [has def]" if defn else ""))
            if not dry_run:
                g.add((iri, RDF.type, OWL.Class))
                if not g.value(iri, RDFS.label):
                    g.add((iri, RDFS.label, Literal(label)))
                    stats["added_labels"] += 1
                if defn and not g.value(iri, IAO_DEF):
                    g.add((iri, IAO_DEF, Literal(defn)))
                    stats["added_defs"] += 1
        stats["missing"] = missing
        print(
            f"\n  Added {stats['added_labels']} labels, "
            f"{stats['added_defs']} definitions, "
            f"{missing} not found"
        )


# ── File parsers ──────────────────────────────────────────────────────────────

def _parse_owl_file(path: Path) -> Graph:
    g = Graph()
    g.parse(str(path), format="xml")
    return g


def _parse_obo_file(path: Path) -> Graph:
    """Minimal OBO → rdflib parser (id / name / def per [Term])."""
    g = Graph()
    in_term = False
    cur_id = cur_name = cur_def = None

    def _commit() -> None:
        if cur_id and cur_name:
            iri = URIRef(OBO_BASE + cur_id.replace(":", "_"))
            g.add((iri, RDF.type,    OWL.Class))
            g.add((iri, RDFS.label,  Literal(cur_name)))
            if cur_def:
                g.add((iri, IAO_DEF, Literal(cur_def)))

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip()
            if line == "[Term]":
                _commit()
                in_term, cur_id, cur_name, cur_def = True, None, None, None
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
                elif line.startswith("is_obsolete: true"):
                    cur_id = None
    _commit()
    return g
