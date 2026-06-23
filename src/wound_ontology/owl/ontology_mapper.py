"""Unified ontology mapping: grounding, replacement, xref, and alignment.

Maps source OWL classes to matching concepts from target ontologies using
one of four methods:

  lexical   — exact rdfs:label / hasExactSynonym match, priority order wins
  sapbert   — cosine similarity via SapBERT; highest-priority match wins
  ontogpt   — OntoGPT SPIRES structured extraction (always mode=subclass)
  llm       — top-K sapbert candidates ranked by LLM via OpenRouter

Three output modes (not applicable to ontogpt, which always uses subclass):

  replace   — source IRI swapped for target IRI (source class removed)
  xref      — source IRI kept, oboInOwl:hasDbXref added pointing to target
  subclass  — source IRI kept, rdfs:subClassOf added pointing to target

Primary API:
    mapper = OntologyMapper(onto_dir)
    mapper.run(source_owl, targets=["DOID", "HP"], method="lexical", mode="replace")

Single-target SSSOM alignment:
    result = mapper.align(source_owl, target="snomed.json")
    mapper.write_sssom(result, out / "alignment.sssom.tsv")
    mapper.extend(result, out / "source_extended.owl")
    mapper.enrich(result, out / "source_extended.owl")
"""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import ClassVar

import numpy as np
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

OBO_BASE  = "http://purl.obolibrary.org/obo/"
OBOA      = Namespace("http://www.geneontology.org/formats/oboInOwl#")
WOND      = Namespace(OBO_BASE + "WOND_")
IAO_DEF   = URIRef(OBO_BASE + "IAO_0000115")
HAS_XREF  = OBOA["hasDbXref"]
HAS_EXSYN = OBOA["hasExactSynonym"]
DEPR      = URIRef("http://www.w3.org/2002/07/owl#deprecated")

SAPBERT_MODEL    = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
_OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_LLM     = "openrouter/deepseek/deepseek-v4-flash"

# prefix → (filename relative to onto_dir, rdflib format)
ONTO_FILES: dict[str, tuple[str, str]] = {
    "BFO":   ("bfo-core.owl", "owl"),
    "COB":   ("cob.owl",      "owl"),
    "IAO":   ("iao.owl",      "owl"),
    "OBI":   ("OBI.rdf",      "owl"),
    "PATO":  ("pato.owl",     "owl"),
    "GO":    ("go.obo",       "obo"),
    "DOID":  ("doid.owl",     "owl"),
    "HP":    ("hp.obo",       "obo"),
    "CHEBI": ("chebi.obo",    "obo"),
    "FMA":        ("fma.owl",              "owl"),
    "NCBITaxon":  ("ncbitaxon_micro.obo",  "obo"),
}

DEFAULT_PRIORITY: list[str] = [
    # Upper-level / foundational first — most abstract wins over derived
    "BFO", "COB", "IAO",
    # Qualities and investigations
    "PATO", "OBI",
    # Taxonomy and chemicals before domain ontologies
    "NCBITaxon", "CHEBI",
    # Domain ontologies last
    "DOID", "HP", "GO", "FMA",
]

PREFIX_MAP: dict[str, str] = {
    "BFO":      OBO_BASE + "BFO_",
    "COB":      OBO_BASE + "COB_",
    "IAO":      OBO_BASE + "IAO_",
    "OBI":      OBO_BASE + "OBI_",
    "PATO":     OBO_BASE + "PATO_",
    "GO":       OBO_BASE + "GO_",
    "DRON":     OBO_BASE + "DRON_",
    "DOID":     OBO_BASE + "DOID_",
    "HP":       OBO_BASE + "HP_",
    "CHEBI":    OBO_BASE + "CHEBI_",
    "FMA":      OBO_BASE + "FMA_",
    "NCBITaxon": OBO_BASE + "NCBITaxon_",
    "OGMS":     OBO_BASE + "OGMS_",
}

# Deterministic label → CURIE used by method="ontogpt" as fast-path
UPPER_KNOWN: dict[str, str] = {
    "plan":                                       "IAO:0000104",
    "protocol":                                   "IAO:0000104",
    "information content entity":                 "IAO:0000030",
    "directive information entity":               "IAO:0000033",
    "measurement scale":                          "IAO:0000109",
    "categorical measurement datum":              "OBI:0000938",
    "wound classification grade":                 "OBI:0000938",
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
    "disposition":                                "BFO:0000016",
    "disease":                                    "BFO:0000016",
    "role":                                       "BFO:0000023",
    "medical personnel role":                     "BFO:0000023",
    "medical personnel function":                 "BFO:0000023",
    "function":                                   "BFO:0000034",
    "pathological process":                       "BFO:0000015",
    "wound related pathological process":         "BFO:0000015",
    "wound related pathologial process":          "BFO:0000015",
    "planned process":                            "COB:0000082",
    "taking a photograph of the wound":           "COB:0000082",
    "wound inspection process":                   "COB:0000082",
    "wound drain reservoir content assessment process": "COB:0000082",
    "wound dressing inspection process":          "COB:0000082",
    "biological_process":                         "GO:0008150",
    "device":                                     "COB:0001300",
    "medical device":                             "COB:0001300",
    "implanted device":                           "COB:0001300",
    "drug product":                               "DRON:00000001",
    "dosage form":                                "DRON:00000005",
    "semi-solid dosage form":                     "DRON:00000005",
    "liquid dosage form":                         "DRON:00000005",
    "solution":                                   "DRON:00000005",
}

