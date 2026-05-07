"""
ABox
====
Algorithmically generates a large ABox (1 k – 10 k+ flap individuals) covering
the complete variety expressible by an OFL TBox.

Key concept — rdflib.Graph
--------------------------
An rdflib ``Graph`` is an in-memory set of RDF triples.  Every triple has the
form (subject, predicate, object), where each element is one of:

  * ``URIRef``  — a full IRI, e.g. ``URIRef("http://example.org/Flap")``.
    This is what OWL class IRIs, property IRIs, and individual IRIs look like
    in code.  Namespaces (``OFL``, ``OBO``, …) are just shorthand factories:
    ``OFL.OFLID10002`` is the same as
    ``URIRef("https://purl.bioontology.org/ontology/OFL/OFLID10002")``.

  * ``BNode``  — a blank node (anonymous resource with no global IRI).
    OWL uses blank nodes internally for class expressions such as restrictions
    (``someValuesFrom``, ``intersectionOf``, …).  We only encounter BNodes
    when parsing the TBox; we never create them in the ABox.

  * ``Literal`` — a typed data value such as a string label or a number.

Adding a triple to the graph::

    output_graph.add((subject_iri, predicate_iri, object_iri))
    # e.g.
    output_graph.add((flap_id, RDF.type, OWL.NamedIndividual))

Querying::

    list(tbox_graph.objects(subject, predicate))   # all objects for subject+property
    list(tbox_graph.subjects(predicate, object))   # inverse
    tbox_graph.value(subject, predicate)           # single object (None if absent)

Serialising to RDF/XML (the .owl format Protégé understands)::

    output_graph.serialize(destination="out.owl", format="xml")

Architecture
------------
* ``TBox`` for loading the TBox and resolving labels/IRIs via SPARQL.
* Only **leaf classes under OFLID10098** ("Flaps classified by region of
  origin") are instantiated — classification axes (Mathes & Nahai, blood
  supply, etc.) are intentionally excluded.

BFO/OBI/RO alignment
---------------------
Every generated ABox imports BFO, OBI, and RO so the OWL RL reasoner can
close over the full property hierarchy.  The individual structure follows the
reference template ``flap_onto_corrected_and_inferred_22.owl``:

  FlapHarvestProcess has_specified_output Flap
  Flap              is_specified_output_of FlapHarvestProcess
  CompleteFlapOp    has_part  FlapHarvestProcess + FlapTransferProcess
  CompleteFlapOp    has_participant  Flap, Patient
  ConcretizedPlan   concretizes  SurgeryPlan
  Pedicle           has_function  BloodSupplyFunction

A plan (BFO:0000031 / OFLID10507) is *not* a process; it is an information
content entity.  The flap therefore has *no* direct connection to the plan —
that relation goes through the process.

Usage (fluent API)
------------------
    from wound_ontology.tbox_abox_reasoner.for_owl.tbox import TBox
    from wound_ontology.tbox_abox_reasoner.for_rdflib.abox import ABox

    tbox = TBox().load("flap_onto.owl")
    gen = ABox(tbox)
    gen.generate(patients_per_combination=5)
    gen.save("ofl_abox_5k.owl")

Or one-shot::

    ABox.run_files("flap_onto.owl", "ofl_abox_5k.owl", patients=5)
"""
from __future__ import annotations

import random
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wound_ontology.tbox_abox_reasoner.for_rdflib.sparql.sparql_helper import SPARQLHelper

# rdflib core types:
#   Graph   — the triple store (our in-memory OWL file)
#   URIRef  — a node identified by a full IRI string
#   BNode   — a blank (anonymous) node, appears in TBox class expressions
#   Literal — a plain or typed data value (used here for rdfs:label strings)
from rdflib import Graph, URIRef, BNode, Literal
# Standard RDF/OWL vocabulary terms used as predicates and types
from rdflib.namespace import RDF, RDFS, OWL

