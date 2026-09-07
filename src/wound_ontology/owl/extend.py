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
from functools import lru_cache
from pathlib import Path

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

from wound_ontology.utils.label_match import LabelIndex
from wound_ontology.utils.rdf_io import parse_graph

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


#: The BFO category a term is typed with is a closed vocabulary with an IRI
#: already declared for every member, so it must never go through label
#: matching. It did, and the matching quietly half-worked: the LabelIndex folds
#: punctuation and plurals but not CamelCase, so the one-word names hit
#: ("Process" -> BFO_0000015, "Quality" -> BFO_0000019) and every multi-word one
#: missed. `MaterialEntity` does not match the BFO label `material entity`, so
#: it was minted as a fresh WONT class carrying the "no BFO anchor" note -- and
#: so were InformationEntity, ImmaterialEntity, ProcessBoundary and
#: RealizableEntity. Measured on output/owl/wont_extended.ttl: 1770 classes hung
#: under those five roots (MaterialEntity alone had 1124 children), and each
#: root subclasses nothing, so none of them is reachable from BFO by a reasoner
#: or a query. Reading the category's own IRI removes the whole class of miss.
def _category_iris() -> dict[str, rdflib.URIRef]:
    from wound_ontology.llm.extraction_models import CATEGORY_IRI

    return {name.strip().lower(): rdflib.URIRef(iri)
            for name, iri in CATEGORY_IRI.items()}


CATEGORY_IRIS: dict[str, rdflib.URIRef] = _category_iris()

_ID_RE = re.compile(r"WONT_(\d+)$")


@dataclass
class ExtendReport:
    """What the merge did, and -- more usefully -- what it declined to do."""

    minted: dict[str, str] = field(default_factory=dict)
    resolved: dict[str, str] = field(default_factory=dict)
    resolved_imported: dict[str, str] = field(default_factory=dict)
    resolved_category: dict[str, str] = field(default_factory=dict)
    resolved_variant: dict[str, str] = field(default_factory=dict)
    ambiguous: dict[str, int] = field(default_factory=dict)
    #: IRI -> the distinct pipeline terms that all resolved to it. Matching folds
    #: punctuation and plurals, so two terms the hierarchy kept apart can land on
    #: one class here and their axioms are unioned. That is usually right
    #: ("wounds" and "Wound" are one class) and occasionally not: `Bacterial Load`
    #: was typed Quality and `Bacterial Loads` MaterialEntity, and folding them
    #: gave one class two disjoint BFO parents. Either way the merge happens at
    #: export, after every upstream review, so it is reported rather than left to
    #: be discovered in a reasoner run.
    folded: dict[str, list[str]] = field(default_factory=dict)
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
            f"resolved imported {len(self.resolved_imported)} terms to imported IRIs "
            f"(BFO/MILD/OBI... — not minted as WONT twins)",
            f"resolved category {len(self.resolved_category)} BFO category names to "
            f"their declared IRI (never label-matched)",
            f"matched on variant {len(self.resolved_variant)} terms (plural, "
            f"punctuation or a stated synonym)",
            f"ambiguous         {len(self.ambiguous)} terms matched >1 class and "
            f"were minted rather than guessed",
            f"folded            {len(self.folded)} class(es) claimed by >1 pipeline "
            f"term; their axioms are unioned",
            f"subClassOf added  {self.subclass_added}",
            f"restrictions      {rel or 'none'}",
            f"withheld          {len(self.withheld_existing)} (subject is a curated class)",
            f"skipped (no IRI)  {self.skipped_no_iri or 'none'}",
            f"triples           {self.triples_before} -> {self.triples_after}",
            f"catalog           {self.catalog or 'NOT WRITTEN - imports will not resolve'}",
        ]
        return "\n".join("  " + line for line in lines)


#: Predicates that state another surface form of the SAME class. Narrow, broad
#: and related synonyms are excluded on purpose: they name a *different*
#: concept, so matching through them would merge classes the source deliberately
#: kept apart -- worse than minting a duplicate.
SAME_CONCEPT_PREDICATES = (
    ALT_TERM,                                                          # IAO_0000118
    rdflib.URIRef("http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"),
    rdflib.URIRef("http://www.w3.org/2004/02/skos/core#altLabel"),
)


