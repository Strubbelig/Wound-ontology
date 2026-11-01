"""Does WONT's wound depth reason as meant? Probe classes over WONT's import closure, with ELK.

    python -u scripts/test_wound_depth.py

Merges WONT (config GROUND_TRUTH_TTL) with its import closure -- MILD, its
modules, WONT's FMA module and the part bridge FMA -> OFL -> BFO -- adds probe
classes and asks ELK (rule 98's companion, 2026-10-31):

* an injury of which a part is part of the epidermis, or of the dermis, is a
  wound (FMA: both are constitutional_part_of Skin; the bridge carries that
  into BFO part of, which Wound's definition uses) and reaches that layer;
* an injury of which a part is part of the subcutis alone is no wound (FMA's
  superficial fascia is part of the integument, not of the skin);
* a part linked to the epidermis only by FMA's own regional_part_of reaches
  the epidermis: the whole chain fma#regional_part_of -> fma#part_of -> Ofl part
  of -> BFO part of;
* each burn degree reaches the layer its definition names, at least.

Exit 0 when every probe answers as expected. Output: output/test_wound_depth/.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "output" / "test_wound_depth"
ROBOT = ["java", "-Xmx6g", "-jar", "/usr/local/bin/robot.jar"]
W = "https://bioportal.bioontology.org/ontologies/WONT/"
P = "https://example.org/wound-depth-probe/"
INJURY, WOUND = W + "WONT_0007817", W + "WONT_0000380"
DEPTH = {"FMA_70596": "WONT_120087", "FMA_70323": "WONT_120088", "FMA_9630": "WONT_120089"}
# probe -> (FMA layer, relation the part has to it, expected: is a wound, the depth class it reaches or None)
PROBES = {
    "injury_epidermis": ("FMA_70596", "http://purl.obolibrary.org/obo/BFO_0000050", True, "WONT_120087"),
    "injury_dermis": ("FMA_70323", "http://purl.obolibrary.org/obo/BFO_0000050", True, "WONT_120088"),
    "injury_subcutis": ("FMA_9630", "http://purl.obolibrary.org/obo/BFO_0000050", False, None),
    "injury_fma_regional_part_of_epidermis": ("FMA_70596", "http://purl.obolibrary.org/obo/fma#regional_part_of",
                                              True, "WONT_120087"),
}
#: burn degree -> every depth class it reaches at least (Third-degree to the subcutis: curator 2026-11-01)
BURNS = {"WONT_0000482": ("WONT_120087",), "WONT_0000483": ("WONT_120088",),
         "WONT_0000484": ("WONT_120088", "WONT_120089"), "WONT_0000485": ("WONT_120089",)}


def main() -> int:
    import rdflib
    from rdflib import OWL, RDFS, URIRef
    from config.settings import GROUND_TRUTH_TTL
    OUT.mkdir(parents=True, exist_ok=True)
    probe = OUT / "probe.ttl"
    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> .", f"<{P[:-1]}> a owl:Ontology ."]
    for name, (layer, rel, _, _) in PROBES.items():
        lines.append(f"<{P}{name}> a owl:Class ; owl:equivalentClass [ owl:intersectionOf ( <{INJURY}> "
                     f"[ a owl:Restriction ; owl:onProperty <http://purl.obolibrary.org/obo/BFO_0000051> ; "
                     f"owl:someValuesFrom [ a owl:Restriction ; owl:onProperty <{rel}> ; "
                     f"owl:someValuesFrom <http://purl.obolibrary.org/obo/{layer}> ] ] ) ] .")
    probe.write_text("\n".join(lines) + "\n", encoding="utf-8")
    closure, merged, reasoned = OUT / "wont_closure.owl", OUT / "probe_merged.owl", OUT / "probe_elk.owl"
    cat = Path(GROUND_TRUTH_TTL).parent / "catalog-v001.xml"
    for args in (["--catalog", str(cat), "merge", "--input", str(GROUND_TRUTH_TTL), "--collapse-import-closure", "true",
                  "--output", str(closure)],
                 ["merge", "--input", str(closure), "--input", str(probe), "--output", str(merged)],
                 ["reason", "--reasoner", "ELK", "--input", str(merged), "--equivalent-classes-allowed", "all",
                  "--output", str(reasoned)]):
        r = subprocess.run([*ROBOT, *args], capture_output=True, text=True)
        if r.returncode:
            print(f"[depth-test] *** ROBOT {args[0] if args[0] != '--catalog' else 'merge'} failed: "
                  f"{(r.stdout + r.stderr)[-800:]} ***")
            return 1
    g = rdflib.Graph().parse(reasoned, format="xml")

    def anc(u):
        """Named superclasses, through subClassOf and named equivalents (ROBOT keeps one per node)."""
        acc, st = set(), [URIRef(u)]
        while st:
            n = st.pop()
            for p in list(g.objects(n, RDFS.subClassOf)) + list(g.objects(n, OWL.equivalentClass)) \
                    + list(g.subjects(OWL.equivalentClass, n)):
                if isinstance(p, URIRef) and p not in acc:
                    acc.add(p); st.append(p)
        return acc

    def reaches(u, depth):
        """u reaches depth: a superclass of u, or the same node (ROBOT drops a named equivalence; the
        depth class's own subclasses then show up under u as well). A depth class without subclasses
        proves nothing that way, so it does not count."""
        subs = set(g.subjects(RDFS.subClassOf, URIRef(W + depth)))
        return URIRef(W + depth) in anc(u) or (bool(subs) and subs <= set(g.subjects(RDFS.subClassOf, URIRef(u)))
                                               | {URIRef(u)})

    bad = 0
    for name, (_, _, is_wound, depth) in PROBES.items():
        u = P + name
        w = URIRef(WOUND) in anc(u)
        d = reaches(u, depth) if depth else None
        ok = w == is_wound and (depth is None or d)
        bad += not ok
        print(f"[depth-test] {name}: wound {w} (expected {is_wound})"
              + (f", reaches {depth} {d}" if depth else "") + f"  {'PASS' if ok else 'FAIL'}")
    for burn, depths in BURNS.items():
        for depth in depths:
            ok = URIRef(W + depth) in anc(W + burn)
            bad += not ok
            print(f"[depth-test] {burn} reaches {depth}: {'PASS' if ok else 'FAIL'}")
    print(f"[depth-test] {'all PASS' if not bad else f'{bad} FAIL'} ({Path(GROUND_TRUTH_TTL).name})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