# ofl_constants.py lives in the Flap ontology project; add it to the path so
# we can import it without installing it as a package.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'Flap ontology' / 'VS Code output'))
from ofl_constants import (
    OFL, OBO, FMA, DCTERMS,          # Namespace objects (IRI prefix factories)
    HAS_PART, PART_OF, HAS_ORIGIN,    # OFL object properties
    HAS_PARTICIPANT, CONCRETIZES, HAS_FUNCTION, HAS_QUALITY, HAS_ROLE, IS_OUTPUT_OF,
    HAS_SPECIFIED_OUTPUT, HAS_SPECIFIED_INPUT, REALIZES,
    EXISTENCE_STARTS_AT_END_OF, EXISTENCE_STARTS_DURING,
    PARTICIPATES_IN, HAS_TARGET_START_LOCATION, HAS_TARGET_END_LOCATION,
    MOD_NO, MOD_YES,                  # Modification class IRIs
    LEAF_SURVIVAL, MAIN_SURVIVAL,     # Survival outcome class IRI lists
    LOCAL_FLAP, REGIONAL_FLAP, DISTANT_FLAP,   # Transfer distance class IRIs
    FREE_TRANSFER, PEDICLED_TRANSFER,           # Transfer type class IRIs
    FLAP_HARVEST_PROCESS, COMPLETE_OPERATION, FLAP_SURGERY_PLAN,
    CONC_PLAN_TYPE, PATIENT_TYPE, VOL_TYPE, MASS_TYPE,
    ROLE_TYPE, MOTOR_FUNC_ROLE_TYPE, TISSUE_LOSS_ROLE_TYPE, FUNC_TYPE,
    SUBDIVISION_CARDINAL_BODY, ANATOMICAL_ENT_TYPE,
    PERFORATOR_VESSEL_OF, PERFORATOR_VESSEL_CLS, SEGMENT_ARTERIAL_TREE, SEGMENT_VENOUS_TREE,
)
try:
    from config.settings import BFO_OWL_URL as _BFO_URL, RO_OWL_URL as _RO_URL, OBI_OWL_URL as _OBI_URL
except ImportError:
    _BFO_URL = "http://purl.obolibrary.org/obo/bfo.owl"
    _RO_URL  = "http://purl.obolibrary.org/obo/ro.owl"
    _OBI_URL = "http://purl.obolibrary.org/obo/obi.owl"



def _load_query(path: Path) -> str:
    """Read a .sparql file and return its text."""
    return path.read_text(encoding="utf-8")


def _fill(template: str, **substitutions: str) -> str:
    """Replace {placeholder} markers in a SPARQL template without touching SPARQL { } braces."""
    for key, value in substitutions.items():
        template = template.replace("{" + key + "}", value)
    return template


class _IDCounter:
    """
    Generates unique OFL IRIs for ABox individuals by incrementing a counter.

    TBox IRIs run from OFLID10000 upward; we start at OFLID0020000 (default)
    so there is no collision with existing TBox classes.

    Example: counter.next() → URIRef("…/OFL/OFLID0020000"), then OFLID0020001, …
    """

    def __init__(self, start: int = 20_000):
        self._n = start

    def next(self) -> URIRef:
        # :07d zero-pads the number to 7 digits, matching the OFL IRI convention
        iri = OFL[f"OFLID{self._n:07d}"]
        self._n += 1
        return iri

    @property
    def current(self) -> int:
        return self._n


