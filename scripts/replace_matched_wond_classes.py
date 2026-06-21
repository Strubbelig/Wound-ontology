"""Replace WOND domain classes that match external OBO terms.

Two-pass matching
-----------------
Pass 1 — Exact (always runs):
  Any WOND class whose rdfs:label exactly matches (case-insensitive) the
  primary label or an exact synonym of an external OBO class is replaced.

Pass 2 — SapBERT near-match (requires --sapbert):
  Remaining WOND classes are encoded with SapBERT and matched against all
  external OBO term labels.
    similarity ≥ --replace-threshold  → full replacement (like exact match)
    similarity <  threshold           → no action
  (default replace=0.95)

Replacement mechanic (same as replace_upper_stubs.py)
------------------------------------------------------
  • Every triple that referred to the WOND class as OBJECT is rewritten to
    use the external IRI (so child classes inherit the new parent).
  • The WOND class and all its own triples are deleted.
  • A MIREOT stub is added for the external class with rdfs:label and
    IAO:0000115 definition from the local source ontology.

Matching priority (exact pass): DOID > HP > CHEBI > GO > PATO > OBI > FMA
SapBERT pass: searches ALL ontologies jointly; picks global best match.

Run after replace_upper_stubs.py.  Safe to re-run — already-replaced
classes are simply absent from the graph.

Usage:
  python scripts/replace_matched_wond_classes.py [options]

  --synonyms           Also match against oboInOwl:hasExactSynonym in exact pass
  --sapbert            Run SapBERT near-match second pass
  --replace-threshold  Cosine similarity for full replacement (default 0.95)
  --dry-run            Print plan without writing files
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

ROOT     = Path(__file__).resolve().parent.parent
OWL_PATH = ROOT / "output" / "owl" / "ground_truth.owl"
ONTO_DIR = Path("/Users/Strubbelig/Library/Mobile Documents/com~apple~CloudDocs/Forschung/Flap ontology/Import-Ontologien")

WOND_BASE    = "http://purl.obolibrary.org/obo/WOND_"
OBO_BASE     = "http://purl.obolibrary.org/obo/"
IAO_DEF      = URIRef(OBO_BASE + "IAO_0000115")
DEPR         = URIRef("http://www.w3.org/2002/07/owl#deprecated")
OBOA         = Namespace("http://www.geneontology.org/formats/oboInOwl#")
HAS_EXSYN    = OBOA["hasExactSynonym"]
DOMAIN_RANGE = range(1, 433)

PRIORITY = ["DOID", "HP", "CHEBI", "GO", "PATO", "OBI", "FMA"]

ONTO_FILES: dict[str, tuple[Path, str]] = {
    "DOID":  (ONTO_DIR / "doid.owl",  "owl"),
    "HP":    (ONTO_DIR / "hp.obo",    "obo"),
    "CHEBI": (ONTO_DIR / "chebi.obo", "obo"),
    "GO":    (ONTO_DIR / "go.obo",    "obo"),
    "PATO":  (ONTO_DIR / "pato.owl",  "owl"),
    "OBI":   (ONTO_DIR / "obi.owl",   "owl"),
    "FMA":   (ONTO_DIR / "fma.owl",   "owl"),
}

SAPBERT_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"

# ---------------------------------------------------------------------------
# Term index helpers
# ---------------------------------------------------------------------------

TermEntry = tuple[URIRef, str, str | None]   # (iri, preferred_label, definition)


def _load_obo(path: Path, use_synonyms: bool) -> dict[str, TermEntry]:
    index: dict[str, TermEntry] = {}
    in_term = False
    cur_id = cur_name = cur_def = None
    cur_syns: list[str] = []

    def commit():
        if not (cur_id and cur_name):
            return
        iri   = URIRef(OBO_BASE + cur_id.replace(":", "_"))
        entry = (iri, cur_name, cur_def)
        index[cur_name.lower()] = entry
        if use_synonyms:
            for s in cur_syns:
                index.setdefault(s.lower(), entry)

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if line == "[Term]":
                commit()
                in_term, cur_id, cur_name, cur_def = True, None, None, None
                cur_syns = []
            elif line.startswith("[") and line != "[Term]":
                in_term = False
            elif in_term:
                if line.startswith("id: "):
                    cur_id = line[4:].strip()
                elif line.startswith("name: "):
                    cur_name = line[6:].strip()
                elif line.startswith("def: "):
                    m = re.match(r'def: "([^"]+)"', line)
                    if m:
                        cur_def = m.group(1)
                elif use_synonyms and line.startswith("synonym: "):
                    m = re.search(r'"([^"]+)".*EXACT', line)
                    if m:
                        cur_syns.append(m.group(1))
                elif line.startswith("is_obsolete: true"):
                    cur_id = None
    commit()
    return index


def _load_owl(path: Path, prefix: str, use_synonyms: bool) -> dict[str, TermEntry]:
    g = Graph()
    g.parse(str(path), format="xml")
    index: dict[str, TermEntry] = {}
    for cls in g.subjects(RDF.type, OWL.Class):
        s = str(cls)
        if not s.startswith(OBO_BASE):
            continue
        local = s[len(OBO_BASE):]
        if not local.startswith(prefix):
            continue
        if g.value(cls, DEPR):
            continue
        lbl  = g.value(cls, RDFS.label)
        defn = g.value(cls, IAO_DEF)
        if not lbl:
            continue
        entry = (cls, str(lbl), str(defn) if defn else None)
        index[str(lbl).lower()] = entry
        if use_synonyms:
            for syn in g.objects(cls, HAS_EXSYN):
                index.setdefault(str(syn).lower(), entry)
    return index


_idx_cache: dict[str, dict[str, TermEntry]] = {}


def load_index(onto: str, use_synonyms: bool) -> dict[str, TermEntry]:
    key = f"{onto}:{use_synonyms}"
    if key not in _idx_cache:
        path, fmt = ONTO_FILES[onto]
        print(f"  Loading {onto} ({path.name}) …", end=" ", flush=True)
        if fmt == "obo":
            idx = _load_obo(path, use_synonyms)
        else:
            idx = _load_owl(path, onto + "_", use_synonyms)
        print(f"{len(idx)} terms")
        _idx_cache[key] = idx
    return _idx_cache[key]


# ---------------------------------------------------------------------------
# SapBERT encoder
# ---------------------------------------------------------------------------

_encode_fn = None


def get_encoder():
    global _encode_fn
    if _encode_fn:
        return _encode_fn
    print(f"\nLoading SapBERT ({SAPBERT_MODEL}) …")
    import torch
    from transformers import AutoModel, AutoTokenizer
    tok   = AutoTokenizer.from_pretrained(SAPBERT_MODEL)
    model = AutoModel.from_pretrained(SAPBERT_MODEL)
    model.eval()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)

    def _encode(texts: list[str], batch_size: int = 512) -> np.ndarray:
        parts = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            enc = tok(batch, padding=True, truncation=True,
                      max_length=64, return_tensors="pt").to(device)
            import torch
            with torch.no_grad():
                out = model(**enc)
            parts.append(out.last_hidden_state[:, 0, :].cpu().numpy())
        return np.vstack(parts)

    _encode_fn = _encode
    return _encode_fn


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _is_domain(iri: URIRef) -> bool:
    s = str(iri)
    if not s.startswith(WOND_BASE):
        return False
    try:
        return int(s.split("WOND_")[1]) in DOMAIN_RANGE
    except ValueError:
        return False


def _apply_replacement(g: Graph, wond_iri: URIRef,
                        ext_iri: URIRef, ext_label: str,
                        ext_def: str | None) -> None:
    g.add((ext_iri, RDF.type, OWL.Class))
    if not g.value(ext_iri, RDFS.label):
        g.add((ext_iri, RDFS.label, Literal(ext_label)))
    if ext_def and not g.value(ext_iri, IAO_DEF):
        g.add((ext_iri, IAO_DEF, Literal(ext_def)))
    # Rewrite references to WOND class
    for s, p, o in list(g.triples((None, None, wond_iri))):
        g.remove((s, p, o))
        g.add((s, p, ext_iri))
    # Delete WOND class
    for triple in list(g.triples((wond_iri, None, None))):
        g.remove(triple)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    use_synonyms: bool = False,
    use_sapbert: bool = False,
    replace_threshold: float = 0.95,
    dry_run: bool = False,
) -> None:
    if not OWL_PATH.exists():
        sys.exit(f"ERROR: {OWL_PATH} not found.")

    print(f"Loading {OWL_PATH} …")
    with open(OWL_PATH) as f:
        first = f.read(300)
    fmt = "turtle" if first.strip().startswith("@") else "xml"
    g = Graph()
    g.bind("oboInOwl", OBOA)
    g.parse(str(OWL_PATH), format=fmt)
    print(f"  {len(g)} triples\n")

    def current_domain() -> dict[URIRef, str]:
        out = {}
        for s in g.subjects(RDF.type, OWL.Class):
            if not _is_domain(s):
                continue
            lbl = g.value(s, RDFS.label)
            if lbl:
                out[s] = str(lbl)
        return out

    # ── Pass 1: Exact matching ─────────────────────────────────────────────
    print("=== Pass 1: Exact label matching ===")
    print("Loading ontology indexes:")

    domain = current_domain()
    exact_matches: list[tuple[URIRef, str, str, TermEntry]] = []
    indexes: dict[str, dict[str, TermEntry]] = {}

    for wond_iri, label in sorted(domain.items(), key=lambda x: x[1]):
        lower = label.lower().strip()
        for onto in PRIORITY:
            if onto not in indexes:
                indexes[onto] = load_index(onto, use_synonyms)
            hit = indexes[onto].get(lower)
            if hit:
                exact_matches.append((wond_iri, label, onto, hit))
                break

    print(f"\nExact matches: {len(exact_matches)}/{len(domain)}")
    print(f"\n{'WOND label':<45}  {'external':<28}  preferred label")
    print("-" * 90)
    for wond_iri, label, onto, (ext_iri, ext_label, ext_def) in exact_matches:
        short = str(ext_iri).split("/obo/")[1]
        print(f"  {label:<43}  {short:<28}  {ext_label!r}")

    if not dry_run:
        for wond_iri, label, onto, (ext_iri, ext_label, ext_def) in exact_matches:
            _apply_replacement(g, wond_iri, ext_iri, ext_label, ext_def)
        # Clean up ext→WOND artifacts
        for s, p, o in list(g.triples((None, RDFS.subClassOf, None))):
            if (str(s).startswith(OBO_BASE) and not str(s).startswith(WOND_BASE)
                    and str(o).startswith(WOND_BASE)):
                g.remove((s, p, o))
        print(f"\nApplied {len(exact_matches)} exact replacements")

    # ── Pass 2: SapBERT near-matching ─────────────────────────────────────
    if not use_sapbert:
        if dry_run:
            print("\n[dry-run] No files written.")
            return
        _finish(g, fmt)
        return

    print(f"\n=== Pass 2: SapBERT near-matching ===")
    print(f"  replace threshold: {replace_threshold}")

    # Build unified candidate pool from all ontologies
    print("\nBuilding candidate pool:")
    cand_labels: list[str]   = []
    cand_iris:   list[URIRef] = []
    cand_pref:   list[str]   = []
    cand_defs:   list[str | None] = []

    for onto in PRIORITY:
        idx = indexes.get(onto) or load_index(onto, use_synonyms)
        for lbl_lower, (iri, pref, defn) in idx.items():
            cand_labels.append(lbl_lower)
            cand_iris.append(iri)
            cand_pref.append(pref)
            cand_defs.append(defn)

    print(f"  {len(cand_labels)} candidates total")

    # Re-collect remaining domain classes (exact-replaced ones are gone if not dry-run)
    remaining = current_domain()
    if not remaining:
        print("  No remaining WOND classes to match.")
        if dry_run:
            print("\n[dry-run] No files written.")
            return
        _finish(g, fmt)
        return

    encode = get_encoder()
    print(f"\n  Encoding {len(cand_labels)} candidates …")
    cand_embs = encode(cand_labels)

    query_labels = [v for v in remaining.values()]
    query_iris   = [k for k in remaining.keys()]
    print(f"  Encoding {len(query_labels)} query classes …")
    query_embs = encode(query_labels)

    # Cosine similarity
    cand_norm  = cand_embs  / (np.linalg.norm(cand_embs,  axis=1, keepdims=True) + 1e-9)
    query_norm = query_embs / (np.linalg.norm(query_embs, axis=1, keepdims=True) + 1e-9)
    sims       = query_norm @ cand_norm.T    # (n_query, n_cand)

    sapbert_replace: list[tuple[URIRef, str, URIRef, str, str | None, float]] = []

    print(f"\n{'WOND label':<45}  {'sim':>5}  {'action':<10}  external")
    print("-" * 100)
    for qi, (wond_iri, label) in enumerate(zip(query_iris, query_labels)):
        best_idx  = int(np.argmax(sims[qi]))
        best_sim  = float(sims[qi, best_idx])
        ext_iri   = cand_iris[best_idx]
        ext_label = cand_pref[best_idx]
        ext_def   = cand_defs[best_idx]
        short     = str(ext_iri).split("/obo/")[1]

        if best_sim >= replace_threshold:
            action = "REPLACE"
            sapbert_replace.append((wond_iri, label, ext_iri, ext_label, ext_def, best_sim))
        else:
            action = "—"

        if action == "REPLACE":
            print(f"  {label:<43}  {best_sim:.3f}  {short}  {ext_label!r}")

    print(f"\nSapBERT: {len(sapbert_replace)} replacements, "
          f"{len(remaining) - len(sapbert_replace)} below threshold (no action)")

    if dry_run:
        print("\n[dry-run] No files written.")
        return

    for wond_iri, label, ext_iri, ext_label, ext_def, sim in sapbert_replace:
        _apply_replacement(g, wond_iri, ext_iri, ext_label, ext_def)

    # Cleanup
    for s, p, o in list(g.triples((None, RDFS.subClassOf, None))):
        if (str(s).startswith(OBO_BASE) and not str(s).startswith(WOND_BASE)
                and str(o).startswith(WOND_BASE)):
            g.remove((s, p, o))

    _finish(g, fmt)


def _finish(g: Graph, fmt: str) -> None:
    remaining = [
        s for s in g.subjects(RDF.type, OWL.Class)
        if _is_domain(s)
    ]

    def reaches_ext(iri, visited=None):
        if visited is None: visited = set()
        if iri in visited: return False
        visited.add(iri)
        s = str(iri)
        if s.startswith(OBO_BASE) and not s.startswith(WOND_BASE): return True
        parent_idx = {}  # lazy; just check directly
        for par in g.objects(iri, RDFS.subClassOf):
            if reaches_ext(par, visited): return True
        return False

    grounded = sum(1 for iri in remaining if reaches_ext(iri))
    print(f"\nRemaining WOND domain classes: {len(remaining)}")
    print(f"  {grounded}/{len(remaining)} reach an external IRI via subClassOf")

    g.serialize(str(OWL_PATH), format=fmt)
    print(f"\nWritten → {OWL_PATH}  ({len(g)} triples)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--synonyms", action="store_true",
                        help="Also match against exact synonyms in exact pass")
    parser.add_argument("--sapbert", action="store_true",
                        help="Run SapBERT near-match second pass")
    parser.add_argument("--replace-threshold", type=float, default=0.95,
                        help="SapBERT cosine similarity for full replacement (default 0.95)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without writing files")
    args = parser.parse_args()
    run(
        use_synonyms=args.synonyms,
        use_sapbert=args.sapbert,
        replace_threshold=args.replace_threshold,
        dry_run=args.dry_run,
    )
