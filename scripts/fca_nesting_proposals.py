"""FCA nesting proposals for the curator (2026-10-04). Read-only on the ontology.

    python -u scripts/fca_nesting_proposals.py OUT.json

Curator: "review page please" -- for what FCA suggested. FCA groups classes
that share properties; it does not say which class goes under which. Each
proposal below is one subclass edge Claude read off a grouping, with the
grouping's shared properties, the model's verdicts behind them (the Opus
gap-fill trial of 2026-10-02 on the Chronic Wound subtree, clean columns,
rule 66) and Claude's reading. ELK checks each edge alone against the current
core. Proposals on existing WONT classes would go into the addition (rule 69).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))

LX = "shared: part of lower extremity, part of skin (model: true of every instance)"
PROPOSALS = [
    # (id, child, parent, source, shared, reading, verdict)
    ("n01", "Chronic Lower-Extremity Ulcer", "Chronic Lower Extremity Wound", "FCA, Chronic Wound subtree", LX,
     "An ulcer is a wound; same site.", "agree"),
    ("n02", "Chronic Leg Ulcer", "Chronic Lower-Extremity Ulcer", "FCA, Chronic Wound subtree", LX,
     "The leg is part of the lower extremity.", "agree"),
    ("n03", "Chronic Foot Ulcer", "Chronic Lower-Extremity Ulcer", "FCA, Chronic Wound subtree",
     LX + "; part of foot", "The foot is part of the lower extremity.", "agree"),
    ("n04", "Chronic Heel Ulcer", "Chronic Foot Ulcer", "FCA, Chronic Wound subtree",
     LX + "; part of foot (shared only by these two)", "The heel is part of the foot.", "agree"),
    ("n05", "Chronic Leg And Foot Ulcer", "Chronic Lower-Extremity Ulcer", "FCA, Chronic Wound subtree", LX,
     "Leg and/or foot: lower extremity either way; not under leg or foot alone.", "agree"),
    ("n06", "Non-Healing Chronic Lower Leg Ulcer", "Chronic Leg Ulcer", "FCA, Chronic Wound subtree",
     LX + "; nonhealing", "A lower-leg ulcer is a leg ulcer.", "agree"),
    ("n07", "Chronic Leg Wound", "Chronic Lower Extremity Wound", "FCA, Chronic Wound subtree", LX,
     "The leg is part of the lower extremity.", "agree"),
    ("n08", "Chronic Leg Ulcer", "Chronic Leg Wound", "FCA, Chronic Wound subtree", LX,
     "An ulcer is a wound; a second parent beside Chronic Lower-Extremity Ulcer.", "agree"),
    ("n09", "Lower-Extremity Hard-To-Heal Wound", "Chronic Lower Extremity Wound", "FCA, Chronic Wound subtree",
     LX + "; nonhealing", "Hard-to-heal and chronic are used as one here; it sits under Chronic Wound already.",
     "agree"),
    ("n10", "Chronic Neuropathic Ulcer", "Chronic Lower-Extremity Ulcer", "FCA, Chronic Wound subtree", LX,
     "The model says every neuropathic ulcer is on the lower extremity; usually on the foot, but not by "
     "definition.", "doubt"),
    ("n11", "Chronic Ulcer", "Chronic Lower Extremity Wound", "FCA, Chronic Wound subtree", LX,
     "FCA grouped it because the model said lower extremity for every instance; chronic ulcers occur "
     "anywhere. Rather the other way: the lower-extremity ulcers are chronic ulcers (next section).", "disagree"),
    ("n12", "Chronic Lower-Extremity Ulcer", "Chronic Ulcer", "the class names, correcting the Chronic Ulcer grouping",
     "-", "A chronic lower-extremity ulcer is a chronic ulcer.", "agree"),
    ("n13", "Diabetic foot ulcer", "Chronic wound", "FCA, Wound subtree, abstracts only",
     "shared with Chronic wound: time to healing, wound area, chronic, pain",
     "WONT places it under Diabetic wound only. Most are chronic, but an acute, new diabetic foot ulcer "
     "is still one.", "doubt"),
    ("n14", "Pressure ulcer", "Chronic wound", "FCA, Wound subtree, abstracts only",
     "shared with Chronic wound: wound size, depth, healing rate",
     "A stage 1 pressure injury is acute; not every pressure ulcer is chronic.", "disagree"),
    ("n15", "Ulcus cruris mixtum", "Chronic wound", "FCA, Wound subtree, abstracts only",
     "shared with Diabetic foot ulcer and Pressure ulcer: chronic-wound qualities",
     "A mixed arterial-venous leg ulcer is a chronic leg ulcer by definition.", "agree"),
    ("n16", "Chronic Foot Ulcer", "(new class: chronic ulcer with amputation risk)", "FCA, Chronic Wound subtree",
     "shared with Chronic Neuropathic Ulcer only: amputation risk",
     "A risk is a tendency, not a kind of ulcer; no new class.", "disagree"),
]


def main(out: str) -> int:
    import rdflib
    from rdflib.namespace import RDFS, OWL, RDF
    from build_wont_core import elk_unsat, CORE
    core = rdflib.Graph(); core.parse(CORE, format="turtle")
    by_label = {}
    for s, o in core.subject_objects(RDFS.label):
        by_label.setdefault(str(o).lower(), s)
    gt = rdflib.Graph(); gt.parse(ROOT / "data" / "ground truth" / "ground_truth_final.owl", format="turtle")
    curated = set(gt.subjects(RDF.type, OWL.Class))
    base = elk_unsat(core, label="core")
    rows = []
    for pid, child, parent, source, shared, reading, verdict in PROPOSALS:
        c, p = by_label.get(child.lower()), by_label.get(parent.lower())
        if c is None:
            raise SystemExit(f"[nest] {child!r} is not a class in the core")
        elk = "not applicable (no class)"
        already = False
        if p is not None:
            already = (c, RDFS.subClassOf, p) in core
            g = rdflib.Graph(); g += core; g.add((c, RDFS.subClassOf, p))
            bad = elk_unsat(g, label=pid) - base
            elk = "ok" if not bad else "unsatisfiable: " + ", ".join(sorted(str(core.value(x, RDFS.label) or x) for x in bad))
        rows.append({"id": pid, "child": child, "parent": parent, "child_iri": str(c), "parent_iri": str(p or ""),
                     "child_curated": c in curated, "source": source, "shared": shared, "reading": reading,
                     "claude": verdict, "elk": elk, "already": already,
                     "child_parents": sorted(str(core.value(x, RDFS.label) or x) for x in core.objects(c, RDFS.subClassOf)
                                             if isinstance(x, rdflib.URIRef))})
        print(f"[nest] {pid} {child} < {parent}: claude {verdict}, ELK {elk[:40]}", flush=True)
    Path(out).write_text(json.dumps({"made": "2026-10-04", "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    assert len(json.loads(Path(out).read_text())["rows"]) == len(PROPOSALS)
    print(f"[nest] written and read back: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