class ABox:
    """
    Generates synthetic OWL ABox individuals for OFL-based TBoxes.

    Parameters
    ----------
    tbox : TBox
        The loaded TBox (used for SPARQL-based TBox extraction).
    id_start : int
        First IRI counter value (default 20 000 to avoid TBox collisions).
    """

    def __init__(self, tbox, id_start: int = 20_000):
        self._tbox         = tbox
        self._id_start     = id_start
        self._output_graph: Graph = Graph()

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate(
        self,
        patients_per_combination: int = 1,
        seed: int = 42,
    ) -> "ABox":
        """Build the ABox graph in memory."""
        random.seed(seed)
        tbox_info = self._extract_tbox_info()

        # ── Create the output Graph and declare namespace prefixes ─────────────
        # A Graph is just a set of (subject, predicate, object) triples.
        # Binding prefixes only affects serialisation (makes IRIs shorter in the
        # saved .owl file); it has no effect on the data itself.
        output_graph = Graph()
        output_graph.bind("ofl",     OFL)
        output_graph.bind("obo",     OBO)
        output_graph.bind("fma",     FMA)
        output_graph.bind("rdfs",    RDFS)
        output_graph.bind("owl",     OWL)
        output_graph.bind("dcterms", DCTERMS)

        # ── Declare this graph as an OWL Ontology and list its imports ─────────
        # owl:imports tells reasoners to load the TBox and foundational
        # ontologies (BFO, RO, OBI) so property hierarchies are available.
        ontology_iri = URIRef("https://purl.bioontology.org/ontology/OFL/abox")
        output_graph.add((ontology_iri, RDF.type,    OWL.Ontology))
        output_graph.add((ontology_iri, OWL.imports, URIRef("https://purl.bioontology.org/ontology/OFL")))
        output_graph.add((ontology_iri, OWL.imports, URIRef(_BFO_URL)))
        output_graph.add((ontology_iri, OWL.imports, URIRef(_RO_URL)))
        output_graph.add((ontology_iri, OWL.imports, URIRef(_OBI_URL)))

        self._output_graph = output_graph
        counter = _IDCounter(self._id_start)

        parts_map   = tbox_info["parts_map"]    # flap IRI → {label, [part IRIs]}
        origin_map     = tbox_info["origin_map"]     # flap IRI → anatomical origin IRI
        pedicle_map    = tbox_info["pedicle_map"]    # label fragment → {iri, [vessel IRIs]}
        perforator_set = tbox_info["perforator_set"] # set of flap IRIs with perforator axiom
        all_named      = tbox_info["all_named"]      # [(flap IRI, label)] — all origin leaves
        rich_flap_iris = set(parts_map)              # flaps that have explicit hasPart data

        flap_count = 0
        patient_n  = 1

        # ── Phase 1: rich instances ────────────────────────────────────────────
        # Flaps for which the TBox declares explicit anatomical parts (hasPart
        # restrictions) are the "rich" set.  We iterate every combination of
        # side × survival outcome × preharvest modification.
        for flap_iri, flap_info in parts_map.items():
            flap_label      = flap_info["label"]
            part_iris       = flap_info["parts"]          # list of FMA part IRIs
            origin_class    = origin_map.get(flap_iri)   # anatomical origin class IRI or None
            pedicle_info    = pedicle_map.get(flap_label.lower(), {})
            transfer_cls    = _infer_transfer(flap_label)
            distance_cls    = _infer_distance(flap_label, transfer_cls)
            is_perforator   = flap_iri in perforator_set

            for side in ("left", "right"):
                for survival_cls in LEAF_SURVIVAL:
                    for modification_cls in (MOD_NO, MOD_YES):
                        for _ in range(patients_per_combination):
                            self._add_instance(
                                output_graph, counter, patient_n,
                                flap_iri, flap_label, part_iris, origin_class,
                                pedicle_cls=pedicle_info.get("iri"),
                                pedicle_vessels=pedicle_info.get("vessels", []),
                                survival_cls=survival_cls, modification_cls=modification_cls,
                                transfer_cls=transfer_cls, distance_cls=distance_cls, side=side,
                                is_perforator=is_perforator,
                            )
                    flap_count += 1
                    patient_n  += 1

        # ── Phase 2: typed-only instances ──────────────────────────────────────
        # Origin leaves without explicit hasPart data get a smaller combination
        # (no modification axis, only main survival outcomes).
        for flap_iri, flap_label in all_named:
            if flap_iri in rich_flap_iris:
                continue   # already handled in Phase 1
            origin_class  = origin_map.get(flap_iri)
            transfer_cls  = _infer_transfer(flap_label)
            distance_cls  = _infer_distance(flap_label, transfer_cls)
            is_perforator = flap_iri in perforator_set

            for side in ("left", "right"):
                for survival_cls in MAIN_SURVIVAL:
                    for _ in range(patients_per_combination):
                        self._add_instance(
                            output_graph, counter, patient_n,
                            flap_iri, flap_label, [], origin_class,
                            pedicle_cls=None, pedicle_vessels=[],
                            survival_cls=survival_cls, modification_cls=MOD_NO,
                            transfer_cls=transfer_cls, distance_cls=distance_cls, side=side,
                            is_perforator=is_perforator,
                        )
                    flap_count += 1
                    patient_n  += 1

        # Count NamedIndividuals by querying the graph for all subjects that
        # have rdf:type owl:NamedIndividual
        n_declares = sum(
            1 for _ in output_graph.subjects(RDF.type, OWL.NamedIndividual)
        )
        print(
            f"[ABox] {flap_count:,} flap instances, "
            f"{n_declares:,} individuals, {len(output_graph):,} triples"
        )
        return self

    def save(self, output_file: str) -> None:
        """Serialize the ABox as RDF/XML."""
        self._output_graph.serialize(destination=output_file, format="xml")

    @classmethod
    def run_files(
        cls,
        tbox_file: str,
        output_file: str,
        patients: int = 1,
        seed: int = 42,
        id_start: int = 20_000,
    ) -> "ABox":
        """
        Convenience one-shot class method::

            ABox.run_files("tbox.owl", "abox.owl", patients=5)
        """
        from wound_ontology.tbox_abox_reasoner.for_owl.tbox import TBox
        tbox = TBox().load(tbox_file)
        abox = cls(tbox, id_start=id_start)
        abox.generate(patients_per_combination=patients, seed=seed)
        abox.save(output_file)
        return abox

    @classmethod
    def from_owl(cls, owl_file: str) -> "ABox":
        """Load an existing OWL/RDF-XML file for inspection without generating individuals."""
        graph = Graph()
        graph.parse(str(Path(owl_file).resolve()), format="xml")
        instance = cls.__new__(cls)
        instance._tbox         = None
        instance._id_start     = 20_000
        instance._output_graph = graph
        return instance

    # ── Graph inspection ───────────────────────────────────────────────────────

    def filter_by_namespace(self, prefix: str) -> "ABox":
        """Return a new ABox containing only triples whose subject IRI starts with prefix."""
        filtered = Graph()
        for s, p, o in self._output_graph:
            if isinstance(s, URIRef) and str(s).startswith(prefix):
                filtered.add((s, p, o))
        return self._wrap_graph(filtered)

    def subgraph(self, root_label: str) -> "ABox":
        """Return a new ABox with only triples reachable via rdfs:subClassOf* from root_label."""
        query_text = _fill(
            _load_query(self._SPARQL_DIR / "subgraph_by_label.sparql"),
            root_label=root_label,
        )
        rows = self._output_graph.query(query_text)
        kept = {str(row.node) for row in rows}
        if not kept:
            print(f"[ABox] subgraph: no node matching '{root_label}'")
            return self._wrap_graph(Graph())
        filtered = Graph()
        for s, p, o in self._output_graph:
            if str(s) in kept:
                filtered.add((s, p, o))
        return self._wrap_graph(filtered)

    def stats(self) -> dict:
        """Triple count and rdf:type distribution of the graph."""
        type_counts: dict[str, int] = {}
        for _, _, rdf_type in self._output_graph.triples((None, RDF.type, None)):
            key = str(rdf_type).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
            type_counts[key] = type_counts.get(key, 0) + 1
        return {"triples": len(self._output_graph), "type_counts": type_counts}

    def find(self, label: str) -> list[tuple[str, str]]:
        """Return all (iri, label) pairs whose rdfs:label contains the search string (case-insensitive)."""
        lower = label.lower()
        return [
            (str(s), str(o))
            for s, _, o in self._output_graph.triples((None, RDFS.label, None))
            if lower in str(o).lower()
        ]

    def neighbours(self, iri: str) -> dict:
        """All outgoing (predicate, object) and incoming (predicate, subject) pairs for a given IRI."""
        node = URIRef(iri)
        return {
            "outgoing": [(str(p), str(o)) for p, o in self._output_graph.predicate_objects(node)],
            "incoming": [(str(p), str(s)) for s, p in self._output_graph.subject_predicates(node)],
        }

    def print_stats(self) -> None:
        s = self.stats()
        print(f"[ABox] {s['triples']:,} triples")
        for t, count in sorted(s["type_counts"].items(), key=lambda x: -x[1])[:10]:
            print(f"  {t}: {count:,}")

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def graph(self) -> Graph:
        """The generated rdflib.Graph (available after generate() or from_owl())."""
        return self._output_graph

    @property
    def sparql(self) -> SPARQLHelper:
        """SPARQLHelper bound to this graph for named SPARQL queries."""
        from wound_ontology.tbox_abox_reasoner.for_rdflib.sparql.sparql_helper import SPARQLHelper
        return SPARQLHelper(self._output_graph)

    def _wrap_graph(self, graph: Graph) -> "ABox":
        """Create a new ABox shell wrapping an existing graph (used by filter/subgraph)."""
        instance = ABox.__new__(ABox)
        instance._tbox         = self._tbox
        instance._id_start     = self._id_start
        instance._output_graph = graph
        return instance

    # ── TBox extraction ────────────────────────────────────────────────────────

    # Path to the directory holding the .sparql query files
    _SPARQL_DIR = Path(__file__).parent / "sparql"

    def _extract_tbox_info(self) -> dict:
        """
        Query the TBox graph with SPARQL to collect metadata needed for ABox
        generation.  Only leaf classes under ORIGIN_ROOT are returned, so
        classification axes (Mathes & Nahai, blood supply, etc.) are never
        instantiated.

        Returns a dict with four keys:
          parts_map   — {flap_iri: {"label": str, "parts": [fma_iri, ...]}}
          origin_map  — {flap_iri: origin_class_iri}
          pedicle_map — {label_fragment: {"iri": str, "vessels": [...]}}
          all_named   — [(flap_iri, label), ...] for all origin-leaf classes
        """
        # rdf_graph is the TBox as an rdflib Graph (not the owlready2 object)
        tbox_graph = self._tbox.rdf_graph

        def _q(filename: str) -> str:
            return _load_query(self._SPARQL_DIR / filename)

        # ── Query 1: flaps with explicit hasPart restrictions ──────────────────
        # Finds leaf flap classes that carry a hasPart (OFLID13296) restriction
        # in either a direct subClassOf or inside an equivalentClass intersection.
        # The restriction filler (?partBN) may be a named class or a blank node
        # (anonymous union/intersection), which _resolve_filler() unpacks below.
        parts_map: dict[str, dict] = {}
        for sparql_row in tbox_graph.query(_q("flaps_with_parts.sparql")):
            flap_class_iri   = str(sparql_row.flap)
            flap_class_label = str(sparql_row.flapLabel)
            # Unpack the restriction filler: may be a single named class IRI
            # or a blank node encoding a union/intersection of classes
            named_part_iris = [
                str(part_iri) for part_iri in
                _resolve_filler(tbox_graph, sparql_row.partBN)
                if isinstance(part_iri, URIRef)
            ]
            if flap_class_iri not in parts_map:
                parts_map[flap_class_iri] = {"label": flap_class_label, "parts": []}
            parts_map[flap_class_iri]["parts"].extend(
                part for part in named_part_iris
                if part not in parts_map[flap_class_iri]["parts"]
            )

        # ── Query 2: anatomical origin class for each flap ─────────────────────
        # All members of "Flaps classified by region of origin" carry a
        # hasOrigin (OFLID12003) restriction that names an anatomical region.
        origin_map: dict[str, str] = {}
        for sparql_row in tbox_graph.query(_q("flap_origin_classes.sparql")):
            origin_map[str(sparql_row.flap)] = str(sparql_row.origin)

        # ── Query 3: pedicle classes and their vessels ─────────────────────────
        # Pedicle classes are identified by their label containing "pedicle of the".
        # We strip that prefix to get a label fragment (e.g. "anterolateral thigh
        # flap") that can be matched against flap labels later.
        pedicle_map: dict[str, dict] = {}
        for sparql_row in tbox_graph.query(_q("pedicle_vessels.sparql")):
            label_fragment = (
                str(sparql_row.pedLabel)
                .lower()
                .replace("flap pedicle of the ", "")
                .strip()
            )
            if label_fragment not in pedicle_map:
                pedicle_map[label_fragment] = {"iri": str(sparql_row.ped), "vessels": []}
            if sparql_row.vessel:
                vessel_iri_str = str(sparql_row.vessel)
                if vessel_iri_str not in pedicle_map[label_fragment]["vessels"]:
                    pedicle_map[label_fragment]["vessels"].append(vessel_iri_str)

        # ── Query 4: all origin-leaf flap classes ──────────────────────────────
        # A leaf class has no named subclasses in the OFL namespace.
        all_named = [
            (str(sparql_row.flap), str(sparql_row.flapLabel))
            for sparql_row in tbox_graph.query(_q("origin_leaf_flap_classes.sparql"))
        ]

        # ── Query 5: perforator flap classes ───────────────────────────────────
        # A perforator flap is defined by having a restriction on PERFORATOR_VESSEL_OF
        # (ofl:OFLID120000) anywhere in its OWL axiom graph — not by label text.
        perforator_set: set[str] = {
            str(sparql_row.flap)
            for sparql_row in tbox_graph.query(_q("perforator_flap_classes.sparql"))
        }

        print(
            f"[ABox] TBox: {len(parts_map)} rich flaps, "
            f"{len(origin_map)} with origin, {len(pedicle_map)} pedicles, "
            f"{len(perforator_set)} perforator flap classes, "
            f"{len(all_named)} total origin-leaf flap classes"
        )
        return dict(
            parts_map=parts_map,
            origin_map=origin_map,
            pedicle_map=pedicle_map,
            perforator_set=perforator_set,
            all_named=all_named,
        )

    # ── Instance builder ───────────────────────────────────────────────────────

    @staticmethod
    def _declare(
        output_graph: Graph,
        iri: URIRef,
        label: str,
        *class_iris: URIRef,
    ) -> None:
        """

        The function is really a low-level RDF writing helper — 
        it emits the three boilerplate triples that every typed resource needs. 
        Declare a named individual: add rdf:type owl:NamedIndividual, an
        rdfs:label, and one rdf:type triple per extra class argument.

        Equivalent to three (or more) raw output_graph.add() calls, kept as a
        static method to avoid repeating the NamedIndividual + label boilerplate.
        """
        output_graph.add((iri, RDF.type,   OWL.NamedIndividual))
        output_graph.add((iri, RDFS.label, Literal(label, lang="en")))
        for class_iri in class_iris:
            output_graph.add((iri, RDF.type, class_iri))

    def _add_instance(
        self,
        output_graph: Graph,         # the ABox graph — all triples go here via output_graph.add()
        counter: _IDCounter,
        patient_n: int,
        flap_iri: str,               # OFL class IRI the flap individual belongs to
        flap_label: str,             # human-readable class name, used to build labels
        part_iris: list[str],        # FMA anatomical component IRIs (may be empty)
        origin_class_iri: str | None,   # anatomical origin class IRI from TBox
        pedicle_cls: str | None,        # pedicle class IRI (None if unknown)
        pedicle_vessels: list[str],     # FMA vessel IRIs within the pedicle
        survival_cls: URIRef,           # one of LEAF_SURVIVAL / MAIN_SURVIVAL
        modification_cls: URIRef,       # MOD_NO or MOD_YES
        transfer_cls: URIRef,           # FREE_TRANSFER or PEDICLED_TRANSFER
        distance_cls: URIRef,           # LOCAL_FLAP, REGIONAL_FLAP, DISTANT_FLAP
        side: str,                      # "left" or "right"
        is_perforator: bool = False,    # True iff the TBox defines this as a perforator flap
    ) -> None:
        """
        Write all triples for one flap instance and all its satellite
        individuals (patient, processes, plan, qualities, role, locations).

        The core primitive is output_graph.add((subject, predicate, object)).
        _declare() is a small helper that groups the three boilerplate
        triples every named individual needs:
            (iri, rdf:type, owl:NamedIndividual)
            (iri, rdfs:label, "…"@en)
            (iri, rdf:type, <class>)   ← one per extra class argument
        """
        side_prefix   = f"{side.capitalize()} " if side else ""
        tbox          = self._tbox
        transfer_word = "Free" if transfer_cls == FREE_TRANSFER else "Pedicled"

        # ── Pre-allocate IRIs for all individuals in this instance ─────────────
        # We reserve IRIs up-front so we can forward-reference them
        # (e.g. PART_OF references flap_id before the flap triple is written —
        # that is fine because a Graph is an unordered set of triples).
        patient_id          = counter.next()
        flap_id             = counter.next()
        harvest_id          = counter.next()
        transfer_id         = counter.next()
        operation_id        = counter.next()
        surgery_plan_id     = counter.next()
        conc_plan_id        = counter.next()  # concretized plan (specifically dependent continuant)
        volume_id           = counter.next()
        mass_id             = counter.next()
        role_id             = counter.next()
        pedicle_id          = counter.next() if pedicle_cls else None
        part_ids            = [counter.next() for _ in part_iris]
        recipient_site_id   = counter.next()
        donor_site_id       = counter.next() if distance_cls != LOCAL_FLAP else None         # Non-local flaps get a separate donor site individual. Local flaps reuse recipient_site_id as the donor site (donor = recipient).
        anatomical_input_id = counter.next()  # anatomical entity (specified input of operation)

        instance_label = f"{side_prefix}{flap_label} of patient {patient_n}"

        # ── Patient ────────────────────────────────────────────────────────────
        # PATIENT_TYPE = NCBITaxon:9606 (Homo sapiens)
        self._declare(output_graph, patient_id, f"Patient {patient_n}", PATIENT_TYPE)

        # ── Anatomical part individuals ────────────────────────────────────────
        # Each FMA part class gets an individual typed with that class.
        # part_of (OFL property) connects each part back to the flap individual.
        for part_id, fma_iri in zip(part_ids, part_iris):
            fma_id_suffix = fma_iri.rstrip("/").rsplit("_", 1)[-1]
            part_label    = tbox.label_of(URIRef(fma_iri)) or f"structure {fma_id_suffix}"
            self._declare(output_graph, part_id,
                        f"{side_prefix}{part_label} of patient {patient_n}",
                        URIRef(fma_iri))
            output_graph.add((part_id, PART_OF, flap_id))

        # ── Pedicle ────────────────────────────────────────────────────────────
        if pedicle_id and pedicle_cls:
            self._declare(output_graph, pedicle_id,
                        f"Flap pedicle of {instance_label}",
                        URIRef(pedicle_cls))
            output_graph.add((pedicle_id, PART_OF, flap_id))

            # Named vessels within the pedicle (up to 2, from TBox SPARQL)
            for vessel_iri in pedicle_vessels[:2]:
                vessel_id     = counter.next()
                fma_id_suffix = vessel_iri.rstrip("/").rsplit("_", 1)[-1]
                vessel_label  = tbox.label_of(URIRef(vessel_iri)) or f"vessel {fma_id_suffix}"
                self._declare(output_graph, vessel_id,
                            f"{side_prefix}{vessel_label} of patient {patient_n}",
                            URIRef(vessel_iri))
                output_graph.add((pedicle_id, HAS_PART, vessel_id))

            # The pedicle carries a blood-supply function (BFO:function)
            blood_func_id = counter.next()
            self._declare(output_graph, blood_func_id,
                        f"Oxygenated blood supply to {instance_label} function",
                        FUNC_TYPE)
            output_graph.add((pedicle_id, HAS_FUNCTION, blood_func_id))

            # ── Perforator vessels (non-random pattern flaps only) ─────────────
            # A perforator flap pedicle must include arterial and venous
            # perforator vessels, each connected to its tree-segment origin
            # via the 'perforator vessel of' property.
            if is_perforator:
                arterial_segment_id    = counter.next()
                arterial_perforator_id = counter.next()
                venous_segment_id      = counter.next()
                venous_perforator_id   = counter.next()

