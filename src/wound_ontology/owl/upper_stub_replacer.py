"""Replace WOND upper-class stubs (WOND_120xxx) with their actual external IRIs.

Steps applied to the graph:
  1. Replace each stub with the corresponding external IRI; rewrite all
     rdfs:subClassOf references that pointed to the stub.
  2. Remove artifact subClassOf axioms (ext→domain and ext→ext) introduced
     when stubs had domain-class parents.
  3. Remove dangling external MIREOT stubs (rdf:type owl:Class only).
  4. Add rdfs:subClassOf BFO:0000015 to WOND_0000249 'process' if rootless.
"""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

OBO_BASE  = "http://purl.obolibrary.org/obo/"
WOND_BASE = OBO_BASE + "WOND_"
STUB_BASE = OBO_BASE + "wond/ground_truth.owl/WOND_120"

EXT_BASES: list[str] = [
    OBO_BASE + "BFO_",  OBO_BASE + "IAO_",  OBO_BASE + "OBI_",
    OBO_BASE + "GO_",   OBO_BASE + "PATO_", OBO_BASE + "DRON_",
    OBO_BASE + "DOID_", OBO_BASE + "HP_",   OBO_BASE + "CHEBI_",
    OBO_BASE + "OGMS_", OBO_BASE + "NCBITaxon_", OBO_BASE + "FMA_",
    OBO_BASE + "COB_",  "http://snomed.info/id/",
]

PREFIX_MAP: dict[str, str] = {
    "BFO":  OBO_BASE + "BFO_",
    "IAO":  OBO_BASE + "IAO_",
    "OBI":  OBO_BASE + "OBI_",
    "GO":   OBO_BASE + "GO_",
    "PATO": OBO_BASE + "PATO_",
    "COB":  OBO_BASE + "COB_",
    "DRON": OBO_BASE + "DRON_",
}

DOMAIN_RANGE = range(1, 433)

# Complete mapping of all WOND_120xxx stub labels → corrected external CURIEs.
UPPER_KNOWN: dict[str, str] = {
    # Information content entities
    "plan":                                       "IAO:0000104",
    "protocol":                                   "IAO:0000104",
    "information content entity":                 "IAO:0000030",
    "directive information entity":               "IAO:0000033",
    "measurement scale":                          "IAO:0000109",
    "categorical measurement datum":              "OBI:0000938",
    "wound classification grade":                 "OBI:0000938",
    # Material entities
    "material entity":                            "BFO:0000040",
    "processed material":                         "BFO:0000040",
    "manufactured product":                       "BFO:0000040",
    "fiat part":                                  "BFO:0000040",
    "fiat part of the wound":                     "BFO:0000040",
    "suspension":                                 "BFO:0000040",
    "suture thread":                              "BFO:0000040",
    "suture needle":                              "BFO:0000040",
    # Immaterial / spatial
    "immaterial entity":                          "BFO:0000141",
    "spatial region":                             "BFO:0000006",
    "three-dimensional spatial region":           "BFO:0000028",
    "wound cavity":                               "BFO:0000028",
    # Qualities
    "quality":                                    "BFO:0000019",
    "pain":                                       "BFO:0000019",
    "liquid":                                     "BFO:0000019",
    "solid":                                      "BFO:0000019",
    "size":                                       "PATO:0000117",
    "wound size":                                 "PATO:0000117",
    "wound length":                               "PATO:0001708",
    "wound depth":                                "PATO:0001595",
    "wound cavity volume":                        "PATO:0000918",
    "temperature":                                "PATO:0000146",
    "wound temperature":                          "PATO:0000146",
    "color":                                      "PATO:0000014",
    "wound color":                                "PATO:0000014",
    "viscosity":                                  "PATO:0001417",
    "wound exudate viscosity":                    "PATO:0001417",
    "odor":                                       "PATO:0001323",
    "wound odor":                                 "PATO:0001323",
    "tissue swelling":                            "PATO:0001450",
    # Dispositions / Roles / Functions
    "disposition":                                "BFO:0000016",
    "disease":                                    "BFO:0000016",
    "role":                                       "BFO:0000023",
    "medical personnel role":                     "BFO:0000023",
    "medical personnel function":                 "BFO:0000023",
    "function":                                   "BFO:0000034",
    # Processes
    "pathological process":                       "BFO:0000015",
    "wound related pathological process":         "BFO:0000015",
    "wound related pathologial process":          "BFO:0000015",
    "planned process":                            "COB:0000082",
    "taking a photograph of the wound":           "COB:0000082",
    "wound inspection process":                   "COB:0000082",
    "wound drain reservoir content assessment process": "COB:0000082",
    "wound dressing inspection process":          "COB:0000082",
    "biological_process":                         "GO:0008150",
    # Devices / Drugs
    "device":                                     "COB:0001300",
    "medical device":                             "COB:0001300",
    "implanted device":                           "COB:0001300",
    "drug product":                               "DRON:00000001",
    "dosage form":                                "DRON:00000005",
    "semi-solid dosage form":                     "DRON:00000005",
    "liquid dosage form":                         "DRON:00000005",
    "solution":                                   "DRON:00000005",
}


