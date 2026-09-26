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
    # Added 2026-09-24, when the naming rule started using these answers as
    # LABELS rather than as lookup keys. Each reaches neither suffix candidate:
    # "crises" gives "cris"/"crise", "meta-analyses" gives "meta-analys"/
    # "meta-analyse". "niches" and "axes" are the two where the -ches/-xes rule
    # (right for "patches", "boxes") is wrong.
    "crises": "crisis", "misdiagnoses": "misdiagnosis",
    "keratoses": "keratosis", "thromboses": "thrombosis",
    "niches": "niche", "axes": "axis",
    # `-aches` is NOT a compound tail like the -sis family below: `roaches`,
    # `cockroaches` and `attaches` all end that way and all want the stem. The
    # body parts that ache are a closed set, so they are listed.
    "aches": "ache", "headaches": "headache", "backaches": "backache",
    "toothaches": "toothache", "earaches": "earache",
    "stomachaches": "stomachache", "heartaches": "heartache",
}

#: The `-ses -> -sis` entries above, as COMPOUND tails. `osteosyntheses`,
#: `sub-analyses` and `endoprostheses` are not keys and never will be: the
#: family is open, and the 2026-09-24 store already had three of them plus a
#: `meta‑analyses` spelled with a non-breaking hyphen, which no ASCII key can
#: match. A word ending in one of these, with something in front of it, takes
#: the same singular.
#:
#: Only the `-sis` group, and only tails of 6 characters or more: `men` and
#: `feet` as suffixes would catch `specimens` and `flatfeet`, where the first is
#: not a compound of `man` and the second is not spelled that way anyway.
_SIS_TAILS: tuple[str, ...] = tuple(sorted(
    (k for k, v in _IRREGULAR.items() if k.endswith("ses") and v.endswith("sis")
     and len(k) >= 6),
    key=len, reverse=True))

#: Singular words that merely look plural. Suffix rules mangle these into
#: things like "diabete", "specy" and "sery".
_INVARIANT: frozenset[str] = frozenset({
    "diabetes", "herpes", "scabies", "rabies", "measles", "mumps", "ascites",
    "caries", "facies", "species", "series", "gas", "bias", "lens", "news",
    "genetics", "orthopedics", "pediatrics", "obstetrics", "diagnostics",
    "physics", "ethics", "statistics", "logistics", "mechanics",
    # Latin present participles used as species epithets, and a few Latin
    # nouns. They end -ans/-ens exactly as `clinicians`, `pathogens`,
    # `specimens` and `regimens` do, and no suffix rule separates them, so
    # they are listed for the same reason `_ES_STEM_IS_SINGULAR` is. Every
    # one of these is in the 2026-09-26 store, being turned into a word that
    # does not exist: `Candida albican`, `Serratia marcescen`,
    # `Clostridium perfringen`, `thromboangiitis obliteran`.
    "albicans", "marcescens", "perfringens", "corrodens", "obliterans",
    "xylosoxidans", "ulcerans", "protuberans", "elegans", "necessitans",
    "dissecans", "simulans", "adiacens", "sapiens",
    "glans", "dens", "pseudomonas", "erysipelas",
})

#: Endings that look plural but are not. "sepsis", "dermis", "abscess",
#: "virus", "process", "status" -- a clinical vocabulary is full of them.
_NOT_PLURAL = ("ss", "us", "is", "sis", "ous")

#: -es is dropped only after these; elsewhere a bare -s is dropped instead.
_ES_STEMS = ("x", "ch", "sh", "s", "z")

#: Stems where the `-es` plural sits on a singular that ALREADY ends in a
#: sibilant, so the stem itself is the name: `viruses -> virus`, not `viruse`.
#: A suffix rule cannot find these. "ends in -us" looks like it should work and
#: does not: `caus` (from `causes`), `hous`, `abus` and `bruis` all end in -us
#: or -s and all want the `e` back, while `virus` and `census` do not. The
#: discriminator is which strings are words, so they are listed.
#:
#: The four at the front are the ones measured in the 2026-09-24 store; the
#: rest are clinical -us nouns that would hit the same branch the first time
#: one is extracted, listed now rather than after they are written down wrong.
_ES_STEM_IS_SINGULAR: frozenset[str] = frozenset({
    "virus", "sinus", "census", "lens", "bias", "gas",
    "bolus", "status", "apparatus", "focus", "plexus", "meatus", "fundus",
    "uterus", "thrombus", "fetus", "callus", "humerus", "radius", "nucleus",
    "bonus", "campus", "surplus", "impetus", "consensus",
})


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
    for tail in _SIS_TAILS:                      # osteo|syntheses, sub-|analyses
        if len(w) > len(tail) and w.endswith(tail):
            return [w[:-len(tail)] + _IRREGULAR[tail]]
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
    """Best-effort singular of one word, for LOOKUP — the first of
    :func:`singular_candidates`.

    A wrong guess here is harmless because the answer is only ever looked up: it
    either matches something or it does not. That was true of every caller until
    2026-09-23, when :func:`singular_spelling` began producing the store's NAMES
    from it and a wrong guess started being written down. Naming goes through
    :func:`naming_singular` instead; this function is unchanged so that `fold`
    and every folded lookup built on it keep answering what they always did.
    """
    return singular_candidates(word)[0]


