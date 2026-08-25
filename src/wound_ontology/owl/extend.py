"""Extend the WONT ground truth with pipeline findings.

Why this exists
---------------
``Orchestrator.export_to_owl`` builds a *separate* ontology from an empty
``OWLOntology.create()``. Nothing in the pipeline ever read
``ground_truth_final.owl`` as a base or merged back into it, so the output was a
parallel artifact rather than "WONT plus what the abstracts taught us".

This module does the merge, in rdflib rather than owlready2 for a concrete
reason: the ground truth is Turtle carrying a ``.owl`` extension, and owlready2
refuses it outright (``OwlReadyOntologyParsingError``).

The ground truth is ground truth
--------------------------------
By default this only asserts axioms whose **subject is a newly minted class**.
An extraction run cannot add a parent to a curated WONT class, cannot restate
one, and cannot contradict one -- those edges are counted and reported instead
of applied. Pass ``touch_existing=True`` to lift that, deliberately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

WONT_NS = "https://bioportal.bioontology.org/ontologies/WONT/"
OBO = "http://purl.obolibrary.org/obo/"
PROVENANCE = rdflib.URIRef("http://www.geneontology.org/formats/oboInOwl#source")
ALT_TERM = rdflib.URIRef(OBO + "IAO_0000118")
DEFINITION = rdflib.URIRef(OBO + "IAO_0000115")
EDITOR_NOTE = rdflib.URIRef(OBO + "IAO_0000116")

#: Surface predicate -> OBO/MILD property IRI. Anything absent is not
#: exportable: ``affects`` has no IRI, ``caused_by`` is refused by MILD
#: commitment 4.
#:
#: This used to be four hand-written entries, which was the legacy extractor's
#: whole vocabulary. Two-stage extraction emits 26 relation types, so 24 of them
#: -- inheres_in, has_part, has_participant, realizes, has_output,
#: has_disposition, is_specified_output_of, the entire BFO backbone MILD is
#: built on -- were counted into ``skipped_no_iri`` and never reached OWL. The
#: table is now derived from the extractor's own RELATION_IRI so the two cannot
#: drift apart; test_export_vocabulary_covers_the_extractor pins that.
#:
#: ``occurs_in`` and ``is_treatment_for`` are kept on top as legacy entries: no
#: RelationType produces them, but stores written before two-stage extraction
#: are full of them and must still export.
def _exportable_relations() -> dict[str, str]:
    from wound_ontology.llm.extraction_adapter import normalize_predicate
    from wound_ontology.llm.extraction_models import RELATION_IRI

    table = {normalize_predicate(label): iri for label, iri in RELATION_IRI.items()}
    table.setdefault("occurs_in", OBO + "BFO_0000066")        # legacy stores only
    table.setdefault("is_treatment_for", OBO + "RO_0002606")  # legacy stores only
    return table


RELATION_IRIS: dict[str, str] = _exportable_relations()

_ID_RE = re.compile(r"WONT_(\d+)$")


@dataclass
class ExtendReport:
    """What the merge did, and -- more usefully -- what it declined to do."""

    minted: dict[str, str] = field(default_factory=dict)
    resolved: dict[str, str] = field(default_factory=dict)
    subclass_added: int = 0
    restrictions_added: dict[str, int] = field(default_factory=dict)
    withheld_existing: list[tuple[str, str, str]] = field(default_factory=list)
    skipped_no_iri: dict[str, int] = field(default_factory=dict)
    triples_before: int = 0
    triples_after: int = 0
    catalog: str | None = None

    def summary(self) -> str:
        rel = ", ".join(f"{k}={v}" for k, v in sorted(self.restrictions_added.items()))
        lines = [
            f"minted            {len(self.minted)} new WONT classes",
            f"resolved          {len(self.resolved)} terms to curated WONT classes",
            f"subClassOf added  {self.subclass_added}",
            f"restrictions      {rel or 'none'}",
            f"withheld          {len(self.withheld_existing)} (subject is a curated class)",
            f"skipped (no IRI)  {self.skipped_no_iri or 'none'}",
            f"triples           {self.triples_before} -> {self.triples_after}",
            f"catalog           {self.catalog or 'NOT WRITTEN - imports will not resolve'}",
        ]
        return "\n".join("  " + line for line in lines)


def label_index(graph: rdflib.Graph) -> dict[str, rdflib.URIRef]:
    """``{lowercased label: IRI}``; preferred labels win over alternative terms."""
    idx: dict[str, rdflib.URIRef] = {}
    for subj, _, obj in graph.triples((None, ALT_TERM, None)):
        if isinstance(subj, rdflib.URIRef):
            idx.setdefault(str(obj).strip().lower(), subj)
    for subj, _, obj in graph.triples((None, RDFS.label, None)):
        if isinstance(subj, rdflib.URIRef):
            idx[str(obj).strip().lower()] = subj
    return idx


#: WONT uses two id series: a main one (currently up to 474) and a MILD-mirroring
#: 1200xx block. Minting past the global maximum would jump the main series to
#: 120085 and abandon 475-119999, so only ids below this ceiling are considered.
SERIES_CEILING = 100000


def existing_ids(graph: rdflib.Graph, namespace: str = WONT_NS) -> set[int]:
    """Every WONT numeric id in use, both series."""
    out: set[int] = set()
    for subj in set(graph.subjects()):
        if not isinstance(subj, rdflib.URIRef) or not str(subj).startswith(namespace):
            continue
        m = _ID_RE.search(str(subj))
        if m:
            out.add(int(m.group(1)))
    return out


def next_free_id(graph: rdflib.Graph, namespace: str = WONT_NS,
                 series_ceiling: int = SERIES_CEILING) -> int:
    """One past the highest WONT id in the main series."""
    ids = {i for i in existing_ids(graph, namespace) if i < series_ceiling}
    return (max(ids) + 1) if ids else 1


def _iter_store_relations(store):
    """(subject, predicate, object) for every confidently asserted store edge."""
    for record in getattr(store, "dict", {}).values():
        for subject, attrs in record.get("entities", {}).items():
            for attr, conf in attrs.items():
                if conf != 1.0 or ":" not in attr:
                    continue
                pred, target = (x.strip() for x in attr.split(":", 1))
                if pred == "is_a" or not target:
                    continue
                yield subject.strip(), pred, target


def _hierarchy_edges(hier):
    """(child, parent) pairs asserted in a BaseHierarchy dataframe."""
    if hier is None or getattr(hier, "df", None) is None or hier.df.empty:
        return
    for child in hier.df.index:
        for parent in hier.df.columns:
            if hier.df.at[child, parent] == 1.0 and child != parent:
                yield str(child).strip(), str(parent).strip()


def extend_ground_truth(
    ground_truth: str | Path,
    output: str | Path,
    class_hier=None,
    mere_hier=None,
    store=None,
    fca_hier=None,
    namespace: str = WONT_NS,
    id_width: int = 7,
    touch_existing: bool = False,
    provenance: str = "wound-ontology-pipeline",
) -> ExtendReport:
    """Merge pipeline findings into a copy of the ground truth.

    Returns an :class:`ExtendReport`. The ground truth file itself is never
    written to -- ``output`` must be a different path.
    """
    ground_truth, output = Path(ground_truth), Path(output)
    if ground_truth.resolve() == output.resolve():
        raise ValueError(
            "refusing to overwrite the ground truth in place; choose another output path"
        )

    g = rdflib.Graph()
    g.parse(str(ground_truth), format="turtle")
    report = ExtendReport(triples_before=len(g))

    idx = label_index(g)
    existing_iris = {str(v) for v in idx.values()}
    taken = existing_ids(g, namespace)
    counter = next_free_id(g, namespace)

    def resolve(term: str) -> rdflib.URIRef:
        """Existing IRI for a label, or a freshly minted WONT class."""
        nonlocal counter
        key = term.strip().lower()
        hit = idx.get(key)
        if hit is not None:
            # Only count it as resolved if it matched a class that was already in
            # the ground truth. Newly minted classes are added to the index too,
            # so without this check a term minted a moment ago would be reported
            # as having matched curated content.
            if str(hit) in existing_iris:
                report.resolved[term] = str(hit)
            return hit
        while counter in taken:      # never reuse an id from either series
            counter += 1
        iri = rdflib.URIRef(f"{namespace}WONT_{counter:0{id_width}d}")
        taken.add(counter)
        counter += 1
        g.add((iri, RDF.type, OWL.Class))
        g.add((iri, RDFS.label, rdflib.Literal(term, lang="en")))
        g.add((iri, PROVENANCE, rdflib.Literal(provenance)))
        g.add((iri, EDITOR_NOTE, rdflib.Literal(
            "Minted by the extraction pipeline, not curated. It carries a label and "
            "whatever relations the text supported; it has no BFO anchor until one is "
            "assigned, so it is not yet usable as ground truth.", lang="en")))
        idx[key] = iri
        report.minted[term] = str(iri)
        return iri

    def may_assert(subject_iri: rdflib.URIRef) -> bool:
        return touch_existing or str(subject_iri) not in existing_iris

    # ---- taxonomy -----------------------------------------------------------
    for child, parent in _hierarchy_edges(class_hier):
        c_iri, p_iri = resolve(child), resolve(parent)
        if not may_assert(c_iri):
            report.withheld_existing.append((child, "is_a", parent))
            continue
        if (c_iri, RDFS.subClassOf, p_iri) not in g:
            g.add((c_iri, RDFS.subClassOf, p_iri))
            report.subclass_added += 1

    # ---- mereology and the remaining relations ------------------------------
    def add_restriction(subject: str, pred: str, target: str) -> None:
        iri = RELATION_IRIS.get(pred)
        if iri is None:
            report.skipped_no_iri[pred] = report.skipped_no_iri.get(pred, 0) + 1
            return
        s_iri, t_iri = resolve(subject), resolve(target)
        if not may_assert(s_iri):
            report.withheld_existing.append((subject, pred, target))
            return
        prop = rdflib.URIRef(iri)
        for existing in g.objects(s_iri, RDFS.subClassOf):
            if (isinstance(existing, rdflib.BNode)
                    and g.value(existing, OWL.onProperty) == prop
                    and g.value(existing, OWL.someValuesFrom) == t_iri):
                return
        node = rdflib.BNode()
        g.add((node, RDF.type, OWL.Restriction))
        g.add((node, OWL.onProperty, prop))
        g.add((node, OWL.someValuesFrom, t_iri))
        g.add((s_iri, RDFS.subClassOf, node))
        report.restrictions_added[pred] = report.restrictions_added.get(pred, 0) + 1

    for branch, root in _hierarchy_edges(mere_hier):
        add_restriction(branch, "part_of", root)
    if store is not None:
        for subject, pred, target in _iter_store_relations(store):
            add_restriction(subject, pred, target)
    for child, parent in _hierarchy_edges(fca_hier):
        c_iri, p_iri = resolve(child), resolve(parent)
        if not may_assert(c_iri):
            report.withheld_existing.append((child, "is_a(fca)", parent))
            continue
        if (c_iri, RDFS.subClassOf, p_iri) not in g:
            g.add((c_iri, RDFS.subClassOf, p_iri))
            report.subclass_added += 1

    report.triples_after = len(g)
    output.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(output), format="turtle")
    report.catalog = _copy_catalog(ground_truth, output)
    return report


def _copy_catalog(ground_truth: Path, output: Path) -> str | None:
    """Put the ground truth's catalog beside the output.

    The extended file inherits ``owl:imports <.../MILD>`` and the twelve module
    imports. Those resolve through ``catalog-v001.xml``, which lives next to the
    ground truth. Without a catalog in the output directory ROBOT tries the web
    and BioPortal answers 403, so the artifact cannot be reasoned over at all.
    """
    src = ground_truth.parent / "catalog-v001.xml"
    if not src.exists():
        return None
    dest = output.parent / "catalog-v001.xml"
    if dest.resolve() == src.resolve():
        return str(dest)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return str(dest)
