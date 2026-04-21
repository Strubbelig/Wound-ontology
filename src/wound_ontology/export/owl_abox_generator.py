"""
OWLABoxGenerator
================
Algorithmically generates a large ABox (1 k – 10 k+ flap individuals) covering
the complete variety expressible by an OFL TBox.

Architecture
------------
* ``OWLOntology`` for loading the TBox and resolving labels/IRIs via SPARQL.
* ``ABoxGenerator`` for writing all individual and property-assertion triples.
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
    from wound_ontology.export import OWLOntology, OWLABoxGenerator

    tbox_onto = OWLOntology().load("flap_onto.owl")
    gen = OWLABoxGenerator(tbox_onto)
    gen.generate(patients_per_combination=5)
    gen.save("ofl_abox_5k.owl")

Or one-shot::

    OWLABoxGenerator.run_files("flap_onto.owl", "ofl_abox_5k.owl", patients=5)
"""
from __future__ import annotations

import random
from itertools import product
from pathlib import Path

from rdflib import Graph, Namespace, URIRef, BNode
from rdflib.namespace import RDF, RDFS, OWL
import rdflib

from wound_ontology.export.owl_generator import ABoxGenerator

# ── Namespaces ────────────────────────────────────────────────────────────────
OFL     = Namespace("https://purl.bioontology.org/ontology/OFL/")
OBO     = Namespace("http://purl.obolibrary.org/obo/")
FMA     = Namespace("http://purl.obolibrary.org/obo/FMA_")
DCTERMS = Namespace("http://purl.org/dc/terms/")

# ── Ontology roots ────────────────────────────────────────────────────────────
FLAP_ROOT   = OFL.OFLID10002   # top-level flap class
ORIGIN_ROOT = OFL.OFLID10098   # Flaps classified by region of origin

# ── OFL object properties ─────────────────────────────────────────────────────
HAS_PART  = OFL.OFLID13296
PART_OF   = OFL.OFLID13297
HAS_ORIGIN = OFL.OFLID12003

# ── RO / OBI properties ───────────────────────────────────────────────────────
HAS_PARTICIPANT = OBO.RO_0000057   # has participant
CONCRETIZES     = OBO.RO_0000059   # concretizes (sdc concretizes gdc)
HAS_FUNCTION    = OBO.RO_0000085   # has function
HAS_QUALITY     = OBO.RO_0000086   # has quality
IS_OUTPUT_OF    = OBO.OBI_0000312  # is specified output of

# ── Flap classification types (typed onto individuals) ────────────────────────
MOD_NO  = OFL.OFLID10130   # without preharvest modification
MOD_YES = OFL.OFLID10131   # with preharvest modification

SURVIVAL_NO_LOSS  = OFL.OFLID10184
SURVIVAL_APEX     = OFL.OFLID10179
SURVIVAL_TOTAL    = OFL.OFLID10183
SURVIVAL_ARTERIAL = OFL.OFLID10180
SURVIVAL_VENOUS   = OFL.OFLID10181

LEAF_SURVIVAL = [SURVIVAL_NO_LOSS, SURVIVAL_APEX, SURVIVAL_TOTAL,
                 SURVIVAL_ARTERIAL, SURVIVAL_VENOUS]
MAIN_SURVIVAL = [SURVIVAL_NO_LOSS, SURVIVAL_APEX, SURVIVAL_TOTAL]

LOCAL_FLAP    = OFL.OFLID10134
REGIONAL_FLAP = OFL.OFLID10140
DISTANT_FLAP  = OFL.OFLID10085

FREE_TRANSFER    = OFL.OFLID1000137   # Free transfer process
PEDICLED_TRANSFER = OFL.OFLID1000138  # Pedicled transfer process

# ── Process / plan class IRIs ─────────────────────────────────────────────────
FLAP_HARVEST_PROCESS    = OFL.OFLID1000132   # Flap harvest process
COMPLETE_OPERATION      = OFL.OFLID1000128   # Complete flap operation process
FLAP_SURGERY_PLAN       = OFL.OFLID10507     # Flap surgery plan (gdc)

# ── BFO / PATO / NCBITaxon types ─────────────────────────────────────────────
CONC_PLAN_TYPE = OBO.BFO_0000020      # specifically dependent continuant
PATIENT_TYPE   = OBO.NCBITaxon_9606   # Homo sapiens
VOL_TYPE       = OBO.PATO_0001679     # volume