def label_index(graph: rdflib.Graph) -> LabelIndex:
    """Label -> IRI for one graph; preferred labels win over synonyms.

    Returns a :class:`LabelIndex`, which still behaves like the dict this used
    to be (``idx[key]``, ``.items()``, ``.values()``) but additionally matches
    through normalization and singularization -- so "material entities" finds
    BFO_0000040 instead of minting a WONT twin of it.
    """
    idx = LabelIndex()
    for pred in SAME_CONCEPT_PREDICATES:
        for subj, obj in graph.subject_objects(pred):
            if isinstance(subj, rdflib.URIRef):
                idx.add(str(obj), subj, preferred=False)
    for subj, obj in graph.subject_objects(RDFS.label):
        if isinstance(subj, rdflib.URIRef):
            idx.add(str(obj), subj, preferred=True)
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
    lexicon=None,
) -> ExtendReport:
    """Merge pipeline findings into a copy of the ground truth.

    Returns an :class:`ExtendReport`. The ground truth file itself is never
    written to -- ``output`` must be a different path.

    ``lexicon`` names files searched for labels the ground truth does not carry,
    defaulting to MILD plus the import modules. Without it every term whose IRI
    lives in an import is unresolvable here, and ``resolve`` mints a WONT twin
    for it: "Function" becomes a fresh WONT class rather than BFO_0000034, even
    though the output already ``owl:imports`` the module that defines it. That
    only started to bite once curated seed edges reached ``class_hier``, which
    is where BFO/MILD parents come from. Pass ``lexicon=()`` for the old
    mint-everything behaviour.
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

    # Labels the ground truth does not define, but its imports do. These are
    # looked up only on a miss, and an IRI found here is untouchable for the
    # same reason a curated WONT class is: an extraction run does not get to
    # add parents to BFO_0000040.
    if lexicon is None:
        lexicon = default_lexicon()
    imported_idx = lexicon_index(lexicon)

    # A category IRI belongs to BFO or MILD, so it is as untouchable as anything
    # else resolved out of an import: an extraction run does not get to hang an
    # axiom on BFO_0000040 itself.
    existing_iris.update(str(u) for u in CATEGORY_IRIS.values())

    #: str(IRI) -> the first term key that claimed it. See ExtendReport.folded.
    claims: dict[str, str] = {}

    def resolve(term: str) -> rdflib.URIRef:
        """Existing IRI for a label, or a freshly minted WONT class.

        Records which terms share an IRI on the way out: matching folds plurals
        and punctuation, so two terms the hierarchy kept apart end up as one
        class here, and every axiom on either becomes an axiom on both.
        """
        iri = _resolve(term)
        key = term.strip().lower()
        first = claims.setdefault(str(iri), key)
        if first != key:
            shared = report.folded.setdefault(str(iri), [first])
            if key not in shared:
                shared.append(key)
        return iri

    def _resolve(term: str) -> rdflib.URIRef:
        nonlocal counter
        key = term.strip().lower()
        declared = CATEGORY_IRIS.get(key)
        if declared is not None:
            # Declared, not matched. See CATEGORY_IRIS.
            report.resolved_category[term] = str(declared)
            return declared
        hit, how = idx.get(key)
        if hit is None and how != "ambiguous":
            imported, how = imported_idx.get(key)
            if imported is not None:
                idx.add(key, imported)             # remember for the next term
                existing_iris.add(str(imported))   # imports are not ours to edit
                report.resolved_imported[term] = str(imported)
                if how == "variant":
                    report.resolved_variant[term] = str(imported)
                return imported
        if how == "ambiguous":
            # Several classes answer to this label. Picking one attaches every
            # downstream axiom to a coin flip, so mint instead and say so.
            report.ambiguous[term] = report.ambiguous.get(term, 0) + 1
        elif hit is not None:
            # Only count it as resolved if it matched a class that was already in
            # the ground truth. Newly minted classes are added to the index too,
            # so without this check a term minted a moment ago would be reported
            # as having matched curated content.
            if str(hit) in existing_iris:
                report.resolved[term] = str(hit)
            if how == "variant":
                report.resolved_variant[term] = str(hit)
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
        idx.add(key, iri)
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


@lru_cache(maxsize=8)
def _lexicon_index_cached(key: tuple[tuple[str, float, int], ...]) -> LabelIndex:
    idx = LabelIndex()
    for path_str, _mtime, _size in key:
        # preferred=False so the FIRST file to claim a label keeps it. The list
        # is MILD then the modules alphabetically, which is arbitrary but fixed
        # -- 193 labels are claimed by two imports at once ("quality" by both
        # BFO and PATO, "skin" by FMA and UBERON), and a stable answer beats one
        # that depends on dict iteration order.
        idx.update(
            label_index(parse_graph(Path(path_str), context="lexicon")),
            preferred=False,
        )
    return idx


def lexicon_index(lexicon) -> LabelIndex:
    """Merged label index for `lexicon`, cached on (path, mtime, size).

    Parsing this costs ~12 s, almost all of it obi_module.owl at 16 MB, and the
    same files are read on every export and by every test that does not pass its
    own lexicon. The cache key carries mtime and size so editing a module still
    takes effect.
    """
    key = []
    for path in [Path(p) for p in lexicon]:
        if not path.exists():
            raise FileNotFoundError(
                f"lexicon file {path} does not exist. It is consulted so terms "
                f"defined in an import resolve to their real IRI instead of "
                f"being minted as a WONT duplicate; skipping it would show up "
                f"only as a larger 'minted' count."
            )
        st = path.stat()
        key.append((str(path), st.st_mtime, st.st_size))
    return _lexicon_index_cached(tuple(key))


def default_lexicon() -> list[Path]:
    """MILD + the import modules: everything the extended file already imports.

    Missing config or a missing modules directory yields an empty lexicon rather
    than an error -- callers that pass their own never touch this path.
    """
    import warnings

    try:
        from config.settings import MILD_TTL, MILD_MODULES_DIR
    except ImportError as exc:
        warnings.warn(
            f"config.settings could not be imported ({exc}), so the extend lexicon "
            "is empty. Every term defined in an import will be minted as a WONT "
            "duplicate instead of resolving to its own IRI.",
            RuntimeWarning, stacklevel=2,
        )
        return []
    mods = Path(MILD_MODULES_DIR)
    found = [Path(MILD_TTL)] if Path(MILD_TTL).exists() else []
    if mods.exists():
        found += sorted(mods.glob("*_module.owl")) + sorted(mods.glob("*_stub.owl"))
    if not found:
        warnings.warn(
            f"no lexicon files found (MILD_TTL={MILD_TTL}, "
            f"MILD_MODULES_DIR={MILD_MODULES_DIR}). Terms defined in an import "
            "will be minted as WONT duplicates rather than resolving to their "
            "own IRI; check the 'minted' count before trusting the output.",
            RuntimeWarning, stacklevel=2,
        )
    return found


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
