#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate the LLM extraction schema FROM the ontologies.

Why generate instead of hand-maintain
-------------------------------------
`bfo_extraction_schema.yaml` was written by hand and drifted: it declared
`Disease: is_a: Disposition`, the OGMS pattern MILD explicitly rejects, and it
grounded diseases to MONDO, a nosology. A hand-maintained schema can contradict
the ontology it is supposed to serve. A generated one cannot: MILD says
`material disease entity` is a `material entity`, so that is what comes out.

What it emits
-------------
1. ``config/extraction_schema.yaml``            LinkML  (source of truth, gen-owl/gen-pydantic ready)
2. ``src/wound_ontology/llm/extraction_models.py``  Pydantic v2 (used directly; no linkml install needed)

Design
------
Closed where closure is correct, open where discovery is needed:

* ``category``     CLOSED enum. One categorical choice per term — C2 stage 1.
* ``label``        FREE string. New terms are the point of the pipeline.
* ``grounded_to``  OPTIONAL closed enum, per category. Existing class or null.
* ``relations``    CLOSED enum, validated against the (subject, object) category
                   pair — C2 stage 2, deterministic rather than LLM judgement.

The per-category term enums carry each class's IAO_0000115 definition as its
description, so the definitions generated in Round 1 become the prompt text.
"""
from __future__ import annotations

import collections
import datetime as _dt
import keyword
import re
from pathlib import Path

import rdflib
from rdflib import OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection

# ── paths ──────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
PROJ = HERE.parent                      # Wound ontology/
ROOT = PROJ.parent                      # Forschung/Ontology/

WONT_TTL = PROJ / "data" / "ground truth" / "ground_truth_final.owl"
MILD_TTL = ROOT / "Disease ontologies" / "Disease proposal 2.ttl"
MODULES  = ROOT / "Disease ontologies" / "Disease ontology modules"

OUT_YAML = PROJ / "config" / "extraction_schema.yaml"
OUT_PY   = PROJ / "src" / "wound_ontology" / "llm" / "extraction_models.py"

OBO  = "http://purl.obolibrary.org/obo/"
MILD = "https://bioportal.bioontology.org/ontologies/MILD/"
WONT = "https://bioportal.bioontology.org/ontologies/WONT/"
IAO115 = URIRef(OBO + "IAO_0000115")
IAO118 = URIRef(OBO + "IAO_0000118")

# BFO's own backbone is not present in any module we import, so state the
# skeleton explicitly rather than silently failing to resolve categories.
BFO_SKELETON = {
    "BFO_0000004": "BFO_0000002", "BFO_0000020": "BFO_0000002",
    "BFO_0000031": "BFO_0000002", "BFO_0000040": "BFO_0000004",
    "BFO_0000141": "BFO_0000004", "BFO_0000015": "BFO_0000003",
    "BFO_0000017": "BFO_0000020", "BFO_0000019": "BFO_0000020",
    "BFO_0000016": "BFO_0000017", "BFO_0000023": "BFO_0000017",
    "BFO_0000034": "BFO_0000016", "BFO_0000035": "BFO_0000003",
    "OGMS_0000045": "BFO_0000040", "IAO_0000030": "BFO_0000031",
}

# The category tree, mirroring BFO (plus MILD's tendency, which MILD places as a
# sibling of disposition under realizable entity, not as a disposition subtype).
#
# COARSE nodes exist so a model that cannot tell a Process from a MaterialEntity
# can RETREAT UP THE TREE instead of guessing. Every extracted term is still
# subsumed under a real BFO class either way — that is the point: a correct
# coarse placement beats a confident wrong precise one, and it can be refined
# later without contradiction, because Process really is an Occurrent.
#
# (name, IRI, parent name or None, coarse?, gloss)
ANCHORS: list[tuple[str, str, str | None, bool, str]] = [
    ("Continuant", OBO + "BFO_0000002", None, True,
     "FALLBACK. Something that persists through time and is wholly present whenever it exists. "
     "Use only when you cannot tell which kind of continuant it is."),
    ("Occurrent", OBO + "BFO_0000003", None, True,
     "FALLBACK. Something that happens or unfolds in time. "
     "Use only when you cannot tell which kind of occurrent it is."),

    ("IndependentContinuant", OBO + "BFO_0000004", "Continuant", True,
     "FALLBACK. A continuant that does not depend on a bearer. "
     "Use only when you cannot tell material from immaterial."),
    ("SpecificallyDependentContinuant", OBO + "BFO_0000020", "Continuant", True,
     "FALLBACK. A continuant that must inhere in a bearer. "
     "Use only when you cannot tell which kind of dependent continuant it is."),
    ("RealizableEntity", OBO + "BFO_0000017", "SpecificallyDependentContinuant", True,
     "A dependent continuant realized in a process. Use directly only for things like plans; "
     "otherwise prefer Disposition, Function, Role or Tendency."),

    ("MaterialEntity", OBO + "BFO_0000040", "IndependentContinuant", False,
     "A material thing: a body part, an organism, a substance, a disorder, a device."),
    ("ImmaterialEntity", OBO + "BFO_0000141", "IndependentContinuant", False,
     "An immaterial continuant such as a cavity, a site or a boundary."),
    ("Quality", OBO + "BFO_0000019", "SpecificallyDependentContinuant", False,
     "A way a thing is, fully exhibited whenever it is present: a colour, a size, a degree."),
    ("Disposition", OBO + "BFO_0000016", "RealizableEntity", False,
     "A tendency to behave a certain way under given conditions, grounded in physical makeup; "
     "it may never be realized."),
    ("Function", OBO + "BFO_0000034", "Disposition", False,
     "A disposition the bearer exists in order to have, by design or by selection."),
    ("Role", OBO + "BFO_0000023", "RealizableEntity", False,
     "Something a thing has only because of context or convention, and could lose without changing."),
    ("Tendency", MILD + "MILD_120005", "RealizableEntity", False,
     "Raises the objective probability of an outcome without necessitating it. "
     "Use for predispositions and risk factors."),
    ("InformationEntity", OBO + "BFO_0000031", "Continuant", False,
     "Information: a datum, a specification, a classification result, a scale, a plan specification."),
    ("Process", OBO + "BFO_0000015", "Occurrent", False,
     "Something that happens and unfolds over time; it has temporal parts."),
    ("ProcessBoundary", OBO + "BFO_0000035", "Occurrent", False,
     "The instantaneous start or end of a process."),
]

ANCHOR_PARENT = {n: p for n, _, p, _, _ in ANCHORS}
ANCHOR_COARSE = {n: c for n, _, _, c, _ in ANCHORS}
ANCHOR_IRI = {n: i for n, i, _, _, _ in ANCHORS}


def anchor_descendants(name: str) -> set[str]:
    """`name` plus every anchor beneath it."""
    out = {name}
    changed = True
    while changed:
        changed = False
        for child, parent in ANCHOR_PARENT.items():
            if parent in out and child not in out:
                out.add(child)
                changed = True
    return out


ANCHOR_BY_IRI = {i: n for n, i, _, _, _ in ANCHORS}


# ── graph ──────────────────────────────────────────────────────────────────
def load_graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(str(WONT_TTL), format="turtle")
    g.parse(str(MILD_TTL), format="turtle")
    for mod in sorted(MODULES.glob("*_module.owl")):
        try:
            g.parse(str(mod))
        except Exception as exc:                      # pragma: no cover
            print(f"  ! skipped {mod.name}: {exc}")
    for child, parent in BFO_SKELETON.items():
        g.add((URIRef(OBO + child), RDFS.subClassOf, URIRef(OBO + parent)))
    return g


class Onto:
    def __init__(self, g: rdflib.Graph):
        self.g = g
        self._anc: dict = {}

    def label(self, n) -> str | None:
        v = self.g.value(n, RDFS.label)
        return str(v) if v is not None else None

    def definition(self, n) -> str | None:
        v = self.g.value(n, IAO115)
        return str(v) if v is not None else None

    def synonyms(self, n) -> list[str]:
        return sorted({str(v) for v in self.g.objects(n, IAO118)})

    def named_parents(self, c) -> list[URIRef]:
        """Named superclasses, flattening anonymous intersections from BOTH
        rdfs:subClassOf and owl:equivalentClass."""
        out: list[URIRef] = []

        def absorb(o):
            if isinstance(o, URIRef):
                out.append(o)
                return
            inter = self.g.value(o, OWL.intersectionOf)
            if inter is None:
                return
            for item in Collection(self.g, inter):
                absorb(item)

        for o in self.g.objects(c, RDFS.subClassOf):
            absorb(o)
        for o in self.g.objects(c, OWL.equivalentClass):
            absorb(o)
        return out

    def ancestors(self, c) -> set:
        if c in self._anc:
            return self._anc[c]
        self._anc[c] = set()                     # cycle guard
        out, stack, seen = set(), [c], {c}
        while stack:
            x = stack.pop()
            for p in self.named_parents(x):
                if p not in seen:
                    seen.add(p)
                    out.add(p)
                    stack.append(p)
        self._anc[c] = out
        return out

    def category(self, c) -> str | None:
        """The most specific BFO/MILD anchor above this class."""
        reach = self.ancestors(c) | {c}
        hits = [URIRef(iri) for _, iri, _, _, _ in ANCHORS if URIRef(iri) in reach]
        if not hits:
            return None
        # most specific = the one with the most other anchors above it
        best = max(hits, key=lambda x: len([y for y in hits if y in self.ancestors(x)]))
        return ANCHOR_BY_IRI[str(best)]

    def restrictions(self, c) -> list[tuple[URIRef, object]]:
        """(property, filler) pairs from someValuesFrom restrictions on c."""
        out = []

        def scan(node):
            p = self.g.value(node, OWL.onProperty)
            f = self.g.value(node, OWL.someValuesFrom)
            if isinstance(p, URIRef) and f is not None:
                out.append((p, f))

        def absorb(o):
            if isinstance(o, URIRef):
                return
            inter = self.g.value(o, OWL.intersectionOf)
            if inter is None:
                scan(o)
                return
            for item in Collection(self.g, inter):
                absorb(item)

        for o in self.g.objects(c, RDFS.subClassOf):
            absorb(o)
        for o in self.g.objects(c, OWL.equivalentClass):
            absorb(o)
        return out

    def filler_category(self, f) -> str | None:
        if isinstance(f, URIRef):
            return self.category(f)
        inter = self.g.value(f, OWL.intersectionOf)
        if inter is None:
            return None
        for item in Collection(self.g, inter):
            if isinstance(item, URIRef):
                return self.category(item)
        return None


# ── identifier helpers ─────────────────────────────────────────────────────
def py_ident(text: str, used: set[str]) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").upper()
    if not s or s[0].isdigit():
        s = "T_" + s
    if keyword.iskeyword(s.lower()):
        s += "_"
    base, i = s, 2
    while s in used:
        s = f"{base}_{i}"
        i += 1
    used.add(s)
    return s


def yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip() + '"'


def collect(onto: Onto):
    """Own MILD/WONT classes grouped by category, plus observed relation patterns."""
    own = sorted(
        (c for c in set(onto.g.subjects(RDF.type, OWL.Class))
         if isinstance(c, URIRef) and (str(c).startswith(MILD) or str(c).startswith(WONT))),
        key=str,
    )
    by_cat: dict[str, list] = collections.defaultdict(list)
    unresolved: list = []
    for c in own:
        if not onto.label(c):
            continue
        cat = onto.category(c)
        if cat:
            by_cat[cat].append(c)
        else:
            unresolved.append(c)
    # observed (subject category, property, object category)
    patterns: collections.Counter = collections.Counter()
    prop_labels: dict[str, str] = {}
    for c in own:
        sc = onto.category(c)
        if not sc:
            continue
        for p, f in onto.restrictions(c):
            oc = onto.filler_category(f)
            if not oc:
                continue
            patterns[(sc, str(p), oc)] += 1
            prop_labels.setdefault(str(p), onto.label(p) or str(p).rsplit("/", 1)[-1])
    return own, dict(by_cat), unresolved, patterns, prop_labels


# ── LinkML emitter ─────────────────────────────────────────────────────────
def emit_linkml(onto: Onto, by_cat, patterns, prop_labels) -> str:
    stamp = _dt.date.today().isoformat()
    L: list[str] = []
    add = L.append

    add("# GENERATED FILE - DO NOT EDIT BY HAND.")
    add("# Regenerate with:  python scripts/build_extraction_schema.py")
    add("# Source of truth:  Disease proposal 2.ttl (MILD) + ground_truth_final.owl (WONT)")
    add(f"# Generated:        {stamp}")
    add("id: https://w3id.org/wont/extraction")
    add("name: wont-extraction")
    add("title: WONT/MILD-derived extraction schema")
    add("description: >-")
    add("  Extraction schema generated from MILD and WONT. Categories and relations are")
    add("  closed sets taken from the ontologies; entity labels stay open so new terms can")
    add("  be discovered. Because it is generated, it cannot contradict the ontologies -")
    add("  in particular a disease is a material entity here, per MILD, not a disposition.")
    add("prefixes:")
    add("  linkml: https://w3id.org/linkml/")
    add("  wont: https://bioportal.bioontology.org/ontologies/WONT/")
    add("  MILD: https://bioportal.bioontology.org/ontologies/MILD/")
    add("  BFO: http://purl.obolibrary.org/obo/BFO_")
    add("  RO: http://purl.obolibrary.org/obo/RO_")
    add("  OBI: http://purl.obolibrary.org/obo/OBI_")
    add("  IAO: http://purl.obolibrary.org/obo/IAO_")
    add("default_prefix: wont")
    add("default_range: string")
    add("imports:")
    add("  - linkml:types")
    add("")
    add("enums:")

    # stage 1 - the single categorical choice
    add("  BFOCategory:")
    add("    description: >-")
    add("      The one categorical choice made per extracted term. Pick exactly one.")
    add("    permissible_values:")
    for name, iri, parent, coarse, gloss in ANCHORS:
        add(f"      {name}:")
        add(f"        meaning: {iri}")
        add(f"        description: {yaml_str(gloss)}")
        if parent:
            add(f"        is_a: {parent}")
        add("        annotations:")
        add(f"          precision: {'coarse' if coarse else 'precise'}")

    # stage 2 - grounding vocabularies, one per category
    for name, _i, _p, _c, _g in ANCHORS:
        members = by_cat.get(name, [])
        if not members:
            continue
        add(f"  {name}Term:")
        add("    description: >-")
        add(f"      Existing {name} classes in MILD/WONT. Ground to one of these when the")
        add("      term already exists; leave empty when it is genuinely new.")
        add("    permissible_values:")
        used: set[str] = set()
        for c in members:
            lab = onto.label(c)
            key = py_ident(lab, used)
            add(f"      {key}:")
            add(f"        meaning: {c}")
            add(f"        title: {yaml_str(lab)}")
            d = onto.definition(c)
            if d:
                add(f"        description: {yaml_str(d)}")
            for syn in onto.synonyms(c):
                add(f"        aliases: [{yaml_str(syn)}]")
                break

    # relations, with the observed category pairs
    add("  RelationType:")
    add("    description: >-")
    add("      Object properties actually used by MILD/WONT. The permitted subject and")
    add("      object categories are derived from how each property is used there, so a")
    add("      relation cannot be applied across a category boundary the ontologies reject.")
    add("    permissible_values:")
    by_prop: dict[str, list] = collections.defaultdict(list)
    for (sc, p, oc), n in patterns.items():
        by_prop[p].append((sc, oc, n))
    used_p: set[str] = set()
    for p in sorted(by_prop, key=lambda x: prop_labels.get(x, x)):
        lab = prop_labels.get(p, p.rsplit("/", 1)[-1])
        key = py_ident(lab, used_p)
        pairs = sorted(set((s, o) for s, o, _ in by_prop[p]))
        add(f"      {key}:")
        add(f"        meaning: {p}")
        add(f"        title: {yaml_str(lab)}")
        add("        description: {}".format(
            yaml_str("Permitted category pairs: "
                     + "; ".join(f"{s} -> {o}" for s, o in pairs))))
    add("")

    add("slots:")
    for sl, rng, desc in [
        ("label", "string", "the term exactly as it appears in the text"),
        ("category", "BFOCategory", "the single BFO/MILD category this term belongs to"),
        ("grounded_to", "uriorcurie", "IRI of the existing MILD/WONT class, if this term already exists"),
        ("subject", "string", "label of the subject entity"),
        ("predicate", "RelationType", "the relation asserted"),
        ("object", "string", "label of the object entity"),
        ("entities", "ExtractedEntity", "every distinct term found in the text"),
        ("relations", "ExtractedRelation", "relations between the extracted terms"),
    ]:
        add(f"  {sl}:")
        add(f"    range: {rng}")
        add(f"    description: {yaml_str(desc)}")
        if sl in ("entities", "relations"):
            add("    multivalued: true")
            add("    inlined_as_list: true")
    add("")

    add("classes:")
    add("  ExtractedEntity:")
    add("    description: a term found in the text, typed to exactly one category")
    add("    slots: [label, category, grounded_to]")
    add("  ExtractedRelation:")
    add("    description: >-")
    add("      A relation between two extracted terms. Validity is decided by the category")
    add("      pair, not by the model's judgement.")
    add("    slots: [subject, predicate, object]")
    add("  ExtractionResult:")
    add("    tree_root: true")
    add("    description: everything extracted from one document")
    add("    slots: [entities, relations]")
    add("")
    return "\n".join(L) + "\n"


# ── Pydantic emitter ───────────────────────────────────────────────────────
def emit_pydantic(onto: Onto, by_cat, patterns, prop_labels) -> str:
    stamp = _dt.date.today().isoformat()
    L: list[str] = []
    add = L.append

    add('# -*- coding: utf-8 -*-')
    add('"""GENERATED FILE - DO NOT EDIT BY HAND.')
    add("")
    add("Regenerate with:  python scripts/build_extraction_schema.py")
    add("Source of truth:  Disease proposal 2.ttl (MILD) + ground_truth_final.owl (WONT)")
    add(f"Generated:        {stamp}")
    add("")
    add("Mirrors config/extraction_schema.yaml. Emitted directly rather than via")
    add("`gen-pydantic` so the pipeline has no hard dependency on the linkml generator;")
    add("the LinkML file stays the declarative source of truth and remains gen-owl ready.")
    add('"""')
    add("from __future__ import annotations")
    add("")
    add("from enum import Enum")
    add("from typing import Optional")
    add("")
    add("from pydantic import BaseModel, Field, model_validator")
    add("")
    add("")
    add("class BFOCategory(str, Enum):")
    add('    """The one categorical choice made per extracted term."""')
    add("")
    for name, iri, _p, _c, gloss in ANCHORS:
        add(f"    {name} = {name!r}")
    add("")
    add("")
    add("CATEGORY_IRI: dict[str, str] = {")
    for name, iri, _p, _c, _g in ANCHORS:
        add(f"    {name!r}: {iri!r},")
    add("}")
    add("")
    add("CATEGORY_GLOSS: dict[str, str] = {")
    for name, _i, _p, _c, gloss in ANCHORS:
        add(f"    {name!r}: {gloss!r},")
    add("}")
    add("")
    add("# The BFO subsumption tree over the categories. Every extracted term is")
    add("# subsumed under one of these, so a new discovery always lands somewhere in BFO.")
    add("CATEGORY_PARENT: dict[str, str | None] = {")
    for name, _i, parent, _c, _g in ANCHORS:
        add(f"    {name!r}: {parent!r},")
    add("}")
    add("")
    add("# Coarse categories are legitimate answers, not failures: a model unsure")
    add("# whether something is a Process or a MaterialEntity should retreat to")
    add("# Occurrent or Continuant rather than guess. They are flagged for refinement.")
    add("COARSE_CATEGORIES: frozenset[str] = frozenset({")
    for name, _i, _p, coarse, _g in ANCHORS:
        if coarse:
            add(f"    {name!r},")
    add("})")
    add("")
    add("")
    add("def category_ancestors(category: str) -> list[str]:")
    add('    """The category itself, then each BFO parent up to the root."""')
    add("    out, cur = [], category")
    add("    while cur is not None:")
    add("        out.append(cur)")
    add("        cur = CATEGORY_PARENT.get(cur)")
    add("    return out")
    add("")
    add("")
    add("def category_descendants(category: str) -> set[str]:")
    add('    """The category plus every category beneath it."""')
    add("    out = {category}")
    add("    changed = True")
    add("    while changed:")
    add("        changed = False")
    add("        for child, parent in CATEGORY_PARENT.items():")
    add("            if parent in out and child not in out:")
    add("                out.add(child)")
    add("                changed = True")
    add("    return out")
    add("")
    add("")
    add("def is_refinement_of(fine: str, coarse: str) -> bool:")
    add('    """True if `fine` sits at or below `coarse` — i.e. refining is consistent."""')
    add("    return coarse in category_ancestors(fine)")
    add("")
    add("")
    # grounding vocabularies
    add("# ── Grounding vocabularies, one per category ──────────────────────────────")
    add("# label -> IRI, for terms that already exist in MILD/WONT.")
    add("GROUNDING: dict[str, dict[str, str]] = {")
    for name, _i, _p, _c, _g in ANCHORS:
        members = by_cat.get(name, [])
        if not members:
            continue
        add(f"    {name!r}: {{")
        for c in members:
            add(f"        {onto.label(c)!r}: {str(c)!r},")
        add("    },")
    add("}")
    add("")
    add("# label -> IAO_0000115 definition, for prompt construction.")
    add("DEFINITIONS: dict[str, str] = {")
    for name, _i, _p, _c, _g in ANCHORS:
        for c in by_cat.get(name, []):
            d = onto.definition(c)
            if d:
                add(f"    {onto.label(c)!r}: {d!r},")
    add("}")
    add("")
    add("")
    # relations
    add("class RelationType(str, Enum):")
    add('    """Object properties actually used by MILD/WONT."""')
    add("")
    by_prop: dict[str, list] = collections.defaultdict(list)
    for (sc, p, oc), n in patterns.items():
        by_prop[p].append((sc, oc, n))
    used_p: set[str] = set()
    key_for: dict[str, str] = {}
    for p in sorted(by_prop, key=lambda x: prop_labels.get(x, x)):
        lab = prop_labels.get(p, p.rsplit("/", 1)[-1])
        key = py_ident(lab, used_p)
        key_for[p] = key
        add(f"    {key} = {lab!r}")
    add("")
    add("")
    add("RELATION_IRI: dict[str, str] = {")
    for p, key in key_for.items():
        add(f"    RelationType.{key}.value: {p!r},")
    add("}")
    add("")
    add("# (subject category, object category) pairs observed in MILD/WONT for each")
    add("# relation. This is the deterministic half of two-stage extraction: once both")
    add("# categories are known the relation is largely forced, so the model is never")
    add("# asked to choose between occurs_in / part_of / inheres_in on BFO grounds.")
    add("RELATION_DOMAINS: dict[str, set[tuple[str, str]]] = {")
    for p, key in key_for.items():
        pairs = sorted(set((s, o) for s, o, _ in by_prop[p]))
        add(f"    RelationType.{key}.value: {{")
        for s_, o_ in pairs:
            add(f"        ({s_!r}, {o_!r}),")
        add("    },")
    add("}")
    add("")
    add("")
    add("def relations_for(subject_category: str, object_category: str) -> list[str]:")
    add('    """Relations MILD/WONT license between these two categories.')
    add("")
    add("    A coarse category stands for any of its descendants, so the answer widens")
    add("    to their union: asking about Continuant -> Process returns everything")
    add("    licensed for MaterialEntity -> Process, Quality -> Process and so on. That is")
    add("    the open-world reading — we know less, so fewer things are ruled out. Use")
    add("    `relations_are_certain()` to tell a confirmed relation from a possible one.")
    add('    """')
    add("    subs = category_descendants(subject_category)")
    add("    objs = category_descendants(object_category)")
    add("    return sorted(")
    add("        r for r, pairs in RELATION_DOMAINS.items()")
    add("        if any(s in subs and o in objs for s, o in pairs)")
    add("    )")
    add("")
    add("")
    add("def relations_are_certain(subject_category: str, object_category: str) -> bool:")
    add('    """True when both categories are precise, so the licensing answer is exact."""')
    add("    return (subject_category not in COARSE_CATEGORIES")
    add("            and object_category not in COARSE_CATEGORIES)")
    add("")
    add("")
    add("class ExtractedEntity(BaseModel):")
    add('    """A term found in the text, typed to exactly one category."""')
    add("")
    add("    label: str = Field(..., description='the term exactly as it appears in the text')")
    add("    category: BFOCategory = Field(..., description='the single BFO/MILD category')")
    add("    grounded_to: Optional[str] = Field(")
    add("        None,")
    add("        description='IRI of the existing MILD/WONT class, or null if the term is new',")
    add("    )")
    add("")
    add("    @property")
    add("    def bfo_iri(self) -> str:")
    add('        """The BFO class this term is subsumed under. Never null."""')
    add("        return CATEGORY_IRI[self.category.value]")
    add("")
    add("    @property")
    add("    def needs_refinement(self) -> bool:")
    add('        """Typed at a coarse node — correct, but a more specific class may apply."""')
    add("        return self.category.value in COARSE_CATEGORIES")
    add("")
    add("    def subsumption_axiom(self) -> tuple[str, str, str]:")
    add('        """(term, rdfs:subClassOf, BFO IRI) — the axiom this term always yields.')
    add("")
    add("        A newly discovered term has no MILD/WONT parent yet, but it is never")
    add("        left dangling: it is subsumed under its BFO category from the start,")
    add("        and curation only ever moves it DOWN the tree from there.")
    add('        """')
    add("        return (self.grounded_to or self.label,")
    add("                'http://www.w3.org/2000/01/rdf-schema#subClassOf',")
    add("                self.bfo_iri)")
    add("")
    add("    @model_validator(mode='after')")
    add("    def _ground_consistently(self):")
    add("        \"\"\"A supplied grounding must exist AND sit in the declared category.\"\"\"")
    add("        if self.grounded_to is None:")
    add("            table = GROUNDING.get(self.category.value, {})")
    add("            hit = table.get(self.label)")
    add("            if hit:")
    add("                self.grounded_to = hit          # exact-label autogrounding")
    add("            return self")
    add("        allowed = set(GROUNDING.get(self.category.value, {}).values())")
    add("        if self.grounded_to not in allowed:")
    add("            raise ValueError(")
    add("                f'{self.grounded_to!r} is not a {self.category.value} in MILD/WONT'")
    add("            )")
    add("        return self")
    add("")
    add("")
    add("class ExtractedRelation(BaseModel):")
    add('    """A relation between two extracted terms."""')
    add("")
    add("    subject: str")
    add("    predicate: RelationType")
    add("    object: str")
    add("")
    add("")
    add("class ExtractionResult(BaseModel):")
    add('    """Everything extracted from one document."""')
    add("")
    add("    entities: list[ExtractedEntity] = Field(default_factory=list)")
    add("    relations: list[ExtractedRelation] = Field(default_factory=list)")
    add("")
    add("    @model_validator(mode='after')")
    add("    def _relations_respect_categories(self):")
    add("        \"\"\"Drop relations whose category pair MILD/WONT does not license.\"\"\"")
    add("        cat = {e.label: e.category.value for e in self.entities}")
    add("        kept, rejected = [], []")
    add("        for r in self.relations:")
    add("            sc, oc = cat.get(r.subject), cat.get(r.object)")
    add("            if sc is None or oc is None:")
    add("                rejected.append((r, 'endpoint not among extracted entities'))")
    add("                continue")
    add("            if (sc, oc) not in RELATION_DOMAINS.get(r.predicate.value, set()):")
    add("                rejected.append((r, f'{sc} -> {oc} not licensed'))")
    add("                continue")
    add("            kept.append(r)")
    add("        self.relations = kept")
    add("        self.rejected_relations = rejected")
    add("        return self")
    add("")
    add("    rejected_relations: list = Field(default_factory=list, exclude=True)")
    add("")
    return "\n".join(L) + "\n"


