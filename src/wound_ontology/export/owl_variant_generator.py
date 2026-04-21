"""
OWLVariantGenerator
===================
Converts every flap class that carries a ``hasPart some (A or B or C …)``
union restriction into a set of named variant subclasses — one per union member:

    PectoralisMajorFlap  →  PectoralisMajorFlapWithSkin
                            PectoralisMajorFlapWithFascia
                            …

The union restriction is then removed from the parent class because it adds no
logical constraint beyond what the named subclasses already express.

Architecture
------------
This class uses:

* ``OWLOntology`` instances for loading the TBox and FMA label lookups.
* ``TBoxGenerator`` for writing new OWL class axioms into the output graph.

Usage (fluent API)
------------------
    from wound_ontology.export import OWLOntology, OWLVariantGenerator

    tbox_onto = OWLOntology().load("flap_onto.owl")
    fma_onto  = OWLOntology().load("fma_obo.owl")

    gen = OWLVariantGenerator(tbox_onto, fma_onto)
    gen.generate()
    gen.save("flap_onto_with_variants.owl")

Or one-shot::

    OWLVariantGenerator.run_files(
        "flap_onto.owl", "flap_onto_with_variants.owl",
        fma_file="fma_obo.owl"
    )
"""
from __future__ import annotations

import re
from pathlib import Path

from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL, BNode

from wound_ontology.export.owl_generator import TBoxGenerator

OFL      = Namespace("https://purl.bioontology.org/ontology/OFL/")
HAS_PART = OFL["OFLID13296"]