# OntoGPT schema slot → BFO CURIE (domain class fallback)
_SLOT_TO_BFO: dict[str, str] = {
    "material_entity":    "BFO:0000040",
    "process":            "BFO:0000015",
    "quality":            "BFO:0000019",
    "disposition":        "BFO:0000016",
    "role":               "BFO:0000023",
    "information_entity": "BFO:0000031",
}

# (iri, preferred_label, definition)
TermEntry = tuple[URIRef, str, str | None]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _iri_to_xref(iri: str) -> str:
    if "snomed.info/id/" in iri:
        return "SNOMEDCT:" + iri.split("snomed.info/id/")[1]
    if "/obo/" in iri:
        local = iri.split("/obo/")[1]
        parts = local.split("_", 1)
        if len(parts) == 2:
            return f"{parts[0]}:{parts[1]}"
    return iri


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class MapMatch:
    source_iri:    URIRef
    source_label:  str
    target_iri:    URIRef
    target_label:  str
    target_prefix: str
    target_def:    str | None
    score:         float    # 1.0 for lexical/known, <1.0 for sapbert/llm
    method:        str      # "lexical" | "sapbert" | "ontogpt" | "llm" | "known"


@dataclass
class MapResult:
    source_owl:         Path
    method:             str
    mode:               str
    matches:            list[MapMatch]
    unmatched:          list[URIRef]
    candidates:         list[dict]           # top-K rows for write_candidates
    # populated by align() only:
    target_path:        Path | None          = None
    target_concepts:    list                 = field(default_factory=list)
    source_label_index: dict[str, URIRef]    = field(default_factory=dict)
    source_max_id:      int                  = 0


# ── OntologyMapper ────────────────────────────────────────────────────────────