# ── Flap quality / role / function types ─────────────────────────────────────
ROLE_TYPE = OFL.OFLID106000   # Wound coverage role
FUNC_TYPE = OFL.OFLID106029   # Oxygenated blood supply to flap function

# ── External ontology import URLs ────────────────────────────────────────────
_BFO_URL = "http://purl.obolibrary.org/obo/bfo.owl"
_RO_URL  = "http://purl.obolibrary.org/obo/ro.owl"
_OBI_URL = "http://purl.obolibrary.org/obo/obi.owl"


class _IDCounter:
    def __init__(self, start: int = 20_000):
        self._n = start

    def next(self) -> URIRef:
        iri = OFL[f"OFLID{self._n:07d}"]
        self._n += 1
        return iri

    @property
    def current(self) -> int:
        return self._n


class OWLABoxGenerator:
    """
    Generates synthetic OWL ABox individuals for OFL-based TBoxes.

    Parameters
    ----------
    tbox_onto : OWLOntology
        The loaded TBox ontology (used for SPARQL-based TBox extraction).
    id_start : int
        First IRI counter value (default 20 000 to avoid TBox collisions).
    """

    def __init__(self, tbox_onto, id_start: int = 20_000):
        self._tbox_onto = tbox_onto
        self._id_start  = id_start
        self._gen: ABoxGenerator | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate(
        self,
        patients_per_combination: int = 1,
        seed: int = 42,
    ) -> "OWLABoxGenerator":
        """Build the ABox graph in memory."""
        random.seed(seed)
        tbox_info = self._extract_tbox_info()

        out = Graph()
        out.bind("ofl",     OFL)
        out.bind("obo",     OBO)
        out.bind("fma",     FMA)
        out.bind("rdfs",    RDFS)
        out.bind("owl",     OWL)
        out.bind("dcterms", DCTERMS)

        onto_iri = URIRef("https://purl.bioontology.org/ontology/OFL/abox")
        out.add((onto_iri, RDF.type, OWL.Ontology))
        # Import TBox and foundational ontologies for correct OWL RL reasoning
        out.add((onto_iri, OWL.imports,
                 URIRef("https://purl.bioontology.org/ontology/OFL")))
        out.add((onto_iri, OWL.imports, URIRef(_BFO_URL)))
        out.add((onto_iri, OWL.imports, URIRef(_RO_URL)))
        out.add((onto_iri, OWL.imports, URIRef(_OBI_URL)))

        self._gen = ABoxGenerator(graph=out)
        counter   = _IDCounter(self._id_start)

        parts_map   = tbox_info["parts_map"]
        origin_map  = tbox_info["origin_map"]
        pedicle_map = tbox_info["pedicle_map"]
        all_named   = tbox_info["all_named"]
        rich_iris   = set(parts_map)

        flap_count = 0
        patient_n  = 1

        # Phase 1 — rich instances (variant leaves with explicit hasPart)
        for flap_iri, flap_info in parts_map.items():
            flap_label = flap_info["label"]
            parts      = flap_info["parts"]
            origin     = origin_map.get(flap_iri)
            ped_info   = pedicle_map.get(flap_label.lower(), {})
            transfer   = _infer_transfer(flap_label)
            distance   = _infer_distance(flap_label, transfer)

            for side, survival, mod in product(
                ["left", "right"], LEAF_SURVIVAL, [MOD_NO, MOD_YES]
            ):
                for _ in range(patients_per_combination):
                    self._add_instance(
                        counter, patient_n,
                        flap_iri, flap_label, parts, origin,
                        pedicle_cls=ped_info.get("iri"),
                        pedicle_vessels=ped_info.get("vessels", []),
                        survival_cls=survival, modification_cls=mod,
                        transfer_cls=transfer, distance_cls=distance, side=side,
                    )
                    flap_count += 1
                    patient_n  += 1

        # Phase 2 — typed instances (origin leaves without explicit hasPart)
        for flap_iri, flap_label in all_named:
            if flap_iri in rich_iris:
                continue
            origin   = origin_map.get(flap_iri)
            transfer = _infer_transfer(flap_label)
            distance = _infer_distance(flap_label, transfer)

            for side, survival in product(["left", "right"], MAIN_SURVIVAL):
                for _ in range(patients_per_combination):
                    self._add_instance(
                        counter, patient_n,
                        flap_iri, flap_label, [], origin,
                        pedicle_cls=None, pedicle_vessels=[],
                        survival_cls=survival, modification_cls=MOD_NO,
                        transfer_cls=transfer, distance_cls=distance, side=side,
                    )
                    flap_count += 1
                    patient_n  += 1

        n_ind = sum(1 for _ in out.subjects(RDF.type, OWL.NamedIndividual))
        print(
            f"[OWLABoxGenerator] {flap_count:,} flap instances, "
            f"{n_ind:,} individuals, {len(out):,} triples"
        )
        return self

    def save(self, output_file: str) -> None:
        """Serialize the ABox as RDF/XML."""
        if self._gen is None:
            raise RuntimeError("Call generate() first.")
        self._gen.save(output_file)

    @classmethod
    def run_files(
        cls,
        tbox_file: str,
        output_file: str,
        patients: int = 1,
        seed: int = 42,
        id_start: int = 20_000,
    ) -> "OWLABoxGenerator":
        """
        Convenience one-shot class method::

            OWLABoxGenerator.run_files("tbox.owl", "abox.owl", patients=5)
        """
        from wound_ontology.export.owl_ontology import OWLOntology
        tbox_onto = OWLOntology().load(tbox_file)
        gen = cls(tbox_onto, id_start=id_start)
        gen.generate(patients_per_combination=patients, seed=seed)
        gen.save(output_file)
        return gen

    @property
    def graph(self) -> Graph | None:
        """The generated rdflib.Graph (available after generate())."""
        return self._gen.graph if self._gen else None

    # ── TBox extraction via OWLOntology.sparql ─────────────────────────────────

    def _extract_tbox_info(self) -> dict:
        """Use the OWLOntology's SPARQL helper to extract generation metadata.

        Only leaf classes under ORIGIN_ROOT are returned so that classification
        axes (Mathes & Nahai, blood supply, etc.) are never instantiated.
        """
        g = self._tbox_onto.rdf_graph

        P = ("PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
             "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
             "PREFIX owl:  <http://www.w3.org/2002/07/owl#>\n"
             "PREFIX ofl:  <https://purl.bioontology.org/ontology/OFL/>")

        parts_map: dict[str, dict] = {}
        for row in g.query(P + f"""
            SELECT DISTINCT ?flap ?flapLabel ?partBN WHERE {{
              ?flap rdfs:subClassOf* ofl:OFLID10098 .
              ?flap rdfs:subClassOf ?r .
              ?r a owl:Restriction ; owl:onProperty ofl:OFLID13296 ;
                 owl:someValuesFrom ?partBN .
              ?flap rdfs:label ?flapLabel .
              FILTER(!isBlank(?flap))
              FILTER NOT EXISTS {{
                ?sub rdfs:subClassOf ?flap .
                FILTER(!isBlank(?sub))
                FILTER(isIRI(?sub))
              }}
            }}"""):
            iri, lbl = str(row.flap), str(row.flapLabel)
            named = [str(p) for p in _resolve_filler(g, row.partBN)
                     if isinstance(p, URIRef)]
            if iri not in parts_map:
                parts_map[iri] = {"label": lbl, "parts": []}
            parts_map[iri]["parts"].extend(
                p for p in named if p not in parts_map[iri]["parts"]
            )

        origin_map: dict[str, str] = {}
        for row in g.query(P + """
            SELECT DISTINCT ?flap ?origin WHERE {
              ?flap rdfs:subClassOf* ofl:OFLID10098 .
              ?flap rdfs:subClassOf ?r .
              ?r a owl:Restriction ; owl:onProperty ofl:OFLID12003 ;
                 owl:someValuesFrom ?origin .
              FILTER(!isBlank(?origin))
            }"""):
            origin_map[str(row.flap)] = str(row.origin)

        pedicle_map: dict[str, dict] = {}
        for row in g.query(P + """
            SELECT DISTINCT ?ped ?pedLabel ?vessel WHERE {
              ?ped rdfs:label ?pedLabel .
              FILTER(CONTAINS(LCASE(STR(?pedLabel)), "pedicle of the"))
              OPTIONAL {
                ?ped rdfs:subClassOf ?r .
                ?r a owl:Restriction ; owl:someValuesFrom ?vessel .
                FILTER(STRSTARTS(STR(?vessel),
                       "http://purl.obolibrary.org/obo/FMA_"))
              }
            }"""):
            frag = str(row.pedLabel).lower().replace(
                "flap pedicle of the ", ""
            ).strip()
            if frag not in pedicle_map:
                pedicle_map[frag] = {"iri": str(row.ped), "vessels": []}
            if row.vessel:
                v = str(row.vessel)
                if v not in pedicle_map[frag]["vessels"]:
                    pedicle_map[frag]["vessels"].append(v)

        # Leaf classes under ORIGIN_ROOT only (no named subclasses in OFL ns)
        all_named = [
            (str(r.flap), str(r.flapLabel))
            for r in g.query(P + f"""
            SELECT DISTINCT ?flap ?flapLabel WHERE {{
              ?flap rdfs:subClassOf* ofl:OFLID10098 .
              ?flap rdfs:label ?flapLabel .
              FILTER(!isBlank(?flap))
              FILTER(STRSTARTS(STR(?flap),
                     "https://purl.bioontology.org/ontology/OFL/"))
              FILTER NOT EXISTS {{
                ?sub rdfs:subClassOf ?flap .
                FILTER(!isBlank(?sub))
                FILTER(isIRI(?sub))
              }}
            }}""")
        ]

        print(
            f"[OWLABoxGenerator] TBox: {len(parts_map)} rich flaps, "
            f"{len(origin_map)} with origin, {len(pedicle_map)} pedicles, "
            f"{len(all_named)} total origin-leaf flap classes"
        )
        return dict(
            parts_map=parts_map,
            origin_map=origin_map,
            pedicle_map=pedicle_map,
            all_named=all_named,
        )

    # ── Instance builder ───────────────────────────────────────────────────────

    def _add_instance(
        self,
        counter: _IDCounter,
        patient_n: int,
        flap_iri: str,
        flap_label: str,
        parts: list[str],
        origin_iri: str | None,
        pedicle_cls: str | None,
        pedicle_vessels: list[str],
        survival_cls: URIRef,
        modification_cls: URIRef,
        transfer_cls: URIRef,
        distance_cls: URIRef,
        side: str,
    ) -> None:
        sp  = f"{side.capitalize()} " if side else ""
        gen = self._gen

        # Pre-allocate IRIs
        patient_id  = counter.next()
        flap_id     = counter.next()
        harvest_id  = counter.next()
        transfer_id = counter.next()
        op_id       = counter.next()
        plan_id     = counter.next()
        cplan_id    = counter.next()
        vol_id      = counter.next()
        role_id     = counter.next()
        pedicle_id  = counter.next() if pedicle_cls else None
        func_id     = counter.next() if pedicle_cls else None
        part_ids    = [counter.next() for _ in parts]

        f_label = f"{sp}{flap_label} of patient {patient_n}"
        prefix  = "Free" if transfer_cls == FREE_TRANSFER else "Pedicled"

        # ── Patient ────────────────────────────────────────────────────────────
        gen.add_individual(patient_id, f"Patient {patient_n}", PATIENT_TYPE)

        # ── Anatomical part individuals ────────────────────────────────────────
        for comp_id, fma_iri in zip(part_ids, parts):
            short = fma_iri.rstrip("/").rsplit("_", 1)[-1]
            lbl   = self._tbox_onto.label_of(URIRef(fma_iri)) or f"structure {short}"
            gen.add_individual(
                comp_id,
                f"{sp}{lbl} of patient {patient_n}",
                URIRef(fma_iri),
            )
            gen.add_object_property(comp_id, PART_OF, flap_id)

        # ── Pedicle ────────────────────────────────────────────────────────────
        if pedicle_id and pedicle_cls:
            gen.add_individual(
                pedicle_id,
                f"Flap pedicle of {f_label}",
                URIRef(pedicle_cls),
            )
            gen.add_object_property(pedicle_id, PART_OF, flap_id)

            # Vessels within pedicle
            for v_iri in pedicle_vessels[:2]:
                v_id  = counter.next()
                short = v_iri.rstrip("/").rsplit("_", 1)[-1]
                lbl   = self._tbox_onto.label_of(URIRef(v_iri)) or f"vessel {short}"
                gen.add_individual(
                    v_id,
                    f"{sp}{lbl} of patient {patient_n}",
                    URIRef(v_iri),
                )
                gen.add_object_property(pedicle_id, HAS_PART, v_id)

            # Blood supply function inheres in the pedicle
            gen.add_individual(func_id, f"Oxygenated blood supply to {f_label} function",
                               FUNC_TYPE)
            gen.add_object_property(pedicle_id, HAS_FUNCTION, func_id)

        # ── Quality (volume) ───────────────────────────────────────────────────
        gen.add_individual(vol_id, f"Volume of {f_label}", VOL_TYPE)

        # ── Role ───────────────────────────────────────────────────────────────
        gen.add_individual(role_id, f"Wound coverage role of {f_label}", ROLE_TYPE)

        # ── Surgery plan (generically dependent continuant) ───────────────────
        gen.add_individual(plan_id, f"Flap surgery plan for {flap_label}",
                           FLAP_SURGERY_PLAN)

        # ── Concretized surgery plan (specifically dependent continuant) ───────
        gen.add_individual(cplan_id,
                           f"Concretized surgery plan of {f_label}",
                           CONC_PLAN_TYPE)
        gen.add_object_property(cplan_id, CONCRETIZES, plan_id)

        # ── Flap harvest process — the flap exists from the end of this ────────
        gen.add_individual(harvest_id,
                           f"Flap harvest process of {f_label}",
                           FLAP_HARVEST_PROCESS)

        # ── Transfer process ───────────────────────────────────────────────────
        gen.add_individual(transfer_id,
                           f"{prefix} flap transfer process of {f_label}",
                           transfer_cls)

        # ── Complete flap operation ────────────────────────────────────────────
        gen.add_individual(op_id,
                           f"{prefix} flap operation of {f_label}",
                           COMPLETE_OPERATION)
        gen.add_object_property(op_id, HAS_PARTICIPANT, flap_id)
        gen.add_object_property(op_id, HAS_PARTICIPANT, patient_id)
        gen.add_object_property(op_id, HAS_PART, harvest_id)
        gen.add_object_property(op_id, HAS_PART, transfer_id)

        # ── Flap ───────────────────────────────────────────────────────────────
        gen.add_individual(
            flap_id, f_label,
            URIRef(flap_iri), survival_cls, modification_cls, distance_cls,
        )
        # Flap comes into existence at the end of the harvest process
        gen.add_object_property(flap_id, IS_OUTPUT_OF, harvest_id)
        gen.add_object_property(flap_id, HAS_QUALITY,  vol_id)

        if origin_iri:
            gen.add_object_property(flap_id, HAS_ORIGIN, URIRef(origin_iri))
        for comp_id in part_ids:
            gen.add_object_property(flap_id, HAS_PART, comp_id)
        if pedicle_id:
            gen.add_object_property(flap_id, HAS_PART, pedicle_id)


