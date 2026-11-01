"""WONT and MILD say in their headers that they are reviewed at least once a year (2026-10-31).

The thesis: "WONT wird vom Autor entwickelt und wie MILD mindestens einmal
jährlich überprüft" and "MILD wird mindestens einmal jährlich überprüft". The
curator (relayed by the thesis session): "ja, jährliche überprüfung bestätige
ich". Neither header said so, and MILD has no form for it to follow, so each
header gets one rdfs:comment, beside MILD's model commitments:

* `ground_truth_final_2026-10-31d.owl` is `..._2026-10-31c.owl` plus WONT's;
* `mild_2026-10-31.ttl` is `mild_2026-10-30g.ttl` plus MILD's, put into the
  header's comment list as text, so the file keeps its Protégé layout.

Each graph difference is checked to be that one triple.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
WONT_OLD, WONT_NEW = GT / "ground_truth_final_2026-10-31c.owl", GT / "ground_truth_final_2026-10-31d.owl"
MILD_OLD, MILD_NEW = (ROOT.parent / "Disease ontologies" / "mild_2026-10-30g.ttl",
                      ROOT.parent / "Disease ontologies" / "mild_2026-10-31.ttl")
WONT_IRI, MILD_IRI = "https://bioportal.bioontology.org/ontologies/WONT", "https://bioportal.bioontology.org/ontologies/MILD"
WONT_SAYS = "WONT is developed by its author and, like MILD, reviewed at least once a year."
MILD_SAYS = "MILD is reviewed at least once a year."
# the end of MILD's last header comment (MODEL COMMITMENT 4 of 4), where the list closes
MILD_LIST_END = 'temporal extension which this ontology does not import, so \'over the same period\' appears in ' \
                'definitions and annotations but is not axiomatised."@en .'


def one_triple_more(old, new, triple, name):
    from rdflib.compare import graph_diff, to_isomorphic
    _, gone, came = graph_diff(to_isomorphic(old), to_isomorphic(new))
    if len(gone) or set(came) != {triple}:
        raise RuntimeError(f"{name}: {len(gone)} triples gone, {len(came)} come; expected the one comment")


def main(argv) -> int:
    import rdflib
    from rdflib import Literal, OWL, RDF, RDFS, URIRef
    from rdflib.compare import isomorphic
    write = "--write" in argv
    for p in (WONT_NEW, MILD_NEW):
        if write and p.exists():
            raise RuntimeError(f"{p} exists; not overwritten")

    # WONT: written by rdflib, as every WONT file since 2026-10-29
    old = rdflib.Graph().parse(WONT_OLD, format="turtle")
    onto, says = URIRef(WONT_IRI), Literal(WONT_SAYS, lang="en")
    if (onto, RDF.type, OWL.Ontology) not in old:
        raise RuntimeError(f"{WONT_OLD.name}: no ontology header")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    g.add((onto, RDFS.comment, says))
    one_triple_more(old, g, (onto, RDFS.comment, says), WONT_OLD.name)
    print(f"[yearly] {WONT_OLD.name}: {len(old):,} triples -> {len(g):,}; header comment {WONT_SAYS!r}")

    # MILD: text edit, the layout is the curator's
    text = MILD_OLD.read_text(encoding="utf-8")
    if text.count(MILD_LIST_END) != 1:
        raise RuntimeError(f"{MILD_OLD.name}: the end of the header's comment list found {text.count(MILD_LIST_END)} times")
    indent = " " * 66   # the column of the header's other comments
    new_text = text.replace(MILD_LIST_END, MILD_LIST_END[:-2] + f',\n{indent}"{MILD_SAYS}"@en .')
    m_old = rdflib.Graph().parse(data=text, format="turtle")
    m_new = rdflib.Graph().parse(data=new_text, format="turtle")
    one_triple_more(m_old, m_new, (URIRef(MILD_IRI), RDFS.comment, Literal(MILD_SAYS, lang="en")), MILD_OLD.name)
    print(f"[yearly] {MILD_OLD.name}: {len(m_old):,} triples -> {len(m_new):,}; header comment {MILD_SAYS!r}")

    if not write:
        print(f"[yearly] dry run; --write writes {WONT_NEW.name} and {MILD_NEW.name}")
        return 0
    g.serialize(WONT_NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(WONT_NEW, format="turtle"), g):
        raise RuntimeError(f"{WONT_NEW.name}: the written file is not the graph meant")
    MILD_NEW.write_text(new_text, encoding="utf-8")
    if not isomorphic(rdflib.Graph().parse(MILD_NEW, format="turtle"), m_new):
        raise RuntimeError(f"{MILD_NEW.name}: the written file is not the graph meant")
    print(f"[yearly] written {WONT_NEW.relative_to(ROOT)} and {MILD_NEW} (both read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