class OntologyMapper:
    """Unified ontology mapping: grounding, replacement, xref, and alignment."""

    onto_files: ClassVar[dict[str, tuple[str, str]]] = ONTO_FILES

    # Labels/defs for classes whose source ontology is not in ONTO_FILES
    _HARDCODED_EXTERNAL: ClassVar[dict[str, dict]] = {
        OBO_BASE + "DRON_00000001": {"label": "drug product",          "def": None},
        OBO_BASE + "DRON_00000005": {"label": "clinical drug product", "def": None},
    }

    def __init__(
        self,
        onto_dir: str | Path | None = None,
        priority: list[str] | None = None,
    ) -> None:
        self.onto_dir = Path(onto_dir) if onto_dir else None
        self.priority = priority or DEFAULT_PRIORITY
        self._idx_cache: dict[str, dict[str, TermEntry]] = {}
        self._encoder = None
        self._spires_engine = None

    # ── Graph helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_graph(owl_path: Path) -> Graph:
        with open(owl_path) as f:
            first = f.read(300)
        fmt = "turtle" if first.strip().startswith("@") else "xml"
        g = Graph()
        g.bind("oboInOwl", OBOA)
        g.parse(str(owl_path), format=fmt)
        return g

    @staticmethod
    def _source_classes(g: Graph) -> dict[URIRef, str]:
        """Return {iri: label} for all named owl:Class instances with a label."""
        out: dict[URIRef, str] = {}
        for cls in g.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef):
                continue
            lbl = g.value(cls, RDFS.label)
            if lbl:
                out[cls] = str(lbl)
        return out

    @staticmethod
    def _source_meta(g: Graph) -> tuple[dict[str, URIRef], int]:
        """Return (norm_label_index, max_wond_id) — used by align()."""
        label_index: dict[str, URIRef] = {}
        max_id = 0
        for cls in g.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef) or "WOND_" not in str(cls):
                continue
            suffix = str(cls).split("WOND_")[1]
            if suffix.isdigit():
                max_id = max(max_id, int(suffix))
            for lbl in g.objects(cls, RDFS.label):
                label_index[_norm(str(lbl))] = cls
        return label_index, max_id

    # ── Target index loading ───────────────────────────────────────────────────

    def _load_obo(self, path: Path, use_synonyms: bool) -> dict[str, TermEntry]:
        index: dict[str, TermEntry] = {}
        in_term = False
        cur_id = cur_name = cur_def = None
        cur_syns: list[str] = []

        def _commit() -> None:
            if not (cur_id and cur_name):
                return
            iri   = URIRef(OBO_BASE + cur_id.replace(":", "_"))
            entry: TermEntry = (iri, cur_name, cur_def)
            index[_norm(cur_name)] = entry
            if use_synonyms:
                for s in cur_syns:
                    index.setdefault(_norm(s), entry)

        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip()
                if line == "[Term]":
                    _commit()
                    in_term, cur_id, cur_name, cur_def, cur_syns = True, None, None, None, []
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
        _commit()
        return index

    def _load_owl_index(
        self, path: Path, prefix: str, use_synonyms: bool
    ) -> dict[str, TermEntry]:
        g = Graph()
        g.parse(str(path), format="xml")
        index: dict[str, TermEntry] = {}
        for cls in g.subjects(RDF.type, OWL.Class):
            s = str(cls)
            if not (s.startswith(OBO_BASE) and s[len(OBO_BASE):].startswith(prefix)):
                continue
            if g.value(cls, DEPR):
                continue
            lbl  = g.value(cls, RDFS.label)
            defn = g.value(cls, IAO_DEF)
            if not lbl:
                continue
            entry: TermEntry = (cls, str(lbl), str(defn) if defn else None)
            index[_norm(str(lbl))] = entry
            if use_synonyms:
                for syn in g.objects(cls, HAS_EXSYN):
                    index.setdefault(_norm(str(syn)), entry)
        return index

    def _load_index(
        self, prefix: str, use_synonyms: bool = False
    ) -> dict[str, TermEntry]:
        if self.onto_dir is None:
            raise ValueError("onto_dir required for lexical/sapbert methods")
        key = f"{prefix}:{use_synonyms}"
        if key not in self._idx_cache:
            filename, fmt = self.onto_files[prefix]
            path = self.onto_dir / filename
            print(f"  Loading {prefix} ({filename}) …", end=" ", flush=True)
            idx = (self._load_obo(path, use_synonyms)
                   if fmt == "obo"
                   else self._load_owl_index(path, prefix + "_", use_synonyms))
            print(f"{len(idx)} terms")
            self._idx_cache[key] = idx
        return self._idx_cache[key]

    # ── SapBERT encoder ────────────────────────────────────────────────────────

    def _get_encoder(self):
        if self._encoder:
            return self._encoder
        print(f"Loading SapBERT ({SAPBERT_MODEL}) …")
        import torch
        from transformers import AutoModel, AutoTokenizer
        tok   = AutoTokenizer.from_pretrained(SAPBERT_MODEL)
        model = AutoModel.from_pretrained(SAPBERT_MODEL)
        model.eval()
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        model.to(device)
        default_batch = 32 if device == "mps" else 512

        def _encode(texts: list[str], batch_size: int = default_batch) -> np.ndarray:
            parts = []
            for i in range(0, len(texts), batch_size):
                enc = tok(
                    texts[i : i + batch_size],
                    padding=True, truncation=True,
                    max_length=64, return_tensors="pt",
                ).to(device)
                with torch.no_grad():
                    out = model(**enc)
                parts.append(out.last_hidden_state[:, 0, :].cpu().numpy())
            return np.vstack(parts)

        self._encoder = _encode
        return self._encoder

    # ── IRI / CURIE helpers ────────────────────────────────────────────────────

    @staticmethod
    def curie_to_iri(curie: str) -> URIRef | None:
        """'BFO:0000040' → http://purl.obolibrary.org/obo/BFO_0000040."""
        if ":" not in curie:
            return None
        prefix, local = curie.split(":", 1)
        base = PREFIX_MAP.get(prefix.upper())
        return URIRef(base + local) if base else None

    @staticmethod
    def _is_external(iri: str) -> bool:
        return iri.startswith(OBO_BASE) and not iri.startswith(OBO_BASE + "WOND_")

    # ── Matching ───────────────────────────────────────────────────────────────

    def _match_lexical(
        self,
        source_classes: dict[URIRef, str],
        targets: list[str],
        use_synonyms: bool,
        top_k: int = 5,
    ) -> tuple[list[MapMatch], list[dict]]:
        """Exact label matching.  Iterates targets in priority order; first hit wins."""
        matches:      list[MapMatch] = []
        candidates:   list[dict]    = []
        matched_iris: set[URIRef]   = set()

        # Build per-target index, collect all hits for candidate CSV
        per_target: dict[str, list[tuple[URIRef, str, TermEntry]]] = {p: [] for p in targets}
        for prefix in targets:
            idx = self._load_index(prefix, use_synonyms)
            for src_iri, src_lbl in source_classes.items():
                hit = idx.get(_norm(src_lbl))
                if hit:
                    per_target[prefix].append((src_iri, src_lbl, hit))
                    tgt_iri, tgt_lbl, _ = hit
                    candidates.append({
                        "source_iri": str(src_iri), "source_label": src_lbl,
                        "target_iri": str(tgt_iri), "target_label": tgt_lbl,
                        "score": 1.0, "method": "lexical",
                    })

        # Apply priority: first target that matched wins
        for prefix in targets:
            for src_iri, src_lbl, (tgt_iri, tgt_lbl, tgt_def) in per_target[prefix]:
                if src_iri not in matched_iris:
                    matches.append(MapMatch(
                        source_iri=src_iri, source_label=src_lbl,
                        target_iri=tgt_iri, target_label=tgt_lbl,
                        target_prefix=prefix, target_def=tgt_def,
                        score=1.0, method="lexical",
                    ))
                    matched_iris.add(src_iri)

        return matches, candidates

    def _match_sapbert(
        self,
        source_classes: dict[URIRef, str],
        targets: list[str],
        threshold: float,
        top_k: int = 5,
    ) -> tuple[list[MapMatch], list[dict]]:
        """Embedding cosine similarity.  Priority order breaks ties above threshold."""
        encode = self._get_encoder()
        priority_rank = {p: i for i, p in enumerate(targets)}

        # Combined target corpus: (prefix, TermEntry)
        cand_labels:  list[str]                        = []
        cand_entries: list[tuple[str, TermEntry]]      = []
        for prefix in targets:
            for lbl, entry in self._load_index(prefix).items():
                cand_labels.append(lbl)
                cand_entries.append((prefix, entry))

        if not cand_labels:
            return [], []

        src_iris   = list(source_classes.keys())
        src_labels = [_norm(l) for l in source_classes.values()]

        print(f"  Embedding {len(src_labels)} source + {len(cand_labels)} target labels …")
        all_embs   = encode(src_labels + cand_labels)
        src_embs   = all_embs[:len(src_labels)]
        cand_embs  = all_embs[len(src_labels):]

        src_norm  = src_embs  / (np.linalg.norm(src_embs,  axis=1, keepdims=True) + 1e-9)
        cand_norm = cand_embs / (np.linalg.norm(cand_embs, axis=1, keepdims=True) + 1e-9)
        sims      = src_norm @ cand_norm.T   # (n_src, n_cand)

        matches:    list[MapMatch] = []
        candidates: list[dict]    = []

        for qi, (src_iri, src_lbl) in enumerate(
            zip(src_iris, source_classes.values())
        ):
            top_js = np.argsort(sims[qi])[::-1][:top_k]

            # Candidate CSV rows
            for j in top_js:
                score = float(sims[qi, j])
                if score <= 0:
                    break
                prefix, (tgt_iri, tgt_lbl, _) = cand_entries[j]
                candidates.append({
                    "source_iri": str(src_iri), "source_label": src_lbl,
                    "target_iri": str(tgt_iri), "target_label": tgt_lbl,
                    "score": round(score, 4), "method": "sapbert",
                })

            # Best match respecting priority
            above = [
                (int(j), float(sims[qi, j]))
                for j in top_js
                if float(sims[qi, j]) >= threshold
            ]
            if above:
                best_j, best_score = min(
                    above,
                    key=lambda x: (priority_rank.get(cand_entries[x[0]][0], 999), -x[1]),
                )
                prefix, (tgt_iri, tgt_lbl, tgt_def) = cand_entries[best_j]
                matches.append(MapMatch(
                    source_iri=src_iri, source_label=src_lbl,
                    target_iri=tgt_iri, target_label=tgt_lbl,
                    target_prefix=prefix, target_def=tgt_def,
                    score=best_score, method="sapbert",
                ))

        return matches, candidates

    def _match_ontogpt(
        self,
        source_classes: dict[URIRef, str],
        g: Graph,
        model: str,
        schema_path: Path,
        cache: dict,
        dry_run: bool,
    ) -> list[MapMatch]:
        """BFO placement via UPPER_KNOWN dict (fast) + OntoGPT SPIRES (fallback).

        Always produces mode=subclass results.
        Cache maps source IRI string → {bfo_curie, ref_curie, method}.
        """
        matches: list[MapMatch] = []

        for src_iri, src_lbl in sorted(source_classes.items(), key=lambda x: str(x[0])):
            iri_str = str(src_iri)
            cached  = cache.get(iri_str)

            if cached is None:
                # Fast path: deterministic dict
                curie = UPPER_KNOWN.get(_norm(src_lbl))
                if curie:
                    cached = {"bfo_curie": curie, "ref_curie": curie, "method": "known"}
                else:
                    # OntoGPT SPIRES fallback
                    if dry_run:
                        continue
                    if self._spires_engine is None:
                        from ontogpt.engines.spires_engine import SPIRESEngine
                        self._spires_engine = SPIRESEngine(
                            template=str(schema_path), model=model
                        )
                    parent     = g.value(src_iri, RDFS.subClassOf)
                    parent_lbl = str(g.value(parent, RDFS.label)) if parent else None
                    text       = src_lbl + (f", a type of {parent_lbl}" if parent_lbl else "")
                    try:
                        result = self._spires_engine.extract_from_text(text=text)
                        obj    = result.extracted_object if result else None
                        cached = None
                        if obj:
                            for slot, bfo_curie in _SLOT_TO_BFO.items():
                                ent = getattr(obj, slot, None)
                                if ent is None:
                                    continue
                                ref = str(ent.id) if getattr(ent, "id", None) else (
                                    ent if isinstance(ent, str) else None
                                )
                                cached = {"bfo_curie": bfo_curie, "ref_curie": ref,
                                          "method": "ontogpt"}
                                break
                    except Exception as exc:
                        print(f"    [ontogpt error] {src_lbl!r}: {exc}")
                    time.sleep(0.5)

                if cached and not dry_run:
                    cache[iri_str] = cached

            if not cached:
                continue

            bfo_curie = cached.get("bfo_curie")
            ref_curie = cached.get("ref_curie")
            tgt_iri   = self.curie_to_iri(bfo_curie) if bfo_curie else None
            if tgt_iri is None:
                continue

            ref_iri = self.curie_to_iri(ref_curie) if (
                ref_curie and ref_curie not in (bfo_curie, "None", "")
            ) else None

            print(f"  {src_lbl!r:45s} → subClassOf {bfo_curie}"
                  + (f"  xref {ref_curie}" if ref_iri else ""))

            matches.append(MapMatch(
                source_iri=src_iri, source_label=src_lbl,
                target_iri=tgt_iri, target_label=bfo_curie,
                target_prefix=bfo_curie.split(":")[0] if ":" in bfo_curie else "",
                target_def=ref_curie if ref_iri else None,   # reuse field for xref curie
                score=1.0, method=cached["method"],
            ))

        return matches

    def _match_llm(
        self,
        source_classes: dict[URIRef, str],
        targets: list[str],
        threshold: float,
        model: str,
        api_key: str,
        top_k: int = 5,
    ) -> tuple[list[MapMatch], list[dict]]:
        """SapBERT top-K candidates ranked by LLM via OpenRouter."""
        import requests as _req

        # Get sapbert candidates (no threshold — just scores for the LLM to judge)
        _, candidates = self._match_sapbert(
            source_classes, targets, threshold=0.0, top_k=top_k
        )

        # Group candidates by source IRI
        from collections import defaultdict
        by_src: dict[str, list[dict]] = defaultdict(list)
        for row in candidates:
            by_src[row["source_iri"]].append(row)

        src_lookup = {str(iri): (iri, lbl) for iri, lbl in source_classes.items()}
        matches:    list[MapMatch] = []

        for iri_str, cands in by_src.items():
            src_iri, src_lbl = src_lookup[iri_str]
            numbered = "\n".join(
                f"  [{i+1}] {c['target_label']} ({c['target_iri']})"
                for i, c in enumerate(cands)
            )
            prompt = (
                f"You are matching ontology terms.\n"
                f"Source concept: \"{src_lbl}\"\n"
                f"Candidates:\n{numbered}\n\n"
                f"Which candidate best matches the source concept in meaning?\n"
                f"Reply with ONLY the candidate number (1–{len(cands)}) "
                f"or 0 if none are a good match."
            )
            try:
                resp = _req.post(
                    url=_OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "max_tokens": 4,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                choice = resp.json()["choices"][0]["message"]["content"].strip()
                idx    = int(re.search(r"\d+", choice).group()) - 1
            except Exception as exc:
                print(f"    [llm error] {src_lbl!r}: {exc}")
                continue

            if 0 <= idx < len(cands):
                c = cands[idx]
                tgt_iri    = URIRef(c["target_iri"])
                tgt_prefix = c.get("target_prefix", "")
                # Look up definition from index
                try:
                    idx_entry = self._load_index(tgt_prefix).get(_norm(c["target_label"]))
                    tgt_def   = idx_entry[2] if idx_entry else None
                except Exception:
                    tgt_def = None
                matches.append(MapMatch(
                    source_iri=src_iri, source_label=src_lbl,
                    target_iri=tgt_iri, target_label=c["target_label"],
                    target_prefix=tgt_prefix, target_def=tgt_def,
                    score=c["score"], method="llm",
                ))

        return matches, candidates

    # ── Application ───────────────────────────────────────────────────────────

    @staticmethod
    def _apply_replace(g: Graph, m: MapMatch) -> None:
        g.add((m.target_iri, RDF.type, OWL.Class))
        if not g.value(m.target_iri, RDFS.label):
            g.add((m.target_iri, RDFS.label, Literal(m.target_label)))
        if m.target_def and not g.value(m.target_iri, IAO_DEF):
            g.add((m.target_iri, IAO_DEF, Literal(m.target_def)))
        for s, p, o in list(g.triples((None, None, m.source_iri))):
            g.remove((s, p, o))
            g.add((s, p, m.target_iri))
        for s, p, o in list(g.triples((m.source_iri, None, None))):
            g.remove((s, p, o))
            g.add((m.target_iri, p, o))

    @staticmethod
    def _apply_xref(g: Graph, m: MapMatch) -> None:
        g.add((m.source_iri, HAS_XREF, Literal(_iri_to_xref(str(m.target_iri)))))

    @staticmethod
    def _apply_subclass(g: Graph, m: MapMatch) -> None:
        g.add((m.target_iri, RDF.type, OWL.Class))
        g.add((m.source_iri, RDFS.subClassOf, m.target_iri))
        # For ontogpt method, target_def holds the more specific xref CURIE
        if m.method in ("ontogpt", "known") and m.target_def:
            ref_iri = OntologyMapper.curie_to_iri(m.target_def)
            if ref_iri and ref_iri != m.target_iri:
                g.add((m.source_iri, HAS_XREF, Literal(m.target_def)))


    # ── Primary API ───────────────────────────────────────────────────────────

    def run(
        self,
        source_owl: str | Path,
        output_path: str | Path | None = None,
        targets: list[str] | None = None,
        method: str = "lexical",
        mode: str = "replace",
        threshold: float = 0.90,
        use_synonyms: bool = False,
        model: str = _DEFAULT_LLM,
        schema_path: str | Path | None = None,
        cache_path: str | Path | None = None,
        candidates_path: str | Path | None = None,
        sssom_path: str | Path | None = None,
        top_k: int = 5,
        dry_run: bool = False,
    ) -> MapResult:
        """Map source OWL classes to target ontology concepts and write output OWL.

        Args:
            source_owl:      OWL/Turtle file to map.
            output_path:     Output path; defaults to overwriting source_owl.
            targets:         Ordered list of ontology keys to search (order = priority).
                             None → self.priority (DEFAULT_PRIORITY).
            method:          "lexical" | "sapbert" | "ontogpt" | "llm"
            mode:            "replace" | "xref" | "subclass"
                             Ignored for method="ontogpt" (always subclass).
            threshold:       Minimum cosine similarity for sapbert/llm methods.
            use_synonyms:    Include hasExactSynonym in lexical matching.
            model:           LiteLLM / OpenRouter model for ontogpt or llm methods.
            schema_path:     OntoGPT schema YAML (method="ontogpt"). Falls back to
                             GROUNDING_SCHEMA in config/settings.py.
            cache_path:      JSON cache for ontogpt/llm results (avoids re-calling LLM).
            candidates_path: Optional CSV of all top-K candidates per source class.
            sssom_path:      Optional SSSOM TSV of best matches.
            top_k:           Candidate count for sapbert/llm methods.
            dry_run:         Print plan without writing any files.
        """
        source_owl  = Path(source_owl)
        output_path = Path(output_path) if output_path else source_owl
        targets     = targets or self.priority
        actual_mode = "subclass" if method == "ontogpt" else mode

        print(f"[OntologyMapper] {source_owl.name}  method={method}  mode={actual_mode}")
        print(f"  targets (priority order): {targets}")

        g = self._load_graph(source_owl)
        print(f"  {len(g)} triples")

        src = self._source_classes(g)
        print(f"  {len(src)} source classes with labels\n")

        # ── Load LLM cache (ontogpt / llm methods) ────────────────────────────
        cache: dict = {}
        resolved_cache: Path | None = None
        if method in ("ontogpt", "llm") and cache_path:
            resolved_cache = Path(cache_path)
            if resolved_cache.exists():
                cache = json.loads(resolved_cache.read_text())
                print(f"  {len(cache)} cached entries")

        # ── Resolve schema for ontogpt ────────────────────────────────────────
        resolved_schema: Path | None = None
        if method == "ontogpt":
            if schema_path:
                resolved_schema = Path(schema_path)
            else:
                try:
                    from config.settings import GROUNDING_SCHEMA
                    resolved_schema = Path(GROUNDING_SCHEMA)
                except (ImportError, AttributeError):
                    resolved_schema = source_owl.parents[2] / "config" / "grounding_schema.yaml"

        # ── Resolve API key for llm ───────────────────────────────────────────
        api_key = ""
        if method == "llm":
            import os
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key:
                raise EnvironmentError("OPENROUTER_API_KEY not set in environment")

        # ── Match ─────────────────────────────────────────────────────────────
        candidates: list[dict] = []

        if method == "lexical":
            matches, candidates = self._match_lexical(src, targets, use_synonyms, top_k)
        elif method == "sapbert":
            matches, candidates = self._match_sapbert(src, targets, threshold, top_k)
        elif method == "ontogpt":
            matches = self._match_ontogpt(src, g, model, resolved_schema, cache, dry_run)
            if resolved_cache and not dry_run:
                resolved_cache.parent.mkdir(parents=True, exist_ok=True)
                resolved_cache.write_text(json.dumps(cache, indent=2))
        elif method == "llm":
            matches, candidates = self._match_llm(src, targets, threshold, model, api_key, top_k)
            if resolved_cache and not dry_run:
                resolved_cache.parent.mkdir(parents=True, exist_ok=True)
                resolved_cache.write_text(json.dumps(cache, indent=2))
        else:
            raise ValueError(f"Unknown method: {method!r}  (lexical|sapbert|ontogpt|llm)")

        matched_iris = {m.source_iri for m in matches}
        unmatched    = [iri for iri in src if iri not in matched_iris]

        print(f"\n  Matched: {len(matches)}  |  Unmatched: {len(unmatched)}")

        # ── Apply ─────────────────────────────────────────────────────────────
        if not dry_run:
            apply_fn = {
                "replace":  self._apply_replace,
                "xref":     self._apply_xref,
                "subclass": self._apply_subclass,
            }[actual_mode]

            for m in matches:
                apply_fn(g, m)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(source_owl) as f:
                fmt = "turtle" if f.read(300).strip().startswith("@") else "xml"
            g.serialize(str(output_path), format=fmt)
            print(f"  Written → {output_path}  ({len(g)} triples)")
        else:
            print("  [dry-run] No files written.")

        result = MapResult(
            source_owl=source_owl, method=method, mode=actual_mode,
            matches=matches, unmatched=unmatched, candidates=candidates,
        )

        if candidates_path:
            self.write_candidates(result, Path(candidates_path))
        if sssom_path:
            self.write_sssom(result, Path(sssom_path))

        return result

    # ── Single-target alignment (SSSOM / extend / enrich) ─────────────────────

    def align(
        self,
        source_owl: Path,
        target: Path,
        method: str = "sapbert+lexical",
        top_k: int = 5,
        threshold: float = 0.70,
    ) -> MapResult:
        """Align source OWL to a single external target (SNOMED JSON, OBO, or OWL).

        method: "lexical", "sapbert", or "sapbert+lexical".
        Returns MapResult; call write_sssom / extend / enrich with the result.
        """
        from wound_ontology.alignment.target_loader import load_target

        g = self._load_graph(source_owl)
        label_index, max_id = self._source_meta(g)

        # Source: one row per unique IRI (primary label)
        iri_to_label: dict[URIRef, str] = {}
        for norm_lbl, iri in label_index.items():
            iri_to_label.setdefault(iri, norm_lbl)

        target_concepts = load_target(target)
        t_labels        = [_norm(c.label) for c in target_concepts]
        n_src, n_tgt    = len(iri_to_label), len(target_concepts)

        print(f"[OntologyMapper.align] Source: {n_src} | Target: {n_tgt} ({target.name})")

        src_iris   = list(iri_to_label.keys())
        src_labels = list(iri_to_label.values())

        import numpy as np
        lexical = np.zeros((n_src, n_tgt), dtype=np.float32)
        sapbert = np.zeros((n_src, n_tgt), dtype=np.float32)

        if "lexical" in method:
            t_norm_idx: dict[str, int] = {}
            for j, c in enumerate(target_concepts):
                t_norm_idx.setdefault(_norm(c.label), j)
                for syn in c.synonyms:
                    t_norm_idx.setdefault(_norm(syn), j)
            for i, s_lbl in enumerate(src_labels):
                j = t_norm_idx.get(s_lbl)
                if j is not None:
                    lexical[i, j] = 1.0

        if "sapbert" in method:
            encode   = self._get_encoder()
            all_embs = encode(src_labels + t_labels)
            s_embs   = all_embs[:n_src]
            t_embs   = all_embs[n_src:]
            sapbert  = (s_embs @ t_embs.T).astype(np.float32)

        combined = np.maximum(lexical, sapbert)

        candidates: list[dict] = []
        for i, (s_iri, s_lbl) in enumerate(zip(src_iris, src_labels)):
            for j in np.argsort(combined[i])[::-1][:top_k]:
                score = float(combined[i, j])
                if score <= 0:
                    break
                candidates.append({
                    "source_iri":   str(s_iri), "source_label": s_lbl,
                    "target_iri":   target_concepts[j].iri,
                    "target_label": target_concepts[j].label,
                    "score":        round(score, 4),
                    "method":       "exact" if lexical[i, j] == 1.0 else "sapbert",
                })

        matches:       list[MapMatch] = []
        mapped_source: set[str]       = set()
        for i, (s_iri, s_lbl) in enumerate(zip(src_iris, src_labels)):
            best_j     = int(np.argmax(combined[i]))
            best_score = float(combined[i, best_j])
            if best_score >= threshold:
                tc     = target_concepts[best_j]
                meth   = "lexical" if lexical[i, best_j] == 1.0 else "sapbert"
                matches.append(MapMatch(
                    source_iri=s_iri, source_label=s_lbl,
                    target_iri=URIRef(tc.iri), target_label=tc.label,
                    target_prefix="", target_def=tc.definition,
                    score=best_score, method=meth,
                ))
                mapped_source.add(str(s_iri))

        unmatched = [iri for iri in src_iris if str(iri) not in mapped_source]
        print(f"  Mapped: {len(matches)} | Unmatched source: {len(unmatched)}")

        return MapResult(
            source_owl=source_owl, method=method, mode="xref",
            matches=matches, unmatched=unmatched, candidates=candidates,
            target_path=target, target_concepts=target_concepts,
            source_label_index=label_index, source_max_id=max_id,
        )

    def extend(
        self,
        result: MapResult,
        out_path: Path,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Mint WOND stubs for target concepts that have no source match."""
        mapped_target_iris = {str(m.target_iri) for m in result.matches}
        unmatched_target   = [c for c in result.target_concepts
                               if c.iri not in mapped_target_iris]
        print(f"[extend] {len(unmatched_target)} target concepts → new stubs")

        if dry_run:
            for c in unmatched_target[:10]:
                print(f"  would stub: {c.label!r}")
            if len(unmatched_target) > 10:
                print(f"  … and {len(unmatched_target) - 10} more")
            print("[dry-run] No files written.")
            return {"new_stubs": len(unmatched_target),
                    "parent_resolved": 0, "parent_owlthing": 0}

        src = out_path if out_path.exists() else result.source_owl
        g   = self._load_graph(src)
        g.bind("wond", WOND)
        g.bind("oboInOwl", OBOA)

        target_to_wond: dict[str, URIRef] = {str(m.target_iri): m.source_iri
                                              for m in result.matches}
        next_id = result.source_max_id + 1
        new_iri_map: dict[str, URIRef] = {}
        for c in unmatched_target:
            new_iri_map[c.iri] = WOND[f"{next_id:07d}"]
            next_id += 1
        target_to_wond.update(new_iri_map)

        parent_resolved = parent_owlthing = 0
        for c in unmatched_target:
            iri = new_iri_map[c.iri]
            if c.parent_iri and c.parent_iri in target_to_wond:
                parent_iri = target_to_wond[c.parent_iri]
                parent_resolved += 1
            else:
                parent_iri = OWL.Thing
                parent_owlthing += 1
            g.add((iri, RDF.type,        OWL.Class))
            g.add((iri, RDFS.label,      Literal(c.label)))
            g.add((iri, HAS_XREF,        Literal(_iri_to_xref(c.iri))))
            g.add((iri, RDFS.subClassOf, parent_iri))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        g.serialize(str(out_path), format="xml")
        print(f"[extend] Wrote {out_path} (+{len(unmatched_target)} stubs)")
        return {"new_stubs": len(unmatched_target),
                "parent_resolved": parent_resolved, "parent_owlthing": parent_owlthing}

    def enrich(
        self,
        result: MapResult,
        out_path: Path,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Annotate matched source classes with xrefs, labels, and definitions."""
        src = out_path if out_path.exists() else result.source_owl
        g   = self._load_graph(src)
        g.bind("oboInOwl", OBOA)

        added_xrefs = added_labels = added_defs = 0
        for m in result.matches:
            xref = Literal(_iri_to_xref(str(m.target_iri)))
            if (m.source_iri, HAS_XREF, xref) not in g:
                if not dry_run:
                    g.add((m.source_iri, HAS_XREF, xref))
                added_xrefs += 1
            if not g.value(m.source_iri, RDFS.label):
                if not dry_run:
                    g.add((m.source_iri, RDFS.label, Literal(m.target_label)))
                added_labels += 1
            if m.target_def and not g.value(m.source_iri, IAO_DEF):
                if not dry_run:
                    g.add((m.source_iri, IAO_DEF, Literal(m.target_def)))
                added_defs += 1

        if dry_run:
            print(f"[dry-run] would add {added_xrefs} xrefs, "
                  f"{added_labels} labels, {added_defs} defs")
            return {"added_xrefs": added_xrefs,
                    "added_labels": added_labels, "added_defs": added_defs}

        out_path.parent.mkdir(parents=True, exist_ok=True)
        g.serialize(str(out_path), format="xml")
        print(f"[enrich] +{added_xrefs} xrefs, +{added_labels} labels, "
              f"+{added_defs} defs → {out_path}")
        return {"added_xrefs": added_xrefs,
                "added_labels": added_labels, "added_defs": added_defs}

    # ── Report outputs ─────────────────────────────────────────────────────────

    def write_candidates(self, result: MapResult, out_path: Path) -> None:
        """Write top-K candidates CSV for manual inspection."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fields = ["source_iri", "source_label", "target_iri", "target_label",
                  "score", "method"]
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields,
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(result.candidates)
        print(f"[OntologyMapper] Candidates → {out_path} ({len(result.candidates)} rows)")

    # ── External label enrichment ─────────────────────────────────────────────

    def _build_external_lookup(
        self, needed: set[URIRef]
    ) -> dict[str, dict]:
        """Return {iri_str: {"label": ..., "def": ...}} for a set of external IRIs."""
        lookup: dict[str, dict] = {}

        for iri in needed:
            info = self._HARDCODED_EXTERNAL.get(str(iri))
            if info:
                lookup[str(iri)] = info

        remaining = {iri for iri in needed if str(iri) not in lookup}

        by_prefix: dict[str, list[URIRef]] = {}
        for iri in remaining:
            local = str(iri).split("/obo/")[1]
            pfx   = local.split("_")[0]
            by_prefix.setdefault(pfx, []).append(iri)

        for pfx, iris in by_prefix.items():
            if pfx not in self.onto_files:
                print(f"  {pfx}: no ontology file configured — skipping")
                continue
            try:
                idx = self._load_index(pfx)
            except Exception as exc:
                print(f"  {pfx}: failed to load — {exc}")
                continue
            # Reverse label→entry index to iri_str→{label, def}
            iri_lookup = {
                str(iri_entry): {"label": lbl, "def": defn}
                for lbl, (iri_entry, lbl, defn) in idx.items()
            }
            for iri in iris:
                info = iri_lookup.get(str(iri))
                if info:
                    lookup[str(iri)] = info

        return lookup

    def enrich_external(
        self,
        graph_path: str | Path,
        output_path: str | Path | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Enrich non-WOND external classes in a mapped OWL file with labels and definitions.

        For every external OBO class present in *graph_path* (as a declared class or a
        subClassOf target), looks up rdfs:label and IAO:0000115 from local source-ontology
        files and writes them in-place.  Requires onto_dir.
        """
        if self.onto_dir is None:
            raise ValueError("onto_dir required for enrich_external")

        graph_path  = Path(graph_path)
        output_path = Path(output_path) if output_path else graph_path

        g = self._load_graph(graph_path)
        print(f"[OntologyMapper.enrich_external] {graph_path.name}  ({len(g)} triples)")

        ext_iris: set[URIRef] = set()
        for s in g.subjects(RDF.type, OWL.Class):
            if isinstance(s, URIRef) and self._is_external(str(s)):
                ext_iris.add(s)
        for _, _, o in g.triples((None, RDFS.subClassOf, None)):
            if isinstance(o, URIRef) and self._is_external(str(o)):
                ext_iris.add(o)

        print(f"  {len(ext_iris)} external classes to enrich")
        lookup = self._build_external_lookup(ext_iris)

        stats: dict[str, int] = {"added_labels": 0, "added_defs": 0, "missing": 0}
        for iri in sorted(ext_iris, key=str):
            short = str(iri).split("/obo/")[1]
            info  = lookup.get(str(iri))
            if not info:
                print(f"  {short:25s}  NOT FOUND in source ontologies")
                stats["missing"] += 1
                continue
            label = info["label"]
            defn  = info.get("def")
            print(f"  {short:25s}  {label!r}" + ("  [has def]" if defn else ""))
            if not dry_run:
                g.add((iri, RDF.type, OWL.Class))
                if not g.value(iri, RDFS.label):
                    g.add((iri, RDFS.label, Literal(label)))
                    stats["added_labels"] += 1
                if defn and not g.value(iri, IAO_DEF):
                    g.add((iri, IAO_DEF, Literal(defn)))
                    stats["added_defs"] += 1

        print(f"\n  Added {stats['added_labels']} labels, "
              f"{stats['added_defs']} definitions, "
              f"{stats['missing']} not found")

        if not dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(graph_path) as f:
                fmt = "turtle" if f.read(300).strip().startswith("@") else "xml"
            g.serialize(str(output_path), format=fmt)
            print(f"  Written → {output_path}  ({len(g)} triples)")
        else:
            print("[dry-run] No files written.")

        return stats

    def write_sssom(self, result: MapResult, out_path: Path) -> None:
        """Write best mappings in SSSOM TSV format."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        target_name = result.target_path.name if result.target_path else "targets"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            f.write("# SSSOM mapping set\n")
            f.write(f"# mapping_set_id: {result.source_owl.name}_x_{target_name}\n")
            f.write(f"# mapping_date: {date.today().isoformat()}\n")
            f.write(f"# mapping_tool: wound-ontology OntologyMapper "
                    f"(method={result.method})\n#\n")
            w = csv.DictWriter(f, delimiter="\t", fieldnames=[
                "subject_id", "subject_label", "predicate_id",
                "object_id", "object_label", "confidence", "mapping_justification",
            ])
            w.writeheader()
            for m in result.matches:
                pred = "skos:exactMatch" if m.score >= 1.0 else "skos:closeMatch"
                just = ("semapv:LexicalMatching" if m.method in ("lexical", "known")
                        else "semapv:SemanticSimilarityThresholdMatching")
                w.writerow({
                    "subject_id":            str(m.source_iri),
                    "subject_label":         m.source_label,
                    "predicate_id":          pred,
                    "object_id":             str(m.target_iri),
                    "object_label":          m.target_label,
                    "confidence":            f"{m.score:.4f}",
                    "mapping_justification": just,
                })
        print(f"[OntologyMapper] SSSOM → {out_path} ({len(result.matches)} mappings)")
