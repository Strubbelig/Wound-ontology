"""Rule 58 inside names: write out every abbreviation a longer name contains.

    python -u scripts/expand_abbreviations_inside.py [--write]

Curator, 2026-10-02: "inside names too please" -- `PRP therapy`, `VAS score`,
`MRSA infection` hold an abbreviation although they are not one. An
abbreviation PART of a name is a maximal letter-digit run (split at spaces,
hyphens, slashes) holding two or more capitals in a row; Roman numerals
(`stage III`), chemical formulas (`CO2`), isoform suffixes (`-BB`) and
`microRNA` excepted.

Version 2 (2026-10-02, after the first run was read row by row). The first
run filled an abbreviation its own abstracts leave undefined from rule 58's
whole-name decision, and that decision came from ONE abstract: `DNA` had
been defined once as `deep neck abscess`, so `cell-free DNA` became
`cell-free deep neck abscess`; `alpha-SMA` became `alpha-supplementary motor
area`, `SOD activity` `semiocclusive dressing activity`. It also took the
SHORTEST spelled tail (`level laser therapy` for LLLT), kept sentence
fragments as full forms, left abbreviations inside the full forms it wrote
in, and doubled words (`wound bed score score`). Now:

  1. the name's own abstracts, read with `spelled_definitions` (the long form
     must spell the short form letter by letter and be a clean phrase);
  2. otherwise the whole corpus, but only when every spelled definition in it
     and rule 58's own decision name ONE concept -- an abbreviation the
     corpus defines as different things cannot be filled from elsewhere;
  3. otherwise the ontology's exact synonym.

Nothing found, or different things found -> the name goes out of scope (the
curator's rule of 2026-09-30). A one- or two-letter prefix glued to the part
(`A-PRF`, `e-PRP`, `G-LED`) makes the whole token the abbreviation: `A-PRF`
is not `PRF`. The full form is expanded again until no part is left, and a
word the full form repeats from its neighbour is dropped.

The run reads the names the first run renamed by their ORIGINAL spelling,
computes what they should have become, and renames (or puts out) the current
name where that differs; names that still hold an abbreviation get the same
treatment. Dry by default; `--write` backs up the term dict, applies, reads
back.
"""
from __future__ import annotations

import glob
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))

FIRST_RUN = ROOT / "output" / "abbreviation_inside_2026-10-02.json"
BEFORE_FIRST = ROOT / "data" / "backup" / "term_mapping_before_abbreviation_inside_2026-10-02_11-26-03.json"
REPORT = ROOT / "output" / "abbreviation_inside_v2_2026-10-02.json"
BY = "rule 58 inside names, v2 (2026-10-02)"
PART = re.compile(r"[A-Za-z0-9]+")
CAPS = re.compile(r"[A-Z]{2,}")
# a Roman numeral that is one (`stage III`, `type IIIB`); `IL` is interleukin, not 49
ROMAN = re.compile(r"^(?=[IVXL])(XL|L?X{0,3})(IX|IV|V?I{0,3})[A-Da-d]?$")
ABBR_ONLY = re.compile(r"^(?=(?:[^A-Z]*[A-Z]){2})[A-Z0-9][A-Z0-9\-/&+.]*?(s)?$")
# A chemical formula is a name, not an abbreviation: element symbols only, with
# a count or a two-letter element in it (`CO2`, `H2O2`, `TiO2`, `NaCl`), plus
# the hydroxyl group `OH`.
ELEMENTS = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Ti Cr Mn Fe Co Ni Cu Zn Ga Ge "
               "As Se Br Sr Zr Mo Ag Cd Sn Sb I Ba Ce Gd W Pt Au Hg Pb Bi".split())
FORMULA_PIECE = re.compile(r"([A-Z][a-z]?)(\d*)")
BRACKETED_ABBR = re.compile(r"\s*[\[(（]\s*[A-Za-z0-9\-]*[A-Z]{2,}[A-Za-z0-9\-]*\s*[\])）]")
KEEP_PARTS = {"microRNA"}          # curator, 2026-10-02: "keep microRNA"
ISOFORM = re.compile(r"(?<=-)([A-Z])\1$")   # `growth factor-BB`, `-AA`: an isoform, not an abbreviation
GLUED = re.compile(r"[A-Za-z]")             # `A`-PRF, `e`-PRP: a letter glued BEFORE the part makes the token the abbreviation
MNEMONIC = re.compile(r"^[A-Z]{2,}[a-z]{3,}$")   # `TENsin`, `COnsensus`: capitals that spell an acronym, inside a full form
GREEK = re.compile(r"(alpha|beta|gamma|delta|kappa)$")

