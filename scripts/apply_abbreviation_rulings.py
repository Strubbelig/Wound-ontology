"""Settle the abbreviations `expand_abbreviations.py` could not (rule 58).

    python -u scripts/apply_abbreviation_rulings.py [--write]

Curator, 2026-09-30: "When there is no suggestion, the abbreviation is out of
scope. If the suggestions are genuinely different: out of scope. If the
suggested terms are synonyms and only spelling differences: keep."

  undefined   no abstract defines it                       -> out
  ambiguous   abstracts define it differently: KEEP below names the ones
              whose forms are one concept spelled differently (`peripheral
              artery disease` / `peripheral arterial disease`), with the form
              kept; every other one is genuinely different (`PI` = pressure
              injury / plaque index / povidone-iodine) -> out
  unspelled   one form, which failed the word-by-word spelling check:
              UNSPELLED_OUT are fragments or still hold an abbreviation
              (`BT to dermal thickness ratio`) -> out; UNSPELLED_FIX are
              fragments whose full form the abstracts write out
              (`personal protective equipment (PPE)`, read from the text);
              the rest are the full form as written -> keep

Dry by default; `--write` backs up the term dict, saves once, reads back.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

SRC = ROOT / "output" / "abbreviation_expansion_2026-09-30.json"
BY = "rule 58: abbreviation ruling (curator, 2026-09-30)"

# ambiguous -> the one form kept (the forms are spellings of one concept)
KEEP: dict[str, str] = {
    "ABC": "antibiotic-impregnated bone cement",
    "AMT": "amniotic membrane transplantation",
    "APG": "autologous platelet-rich gel",
    "BWAT": "Bates-Jensen Wound Assessment Tool",
    "CHX": "chlorhexidine",
    "COL": "collagen",
    "DACC": "dialkylcarbamoyl chloride",
    "DAIR": "debridement, antibiotics, and implant retention",
    "DFD": "diabetes-related foot disease",
    "DPN": "diabetic peripheral neuropathy",
    "DRPI": "device-related pressure injury",
    "DVT": "deep vein thrombosis",
    "EMT": "epithelial-mesenchymal transition",
    "FGSI": "Fournier's Gangrene Severity Index",
    "GAS": "group A Streptococcus",
    "HBOT": "hyperbaric oxygen therapy",
    "L-PRF": "leukocyte- and platelet-rich fibrin",
    "MDR": "multidrug resistance",
    "MDRPI": "medical device-related pressure injury",
    "MPO": "myeloperoxidase",
    "NLRP3": "NOD-like receptor family pyrin domain-containing 3",
    "ORIF": "open reduction and internal fixation",
    "PAD": "peripheral artery disease",
    "PHMB-B": "polyhexamethylene biguanide and betaine",
    "POSAS": "Patient and Observer Scar Assessment Scale",   # other "form" is a misread sentence
    "PRGF": "plasma rich in growth factors",
    "PSF": "posterior spinal fusion",
    "QCS": "quaternized chitosan",
    "RDW": "red cell distribution width",
    "SIH": "secondary intention healing",
    "TEM": "transmission electron microscopy",          # other "form" is a misread sentence
    "UBT": "urea breath test",
    "UCH-L1": "ubiquitin carboxyl-terminal hydrolase L1",
    "VAS": "visual analogue scale",
    "VEGFR2": "vascular endothelial growth factor receptor 2",
    "VLU": "venous leg ulcer",
}

UNSPELLED_OUT = {"BBD", "BSHS-B-AR", "BT/DT", "BWAT-CUA", "BWD+PHMB", "CISEB", "MBP+OAB",
                 "MDR-DFI", "MOF-PU", "MP-SJS", "OESM", "PASH", "PVP-F", "RE-AC", "SI-RFA",
                 "SST-DFI", "TL-01"}
UNSPELLED_FIX = {"PPE": "personal protective equipment",
                 "TLC-NOSF": "Lipido-Colloid Technology-Nano-OligoSaccharide Factor",
                 "PAMCAI": "Personalized and Multi-dimensional Compression Assessment and Intervention"}


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.normalise import normalise

    write = "--write" in argv
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    names_by_key = defaultdict(Counter)
    for _, ents in p.store.view(mapped=False):
        for name in ents:
            names_by_key[normalise(name).key][name] += 1

    def target(form: str) -> str:
        got = names_by_key.get(normalise(form).key)
        return got.most_common(1)[0][0] if got else normalise(form).name

    maps, outs = {}, {}
    amb = {r["term"]: r for r in rows["ambiguous"]}
    unknown = sorted(set(KEEP) - set(amb))
    if unknown:
        raise SystemExit(f"KEEP names terms that are not ambiguous: {unknown}")
    for t in amb:
        if t in KEEP:
            maps[t] = (target(KEEP[t]), "abstracts spell one concept differently: " + " / ".join(amb[t]["forms"]))
        else:
            outs[t] = "abstracts define it as different things: " + " / ".join(amb[t]["forms"])
    uns = {r["term"]: r for r in rows["unspelled"]}
    bad = sorted((UNSPELLED_OUT | set(UNSPELLED_FIX)) - set(uns))
    if bad:
        raise SystemExit(f"names not in the unspelled list: {bad}")
    for t, r in uns.items():
        if t in UNSPELLED_OUT:
            outs[t] = f"no usable full form (abstract wrote {r['as written']!r})"
        elif t in UNSPELLED_FIX:
            maps[t] = (target(UNSPELLED_FIX[t]), "full form as the abstracts write it out")
        else:
            maps[t] = (r["to"], f"full form as written: {r['as written']!r}")
    for r in rows["undefined"]:
        if r["abstracts"] >= 2:
            outs[r["term"]] = "abbreviation only; no abstract that uses it defines it"

    print(f"[abbr2] map {len(maps)}  e.g. {list(maps.items())[:6]}")
    print(f"[abbr2] out {len(outs)}  e.g. {list(outs)[:15]}")
    if not write:
        print("[abbr2] dry run; --write to apply")
        return 0

    latest = sorted((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"))[-1]
    backup = ROOT / "data" / "backup" / f"term_mapping_before_abbreviation_rulings_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[abbr2] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    for t, (to, why) in maps.items():
        rec = gt.record(t)
        rec.update({"to": to, "confidence": 1.0, "method": "curator"})
        rec.pop("retired", None)
        gt.judge(t, to, curator={"verdict": "same_class", "when": when, "by": BY, "reason": why})
    for t, why in outs.items():
        gt.gate(t, curator={"verdict": "out", "when": when, "by": BY, "reason": why})
    gt._dirty()
    gt.save()                                   # once: see expand_abbreviations.py
    print(f"[abbr2] gate lists re-exported: {p.export_gate_lists()}")

    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate
    g2 = TermMappingAndGate(DataManager(), file_name="term_mapping")
    lost = [t for t, (to, _) in maps.items() if g2.data.get(t) != to]
    lost += [t for t in outs if g2.peek_gate(g2.resolve(t)).get("curator", {}).get("verdict") != "out"]
    if lost:
        raise RuntimeError(f"{len(lost)} decision(s) did not land: {lost[:10]}")
    print(f"[abbr2] written and read back: {len(maps)} mapped, {len(outs)} out of scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
