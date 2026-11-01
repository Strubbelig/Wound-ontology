#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Anatomical regions and sites out of scope, by the author (2026-10-30).

    python -u scripts/apply_anatomical_regions_out_2026_10_30.py           # dry run: the lists
    python -u scripts/apply_anatomical_regions_out_2026_10_30.py --write   # scope `out` by the author

The author, 2026-10-30, on the dispute page's 35 "immaterial anatomical entity"
rows: "du kannst diese ganzen anatomischen regionen und sites löschen, denke
ich. die gehören alle unter http://purl.org/sig/ont/fma/fma67504 und da sind
alle regionen schon. ich brauche keinen neuen erfinden." FMA_67504 is FMA's
Subdivision of cardinal body part (thorax, forearm, hand, nose, scrotum ...).

The classes are every class the WONT addition minted below an anatomical
entity (FMA, UBERON or CARO; 363), plus three regions placed under a spatial
region. Each was read by name and sorted into one of four groups:

  REGIONS  body regions, body parts as subdivisions, sides, aspects, positions
  SITES    a place named by what happened there (donor site, incision site,
           lesion location)
  WOUND    a part or feature of the wound itself (tunnel, undermining, wound
           boundary): FMA has none of these -- asked, not written
  OTHER    cells, tissues, organs, bones, vessels, organisms: not regions --
           asked, not written

REGIONS and SITES get a scope `out` by the author on their concept. A class
that falls in no group, or a name that resolves to no term, stops the run.

Asked the same day, the author answered: WOUND "Bleiben" (they describe the
wound, FMA has none of them; nothing written), OTHER "Alle raus" (FMA, UBERON,
the Cell Ontology and NCBITaxon hold them; no new anatomical class): OTHER is
written `out` as well, with its own reason. A term already out by the author
is not written again.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

# the addition the author decided on (run k, 2026-10-29 23:38); the run that
# put the regions out backed it up here before writing the next one
CORE = ROOT / "data" / "backup" / "core_2026-10-30_09-40-22" / "wont_extended_core.ttl"
WHEN = "2026-10-30"
REASON = ("anatomical region or site: FMA's Subdivision of cardinal body part (FMA_67504) and its parts "
          "already hold every region, no new class (author, 2026-10-30: \"ich brauche keinen neuen erfinden\")")

