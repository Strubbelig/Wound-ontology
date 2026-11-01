"""MILD's two Hucklenbroich comments say what the thesis says of pathologicity (2026-10-30).

Asked whether to align them with the thesis -- MILD lays down no criteria,
rules or inferences for pathologicity and records it as a classification by
medicine -- the curator (through the thesis session): "ja bitte". The two:

* MODEL COMMITMENT (2 of 4) on the ontology, which said MILD "adopts
  Hucklenbroich's criteria - threat to life, pain and suffering, loss of
  ability, loss of fertility" and set itself apart from normativism, while
  the thesis says the stance is close to it (Engelhardt 1975);
* the comment on material disease entity, carried over from pathological
  disorder: "Pathologicity is asserted - not inferred - by primitives (e.g.
  threat to life, pain/suffering, loss of ability/fertility) as mentioned by
  Hucklenbroich et al."

Both now follow the definition of the quality pathological (MILD_120102).
`mild_2026-10-30g.ttl` is `mild_2026-10-30f.ttl` with these two literals
replaced; the graphs are compared.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent / "Disease ontologies" / "mild_2026-10-30f.ttl"
NEW = ROOT.parent / "Disease ontologies" / "mild_2026-10-30g.ttl"
COMMITMENT_OLD = (
    "MODEL COMMITMENT (2 of 4) - pathologicity is a declared primitive. What makes a disorder pathological is "
    "ASSERTED by criteria, never inferred. MILD adopts Hucklenbroich's criteria - threat to life, pain and "
    "suffering, loss of ability, loss of fertility - and does not reduce pathologicity to statistical rarity "
    "(Boorse) or to social disvalue (normativism). Species-comparative abnormality alone is explicitly not "
    "sufficient, because rare variation is not thereby pathological. Following Scheuermann et al., this term is "
    "left primitive on purpose rather than defined away, and the choice is recorded here rather than hidden. See "
    "MILD_120020.")
COMMITMENT_NEW = (
    "MODEL COMMITMENT (2 of 4) - pathologicity is a declared primitive. A material entity is pathological because "
    "medicine classifies it as pathological; this is asserted, never inferred. MILD lays down no criteria, rules or "
    "inferences for pathologicity, because what is pathological can depend on context, and records the "
    "classification by the quality pathological (MILD_120102). Following Scheuermann et al., this term is left "
    "primitive on purpose rather than defined away, and the choice is recorded here rather than hidden. See "
    "MILD_120020.")
MDE_OLD = ("Pathologicity is asserted - not inferred -  by primitives (e.g. threat to life, pain/suffering, loss of "
           "ability/fertility) as mentioned by Hucklenbroich et al.")
MDE_NEW = ("Pathologicity is asserted, never inferred: a material entity is a material disease entity because "
           "medicine classifies it as pathological (the quality pathological, MILD_120102). MILD lays down no "
           "criteria, rules or inferences for it, because what is pathological can depend on context.")


def main(argv) -> int:
    import rdflib
    from rdflib import Literal
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    text = OLD.read_text(encoding="utf-8")
    new = text
    for a, b in ((COMMITMENT_OLD, COMMITMENT_NEW), (MDE_OLD, MDE_NEW)):
        if new.count(f'"{a}"@en') != 1:
            raise RuntimeError(f"found {new.count(chr(34) + a + chr(34) + '@en')} time(s): {a[:80]!r}")
        new = new.replace(f'"{a}"@en', f'"{b}"@en')
    old_g = rdflib.Graph().parse(data=text, format="turtle")
    new_g = rdflib.Graph().parse(data=new, format="turtle")
    want = rdflib.Graph()
    swap = {Literal(COMMITMENT_OLD, lang="en"): Literal(COMMITMENT_NEW, lang="en"),
            Literal(MDE_OLD, lang="en"): Literal(MDE_NEW, lang="en")}
    for s, p, o in old_g:
        want.add((s, p, swap.get(o, o)))
    if not isomorphic(new_g, want):
        _, a, b = graph_diff(to_isomorphic(new_g), to_isomorphic(want))
        raise RuntimeError(f"not the decided change: {list(a)[:5]} / {list(b)[:5]}")
    print(f"[pathologicity] {OLD.name}: {len(old_g)} triples -> {len(new_g)}; 2 comments now say what the thesis "
          f"says (graphs compared)")
    if "--write" not in argv:
        print(f"[pathologicity] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    NEW.write_text(new, encoding="utf-8")
    print(f"[pathologicity] written {NEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