#---------------------------------------------------------------
#_______________________________________________________________
                #COMPLAINT: This is too coarse. The Subsegment of the arterial tree that gives rise to the perforator vessel should be the instance of a specific subclass of Segment of arterial tree organ, not just the general class. This is because a flap is defined largely by the incorporated vessel. This is axiomatized using: equivalent to "Surgical flap" and (hasPart some ("Anterior tibial artery")) 
                self._declare(output_graph, arterial_segment_id,
                            f"Arterial tree segment of patient {patient_id}",
                            SEGMENT_ARTERIAL_TREE)
                self._declare(output_graph, arterial_perforator_id,
                            f"Arterial perforator of a vessel in patient {patient_id}",
                            PERFORATOR_VESSEL_CLS)
                output_graph.add((arterial_perforator_id, PERFORATOR_VESSEL_OF, arterial_segment_id))
                output_graph.add((pedicle_id,             HAS_PART,             arterial_perforator_id))

                self._declare(output_graph, venous_segment_id,
                            f"Venous tree segment for {instance_label}",
                            SEGMENT_VENOUS_TREE)
                self._declare(output_graph, venous_perforator_id,
                            f"Venous perforator of {instance_label}",
                            PERFORATOR_VESSEL_CLS)
                output_graph.add((venous_perforator_id, PERFORATOR_VESSEL_OF, venous_segment_id))
                output_graph.add((pedicle_id,           HAS_PART,             venous_perforator_id))

        # ── Qualities: volume and mass ─────────────────────────────────────────
        # BFO qualities inhere in the flap (connected below via HAS_QUALITY).
        self._declare(output_graph, volume_id, f"Volume of {instance_label}", VOL_TYPE)
        self._declare(output_graph, mass_id,   f"Mass of {instance_label}",   MASS_TYPE)

        # ── Role ───────────────────────────────────────────────────────────────
        # A flap can serve different surgical roles; one is assigned randomly.
        role_class = random.choice([ROLE_TYPE, MOTOR_FUNC_ROLE_TYPE, TISSUE_LOSS_ROLE_TYPE])
        self._declare(output_graph, role_id, f"Role of {instance_label}", role_class)

        # ── Surgery plan (generically dependent continuant / GDC) ─────────────
        # The plan is a BFO:InformationContentEntity that prescribes the surgery.
        self._declare(output_graph, surgery_plan_id,
                    f"Flap surgery plan for {flap_label}",
                    FLAP_SURGERY_PLAN)

        # ── Concretized surgery plan (specifically dependent continuant / SDC) ─
        # The SDC is the plan as instantiated for this specific patient.
        self._declare(output_graph, conc_plan_id,
                    f"Concretized surgery plan of {instance_label}",
                    CONC_PLAN_TYPE)
        output_graph.add((conc_plan_id, CONCRETIZES, surgery_plan_id))

        # ── Flap harvest process ───────────────────────────────────────────────
        # The flap comes into existence at the end of this process.
        self._declare(output_graph, harvest_id,
                    f"Flap harvest process of {instance_label}",
                    FLAP_HARVEST_PROCESS)

        # ── Transfer process + donor / recipient site ──────────────────────────
        self._declare(output_graph, transfer_id,
                    f"{transfer_word} flap transfer process of {instance_label}",
                    transfer_cls)

        # The donor site is typed with the TBox-defined anatomical origin class.
        # This applies uniformly to all flaps — every flap classified by origin
        # has a defined origin in the TBox (hasOrigin restriction).
        donor_site_class = URIRef(origin_class_iri) if origin_class_iri else SUBDIVISION_CARDINAL_BODY
        self._declare(output_graph, recipient_site_id,
                    f"Recipient site of {instance_label}",
                    SUBDIVISION_CARDINAL_BODY)
        output_graph.add((transfer_id, HAS_TARGET_END_LOCATION, recipient_site_id))

        if donor_site_id is None:
            # Local flap: donor and recipient region are the same individual.
            # Locality is defined by start = end, not by which class the region
            # belongs to.
            output_graph.add((transfer_id,       HAS_TARGET_START_LOCATION, recipient_site_id))
            output_graph.add((recipient_site_id, RDF.type,                  donor_site_class))
        else:
            # Regional / distant flap: separate donor site individual
            self._declare(output_graph, donor_site_id,
                        f"Donor site of {instance_label}",
                        donor_site_class)
            output_graph.add((transfer_id, HAS_TARGET_START_LOCATION, donor_site_id))

        # ── Anatomical entity (specified input to the operation) ───────────────
        self._declare(output_graph, anatomical_input_id,
                    f"Anatomical site of {instance_label}",
                    ANATOMICAL_ENT_TYPE)

        # ── Complete flap operation ────────────────────────────────────────────
        # The operation is the top-level process that contains all sub-processes.
        self._declare(output_graph, operation_id,
                    f"{transfer_word} flap operation of {instance_label}",
                    COMPLETE_OPERATION)
        output_graph.add((operation_id, HAS_PARTICIPANT,      flap_id))
        output_graph.add((operation_id, HAS_PARTICIPANT,      patient_id))
        output_graph.add((operation_id, HAS_PART,             harvest_id))
        output_graph.add((operation_id, HAS_PART,             transfer_id))
        output_graph.add((operation_id, HAS_SPECIFIED_OUTPUT, flap_id))
        output_graph.add((operation_id, HAS_SPECIFIED_INPUT,  anatomical_input_id))
        # The operation realizes the concretized plan (SDC), not the plan itself
        output_graph.add((operation_id, REALIZES,             conc_plan_id))

        # ── Flap individual ────────────────────────────────────────────────────
        # Typed with multiple OWL classes simultaneously: specific flap class +
        # survival outcome + modification + distance.  In OWL an individual can
        # belong to any number of classes.
        self._declare(output_graph, flap_id, instance_label,
                    URIRef(flap_iri), survival_cls, modification_cls, distance_cls)
        # Temporal / causal relations
        output_graph.add((flap_id, IS_OUTPUT_OF,               harvest_id))
        output_graph.add((flap_id, IS_OUTPUT_OF,               operation_id))
        output_graph.add((flap_id, EXISTENCE_STARTS_AT_END_OF, harvest_id))
        output_graph.add((flap_id, EXISTENCE_STARTS_DURING,    operation_id))
        # Quality and role bearership
        output_graph.add((flap_id, HAS_QUALITY,                volume_id))
        output_graph.add((flap_id, HAS_QUALITY,                mass_id))
        output_graph.add((flap_id, HAS_ROLE,                   role_id))
        # Process participation
        output_graph.add((flap_id, PARTICIPATES_IN,            transfer_id))
        # Anatomical origin (OFL-specific relation, from TBox restriction)
        if origin_class_iri:
            output_graph.add((flap_id, HAS_ORIGIN, URIRef(origin_class_iri)))
        # Mereological structure
        for part_id in part_ids:
            output_graph.add((flap_id, HAS_PART, part_id))
        if pedicle_id:
            output_graph.add((flap_id, HAS_PART, pedicle_id))


