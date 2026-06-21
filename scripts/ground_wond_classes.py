"""Ground WOND classes against reference ontologies using LLM + OAK.

Two-track strategy
------------------
Upper classes  WOND_0000433–0000486 (the former WOND_120xxx structural stubs):
    Known mappings dict (UPPER_KNOWN).  Their labels are standard ontology
    terms so exact mappings are deterministic; OAK is the fallback.

Domain classes WOND_0000001–0000432:
    Direct JSON call via OpenRouter (openai SDK).  The LLM returns:
      bfo_category  — one of the BFO category labels (MaterialEntity, Process, …)
      ref_curie     — best matching CURIE from a reference OBO ontology

Output
------
Adds to output/owl/ground_truth.owl:
  rdfs:subClassOf  <BFO:xxx / IAO:xxx / ...>   (BFO-category anchor)
  oboInOwl:hasDbXref  "CURIE"                  (reference ontology xref)

Cache
-----
data/cache/grounding_cache.json — keyed by WOND IRI; safe to delete to re-run.

Usage
-----
  python scripts/ground_wond_classes.py [--dry-run] [--only-upper] [--model MODEL] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Load .env so API keys are available to LiteLLM / OntoGPT
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# Expose OPENROUTER_API_KEY so LiteLLM can route openrouter/* model names
os.environ.setdefault("OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY", ""))

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

# ---------------------------------------------------------------------------
# Paths & namespaces
# ---------------------------------------------------------------------------
ROOT    = Path(__file__).resolve().parent.parent
OWL_IN  = ROOT / "output" / "owl" / "ground_truth.owl"
CACHE   = ROOT / "data" / "cache" / "grounding_cache.json"
SCHEMA  = ROOT / "config" / "grounding_schema.yaml"

WOND    = Namespace("http://purl.obolibrary.org/obo/WOND_")
BFO     = Namespace("http://purl.obolibrary.org/obo/BFO_")
IAO     = Namespace("http://purl.obolibrary.org/obo/IAO_")
OBI_NS  = Namespace("http://purl.obolibrary.org/obo/OBI_")
GO_NS   = Namespace("http://purl.obolibrary.org/obo/GO_")
PATO_NS = Namespace("http://purl.obolibrary.org/obo/PATO_")
DRON    = Namespace("http://purl.obolibrary.org/obo/DRON_")
OBOA    = Namespace("http://www.geneontology.org/formats/oboInOwl#")

WOND_BASE = "http://purl.obolibrary.org/obo/WOND_"

# ---------------------------------------------------------------------------
# Schema class → BFO parent IRI
# (derived from wound_ontology_schema.yaml is_a chain)
# ---------------------------------------------------------------------------
SCHEMA_CLASS_TO_BFO: dict[str, str] = {
    "WoundLesion":            "BFO:0000040",   # MaterialEntity
    "AnatomicalSite":         "BFO:0000040",
    "WoundMaterial":          "BFO:0000040",
    "WoundDrug":              "BFO:0000040",
    "WoundDevice":            "BFO:0000040",
    "WoundMicroorganism":     "BFO:0000040",
    "WoundRecord":            "BFO:0000031",   # GenericallyDependentContinuant
    "WoundCharacteristic":    "BFO:0000019",   # Quality
    "WoundInfection":         "BFO:0000016",   # Disposition
    "ClinicalRole":           "BFO:0000023",   # Role
    "WoundProcess":           "BFO:0000015",   # Process
    "WoundTreatment":         "BFO:0000015",
    "WoundAssessment":        "BFO:0000015",
    "WoundBiologicalProcess": "BFO:0000015",
    # fallback ancestors from schema
    "MaterialEntity":         "BFO:0000040",
    "Process":                "BFO:0000015",
    "Quality":                "BFO:0000019",
    "Disposition":            "BFO:0000016",
    "Role":                   "BFO:0000023",
    "GenericallyDependentContinuant": "BFO:0000031",
}

def curie_to_iri(curie: str) -> URIRef | None:
    """Convert BFO:0000040 → http://purl.obolibrary.org/obo/BFO_0000040."""
    if ":" not in curie:
        return None
    prefix, local = curie.split(":", 1)
    base_map = {
        "BFO":  "http://purl.obolibrary.org/obo/BFO_",
        "IAO":  "http://purl.obolibrary.org/obo/IAO_",
        "OBI":  "http://purl.obolibrary.org/obo/OBI_",
        "GO":   "http://purl.obolibrary.org/obo/GO_",
        "PATO": "http://purl.obolibrary.org/obo/PATO_",
        "DRON": "http://purl.obolibrary.org/obo/DRON_",
        "DOID": "http://purl.obolibrary.org/obo/DOID_",
        "HP":   "http://purl.obolibrary.org/obo/HP_",
        "CHEBI":"http://purl.obolibrary.org/obo/CHEBI_",
        "OGMS": "http://purl.obolibrary.org/obo/OGMS_",
        "FMA":  "http://purl.obolibrary.org/obo/FMA_",
        "NCBITaxon": "http://purl.obolibrary.org/obo/NCBITaxon_",
    }
    base = base_map.get(prefix.upper())
    if base:
        return URIRef(base + local)
    return None

