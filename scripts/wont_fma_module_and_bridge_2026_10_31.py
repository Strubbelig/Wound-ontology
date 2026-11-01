"""WONT's FMA module and the part bridge FMA -> OFL -> BFO (2026-10-31).

The curator closes the thesis's "most important gap" before submission: WONT
says a wound has a part of the skin and an injury lies in a subdivision of a
cardinal body part, not how deep a wound reaches. Depth is defined by FMA
classes, taken from the same FMA OFL uses, and a bridge file binds FMA's part
relations to OFL's. His choices: six layers (epidermis, dermis, subcutis,
fascia, muscle, bone), the bridge "FMA -> OFL -> BFO".

* `modules/wont_fma_module.owl`: a BOT module of the OBO FMA release
  2020-04-13 (`Import ontologies/fma_obo.owl`, the release OFL 2.0.0 imports;
  MILD's FMA module is a MIREOT of the same file) for the six layers and Skin.
  MIREOT keeps only superclass paths; BOT keeps the part axioms the depth
  reasoning needs (Epidermis and Dermis constitutional_part_of some Skin) and
  fma#part_of's transitivity. FMA's subcutis is `Superficial fascia`
  (FMA_9630, exact synonym "Subcutaneous tissue"); the deep fascia is
  `Investing fascia` (FMA_27935); both are Fascia organs, neither subsumes the
  other.
* `modules/fma_ofl_bfo_part_bridge.owl`: fma#part_of (whose subproperties are
  constitutional_, regional_ and systemic_part_of) is a subproperty of OFL's
  "Ofl part of" (OFLID13297), which is a subproperty of BFO "part of"
  (BFO_0000050); OFL's "Ofl part" (OFLID13296) is a subproperty of BFO "has
  part" (BFO_0000051). OFL itself states the BioPortal FMA's part_of
  (purl.org/sig/ont/fma/part_of) under "Ofl part of", but imports the OBO FMA,
  whose relation is obo/fma#part_of, so that binding never applied. OFL is not
  changed; the bridge says it.

Both are catalogued next to WONT (data/ground truth/ and output/owl/).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
MODS = GT / "modules"
FMA = ROOT.parent / "Import ontologies" / "fma_obo.owl"
OBO = "http://purl.obolibrary.org/obo/"
W = "https://bioportal.bioontology.org/ontologies/WONT/"
OFL = "https://purl.bioontology.org/ontology/OFL/"
MODULE_IRI, MODULE_VERSION = W + "modules/fma_module.owl", W + "modules/2026-10-31/fma_module.owl"
BRIDGE_IRI, BRIDGE_VERSION = W + "bridges/fma_ofl_bfo_part.owl", W + "bridges/2026-10-31/fma_ofl_bfo_part.owl"
MODULE, BRIDGE = MODS / "wont_fma_module.owl", MODS / "fma_ofl_bfo_part_bridge.owl"
SEEDS = {"FMA_70596": "Epidermis", "FMA_70323": "Dermis", "FMA_9630": "Superficial fascia",
         "FMA_27935": "Investing fascia", "FMA_5022": "Muscle organ", "FMA_5018": "Bone organ", "FMA_7163": "Skin"}
ROBOT = ["java", "-Xmx8g", "-jar", "/usr/local/bin/robot.jar"]
CATALOGS = [GT / "catalog-v001.xml", ROOT / "output" / "owl" / "catalog-v001.xml"]


def main(argv) -> int:
    import rdflib
    from rdflib import OWL, RDF, RDFS, DCTERMS, Literal, URIRef
    if not FMA.exists():
        raise RuntimeError(f"{FMA} missing")
    fma = rdflib.Graph().parse(FMA, format="xml")
    ver = fma.value(URIRef(OBO + "fma.owl"), OWL.versionIRI)
    if str(ver) != OBO + "fma/releases/2020-04-13/fma.owl":
        raise RuntimeError(f"{FMA.name} is release {ver}, not the 2020-04-13 OFL imports")
    for i, label in SEEDS.items():
        if str(fma.value(URIRef(OBO + i), RDFS.label)) != label:
            raise RuntimeError(f"{i} is {fma.value(URIRef(OBO + i), RDFS.label)!r} in {FMA.name}, expected {label!r}")
    MODS.mkdir(exist_ok=True)
    for f in (MODULE, BRIDGE):
        if f.exists():
            raise RuntimeError(f"{f} exists; not overwritten")

    seeds = MODS / "_fma_seeds.txt"
    seeds.write_text("".join(OBO + i + "\n" for i in SEEDS))
    tmp = MODS / "_fma_bot.owl"
    subprocess.run(ROBOT + ["extract", "--method", "BOT", "--input", str(FMA), "--term-file", str(seeds),
                            "--output", str(tmp)], check=True)
    subprocess.run(ROBOT + ["annotate", "--input", str(tmp), "--ontology-iri", MODULE_IRI, "--version-iri", MODULE_VERSION,
                            "--annotation", "rdfs:comment",
                            "BOT module of the OBO FMA release 2020-04-13 (the FMA OFL 2.0.0 imports) for the layers "
                            "WONT's wound depth classes name -- Epidermis, Dermis, Superficial fascia (the subcutis), "
                            "Investing fascia (the deep fascia), Muscle organ, Bone organ -- and Skin. Extracted "
                            "2026-10-31 by scripts/wont_fma_module_and_bridge_2026_10_31.py.",
                            "--output", str(MODULE)], check=True)
    tmp.unlink(); seeds.unlink()
    m = rdflib.Graph().parse(MODULE, format="xml")
    missing = [i for i in SEEDS if (URIRef(OBO + i), RDF.type, OWL.Class) not in m]
    if missing or (URIRef(OBO + "fma#part_of"), RDF.type, OWL.TransitiveProperty) not in m:
        raise RuntimeError(f"module lacks {missing} or the transitivity of fma#part_of")
    print(f"[fma] {MODULE.relative_to(ROOT)}: {len(m)} triples, "
          f"{len(set(m.subjects(RDF.type, OWL.Class)))} classes")

    b = rdflib.Graph()
    b.bind("obo", OBO); b.bind("ofl", OFL); b.bind("dcterms", str(DCTERMS))
    o = URIRef(BRIDGE_IRI)
    b.add((o, RDF.type, OWL.Ontology))
    b.add((o, OWL.versionIRI, URIRef(BRIDGE_VERSION)))
    b.add((o, RDFS.label, Literal("FMA, OFL and BFO part relations bridge", lang="en")))
    b.add((o, DCTERMS.created, Literal("2026-10-31", datatype=rdflib.XSD.date)))
    # OWL 2 DL wants every annotation property declared; rdfs:label and rdfs:comment are
    # built in, dcterms:created is not (2026-11-01: the thesis session's DL profile check of
    # WONT's import closure found it undeclared here, the closure's only violation)
    b.add((DCTERMS.created, RDF.type, OWL.AnnotationProperty))
    b.add((o, RDFS.comment, Literal(
        "Binds the part relations of the OBO FMA release 2020-04-13 to OFL's and OFL's to BFO's, so that WONT's "
        "wound depth classes, OFL's flaps and FMA's partonomy speak through one relation: fma#part_of (and with it "
        "constitutional_, regional_ and systemic_part_of) is a subproperty of OFL 'Ofl part of', which is a "
        "subproperty of BFO 'part of'; OFL 'Ofl part' is a subproperty of BFO 'has part'. OFL itself binds the "
        "BioPortal FMA's part_of (purl.org/sig/ont/fma/part_of) but imports the OBO FMA, whose relation is "
        "obo/fma#part_of; this file states the binding for the FMA OFL actually loads. OFL is not changed "
        "(curator, 2026-10-31: bridge 'FMA -> OFL -> BFO').", lang="en")))
    for child, parent in ((OBO + "fma#part_of", OFL + "OFLID13297"), (OFL + "OFLID13297", OBO + "BFO_0000050"),
                          (OFL + "OFLID13296", OBO + "BFO_0000051")):
        for p in (child, parent):
            b.add((URIRef(p), RDF.type, OWL.ObjectProperty))
        b.add((URIRef(child), RDFS.subPropertyOf, URIRef(parent)))
    b.serialize(BRIDGE, format="xml")
    print(f"[fma] {BRIDGE.relative_to(ROOT)}: {len(b)} triples")

    for cat in CATALOGS:
        text = cat.read_text(encoding="utf-8")
        add = ""
        for name, f, ident in ((MODULE_IRI, MODULE, "WONT FMA module"), (BRIDGE_IRI, BRIDGE, "WONT part bridge")):
            if f'name="{name}"' in text:
                raise RuntimeError(f"{cat}: already maps {name}")
            add += f'    <uri id="{ident}" name="{name}" uri="{f.as_uri()}"/>\n'
        anchor = "    <uri id=\"MILD import\""
        if text.count(anchor) != 1:
            raise RuntimeError(f"{cat}: no single MILD import entry to insert before")
        cat.write_text(text.replace(anchor, add + anchor), encoding="utf-8")
        print(f"[fma] catalogued in {cat.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