REGIONS = {
    "Abdomen", "Abdominal Cavity", "Abdominal Wall", "Anatomical Area", "Anatomical Location", "Anatomical Site",
    "Angiosome", "Ankle", "Anterior Abdominal Wall", "Arm", "Axilla", "Back", "Bilateral Lower Extremity",
    "Body Area", "Body Region", "Body Surface", "Bone Prominence", "Breast", "Buccal Side", "Buttock",
    "Cervical Region", "Chest", "Chest Wall", "Chest Wall Anatomy", "Chin", "Compartment",
    "Contralateral Extremity", "Contralateral Side", "Digit", "Distal Lower Extremity", "Distal Third",
    "Dominant Extremity", "Dorsal Aspect", "Dorsum", "Dorsum Of The Foot", "Ear", "Extremity", "Eyelid", "Face",
    "Facial Region", "Femoropopliteal", "Finger", "Forearm", "Forefoot Region", "Forehead", "Genital",
    "Genital Region", "Hand", "Head", "Head And Neck Region", "High-Risk Anatomical Site", "Index Extremity",
    "Intertriginous Area", "Ischial", "Knee", "Lateral Compartment", "Left Arm", "Left Breast", "Left Hand",
    "Left Lower Extremity", "Lower Abdominal Region", "Lower Extremity", "Medial Aspect", "Medial Compartment",
    "Mediastinum", "Mouth", "Neck", "Non-Dominant Extremity", "Nose", "Nose Bridge", "Orbital", "Pelvic",
    "Pelvic Floor", "Pelvic Side Wall", "Perianal Area", "Perineal", "Perineal And Genital Re-Gion",
    "Perineal Region", "Plantar Surface", "Posterior Region", "Pressure Point", "Proximal Stump", "Quadrant",
    "Residual Extremity", "Retro-Rectus", "Retroperitoneal", "Retroperitoneum", "Right Extremity",
    "Right Inguinal Region", "Right Shoulder", "Right Side", "Right Side Of The Face", "Sacral Area",
    "Sacral Region", "Scalp", "Scrotum", "Shoulder Region", "Sinonasal Cavity", "Stump", "Tendon Insertion",
    "Thigh Region", "Thorax", "Thumb", "Tibial Insertion", "Toe", "Treated Extremity", "Trochanteric Region",
    "Trunk", "Upper And Lower Extremity", "Upper Arm", "Upper Extremity", "Upper Leg", "Weight-Bearing Region",
    "Wound Angiosome Area", "Wrist",
    # placed under a spatial region, not under an anatomical entity
    "Heel Region", "Inguinal Region", "High-Risk Region",
}
SITES = {
    "Biopsy Site", "Burn Location", "Burn Site", "Defect Area", "Defect Location", "Defect Site",
    "Diabetic Foot Ulcer Site", "Donor Area", "Extraction Site", "Flap Donor Site", "Harvest Site",
    "Incision Site", "Injury Site", "Lesion Location", "Operative Site", "Organ Space", "Puncture Site",
    "Recipient Site", "Scar Location", "Skin Graft Area", "Skin Graft Donor Site",
    "Split Thickness Skin Grafts Donor Site", "Surgical Site", "Vein Harvest Site", "Wound Site",
}
WOUND = {
    "Bone Exposure", "Bone Margin", "Center Of The Wound", "Dead Space", "Exposed Critical Structure",
    "Extraction Socket", "Non-Epithelialized Area", "Perforation", "Pocket", "Pressure Ulcer Surface", "Raw Area",
    "Skin Incision", "Socket", "Superficial Wound Dehiscence", "Surgical Cavity", "Tissue Plane", "Tunnel",
    "Ulcerated Area", "Undermining", "Wound Boundary", "Wound Opening",
}
REASON_OTHER = ("anatomy that is not a region (cell, tissue, organ, bone, vessel, organism): FMA, UBERON, the Cell "
                "Ontology and NCBITaxon already hold it, no new class (author, 2026-10-30, asked about these 202: "
                "\"Alle raus\")")
SPATIAL = {"Heel Region", "Inguinal Region", "High-Risk Region"}
ANATOMY_ROOTS = ("FMA_62955", "UBERON_0001062", "UBERON_0000466", "UBERON_0000465", "FMA_67165", "FMA_61775",
                 "FMA_67135", "CARO_0000000", "UBERON_0000061", "UBERON_0000475")


def minted_anatomy() -> dict[str, str]:
    """label -> IRI of every class the addition minted below an anatomical entity, plus SPATIAL."""
    import rdflib
    from rdflib.namespace import OWL, RDF, RDFS
    from config.settings import GROUND_TRUTH_TTL, MILD_TTL, MILD_MODULES_DIR
    g = rdflib.Graph()
    for f in (GROUND_TRUTH_TTL, MILD_TTL):
        g.parse(str(f), format="turtle")
    for m in sorted(Path(MILD_MODULES_DIR).glob("*_module.owl")):
        g.parse(str(m))
    core = rdflib.Graph()
    core.parse(str(CORE), format="turtle")
    g += core
    src = rdflib.URIRef("http://www.geneontology.org/formats/oboInOwl#source")
    roots = {rdflib.URIRef("http://purl.obolibrary.org/obo/" + r) for r in ANATOMY_ROOTS}
    out = {}
    for s in core.subjects(RDF.type, OWL.Class):
        if core.value(s, src) is None:
            continue
        lab = str(core.value(s, RDFS.label))
        seen, todo = set(), [s]
        while todo:
            for o in g.objects(todo.pop(), RDFS.subClassOf):
                if isinstance(o, rdflib.URIRef) and o not in seen:
                    seen.add(o)
                    todo.append(o)
        if seen & roots or lab in SPATIAL:
            out[lab] = str(s)
    return out