# ---------------------------------------------------------------------------
# Upper-class OAK grounding
# ---------------------------------------------------------------------------
UPPER_RANGE = range(433, 487)   # WOND_0000433 – WOND_0000486

# Complete coverage of all 54 structural upper classes (WOND_0000433–0000486).
# Keyed by normalised label (lowercase).  OAK is NOT called for these — their
# mappings are deterministic.  BFO:0000040 is used as the fallback for any
# material-entity subtype that has no more specific external term.
UPPER_KNOWN: dict[str, str] = {
    # ── IAO / plan ──────────────────────────────────────────────────────────
    "plan":                                       "IAO:0000104",
    "protocol":                                   "IAO:0000104",
    "information content entity":                 "IAO:0000030",
    "directive information entity":               "IAO:0000033",
    "measurement scale":                          "IAO:0000002",
    "categorical measurement datum":              "IAO:0000244",
    "wound classification grade":                 "IAO:0000244",
    # ── BFO continuant ──────────────────────────────────────────────────────
    "material entity":                            "BFO:0000040",
    "processed material":                         "BFO:0000040",
    "manufactured product":                       "BFO:0000040",
    "fiat part":                                  "BFO:0000040",
    "fiat part of the wound":                     "BFO:0000040",
    "suspension":                                 "BFO:0000040",
    "suture thread":                              "BFO:0000040",
    "suture needle":                              "BFO:0000040",
    "immaterial entity":                          "BFO:0000141",
    "spatial region":                             "BFO:0000006",
    "three-dimensional spatial region":           "BFO:0000028",
    "wound cavity":                               "BFO:0000028",
    "quality":                                    "BFO:0000019",
    "disposition":                                "BFO:0000016",
    "disease":                                    "BFO:0000016",
    "role":                                       "BFO:0000023",
    "medical personnel role":                     "BFO:0000023",
    # ── BFO process ─────────────────────────────────────────────────────────
    "pathological process":                       "BFO:0000015",
    "planned process":                            "OBI:0000011",
    "taking a photograph of the wound":           "OBI:0000011",
    "wound inspection process":                   "OBI:0000011",
    "wound drain reservoir content assessment process": "OBI:0000011",
    "wound dressing inspection process":          "OBI:0000011",
    "wound related pathological process":         "BFO:0000015",
    "biological_process":                         "GO:0008150",
    # ── OBI devices ─────────────────────────────────────────────────────────
    "device":                                     "OBI:0000968",
    "medical device":                             "OBI:0000968",
    "implanted device":                           "OBI:0000968",
    # ── DRON drug products ───────────────────────────────────────────────────
    "drug product":                               "DRON:00000001",
    "dosage form":                                "DRON:00000005",
    "semi-solid dosage form":                     "DRON:00000005",
    "liquid dosage form":                         "DRON:00000005",
    "solution":                                   "DRON:00000005",
    # ── PATO qualities ──────────────────────────────────────────────────────
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
}

