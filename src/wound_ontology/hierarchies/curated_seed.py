from __future__ import annotations
"""Curated seed edges, read out of the merged WONT and MILD ontologies.

These edges used to live in ``data/raw/predefined_concept_hierarchy.csv`` and
were loaded by ``Orchestrator.run_build_hierarchies``. That table has since been
merged into the ontologies themselves, so the CSV is gone -- but nothing took
over the job of feeding those edges back into ``ClassHierarchy``. The curated
tier of the ``curated > text > fca`` precedence was therefore empty on every
run: FCA could contradict a hand-authored WONT parent and no rank check fired,
because there was nothing at rank 3 to compare against.

This module reads the same information from its new home. It collects named
``rdfs:subClassOf`` edges -- both ends a URI carrying an ``rdfs:label`` -- and
returns them in the 'Class' / 'Parent class' shape ``apply_curated`` expects.

Labels are pooled across all sources before any edge is judged, so a WONT class
whose parent lives in MILD still resolves. Parents that live in an *import*
(BFO, COB, IAO, OBI...) carry no label in either file; `label_sources` names
files consulted for labels only. Nothing in them becomes a curated edge -- they
are a lexicon, not a source of subsumption.

What is deliberately NOT collected:

* anonymous superclasses (``owl:Restriction`` blank nodes). Those are relation
  axioms, not subsumption between named classes; they reach the store through
  extraction, not through the class hierarchy.
* classes marked ``owl:deprecated``.
* ``owl:Thing`` parents, which assert nothing.

Every one of those is counted and reported rather than dropped in silence, and
an empty result raises: "no curated edges" is exactly the degradation the old
FileNotFoundError guard existed to prevent.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd
import rdflib
from rdflib.namespace import OWL, RDF, RDFS

from wound_ontology.utils.rdf_io import parse_graph, sniff_format


@dataclass
class CuratedSeedReport:
    """What was read, and -- more usefully -- what was left behind."""

    per_source: dict[str, int] = field(default_factory=dict)
    recovered_labels: int = 0
    skipped_anonymous: int = 0
    skipped_unlabelled: int = 0
    skipped_deprecated: int = 0
    skipped_owl_thing: int = 0
    duplicates_dropped: int = 0
    unresolved_iris: list[str] = field(default_factory=list)

    @property
    def kept(self) -> int:
        return sum(self.per_source.values())

    def summary(self) -> str:
        per = ", ".join(f"{k}={v}" for k, v in sorted(self.per_source.items()))
        head = self.unresolved_iris[:5]
        lines = [
            f"curated edges      {self.kept} ({per or 'none'})",
            f"labels recovered   {self.recovered_labels} from label_sources",
            f"skipped anonymous  {self.skipped_anonymous} (owl:Restriction superclass)",
            f"skipped unlabelled {self.skipped_unlabelled}"
            + (f" -> {', '.join(head)}{' ...' if len(self.unresolved_iris) > 5 else ''}"
               if head else ""),
            f"skipped deprecated {self.skipped_deprecated}",
            f"skipped owl:Thing  {self.skipped_owl_thing}",
            f"duplicates         {self.duplicates_dropped}",
        ]
        return "\n".join("  " + line for line in lines)


# Format sniffing lives in utils.rdf_io: extend.py needs the same reader for the
# same reason, and a second copy would be one more place to get it wrong.
_sniff_format = sniff_format


def _parse(path: Path) -> rdflib.Graph:
    return parse_graph(path, context="curated seed source")


def _labels_for(wanted: set, label_sources: list[Path]) -> dict:
    """Labels for `wanted` IRIs, looked up across `label_sources`.

    Parsed lazily and only for IRIs still unresolved, because one of these
    files (obi_module.owl) is 16 MB and costs ~11 s to read.
    """
    found: dict = {}
    for path in label_sources:
        if not wanted:
            break
        if not path.exists():
            raise FileNotFoundError(
                f"label source {path} does not exist. It is consulted to name "
                f"the imported parents of curated edges; without it those edges "
                f"are dropped, which shows up only as a smaller hierarchy."
            )
        g = _parse(path)
        for subj, obj in g.subject_objects(RDFS.label):
            if subj in wanted:
                found[subj] = str(obj)
                wanted.discard(subj)
    return found


def load_curated_edges(
    sources: Iterable[Path | str],
    label_sources: Iterable[Path | str] = (),
    *,
    report: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, CuratedSeedReport]:
    """Named subsumption from `sources`, as a 'Class' / 'Parent class' frame.

    Raises FileNotFoundError for a missing source and RuntimeError when the
    combined result is empty -- both are the silent-degradation case the caller
    would otherwise see only as a smaller hierarchy.
    """
    sources = [Path(s) for s in sources]
    label_sources = [Path(s) for s in label_sources]
    missing = [str(s) for s in sources if not s.exists()]
    if missing:
        raise FileNotFoundError(
            f"curated seed source(s) do not exist: {', '.join(missing)}. These "
            f"carry the curated subsumption that outranks both text-asserted and "
            f"FCA-suggested edges; building without them silently produces a "
            f"different ontology. Fix the path, or pass predefined_df explicitly "
            f"(an empty DataFrame if you really intend no curated edges)."
        )

    rep = CuratedSeedReport()

    # Pass 1: pool labels and candidate edges across every source, so a WONT
    # class whose parent is defined in MILD is not mistaken for unlabelled.
    labels: dict = {}
    deprecated: set = set()
    edges: list[tuple[Path, rdflib.URIRef, rdflib.URIRef]] = []
    for src in sources:
        g = _parse(src)
        labels.update({s: str(o) for s, o in g.subject_objects(RDFS.label)})
        deprecated.update(g.subjects(OWL.deprecated, rdflib.Literal(True)))
        for child, parent in g.subject_objects(RDFS.subClassOf):
            if isinstance(parent, rdflib.BNode) or isinstance(child, rdflib.BNode):
                rep.skipped_anonymous += 1
                continue
            if parent == OWL.Thing:
                rep.skipped_owl_thing += 1
                continue
            edges.append((src, child, parent))
        rep.per_source.setdefault(src.name, 0)

    # Pass 2: name the imported parents, reading label_sources only for the
    # IRIs still missing.
    unresolved = {n for _, c, p in edges for n in (c, p) if n not in labels}
    if unresolved and label_sources:
        recovered = _labels_for(set(unresolved), label_sources)
        labels.update(recovered)
        rep.recovered_labels = len(recovered)

    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, str]] = []
    still_unresolved: set = set()
    for src, child, parent in edges:
        if child in deprecated or parent in deprecated:
            rep.skipped_deprecated += 1
            continue
        if child not in labels or parent not in labels:
            rep.skipped_unlabelled += 1
            still_unresolved.update(n for n in (child, parent) if n not in labels)
            continue
        key = (labels[child], labels[parent])
        if key in seen:
            rep.duplicates_dropped += 1
            continue
        seen.add(key)
        rows.append({"Class": key[0], "Parent class": key[1]})
        rep.per_source[src.name] += 1

    rep.unresolved_iris = sorted(str(n) for n in still_unresolved)

    if not rows:
        raise RuntimeError(
            f"no curated edges could be read from {', '.join(s.name for s in sources)}. "
            f"The files parsed, but yielded no named rdfs:subClassOf with labels on "
            f"both ends. Refusing to build a hierarchy whose curated tier is empty -- "
            f"FCA and text edges would then rank highest by default.\n{rep.summary()}"
        )

    df = pd.DataFrame(rows, columns=["Class", "Parent class"])
    return (df, rep) if report else df


def default_curated_sources() -> tuple[list[Path], list[Path]]:
    """``(sources, label_sources)``.

    Subsumption comes from WONT + MILD only. The import modules are extracted
    subsets of BFO/RO/OBI/ChEBI: folding their edges in would stamp thousands of
    imported classes as locally curated, so they are consulted for labels alone.
    """
    from config.settings import GROUND_TRUTH_TTL, MILD_TTL, MILD_MODULES_DIR
    mods = Path(MILD_MODULES_DIR)
    labels = sorted(mods.glob("*_module.owl")) + sorted(mods.glob("*_stub.owl")) \
        if mods.exists() else []
    return [Path(GROUND_TRUTH_TTL), Path(MILD_TTL)], labels


def module_ancestry(iris: Iterable[str], module_sources: Iterable[Path | str]) -> pd.DataFrame:
    """The import modules' named subsumption ABOVE the given classes only.

    2026-10-02: placements use module classes as parents (`planned process`,
    `1-D extent`); WONT/MILD alone leave those parentless, so the tree showed
    them at top level. Folding whole modules in would stamp thousands of
    imported classes as curated (see `default_curated_sources`), so this walks
    upward from the classes actually used and returns just those chains, as a
    'Class' / 'Parent class' frame.
    """
    g = rdflib.Graph()
    for path in module_sources:
        g += _parse(Path(path))
    labels = {s: str(o) for s, o in g.subject_objects(RDFS.label)}
    # The hierarchy is keyed by label, so a non-BFO class carrying a BFO label
    # IS that BFO node there. Its own parents would be read as BFO's: obi_module
    # states ChEBI `role` (CHEBI_50906) under PATO `quality`, and that came out
    # as `Role ⊑ Quality` (2026-10-03). BFO is the top ontology; its own
    # subsumption comes from `bfo_edges`, never through a namesake.
    bfo_labels = {str(o).lower() for s, o in g.subject_objects(RDFS.label) if str(s).startswith(BFO_NS)}
    namesakes = []
    rows, seen = [], set()
    stack = [rdflib.URIRef(i) for i in iris]
    visited = set()
    while stack:
        c = stack.pop()
        if c in visited:
            continue
        visited.add(c)
        if not str(c).startswith(BFO_NS) and labels.get(c, "").lower() in bfo_labels:
            namesakes.append((str(c), labels[c]))
            continue
        for p in g.objects(c, RDFS.subClassOf):
            if isinstance(p, rdflib.BNode) or p == OWL.Thing:
                continue
            if c in labels and p in labels and (labels[c], labels[p]) not in seen:
                seen.add((labels[c], labels[p]))
                rows.append({"Class": labels[c], "Parent class": labels[p]})
            stack.append(p)
    if namesakes:
        print(f"[curated_seed] module ancestry: {len(namesakes)} non-BFO class(es) carry a BFO label "
              f"and were not climbed (BFO's own edges stand for that node): {namesakes}")
    return pd.DataFrame(rows, columns=["Class", "Parent class"])


BFO_NS = "http://purl.obolibrary.org/obo/BFO_"


def bfo_edges(module_sources: Iterable[Path | str]) -> pd.DataFrame:
    """BFO's own subsumption, whole, plus the extraction categories that are not
    BFO labels, as a 'Class' / 'Parent class' frame (2026-10-03).

    BFO is the top ontology of WONT, and WONT, MILD and the modules become the
    extraction schema and the class hierarchy. Before this the hierarchy read
    subsumption from WONT + MILD only, which hold no BFO axiom, so `disposition`,
    `function`, `realizable entity` and `process boundary` had no parent and
    `role` had the wrong one. The modules carry all 36 BFO 2020 classes since
    the build seeds BFO core whole (build_disease_proposal.sh, FIX 4); this
    raises if they do not.

    The two extraction categories that are not BFO labels hang where their
    definition puts them: `information entity` (typed as BFO_0000031) under
    generically dependent continuant, `tendency` (MILD_120005) under realizable
    entity (CATEGORY_PARENT).
    """
    from wound_ontology.llm.extraction_models import CATEGORY_IRI, CATEGORY_PARENT
    g = rdflib.Graph()
    for path in module_sources:
        g += _parse(Path(path))
    label = {}
    for s, o in g.subject_objects(RDFS.label):
        if str(s).startswith(BFO_NS) and getattr(o, "language", None) in (None, "en"):
            label.setdefault(s, str(o))
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if str(s).startswith(BFO_NS)}
    if len(classes) < 36 or classes - set(label):
        raise RuntimeError(
            f"the import modules hold {len(classes)} BFO class(es), {len(classes - set(label))} unlabelled; "
            f"BFO 2020 core has 36. Rebuild the modules (build_disease_proposal.sh seeds BFO core whole).")
    rows = []
    for c in sorted(classes):
        for p in g.objects(c, RDFS.subClassOf):
            if isinstance(p, rdflib.URIRef) and str(p).startswith(BFO_NS):
                rows.append({"Class": label[c], "Parent class": label[p]})
    by_iri = {str(k): v for k, v in label.items()}
    names = {v.lower() for v in label.values()}
    for cat, iri in CATEGORY_IRI.items():
        if cat in names:
            continue
        if iri in by_iri:                       # a category named apart from the BFO class it is
            rows.append({"Class": cat, "Parent class": by_iri[iri]})
        elif CATEGORY_PARENT.get(cat):
            rows.append({"Class": cat, "Parent class": CATEGORY_PARENT[cat]})
    return pd.DataFrame(rows, columns=["Class", "Parent class"]).drop_duplicates()