# One concept spelled differently -> the form kept. The curator's own KEEP
# lists of 2026-09-30 and 2026-10-02 ("if the suggested terms are synonyms
# and only spelling differences: keep"), then the conflicts of this run read
# by Claude under the same rule (SAME_READ, 2026-10-02).
from apply_abbreviation_rulings import KEEP as _KEEP_0930          # noqa: E402
from apply_abbreviation_rulings import UNSPELLED_FIX as _FIX_0930  # noqa: E402
from apply_abbreviation_rulings import UNSPELLED_OUT as _OUT_0930  # noqa: E402
from apply_abbreviation_wide import KEEP as _KEEP_1002             # noqa: E402
from apply_abbreviation_wide import UNSPELLED_FIX as _FIX_1002     # noqa: E402
from apply_abbreviation_wide import UNSPELLED_OUT as _OUT_1002     # noqa: E402
# the unspelled long forms the curator threw out: never read again as a definition
UNSPELLED_BAD = set(_OUT_0930) | set(_OUT_1002)
SAME_READ: dict[str, str] = {
    "DFU": "diabetic foot ulcer",                       # `diabetic fool ulcers`: a typing error
    "HIF-1alpha": "hypoxia-inducible factor 1-alpha",   # `hypoxic inducible factor-1alpha`
    "IMN": "intramedullary nailing",                    # `intermedullary nailing`: a typing error
    "MSC": "mesenchymal stem cell",                     # stem / stromal cell: one cell, two names
    "PBMT": "photobiomodulation therapy",               # `photobiomodulation (therapy)`
    "CRP": "C-reactive protein",                        # `C rectanglereactive protein`: a character lost in the text
}
SAME: dict[str, str] = {**_KEEP_0930, **_FIX_0930, **_KEEP_1002, **_FIX_1002, **SAME_READ}
# A name whose expansion borrowed a meaning from another paper that its own
# paper does not have (every corpus-filled row read, 2026-10-02)
READ_OUT = {
    "alginate-[Mg-Al]-LDH/SDZ film": "LDH here is a layered double hydroxide; the corpus defines LDH only as lactate dehydrogenase",
    "antimicrobial peptide Temporin-SHF": "Temporin-SHF is a peptide name; the corpus defines SHF only as silver hydrofibre",
    "IL STS": "neither part is defined by its abstract; STS borrowed from another paper",
    "ERG overexpression": "ETS-related gene: the corpus defines ETS only as end-to-side",
    # first-run outs the corrected reading would bring back, read and refused:
    # the meaning borrowed from another paper is not this name's
    **{n: why for why, names in {
        "HO-1 is heme oxygenase-1, not heterotopic ossification": [
            "activation of Nrf2/HO-1, STAT3, and Akt pathway", "Nrf2/HO-1 pathway", "HO cytotoxicity"],
        "AMP here is adenosine monophosphate (AMPK), not antimicrobial peptide": [
            "AMP-activated protein kinase", "AMP-activated Protein Kinase alpha", "AMP-activated protein kinase signaling"],
        "TLC here is the lipido-colloid technology, not total leukocyte count": [
            "Andoflex TLC Calamine Lite", "TLC dressing", "neutral TLC foam dressing"],
        "anti-SSA is an autoantibody, not sub-Saharan Africa": ["anti-SSA antibody"],
        "Braden QD is a scale name, not quantum dots": ["Braden QD Scale", "Braden QD-T", "Braden QD-T Scale"],
        "C/EBP is a transcription factor, not enhanced barrier precautions": ["C/EBP homologous protein"],
        "NP here is nanoparticle, not nurse practitioner": [
            "CeO NPs-based nanozyme", "CeO NPs-GOx", "CuS NP", "gold nanoparticle (Au NP", "His-Ag NP",
            "Que NP", "release NP-Cur"],
        "NCS here is a material, not nerve conduction study": ["CS/NCS blended nonwoven fabric", "CS/NCS material"],
        "HPA axis is hypothalamic-pituitary-adrenal, not Human Protein Atlas": ["early-morning HPA-axis dynamic"],
        "ETS-related gene: the corpus defines ETS only as end-to-side": ["ETS-related gene 1"],
        "the definition read is a sentence fragment (`IntroductionImmune`)": ["ICI-induced dermatological toxicity"],
        "the definition read lost `multiple`": ["MLTC burden", "MLTC progression"],
        "NAD is nicotinamide adenine dinucleotide, not non-angiosome directed": ["NAD replenishment"],
        "MB here is methylene blue, not microorganism-binding": ["oral MB", "PVA GV/MB foam", "PVA GV/MB foam dressing"],
        "OTA is the Orthopaedic Trauma Association, not oxidized tannic acid": ["OTA 82B/C calcaneal fracture"],
        "DIEP is deep inferior epigastric perforator, not an eosinophilic pneumonia": ["pedicled vertical DIEP flap"],
        "MAP kinase is mitogen-activated, not mean arterial pressure": ["phospho MAP kinase-ERK kinase"],
        "ON is not osteonecrosis here": ["QS-ON GAS"],
        "EI here is not echo intensity": ["three-layer EI dressing"],
        "WA is WoundAide, not Western Australia": ["WA imaging system", "WA measurement"],
        "DVA tributaries: a developmental venous anomaly, not deep venous arterialization": ["tributaries of DVA"],
    }.items() for n in names},
}
# a word of a curator-kept full form is the curator's spelling, never re-expanded
# (`NOD-like receptor family pyrin domain-containing 3`)
PROTECTED = {w for v in SAME.values() for w in re.split(r"[\s/]+", v)}
# Whole-name rule-58 decisions taken from one abstract against the meaning of
# the term's other abstracts (each use read, 2026-10-02). `DNA`: seven of its
# eight abstracts use it for the molecule and the corpus defines it so (PMID
# 42579608, `deoxyribonucleic acid (DNA)`); the eighth (PMID 41841442, deep
# neck abscess) is the odd one, and its one use goes with the seven.
WHOLE_REMAP = {"DNA": "deoxyribonucleic acid",
               # the shortest-tail reading lost the first word (`low-level`)
               "LLLT": "low-level laser therapy",
               "OOT": "oxygen-ozone therapy",
               "PEGDA": "poly(ethylene glycol) diacrylate",
               "PPC": "polycaprolactone-polydopamine-collagen",
               "PI-DGAME": "pressure ulcer digital game"}
