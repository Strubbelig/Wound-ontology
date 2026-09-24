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
    # -sis/-ses that are not disease names but turn up in wound-care prose.
    # Measured 2026-09-10: "orthoses" is in the store and reaches neither
    # "orthos" nor "orthose", so no suffix candidate finds "orthosis".
    "orthoses": "orthosis", "prostheses": "prosthesis",
    "exostoses": "exostosis", "paralyses": "paralysis", "dialyses": "dialysis",
    "syntheses": "synthesis", "hypotheses": "hypothesis",
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


def singular_candidates(word: str) -> list[str]:
    """Every plausible singular of one word, best guess first, no duplicates.

    ``-es`` is genuinely ambiguous and no suffix rule separates the two cases:
    ``buses -> bus`` drops two characters because the *singular* ends in a
    sibilant, while ``phases -> phase`` drops one because the singular already
    ends in ``e``. The surface forms are identical.

    Guessing once was measured to be wrong more often than right on this
    vocabulary: of the 45 store terms whose head noun takes that branch, **31
    are mis-singularised** across 12 head nouns (``responses -> respons``,
    ``nurses -> nurs``, ``cases -> cas``, ``phases -> phas``,
    ``orthoses -> orthos``, ``databases -> databas``, ``bases -> bas``,
    ``causes -> caus``, ``diseases -> diseas``, ``exercises -> exercis``,
    ``expenses -> expens``, ``endoproteases -> endoproteas``) and only 14 are
    right (``approaches -> approach``, ``processes -> process``,
    ``lenses -> lens``, ``bypasses -> bypass``, ``censuses -> census``,
    ``stresses -> stress``). On the ontology side 9 of 7242 labels take it, 3
    of them wrongly.

    So both are offered and the *lookup* decides, by which one an ontology
    actually carries. The first candidate is the historical guess, so
    :func:`singularize` and :func:`fold` are unchanged.
    """
    w = word.lower()
    if w in _IRREGULAR:
        return [_IRREGULAR[w]]
    if w in _INVARIANT:
        return [w]
    # "processes" and "abscesses" are plurals of -ss words; the -ss guard in
    # _NOT_PLURAL would otherwise freeze them, so they are handled first.
    if w.endswith("sses"):
        return [w[:-2]]
    if len(w) < 4 or not w.endswith("s") or w.endswith(_NOT_PLURAL):
        return [w]
    if w.endswith("ies") and len(w) > 4:
        return [w[:-3] + "y"]
    if w.endswith("es") and w[:-2].endswith(_ES_STEMS):
        # The ambiguous branch, and the only one that yields two.
        return [w[:-2], w[:-1]]
    return [w[:-1]]


def singularize(word: str) -> str:
    """Best-effort singular of one word — the first of
    :func:`singular_candidates`. Wrong guesses are harmless: a key is only ever
    *looked up*, never stored as a label."""
    return singular_candidates(word)[0]


def singular_spelling(label: str) -> str:
    """`label` with its head noun singular, KEEPING the label's own spelling.

    `singularize` is a folding function: it lowercases, because its answers are
    only ever looked up as keys. This one produces a NAME -- the curator's rule
    of 2026-09-23, "I always want the singular" -- so the rest of the label is
    left exactly as written and the head keeps its case:

        'Diabetic Foot Ulcers' -> 'Diabetic Foot Ulcer'
        'DFUs'                 -> 'DFU'          (an acronym plural, which
                                                  `singularize` cannot see:
                                                  it answers 'dfus')
        'Diabetes'             -> 'Diabetes'     (-es on a -sis/-itis/-us word
                                                  is not a plural)

    Unchanged when the head is already singular, so it is safe to apply twice.
    """
    words = label.split()
    if not words:
        return label
    head = words[-1]
    core = head.rstrip(".,;:)")
    trailing = head[len(core):]
    if len(core) > 1 and core[:-1].isupper() and core.endswith("s") and core[:-1].isalpha():
        # SSIs, DFUs, PJIs -- an acronym with a plural s, which no suffix rule
        # recognises because the stem is not a word.
        return " ".join(words[:-1] + [core[:-1] + trailing])
    lowered = core.lower()
    single = singularize(lowered)
    if single == lowered:
        return label
    if core.isupper():
        single = single.upper()
    elif core[:1].isupper():
        single = single[:1].upper() + single[1:]
    return " ".join(words[:-1] + [single + trailing])


def fold_candidates(term: str) -> list[str]:
    """Every folded key ``term`` could match, best guess first.

    Only the head noun varies, so this is one key per singular candidate.
    """
    base = normalize_term(term)
    if not base:
        return [base]
    words = base.split()
    head = words[-1]
    return [" ".join(words[:-1] + [cand]) for cand in singular_candidates(head)]


def fold(term: str) -> str:
    """Normalized key: punctuation folded, head noun singularized."""
    return fold_candidates(term)[0]


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
        for f in fold_candidates(key):
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
        # Try each folded candidate in order. An ambiguous one does not end the
        # search: a later candidate may resolve cleanly, and refusing on the
        # first collision would throw away a match that exists. Ambiguity is
        # only the answer if nothing resolved.
        ambiguous = False
        for f in fold_candidates(key):
            if not f:
                continue
            claimants = self.folded.get(f)
            if not claimants:
                continue
            if len(claimants) > 1:
                ambiguous = True
                continue
            return next(iter(claimants)), "variant"
        return None, ("ambiguous" if ambiguous else None)
