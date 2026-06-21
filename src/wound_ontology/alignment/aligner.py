"""Aligner: align a source OWL ontology to any target ontology.

Typical call sequence:
    aligner = Aligner(source_owl, embedder)
    result  = aligner.align(target_path, method="sapbert+lexical")
    aligner.write_candidates(result, out_dir / "candidates.csv")
    aligner.write_sssom(result, out_dir / "alignment.sssom.tsv")
    aligner.extend(result, out_dir / "source_extended.owl")
    aligner.enrich(result, out_dir / "source_extended.owl")
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from wound_ontology.alignment.target_loader import TargetConcept, load_target

WOND    = Namespace("http://purl.obolibrary.org/obo/WOND_")
OBOANN  = Namespace("http://www.geneontology.org/formats/oboInOwl#")
IAO_DEF = URIRef("http://purl.obolibrary.org/obo/IAO_0000115")
HAS_XREF = OBOANN["hasDbXref"]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _parse_graph(path: Path) -> Graph:
    """Parse an OWL/RDF file with automatic format detection."""
    with open(path) as f:
        first = f.read(200)
    fmt = "turtle" if first.strip().startswith("@") else "xml"
    g = Graph()
    g.parse(str(path), format=fmt)
    return g


def _xref_id(iri: str) -> str:
    """Convert an IRI to a compact xref string (e.g. SNOMEDCT:12345, BFO:0000040)."""
    if "snomed.info/id/" in iri:
        return "SNOMEDCT:" + iri.split("snomed.info/id/")[1]
    if "/obo/" in iri:
        local = iri.split("/obo/")[1]
        parts = local.split("_", 1)
        if len(parts) == 2:
            return f"{parts[0]}:{parts[1]}"
    return iri


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class MappedPair:
    source_iri:   URIRef
    source_label: str
    target:       TargetConcept
    score:        float
    method:       str   # "exact", "sapbert"


@dataclass
class AlignmentResult:
    source_owl:          Path
    target_path:         Path
    method:              str
    mappings:            list[MappedPair]
    candidates:          list[dict]
    unmatched_source:    list[URIRef]        # source classes with no target mapping
    target_concepts:     list[TargetConcept] # full target list (used by extend)
    source_label_index:  dict[str, URIRef]   # norm label → source IRI
    source_max_id:       int


# ── Aligner ───────────────────────────────────────────────────────────────────

class Aligner:
    """Align a source WOND OWL to any target ontology (SNOMED JSON, OBO, OWL).

    The same class handles any target format; format detection is by file extension.
    Embedder is optional: pass None to restrict to lexical-only matching.
    """

    def __init__(self, source_owl: Path, embedder=None) -> None:
        if not source_owl.exists():
            raise FileNotFoundError(f"Source OWL not found: {source_owl}")
        self.source_owl = source_owl
        self.embedder   = embedder
        self._source_graph:       Graph | None             = None
        self._source_label_index: dict[str, URIRef] | None = None
        self._source_max_id:      int | None               = None

    # ── Source loading (lazy, cached) ──────────────────────────────────────────

    def _load_source(self) -> tuple[Graph, dict[str, URIRef], int]:
        if self._source_graph is not None:
            return self._source_graph, self._source_label_index, self._source_max_id

        g = _parse_graph(self.source_owl)

        label_index: dict[str, URIRef] = {}
        max_id = 0
        for cls in g.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef) or "WOND_" not in str(cls):
                continue
            suffix = str(cls).split("WOND_")[1]
            if suffix.isdigit():
                max_id = max(max_id, int(suffix))
            for lbl in g.objects(cls, RDFS.label):
                label_index[_norm(str(lbl))] = cls

        self._source_graph       = g
        self._source_label_index = label_index
        self._source_max_id      = max_id
        return g, label_index, max_id

    # ── align ──────────────────────────────────────────────────────────────────

    def align(
        self,
        target: Path,
        method: str = "sapbert+lexical",
        top_k: int = 5,
        close_thresh: float = 0.70,
    ) -> AlignmentResult:
        """Find mappings between source OWL classes and target concepts.

        method: "lexical", "sapbert", or "sapbert+lexical" (default).
        close_thresh: minimum score for a pair to be included in mappings.
        Lexical exact match always scores 1.0 regardless of threshold.
        Returns AlignmentResult; unmatched_source lists source classes with no mapping.
        """
        import numpy as np

        _, label_index, max_id = self._load_source()
        target_concepts = load_target(target)

        # One row per unique source IRI, using its primary (first) label
        iri_to_label: dict[URIRef, str] = {}
        for norm_lbl, iri in label_index.items():
            if iri not in iri_to_label:
                iri_to_label[iri] = norm_lbl
        source_iris   = list(iri_to_label.keys())
        source_labels = list(iri_to_label.values())
        n_src = len(source_iris)

        t_labels = [_norm(c.label) for c in target_concepts]
        n_tgt    = len(target_concepts)

        print(f"[Aligner] Source: {n_src} WOND classes | Target: {n_tgt} concepts ({target.name})")

        lexical = np.zeros((n_src, n_tgt), dtype=np.float32)
        sapbert = np.zeros((n_src, n_tgt), dtype=np.float32)

        # ── Lexical pass ───────────────────────────────────────────────────────
        if "lexical" in method:
            # Build label + synonym → target index map
            t_norm_to_idx: dict[str, int] = {}
            for j, c in enumerate(target_concepts):
                t_norm_to_idx.setdefault(_norm(c.label), j)
                for syn in c.synonyms:
                    t_norm_to_idx.setdefault(_norm(syn), j)
            for i, s_lbl in enumerate(source_labels):
                j = t_norm_to_idx.get(s_lbl)
                if j is not None:
                    lexical[i, j] = 1.0

        # ── SapBERT pass ───────────────────────────────────────────────────────
        if "sapbert" in method and self.embedder is not None:
            print(f"[Aligner] Embedding {n_src} + {n_tgt} labels via SapBERT...")
            all_embs  = self.embedder.embed(source_labels + t_labels)
            s_embs    = all_embs[:n_src]
            t_embs    = all_embs[n_src:]
            sapbert   = (s_embs @ t_embs.T).astype(np.float32)

        combined = np.maximum(lexical, sapbert)

        # ── Candidates (top-K per source) ──────────────────────────────────────
        candidates: list[dict] = []
        for i, (s_iri, s_lbl) in enumerate(zip(source_iris, source_labels)):
            top_js = np.argsort(combined[i])[::-1][:top_k]
            for j in top_js:
                score = float(combined[i, j])
                if score <= 0:
                    break
                candidates.append({
                    "source_iri":   str(s_iri),
                    "source_label": s_lbl,
                    "target_iri":   target_concepts[j].iri,
                    "target_label": target_concepts[j].label,
                    "score":        round(score, 4),
                    "method":       "exact" if lexical[i, j] == 1.0 else "sapbert",
                })

        # ── Mappings (best match per source above threshold) ───────────────────
        mappings: list[MappedPair] = []
        mapped_source: set[str]   = set()

        for i, (s_iri, s_lbl) in enumerate(zip(source_iris, source_labels)):
            best_j     = int(np.argmax(combined[i]))
            best_score = float(combined[i, best_j])
            if best_score >= close_thresh:
                m_method = "exact" if lexical[i, best_j] == 1.0 else "sapbert"
                mappings.append(MappedPair(
                    source_iri   = s_iri,
                    source_label = s_lbl,
                    target       = target_concepts[best_j],
                    score        = best_score,
                    method       = m_method,
                ))
                mapped_source.add(str(s_iri))

        unmatched_source = [iri for iri in source_iris if str(iri) not in mapped_source]

        print(f"[Aligner] Mapped: {len(mappings)} | "
              f"Unmatched source: {len(unmatched_source)}")

        return AlignmentResult(
            source_owl         = self.source_owl,
            target_path        = target,
            method             = method,
            mappings           = mappings,
            candidates         = candidates,
            unmatched_source   = unmatched_source,
            target_concepts    = target_concepts,
            source_label_index = dict(label_index),
            source_max_id      = max_id,
        )

    # ── extend ─────────────────────────────────────────────────────────────────

    def extend(
        self,
        result: AlignmentResult,
        out_path: Path,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Mint WOND stubs for target concepts that have no source match.

        Reads from source_owl (or out_path if it already exists from a prior
        extend/enrich call), writes merged OWL to out_path.
        Returns {"new_stubs", "parent_resolved", "parent_owlthing"}.
        """
        mapped_target_iris = {m.target.iri for m in result.mappings}
        unmatched_target   = [c for c in result.target_concepts
                               if c.iri not in mapped_target_iris]

        print(f"[Aligner.extend] {len(unmatched_target)} target concepts → new stubs")

        if dry_run:
            for c in unmatched_target[:10]:
                print(f"  would stub: {c.label!r}")
            if len(unmatched_target) > 10:
                print(f"  ... and {len(unmatched_target) - 10} more")
            print("[dry-run] No files written.")
            return {"new_stubs": len(unmatched_target),
                    "parent_resolved": 0, "parent_owlthing": 0}

        src = out_path if out_path.exists() else result.source_owl
        g = _parse_graph(src)
        g.bind("wond",     WOND)
        g.bind("oboInOwl", OBOANN)

        # target IRI → WOND IRI for parent resolution
        target_to_wond: dict[str, URIRef] = {m.target.iri: m.source_iri
                                              for m in result.mappings}
        # assign new IRIs up front so parents of stubs can resolve to sibling stubs
        next_id = result.source_max_id + 1
        new_iri_map: dict[str, URIRef] = {}
        for c in unmatched_target:
            new_iri_map[c.iri] = WOND[f"{next_id:07d}"]
            next_id += 1
        target_to_wond.update(new_iri_map)

        parent_resolved = parent_owlthing = 0
        for c in unmatched_target:
            iri = new_iri_map[c.iri]
            if c.parent_iri and c.parent_iri in target_to_wond:
                parent_iri = target_to_wond[c.parent_iri]
                parent_resolved += 1
            else:
                parent_iri = OWL.Thing
                parent_owlthing += 1

            g.add((iri, RDF.type,        OWL.Class))
            g.add((iri, RDFS.label,      Literal(c.label)))
            g.add((iri, HAS_XREF,        Literal(_xref_id(c.iri))))
            g.add((iri, RDFS.subClassOf, parent_iri))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        g.serialize(str(out_path), format="xml")
        print(f"[Aligner.extend] Wrote {out_path} "
              f"(+{len(unmatched_target)} stubs, "
              f"{parent_resolved} parents resolved, {parent_owlthing} → owl:Thing)")
        return {"new_stubs": len(unmatched_target),
                "parent_resolved": parent_resolved,
                "parent_owlthing": parent_owlthing}

    # ── enrich ─────────────────────────────────────────────────────────────────

    def enrich(
        self,
        result: AlignmentResult,
        out_path: Path,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Annotate mapped source classes with xrefs, labels, and definitions.

        Reads out_path if it exists (after extend()), otherwise reads source_owl.
        Returns {"added_xrefs", "added_labels", "added_defs"}.
        """
        src = out_path if out_path.exists() else result.source_owl
        g = _parse_graph(src)
        g.bind("oboInOwl", OBOANN)

        added_xrefs = added_labels = added_defs = 0
        for m in result.mappings:
            xref = Literal(_xref_id(m.target.iri))
            if (m.source_iri, HAS_XREF, xref) not in g:
                if not dry_run:
                    g.add((m.source_iri, HAS_XREF, xref))
                added_xrefs += 1
            if not g.value(m.source_iri, RDFS.label):
                if not dry_run:
                    g.add((m.source_iri, RDFS.label, Literal(m.target.label)))
                added_labels += 1
            if m.target.definition and not g.value(m.source_iri, IAO_DEF):
                if not dry_run:
                    g.add((m.source_iri, IAO_DEF, Literal(m.target.definition)))
                added_defs += 1

        if dry_run:
            print(f"[dry-run] would add {added_xrefs} xrefs, "
                  f"{added_labels} labels, {added_defs} defs")
            return {"added_xrefs": added_xrefs,
                    "added_labels": added_labels, "added_defs": added_defs}

        out_path.parent.mkdir(parents=True, exist_ok=True)
        g.serialize(str(out_path), format="xml")
        print(f"[Aligner.enrich] +{added_xrefs} xrefs, +{added_labels} labels, "
              f"+{added_defs} defs → {out_path}")
        return {"added_xrefs": added_xrefs,
                "added_labels": added_labels, "added_defs": added_defs}

    # ── output ─────────────────────────────────────────────────────────────────

    def write_candidates(self, result: AlignmentResult, out_path: Path) -> None:
        """Write top-K candidates CSV for manual inspection."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fields = ["source_iri", "source_label", "target_iri", "target_label",
                  "score", "method"]
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(result.candidates)
        print(f"[Aligner] Candidates → {out_path} ({len(result.candidates)} rows)")

    def write_sssom(self, result: AlignmentResult, out_path: Path) -> None:
        """Write best mappings in SSSOM TSV format."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            f.write("# SSSOM mapping set\n")
            f.write(f"# mapping_set_id: "
                    f"{result.source_owl.name}_x_{result.target_path.name}\n")
            f.write(f"# mapping_date: {date.today().isoformat()}\n")
            f.write(f"# mapping_tool: wound-ontology Aligner "
                    f"(method={result.method})\n#\n")
            w = csv.DictWriter(f, delimiter="\t", fieldnames=[
                "subject_id", "subject_label", "predicate_id",
                "object_id", "object_label",
                "confidence", "mapping_justification",
            ])
            w.writeheader()
            for m in result.mappings:
                pred = "skos:exactMatch" if m.score >= 1.0 else "skos:closeMatch"
                just = ("semapv:LexicalMatching" if m.method == "exact"
                        else "semapv:SemanticSimilarityThresholdMatching")
                w.writerow({
                    "subject_id":            str(m.source_iri),
                    "subject_label":         m.source_label,
                    "predicate_id":          pred,
                    "object_id":             m.target.iri,
                    "object_label":          m.target.label,
                    "confidence":            f"{m.score:.4f}",
                    "mapping_justification": just,
                })
        print(f"[Aligner] SSSOM → {out_path} ({len(result.mappings)} mappings)")