def main(argv: list[str]) -> int:
    from wound_ontology.data_manager.data_manager import DataManager
    from wound_ontology.mappers.term_mapping_and_gate import TermMappingAndGate

    classes = minted_anatomy()
    groups = {"regions": REGIONS, "sites": SITES, "wound": WOUND}
    for a in groups:
        for b in groups:
            if a < b and groups[a] & groups[b]:
                raise SystemExit(f"*** in two groups ({a}, {b}): {sorted(groups[a] & groups[b])} ***")
    named = REGIONS | SITES | WOUND
    missing = sorted(named - set(classes))
    if missing:
        raise SystemExit(f"*** named here but not a minted anatomical class of the addition: {missing} ***")
    other = sorted(set(classes) - named)
    print(f"[anatomy-out] {len(classes)} minted anatomical classes: {len(REGIONS)} regions, {len(SITES)} sites, "
          f"{len(WOUND)} parts of the wound (stay), {len(other)} other (out)")

    from wound_ontology.utils.string_utils import normalize_term as N
    gt = TermMappingAndGate(DataManager())
    # the addition writes a class's label in title case ("Sacral Region"); the
    # term dict names the concept as the abstracts did ("Sacral region")
    concepts = defaultdict(set)
    for t in gt.records:
        try:
            c = gt.concept(gt.resolve(t))
        except RuntimeError:
            continue
        concepts[N(c)].add(c)
    todo, unresolved = [], []
    for lab in sorted(REGIONS | SITES | set(other)):
        found = concepts.get(N(lab), set())
        if len(found) != 1:
            unresolved.append((lab, f"{len(found)} concept(s) by that name: {sorted(found)}"))
            continue
        concept = next(iter(found))
        if concept not in gt.records:
            unresolved.append((lab, f"concept {concept!r} has no record"))
            continue
        todo.append((lab, concept, gt.gate_verdict(concept)))
    already = [t for t in todo if t[2] == ("out", "author")]
    todo = [t for t in todo if t[2] != ("out", "author")]
    if len({c for _, c, _ in todo}) != len(todo):
        raise SystemExit("*** two classes resolve to one concept; nothing written ***")
    if unresolved:
        for lab, why in unresolved:
            print(f"[anatomy-out] *** {lab}: {why} ***")
        raise SystemExit(f"*** {len(unresolved)} class(es) resolve to no term; nothing written ***")
    print(f"[anatomy-out] {len(todo)} term(s) to put out; {len(already)} already out by the author (not written again); "
          f"scope before: {dict(sorted(__import__('collections').Counter(f'{v} by {b}' for _, _, (v, b) in todo).items()))}")
    out_dir = ROOT / "data" / "review" / "anatomical_regions_2026-10-30"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "groups.json").write_text(json.dumps({
        "regions": sorted(REGIONS), "sites": sorted(SITES), "wound (author: stay)": sorted(WOUND),
        "other (author: out)": other, "iri": classes}, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--write" not in argv:
        print("[anatomy-out] dry run; --write puts them out")
        return 0

    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_anatomy_out_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[anatomy-out] backed up {live.name} -> {backup.relative_to(ROOT)}")
    for lab, concept, _ in todo:
        why = REASON if lab in REGIONS | SITES else REASON_OTHER
        gt.gate(concept, curator={"verdict": "out", "by": "author", "when": WHEN, "reason": why})
    gt._dirty()
    gt.save()
    check = TermMappingAndGate(DataManager())
    wrong = [(lab, c, check.gate_verdict(c)) for lab, c, _ in todo if check.gate_verdict(c) != ("out", "author")]
    if wrong:
        raise SystemExit(f"*** read back: {len(wrong)} not out by the author: {wrong[:10]} ***")
    print(f"[anatomy-out] written and read back: {len(todo)} term(s) out by the author")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