# ── Module-private helpers ────────────────────────────────────────────────────

def _resolve_filler(tbox_graph: Graph, restriction_filler) -> list[URIRef]:
    """
    Recursively extract all named class IRIs from an OWL restriction filler.

    In RDF/OWL, a restriction filler can be:
      - A plain URIRef  → return it directly.
      - A BNode carrying owl:unionOf or owl:intersectionOf → unwrap the list.
      - A BNode with a nested owl:someValuesFrom → recurse.

    This handles cases like ``hasPart some (SkinFlap or FasciaFlap)`` where
    the filler is a union BNode containing two named classes.
    """
    if isinstance(restriction_filler, URIRef):
        return [restriction_filler]
    named_class_iris: list[URIRef] = []
    for rdf_list_node in tbox_graph.objects(restriction_filler, OWL.intersectionOf):
        named_class_iris.extend(_resolve_rdf_list(tbox_graph, rdf_list_node))
    for rdf_list_node in tbox_graph.objects(restriction_filler, OWL.unionOf):
        named_class_iris.extend(_resolve_rdf_list(tbox_graph, rdf_list_node))
    for nested_filler in tbox_graph.objects(restriction_filler, OWL.someValuesFrom):
        named_class_iris.extend(_resolve_filler(tbox_graph, nested_filler))
    return named_class_iris


