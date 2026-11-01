"""Four risks and susceptibilities are tendencies; complete wound healing is a process boundary (2026-10-30).

Asked about six `has tendency` relations the typing check refused because
their value was typed disposition, though rule 68 had made them tendencies,
the curator: "dann mach sie wieder zu tendencies". The four values are typed
tendency in most of their abstracts (Pressure ulcer risk in 48 of 51) and came
out disposition because the merge of conflicting typings follows MILD, which
states tendency a subclass of disposition (MILD_120005 rdfs:subClassOf
BFO_0000016) while its own comment calls it a sibling of disposition under
realizable entity -- put to the curator, MILD is not edited here. Each of the
four gets the author's category tendency.

Asked whether `Complete wound healing` -- a process by his ruling of
2026-09-29, used as the end of wound healing -- is, like the recurrences, a
point in time: "grenze bitte". It goes under BFO `process boundary`, placed and
typed; its process category and its placement under GO `wound healing` (a
process) go, as with the recurrences (BFO keeps process and process boundary
apart). Its relations are left to the typing check and the reading, as any
other: no axiom is added here.

All as the author's judgements, each with his words as the reason.
"""
from __future__ import annotations

import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))

from apply_recurrence_events_2026_10_30 import BOUNDARY, is_process_class  # noqa: E402

WHEN = None                      # now
TENDENCIES = ["Bacterial susceptibility", "Susceptibility to infection", "Pressure ulcer risk", "Recurrence risk"]
END_OF_HEALING = "Complete wound healing"
TENDENCY = ("a risk or susceptibility is a tendency, not a disposition (rule 68; curator 2026-10-30, on six "
            "has tendency relations refused because their value was typed disposition: \"dann mach sie wieder "
            "zu tendencies\")")
END = ("complete wound healing is the end of the wound healing process, a process boundary, not a process "
       "(curator 2026-10-30, asked whether it is, like a recurrence, a point in time: \"grenze bitte\")")


def main(argv) -> int:
    import rdflib
    from config.settings import GROUND_TRUTH_TTL
    from wound_ontology.mappers.judgements import current
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.owl.extend import default_lexicon
    from wound_ontology.utils.rdf_io import parse_graph
    graphs = [rdflib.Graph().parse(str(GROUND_TRUTH_TTL), format="turtle")]
    graphs += [parse_graph(Path(p), context="tendencies and boundary") for p in default_lexicon()]
    gt = Orchestrator().term_mapper._term_mapping
    named = TENDENCIES + [END_OF_HEALING]
    missing = [t for t in named if t not in gt.records or gt.concept(gt.resolve(t)) != t]
    if missing:
        raise RuntimeError(f"terms not found as concepts: {missing}")
    tally = Counter()
    for t in TENDENCIES:
        standing = gt.categories().get(t)
        if standing and standing["verdict"] == "tendency" and standing["by"] == "author":
            continue
        if standing:
            gt._put(t, "is_a", gt._j("no", "author", TENDENCY, WHEN), standing["verdict"])
            tally[f"a decided category {standing['verdict']}: no"] += 1
        gt._put(t, "is_a", gt._j("yes", "author", TENDENCY, WHEN), "tendency")
        tally["category tendency: yes"] += 1
    t = END_OF_HEALING
    for k, js in list((gt.records[t].get("is_a") or {}).items()):
        cj = current(js)
        iri = next((j["iri"] for j in reversed(js) if j.get("iri")), None)
        if not cj or cj["verdict"] != "yes" or k == "process boundary":
            continue
        if k.lower() == "process" or (iri and is_process_class(iri, graphs)):
            gt._put(t, "is_a", gt._j("no", "author", END, WHEN, iri), k)
            tally[f"{t}: is_a {k}: no"] += 1
        else:
            raise RuntimeError(f"{t}: is_a {k} ({iri}) stands yes and is no process; nothing decides it")
    gt._put(t, "is_a", gt._j("yes", "author", END, WHEN, BOUNDARY), "process boundary")
    gt._put(t, "is_a", gt._j("yes", "author", END, WHEN), "process boundary")
    tally[f"{t}: under process boundary, typed process boundary"] += 1
    print(f"[tendencies-boundary] {dict(tally)}")
    gt._dirty()
    cats = gt.categories()
    bad = [x for x in TENDENCIES if (cats.get(x) or {}).get("verdict") != "tendency"]
    if (cats.get(t) or {}).get("verdict") != "process boundary":
        bad.append(t)
    placed = sorted(c for x, c in gt.placements() if x == t)
    if bad or placed != ["process boundary"]:
        raise RuntimeError(f"categories not as decided: {bad}; {t} placed under {placed}")
    print(f"[tendencies-boundary] categories: " + ", ".join(f"{x} = {cats[x]['verdict']}" for x in named)
          + f"; {t} placed under {placed}")
    if "--write" not in argv:
        print("[tendencies-boundary] dry run; --write saves")
        return 0
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_tendencies_boundary_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[tendencies-boundary] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