# ── main ───────────────────────────────────────────────────────────────────
def main() -> None:
    print("Loading MILD + WONT + modules ...")
    onto = Onto(load_graph())
    own, by_cat, unresolved, patterns, prop_labels = collect(onto)

    print(f"  own MILD/WONT classes : {len(own)}")
    for name, _i, _p, _c, _g in ANCHORS:
        n = len(by_cat.get(name, []))
        if n:
            print(f"    {name:<18} {n}")
    if unresolved:
        print(f"  UNRESOLVED (no BFO anchor): {len(unresolved)}")
        for c in unresolved:
            print(f"    - {onto.label(c)}  <{c}>")
    print(f"  relation patterns     : {len(patterns)} over {len(prop_labels)} properties")

    OUT_YAML.parent.mkdir(parents=True, exist_ok=True)
    OUT_YAML.write_text(emit_linkml(onto, by_cat, patterns, prop_labels), encoding="utf-8")
    print(f"  wrote {OUT_YAML.relative_to(PROJ)}")

    OUT_PY.parent.mkdir(parents=True, exist_ok=True)
    OUT_PY.write_text(emit_pydantic(onto, by_cat, patterns, prop_labels), encoding="utf-8")
    print(f"  wrote {OUT_PY.relative_to(PROJ)}")


if __name__ == "__main__":
    main()
