from __future__ import annotations
"""Matching a pipeline term to a class that already exists.

The pipeline works in labels; an ontology works in IRIs. Whatever cannot be
matched to an existing class gets a new WONT identifier minted for it, so every
missed match is a duplicate class: "material entities" minted alongside
BFO_0000040 "material entity", meaning the same thing, sharing no axioms, and
invisible to the reasoner as the same concept.

Matching runs in tiers, widest-first-loses:

  exact     the label as written, lowercased          -- what we always did
  normal    punctuation, hyphens and parentheticals folded (normalize_term)
  singular  the head noun singularized

An upstream ontology also states its own variants, so ``hasExactSynonym``,
``IAO_0000118`` (alternative term) and ``skos:altLabel`` are indexed alongside
``rdfs:label``. Narrow, broad and related synonyms are NOT: those assert a
*different* concept, and treating "wound infection" as "sepsis" because someone
recorded a related synonym is worse than minting a duplicate.

Ambiguity is refused, never guessed. If two distinct classes fold to the same
key the term is reported as ambiguous and left to mint, because silently
choosing one of them attaches every downstream axiom to a coin flip.
"""
from dataclasses import dataclass, field

from wound_ontology.utils.string_utils import normalize_term

#: Latin and irregular plurals that no suffix rule gets right.
_IRREGULAR: dict[str, str] = {
    "bacteria": "bacterium", "criteria": "criterion", "phenomena": "phenomenon",
    "media": "medium", "ganglia": "ganglion", "sequelae": "sequela",
    "fungi": "fungus", "nuclei": "nucleus", "foci": "focus", "loci": "locus",
    "villi": "villus", "emboli": "embolus", "thrombi": "thrombus",
    "vertebrae": "vertebra", "bullae": "bulla", "lamellae": "lamella",
    "fistulae": "fistula", "maculae": "macula", "papillae": "papilla",
    "indices": "index", "apices": "apex", "cortices": "cortex",
    "matrices": "matrix", "vertices": "vertex", "helices": "helix",
    "feet": "foot", "teeth": "tooth", "children": "child", "men": "man",
    "women": "woman", "people": "person", "mice": "mouse", "lice": "louse",
    # Greek -sis/-ses. A general "-ses -> -sis" rule would wreck "roses" and
    # "noses", so the clinically common ones are listed instead.
    "analyses": "analysis", "diagnoses": "diagnosis", "prognoses": "prognosis",
    "metastases": "metastasis", "anastomoses": "anastomosis",
    "stenoses": "stenosis", "necroses": "necrosis", "fibroses": "fibrosis",
    "neuroses": "neurosis", "psychoses": "psychosis", "mycoses": "mycosis",
    "dermatoses": "dermatosis", "sclerosis": "sclerosis", "acidoses": "acidosis",
}

#: Singular words that merely look plural. Suffix rules mangle these into
#: things like "diabete", "specy" and "sery".
_INVARIANT: frozenset[str] = frozenset({
    "diabetes", "herpes", "scabies", "rabies", "measles", "mumps", "ascites",
    "caries", "facies", "species", "series", "gas", "bias", "lens", "news",
    "genetics", "orthopedics", "pediatrics", "obstetrics", "diagnostics",
    "physics", "ethics", "statistics", "logistics", "mechanics",
})

#: Endings that look plural but are not. "sepsis", "dermis", "abscess",
#: "virus", "process", "status" -- a clinical vocabulary is full of them.
_NOT_PLURAL = ("ss", "us", "is", "sis", "ous")

#: -es is dropped only after these; elsewhere a bare -s is dropped instead.
_ES_STEMS = ("x", "ch", "sh", "s", "z")


def singularize(word: str) -> str:
    """Best-effort singular of one word. Wrong guesses are harmless: a key is
    only ever *looked up*, never stored as a label."""
    w = word.lower()
    if w in _IRREGULAR:
        return _IRREGULAR[w]
    if w in _INVARIANT:
        return w
    # "processes" and "abscesses" are plurals of -ss words; the -ss guard in
    # _NOT_PLURAL would otherwise freeze them, so they are handled first.
    if w.endswith("sses"):
        return w[:-2]
    if len(w) < 4 or not w.endswith("s") or w.endswith(_NOT_PLURAL):
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and w[:-2].endswith(_ES_STEMS):
        return w[:-2]
    return w[:-1]


def fold(term: str) -> str:
    """Normalized key: punctuation folded, head noun singularized."""
    base = normalize_term(term)
    if not base:
        return base
    words = base.split()
    words[-1] = singularize(words[-1])
    return " ".join(words)


@dataclass
class LabelIndex:
    """Label -> IRI, with normalized and singularized fallbacks.

    ``add`` is order-sensitive in the same way the old dict was: preferred
    labels overwrite synonyms, synonyms never overwrite a preferred label.
    """

    exact: dict[str, object] = field(default_factory=dict)
    folded: dict[str, set] = field(default_factory=dict)

    def add(self, label: str, iri, *, preferred: bool = True) -> None:
        key = str(label).strip().lower()
        if not key:
            return
        if preferred:
            self.exact[key] = iri
        else:
            self.exact.setdefault(key, iri)
        f = fold(key)
        if f:
            self.folded.setdefault(f, set()).add(iri)

    def update(self, other: "LabelIndex", *, preferred: bool = True) -> None:
        for key, iri in other.exact.items():
            self.add(key, iri, preferred=preferred)

    # dict-ish surface, so callers that only ever did idx[key] / idx.items()
    # keep working while the tiered lookup lives behind .get().
    def __getitem__(self, term: str):
        return self.exact[str(term).strip().lower()]

    def items(self):
        return self.exact.items()

    def values(self):
        return self.exact.values()

    def keys(self):
        return self.exact.keys()

    def __len__(self) -> int:
        return len(self.exact)

    def __contains__(self, term: str) -> bool:
        return str(term).strip().lower() in self.exact

    def get(self, term: str):
        """``(iri, how)`` where how is 'exact' | 'variant' | None.

        A third value, 'ambiguous', means several distinct classes share the
        folded key; the caller must not pick one.
        """
        key = str(term).strip().lower()
        hit = self.exact.get(key)
        if hit is not None:
            return hit, "exact"
        f = fold(key)
        if not f:
            return None, None
        candidates = self.folded.get(f)
        if not candidates:
            return None, None
        if len(candidates) > 1:
            return None, "ambiguous"
        return next(iter(candidates)), "variant"
