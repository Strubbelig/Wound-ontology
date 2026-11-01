"""`disease perpetuation process` out of MILD; recurrences are events (2026-10-30).

The curator: "disease perpetuation process ist eine ziemlich miese klasse.
lösch sie einfach aus WONT" -- the class is MILD's (MILD_120035), so
`mild_2026-10-30.ttl` is `mild_2026-10-29.ttl` without its twelve triples.
And: "diese recurrences sind der zeitpunkt, an dem der krankheitsprozess
startet einer krankheit, deren krankheitsprozess schon mal bestanden hat.
demnach ist die recurrence ein event und kein prozess". Asked how, he chose:

* the 28 recurrences: under BFO `process boundary` (placed and typed), with
  `is process boundary at start of` some `course of the disease process`
  (MILD_120083, MILD_120028); every placement or category of theirs that is
  a process goes (BFO keeps process and process boundary apart);
* the other 25 placed there are processes (persistence, progression, an
  infection that recurs): they lose the parent and go to the candidates.

Every placement under MILD_120035 gets the author's `no`. All as the author's
judgements, each with his words as the reason.
"""
from __future__ import annotations

import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

OBO, MILD = "http://purl.obolibrary.org/obo/", "https://bioportal.bioontology.org/ontologies/MILD/"
DELETED = MILD + "MILD_120035"
BOUNDARY = OBO + "BFO_0000035"
COURSE = MILD + "MILD_120028"
WHEN = None                      # now
GONE = ("disease perpetuation process deleted from MILD (curator 2026-10-30: \"disease perpetuation process "
        "ist eine ziemlich miese klasse. lösch sie einfach\")")
EVENT = ("a recurrence is an event, not a process (curator 2026-10-30: \"diese recurrences sind der zeitpunkt, "
         "an dem der krankheitsprozess startet einer krankheit, deren krankheitsprozess schon mal bestanden "
         "hat. demnach ist die recurrence ein event und kein prozess\")")

EVENTS = [
    "Bioburden recurrence", "Bone infection recurrence", "Diabetic foot ulcer recurrence", "Hematoma recurrence",
    "Hernia recurrence", "Infection relapse", "Lesion recurrence", "Long-term recurrence", "Lymphocele recurrence",
    "Microbial recurrence", "Osteomyelitis recurrence", "Postoperative recurrence", "Pressure ulcer recurrence",
    "Re-wound", "Recur", "Recurred", "Recurrence of cellulitis", "Recurrence of chronic extremity-threatening ischemia",
    "Recurrence of incisional hernia", "Recurrence of infection", "Recurrence of sinus", "Relapse", "Relapsed",
    "Reccurrence", "Tumor recurrence", "Re-infection with osteomyelitis", "Venous lower extremity wound recurrence",
    "Venous lower extremity wounds reoccurrence"]


def is_process_class(iri: str, graphs) -> bool:
    """`iri` is BFO process or below it in WONT, MILD or the modules."""
    import rdflib
    from rdflib import RDFS
    seen, todo = set(), [rdflib.URIRef(iri)]
    while todo:
        c = todo.pop()
        if str(c) == OBO + "BFO_0000015":
            return True
        if c in seen:
            continue
        seen.add(c)
        for g in graphs:
            todo += [p for p in g.objects(c, RDFS.subClassOf) if isinstance(p, rdflib.URIRef)]
    return False


def main(argv) -> int:
    import rdflib
    from config.settings import GROUND_TRUTH_TTL
    from wound_ontology.mappers.judgements import current
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.owl.extend import default_lexicon
    from wound_ontology.utils.rdf_io import parse_graph
    graphs = [rdflib.Graph().parse(str(GROUND_TRUTH_TTL), format="turtle")]
    graphs += [parse_graph(Path(p), context="recurrences") for p in default_lexicon()]
    gt = Orchestrator().term_mapper._term_mapping
    missing = [t for t in EVENTS if t not in gt.records or gt.concept(gt.resolve(t)) != t]
    if missing:
        raise RuntimeError(f"recurrences not found as concepts: {missing}")
    tally, placed_out = Counter(), []
    for t, rec in gt.records.items():
        for k, js in (rec.get("is_a") or {}).items():
            if any(j.get("iri") == DELETED for j in js) and (current(js) or {}).get("verdict") != "no":
                gt._put(t, "is_a", gt._j("no", "author", GONE, WHEN, DELETED), k)
                tally["placement under the deleted class: no"] += 1
                placed_out.append(t)
    for t in EVENTS:
        rec = gt.records[t]
        for k, js in list((rec.get("is_a") or {}).items()):
            cj = current(js)
            iri = next((j["iri"] for j in reversed(js) if j.get("iri")), None)
            if not cj or cj["verdict"] != "yes" or iri == DELETED:
                continue
            if k.lower() == "process" or (iri and is_process_class(iri, graphs)):
                gt._put(t, "is_a", gt._j("no", "author", EVENT, WHEN, iri), k)
                tally["a process placement or category of a recurrence: no"] += 1
        gt._put(t, "is_a", gt._j("yes", "author", EVENT, WHEN, BOUNDARY), "process boundary")
        gt._put(t, "is_a", gt._j("yes", "author", EVENT, WHEN), "process boundary")
        gt._put(t, "relations", gt._j("yes", "author", EVENT, WHEN, COURSE),
                "is_process_boundary_at_start_of: course of the disease process")
        tally["recurrence: under process boundary, starts a course of the disease process"] += 1
    # the term itself, should the abstracts name it: no class of its own either
    from wound_ontology.utils.string_utils import normalize_term as N
    for t in [t for t in gt.records if N(t) == N("disease perpetuation process")]:
        c = gt.concept(gt.resolve(t))
        if gt.gate_verdict(c)[0] != "out":
            gt.gate(c, curator={"verdict": "out", "by": "author", "when": None, "reason": GONE})
            tally["the term disease perpetuation process: out"] += 1
    others = sorted(set(placed_out) - set(EVENTS))
    print(f"[recurrences] {dict(tally)}")
    print(f"[recurrences] {len(others)} other term(s) lose the parent: {others}")
    gt._dirty()
    bad = [t for t in EVENTS if (gt.categories().get(t) or {}).get("verdict") != "process boundary"]
    if bad:
        raise RuntimeError(f"recurrences whose category is not process boundary: {bad}")
    if "--write" not in argv:
        print("[recurrences] dry run; --write saves")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_recurrences_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[recurrences] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
