"""Build the review sheet for the term mapping — P4 step 2, the manual one.

`review_mapping()` walks every non-identity entry at an interactive prompt. On
the 2026-09-21 build that is 14,131 questions, and pressing `y` fourteen
thousand times is not review; the 2026-09-10 sheet made the same point at 191.
So the queue is partitioned first, by the rule the pipeline itself used to
decide what to ask the model:

  * `label_difference` says how two labels differ. `identical` (case,
    punctuation, spacing) and `inflection` (singular/plural) were accepted
    without a model call, because all 28 such pairs in the 2026-09-06 sample
    were right. They are not in the sheet.
  * `content` — a real word changed — is what the model adjudicated, and what
    a curator has to confirm. Those are the rows here.

Within them the sheet is ordered by consequence: the pairs the ontologies
already relate by an axiom first (a merge that contradicts WONT is wrong
however plausible it reads), then the anchor merges, which absorb a store term
into an existing class and cannot be undone downstream, then the store-to-store
merges by how many mentions they move.

Writes data/review/mapping_review_<date>.csv. Mark it up and apply it with
scripts/apply_review_sheet.py.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from rdflib import OWL, RDF, RDFS, Graph, URIRef

from wound_ontology.llm.category_vocab import is_category
from wound_ontology.mappers.mapping_adjudicator import label_difference
from wound_ontology.orchestrator import Orchestrator
from wound_ontology.utils.rdf_io import parse_graph

ALT = URIRef("http://purl.obolibrary.org/obo/IAO_0000118")
STOP = {"of", "the", "a", "an", "and", "to", "in", "for", "on", "by", "at"}


# ── how a content difference varies, for ordering only ───────────────────────
# Advisory, never a decision: `label_difference` above decides what is in the
# sheet at all. This only tells the curator which rows are mechanical.
def _britam(t: str) -> str:
    t = re.sub(r"\bhaem", "hem", t).replace("oe", "e").replace("ae", "e")
    t = re.sub(r"isation$", "ization", t)
    t = re.sub(r"is(e|ed|ing)$", r"iz\1", t)
    t = re.sub(r"our", "or", t)
    t = re.sub(r"(cent|fib|met|lit|calib|theat)re$", r"\1er", t)
    return t


def _stem(t: str) -> str:
    t = _britam(t.lower())
    if len(t) > 3:
        if t.endswith("ies"):
            t = t[:-3] + "y"
        elif t.endswith(("ses", "xes", "ches", "shes")):
            t = t[:-2]
        elif t.endswith("s") and not t.endswith(("ss", "us", "is")):
            t = t[:-1]
    return re.sub(r"e$", "", t)


def _toks(s: str) -> list[str]:
    return [t for t in (_stem(x) for x in re.split(r"[^A-Za-z0-9]+", s) if x)
            if t and t not in STOP]


def _is_acronym_pair(a: str, b: str) -> bool:
    A = [t for t in re.split(r"[^A-Za-z0-9]+", a) if t]
    B = [t for t in re.split(r"[^A-Za-z0-9]+", b) if t]
    for short, long_ in ((A, B), (B, A)):
        for i, tok in enumerate(short):
            if not (2 <= len(tok) <= 6 and tok.isalpha()):
                continue
            n = len(tok)
            for j in range(len(long_) - n + 1):
                run = long_[j:j + n]
                if all(w[0].lower() == c for w, c in zip(run, tok.lower())):
                    rest_s = [t for t in map(_stem, short[:i] + short[i + 1:]) if t not in STOP]
                    rest_l = [t for t in map(_stem, long_[:j] + long_[j + n:]) if t not in STOP]
                    if sorted(rest_s) == sorted(rest_l):
                        return True
        if len(A) >= 2 and len(B) >= 2 and len(short[0]) <= 2 \
                and short[0][0].lower() == long_[0][0].lower() \
                and [_stem(t) for t in short[1:]] == [_stem(t) for t in long_[1:]]:
            return True
    return False


def variation(a: str, b: str) -> str:
    ta, tb = _toks(a), _toks(b)
    if ta == tb:
        return "spelling"
    if sorted(ta) == sorted(tb):
        return "word order"
    if _is_acronym_pair(a, b):
        return "abbreviation"
    return "real"


def process_direction(a: str, b: str) -> str:
    ap, bp = "process" in a.lower(), "process" in b.lower()
    if bp and not ap:
        return "adds 'process'"
    if ap and not bp:
        return "DROPS 'process'"
    return ""


def main() -> None:
    p = Orchestrator()
    mapping = dict(p.term_mapper.mapping)
    freq = p._collect_store_terms_with_freq()
    adj = p.dm.load_latest_json("mapping_adjudication") or {}

    # every name a curated class answers to, and the graph itself, so a merge
    # the ontologies already relate by an axiom can be shown as such
    from wound_ontology.hierarchies.curated_seed import default_curated_sources
    sources, _ = default_curated_sources()
    G = Graph()
    label2iri: dict[str, set] = {}
    for src in sources:
        for t in parse_graph(src):
            G.add(t)
    individuals = set(G.subjects(RDF.type, OWL.NamedIndividual))
    classes = set(G.subjects(RDF.type, OWL.Class))
    for pred in (RDFS.label, ALT):
        for s, _, o in G.triples((None, pred, None)):
            if s in individuals or s not in classes:
                continue
            label2iri.setdefault(str(o).strip(), set()).add(s)
    labels = set(label2iri)

    def axiom_between(a: str, b: str) -> str:
        ai, bi = label2iri.get(a.strip(), set()), label2iri.get(b.strip(), set())
        if not ai or not bi or ai & bi:
            return ""
        found = []
        for x, y in ((a_, b_) for a_ in ai for b_ in bi):
            for _, pred, obj in G.triples((x, None, None)):
                if obj == y:
                    found.append(str(pred).rsplit("/", 1)[-1].rsplit("#", 1)[-1])
            for _, pred, obj in G.triples((y, None, None)):
                if obj == x:
                    found.append(str(pred).rsplit("/", 1)[-1].rsplit("#", 1)[-1])
            for _, _, node in G.triples((x, RDFS.subClassOf, None)):
                if (node, OWL.someValuesFrom, y) in G or (node, OWL.allValuesFrom, y) in G:
                    found.append(str(G.value(node, OWL.onProperty)).rsplit("/", 1)[-1])
            for _, _, node in G.triples((y, RDFS.subClassOf, None)):
                if (node, OWL.someValuesFrom, x) in G or (node, OWL.allValuesFrom, x) in G:
                    found.append(str(G.value(node, OWL.onProperty)).rsplit("/", 1)[-1])
        return "; ".join(sorted(set(found)))

    rows = []
    for term, canonical in mapping.items():
        if label_difference(term, canonical) != "content":
            continue
        verdict = adj.get(f"{term}\x1f{canonical}", {})
        onto_axiom = axiom_between(term, canonical)
        both = term.strip() in labels and canonical.strip() in labels
        section = ("1 the ontology already relates these" if onto_axiom else
                   "2 onto an existing class" if canonical in labels else
                   "3 store term onto store term")
        rows.append({
            "section": section,
            "term": term,
            "canonical": canonical,
            "term mentions": freq.get(term, 0),
            "canonical mentions": freq.get(canonical, 0),
            "variation": variation(term, canonical),
            "process": process_direction(term, canonical),
            "both sides curated": "yes" if both else "",
            "BFO category side": ("term" if is_category(term) else
                                  "canonical" if is_category(canonical) else ""),
            "ontology axiom": onto_axiom,
            "LLM verdict": verdict.get("verdict", "— never asked —"),
            "LLM reason": verdict.get("reason", ""),
            "keep(y/n)": "",
            "corrected canonical": "",
        })

    order = {"real": 0, "word order": 1, "abbreviation": 2, "spelling": 3}
    rows.sort(key=lambda r: (r["section"],
                             order[r["variation"]],
                             -(r["term mentions"] + r["canonical mentions"])))
    df = pd.DataFrame(rows)
    out = ROOT / "data" / "review" / f"mapping_review_{date.today()}.csv"
    df.to_csv(out, index=False)

    total = len(mapping)
    print(f"[sheet] {total:,} live mapping entries; {len(df):,} differ by a real "
          f"word and are in the sheet. The rest differ only by case, punctuation "
          f"or plural and were accepted without a model call.")
    print(df.groupby(["section", "variation"]).size().to_string())
    print(f"[sheet] never adjudicated: {(df['LLM verdict'] == '— never asked —').sum()}")
    print(f"[sheet] wrote {out}")


if __name__ == "__main__":
    main()