WHOLE_WHY = {"DNA": "7 of its 8 abstracts use it for the molecule; PMID 42579608 defines it so; "
                    "the one definition as deep neck abscess (PMID 41841442) is the odd one"}
WHOLE_OUT = {
    "ADS": "artificial dermal scaffold / anti-discoloration system",
    "CAD": "coronary artery disease / cadaverine",
    "DF": "diabetic foot / dermal fibroblast",
    "EC": "epithelial cell / endothelial cell",
    "FM": "fentanyl-midazolam / DermaBind FM (a product)",
    "FU": "follicular unit / foot ulcer",
    "GF": "growth factor / gauge factor",
    "HGF": "hepatocyte growth factor / human gingival fibroblast",
    "LBP": "lipopolysaccharide-binding protein / low back pain",
    "MBC": "metastatic breast cancer / minimum bactericidal concentration",
    "NLR": "neutrophil to lymphocyte ratio / negative likelihood ratio",
    "NSF": "nasoseptal flap / normal skin fibroblast",
    "OASIS": "obstetric anal sphincter injury / OASIS database",
    "PM": "placental membrane / prosthetic mesh",
    "SAH": "subarachnoid hemorrhage / self-assembled hydrogel",
    "SEA": "spinal epidural abscess / similarity ensemble approach",
    "SPI": "sustained pedal inflow / surgical or sacral pressure injury",
    "STI": "soft tissue infection / sexually transmitted infection",
    "SWI": "sternal wound infection / susceptibility-weighted imaging",
    "TM": "thrombomodulin / tympanic membrane",
    "VG": "Vaseline gauze / vancomycin group",
    "WAS": "wound area size / WAS gene",
}


