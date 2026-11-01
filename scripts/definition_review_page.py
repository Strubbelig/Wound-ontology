#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WONT's definitions for the author to review: Claude's 275 drafts and the 24 classes without one.

    python -u scripts/definition_review_page.py    # data/review/definition_review_2026-10-31/{items.json, page.html}

The thesis says "Jede Klasse hat eine Bezeichnung und eine textuelle
Definition" and "275 der WONT-Definitionen hat Claude Opus 5.5 entworfen, und
der Autor hat sie durchgesehen". The curator (relayed by the thesis session,
2026-10-31: "schick der pipeline-sitzung die wont-aufgaben") reviews the 275
drafts, which carry IAO_0000119 "Drafted by Claude ...; to be reviewed by the
curator" (`claude_write_definitions.py`), and writes the 24 missing ones
himself.

One row per class, with what a reader needs to judge a definition: label, IRI,
named parents with their definitions, logical axioms (short Manchester form,
labels for names), synonyms, comments, direct subclasses, and the draft. For
the 21 classes Claude held back on 2026-10-30, its reason is shown; the other 3
have only a logical definition and were never sent. Rows are grouped by their
first parent, so siblings are read side by side.

The page stores each answer with its question (rule 47): the draft text shown,
the class's IRI and label, the choice (accept / own version) and the author's
text. The row id is the WONT id, stable across rebuilds (rule 72). Nothing
changes in WONT until the answers are read back and written into a new file.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "data" / "review" / "definition_review_2026-10-31"
TEMPLATE = ROOT / "scripts" / "definition_review_page.html"
HELD = ROOT / "data" / "llm_runs" / "claude_definitions_2026-10-30" / "result.json"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
OBO = "http://purl.obolibrary.org/obo/"
DRAFTS, MISSING = 275, 24   # what the thesis states; anything else stops the build


def names_index():
    """IRI -> (label, definition) over WONT, MILD, the modules, RO and BFO; first label wins, as `labels_index`."""
    import rdflib
    from rdflib import RDFS, URIRef
    from config.settings import BFO_OWL, GROUND_TRUTH_TTL, MILD_TTL, RO_OWL
    from wound_ontology.owl.extend import default_lexicon
    from wound_ontology.utils.rdf_io import parse_graph
    iao115 = URIRef(OBO + "IAO_0000115")
    lab, dfn = {}, {}
    for path in [GROUND_TRUTH_TTL, MILD_TTL, *default_lexicon(), RO_OWL, BFO_OWL]:
        p = Path(path)
        g = parse_graph(p, context="definitions") if p.suffix != ".ttl" and "ground_truth" not in p.name \
            else rdflib.Graph().parse(str(p), format="turtle")
        for s, o in g.subject_objects(RDFS.label):
            lab.setdefault(str(s), str(o))
        for s, o in g.subject_objects(iao115):
            dfn.setdefault(str(s), str(o))
    return lab, dfn


def main() -> int:
    import rdflib
    from rdflib import OWL, RDF, RDFS, URIRef
    from config.settings import GROUND_TRUTH_TTL
    from claude_write_definitions import manchester
    g = rdflib.Graph().parse(str(GROUND_TRUTH_TTL), format="turtle")
    lab, dfn = names_index()
    iao115, iao116, iao118, iao119 = (URIRef(OBO + f"IAO_000011{i}") for i in (5, 6, 8, 9))
    held = {h["iri"]: h["why"].removeprefix("cannot: ") for h in json.loads(HELD.read_text(encoding="utf-8"))["held"]}

    children = defaultdict(list)
    for c, p in g.subject_objects(RDFS.subClassOf):
        if isinstance(p, URIRef) and str(c).startswith(W):
            children[p].append(lab.get(str(c), str(c)))
    own = sorted((c for c in g.subjects(RDF.type, OWL.Class) if str(c).startswith(W)), key=str)
    items, tally = [], Counter()
    for c in own:
        defs = [str(o) for o in g.objects(c, iao115)]
        draft = bool(list(g.objects(c, iao119)))
        if len(defs) > 1:
            raise RuntimeError(f"{c}: {len(defs)} definitions")
        if defs and not draft:
            tally["the author's own definition: not asked"] += 1
            continue
        if draft and not defs:
            raise RuntimeError(f"{c}: a draft marker without a definition")
        parents = sorted((p for p in g.objects(c, RDFS.subClassOf) if isinstance(p, URIRef)),
                         key=lambda p: (not str(p).startswith(W), lab.get(str(p), str(p)).lower()))
        local = str(c).rsplit("/", 1)[-1]
        items.append({
            "id": local, "iri": str(c), "label": lab.get(str(c), local),
            "kind": "draft" if draft else "missing",
            "draft": defs[0] if defs else "",
            "parents": [{"label": lab.get(str(p), str(p).rsplit("/", 1)[-1]), "iri": str(p),
                         "def": dfn.get(str(p), "")} for p in parents],
            "axioms": [f"SubClassOf {manchester(g, o, lab)}" for o in g.objects(c, RDFS.subClassOf)
                       if isinstance(o, rdflib.BNode)]
                      + [f"EquivalentTo {manchester(g, o, lab)}" for o in g.objects(c, OWL.equivalentClass)],
            "synonyms": sorted(str(o) for o in g.objects(c, iao118)),
            "comments": [str(o) for p_ in (RDFS.comment, iao116) for o in g.objects(c, p_)],
            "children": sorted(children.get(c, []), key=str.lower),
            "held": held.get(str(c), ""),
        })
        tally[items[-1]["kind"]] += 1
    if tally["draft"] != DRAFTS or tally["missing"] != MISSING:
        raise RuntimeError(f"{dict(tally)}: expected {DRAFTS} drafts and {MISSING} without a definition")
    unheld = [x["label"] for x in items if x["kind"] == "missing" and not x["held"]]
    if any(x["parents"] for x in items if x["kind"] == "missing" and not x["held"]):
        raise RuntimeError(f"without a definition, not held and with a named parent: {unheld}")
    gone = set(held) - {x["iri"] for x in items if x["kind"] == "missing"}
    if gone:
        raise RuntimeError(f"held on 2026-10-30 but no longer without a definition: {sorted(gone)}")
    for x in items:
        x["group"] = x["parents"][0]["label"] if x["parents"] else ""

    OUT.mkdir(parents=True, exist_ok=True)
    data = {"made": datetime.now().isoformat(timespec="minutes"), "wont": GROUND_TRUTH_TTL.name,
            "tally": dict(tally), "items": items}
    (OUT / "items.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*ITEMS*/null", json.dumps(items, ensure_ascii=False))
    (OUT / "page.html").write_text(page, encoding="utf-8")
    print(f"[definition-page] {GROUND_TRUTH_TTL.name}: {dict(tally)}; {len(unheld)} without a definition "
          f"and only a logical one: {unheld}")
    print(f"[definition-page] {len(items)} rows in {len({x['group'] for x in items})} groups -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