def _curie_to_iri(curie: str) -> URIRef:
    prefix, local = curie.split(":", 1)
    return URIRef(PREFIX_MAP[prefix] + local)


class UpperStubReplacer:
    """Replace WOND_120xxx structural stubs with external OBO IRIs."""

    @staticmethod
    def is_stub(iri: URIRef) -> bool:
        return str(iri).startswith(STUB_BASE)

    @staticmethod
    def is_ext(iri: URIRef) -> bool:
        return any(str(iri).startswith(b) for b in EXT_BASES)

    @staticmethod
    def is_domain(iri: URIRef) -> bool:
        s = str(iri)
        if not s.startswith(WOND_BASE):
            return False
        try:
            return int(s.split("WOND_")[1]) in DOMAIN_RANGE
        except ValueError:
            return False

    def replace(self, g: Graph, dry_run: bool = False) -> dict[str, int]:
        """Apply all four steps in place. Returns stats dict."""
        stats = {
            "redirected": 0, "artifacts_removed": 0,
            "stubs_removed": 0, "orphan_fixed": 0,
        }

        # Step 1: map stubs → external IRIs
        stub_to_ext: dict[URIRef, URIRef] = {}
        unmapped: list[tuple[str, str]] = []
        for cls in list(g.subjects(RDF.type, OWL.Class)):
            if not self.is_stub(cls):
                continue
            label = str(g.value(cls, RDFS.label) or "").lower().strip()
            curie  = UPPER_KNOWN.get(label)
            if curie:
                stub_to_ext[cls] = _curie_to_iri(curie)
            else:
                unmapped.append((str(cls), label))

        print(f"Step 1 — replacing {len(stub_to_ext)} upper stubs:")
        for stub_iri, ext_iri in stub_to_ext.items():
            stub_label = str(g.value(stub_iri, RDFS.label) or "")
            ext_short  = str(ext_iri).split("/obo/")[1]
            print(f"  {stub_label!r:55s} → {ext_short}")
            if not dry_run:
                g.add((ext_iri, RDF.type, OWL.Class))
                for s, p, o in list(g.triples((None, None, stub_iri))):
                    g.remove((s, p, o))
                    g.add((s, p, ext_iri))
                    stats["redirected"] += 1
                for triple in list(g.triples((stub_iri, None, None))):
                    g.remove(triple)

        if unmapped:
            print(f"\n  WARNING: {len(unmapped)} stubs had no mapping:")
            for iri, label in unmapped:
                print(f"    {label!r}  ({iri})")

        if dry_run:
            return stats

        # Step 2: remove artifact ext→domain and ext→ext subClassOf axioms
        for s, p, o in list(g.triples((None, RDFS.subClassOf, None))):
            if self.is_ext(s) and (self.is_domain(o) or self.is_ext(o)):
                g.remove((s, p, o))
                stats["artifacts_removed"] += 1
        print(f"\nStep 2 — removed {stats['artifacts_removed']} artifact subClassOf axioms")

        # Step 3: remove dangling external MIREOT stubs (rdf:type owl:Class only)
        for cls in list(g.subjects(RDF.type, OWL.Class)):
            if not self.is_ext(cls):
                continue
            triples = list(g.triples((cls, None, None)))
            if len(triples) == 1 and triples[0][1] == RDF.type:
                g.remove(triples[0])
                stats["stubs_removed"] += 1
        print(f"Step 3 — removed {stats['stubs_removed']} dangling external MIREOT stubs")

        # Step 4: fix rootless WOND_0000249 'process'
        process_iri = URIRef(WOND_BASE + "0000249")
        bfo_process = URIRef(OBO_BASE + "BFO_0000015")
        label = str(g.value(process_iri, RDFS.label) or "")
        if g.value(process_iri, RDFS.subClassOf) is None:
            print(f"\nStep 4 — WOND_0000249 {label!r} has no parent → "
                  f"adding rdfs:subClassOf BFO_0000015")
            g.add((bfo_process, RDF.type, OWL.Class))
            g.add((process_iri, RDFS.subClassOf, bfo_process))
            stats["orphan_fixed"] += 1
        else:
            print(f"\nStep 4 — WOND_0000249 {label!r} already has parents, skipping")

        return stats

    def run(
        self,
        source: str | Path,
        output: str | Path | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Load *source*, apply replacements, write to *output* (default: overwrite source)."""
        source = Path(source)
        output = Path(output) if output else source

        print(f"Loading {source} …")
        g = Graph()
        fmt = "turtle" if source.suffix in (".ttl", ".turtle") else "xml"
        g.parse(str(source), format=fmt)
        print(f"  {len(g)} triples")

        stats = self.replace(g, dry_run=dry_run)

        if dry_run:
            print("\n[dry-run] No files written.")
            return stats

        output.parent.mkdir(parents=True, exist_ok=True)
        g.serialize(str(output), format=fmt)
        print(f"\nWritten → {output}  ({len(g)} triples)")
        return stats