# ── Module-private helpers ────────────────────────────────────────────────────

def _resolve_filler(g: Graph, node) -> list[URIRef]:
    if isinstance(node, URIRef):
        return [node]
    results: list[URIRef] = []
    for lst in g.objects(node, OWL.intersectionOf):
        results.extend(_resolve_list(g, lst))
    for lst in g.objects(node, OWL.unionOf):
        results.extend(_resolve_list(g, lst))
    for filler in g.objects(node, OWL.someValuesFrom):
        results.extend(_resolve_filler(g, filler))
    return results


def _resolve_list(g: Graph, lst) -> list[URIRef]:
    items: list[URIRef] = []
    while lst and lst != RDF.nil:
        first = g.value(lst, RDF.first)
        if first is not None:
            if isinstance(first, rdflib.BNode):
                items.extend(_resolve_filler(g, first))
            else:
                items.append(first)
        lst = g.value(lst, RDF.rest)
    return items


def _infer_transfer(flap_label: str) -> URIRef:
    if any(w in flap_label.lower() for w in ["free", "perforator", "microvascular"]):
        return FREE_TRANSFER
    return PEDICLED_TRANSFER


def _infer_distance(flap_label: str, transfer_cls: URIRef) -> URIRef:
    if transfer_cls == FREE_TRANSFER:
        return DISTANT_FLAP
    lc = flap_label.lower()
    if any(w in lc for w in ["local", "advancement", "rotation"]):
        return LOCAL_FLAP
    return REGIONAL_FLAP
