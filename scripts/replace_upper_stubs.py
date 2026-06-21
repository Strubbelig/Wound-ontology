"""Replace WOND upper-class stubs with their actual external IRIs.

The WOND ontology contains structural stubs at
  http://purl.obolibrary.org/obo/wond/ground_truth.owl/WOND_120xxx
for standard ontology classes like 'material entity', 'quality',
'planned process', etc.  This script:

  1. Replaces each stub with the corresponding external IRI (BFO, IAO, OBI,
     GO, PATO, DRON) — rewriting every rdfs:subClassOf that pointed to the stub.
  2. Deletes the stub class and all its triples.
  3. Strips artifact axioms produced when stubs had domain-class parents
     (e.g. ext_iri rdfs:subClassOf wond_domain_class).
  4. Removes dangling external MIREOT stubs (nothing but rdf:type owl:Class).
  5. Adds rdfs:subClassOf BFO:0000015 to WOND_0000249 'process' (rootless orphan).

Source → output:
  data/raw/<latest>.ttl  →  output/owl/ground_truth.owl

Usage:
  python scripts/replace_upper_stubs.py [--source path/to/file.ttl] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT        = Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "data" / "raw" / "ground_truth_2606192019.ttl"
OWL_PATH    = ROOT / "output" / "owl" / "ground_truth.owl"

WOND_BASE    = "http://purl.obolibrary.org/obo/WOND_"
STUB_BASE    = "http://purl.obolibrary.org/obo/wond/ground_truth.owl/WOND_120"
DOMAIN_RANGE = range(1, 433)

OBOA     = Namespace("http://www.geneontology.org/formats/oboInOwl#")
HAS_XREF = OBOA["hasDbXref"]

EXT_BASES = [
    "http://purl.obolibrary.org/obo/BFO_",
    "http://purl.obolibrary.org/obo/IAO_",
    "http://purl.obolibrary.org/obo/OBI_",
    "http://purl.obolibrary.org/obo/GO_",
    "http://purl.obolibrary.org/obo/PATO_",
    "http://purl.obolibrary.org/obo/DRON_",
    "http://purl.obolibrary.org/obo/DOID_",
    "http://purl.obolibrary.org/obo/HP_",
    "http://purl.obolibrary.org/obo/CHEBI_",
    "http://purl.obolibrary.org/obo/OGMS_",
    "http://purl.obolibrary.org/obo/NCBITaxon_",
    "http://purl.obolibrary.org/obo/FMA_",
    "http://snomed.info/id/",
]

PREFIX_MAP = {
    "BFO":  "http://purl.obolibrary.org/obo/BFO_",
    "IAO":  "http://purl.obolibrary.org/obo/IAO_",
    "OBI":  "http://purl.obolibrary.org/obo/OBI_",
    "GO":   "http://purl.obolibrary.org/obo/GO_",
    "PATO": "http://purl.obolibrary.org/obo/PATO_",
    "COB":  "http://purl.obolibrary.org/obo/COB_",
    "DRON": "http://purl.obolibrary.org/obo/DRON_",
}

# ---------------------------------------------------------------------------
# Stub → external CURIE mapping (all 57 WOND_120xxx stubs by lowercased label)
# ---------------------------------------------------------------------------
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
    "pain":                                       "BFO:0000019",   # new
    "liquid":                                     "BFO:0000019",   # new — physical state quality
    "solid":                                      "BFO:0000019",   # new — physical state quality
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
    # Dispositions / Diseases
    "disposition":                                "BFO:0000016",
    "disease":                                    "BFO:0000016",
    # Roles / Functions
    "role":                                       "BFO:0000023",
    "medical personnel role":                     "BFO:0000023",   # old label fallback
    "medical personnel function":                 "BFO:0000023",   # new label
    "function":                                   "BFO:0000034",
    # Processes
    "pathological process":                       "BFO:0000015",
    "wound related pathological process":         "BFO:0000015",
    "wound related pathologial process":          "BFO:0000015",   # typo in source
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


def curie_to_iri(curie: str) -> URIRef:
    prefix, local = curie.split(":", 1)
    return URIRef(PREFIX_MAP[prefix] + local)


def is_ext(iri) -> bool:
    return any(str(iri).startswith(b) for b in EXT_BASES)


def is_stub(iri) -> bool:
    return str(iri).startswith(STUB_BASE)


def is_domain(iri) -> bool:
    s = str(iri)
    if not s.startswith(WOND_BASE):
        return False
    try:
        return int(s.split("WOND_")[1]) in DOMAIN_RANGE
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(source: Path, dry_run: bool = False) -> None:
    if not source.exists():
        sys.exit(f"ERROR: {source} not found.")

    print(f"Loading {source} …")
    g = Graph()
    fmt = "turtle" if source.suffix in (".ttl", ".turtle") else "xml"
    g.parse(str(source), format=fmt)
    g.bind("oboInOwl", OBOA)
    print(f"  {len(g)} triples")

    # ------------------------------------------------------------------
    # Step 1: Collect stubs and map to external IRIs
    # ------------------------------------------------------------------
    stub_to_ext: dict[URIRef, URIRef] = {}
    unmapped: list[tuple[str, str]] = []

    for cls in list(g.subjects(RDF.type, OWL.Class)):
        if not is_stub(cls):
            continue
        label = str(g.value(cls, RDFS.label) or "").lower().strip()
        curie  = UPPER_KNOWN.get(label)
        if curie:
            stub_to_ext[cls] = curie_to_iri(curie)
        else:
            unmapped.append((str(cls), label))

    print(f"\nStep 1 — replacing {len(stub_to_ext)} upper stubs:")
    redirected = 0
    for stub_iri, ext_iri in stub_to_ext.items():
        stub_label = str(g.value(stub_iri, RDFS.label) or "")
        ext_short  = str(ext_iri).split("/obo/")[1]
        print(f"  {stub_label!r:55s} → {ext_short}")
        if dry_run:
            continue
        # MIREOT declaration
        g.add((ext_iri, RDF.type, OWL.Class))
        # Rewrite everything that USE the stub as object
        for s, p, o in list(g.triples((None, None, stub_iri))):
            g.remove((s, p, o))
            g.add((s, p, ext_iri))
            redirected += 1
        # Delete the stub itself
        for triple in list(g.triples((stub_iri, None, None))):
            g.remove(triple)

    if unmapped:
        print(f"\n  WARNING: {len(unmapped)} stubs had no mapping:")
        for iri, label in unmapped:
            print(f"    {label!r}  ({iri})")

    print(f"  Redirected {redirected} axioms")

    # ------------------------------------------------------------------
    # Step 2: Remove artifact axioms from stubs that had domain parents.
    # After Step 1 the former stub IRI is now an external IRI; if it had
    # a domain-class parent it produced  ext rdfs:subClassOf domain_wond,
    # which is wrong.  Similarly ext→ext artifacts from stub-to-stub chains
    # where both ends were replaced by DIFFERENT external IRIs.
    # ------------------------------------------------------------------
    if not dry_run:
        removed_art = 0
        for s, p, o in list(g.triples((None, RDFS.subClassOf, None))):
            if is_ext(s) and (is_domain(o) or is_ext(o)):
                g.remove((s, p, o))
                removed_art += 1
        print(f"\nStep 2 — removed {removed_art} artifact subClassOf axioms "
              f"(ext→domain and ext→ext)")

    # ------------------------------------------------------------------
    # Step 3: Remove dangling external MIREOT stubs (rdf:type owl:Class only)
    # ------------------------------------------------------------------
    if not dry_run:
        removed_stubs = 0
        for cls in list(g.subjects(RDF.type, OWL.Class)):
            if not is_ext(cls):
                continue
            triples = list(g.triples((cls, None, None)))
            if len(triples) == 1 and triples[0][1] == RDF.type:
                g.remove(triples[0])
                removed_stubs += 1
        print(f"Step 3 — removed {removed_stubs} dangling external MIREOT stubs")

    # ------------------------------------------------------------------
    # Step 4: Fix rootless domain class WOND_0000249 'process'
    # ------------------------------------------------------------------
    process_iri = URIRef(f"{WOND_BASE}0000249")
    bfo_process = URIRef("http://purl.obolibrary.org/obo/BFO_0000015")
    label = str(g.value(process_iri, RDFS.label) or "")
    if g.value(process_iri, RDFS.subClassOf) is None:
        print(f"\nStep 4 — WOND_0000249 {label!r} has no parent → "
              f"adding rdfs:subClassOf BFO_0000015")
        if not dry_run:
            g.add((bfo_process, RDF.type, OWL.Class))
            g.add((process_iri, RDFS.subClassOf, bfo_process))
    else:
        print(f"\nStep 4 — WOND_0000249 {label!r} already has parents, skipping")

    # ------------------------------------------------------------------
    # Summary verification
    # ------------------------------------------------------------------
    if not dry_run:
        # Check all domain classes reach an external IRI via subClassOf chain
        parent_idx: dict[URIRef, list[URIRef]] = {}
        for s, _, o in g.triples((None, RDFS.subClassOf, None)):
            parent_idx.setdefault(s, []).append(o)

        def reaches_ext(iri, visited=None):
            if visited is None: visited = set()
            if iri in visited: return False
            visited.add(iri)
            for par in parent_idx.get(iri, []):
                if is_ext(par): return True
                if reaches_ext(par, visited): return True
            return False

        domain_iris = [
            s for s in g.subjects(RDF.type, OWL.Class)
            if is_domain(s)
        ]
        grounded = sum(1 for iri in domain_iris if reaches_ext(iri))
        print(f"\nVerification: {grounded}/{len(domain_iris)} domain classes "
              f"reach an external IRI via subClassOf chain")

    if dry_run:
        print("\n[dry-run] No files written.")
        return

    OWL_PATH.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(str(OWL_PATH), format="turtle")
    print(f"\nWritten → {OWL_PATH}  ({len(g)} triples)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=SOURCE_PATH,
        help=f"Source TTL file (default: {SOURCE_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing any files",
    )
    args = parser.parse_args()
    run(source=args.source, dry_run=args.dry_run)