def is_formula(p: str) -> bool:
    if p in ("OH", "CO", "NO", "NH"):
        return True
    pieces = FORMULA_PIECE.findall(p)
    if "".join(a + b for a, b in pieces) != p or not all(a in ELEMENTS for a, _ in pieces):
        return False
    return any(b for _, b in pieces) or any(len(a) == 2 for a, _ in pieces)


def parts(name: str):
    for m in PART.finditer(name):
        p = m.group(0)
        if p in KEEP_PARTS or p.rstrip("s") in KEEP_PARTS or ROMAN.match(p) or is_formula(p):
            continue
        if ISOFORM.search(name[:m.end()]) and len(p) == 2:
            continue
        if CAPS.search(p):
            yield m


STOP = {"of", "the", "and", "in", "with", "for", "to", "on", "by", "a", "an", "or", "at", "from"}
_normalise = None                     # set in main: pass 0's own vocabulary


def concept(lf: str) -> str:
    """Spellings of one concept fall together: pass 0's vocabulary (`pressure
    injury` = `pressure ulcer`, `disease` = `disorder`), case, hyphens,
    spaces, commas, stop words, plural, British -ae-/-oe-/-ogue/-ise,
    `ulceration` = `ulcer`, `diabetes foot` = `diabetic foot`."""
    if _normalise is not None:
        lf = _normalise(lf).name
    words = re.split(r"[\s\-/,]+", lf.lower())
    out = []
    for w in words:
        w = re.sub(r"[^a-z0-9]", "", w).replace("ae", "e").replace("oe", "e")
        if not w or w in STOP:
            continue
        w = re.sub(r"ogue$", "og", w)
        w = re.sub(r"is(e|ed|er|ers|ing|ation)$", r"iz\1", w)
        w = {"ulceration": "ulcer", "diabetes": "diabetic"}.get(w, w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return "".join(out)


def dedupe(name: str) -> str:
    """`wound bed score score` -> `wound bed score`; `therapy therapy-treated`
    -> `therapy-treated`; a repeated run of up to four words goes once."""
    name = re.sub(r"\b(\w+)\s+\1(?=-)", r"\1", name, flags=re.I)
    toks = name.split(" ")
    for n in (4, 3, 2, 1):
        i = 0
        while i + 2 * n <= len(toks):
            if [t.lower() for t in toks[i:i + n]] == [t.lower() for t in toks[i + n:i + 2 * n]]:
                del toks[i + n:i + 2 * n]
            else:
                i += 1
    return " ".join(toks)


class Expander:
    def __init__(self, text, known, onto, normalise):
        from expand_abbreviations import definitions, dirty, spelled_definitions
        self.text, self.known, self.onto, self.normalise = text, known, onto, normalise
        self.dirty = dirty
        self.defs = {k: spelled_definitions(t) for k, t in text.items()}
        self.raw = {k: definitions(t) for k, t in text.items()}
        self.corpus: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        for k, d in self.defs.items():
            for sf, lf in d.items():
                self.corpus[sf][concept(lf)][lf] += 1

    def _own(self, cand, keys):
        found = defaultdict(Counter)
        for k in keys:
            d = self.defs.get(k, {})
            lf = d.get(cand) or d.get(cand + "s")
            if lf:
                found[concept(lf)][lf] += 1
        return found

    def lookup(self, cands, keys, corpus=True):
        """(full form, source, candidate) or (None, why, None).

        `corpus=False` inside a full form already written in: `ETS-related
        gene 1` must not borrow `ETS` = end-to-side from another paper."""
        for cand in cands:                                   # 1. own abstracts
            found = self._own(cand, keys)
            if len(found) == 1:
                return next(iter(found.values())).most_common(1)[0][0], f"own abstracts define {cand}", cand
            if found:
                if cand in SAME:
                    return SAME[cand], f"curator: {cand} is one concept spelled differently", cand
                return None, f"{cand}: own abstracts define it as different things", None
        for cand in cands:                                   # the curator's one-concept rulings
            if cand in SAME:
                return SAME[cand], f"curator: {cand} is one concept spelled differently", cand
        for cand in (c for c in cands if c not in UNSPELLED_BAD):   # 1b. own abstracts, unspelled
            found = defaultdict(Counter)                     # (`Laboratory Risk Indicator for
            for k in keys:                                   # Necrotizing Fasciitis (LRINEC)`:
                d = self.raw.get(k, {})                      # read, like rule 58's `unspelled`)
                lf = d.get(cand) or d.get(cand + "s")
                if lf and not self.dirty(lf) and not re.search(
                        r"(?<![A-Za-z0-9])" + re.escape(cand) + r"s?(?![A-Za-z0-9])", lf):
                    found[concept(lf)][lf] += 1
            if len(found) == 1:
                return next(iter(found.values())).most_common(1)[0][0], f"UNSPELLED own abstracts define {cand}", cand
            if found:
                return None, f"{cand}: own abstracts define it as different things", None
        for cand in cands:                                   # the reading of 2026-10-02
            if cand in WHOLE_REMAP:
                return WHOLE_REMAP[cand], f"whole-name ruling on {cand}", cand
        if not corpus:                                       # inside a full form: the curator's
            for cand in cands:                               # whole-name decision, else nothing
                if self.known.get(cand):
                    return self.known[cand], f"curator decision on {cand}", cand
        for cand in cands:                                   # used for different things (read)
            if cand in WHOLE_OUT:
                return None, f"{cand}: its abstracts use it for different things ({WHOLE_OUT[cand]})", None
        for cand in cands if corpus else ():                 # 2. corpus + rule 58
            cs = {c: Counter(f) for c, f in self.corpus.get(cand, {}).items()}
            for c, f in self.corpus.get(cand + "s", {}).items():
                cs.setdefault(c, Counter()).update(f)
            # a form that still holds an abbreviation (`platelet-derived GF`,
            # `hospital-acquired PI`) is half written, not a rival concept
            whole = {c: f for c, f in cs.items() if not any(CAPS.search(x) for x in f)}
            if whole:
                cs = whole
            kn = self.known.get(cand)
            if kn:
                cs.setdefault(concept(kn), Counter())[kn] += 1000     # rule 58's spelling wins inside its concept
            if len(cs) == 1:
                return next(iter(cs.values())).most_common(1)[0][0], f"corpus defines {cand} one way", cand
            if cs:
                forms = " / ".join(f.most_common(1)[0][0] for f in cs.values())
                return None, f"{cand}: the corpus defines it as different things ({forms})", None
        for cand in cands:                                   # 3. the ontology
            if self.onto.get(cand):
                return self.onto[cand], f"ontology synonym of {cand}", cand
        return None, f"{cands[0]}: no abstract defines it", None

    def _put(self, new, s, e, full):
        """Write `full` over new[s:e]; a neighbour the full form already says
        goes (`HOT therapy` -> not `... therapy therapy`)."""
        before, after = new[:s], new[e:]
        fw = full.split()
        nxt = re.match(r"\s+(\S+)", after)
        if nxt and fw and (nxt.group(1).lower() == fw[-1].lower()
                           or (len(nxt.group(1)) >= 4 and fw[-1].lower().endswith(nxt.group(1).lower()))):
            after = after[nxt.end():]
        prv = re.search(r"(\S+)\s+$", before)
        if prv and fw and prv.group(1).lower() == fw[0].lower():
            before = before[:prv.start()]
        return before + full + after

    def expand(self, name, keys, depth=0):
        """(new name, [why per part not written out], [sources]).

        Token by token, right to left, so every offset still to be used lies
        to the left of what was written: the whole token first (`HU-MSCs`,
        `IL-6`, `e-PRP`), and only if the token is not defined, its parts."""
        base = BRACKETED_ABBR.sub("", name).strip() or name
        new, bad, used = base, [], []
        tokens = {}
        for m in parts(base):
            lo, hi = m.start(), m.end()
            while lo > 0 and base[lo - 1] not in " /": lo -= 1
            while hi < len(base) and base[hi] not in " /": hi += 1
            raw = base[lo:hi]
            strip_l = len(raw) - len(raw.lstrip("()[],;:"))
            tok = raw.strip("()[],;:")
            tokens.setdefault((lo + strip_l, lo + strip_l + len(tok)), []).append(m)
        corpus = True          # every corpus-filled row is read (READ_OUT); ETS-related gene went out that way
        for (tlo, thi), ms in sorted(tokens.items(), key=lambda kv: -kv[0][0]):
            token = base[tlo:thi]
            if depth and token in PROTECTED:
                continue
            single = len(ms) == 1 and ms[0].group(0) == token
            if not single:
                full, why, hit = self.lookup([token], keys, corpus=corpus)
                if full is not None:
                    new = self._put(new, tlo, thi, full); used.append(why)
                    continue
                chunks = token.split("-")
                first = ms[0].group(0)
                idx = chunks.index(first) if first in chunks else 0
                if any(GLUED.fullmatch(c) for c in chunks[:idx]):
                    bad.append(f"{token}: no abstract defines it")          # `A-PRF` is not `PRF`
                    continue
            for m in sorted(ms, key=lambda m: -m.start()):
                ab = m.group(0)
                if depth and ab in PROTECTED:
                    continue
                if depth and MNEMONIC.match(ab) and not GREEK.search(ab):
                    new = new[:m.start()] + ab.lower() + new[m.end():]
                    continue
                cands = list(dict.fromkeys(c for c in (ab, ab.rstrip("s")) if c))
                full, why, hit = self.lookup(cands, keys, corpus=corpus)
                if full is None:
                    bad.append(why)
                    continue
                new = self._put(new, m.start(), m.end(), full); used.append(why)
        if not bad and new != base and depth < 3:
            again, bad2, used2 = self.expand(new, keys, depth + 1)
            if not bad2:
                new, used = again, used + used2
            else:
                bad += bad2
        return dedupe(re.sub(r"\s+", " ", new).strip()), bad, used


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.normalise import normalise

    DO_WRITE = "--write" in argv          # (a local `write` was once shadowed by a helper: never again)
    p = Orchestrator()
    gt = p.term_mapper._term_mapping

    # the curator's whole-name decisions (rule 58 and the rulings pages):
    # abbreviation -> its full form
    known: dict[str, str] = {}
    for term, rec in gt.records.items():
        if gt.is_alias(term) or not rec.get("to") or rec.get("method") != "curator":
            continue
        t = term.strip()
        if " " in t or not CAPS.search(t) or t in WHOLE_OUT:
            continue
        j = (rec.get("pairs") or {}).get(rec["to"], {}).get("curator") or {}
        if j.get("verdict") == "same_class":
            known[t] = rec["to"]
            if t.endswith("s") and t[:-1].isupper():
                known.setdefault(t[:-1], rec["to"])
    known.update(WHOLE_REMAP)
    # An abbreviation the curator ruled IN as a name of its own, unmapped
    # (`RNA`, the contradiction queue of 2026-09-28), is kept inside a name the
    # way `microRNA` is: the curator's ruling, not a guess.
    for term, rec in gt.records.items():
        t = term.strip()
        if gt.is_alias(term) or rec.get("to") or " " in t or not CAPS.search(t) or not ABBR_ONLY.match(t):
            continue
        if ((rec.get("gate") or {}).get("curator") or {}).get("verdict") == "in":
            KEEP_PARTS.add(t)
    print(f"[inside2] abbreviations the curator kept as names: {sorted(KEEP_PARTS)}")

    import rdflib
    from rdflib.namespace import RDFS
    EXACT = [rdflib.URIRef("http://www.geneontology.org/formats/oboInOwl#hasExactSynonym"),
             rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000118")]
    og = rdflib.Graph()
    og.parse(ROOT / "data" / "ground truth" / "ground_truth_final.owl", format="turtle")
    og.parse(ROOT.parent / "Disease ontologies" / "mild.ttl", format="turtle")
    for mfile in sorted((ROOT.parent / "Disease ontologies" / "Disease ontology modules").glob("*_module.owl")):
        og.parse(mfile)
    syn = defaultdict(set)
    for prop in EXACT:
        for c, v in og.subject_objects(prop):
            lab = og.value(c, RDFS.label)
            if lab is not None and CAPS.search(str(v)):
                syn[str(v).strip()].add(str(lab))
    onto = {k: next(iter(v)) for k, v in syn.items() if len(v) == 1}

    frames = [pd.read_csv(f) for f in sorted(glob.glob(str(ROOT / "data/cache/pubmed_abstracts_*.csv")))]
    df = pd.concat(frames).drop_duplicates("pmid")
    text = {str(r.pmid): re.sub(r"\s+", " ", f"{r.title or ''}. {r.abstract or ''}") for r in df.itertuples()}
    global _normalise
    _normalise = normalise
    X = Expander(text, known, onto, normalise)
    print(f"[inside2] {len(known):,} rule-58 full forms; {len(onto)} ontology synonyms; "
          f"{len(X.corpus):,} abbreviations defined (spelled) in the corpus")

    where = defaultdict(set)
    for key, ents in p.store.view():
        for name in ents:
            where[name].add(key)
    labels = {str(l) for l in p.ontology_labels()}
    first = json.loads(FIRST_RUN.read_text(encoding="utf-8"))
    by_current = defaultdict(list)                # current name -> originals the first run renamed onto it
    for o, t in first["renames"].items():
        by_current[gt.resolve(t)].append(o)

    def in_scope(n):
        return gt.effective_gate_verdict(gt.resolve(n))[0] == "in"

    current = sorted(n for n in where if in_scope(n) and n not in labels
                     and (n in by_current or (not ABBR_ONLY.match(n.strip()) and list(parts(n)))))
    renames, outs, split, same, why_out = {}, {}, {}, 0, Counter()
    how = {}                                      # current name -> (new name, how each part was written out)
    for c in current:
        sources = by_current.get(c) or [c]
        results = {}
        for s in sources:
            if s in READ_OUT:
                results[s] = ("OUT", f"{s}: {READ_OUT[s]}")
                continue
            new, bad, used = X.expand(s, where[c])
            left = [m.group(0) for m in parts(new)
                    if m.group(0) not in PROTECTED
                    and not any(m.group(0) in w for w in PROTECTED if w in new)]
            if not bad and left:
                bad = [f"{a}: still an abbreviation after writing out" for a in left]
            results[s] = ("OUT", "; ".join(bad)) if bad else (normalise(new).name, "; ".join(used))
        targets = {r[0] for r in results.values()}
        if len(targets) > 1 and "OUT" not in targets and len({concept(t) for t in targets}) == 1:
            targets = {c if concept(c) == concept(next(iter(targets))) else next(iter(targets))}
            results = {s: (next(iter(targets)), r[1]) for s, r in results.items()}
        if len(targets) > 1:
            split[c] = results
            continue
        t, why = next(iter(results.values()))
        how[c] = (t, why)
        if t == "OUT":
            outs[c] = why
            why_out[why.split(": ", 1)[-1].split(" (")[0]] += 1
        elif concept(t) != concept(c):            # case and plural churn is not a correction
            renames[c] = t
        else:
            same += 1

    # The first run's outs that the corrected reading writes out: the out it
    # set is lifted (the gate goes back to what it was before that run) and
    # the name is renamed like the others.
    FIRST_BY = "rule 58 inside names (curator, 2026-10-02)"
    before_first = json.loads(BEFORE_FIRST.read_text(encoding="utf-8"))
    where_all = defaultdict(set)
    for key, ents in p.store.view(mapped=False, include_rejected=True):
        for name in ents:
            where_all[name].add(key)
    revive = {}
    for o in first["out"]:
        if o in READ_OUT or gt.peek_gate(gt.resolve(o)).get("curator", {}).get("by") != FIRST_BY:
            continue
        new, bad, used = X.expand(o, where_all.get(o, set()))
        if bad or [m.group(0) for m in parts(new)]:
            continue
        prior = ((before_first.get(o) or {}).get("gate") or {}).get("curator")
        revive[o] = {"to": normalise(new).name, "how": "; ".join(used), "gate before": prior}
    print(f"[inside2] first-run outs written out now: {len(revive)}")

    def final(t, seen=()):
        return final(renames[t], seen + (t,)) if t in renames and t not in seen else t
    for o, r in revive.items():
        if r["to"] != o:
            renames[o] = r["to"]
    renames = {a: gt.resolve(final(b)) for a, b in renames.items()}
    renames = {a: b for a, b in renames.items() if a != b}
    clash = sorted(set(renames) & set(renames.values()))
    for cl in clash:
        renames.pop(cl)
    outs = {t: w for t, w in outs.items() if t not in renames}

    # Whole-name decisions (rule 58) the reading of their uses overturned
    whole = {"remap": {}, "out": {}}
    for t, to in WHOLE_REMAP.items():
        to = gt.resolve(normalise(to).name) if gt.resolve(normalise(to).name) != normalise(to).name else to
        if t in gt.records and gt.records[t].get("to") != to:
            whole["remap"][t] = to
    for t, why in WHOLE_OUT.items():
        if gt.effective_gate_verdict(gt.resolve(t))[0] == "in":
            whole["out"][t] = why

    REPORT.write_text(json.dumps({"renames": renames, "out": outs, "split": split, "how": how, "revive": revive,
                                  "whole name": whole, "clash dropped": clash},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[inside2] {len(current):,} current names checked ({sum(1 for c in current if c in by_current):,} "
          f"renamed by the first run); unchanged {same:,}")
    print(f"[inside2] rename: {len(renames):,}  out: {len(outs):,} {dict(why_out.most_common(6))}  "
          f"split (originals disagree, left alone): {len(split)}")
    print(f"[inside2] whole names: remap {whole['remap']}  out {len(whole['out'])}")
    print(f"[inside2] report {REPORT.relative_to(ROOT)}")
    if not DO_WRITE or "--write" not in argv:
        print("[inside2] dry run; --write to apply")
        return 0

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_abbreviation_inside_v2_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[inside2] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    for t, to in whole["remap"].items():
        old = gt.records.get(t, {}).get("to")
        if old:
            gt.refuse(t, old, reason=f"rule 58 reading corrected: {t} is {to}", by=BY)
        rec = gt.record(t)
        rec.update({"to": to, "confidence": 1.0, "method": "curator"})
        rec.pop("retired", None)
        gt.judge(t, to, curator={"verdict": "same_class", "when": when, "by": BY,
                                 "reason": WHOLE_WHY.get(t, "its own abstracts spell it so, letter by letter; "
                                                            "the first reading had lost a word")})
    for t, why in whole["out"].items():
        gt.gate(t, curator={"verdict": "out", "when": when, "by": BY,
                            "reason": f"its abstracts use it for different things: {why}"})
    for t, why in outs.items():
        gt.gate(t, curator={"verdict": "out", "when": when, "by": BY, "reason": why})
    for o, r in revive.items():
        g = gt.gate_record(o)
        if r["gate before"]:
            g["curator"] = r["gate before"]
        else:
            g.pop("curator", None)
        gt._gate_idx = None
    gt._dirty()
    gt.save()
    rep = p.store.apply_renames(renames, by=BY)
    print(f"[inside2] renames: { {k: v for k, v in rep.items() if not isinstance(v, list)} }")

    fresh = Orchestrator()
    g2 = fresh.term_mapper._term_mapping
    left = [t for t in renames if t in g2.records and not g2.is_alias(t)]
    lost = [t for t in list(outs) + list(whole["out"])
            if g2.peek_gate(g2.resolve(t)).get("curator", {}).get("verdict") != "out"]
    lost += [t for t, to in whole["remap"].items() if g2.data.get(t) != to]
    lost += [o for o in revive if g2.peek_gate(g2.resolve(o)).get("curator", {}).get("by") == FIRST_BY]
    if left or lost:
        raise RuntimeError(f"[inside2] read back: {len(left)} rename(s) and {len(lost)} verdict(s) "
                           f"did not land: {left[:5]} {lost[:5]}")
    print(f"[inside2] written and read back: {len(renames)} renamed, {len(outs)} out, "
          f"{len(whole['remap'])} whole name(s) remapped, {len(whole['out'])} whole name(s) out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