def _resolve_rdf_list(tbox_graph: Graph, rdf_list_node) -> list[URIRef]:
    """
    Walk an RDF list (linked via rdf:first / rdf:rest) and collect all items.

    RDF lists are a linked-list structure encoded as triples:
        _:node0  rdf:first  ClassA       ← head item
                 rdf:rest   _:node1      ← pointer to next node
        _:node1  rdf:first  ClassB
                 rdf:rest   rdf:nil      ← end-of-list sentinel

    tbox_graph.value(node, rdf:first) retrieves the single head item of that
    node.  Items that are themselves BNodes (nested expressions) are passed
    back through _resolve_filler so unions-within-unions are handled correctly.
    """
    collected_iris: list[URIRef] = []
    while rdf_list_node and rdf_list_node != RDF.nil:
        list_item = tbox_graph.value(rdf_list_node, RDF.first)
        if list_item is not None:
            if isinstance(list_item, BNode):
                collected_iris.extend(_resolve_filler(tbox_graph, list_item))
            elif isinstance(list_item, URIRef):
                collected_iris.append(list_item)
        rdf_list_node = tbox_graph.value(rdf_list_node, RDF.rest)
    return collected_iris


def _infer_transfer(flap_label: str) -> URIRef:
    """Heuristic: flaps with 'free', 'perforator', or 'microvascular' in their
    label are classified as free transfers; all others as pedicled."""
    if any(word in flap_label.lower() for word in ["free", "perforator", "microvascular"]):
        return FREE_TRANSFER
    return PEDICLED_TRANSFER


def _infer_distance(flap_label: str, transfer_cls: URIRef) -> URIRef:
    """Free transfers are always distant; pedicled flaps are local if their
    label suggests so (advancement / rotation), regional otherwise."""
    if transfer_cls == FREE_TRANSFER:
        return DISTANT_FLAP
    if any(word in flap_label.lower() for word in ["local", "advancement", "rotation"]):
        return LOCAL_FLAP
    return REGIONAL_FLAP