def ground_upper_class(label: str) -> dict | None:
    """Look up in UPPER_KNOWN (exact, no OAK download needed for structural classes)."""
    norm = label.lower().strip()
    curie = UPPER_KNOWN.get(norm)
    if curie:
        return {"schema_class": None, "bfo_curie": curie, "ref_curie": curie, "method": "known"}
    # OAK only for BFO/IAO — small databases, no giant downloads
    try:
        from oaklib import get_adapter
        for db in ("sqlite:obo:bfo", "sqlite:obo:iao"):
            try:
                adapter = get_adapter(db)
                hits = list(adapter.basic_search(label, config=None))
                if hits:
                    return {"schema_class": None, "bfo_curie": hits[0],
                            "ref_curie": hits[0], "method": f"oak:{db}"}
            except Exception:
                continue
    except ImportError:
        pass
    return None

# ---------------------------------------------------------------------------
# Domain-class grounding via OntoGPT SPIRES (grounding_schema.yaml)
# ---------------------------------------------------------------------------

# grounding_schema.yaml slot name → BFO CURIE
_SLOT_TO_BFO: dict[str, str] = {
    "material_entity":   "BFO:0000040",
    "process":           "BFO:0000015",
    "quality":           "BFO:0000019",
    "disposition":       "BFO:0000016",
    "role":              "BFO:0000023",
    "information_entity":"BFO:0000031",
}

def _build_spires_engine(model: str):
    from ontogpt.engines.spires_engine import SPIRESEngine
    return SPIRESEngine(template=str(SCHEMA), model=model)

