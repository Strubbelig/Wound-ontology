"""MILD without a required threshold crossing and without causality (2026-10-30).

The curator, reviewing the thesis: "causally downstream wenn ich kausalität
immer abgelehnt habe finde ich schwierig. und einen threshold überschreitung
zu verlangen finde ich geht auch nicht. es mag solche krankheiten geben die
dadurch epistemisch definiert sind, aber es sind bei weitem nicht alle" -- and
"gib MILD änderungen an die andre session ab". Asked whether pathological
disorder should give way to material disease entity: "pathological
disorder=material disease entity soll bitte so bleiben, das soll nur in der
thesis einheitlich sein"; so only these go:

* `disorder development process` (MILD_120021): its `has as process boundary
  at end` some `threshold crossing event`;
* `course of the disease process` (MILD_120028): its `immediately causally
  downstream of` some `disorder development process` and its `has as process
  boundary at start` some `threshold crossing event`;
* each one's definition says what is left; `immediately causally downstream
  of` (RO_0002405), used nowhere else in MILD, is no longer declared.
  `threshold crossing event` (MILD_120031) stays, no longer required.

`mild_2026-10-30b.ttl` is `mild_2026-10-30.ttl` edited as text, so the file
keeps the form the curator's editor wrote; the change is then checked on the
graphs: the new file must be the old one with exactly these triples taken out
and the two definitions replaced, nothing else.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "Disease ontologies" / "mild_2026-10-30.ttl"
NEW = ROOT.parent / "Disease ontologies" / "mild_2026-10-30b.ttl"
M = "https://bioportal.bioontology.org/ontologies/MILD/"
OBO = "http://purl.obolibrary.org/obo/"
DEV_DEF = ("A process that has as output a pathological disorder and that has as its end boundary a threshold "
           "crossing event.")
DEV_NEW = "A process that has as output a pathological disorder."
COURSE_DEF = ("A process that has as participant a material disease entity, that is immediately causally "
              "downstream of a disorder development process, and that has as its start boundary a threshold "
              "crossing event.")
COURSE_NEW = "A process that has as participant a material disease entity."

EDITS = [
    # disorder development process: the end boundary goes
    ("""                               owl:someValuesFrom :MILD_120022
                             ] ,
                             [ rdf:type owl:Restriction ;
                               owl:onProperty :MILD_120085 ;
                               owl:someValuesFrom :MILD_120031
                             ] ;
             <http://purl.obolibrary.org/obo/IAO_0000115> \"""" + DEV_DEF + '"@en ;',
     """                               owl:someValuesFrom :MILD_120022
                             ] ;
             <http://purl.obolibrary.org/obo/IAO_0000115> \"""" + DEV_NEW + '"@en ;'),
    # course of the disease process: causality and the start boundary go
    ("""                               owl:someValuesFrom :MILD_120020
                             ] ,
                             [ rdf:type owl:Restriction ;
                               owl:onProperty <http://purl.obolibrary.org/obo/RO_0002405> ;
                               owl:someValuesFrom :MILD_120021
                             ] ,
                             [ rdf:type owl:Restriction ;
                               owl:onProperty :MILD_120084 ;
                               owl:someValuesFrom :MILD_120031
                             ] ;
             <http://purl.obolibrary.org/obo/IAO_0000115> \"""" + COURSE_DEF + '"@en ;',
     """                               owl:someValuesFrom :MILD_120020
                             ] ;
             <http://purl.obolibrary.org/obo/IAO_0000115> \"""" + COURSE_NEW + '"@en ;'),
    # RO_0002405 is used nowhere else
    ("""###  http://purl.obolibrary.org/obo/RO_0002405
<http://purl.obolibrary.org/obo/RO_0002405> rdf:type owl:ObjectProperty .


""", ""),
]


def expected(old):
    """The old graph with exactly the decided triples taken out and the definitions replaced."""
    import rdflib
    from rdflib import OWL, RDF, RDFS, Literal, URIRef
    g = rdflib.Graph()
    for t in old:
        g.add(t)
    iao = URIRef(OBO + "IAO_0000115")

    def drop(cls, prop, filler):
        hits = [b for b in g.objects(URIRef(M + cls), RDFS.subClassOf)
                if (b, OWL.onProperty, URIRef(prop)) in g and (b, OWL.someValuesFrom, URIRef(filler)) in g]
        if len(hits) != 1:
            raise RuntimeError(f"{cls}: {len(hits)} restriction(s) on {prop} some {filler}, expected 1")
        b = hits[0]
        g.remove((URIRef(M + cls), RDFS.subClassOf, b))
        g.remove((b, None, None))
    drop("MILD_120021", M + "MILD_120085", M + "MILD_120031")
    drop("MILD_120028", OBO + "RO_0002405", M + "MILD_120021")
    drop("MILD_120028", M + "MILD_120084", M + "MILD_120031")
    for cls, a, b in (("MILD_120021", DEV_DEF, DEV_NEW), ("MILD_120028", COURSE_DEF, COURSE_NEW)):
        g.remove((URIRef(M + cls), iao, Literal(a, lang="en")))
        g.add((URIRef(M + cls), iao, Literal(b, lang="en")))
    if any(True for _ in g.triples((None, None, URIRef(OBO + "RO_0002405")))) \
            or any(True for _ in g.triples((None, OWL.onProperty, URIRef(OBO + "RO_0002405")))):
        raise RuntimeError("RO_0002405 is still used in MILD; its declaration stays")
    g.remove((URIRef(OBO + "RO_0002405"), RDF.type, OWL.ObjectProperty))
    return g


def main(argv) -> int:
    import rdflib
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    text = OLD.read_text(encoding="utf-8")
    for a, b in EDITS:
        if text.count(a) != 1:
            raise RuntimeError(f"edit found {text.count(a)} time(s), expected once: {a[:120]!r}")
        text = text.replace(a, b)
    old = rdflib.Graph().parse(OLD, format="turtle")
    new = rdflib.Graph().parse(data=text, format="turtle")
    want = expected(old)
    if not isomorphic(new, want):
        _, only_new, only_want = graph_diff(to_isomorphic(new), to_isomorphic(want))
        raise RuntimeError(f"the edited MILD is not the decided change: {len(only_new)} triple(s) only in it, "
                           f"{len(only_want)} only in the expected graph: {list(only_new)[:5]} / {list(only_want)[:5]}")
    print(f"[mild] {OLD.name}: {len(old):,} triples -> {len(new):,} ({len(old) - len(new)} fewer); "
          f"the edit is exactly the decided change (graphs compared)")
    left = [str(s) for s, p, o in new.triples((None, None, rdflib.URIRef(M + "MILD_120031")))]
    print(f"[mild] threshold crossing event still named by: {left or 'nothing (a class of its own, not required)'}")
    if "--write" not in argv:
        print(f"[mild] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    NEW.write_text(text, encoding="utf-8")
    print(f"[mild] written {NEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
