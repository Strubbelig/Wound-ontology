"""WONT's definitions say how things are, not what caused them (2026-10-31).

The curator: "vermeide einfach notorisch kausalität" (relayed by the thesis
session, 2026-10-31, with Injury's "whatever its cause" and the request to read
the drafted definitions for "caused by", "due to", "resulting from").

* Injury (WONT_0007817): "..., however it came about" (the thesis session's
  wording) in place of "whatever its cause": any injury, by origin unrestricted.
* Eleven definitions Claude drafted on 2026-10-30 (rule 94) said a cause:
  "owing to", "resulting from ... caused by", "microorganisms that cause",
  "arise as", "producing", "results in", "the resulting cavity", "arising
  after/in". Each now says what is there, where, or what a process has as
  output -- WONT's own pattern, which claims no cause.
* Not changed: physical or spatial wording ("fluid from the wound", the suction
  a drain's bulb produces, honey produced by bees); "spontaneously arising"
  blisters and an "acute wound that has recently arisen" (no cause named); the
  curator's own and imported definitions (Neoplasm "arising from", Erysipelas
  "caused by", MRSA infection "causal agent", the five "No claim is made that
  the disorder caused the wound") -- put to the curator.

`ground_truth_final_2026-10-31b.owl` is `..._2026-10-31.owl` with these
definitions; every changed triple is checked to be one of them.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "data" / "ground truth"
OLD, NEW = GT / "ground_truth_final_2026-10-31.owl", GT / "ground_truth_final_2026-10-31b.owl"
W, OBO = "https://bioportal.bioontology.org/ontologies/WONT/", "http://purl.obolibrary.org/obo/"

DEFINITIONS = {   # WONT id -> (old text, new text), each matched whole
    "0007817": ("A material disease entity that is structural damage to a tissue or an organ, whatever its cause.",
                "A material disease entity that is structural damage to a tissue or an organ, however it came "
                "about."),
    "0000027": ("A skin wound located on the leg or foot in which the skin and underlying tissue are disrupted in an "
                "area that is ischaemic owing to insufficient arterial blood supply.",
                "A skin wound located on the leg or foot in which the skin and underlying tissue are disrupted in an "
                "area that is ischaemic, with insufficient arterial blood supply."),
    "0000348": ("A skin wound that is an ulcer of the lower leg resulting from ischemic necrosis of the skin caused "
                "by stenosing arteriolosclerosis of subcutaneous arterioles in a patient with arterial hypertension.",
                "A skin wound that is an ulcer of the lower leg at a site of ischemic necrosis of the skin, with "
                "stenosing arteriolosclerosis of subcutaneous arterioles, in a patient with arterial hypertension."),
    "0000558": ("A material disease entity consisting in the abnormal organization of the organs or tissues of a "
                "patient, resulting from a dysregulated host response to an infection, such that organ function is "
                "impaired.",
                "A material disease entity consisting in the abnormal organization of the organs or tissues of a "
                "patient that is the output of a dysregulated host response to an infection, such that organ "
                "function is impaired."),
    "0000202": ("A diagnostic process to assess wound characteristics in which a specimen collected from the wound "
                "with a swab is examined in a laboratory to detect and identify microorganisms that cause wound "
                "infection.",
                "A diagnostic process to assess wound characteristics in which a specimen collected from the wound "
                "with a swab is examined in a laboratory to detect and identify microorganisms that participate in "
                "wound infection."),
    "0000111": ("A material disease entity consisting of one or more sharply demarcated inflammatory lesions of the "
                "skin or mucosa that arise as a hypersensitivity reaction to a drug and recur at the same sites each "
                "time the patient is re-exposed to that drug.",
                "A material disease entity consisting of one or more sharply demarcated inflammatory lesions of the "
                "skin or mucosa that are the output of a hypersensitivity reaction to a drug and recur at the same "
                "sites each time the patient is re-exposed to that drug."),
    "0000046": ("A skin wound in which the skin layers separate within the epidermis or at the dermo-epidermal "
                "junction, and fluid collects in the resulting cavity.",
                "A skin wound in which the skin layers separate within the epidermis or at the dermo-epidermal "
                "junction, and fluid collects in the space between them."),
    "0000271": ("A traumatic wound that is the output of a sharp or rough object being drawn across the skin surface, "
                "producing a superficial linear disruption of the skin.",
                "A traumatic wound that is a superficial linear disruption of the skin and the output of a process "
                "in which a sharp or rough object is drawn across the skin surface."),
    "0000552": ("A traumatic wound in which tissue has been torn or split by blunt force, producing irregular wound "
                "margins.",
                "A traumatic wound in which tissue has been torn or split by blunt force and that has irregular "
                "wound margins."),
    "0000269": ("A disorder development process in which the fibrous tissue laid down during wound repair is "
                "deposited in excess or in a disorganized way, so that the repair results in an abnormal scar.",
                "A disorder development process in which the fibrous tissue laid down during wound repair is "
                "deposited in excess or in a disorganized way, and that has as output an abnormal scar."),
    "0000550": ("A material disease entity that is an infection by microorganisms of the surgical incision, of the "
                "tissues at the operative site or of an organ or space manipulated during a surgical operation, "
                "arising after that operation.",
                "A material disease entity that is an infection by microorganisms of the surgical incision, of the "
                "tissues at the operative site or of an organ or space manipulated during a surgical operation, "
                "beginning after that operation."),
    "0000186": ("A skin wound that is an ulcerated malignant neoplasm arising in scar tissue or in a long-standing "
                "chronic wound.",
                "A skin wound that is an ulcerated malignant neoplasm in scar tissue or in a long-standing chronic "
                "wound."),
}


def main(argv) -> int:
    import rdflib
    from rdflib import Literal, URIRef
    from rdflib.compare import graph_diff, isomorphic, to_isomorphic
    old = rdflib.Graph().parse(OLD, format="turtle")
    iao = URIRef(OBO + "IAO_0000115")
    g = rdflib.Graph()
    for pfx, ns in old.namespaces():
        g.bind(pfx, ns)
    for t in old:
        g.add(t)
    for k, (a, b) in DEFINITIONS.items():
        s = URIRef(W + "WONT_" + k)
        have = list(old.objects(s, iao))
        if [str(d) for d in have] != [a]:
            raise RuntimeError(f"WONT_{k}: definition {[str(d)[:80] for d in have]}, expected {a[:80]!r}")
        g.remove((s, iao, have[0]))
        g.add((s, iao, Literal(b, lang=have[0].language)))
    _, gone, came = graph_diff(to_isomorphic(old), to_isomorphic(g))
    allowed = {URIRef(W + "WONT_" + k) for k in DEFINITIONS}
    off = [t for t in list(gone) + list(came) if t[0] not in allowed or t[1] != iao]
    if off or len(gone) != len(DEFINITIONS) or len(came) != len(DEFINITIONS):
        raise RuntimeError(f"changed triples: {len(gone)} gone, {len(came)} come, {len(off)} outside the "
                           f"definitions named here")
    print(f"[causal] {OLD.name}: {len(old):,} triples -> {len(g):,}; {len(DEFINITIONS)} definitions rewritten")
    for k, (a, b) in DEFINITIONS.items():
        print(f"[causal]     WONT_{k}: {b}")
    if "--write" not in argv:
        print(f"[causal] dry run; --write writes {NEW.name}")
        return 0
    if NEW.exists():
        raise RuntimeError(f"{NEW} exists; not overwritten")
    g.serialize(NEW, format="turtle")
    if not isomorphic(rdflib.Graph().parse(NEW, format="turtle"), g):
        raise RuntimeError("the written file is not the graph meant")
    print(f"[causal] written {NEW.relative_to(ROOT)} (read back, identical)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