def naming_singular(word: str) -> str:
    """The singular to WRITE for `word`. One answer, chosen not guessed.

    `singular_candidates` returns two for the ambiguous `-es` branch and leaves
    the choice to the caller, because `buses -> bus` drops two characters while
    `phases -> phase` drops one and the surface forms are identical. A lookup
    can try both. A name cannot, and taking the first — the historical guess —
    put `cas`, `dos`, `phas`, `nurs`, `caus` and `expens` on 938 of the store's
    names (1,722 mentions, 96 head nouns), which is how the curator found it:
    "canonical is always the singular, this should have been handled by the
    regex".

    What separates the two, measured over those 96 head nouns:

    * `-ches`, `-shes`, `-xes` — the `-es` is there for pronunciation and the
      stem is the singular: `searches -> search`, `patches -> patch`,
      `meshes -> mesh`, `complexes -> complex`, `indexes -> index`. The two
      exceptions in this vocabulary, `niches` and `axes`, are listed as
      irregular rather than guessed at.
    * `-ses`, `-zes` — the singular already ends in `e` and only the `s` comes
      off: `cases -> case`, `doses -> dose`, `nurses -> nurse`,
      `gauzes -> gauze`, `purposes -> purpose`, `uses -> use`. Unless the stem
      is itself a word ending in a sibilant, which is not something a suffix
      can see and so is listed in `_ES_STEM_IS_SINGULAR`:
      `viruses -> virus`, `censuses -> census`.

    `-sses` never reaches here: `singular_candidates` handles it first and
    returns one candidate (`processes -> process`, `abscesses -> abscess`).
    """
    cands = singular_candidates(word)
    if len(cands) == 1:
        return cands[0]
    drop_two, drop_one = cands
    if word.lower().endswith(("ches", "shes", "xes")):
        return drop_two
    if drop_two in _ES_STEM_IS_SINGULAR:
        return drop_two
    return drop_one


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
    if len(core) > 1 and core.isupper() and core.isalpha():
        # An ALL-CAPS token is an acronym, not an English word, and its final S
        # is part of it. Measured on the 2026-09-24 store: 275 distinct all-caps
        # heads end in S, and the suffix rules were eating the last letter of
        # POSAS, ARDS, NIRS, KOOS, LEFS, ASES and SBSES. The ones that survived
        # did so by accident -- VAS, LOS and HS are under the four-character
        # floor, not recognised as names.
        #
        # The casualties are RESULTS, METHODS and CONCLUSIONS, which stay
        # plural. They are section headings the methodology blocklist is meant
        # to keep out of the store in the first place, so this is the right
        # trade: an acronym is content and a heading is noise.
        return label
    if core[1:] != core[1:].lower():
        # A token with an INTERNAL capital is an acronym or a chemical name --
        # `miRNAs`, `microRNAs`, `iGAS`, `PrUMS`. Its case is not ours to
        # normalise, and the round trip through the lowercase `naming_singular`
        # was destroying it: `miRNAs` came back `mirna` and `iGAS` came back
        # `iga`. Only a trailing LOWERCASE s is a plural on such a token; a
        # trailing capital S is part of it.
        if len(core) > 1 and core.endswith("s"):
            return " ".join(words[:-1] + [core[:-1] + trailing])
        return label
    if core.endswith(("'s", "\u2019s", "'", "\u2019")):
        # A genitive is not a plural. `naming_singular` read the final s of
        # `patient's` as one and answered `patient'` -- a name no one would
        # ever write. The same shape covers a quoted phrase, where the head is
        # `'wound'`. 17 store names on the 2026-09-26 corpus: `patient's`,
        # `fibroblasts'`, `growth factors'`, `'machine learning'`.
        return label
    lowered = core.lower()
    single = naming_singular(lowered)
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