def ground_domain_class(
    label: str,
    parent_label: str | None,
    engine,
    dry_run: bool = False,
) -> dict | None:
    """Run OntoGPT SPIRES against grounding_schema.yaml for one WOND class."""
    if dry_run:
        print(f"    [dry-run] would call OntoGPT for: {label!r}")
        return None
    # Short natural-language sentence — SPIRES extracts entities from text,
    # not from instructions.
    text = f"{label}"
    if parent_label:
        text += f", a type of {parent_label}"
    try:
        result = engine.extract_from_text(text=text)
        if not result or not result.extracted_object:
            return None
        obj = result.extracted_object

        # Walk the concrete category slots to find which one was filled.
        # SPIRES may return the slot value as:
        #   - a Pydantic object with .id  (ideal)
        #   - a plain string (the CURIE directly)
        #   - None (not filled)
        for slot_name, bfo_curie in _SLOT_TO_BFO.items():
            ent = getattr(obj, slot_name, None)
            if ent is None:
                continue
            if isinstance(ent, str):
                ref_curie = ent or None
            else:
                ref_curie = str(ent.id) if getattr(ent, "id", None) else None
            schema_cls = type(ent).__name__
            return {
                "schema_class": schema_cls,
                "bfo_curie":    bfo_curie,
                "ref_curie":    ref_curie,
                "method":       "ontogpt",
            }
        return None
    except Exception as exc:
        print(f"    OntoGPT error for {label!r}: {exc}")
        return None

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, only_upper: bool = False, model: str = "openrouter/deepseek/deepseek-v4-flash", limit: int = 0) -> None:
    if not OWL_IN.exists():
        sys.exit(f"ERROR: {OWL_IN} not found. Run the renumbering script first.")
    if not SCHEMA.exists():
        sys.exit(f"ERROR: {SCHEMA} not found.")

    print(f"Loading {OWL_IN} …")
    g = Graph()
    g.parse(str(OWL_IN), format="turtle")
    HAS_XREF = OBOA["hasDbXref"]

    # Collect all WOND classes
    classes = {}   # IRI → {"label": str, "parent_label": str|None, "n": int}
    for cls in g.subjects(RDF.type, OWL.Class):
        if not str(cls).startswith(WOND_BASE):
            continue
        n = int(str(cls).split("WOND_")[1])
        label = str(g.value(cls, RDFS.label) or "")
        parent = g.value(cls, RDFS.subClassOf)
        parent_label = str(g.value(parent, RDFS.label)) if parent else None
        classes[str(cls)] = {"label": label, "parent_label": parent_label, "n": n}

    print(f"  {len(classes)} WOND classes found")

    # Load cache
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, dict] = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text())
        print(f"  {len(cache)} entries in grounding cache")

    # Initialise OntoGPT engine (only if needed for domain classes)
    engine = None

    n_upper = n_domain = n_skipped = n_error = 0
    n_domain_processed = 0

    for iri_str, info in sorted(classes.items(), key=lambda x: x[1]["n"]):
        iri   = URIRef(iri_str)
        n     = info["n"]
        label = info["label"]
        parent_label = info["parent_label"]

        is_upper = n in UPPER_RANGE
        if only_upper and not is_upper:
            continue
        if iri_str in cache:
            result = cache[iri_str]
        else:
            if is_upper:
                result = ground_upper_class(label)
                n_upper += 1
            else:
                if limit and n_domain_processed >= limit:
                    continue
                if engine is None and not dry_run:
                    print(f"  Initialising OntoGPT SPIRES engine (model={model}) …")
                    engine = _build_spires_engine(model)
                result = ground_domain_class(label, parent_label, engine, dry_run=dry_run)
                n_domain += 1
                n_domain_processed += 1
                if not dry_run:
                    time.sleep(0.5)   # gentle rate limit

            if result:
                cache[iri_str] = result
                if not dry_run:
                    CACHE.write_text(json.dumps(cache, indent=2))
            else:
                n_error += 1
                continue

        if result is None:
            n_skipped += 1
            continue

        # Write grounding axioms into the graph
        bfo_curie = result.get("bfo_curie")
        ref_curie = result.get("ref_curie")

        if bfo_curie:
            ext_iri = curie_to_iri(bfo_curie)
            if ext_iri:
                if not dry_run:
                    g.add((ext_iri, RDF.type, OWL.Class))   # MIREOT stub
                    g.add((iri, RDFS.subClassOf, ext_iri))
                print(f"  [{'upper' if is_upper else 'domain'}] {label!r:45s} "
                      f"-> subClassOf {bfo_curie}")

        if ref_curie and ref_curie != bfo_curie and ref_curie not in ("None", ""):
            if not dry_run:
                g.add((iri, HAS_XREF, Literal(ref_curie)))
            print(f"  {'':47s}   xref {ref_curie}")

    print(f"\nProcessed: {n_upper} upper, {n_domain} domain, "
          f"{n_skipped} skipped, {n_error} errors")

    if not dry_run:
        for prefix, ns in [("wond", WOND), ("BFO", BFO), ("IAO", IAO),
                           ("OBI", OBI_NS), ("GO", GO_NS), ("PATO", PATO_NS),
                           ("DRON", DRON), ("oboInOwl", OBOA)]:
            g.bind(prefix, ns)
        g.serialize(str(OWL_IN), format="turtle")
        print(f"Written  → {OWL_IN}  ({len(g)} triples)")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run",    action="store_true",
                        help="Print what would be done without calling OntoGPT or writing files")
    parser.add_argument("--only-upper", action="store_true",
                        help="Only ground the 54 structural upper classes (no OntoGPT calls)")
    parser.add_argument("--model",      default="openrouter/deepseek/deepseek-v4-flash",
                        help="LLM model for OntoGPT via LiteLLM (default: openrouter/deepseek/deepseek-v4-flash)")
    parser.add_argument("--limit",      type=int, default=0,
                        help="Only process this many domain classes (0 = all)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, only_upper=args.only_upper, model=args.model, limit=args.limit)