class OWLVariantGenerator:
    """
    Generates named compositional variant subclasses from union restrictions.

    Parameters
    ----------
    tbox_onto : OWLOntology
        The loaded TBox ontology (used for SPARQL queries and graph mutation).
    fma_onto : OWLOntology, optional
        FMA ontology for resolving labels of FMA IRIs.
    flap_root : URIRef
        IRI of the top-level flap class (default: OFL:OFLID10002).
    origin_root : URIRef
        Only leaf classes under this subtree are expanded (default:
        OFL:OFLID10098 — "Flaps classified by region of origin").
        Restricts variant generation to anatomically named flap classes and
        prevents accidentally exploding classification axes (e.g. Mathes & Nahai).
    has_part : URIRef
        IRI of the hasPart property (default: OFL:OFLID13296).
    """

    def __init__(
        self,
        tbox_onto,
        fma_onto=None,
        flap_root: URIRef = OFL["OFLID10002"],
        origin_root: URIRef = OFL["OFLID10098"],
        has_part: URIRef = HAS_PART,
    ):
        self._tbox_onto  = tbox_onto
        self._fma_onto   = fma_onto
        self._flap_root  = flap_root
        self._origin_root = origin_root
        self._has_part   = has_part
        self._next_id: list[int] = [0]
        self._created: list[dict] = []
        self._gen: TBoxGenerator | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate(self) -> "OWLVariantGenerator":
        """Discover union restrictions and create named variant subclasses."""
        g = self._tbox_onto.rdf_graph
        self._next_id[0] = self._find_max_id(g) + 1

        # Write into the TBox's existing rdflib graph so the save() call
        # serializes the fully modified ontology
        self._gen = TBoxGenerator(graph=g)

        union_rows = self._discover_union_restrictions(g)
        print(f"[OWLVariantGenerator] Union hasPart restrictions: {len(union_rows)}")

        self._created = []
        for flap_iri, flap_label, restr_node, filler in union_rows:
            members = self._union_members(g, filler)
            flap_base = re.sub(r"\s+flap$", "", flap_label, flags=re.IGNORECASE).strip().lower()
            for comp_iri in members:
                comp_label = self._label_of(comp_iri)
                # Skip redundant variants where the component IS the flap's own tissue
                if comp_label.lower() == flap_base:
                    continue
                variant_iri   = self._new_iri()
                variant_label = self._make_label(flap_label, comp_label)

                # Defined class: C ≡ parent ⊓ ∃hasPart.component
                self._gen.add_defined_class(
                    variant_iri, variant_label, flap_iri, self._has_part, comp_iri
                )

                self._created.append({
                    "iri": str(variant_iri),
                    "label": variant_label,
                    "parent": flap_label,
                    "component": comp_label,
                })

            # Remove the union restriction from the parent
            g.remove((flap_iri, RDFS.subClassOf, restr_node))

        # Invalidate the ontology's SPARQL cache so it reflects the changes
        self._tbox_onto._sparql_helper = None
        print(f"[OWLVariantGenerator] Created {len(self._created)} variant subclasses.")
        return self

    def save(self, output_file: str) -> None:
        """Serialize the modified TBox to RDF/XML."""
        if self._gen is None:
            raise RuntimeError("Call generate() first.")
        self._gen.save(output_file)

    @classmethod
    def run_files(
        cls,
        tbox_file: str,
        output_file: str,
        fma_file: str | None = None,
        flap_root: URIRef = OFL["OFLID10002"],
        origin_root: URIRef = OFL["OFLID10098"],
        has_part: URIRef = HAS_PART,
    ) -> "OWLVariantGenerator":
        """
        Convenience one-shot class method::

            OWLVariantGenerator.run_files("tbox.owl", "tbox_variants.owl",
                                           fma_file="fma.owl")
        """
        from wound_ontology.export.owl_ontology import OWLOntology
        tbox_onto = OWLOntology().load(tbox_file)
        fma_onto  = OWLOntology().load(fma_file) if fma_file else None
        gen = cls(tbox_onto, fma_onto, flap_root=flap_root,
                  origin_root=origin_root, has_part=has_part)
        gen.generate()
        gen.save(output_file)
        return gen

    @property
    def created(self) -> list[dict]:
        """List of dicts describing each created variant subclass."""
        return list(self._created)

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _find_max_id(g: Graph) -> int:
        import re as _re
        max_id = 1_000_200
        for s in g.subjects():
            m = _re.search(r"OFLID(\d+)", str(s))
            if m:
                max_id = max(max_id, int(m.group(1)))
        return max_id

    def _new_iri(self) -> URIRef:
        iri = OFL[f"OFLID{self._next_id[0]}"]
        self._next_id[0] += 1
        return iri

    def _label_of(self, iri: URIRef) -> str:
        """Look up label via FMA ontology, then TBox ontology, then local name."""
        for onto in (self._fma_onto, self._tbox_onto):
            if onto is None:
                continue
            lbl = onto.label_of(iri)
            if lbl:
                return lbl
        return str(iri).split("/")[-1]

    def _rdf_list_items(self, g: Graph, node) -> list:
        items = []
        while node and node != RDF.nil:
            first = next(g.objects(node, RDF.first), None)
            if first is not None:
                items.append(first)
            node = next(g.objects(node, RDF.rest), RDF.nil)
        return items

    def _union_members(self, g: Graph, filler) -> list[URIRef]:
        union_node = next(g.objects(filler, OWL.unionOf), None)
        if union_node is None:
            return [filler] if isinstance(filler, URIRef) else []
        members: list[URIRef] = []
        for item in self._rdf_list_items(g, union_node):
            if isinstance(item, URIRef):
                members.append(item)
            else:
                for sub in self._rdf_list_items(
                    g, next(g.objects(item, OWL.unionOf), RDF.nil)
                ):
                    if isinstance(sub, URIRef):
                        members.append(sub)
                for sub in self._rdf_list_items(
                    g, next(g.objects(item, OWL.intersectionOf), RDF.nil)
                ):
                    if isinstance(sub, URIRef):
                        members.append(sub)
        return members

    def _discover_union_restrictions(self, g: Graph) -> list[tuple]:
        sparql = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl:  <http://www.w3.org/2002/07/owl#>
        SELECT DISTINCT ?flap ?flapLabel ?restr ?filler
        WHERE {{
          ?flap rdfs:subClassOf* <{self._origin_root}> .
          ?flap rdfs:subClassOf ?restr .
          ?restr a owl:Restriction ;
                 owl:onProperty <{self._has_part}> ;
                 owl:someValuesFrom ?filler .
          OPTIONAL {{ ?flap rdfs:label ?flapLabel }}
          FILTER(!isBlank(?flap))
        }}
        """
        rows = []
        for r in g.query(sparql):
            if next(g.objects(r.filler, OWL.unionOf), None) is not None:
                label = str(r.flapLabel) if r.flapLabel else str(r.flap).split("/")[-1]
                rows.append((r.flap, label, r.restr, r.filler))
        return rows

    @staticmethod
    def _make_label(flap_label: str, component_label: str) -> str:
        base = re.sub(r"\s+flap$", "", flap_label, flags=re.IGNORECASE).strip()
        return f"{base} flap with {component_label.lower()}"
