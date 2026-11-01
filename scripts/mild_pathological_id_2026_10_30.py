"""The quality `pathological` gets an identifier in MILD's range and a definition (2026-10-30).

The thesis noted: "In mild.ttl trägt die Qualität noch die Kennung MILD_000600
außerhalb des Nummernbereichs und keine Definition." The curator: "ändere das".

* MILD_000600 becomes MILD_120102, the next number after the highest in use
  (MILD_120101; a deleted number, such as MILD_120035, is never given again).
  MILD is not released and nothing outside it names MILD_000600 (WONT, the
  term dict and the id registry do not; the generated extraction schema is
  made again), so the identifier is changed, not deprecated.
* Its definition says what the thesis says of pathologicity in MILD: it is
  asserted by medicine, never inferred, by no criteria, because it can
  depend on context.

`mild_2026-10-30d.ttl` is `mild_2026-10-30c.ttl` edited as text; the graphs
are compared: the new file must be the old one with the identifier replaced
and one definition added, nothing else.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "Disease ontologies" / "mild_2026-10-30c.ttl"
NEW = ROOT.parent / "Disease ontologies" / "mild_2026-10-30d.ttl"
M = "https://bioportal.bioontology.org/ontologies/MILD/"
FROM, TO = "MILD_000600", "MILD_120102"
DEFINITION = ("A quality that a material entity has because medicine classifies it as pathological. Pathologicity "
              "is asserted, never inferred: MILD lays down no criteria, rules or inferences for it, because what is "
              "pathological can depend on context.")


def main(argv) -> int:
    import rdflib
    from rdflib import Literal, URIRef
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    text = OLD.read_text(encoding="utf-8")
    block = ":MILD_000600 rdf:type owl:Class ;"
    if text.count(block) != 1:
        raise RuntimeError(f"{block!r} found {text.count(block)} time(s)")
    head, _, tail = text.partition(block)
    label = '                                                                rdfs:label "pathological"@en .'
    if not tail.lstrip("\n").split("\n\n", 1)[0].rstrip().endswith(label.strip()):
        raise RuntimeError("the block of MILD_000600 does not end with its label as expected")
    tail = tail.replace(label, '                                                                '
                        '<http://purl.obolibrary.org/obo/IAO_0000115> "' + DEFINITION + '"@en ;\n' + label, 1)
    new = (head + block + tail).replace(FROM, TO)
    old_g = rdflib.Graph().parse(data=text, format="turtle")
    new_g = rdflib.Graph().parse(data=new, format="turtle")
    want = rdflib.Graph()
    ren = lambda x: URIRef(M + TO) if x == URIRef(M + FROM) else x  # noqa: E731
    for s, p, o in old_g:
        want.add((ren(s), p, ren(o)))
    want.add((URIRef(M + TO), URIRef("http://purl.obolibrary.org/obo/IAO_0000115"), Literal(DEFINITION, lang="en")))
    if not isomorphic(new_g, want):
        _, a, b = graph_diff(to_isomorphic(new_g), to_isomorphic(want))
        raise RuntimeError(f"not the decided change: {list(a)[:5]} / {list(b)[:5]}")
    print(f"[pathological] {OLD.name}: {len(old_g)} triples -> {len(new_g)}; {FROM} is {TO}, with a definition "
          f"(graphs compared)")
    if "--write" not in argv:
        print(f"[pathological] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    NEW.write_text(new, encoding="utf-8")
    print(f"[pathological] written {NEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
