"""Apply a WONT axiom patch to a COPY of the curated WONT and check it.

    python -u scripts/wont_patch_check.py ADD.ttl REMOVE.ttl [--hermit]

The curated WONT (data/ground truth/ground_truth_final.owl) is never written:
changes there are the curator's hand edits. This writes the patched copy to
output/owl/wont_patch_candidate_<date>.ttl, so the curator can open it in
Protégé, compare, and adopt it, or apply the two files by hand.

Besides the triples in REMOVE.ttl, every owl:equivalentClass of a class the
ADD file marks owl:deprecated is removed (an obsolete class keeps no logic,
OBO practice). Checks, each loud (rule 1):
  * every removal was present in WONT (a removal that matches nothing means
    the patch was written against another version);
  * every new WONT id is free: not in WONT, and not a registry id unless the
    registry entry carries the same name (rule 71);
  * ELK over the copy with its imports: no unsatisfiable class;
  * with --hermit, HermiT too (the closures and the wavelength bound are OWL DL).
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
WONT = ROOT / "data" / "ground truth" / "ground_truth_final.owl"
CATALOG = ROOT / "output" / "owl" / "catalog-v001.xml"
NS = "https://bioportal.bioontology.org/ontologies/WONT/"


def robot(*args, xmx="3g", timeout=None) -> subprocess.CompletedProcess:
    cmd = ["java", f"-Xmx{xmx}", "-jar", "/usr/local/bin/robot.jar", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def main(argv: list[str]) -> int:
    add_p, rem_p = Path(argv[1]), Path(argv[2])
    g = rdflib.Graph().parse(WONT, format="turtle")
    add = rdflib.Graph().parse(add_p, format="turtle")
    rem = rdflib.Graph().parse(rem_p, format="turtle")
    before = len(g)

    missing = [t for t in rem if t not in g]
    if missing:
        raise RuntimeError(f"[patch] {len(missing)} removal(s) are not in WONT -- written against "
                           f"another version? {missing}")
    for t in rem:
        g.remove(t)
    retired = set(add.subjects(OWL.deprecated, None))
    dropped_eq = 0
    for c in retired:
        for e in list(g.objects(c, OWL.equivalentClass)):
            g.remove((c, OWL.equivalentClass, e))
            dropped_eq += 1
            # the class expression behind it: its blank nodes, recursively
            todo = [e] if isinstance(e, rdflib.BNode) else []
            while todo:
                b = todo.pop()
                for p, o in list(g.predicate_objects(b)):
                    g.remove((b, p, o))
                    if isinstance(o, rdflib.BNode):
                        todo.append(o)

    # New ids must be free.
    from wound_ontology.owl.id_registry import IdRegistry
    reg = IdRegistry(ROOT / "data" / "registry" / "wont_ids.json", namespace=NS)
    in_wont = {s for s in g.subjects(RDF.type, OWL.Class) if str(s).startswith(NS)}
    new = {s for s in add.subjects(RDF.type, OWL.Class) if str(s).startswith(NS)} - in_wont
    clash = []
    for s in sorted(new):
        e = reg.entries.get(str(s))
        lab = str(add.value(s, RDFS.label) or "")
        if e and IdRegistry.key(e["label"]) != IdRegistry.key(lab):
            clash.append((str(s).rsplit("/", 1)[-1], lab, "registry holds", e["label"]))
    if clash:
        raise RuntimeError(f"[patch] id(s) taken by another class: {clash}")
    reused = [str(s).rsplit("/", 1)[-1] for s in new if str(s) in reg.entries]

    g += add
    out = ROOT / "output" / "owl" / f"wont_patch_candidate_{date.today():%Y-%m-%d}.ttl"
    g.serialize(out, format="turtle")
    nums = [int(m.group(1)) for s in g.subjects(RDF.type, OWL.Class)
            for m in [re.search(r"WONT_(\d+)$", str(s))] if m and int(m.group(1)) < 100000]
    print(f"[patch] WONT {before:,} triples -> copy {len(g):,}; removed {len(rem)} + {dropped_eq} "
          f"equivalence(s) of {len(retired)} retired class(es); {len(new)} new WONT class(es), "
          f"{len(reused)} keeping a literature id {sorted(reused)}")
    print(f"[patch] copy written: {out.relative_to(ROOT)}  (curated WONT untouched; "
          f"highest id in the copy WONT_{max(nums):07d})")

    reasoners = ["ELK"] + (["HermiT"] if "--hermit" in argv else [])
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.ttl"
        g.serialize(src, format="turtle")
        merged = Path(tmp) / "merged.owl"
        r = robot("--catalog", str(CATALOG), "merge", "--input", str(src),
                  "--collapse-import-closure", "true", "--output", str(merged))
        if r.returncode:
            raise RuntimeError(f"[patch] merge failed: {r.stderr[-800:]}")
        bad = 0
        for name in reasoners:
            dump = Path(tmp) / f"unsat_{name}.txt"
            r = robot("reason", "--reasoner", name, "--input", str(merged),
                      "--dump-unsatisfiable", str(dump), "--output", str(Path(tmp) / "out.owl"),
                      xmx="3g" if name == "ELK" else "8g")
            log = r.stdout + r.stderr
            unsat = sorted(set(re.findall(r"unsatisfiable: (\S+)", log)))
            if "inconsistent" in log.lower():
                print(f"[patch] *** {name}: the copy is INCONSISTENT ***\n{log[-1500:]}")
                bad += 1
            elif unsat:
                print(f"[patch] *** {name}: {len(unsat)} unsatisfiable class(es) ***")
                for u in unsat[:60]:
                    print(f"[patch]   {u}")
                bad += 1
            elif r.returncode:
                raise RuntimeError(f"[patch] {name} failed: {log[-1500:]}")
            else:
                print(f"[patch] {name}: consistent, no unsatisfiable class")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
