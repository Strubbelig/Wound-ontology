#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Disease names are diagnoses: the curator's 2026-10-31 rule, written into the term dict.

    python -u scripts/diseases_are_diagnoses_term_dict_2026_10_31.py            # dry run
    python -u scripts/diseases_are_diagnoses_term_dict_2026_10_31.py --write

The curator: "wir müssen alle krankheitsnamen unter diagnose schieben. die
vaskulitis ist die diagnose, nicht die krankheit." WONT 10-31h moves 22 of its
classes from material disease entity (MILD_120020) to disease diagnostic result
(MILD_120024); what one can point at in the patient stays material (his choice:
"Nur die 22 Krankheitsnamen"). The extension must follow, or every extension
term under a moved class is typed material and an information entity at once.
Claude read each extension term the rule touches -- the ones under a moved class
and the ones placed straight under material disease entity -- and sorted it:

* a disease name is a diagnosis: its category is information entity, every
  material placement (material entity, material disease entity, OGMS disorder,
  MILD's retired compound pathological disorder) gets the author's `no`, and a
  term placed straight under material disease entity is placed under disease
  diagnostic result instead;
* a thing one can point at (THINGS_UNDER_DX) leaves the diagnosis it was placed
  under and is placed under material disease entity, or keeps only Wound;
* a thing already straight under material disease entity (THINGS_DIRECT) is
  left as it is and named, so the curator sees the reading.

The author's own earlier `yes` (the placement review of 2026-10-02, the term
rulings of 2026-10-18) gives way to his newer rule; every `no` names it.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

W = "https://bioportal.bioontology.org/ontologies/WONT/"
MILD = "https://bioportal.bioontology.org/ontologies/MILD/"
OBO = "http://purl.obolibrary.org/obo/"
MDE, DDR = MILD + "MILD_120020", MILD + "MILD_120024"
MDE_KEY, DDR_KEY = "material disease entity", "disease diagnostic result"
#: placements that make a term material; a diagnosis takes none of them
MATERIAL_IRIS = {MDE, OBO + "OGMS_0000045", MILD + "MILD_120049", OBO + "BFO_0000040"}
#: the 22 WONT classes 10-31h moved (scripts/diseases_are_diagnoses_2026_10_31.py)
MOVED = {W + i for i in (
    "WONT_0000013 WONT_0000466 WONT_0000201 WONT_0000229 WONT_0000469 WONT_0000049 WONT_0000050 WONT_0000467 "
    "WONT_0000443 WONT_0000111 WONT_0000115 WONT_0003586 WONT_0000173 WONT_0000174 WONT_0000447 WONT_0000446 "
    "WONT_0000559 WONT_0000233 WONT_0000558 WONT_0000550 WONT_0000468 WONT_0000408").split()}
CURATED = ["ANCA-associated Vasculitis", "Angiopathy", "Microangiopathy", "Peripheral arterial occlusive disease",
           "Autoimmune tissue disorder", "Bullosis diabeticorum", "Bullous impetigo", "Diabetic metabolic disorder",
           "Erysipelas", "Fixed drug exanthema", "Fournier's gangrene", "Immunodeficiency disorder",
           "Linear IgA dermatosis", "Livedovasculopathy", "MRSA infection", "Mucous membrane pemphigoid",
           "Osteomyelitis", "Phlegmon", "Sepsis", "Surgical site infection", "Venous insufficiency disorder",
           "Wound healing disorder"]
#: Claude's reading: things one can point at, placed under a moved diagnosis
THINGS_UNDER_DX = {"aneurysm", "arterial calcification", "chronic total occlusion", "coronary artery calcification",
                   "infrapopliteal lesion", "nonresponsive wound", "pathological scar", "telangiectasia",
                   "tibial artery lesion", "vascular calcification", "vascular lesion", "wound contracture"}
#: Claude's reading: things one can point at, straight under material disease entity -- left as they are
THINGS_DIRECT = {"bone lesion", "inflammatory lesion", "lesion", "local lesion", "local skin reaction",
                 "lower-extremity lesion", "oral lesion", "pathological fracture", "skin lesion", "skin reaction",
                 "stricture", "structural abnormality"}
SAID = ("curator 2026-10-31: \"wir müssen alle krankheitsnamen unter diagnose schieben. die vaskulitis ist die "
        "diagnose, nicht die krankheit.\"")
WHY_DX = SAID + "; a disease name names a diagnosis, an information entity (WONT 10-31h); applied to this term by Claude"
WHY_THING = SAID + "; this name names one thing in the patient one can point at, which stays material; read by Claude"


