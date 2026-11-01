"""MILD imports the whole of RO and of BFO (2026-10-30).

After the third relation the extraction schema lost because MILD no longer
used it ("has realization", with realized disease predisposition), the
curator: "das geht mir langsam auf die nüsse, jetzt importier gesamt RO und
fertig", and "mild soll auch komplett BFO importieren". MILD imported neither;
it declared the RO and BFO relations it used itself.

`mild_2026-10-30f.ttl` is `mild_2026-10-30e.ttl` with two imports more, by the
version IRIs of the files at hand (no download): RO of 2025-12-17
(`Import ontologies/ro.owl`) and BFO 2020 core (`Import
ontologies/bfo-core2020.owl`); both import catalogs map them there. The graphs
are compared: exactly the two `owl:imports` triples are new.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "Disease ontologies" / "mild_2026-10-30e.ttl"
NEW = ROOT.parent / "Disease ontologies" / "mild_2026-10-30f.ttl"
ONTO = "https://bioportal.bioontology.org/ontologies/MILD"
IMPORTS = ["http://purl.obolibrary.org/obo/bfo/2020/bfo-core.owl",
           "http://purl.obolibrary.org/obo/ro/releases/2025-12-17/ro.owl"]
LAST = "<https://bioportal.bioontology.org/ontologies/MILD/modules/upheno_module.owl> ;"


def main(argv) -> int:
    import rdflib
    from rdflib import OWL, URIRef
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    text = OLD.read_text(encoding="utf-8")
    if text.count(LAST) != 1:
        raise RuntimeError("the import list does not end as expected")
    pad = " " * 65
    new = text.replace(LAST, LAST[:-2] + " ,\n" + ",\n".join(f"{pad}<{i}>" for i in IMPORTS) + " ;")
    old_g = rdflib.Graph().parse(data=text, format="turtle")
    new_g = rdflib.Graph().parse(data=new, format="turtle")
    want = rdflib.Graph()
    for t in old_g:
        want.add(t)
    for i in IMPORTS:
        want.add((URIRef(ONTO), OWL.imports, URIRef(i)))
    if not isomorphic(new_g, want):
        _, a, b = graph_diff(to_isomorphic(new_g), to_isomorphic(want))
        raise RuntimeError(f"not the decided change: {list(a)[:5]} / {list(b)[:5]}")
    print(f"[ro-bfo] {OLD.name}: {len(old_g)} triples -> {len(new_g)}; imports {IMPORTS} (graphs compared)")
    if "--write" not in argv:
        print(f"[ro-bfo] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    NEW.write_text(new, encoding="utf-8")
    print(f"[ro-bfo] written {NEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
