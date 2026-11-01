"""`realized disease predisposition` out of MILD (2026-10-30).

The curator, on its axiom (`SubClassOf: 'disease predisposition', 'has
realization' some 'disorder development process'`): "ich glaub das axiom
stimmt so nicht". Read to him: it says a disease came about by realizing this
predisposition -- an aetiological claim MILD refuses (MODEL COMMITMENT 4 of 4)
and that nobody can observe of a tendency, which may be realized to varying
degrees or not at all. Asked whether to delete it and its counterpart
`predisposition realizing disorder development process` (MILD_120012): "lösch
nur realized predisposition".

`mild_2026-10-30e.ttl` is `mild_2026-10-30d.ttl` without the block of
MILD_120014, which nothing else in MILD, WONT or the term dict names; the
graphs are compared: the new file must be the old one without exactly that
class's triples.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "Disease ontologies" / "mild_2026-10-30d.ttl"
NEW = ROOT.parent / "Disease ontologies" / "mild_2026-10-30e.ttl"
M = "https://bioportal.bioontology.org/ontologies/MILD/"
GONE = "MILD_120014"


def main(argv) -> int:
    import rdflib
    from rdflib import BNode, URIRef
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    text = OLD.read_text(encoding="utf-8")
    head = f"###  {M}{GONE}\n"
    start = text.find(head)
    if start < 0 or text.count(head) != 1:
        raise RuntimeError(f"the block of {GONE} is not found once")
    end = text.find("\n\n\n", start)
    block = text[start:end + 3]
    if not block.rstrip().endswith('rdfs:label "realized disease predisposition"@en .'):
        raise RuntimeError(f"the block of {GONE} does not end with its label: {block[-200:]!r}")
    new = text[:start] + text[end + 3:]
    if GONE in new:
        raise RuntimeError(f"{GONE} is still named elsewhere in MILD; not deleted")
    old_g = rdflib.Graph().parse(data=text, format="turtle")
    new_g = rdflib.Graph().parse(data=new, format="turtle")
    want = rdflib.Graph()
    for t in old_g:
        want.add(t)
    gone = URIRef(M + GONE)

    def drop(n):
        for p, o in list(want.predicate_objects(n)):
            want.remove((n, p, o))
            if isinstance(o, BNode):
                drop(o)
    drop(gone)
    if not isomorphic(new_g, want):
        _, a, b = graph_diff(to_isomorphic(new_g), to_isomorphic(want))
        raise RuntimeError(f"not the decided change: {list(a)[:5]} / {list(b)[:5]}")
    print(f"[realized] {OLD.name}: {len(old_g)} triples -> {len(new_g)} ({len(old_g) - len(new_g)} fewer); "
          f"{GONE} realized disease predisposition deleted (graphs compared)")
    if "--write" not in argv:
        print(f"[realized] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    NEW.write_text(new, encoding="utf-8")
    print(f"[realized] written {NEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