def main(argv: list[str]) -> int:
    import rdflib
    from rdflib import RDFS, URIRef
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.mappers.judgements import current, rank, AUTHOR
    from wound_ontology.mappers.term_mapping_and_gate import TERM_RULING
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)

    # The terms the rule touches, read off the extension as last built: under a moved class, or
    # straight under material disease entity outside the wound and necrosis trees.
    g = rdflib.Graph().parse(ROOT / "data" / "ground truth" / "ground_truth_final_2026-10-31h.owl", format="turtle")
    core = rdflib.Graph().parse(ROOT / "output" / "owl" / "wont_extended_core.ttl", format="turtle")
    both = g + core
    gt_iris = {s for s in g.subjects() if isinstance(s, URIRef)}

    def below(u):
        acc, stack = set(), [URIRef(u)]
        while stack:
            for s in both.subjects(RDFS.subClassOf, stack.pop()):
                if isinstance(s, URIRef) and s not in acc:
                    acc.add(s); stack.append(s)
        return acc
    material_wont = {W + "WONT_0007817", W + "WONT_120020", W + "WONT_0000141", W + "WONT_0000472", W + "WONT_0000276",
                     W + "WONT_0000110", W + "WONT_0000178", W + "WONT_0000470", W + "WONT_0000464", W + "WONT_0000392"}
    keep_out = set().union(*(below(u) | {URIRef(u)} for u in material_wont))
    under_dx = set().union(*(below(u) for u in MOVED)) - gt_iris
    direct = {s for s in both.subjects(RDFS.subClassOf, URIRef(MDE)) if isinstance(s, URIRef)} - gt_iris - keep_out
    labels = lambda u: str(next(both.objects(u, RDFS.label)))  # noqa: E731
    touched = {labels(u): ("dx" if u in under_dx else "direct") for u in under_dx | direct}

    low = {k.lower(): k for k in gt.records}

    def key(name):
        k = gt.concept(gt.resolve(name))
        if k not in gt.records:
            k = gt.concept(gt.resolve(low.get(name.lower(), name)))
        return k if k in gt.records else None

    def yes_keys(k):
        out = {}
        for tgt, js in (gt.records[k].get("is_a") or {}).items():
            cj = current(js)
            if cj and cj["verdict"] == "yes":
                out[tgt] = next((j.get("iri") for j in js if j.get("iri")), None)
        return out

    log = {"diagnosis": [], "thing_moved": [], "thing_left": [], "curated": [], "missing": []}
    n_no = n_yes = n_cat = 0

    def no(k, tgt, why):
        nonlocal n_no
        gt._put(k, "is_a", gt._j("no", "author", why), tgt); n_no += 1

    def as_diagnosis(k, place_under_ddr):
        nonlocal n_yes, n_cat
        ys = yes_keys(k)
        for tgt, iri in ys.items():
            if iri in MATERIAL_IRIS or (iri is None and tgt == "material entity"):
                if iri is None:
                    continue  # the category, replaced below
                no(k, tgt, WHY_DX)
        if place_under_ddr and DDR_KEY not in ys:
            gt._put(k, "is_a", gt._j("yes", "author", WHY_DX, iri=DDR), DDR_KEY); n_yes += 1
        if gt.set_category(k, "information entity", source=TERM_RULING, note=WHY_DX) == "set":
            n_cat += 1

    for name, where in sorted(touched.items()):
        k = key(name)
        if k is None:
            log["missing"].append(name)
            continue
        lname = name.lower()
        if lname in THINGS_UNDER_DX:
            if where != "dx":
                raise RuntimeError(f"{name}: read as a thing under a diagnosis, but it is not under one")
            ys = yes_keys(k)
            gone = [t for t, iri in ys.items() if iri in MOVED]
            for t in gone:
                no(k, t, WHY_THING)
            if not any(iri == MDE or iri == W + "WONT_0000380" for iri in ys.values()):
                gt._put(k, "is_a", gt._j("yes", "author", WHY_THING, iri=MDE), MDE_KEY); n_yes += 1
            log["thing_moved"].append((name, gone))
        elif lname in THINGS_DIRECT:
            if where != "direct":
                raise RuntimeError(f"{name}: read as a thing straight under material disease entity, but it is not")
            log["thing_left"].append(name)
        else:
            as_diagnosis(k, place_under_ddr=(where == "direct"))
            log["diagnosis"].append((name, where))
    for name in CURATED:
        k = key(name)
        if k is None:
            continue
        as_diagnosis(k, place_under_ddr=False)
        log["curated"].append(name)
    stray = (THINGS_UNDER_DX | THINGS_DIRECT) - {n.lower() for n in touched}
    if stray:
        raise RuntimeError(f"read as things but not among the touched terms: {sorted(stray)}")

    print(f"[dx-terms] {live.name}: {len(touched)} extension terms touched "
          f"({sum(1 for v in touched.values() if v == 'dx')} under a moved class, "
          f"{sum(1 for v in touched.values() if v == 'direct')} straight under material disease entity)")
    print(f"[dx-terms]   diagnoses {len(log['diagnosis'])}, things moved to material disease entity "
          f"{len(log['thing_moved'])}, things left {len(log['thing_left'])}, curated names {len(log['curated'])}; "
          f"author 'no' {n_no}, 'yes' on a parent {n_yes}, category set to information entity {n_cat}")
    print(f"[dx-terms]   things moved: {', '.join(n for n, _ in log['thing_moved'])}")
    print(f"[dx-terms]   things left: {', '.join(log['thing_left'])}")
    if log["missing"]:
        print(f"[dx-terms]   *** no record for {len(log['missing'])}: {log['missing']} ***")
    out = ROOT / "output" / "diseases_are_diagnoses_terms_2026-10-31.json"
    out.write_text(json.dumps(log, indent=1, ensure_ascii=False))

    if "--write" not in argv:
        print("[dx-terms] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_diagnoses_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[dx-terms] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()

    g2 = Orchestrator().term_mapper._term_mapping
    cats = g2.categories()
    bad = [n for n, _ in log["diagnosis"] if (cats.get(g2.concept(g2.resolve(n))) or {}).get("verdict") != "information entity"
           and key(n) is not None and (cats.get(key(n)) or {}).get("verdict") != "information entity"]
    if bad:
        raise SystemExit(f"[dx-terms] read back: {len(bad)} diagnoses not typed information entity: {bad[:10]}")
    print(f"[dx-terms] read back: every diagnosis typed information entity; written {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
