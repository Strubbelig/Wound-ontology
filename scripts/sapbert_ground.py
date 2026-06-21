"""Ground WOND domain classes using SapBERT entity linking.

Two steps per domain class
--------------------------
1. BFO subClassOf — derived by traversing the intra-WOND hierarchy upward
   until an external IRI is reached (no model needed).

2. External xref — SapBERT cosine-similarity match against local OBO/OWL
   files.  The target ontology set is chosen based on the BFO root IRI:

     BFO:0000040  MaterialEntity  → CHEBI, FMA, OBI
     BFO:0000015  Process         → GO, OBI
     BFO:0000019  Quality         → PATO, HP
     BFO:0000016  Disposition     → DOID, HP
     BFO:0000023  Role            → OBI
     BFO:0000034  Function        → OBI
     OBI:0000011  PlannedProcess  → OBI
     OBI:0000968  Device          → OBI
     GO:0008150   BiologicalProc  → GO
     PATO:*       Quality         → PATO
     IAO:*        InfoEntity      → (skip — no local IAO file)
     DRON:*       Drug            → CHEBI  (DRON not in local files)
     BFO:0000028  3D region       → FMA
     BFO:0000141  ImmaterialEnt   → FMA
     BFO:0000031  GenDepCont      → (skip)
     BFO:0000006  SpatialRegion   → FMA

Output
------
Adds to output/owl/ground_truth.owl:
  rdfs:subClassOf  <BFO/OBI/GO/PATO/…>   (from hierarchy traversal)
  oboInOwl:hasDbXref  "PREFIX:NNNNNNN"   (top SapBERT match)

Cache
-----
data/cache/sapbert_grounding.json — keyed by WOND IRI; delete to re-run.

Usage
-----
  python scripts/sapbert_ground.py [--dry-run] [--threshold 0.85] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT        = Path(__file__).resolve().parent.parent
OWL_PATH    = ROOT / "output" / "owl" / "ground_truth.owl"
ONTO_DIR    = Path("/Users/Strubbelig/Library/Mobile Documents/com~apple~CloudDocs/Forschung/Flap ontology/Import-Ontologien")
CACHE_PATH  = ROOT / "data" / "cache" / "sapbert_grounding.json"

WOND_BASE = "http://purl.obolibrary.org/obo/WOND_"
OBOA      = Namespace("http://www.geneontology.org/formats/oboInOwl#")
HAS_XREF  = OBOA["hasDbXref"]
HAS_SYN   = OBOA["hasExactSynonym"]

EXT_PREFIXES = {
    "BFO_":      "http://purl.obolibrary.org/obo/BFO_",
    "IAO_":      "http://purl.obolibrary.org/obo/IAO_",
    "OBI_":      "http://purl.obolibrary.org/obo/OBI_",
    "GO_":       "http://purl.obolibrary.org/obo/GO_",
    "PATO_":     "http://purl.obolibrary.org/obo/PATO_",
    "DRON_":     "http://purl.obolibrary.org/obo/DRON_",
}

# BFO/external root IRI prefix → list of ontology keys to search
ROOT_TO_ONTOS: dict[str, list[str]] = {
    "BFO_0000040": ["chebi", "fma", "obi"],   # MaterialEntity
    "BFO_0000015": ["go", "obi"],              # Process
    "BFO_0000019": ["pato", "hp"],             # Quality
    "BFO_0000016": ["doid", "hp"],             # Disposition
    "BFO_0000023": ["obi"],                    # Role
    "BFO_0000034": ["obi"],                    # Function
    "OBI_0000011": ["obi"],                    # PlannedProcess
    "OBI_0000968": ["obi"],                    # Device
    "GO_0008150":  ["go"],                     # BiologicalProcess
    "BFO_0000028": ["fma"],                    # 3DSpatialRegion
    "BFO_0000141": ["fma"],                    # ImmaterialEntity
    "BFO_0000006": ["fma"],                    # SpatialRegion
    "DRON_":       ["chebi"],                  # Drug → CHEBI fallback
    "PATO_":       ["pato"],                   # Quality subtype
    "IAO_":        [],                         # no local IAO file
    "BFO_0000031": [],                         # GenDepContinuant — skip
}

ONTO_FILES: dict[str, Path] = {
    "chebi": ONTO_DIR / "chebi.obo",
    "doid":  ONTO_DIR / "doid.owl",
    "fma":   ONTO_DIR / "fma.owl",
    "go":    ONTO_DIR / "go.obo",
    "hp":    ONTO_DIR / "hp.obo",
    "obi":   ONTO_DIR / "OBI.rdf",
    "pato":  ONTO_DIR / "pato.owl",
}

# ---------------------------------------------------------------------------
# Ontology term extraction
# ---------------------------------------------------------------------------

def _parse_obo(path: Path) -> list[tuple[str, str]]:
    """Extract (label, CURIE) pairs from an .obo file."""
    terms: list[tuple[str, str]] = []
    in_term = False
    cur_id = cur_name = None
    synonyms: list[str] = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if line == "[Term]":
                if in_term and cur_id and cur_name:
                    terms.append((cur_name, cur_id))
                    for syn in synonyms:
                        terms.append((syn, cur_id))
                in_term = True
                cur_id = cur_name = None
                synonyms = []
            elif line.startswith("[") and line != "[Term]":
                in_term = False
            elif in_term:
                if line.startswith("id: "):
                    raw = line[4:].strip()
                    # Normalise to CURIE (DOID:123 stays, GO:123 stays)
                    cur_id = raw.replace("_", ":")
                elif line.startswith("name: "):
                    cur_name = line[6:].strip()
                elif line.startswith("synonym: "):
                    m = re.search(r'"([^"]+)"', line)
                    if m and "EXACT" in line:
                        synonyms.append(m.group(1))
                elif line.startswith("is_obsolete: true"):
                    cur_id = None  # skip obsolete

    if in_term and cur_id and cur_name:
        terms.append((cur_name, cur_id))
    return terms


def _parse_owl(path: Path, prefix: str) -> list[tuple[str, str]]:
    """Extract (label, CURIE) pairs from an OWL/RDF file."""
    g = Graph()
    fmt = "xml" if str(path).endswith((".rdf", ".owl")) else "turtle"
    g.parse(str(path), format=fmt)

    obo_base = "http://purl.obolibrary.org/obo/"
    terms: list[tuple[str, str]] = []

    for cls in g.subjects(RDF.type, OWL.Class):
        s = str(cls)
        if not s.startswith(obo_base):
            continue
        local = s[len(obo_base):]   # e.g. "DOID_0001234"
        if not local.startswith(prefix):
            continue
        curie = local.replace("_", ":", 1)  # DOID_0001234 → DOID:0001234
        label = g.value(cls, RDFS.label)
        if label is None:
            continue
        terms.append((str(label), curie))
        # exact synonyms
        for syn in g.objects(cls, OBOA["hasExactSynonym"]):
            terms.append((str(syn), curie))

    return terms


ONTO_PREFIX = {
    "chebi": None,   # .obo
    "go":    None,   # .obo
    "hp":    None,   # .obo
    "doid":  "DOID",
    "fma":   "FMA",
    "obi":   "OBI",
    "pato":  "PATO",
}

_term_cache: dict[str, list[tuple[str, str]]] = {}

def load_onto(key: str) -> list[tuple[str, str]]:
    if key in _term_cache:
        return _term_cache[key]
    path = ONTO_FILES[key]
    prefix = ONTO_PREFIX[key]
    print(f"  Loading {key} from {path.name} …", end=" ", flush=True)
    if prefix is None:
        terms = _parse_obo(path)
    else:
        terms = _parse_owl(path, prefix)
    # Deduplicate labels (keep all, SapBERT handles it)
    print(f"{len(terms)} terms")
    _term_cache[key] = terms
    return terms

# ---------------------------------------------------------------------------
# SapBERT encoder
# ---------------------------------------------------------------------------
SAPBERT_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
_encoder = None

def get_encoder():
    global _encoder
    if _encoder is not None:
        return _encoder
    print(f"  Loading SapBERT ({SAPBERT_MODEL}) …")
    from transformers import AutoTokenizer, AutoModel
    import torch
    tok   = AutoTokenizer.from_pretrained(SAPBERT_MODEL)
    model = AutoModel.from_pretrained(SAPBERT_MODEL)
    model.eval()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)

    def encode(texts: list[str], batch_size: int = 512) -> np.ndarray:
        import torch
        all_embs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            enc = tok(batch, padding=True, truncation=True, max_length=64,
                      return_tensors="pt").to(device)
            with torch.no_grad():
                out = model(**enc)
            cls = out.last_hidden_state[:, 0, :].cpu().numpy()
            all_embs.append(cls)
        return np.vstack(all_embs)

    _encoder = encode
    return _encoder

# ---------------------------------------------------------------------------
# Hierarchy traversal → external root IRI
# ---------------------------------------------------------------------------
def _build_parent_index(g: Graph) -> dict[URIRef, list[URIRef]]:
    idx: dict[URIRef, list[URIRef]] = {}
    for s, _, o in g.triples((None, RDFS.subClassOf, None)):
        idx.setdefault(s, []).append(o)
    return idx

def find_ext_root(iri: URIRef, idx: dict, visited: set | None = None) -> URIRef | None:
    if visited is None:
        visited = set()
    if iri in visited:
        return None
    visited.add(iri)
    for par in idx.get(iri, []):
        s = str(par)
        if any(s.startswith(f"http://purl.obolibrary.org/obo/{p}") for p in EXT_PREFIXES):
            return par
        result = find_ext_root(par, idx, visited)
        if result:
            return result
    return None

def root_to_onto_keys(root_iri: URIRef) -> list[str]:
    """Map an external root IRI to the list of ontologies to search."""
    s = str(root_iri).split("/obo/")[-1]  # e.g. BFO_0000040
    # Exact match first
    if s in ROOT_TO_ONTOS:
        return ROOT_TO_ONTOS[s]
    # Prefix match for PATO_xxx, IAO_xxx, DRON_xxx
    for prefix, keys in ROOT_TO_ONTOS.items():
        if prefix.endswith("_") and s.startswith(prefix):
            return keys
    return []

# ---------------------------------------------------------------------------
# SapBERT matching
# ---------------------------------------------------------------------------

def best_match(
    query: str,
    onto_keys: list[str],
    threshold: float,
) -> tuple[str, float] | None:
    """Return (curie, score) for the best SapBERT match, or None."""
    encode = get_encoder()

    all_labels: list[str] = []
    all_curies: list[str] = []
    for key in onto_keys:
        for label, curie in load_onto(key):
            all_labels.append(label)
            all_curies.append(curie)

    if not all_labels:
        return None

    q_emb  = encode([query])                    # (1, D)
    c_embs = encode(all_labels)                 # (N, D)

    # Cosine similarity
    q_norm = q_emb  / (np.linalg.norm(q_emb,  axis=1, keepdims=True) + 1e-9)
    c_norm = c_embs / (np.linalg.norm(c_embs, axis=1, keepdims=True) + 1e-9)
    sims   = (q_norm @ c_norm.T).squeeze(0)     # (N,)

    best_idx  = int(np.argmax(sims))
    best_sim  = float(sims[best_idx])
    best_curie = all_curies[best_idx]
    best_label = all_labels[best_idx]

    if best_sim < threshold:
        return None
    return best_curie, best_sim

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, threshold: float = 0.85, limit: int = 0) -> None:
    if not OWL_PATH.exists():
        sys.exit(f"ERROR: {OWL_PATH} not found.")

    print(f"Loading {OWL_PATH} …")
    g = Graph()
    g.parse(str(OWL_PATH), format="turtle")
    g.bind("oboInOwl", OBOA)
    print(f"  {len(g)} triples")

    parent_idx = _build_parent_index(g)

    # Collect domain WOND classes
    domain = sorted(
        [(s, str(g.value(s, RDFS.label) or ""))
         for s in g.subjects(RDF.type, OWL.Class)
         if str(s).startswith(WOND_BASE) and int(str(s).split("WOND_")[1]) < 433],
        key=lambda x: x[0],
    )
    print(f"  {len(domain)} domain classes to process")

    # Load cache
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, dict] = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text())
        print(f"  {len(cache)} cached entries")

    n_bfo = n_xref = n_skip = n_err = 0
    processed = 0

    for iri, label in domain:
        iri_str = str(iri)

        if limit and processed >= limit:
            break

        # ── BFO root via hierarchy traversal ────────────────────────────────
        ext_root = find_ext_root(iri, parent_idx)
        if ext_root is None:
            print(f"  [WARN] no BFO root for {label!r}")
            n_err += 1
            continue

        # ── Write rdfs:subClassOf (always, even in cache) ───────────────────
        if not dry_run:
            g.add((ext_root, RDF.type, OWL.Class))
            g.add((iri, RDFS.subClassOf, ext_root))
        root_short = str(ext_root).split("/obo/")[1]
        n_bfo += 1

        # ── SapBERT xref ────────────────────────────────────────────────────
        if iri_str in cache:
            result = cache[iri_str]
        else:
            onto_keys = root_to_onto_keys(ext_root)
            if not onto_keys:
                result = None
            elif dry_run:
                print(f"  [dry-run] {label!r} → {root_short}  search={onto_keys}")
                n_skip += 1
                continue
            else:
                match = best_match(label, onto_keys, threshold)
                result = {"curie": match[0], "score": match[1]} if match else None
            if not dry_run:
                cache[iri_str] = result
                CACHE_PATH.write_text(json.dumps(cache, indent=2))

        if result:
            curie = result["curie"]
            score = result.get("score", 0)
            if not dry_run:
                g.add((iri, HAS_XREF, Literal(curie)))
            print(f"  {label!r:50s} → {root_short:15s}  xref={curie}  ({score:.3f})")
            n_xref += 1
        else:
            print(f"  {label!r:50s} → {root_short:15s}  xref=NONE")
            n_skip += 1

        processed += 1

    print(f"\nDone: {n_bfo} BFO axioms, {n_xref} xrefs, {n_skip} no-match, {n_err} errors")

    if not dry_run:
        g.serialize(str(OWL_PATH), format="turtle")
        print(f"Written → {OWL_PATH}  ({len(g)} triples)")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run",   action="store_true",
                        help="Print plan without loading SapBERT or writing files")
    parser.add_argument("--threshold", type=float, default=0.85,
                        help="Minimum cosine similarity for a match (default 0.85)")
    parser.add_argument("--limit",     type=int, default=0,
                        help="Only process this many domain classes (0 = all)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, threshold=args.threshold, limit=args.limit)
