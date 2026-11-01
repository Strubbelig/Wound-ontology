"""WONT imported together with OFL, the flap ontology: does it load, is it coherent? (2026-10-30)

The curator: "übrigens haben wir bisher nie den import von ofl in wont
getestet. müssen wir auf jeden fall machen". WONT is meant to fit OFL (thesis,
aim 3); nobody had loaded the two together.

A test ontology imports WONT (with MILD, the whole RO and BFO) and OFL 2.0.0
(`Flap ontology/OFL Versionen/ofl_2.0.0.owl`, which imports the whole FMA
2020-04-13, OBI, PATO and RO). Every import resolves to a local file through a
catalog made for the test: WONT's own catalog plus OFL and its imports (the
local OBI, PATO and RO are other releases than OFL names; said in the report).
ROBOT merges the import closure, ELK reasons over it; the report lists:

* whether the closure is consistent, and every unsatisfiable class;
* OFL and WONT classes with the same label but different IRIs (candidates for
  one class, or for a clash of meaning);
* the sizes of what was merged.

Nothing of WONT, MILD or OFL is changed. Output: `output/wont_with_ofl_<date>/`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

ONTO = ROOT.parent
OFL = ONTO / "Flap ontology" / "OFL Versionen" / "ofl_2.0.0.owl"
IMPORTS = ONTO / "Import ontologies"
#: `--tag NAME` writes to `output/wont_with_ofl_<date>_NAME/`, so a second run on one day keeps the first
OUT = ROOT / "output" / (f"wont_with_ofl_{datetime.now():%Y-%m-%d}"
                         + (f"_{sys.argv[sys.argv.index('--tag') + 1]}" if "--tag" in sys.argv else ""))
ROBOT = ["java", "-Xmx8g", "-jar", "/usr/local/bin/robot.jar"]
OFL_IMPORTS = {   # what OFL 2.0.0 imports -> the file at hand
    # the OBO release OFL names (`fma_obo.owl`), not `fma.owl`, which is the
    # BioPortal FMA 5.0.0 with other IRIs (purl.org/sig/ont/fma/): loaded by
    # mistake on the first try, its 69,100 classes were all unsatisfiable
    "http://purl.obolibrary.org/obo/fma/releases/2020-04-13/fma.owl": IMPORTS / "fma_obo.owl",
    "http://purl.obolibrary.org/obo/obi/2025-03-06/obi.owl": IMPORTS / "obi.owl",
    "http://purl.obolibrary.org/obo/pato/releases/2025-05-14/pato.owl": IMPORTS / "pato.owl",
}
# OFL imports RO 2025-03-05, MILD RO 2025-12-17; there is one RO file at hand,
# and OWLAPI refuses to load one ontology under two version IRIs ("Ontology
# already exists", first try 2026-10-31). Combined, the two use one RO: the
# test loads a copy of OFL whose RO import names MILD's release. OFL itself is
# not changed.
OFL_RO, MILD_RO = ("http://purl.obolibrary.org/obo/ro/releases/2025-03-05/ro.owl",
                   "http://purl.obolibrary.org/obo/ro/releases/2025-12-17/ro.owl")
OFL_IRI = "https://purl.bioontology.org/ontology/OFL"
WONT_IRI = "https://bioportal.bioontology.org/ontologies/WONT"


def file_uri(p: Path) -> str:
    return p.resolve().as_uri()


def main(argv) -> int:
    from config.settings import GROUND_TRUTH_TTL
    OUT.mkdir(parents=True, exist_ok=True)
    # the catalog: WONT's own entries (MILD, its modules, RO, BFO) plus OFL and its imports
    base = (ROOT / "output" / "owl" / "catalog-v001.xml").read_text(encoding="utf-8")
    entries = re.findall(r'<uri [^>]*/>', base)
    names = {re.search(r'name="([^"]*)"', e).group(1) for e in entries}
    ofl_text = OFL.read_text(encoding="utf-8")
    if ofl_text.count(OFL_RO) != 1:
        raise RuntimeError(f"OFL does not import {OFL_RO} once")
    ofl_copy = OUT / "ofl_2.0.0_one_ro.owl"
    ofl_copy.write_text(ofl_text.replace(OFL_RO, MILD_RO), encoding="utf-8")
    extra = {OFL_IRI: ofl_copy, WONT_IRI: Path(GROUND_TRUTH_TTL), **OFL_IMPORTS}
    for iri, path in extra.items():
        if not path.exists():
            raise RuntimeError(f"{iri}: {path} does not exist")
        if iri not in names:
            entries.append(f'<uri name="{iri}" uri="{file_uri(path)}"/>')
    catalog = OUT / "catalog-v001.xml"
    catalog.write_text('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
                       '<catalog prefer="public" xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n    '
                       + "\n    ".join(entries) + "\n</catalog>\n", encoding="utf-8")
    test = OUT / "wont_with_ofl.ttl"
    test.write_text(f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://bioportal.bioontology.org/ontologies/WONT/test/wont_with_ofl> a owl:Ontology ;
    owl:imports <{WONT_IRI}> , <{OFL_IRI}> .
""", encoding="utf-8")
    merged, reasoned, log = OUT / "merged.owl", OUT / "reasoned_elk.owl", OUT / "elk.log"
    print(f"[ofl] merging WONT ({Path(GROUND_TRUTH_TTL).name}) + OFL ({OFL.name}) with their import closures ...", flush=True)
    r = subprocess.run([*ROBOT, "--catalog", str(catalog), "merge", "--input", str(test),
                        "--collapse-import-closure", "true", "--output", str(merged)], capture_output=True, text=True)
    (OUT / "merge.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode:
        print(f"[ofl] *** the merge failed: {(r.stderr + r.stdout)[-1500:]} ***")
        return 1
    print(f"[ofl] merged: {merged.stat().st_size / 1e6:.0f} MB; reasoning with ELK ...", flush=True)
    r = subprocess.run([*ROBOT, "reason", "--reasoner", "ELK", "--input", str(merged),
                        "--equivalent-classes-allowed", "all", "--output", str(reasoned)],
                       capture_output=True, text=True)
    log.write_text(r.stdout + r.stderr, encoding="utf-8")
    text = r.stdout + r.stderr
    unsat = sorted(set(re.findall(r"unsatisfiable: (\S+)", text)))
    inconsistent = "inconsistent" in text.lower() and "unsatisfiable" not in text.lower()
    print(f"[ofl] ELK exit {r.returncode}; inconsistent: {inconsistent}; unsatisfiable classes: {len(unsat)}")
    for u in unsat[:60]:
        print(f"[ofl]     {u}")
    # labels shared by an OFL class and a WONT class with different IRIs
    import rdflib
    from rdflib import OWL, RDF, RDFS
    w = rdflib.Graph().parse(str(GROUND_TRUTH_TTL), format="turtle")
    o = rdflib.Graph().parse(str(OFL))
    def labels(g, ns):
        out = {}
        for s, l in g.subject_objects(RDFS.label):
            if str(s).startswith(ns) and (s, RDF.type, OWL.Class) in g:
                out.setdefault(str(l).strip().lower(), set()).add(str(s))
        return out
    lw, lo = labels(w, WONT_IRI + "/"), labels(o, OFL_IRI + "/")
    same = sorted((l, sorted(lo[l]), sorted(lw[l])) for l in set(lw) & set(lo))
    print(f"[ofl] OFL classes {sum(map(len, lo.values()))}, WONT classes {sum(map(len, lw.values()))}; "
          f"labels both carry (different IRIs): {len(same)}")
    for l, a, b in same[:40]:
        print(f"[ofl]     {l}: OFL {a} | WONT {b}")
    json.dump({"wont": str(GROUND_TRUTH_TTL), "ofl": str(OFL), "elk_exit": r.returncode,
               "inconsistent": inconsistent, "unsatisfiable": unsat,
               "same_label": [{"label": l, "ofl": a, "wont": b} for l, a, b in same],
               "note": "local OBI, PATO and RO are other releases than OFL 2.0.0 names; OFL's RO import "
                       "(2025-03-05) was pointed at MILD's (2025-12-17) in a test copy, one RO for both"},
              open(OUT / "report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[ofl] report: {(OUT / 'report.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
