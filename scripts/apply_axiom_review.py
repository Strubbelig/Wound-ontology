"""Turn the curator's review of relations on existing WONT classes into axioms (rule 69).

    python -u scripts/apply_axiom_review.py DB_DIR [--write]

DB_DIR holds the review page's database as ArtifactData saved it
(`decision/<id>.json`, `lift/<id>.json`; https://claude.ai/artifact/BRc7QuBRBmXJV4tXcCun8A).
Writes `data/review/curator_axioms_2026-10-03.json`, which
`scripts/build_wont_core.py` reads: every entry is one `subject SubClassOf
property some filler` in the WONT addition (never in ground_truth_final.owl).

* A cluster asserted on Wound gives one axiom on Wound per ticked quality: the
  cluster's own quality when its term is ticked (area, size, depth, length,
  volume, age), otherwise the ticked term's class (the bacterial cluster: the
  curator kept `degree of microbial burden`, WONT's class, and unticked
  `bacterial load`). Per-class rows inside a cluster are covered by
  inheritance and give no axiom.
* A row marked add gives its axiom. Four subjects resolved to WONT plan
  specifications, and the curator's notes say the process is meant ("the
  process of the specified plan"): those axioms go on the process class.
* "Wound healing and wound healing process are the same" (curator): recorded in
  the term dict, and the two identical rows give one axiom.
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

ROWS = ROOT / "data" / "review" / "withheld_relations_2026-10-03.json"
OUT = ROOT / "data" / "review" / "curator_axioms_2026-10-03.json"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
O = "http://purl.obolibrary.org/obo/"
WOUND = W + "WONT_0000380"
BY = "curator, axiom review page 2026-10-03"

# plan specification -> the process that realizes it (curator's notes)
PROCESS_FOR_PLAN = {
    W + "WONT_0000094": (W + "WONT_0007699", "Wound Dressing Change"),
    W + "WONT_0000213": (W + "WONT_0001008", "Application Of Negative Pressure Wound Therapy"),
    W + "WONT_0000581": (W + "WONT_0000299", "Surgical wound debridement process"),
    W + "WONT_0000016": (W + "WONT_0000589", "Antibiotic administration process"),
}
# fillers the probe left unresolved (imported) or minted under a probe id
IMPORTED = {"foot": O + "FMA_9664", "pathogen": O + "IDO_0000528"}
SAME_AS = [("wound healing process", "wound healing"), ("wound age", "age")]


def main(argv: list[str]) -> int:
    # 2026-10-30: the axioms it wrote are the author's judgements in the term
    # dict now (scripts/move_relation_decisions_2026_10_30.py); a file beside it
    # would be a second record of his word (rule 51)
    raise SystemExit("[axiom-review] retired 2026-10-30: the curator's axioms live in the term dict; "
                     "write a new review's decisions there as the author's judgements")
    from wound_ontology.owl.extend import RELATION_IRIS
    db = Path(argv[1])
    rows = {r["id"]: r for r in json.loads(ROWS.read_text(encoding="utf-8"))["rows"]}
    clusters = {c["id"]: c for c in json.loads(ROWS.read_text(encoding="utf-8"))["clusters"]}

    def docs(coll):
        out = {}
        for f in sorted((db / coll).glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            out[f.stem] = d.get("data", d)
        return out

    lift, dec = docs("lift"), docs("decision")
    prop = {r["predicate"]: RELATION_IRIS[r["predicate"].replace(" ", "_")] for r in rows.values()}
    axioms, seen, undecided, left = [], set(), [], []

    def add(subject_iri, subject_label, predicate, filler_iri, filler_label, source, note=""):
        key = (subject_iri, predicate, filler_iri or filler_label.lower())
        if key in seen:
            return
        seen.add(key)
        axioms.append({"subject_iri": subject_iri, "subject_label": subject_label, "predicate": predicate,
                       "property_iri": prop[predicate], "filler_iri": filler_iri, "filler_label": filler_label,
                       "from": source, "note": note, "by": BY})

    for cid, d in sorted(lift.items()):
        c = clusters[cid]
        if d.get("v") != "wound":
            left.append(cid)
            continue
        ticked = [t for t, on in d.get("members", {}).items() if on]
        own_term_ticked = any(t.lower() == c["canonical"].lower() for t in ticked) or c["canonical"] == "age"
        if own_term_ticked:
            add(WOUND, "Wound", "has quality", c["iri"], c["canonical"], f"cluster {cid}", d.get("note", ""))
        else:
            for t in ticked:
                r = next(r for r in rows.values() if r.get("cluster") == cid and r["value"].lower() == t.lower())
                add(WOUND, "Wound", "has quality", r["value_iri"], r["value_label"], f"cluster {cid}: ticked {t}",
                    d.get("note", ""))

    for rid, r in sorted(rows.items()):
        if r["section"] == "cluster":
            continue
        d = dec.get(rid, {})
        if d.get("v") == "leave":
            left.append(rid)
            continue
        if d.get("v") != "add":
            undecided.append((rid, r["subject"], r["predicate"], r["value"], d.get("note", "")))
            continue
        s_iri, s_label = r["subject_iri"], r["subject_label"]
        if s_iri in PROCESS_FOR_PLAN:
            s_iri, s_label = PROCESS_FOR_PLAN[s_iri]
        f_iri = IMPORTED.get(r["value"].lower()) or (None if r["value_is_new"] else r["value_iri"]) or None
        add(s_iri, s_label, r["predicate"], f_iri, r["value_label"] if not r["value_is_new"] else r["value"],
            rid, d.get("note", ""))

    print(f"[review] {len(axioms)} curator axiom(s); {len(left)} left out; {len(undecided)} undecided")
    for a in axioms:
        print(f"[review]   {a['subject_label']} | {a['predicate']} | {a['filler_label']}  "
              f"({a['filler_iri'].rsplit('/', 1)[-1] if a['filler_iri'] else 'by label, from the extension'})  [{a['from']}]")
    for u in undecided:
        print(f"[review]   UNDECIDED {u}")
    if "--write" not in argv:
        print("[review] dry run; --write to record")
        return 0

    OUT.write_text(json.dumps({"by": BY, "axioms": axioms, "undecided": undecided, "left_out": left},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(OUT.read_text(encoding="utf-8"))
    assert len(back["axioms"]) == len(axioms)
    print(f"[review] written and read back: {OUT.relative_to(ROOT)}")

    # the curator's identities, in the term dict
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.orchestrator import Orchestrator
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    gt = p.term_mapper._term_mapping
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_axiom_review_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[review] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    for term, canon in SAME_AS:
        t = gt.resolve(term)
        rec = gt.record(t)
        rec.update({"to": canon, "confidence": 1.0, "method": "curator"})
        rec.pop("retired", None)
        gt.judge(t, canon, curator={"verdict": "same_class", "when": when, "by": BY,
                                    "reason": "curator: the same" if term.startswith("wound healing")
                                    else "ticked as the age of the wound (cluster q-age)"})
    gt._dirty(); gt.save()
    g2 = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES,
                      base_path=BASE_PATH).term_mapper._term_mapping
    lost = [(t, c) for t, c in SAME_AS if g2.data.get(g2.resolve(t)) != c]
    if lost:
        raise RuntimeError(f"[review] term-dict identities did not land: {lost}")
    print(f"[review] term dict written and read back: {SAME_AS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
