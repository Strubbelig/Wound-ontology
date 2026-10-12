"""Join the two checks of the placement answers into one decision per term. Sandbox only.

    python -u scripts/merge_placement_checks.py

Curator, 2026-10-01: the placement answers are not used as the model gave them.
Every `is_a`/`same` answer passed exactly one second check:

* the 2,309 the sandbox review found most reliable -> the model's yes/no
  question (`scripts/p4_verify_placements.py`, `placement_verify_2026-10-01.json`);
* the other 16,150 -> read row by row by Claude
  (`placement_selfcheck_2026-10-01/verdicts_XX.txt`: `n:0` no parent,
  `n:1..4` the numbered alternative of `chunk_XX.txt`, `n:I` a `same` that is
  only an `is_a`; a row not listed stands as answered);
* 143 answers name no offered class or no class at all -> dropped (curator:
  "thanks").

Outcome per term: `placed` (is_a, parent stands), `synonym` (same, stands),
`candidate` (the check refused the parent; the refused parent is kept as
`suggested` so a curator sees what was proposed), `unplaced` (the model said
none), `unanswered` (the verify run has not answered it yet), `unchecked`
(usable, but cut after the checks), `dropped`.

Reads `output/placement_current_2026-10-01.json`, the verify file and the
self-check folder; the alternatives' IRIs come from the same class pool the
placement run offered (WONT ground truth + MILD + import modules). Writes
`data/review/placement_merged_2026-10-01.json` and reads it back. No term
dict, no ontology file.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SRC = ROOT / "output" / "placement_current_2026-10-01.json"
VERIFY = ROOT / "data" / "review" / "placement_verify_2026-10-01.json"
SELF = ROOT / "data" / "review" / "placement_selfcheck_2026-10-01"
VCHECK = ROOT / "data" / "review" / "placement_verifycheck_2026-10-01"   # Claude over the verify rows
OUT = ROOT / "data" / "review" / "placement_merged_2026-10-01.json"
GT = ROOT / "data" / "ground truth" / "ground_truth_final.owl"
MILD = ROOT.parent / "Disease ontologies" / "Disease proposal 2.ttl"
MODULES = ROOT.parent / "Disease ontologies" / "Disease ontology modules"


def key(r):
    return (r["term"], r["relation"], r["parent"])


def label_index():
    """label -> set of IRIs over the class pool the placement run offered,
    and the one class each label stands for (`one_class`)."""
    import rdflib
    from rdflib.namespace import OWL, RDF, RDFS
    gt, mild = rdflib.Graph(), rdflib.Graph()
    gt.parse(GT, format="turtle"); mild.parse(MILD, format="turtle")
    g = rdflib.Graph(); g += gt; g += mild
    for m in sorted(MODULES.glob("*_module.owl")):
        g.parse(m)
    idx = defaultdict(set)
    for s in g.subjects(RDF.type, OWL.Class):
        if isinstance(s, rdflib.URIRef):
            for lab in g.objects(s, RDFS.label):
                idx[str(lab)].add(str(s))
    in_gt = {str(s) for s in gt.subjects(RDF.type, OWL.Class)}
    in_mild = {str(s) for s in mild.subjects(RDF.type, OWL.Class)}
    return idx, one_class(idx, in_gt, in_mild)


# Curator, 2026-10-02: "wont has its own disease class. dont reuse ogms. same
# with the protein class. we dont need several class of several ontologies
# with the same name". One class per label: the ground truth's own copy (its
# WONT_ class first -- WONT also holds bare HP/DOID copies of Abscess, Pressure
# ulcer, Osteomyelitis, Lymphocele with no parent), then MILD, then COB, then
# UBERON, then any other module. `disease` is OGMS_0000031 (a disposition);
# WONT's disease class is MILD's `material disease entity`, where the
# curator's ruling of 2026-09-29 already sends the word.
DISEASE = "https://bioportal.bioontology.org/ontologies/MILD/MILD_120020"
# Terms whose abstract typing contradicts the one class they now sit under
# (found by ELK after the redirect, 2026-10-02); retyped with the reason.
RETYPE = {"cervicofacial abscess": ("material entity",
          "an abscess is a material entity; WONT's Abscess is a pathological disorder (ELK, 2026-10-02)")}
REDIRECT = {"http://purl.obolibrary.org/obo/OGMS_0000031": (DISEASE, "material disease entity"),
            "http://purl.obolibrary.org/obo/DOID_4": (DISEASE, "material disease entity")}


def one_class(idx, in_gt, in_mild):
    def rank(i):
        if i in in_gt and "/WONT/" in i:
            return 0
        if i in in_gt:
            return 1
        if i in in_mild:
            return 2
        for n, ns in enumerate(("COB_", "UBERON_"), start=3):
            if ns in i:
                return n
        return 9
    folded = defaultdict(set)
    for lab, iris in idx.items():
        folded[" ".join(lab.lower().split())] |= iris
    out = {}
    for lab, iris in folded.items():
        if len(iris) > 1:
            best = min(iris, key=lambda i: (rank(i), i))
            for i in iris:
                if i != best:
                    out[i] = best
    return out


def read_chunks(folder=None):
    """n -> (term, relation symbol, parent, {k: alternative label})."""
    out = {}
    for f in sorted((folder or SELF).glob("chunk_*.txt")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            n, term, _cat, rel_parent, alts = line.split("|", 4)
            if folder == VCHECK:                  # one more field: the model's answer
                alts = alts.split("|", 1)[1]
            alt = {}
            for part in alts.split(" ; "):
                k, _, lab = part.partition(":")
                alt[int(k)] = lab.strip()
            out[int(n)] = (term, rel_parent[0], rel_parent[2:], alt)
    return out


def read_verdicts(folder=None, codes="0-4I"):
    out, dup = {}, []
    for f in sorted((folder or SELF).glob("verdicts_*.txt")):
        for tok in f.read_text(encoding="utf-8").split():
            m = re.fullmatch(rf"(\d+):([{codes}])", tok)
            if not m:
                raise SystemExit(f"[merge] unreadable verdict {tok!r} in {f.name}")
            n = int(m[1])
            if n in out and out[n] != m[2]:
                dup.append((n, out[n], m[2]))
            out[n] = m[2]
    if dup:
        raise SystemExit(f"[merge] {len(dup)} rows carry two different verdicts, e.g. {dup[:5]}")
    return out


def main() -> int:
    rows = json.loads(SRC.read_text(encoding="utf-8"))["rows"]
    selfrows = json.loads((SELF / "rows.json").read_text(encoding="utf-8"))["rows"]
    verify = {(v["term"], v["relation"], v["parent"]): v
              for v in json.loads(VERIFY.read_text(encoding="utf-8"))["rows"]}
    chunks, verdicts = read_chunks(), read_verdicts()
    vchunks = read_chunks(VCHECK)
    vverdicts = read_verdicts(VCHECK, codes="0-4IY")
    vrows = json.loads((VCHECK / "rows.json").read_text(encoding="utf-8"))["rows"]
    vkey = {key(r): r["n"] for r in vrows}
    for n, (term, _, parent, _) in vchunks.items():
        r0 = next(r for r in vrows if r["n"] == n)
        if (r0["term"], r0["parent"]) != (term, parent):
            raise SystemExit(f"[merge] verify-check row {n}: chunk and rows.json disagree")
    by_n = {r["n"]: r for r in selfrows}
    if set(chunks) != set(by_n):
        raise SystemExit(f"[merge] chunk files and rows.json disagree: {len(set(chunks) ^ set(by_n))} rows")
    for n, (term, _, parent, _) in chunks.items():
        if (by_n[n]["term"], by_n[n]["parent"]) != (term, parent):
            raise SystemExit(f"[merge] row {n}: chunk says {term!r} < {parent!r}, rows.json disagrees")
    selfkey = {key(r): r["n"] for r in selfrows}

    from p4_verify_placements import selected
    vsel = {key(r) for r in selected(rows)}
    if vsel & set(selfkey):
        raise SystemExit(f"[merge] {len(vsel & set(selfkey))} rows were in both checks")

    idx, same_as = label_index()
    iri_label = {i: lab for lab, iris in idx.items() for i in iris}
    out, problems = [], []
    for r in rows:
        base = {"term": r["term"], "category": r["category"], "abstracts": r["abstracts"],
                "model relation": r["relation"], "model parent": r["parent"],
                "model parent iri": r.get("parent iri")}
        k = key(r)
        if r["relation"] == "none":
            out.append({**base, "outcome": "unplaced", "check": "model said none"})
        elif k in vsel:
            v = verify.get(k)
            n = vkey.get(k)
            mine = vverdicts.get(n) if n is not None else None
            if v is None:
                out.append({**base, "outcome": "unanswered", "check": "verify: not yet answered"})
                continue
            # Claude read every verify row too (curator, 2026-10-01: "do it");
            # a listed verdict overrides the model, an unlisted row agrees with it
            ans = v["answer"]
            if n is None:
                problems.append(f"{r['term']!r}: verify row missing from the verify check")
                check = f"verify: {ans} (not read)"
            else:
                check = f"verify: {ans}; Claude: " + {None: "agrees", "Y": "yes (overrides)",
                         "0": "no (overrides)", "I": "is_a, not same"}.get(mine, f"alternative {mine}")
            if mine == "I" or (mine is None and ans == "yes") or mine == "Y":
                rel = "is_a" if mine == "I" else r["relation"]
                out.append({**base, "outcome": "synonym" if rel == "same" else "placed",
                            "relation": rel, "parent": r["parent"], "parent iri": r["parent iri"],
                            "check": check, "reason": v["reason"]})
            elif mine in ("1", "2", "3", "4"):
                lab = vchunks[n][3].get(int(mine))
                iris = sorted(idx.get(lab, ())) if lab else []
                if len(iris) != 1:
                    problems.append(f"verify row {n} {r['term']!r}: alternative {mine} = {lab!r} resolves to {len(iris)} classes")
                    out.append({**base, "outcome": "candidate", "suggested": lab, "suggested iri": None,
                                "check": check + ", class not resolved"})
                    continue
                out.append({**base, "outcome": "synonym" if r["relation"] == "same" else "placed",
                            "relation": r["relation"], "parent": lab, "parent iri": iris[0], "check": check})
            else:
                out.append({**base, "outcome": "candidate", "suggested": r["parent"],
                            "suggested iri": r["parent iri"], "check": check, "reason": v["reason"]})
        elif k in selfkey:
            n = selfkey[k]
            vd = verdicts.get(n)
            if vd is None:
                out.append({**base, "outcome": "synonym" if r["relation"] == "same" else "placed",
                            "relation": r["relation"], "parent": r["parent"], "parent iri": r["parent iri"],
                            "check": "self-check: stands", "row": n})
            elif vd == "0":
                out.append({**base, "outcome": "candidate", "suggested": r["parent"],
                            "suggested iri": r["parent iri"], "check": "self-check: no parent", "row": n})
            elif vd == "I":
                if r["relation"] != "same":
                    problems.append(f"row {n} {r['term']!r}: I on an is_a row")
                out.append({**base, "outcome": "placed", "relation": "is_a", "parent": r["parent"],
                            "parent iri": r["parent iri"], "check": "self-check: same -> is_a", "row": n})
            else:
                lab = chunks[n][3].get(int(vd))
                iris = sorted(idx.get(lab, ())) if lab else []
                if len(iris) != 1:
                    problems.append(f"row {n} {r['term']!r}: alternative {vd} = {lab!r} resolves to {len(iris)} classes")
                    out.append({**base, "outcome": "candidate", "suggested": lab, "suggested iri": None,
                                "check": f"self-check: alternative {vd}, class not resolved", "row": n})
                    continue
                rel = r["relation"]
                out.append({**base, "outcome": "synonym" if rel == "same" else "placed", "relation": rel,
                            "parent": lab, "parent iri": iris[0], "check": f"self-check: alternative {vd}",
                            "row": n})
        elif r.get("unlisted") or not r.get("parent"):
            out.append({**base, "outcome": "dropped",
                        "check": "no offered class" if r.get("unlisted") else "no class named"})
        else:
            # usable, but in neither check: a term the view gained after the
            # checks were cut (a refusal freed it). Never counted as dropped.
            out.append({**base, "outcome": "unchecked", "check": "unchecked: in neither check"})

    # one class per label (curator, 2026-10-02), and WONT's own disease class
    redirected, retyped = Counter(), 0
    for row in out:
        for f_iri, f_lab in (("parent iri", "parent"), ("suggested iri", "suggested")):
            i = row.get(f_iri)
            if not i:
                continue
            if i in REDIRECT:
                new_i, new_lab = REDIRECT[i]
            elif i in same_as:
                new_i = same_as[i]
                new_lab = row[f_lab]
            else:
                continue
            row[f_iri + " was"] = i
            row[f_iri] = new_i
            row[f_lab] = new_lab if i in REDIRECT else next(
                (lab for lab in idx if new_i in idx[lab]), row[f_lab])
            redirected[(i.rsplit("/", 1)[-1], new_i.rsplit("/", 1)[-1])] += 1
            if new_i == DISEASE and f_iri == "parent iri" and row["category"] != "material entity":
                row["category was"] = row["category"]
                row["category"] = "material entity"
                row["category note"] = "follows its superclass, MILD material disease entity (curator, 2026-10-02)"
                retyped += 1
    for row in out:
        if row["term"] in RETYPE and row["outcome"] in ("placed", "synonym"):
            row["category was"], row["category"] = row["category"], RETYPE[row["term"]][0]
            row["category note"] = RETYPE[row["term"]][1]
            retyped += 1
    print(f"[merge] one class per label: {sum(redirected.values())} parent(s) redirected "
          f"{dict(redirected.most_common())}; {retyped} term(s) retyped material entity under material disease entity")
    OUT.write_text(json.dumps({"measured": time.strftime("%Y-%m-%d %H:%M"), "rows": out},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(OUT.read_text(encoding="utf-8"))["rows"]
    if len(back) != len(rows) or {x["term"] for x in back} != {r["term"] for r in rows}:
        raise SystemExit("[merge] read-back does not hold every term once")
    print(f"[merge] written and read back: {len(back):,} terms -> {OUT.relative_to(ROOT)}")
    for (o, c), n in sorted(Counter((x["outcome"], x["check"].split(":")[0]) for x in back).items()):
        print(f"[merge]   {o:<11} {c:<20} {n:>6,}")
    print(f"[merge] by outcome: {dict(Counter(x['outcome'] for x in back))}")
    for p in problems:
        print(f"[merge] PROBLEM {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
