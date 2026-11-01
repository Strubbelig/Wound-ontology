#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Claude Opus 5.5 reads every placement proposal, as a pipeline step (2026-10-29).

    python -u scripts/claude_read_placements.py                  # dry run: rows, one prompt, cost
    python -u scripts/claude_read_placements.py --test 20        # send the first 20 rows, wait, show
    python -u scripts/claude_read_placements.py --submit         # send every row (resumable)
    python -u scripts/claude_read_placements.py --wait           # wait for the batches
    python -u scripts/claude_read_placements.py --write          # the answers into the term dict

Curator, 2026-10-29: the placement proposals of DeepSeek (`deepseek-v4-flash_top_15`)
were read row by row by Claude in Claude Code sessions on 2026-10-01 -- "quick and
easy, but not right": a row showed the class labels only, and a row not listed
stood as answered. "Dann bau die pipeline so, dass sie das macht"; all of them
again ("Alles neu"), through OpenRouter like DeepSeek.

Each row now carries the term (category, abstracts), the proposal with DeepSeek's
reason, and every offered class with its category, its parent and its
definition. Claude answers every row: `stands`, `change` (the relation and the
number of the right class), or `none`. A row without an answer is an error.

Rows are the proposals still in the term dict whose term is not out of scope (a
placement of a term out of scope is never built, and an out-of-scope term never
reaches a placement question). The answers are written as judgements of
`claude-opus-5-5_placement`; the session readings (`claude-opus-5-5`) stay in
the history. Where the author has spoken, the author's word still counts.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

AGENT = "claude-opus-5-5_placement"
PROPOSER = "deepseek-v4-flash_top_15"
PROPOSALS = ROOT / "output" / "placement_current_2026-10-01.json"   # the offered classes of each term
OLD_GT = ROOT / "data" / "ground truth" / "ground_truth_final.owl"    # labels as offered on 2026-09-29
OLD_MILD = ROOT.parent / "Disease ontologies" / "mild.ttl"
RUN_DIR = ROOT / "data" / "llm_runs" / "claude_placements_2026-10-29"
ROWS_PER_REQUEST = 20
DEF_CHARS = 220

SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "row": {"type": "integer"},
            "verdict": {"type": "string", "enum": ["stands", "change", "none"]},
            "relation": {"type": "string", "enum": ["is_a", "same", "none"]},
            "class": {"type": "integer"},
            "why": {"type": "string"}},
        "required": ["row", "verdict", "relation", "class", "why"],
        "additionalProperties": False}}},
    "required": ["answers"],
    "additionalProperties": False,
}

INSTRUCTIONS = """\
You are checking where terms extracted from wound-care abstracts belong in a wound
ontology: WONT, built on the disease ontology MILD, on modules of OBO ontologies
(GO, UBERON, CHEBI, OBI, PATO and others) and on BFO 2020.

For every row, a first model was offered up to ten classes of the ontologies and
proposed one of them, either as the term's parent ("is_a": the term names a KIND
of that class) or as the term itself ("same": the term names exactly that class).
Judge the proposal of EVERY row and answer for every row:

- "stands": the proposal is right as it is. Repeat its relation and class number.
- "change": another answer is right. Give the relation ("is_a" or "same") and the
  number of the offered class. It may be the proposed class with the other
  relation. For "is_a", choose the most specific offered class that is still
  correct.
- "none": no offered class is a correct parent and none is the same class. Give
  relation "none" and class 0. A wrong parent is worse than none.

Rules:
- A parent must be the same kind of thing in BFO. A dressing (a material entity)
  is not a process; a procedure is not a plan specification; a quality is not a
  process; a disposition is not a quality; information about a thing is not the
  thing.
- A word shared with a class is not enough: "wound closure" the process is not a
  kind of "closure" the quality.
- "is_a" means every instance of the term is an instance of the class. A term
  that is narrower only sometimes, or is a part, a cause, a measurement or a
  location of the class, is not a kind of it.
- "same" only when the two name exactly the same thing; a term with an extra
  qualifier ("chronic", "infected", "partial-thickness") is a kind of, not the same.
- Read each class's definition. Where a class has none, go by its label and its
  parent. Judge the term as it is used in wound care.
- Give one sentence of reason for every row, naming what decides it.

ROWS
"""


def placement_prompt(rows: list[dict]) -> str:
    """The prompt for one request: the instructions, then the rows."""
    out = [INSTRUCTIONS]
    for r in rows:
        prop = f'{r["relation"]} [{r["proposed"]}]'
        reason = f' -- the first model\'s reason: "{r["reason"]}"' if r.get("reason") else ""
        out.append(f'ROW {r["row"]}: TERM "{r["term"]}" ({r["category"] or "category unknown"}; '
                   f'in {r["abstracts"]} abstract{"s" if r["abstracts"] != 1 else ""})\n'
                   f'PROPOSED: {prop}{reason}\nOFFERED:')
        for i, c in enumerate(r["offered"], 1):
            under = f'; under "{c["parent"]}"' if c.get("parent") else ""
            d = f' Definition: {c["definition"]}' if c.get("definition") else " (no definition)"
            out.append(f'  [{i}] {c["label"]} -- {c["category"] or "category unknown"}{under}.{d}')
        out.append("")
    return "\n".join(out)


def _ontology_index():
    """label (lower) -> class info, from the current files; old labels kept for lookup."""
    import rdflib
    from rdflib.collection import Collection
    from rdflib.namespace import OWL, RDF, RDFS
    from config.settings import GROUND_TRUTH_TTL, MILD_TTL, MILD_MODULES_DIR
    from wound_ontology.llm.extraction_models import CATEGORY_IRI

    cur = rdflib.Graph()
    cur.parse(str(GROUND_TRUTH_TTL), format="turtle")
    cur.parse(str(MILD_TTL), format="turtle")
    full = rdflib.Graph()
    full += cur
    for m in sorted(Path(MILD_MODULES_DIR).glob("*_module.owl")):
        full.parse(str(m))
    old = rdflib.Graph()
    for f in (OLD_GT, OLD_MILD):
        if f.exists():
            old.parse(str(f), format="turtle")
    cat_iris = {rdflib.URIRef(v): k for k, v in CATEGORY_IRI.items()}
    iao_def = rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000115")

    def parents(c):
        for o in full.objects(c, RDFS.subClassOf):
            if isinstance(o, rdflib.URIRef):
                yield o
        for e in full.objects(c, OWL.equivalentClass):
            lst = full.value(e, OWL.intersectionOf)
            if lst is not None:
                yield from (m for m in Collection(full, lst) if isinstance(m, rdflib.URIRef))

    def category(c):
        frontier, seen = [c], {c}
        while frontier:
            nxt = []
            for n in frontier:
                if n in cat_iris:
                    return cat_iris[n]
                for p in sorted(set(parents(n)), key=str):
                    if p not in seen:
                        seen.add(p)
                        nxt.append(p)
            frontier = nxt
        return None

    def label(c):
        return str(cur.value(c, RDFS.label) or full.value(c, RDFS.label) or "")

    by_iri, by_label = {}, {}
    # One label, several classes (WONT's "Pressure ulcer" and HP's): the
    # curator's own class wins, WONT before MILD before the modules. The
    # classes were taken in set order until 2026-10-30, so a label went to
    # whichever came first: HP's Pressure ulcer, a phenotype, stood under
    # "Terminal wound" and made WONT's Pressure ulcer a quality.
    own = {x for x in cur.subjects(RDF.type, OWL.Class) if isinstance(x, rdflib.URIRef)}
    wont = "https://bioportal.bioontology.org/ontologies/WONT/"
    order = lambda x: (0 if x in own and str(x).startswith(wont) else 1 if x in own else 2, str(x))  # noqa: E731
    for s in sorted({s for s in full.subjects(RDF.type, OWL.Class) if isinstance(s, rdflib.URIRef)}, key=order):
        lab = label(s)
        if not lab:
            continue
        par = next((label(p) for p in sorted(set(parents(s)), key=str) if label(p)), "")
        d = str(cur.value(s, iao_def) or full.value(s, iao_def) or "")
        info = {"label": lab, "iri": str(s), "category": category(s), "parent": par,
                "definition": d[:DEF_CHARS] + ("..." if len(d) > DEF_CHARS else "")}
        by_iri[str(s)] = info
        by_label.setdefault(lab.lower(), info)
    for s, o in old.subject_objects(RDFS.label):           # a label offered then, renamed since
        if str(s) in by_iri:
            by_label.setdefault(str(o).lower(), by_iri[str(s)])
    return by_iri, by_label


def build_rows(p, gt) -> tuple[list[dict], Counter]:
    from wound_ontology.mappers.judgements import current
    from wound_ontology.utils.string_utils import normalize_term as N
    by_iri, by_label = _ontology_index()
    offered_of = {N(r["term"]): r for r in json.loads(PROPOSALS.read_text(encoding="utf-8"))["rows"]}
    docs, typings = Counter(), {}
    for _, ents in p.store.view():
        for name, attrs in ents.items():
            docs[name] += 1
            for t in attrs:
                pr, _, tg = t.partition(":")
                if pr.strip() == "is_a":
                    typings.setdefault(name, set()).add(tg.strip())
    cats = gt.categories()
    # a term renamed since 2026-10-01 was offered its classes under a former
    # name, which still points to it
    former: dict[str, list[str]] = {}
    for s in gt.records:
        try:
            now = gt.concept(gt.resolve(s))
        except RuntimeError:
            continue
        if now != s:
            former.setdefault(now, []).append(s)
    tally = Counter()
    rows = []
    for term in sorted(gt.records):
        rec = gt.records[term]
        for q, rel in (("is_a", "is_a"), ("pairs", "same")):
            for key, js in (rec.get(q) or {}).items():
                prop = [j for j in js if j["by"] == PROPOSER and j.get("iri")]
                if not prop:
                    continue
                tally["proposals"] += 1
                concept = gt.concept(gt.resolve(term))
                if gt.gate_verdict(concept)[0] == "out":
                    tally["out of scope, not read"] += 1
                    continue
                iri = prop[-1]["iri"]
                proposed = by_iri.get(iri) or {"label": key, "iri": iri, "category": None, "parent": "",
                                                "definition": ""}
                src = next((offered_of[N(x)] for x in [term, concept, *former.get(concept, []),
                                                       *former.get(term, [])] if N(x) in offered_of), None)
                offered = []
                for lab, _score in (src or {}).get("candidates") or []:
                    info = by_label.get(lab.lower())
                    if info and info["iri"] not in {o["iri"] for o in offered}:
                        offered.append(info)
                if not src:
                    tally["offered classes not found, proposal alone"] += 1
                if proposed["iri"] not in {o["iri"] for o in offered}:
                    offered.insert(0, proposed)
                c = (cats.get(concept) or {}).get("verdict")
                if c is None and typings.get(concept):
                    ts = typings[concept]
                    c = next(iter(ts)) if len(ts) == 1 else p.reasoner_gate.least_common_category(ts)
                rows.append({"term": term, "key": key, "question": q, "relation": rel,
                             "iri": iri, "category": c, "abstracts": docs.get(concept, 0),
                             "reason": (src or {}).get("reason", "") if (src or {}).get("relation") == rel else "",
                             "offered": offered,
                             "proposed": 1 + [o["iri"] for o in offered].index(proposed["iri"]),
                             "now": (current(js) or {}).get("verdict")})
                tally["rows"] += 1
    return rows, tally


def requests_of(rows: list[dict]) -> list[tuple[str, dict, list[dict]]]:
    from wound_ontology.llm.claude_batch import request_body
    out = []
    for i in range(0, len(rows), ROWS_PER_REQUEST):
        chunk = [dict(r, row=j + 1) for j, r in enumerate(rows[i:i + ROWS_PER_REQUEST])]
        out.append((f"p{i // ROWS_PER_REQUEST:05d}", request_body(placement_prompt(chunk), SCHEMA), chunk))
    return out


RETRY_ROWS = 5


def retries_of(reqs, ans) -> list[tuple[str, dict, list[dict]]]:
    """A request the model refused (its safety check: 2026-10-29, two
    `reasoning_extraction` and one `bio`, all three on harmless rows) is sent
    again in requests of RETRY_ROWS rows, so one row cannot take its neighbours
    down with it."""
    from wound_ontology.llm.claude_batch import request_body
    out = []
    for c, _, chunk in reqs:
        a = ans.get(c)
        if a is not None and (a.error or "").startswith("stopped: refusal"):
            for k in range(0, len(chunk), RETRY_ROWS):
                sub = [dict(r, row=j + 1) for j, r in enumerate(chunk[k:k + RETRY_ROWS])]
                out.append((f"{c}_{k // RETRY_ROWS}", request_body(placement_prompt(sub), SCHEMA), sub))
    return out


def _words(text: str) -> set[str]:
    import re
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def slipped(answer: dict, row: dict) -> str | None:
    """A `stands` that names another class number than the proposal's.

    Run of 2026-10-29: 264 of 17,328 rows, 213 of them with the proposal at
    [1]; in 236 the reason names the proposed class and not the other ("Acute-
    phase proteins are proteins" with the number of "Acute wound"). Returns
    "proposal" when the reason names the proposed class and not the class the
    number points to (the verdict stands, the number slipped), "unclear"
    otherwise (the row is not written), None when nothing slipped."""
    if answer["verdict"] != "stands" or (answer["relation"], answer["class"]) == (row["relation"], row["proposed"]):
        return None
    why = answer["why"].lower()
    prop = row["offered"][row["proposed"] - 1]["label"]
    other = row["offered"][answer["class"] - 1]["label"] if 1 <= answer["class"] <= len(row["offered"]) else ""
    names = lambda lab: bool(lab) and (lab.lower() in why or (_words(lab) and _words(lab) <= _words(why)))  # noqa: E731
    return "proposal" if names(prop) and not names(other) else "unclear"


def check(answer: dict | None, chunk: list[dict]) -> list[str]:
    """What is wrong with one request's answer; empty when every row is answered soundly."""
    if not answer:
        return ["no answer"]
    got = {a["row"]: a for a in answer.get("answers", [])}
    bad = [f"row {r['row']} unanswered" for r in chunk if r["row"] not in got]
    for r in chunk:
        a = got.get(r["row"])
        if not a:
            continue
        n = len(r["offered"])
        if a["verdict"] == "none" and (a["relation"], a["class"]) != ("none", 0):
            bad.append(f"row {r['row']}: none with {a['relation']} {a['class']}")
        if a["verdict"] in ("stands", "change") and not (1 <= a["class"] <= n and a["relation"] in ("is_a", "same")):
            bad.append(f"row {r['row']}: {a['verdict']} names {a['relation']} [{a['class']}] of {n}")
        # `stands` with another class number than the proposal's: the verdict
        # and the reason decide, the number slipped (write(): `slipped`)
        if a["verdict"] == "change" and (a["relation"], a["class"]) == (r["relation"], r["proposed"]):
            bad.append(f"row {r['row']}: change to the proposal itself")
    return bad


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.llm.claude_batch import BatchRun
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    rows, tally = build_rows(p, gt)
    reqs = requests_of(rows)
    print(f"[place-read] {dict(tally)}; {len(reqs)} request(s) of up to {ROWS_PER_REQUEST} rows")

    if "--test" in argv:
        n = int(argv[argv.index("--test") + 1])
        run = BatchRun(RUN_DIR.with_name(RUN_DIR.name + f"_test{n}"))
        test = requests_of(rows[:n])
        run.submit([(c, b) for c, b, _ in test])
        run.wait(poll=20)
        ans = run.answers()
        for c, _, chunk in test:
            a = ans[c]
            print(f"[place-read] {c}: {a.error or 'answered'}; usage {a.usage.get('input_tokens')} in / "
                  f"{a.usage.get('output_tokens')} out ({(a.usage.get('output_tokens_details') or {}).get('thinking_tokens')} thinking); "
                  f"problems: {check(a.answer, chunk) or 'none'}")
            got = {x["row"]: x for x in (a.answer or {}).get("answers", [])}
            for r in chunk:
                x = got.get(r["row"], {})
                tgt = r["offered"][x["class"] - 1]["label"] if x.get("class") else "-"
                print(f"   {r['term']!r} {r['relation']} {r['offered'][r['proposed'] - 1]['label']!r} (now: {r['now']}) "
                      f"-> {x.get('verdict')} {x.get('relation')} {tgt!r}: {x.get('why', '')[:150]}")
        print(f"[place-read] test cost ${run.cost():.4f}; snapshot {run.snapshots()}")
        return 0

    if "--finish" in argv:
        return finish(gt, rows)
    if any(a in argv for a in ("--submit", "--retry", "--reask", "--wait", "--write")):
        run = BatchRun(RUN_DIR)
        if "--submit" in argv:
            print(f"[place-read] sent {run.submit([(c, b) for c, b, _ in reqs])} request(s)")
        if "--retry" in argv:
            again = retries_of(reqs, run.answers())
            print(f"[place-read] refused request(s) sent again in {len(again)} smaller one(s): "
                  f"{run.submit([(c, b) for c, b, _ in again])} sent")
        if "--reask" in argv:
            _, open_ = settle(reqs, run.answers())
            again = reasks_of(list(open_.values()))
            print(f"[place-read] {len(open_)} unsettled row(s) asked again in {len(again)} request(s): "
                  f"{run.submit([(c, b) for c, b, _ in again])} sent")
        if "--wait" in argv:
            run.wait()
        if "--write" in argv:
            return write(gt, run, reqs)
        return 0

    sample = ROOT / "output" / "claude_placement_prompt_example.txt"
    sample.write_text(placement_prompt([dict(r, row=j + 1) for j, r in enumerate(rows[:ROWS_PER_REQUEST])]), encoding="utf-8")
    chars = sum(len(json.dumps(b)) for _, b, _ in reqs)
    print(f"[place-read] dry run; one prompt in {sample.relative_to(ROOT)}; ~{chars / 4 / 1e6:.1f} M input tokens")
    return 0


def key_for(gt, term: str, question: str, cls: dict) -> str:
    """The key `cls` already has on the record (the same IRI, any spelling), else its label.

    Written first under the ontology's label, Claude's `immaterial anatomical
    entity` stood beside the author's `Immaterial anatomical entity` -- the same
    class, UBERON_0000466 -- and the author's later `no` on one key did not
    reach the other (2026-10-29, three records)."""
    for k, js in ((gt.records.get(term) or {}).get(question) or {}).items():
        if any(j.get("iri") == cls["iri"] for j in js):
            return k
    return cls["label"]


def answer_verdicts(r: dict, x: dict, verdict: str) -> list[tuple[str, str, dict]]:
    """`(question, verdict, class)` for one settled answer, in the term dict's own answers.

    The proposal's cell gets yes / same_class on `stands`, else no / a pair
    answer; a `change` also gets yes / same_class on the class chosen. The
    proposal "same as X" answered "a kind of X" is `narrower` on the pair, not
    `different` (23 written so on 2026-10-29, mapped on 2026-10-30)."""
    own = {"iri": r["iri"], "label": r["key"]}
    if verdict == "stands":
        return [(r["question"], "yes" if r["question"] == "is_a" else "same_class", own)]
    chosen = r["offered"][x["class"] - 1] if verdict == "change" else None
    if r["question"] == "is_a":
        out = [("is_a", "no", own)]
    else:
        kind_of_it = chosen is not None and x["relation"] == "is_a" and chosen["iri"] == r["iri"]
        out = [("pairs", "narrower" if kind_of_it else "different", own)]
    if chosen is not None:
        out.append(("is_a", "yes", chosen) if x["relation"] == "is_a" else ("pairs", "same_class", chosen))
    return out


def put_answer(gt, r: dict, x: dict, verdict: str, why: str) -> None:
    for i, (q, v, cls) in enumerate(answer_verdicts(r, x, verdict)):
        key = r["key"] if i == 0 else key_for(gt, r["term"], q, cls)
        gt._put(r["term"], q, gt._j(v, AGENT, why, iri=cls["iri"]), key)


def judge_row(x: dict | None, r: dict) -> tuple[str | None, str | None]:
    """`(verdict to write, note)` for one row's answer, or `(None, why not)`.

    The fields of an answer can contradict each other (run of 2026-10-29):
    `stands` with another class's number (see `slipped`), `change` with no
    class (relation "none", class 0: read as `none`, which both fields say),
    `change` to the proposal itself, a row left out of the answer. A row whose
    answer does not settle what Claude meant is not written."""
    if x is None:
        return None, "unanswered"
    n, v, rel, k = len(r["offered"]), x["verdict"], x["relation"], x["class"]
    if v == "none" or (v == "change" and (rel, k) == ("none", 0)):
        if (rel, k) != ("none", 0):
            return None, f"none with {rel} [{k}]"
        return "none", (None if v == "none" else "the answer said change and named no class; read as none")
    if v == "stands":
        if (rel, k) == (r["relation"], r["proposed"]):
            return "stands", None
        if slipped(x, r) == "proposal":
            return "stands", f"the answer gave class number {k}; verdict and reason confirm the proposal"
        return None, f"stands with class [{k}], the reason does not settle which"
    if not (1 <= k <= n and rel in ("is_a", "same")):
        return None, f"change names {rel} [{k}] of {n}"
    if (rel, k) == (r["relation"], r["proposed"]):
        return None, "change to the proposal itself"
    return "change", None


REASK_ROWS = 5


def settle(reqs, ans):
    """`{row id: (row, answer, verdict, note)}` for every row an answer settles,
    and the rows none does, with why: the first answer, then the answer of a
    refused request sent again in smaller ones, then the answer of a row asked
    again (`reasks_of`)."""
    rid = lambda r: (r["term"], r["question"], r["key"])  # noqa: E731
    done, open_ = {}, {}

    def take(c, chunk):
        a = ans.get(c)
        got = {x["row"]: x for x in ((a.answer or {}) if a else {}).get("answers", [])} if a and a.answer else {}
        for r in chunk:
            if rid(r) in done:
                continue
            if a is None:
                open_.setdefault(rid(r), (r, "not sent"))
                continue
            if a.error:
                open_[rid(r)] = (r, a.error)
                continue
            verdict, note = judge_row(got.get(r["row"]), r)
            if verdict:
                done[rid(r)] = (r, got[r["row"]], verdict, note)
                open_.pop(rid(r), None)
            else:
                open_[rid(r)] = (r, note)

    for c, _, chunk in reqs:
        take(c, chunk)
    for c, _, chunk in retries_of(reqs, ans):
        take(c, chunk)
    for c, _, chunk in reasks_of(list(open_.values())):
        if c in ans:
            take(c, chunk)
    return done, open_


def reasks_of(open_rows) -> list[tuple[str, dict, list[dict]]]:
    """The rows no answer settled, asked again in requests of REASK_ROWS rows.
    Ids are stable for the same rows (`x` + the rows' terms hashed)."""
    import hashlib
    from wound_ontology.llm.claude_batch import request_body
    rows = sorted((r for r, _ in open_rows), key=lambda r: (r["term"], r["question"], r["key"]))
    out = []
    for k in range(0, len(rows), REASK_ROWS):
        sub = [dict(r, row=j + 1) for j, r in enumerate(rows[k:k + REASK_ROWS])]
        h = hashlib.sha1("|".join(f"{r['term']}|{r['key']}" for r in sub).encode()).hexdigest()[:10]
        out.append((f"x{h}", request_body(placement_prompt(sub), SCHEMA), sub))
    return out


FINISH_DIR = RUN_DIR.with_name(RUN_DIR.name + "_finish")


def finish(gt, rows) -> int:
    """The rows no answer settled in the main run, asked again and written alone.

    The first re-ask (2026-10-29) found its answers again by a hash of each
    group of five rows; the groups depend on which rows are open, which had
    changed by the time of writing, so 19 of 22 answers were not found again
    and their rows stayed unwritten. Here a row is open when its proposal
    carries no judgement of AGENT yet, the rows are kept beside the request
    (`<run>/rows.json`), and the answers are matched through them."""
    from wound_ontology.llm.claude_batch import BatchRun, request_body
    run = BatchRun(FINISH_DIR)
    keep = FINISH_DIR / "rows.json"
    if keep.exists():
        groups = json.loads(keep.read_text(encoding="utf-8"))
    else:
        open_rows = [r for r in rows
                     if not any(j["by"] == AGENT for j in
                                (gt.records[r["term"]].get(r["question"]) or {}).get(r["key"]) or [])]
        groups = {f"f{k // REASK_ROWS:04d}": [dict(r, row=j + 1) for j, r in enumerate(open_rows[k:k + REASK_ROWS])]
                  for k in range(0, len(open_rows), REASK_ROWS)}
        keep.write_text(json.dumps(groups, ensure_ascii=False), encoding="utf-8")
        print(f"[place-read] {len(open_rows)} row(s) without a reading of {AGENT}, in {len(groups)} request(s)")
    run.submit([(c, request_body(placement_prompt(g), SCHEMA)) for c, g in groups.items()])
    run.wait(poll=20)
    ans = run.answers()
    snap = ", ".join(sorted(run.snapshots()))
    tally, left = Counter(), []
    for c, g in groups.items():
        a = ans.get(c)
        got = {x["row"]: x for x in (a.answer or {}).get("answers", [])} if a and a.answer else {}
        for r in g:
            verdict, note = judge_row(got.get(r["row"]), r) if a and not a.error else (None, a.error if a else "not sent")
            if not verdict:
                left.append((r["term"], r["key"], note))
                continue
            x = got[r["row"]]
            put_answer(gt, r, x, verdict, f"{x['why']} ({snap})" + (f" [{note}]" if note else ""))
            tally[verdict] += 1
    if tally:
        gt._dirty()
        gt.save()
    print(f"[place-read] finish: written {dict(tally)}; cost ${run.cost():.2f}")
    if left:
        print(f"[place-read] *** {len(left)} row(s) still unsettled; not written, their earlier judgements stand: ***")
        for t, k, n in left:
            print(f"[place-read]     {t} is_a {k}: {n}")
    return 0


def write(gt, run, reqs) -> int:
    """Each settled answer as a judgement of AGENT on the proposal, and on the class chosen instead."""
    import shutil
    ans = run.answers()
    if any(c not in ans for c, _, _ in reqs):
        print(f"[place-read] *** {sum(c not in ans for c, _, _ in reqs)} request(s) never sent; nothing written ***")
        return 1
    done, open_ = settle(reqs, ans)
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_claude_placements_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[place-read] backed up {live.name} -> {backup.relative_to(ROOT)}")
    snap = ", ".join(sorted(run.snapshots()))
    tally = Counter()
    for r, x, verdict, note in done.values():
        put_answer(gt, r, x, verdict, f"{x['why']} ({snap})" + (f" [{note}]" if note else ""))
        tally[" ".join((r["relation"], verdict) + ((x["relation"],) if verdict == "change" else ()))] += 1
        if note:
            tally["read past a slip in the answer"] += 1
    gt._dirty()
    gt.save()
    print(f"[place-read] written {len(done)} row(s): {dict(sorted(tally.items()))}; cost ${run.cost():.2f}")
    if open_:
        why = Counter(n.split(":")[0] if n.startswith("stopped") else n.split(",")[0] for _, n in open_.values())
        print(f"[place-read] *** {len(open_)} row(s) no answer settled; not written, their earlier judgements "
              f"stand: {dict(why)} ***")
        for r, n in list(open_.values())[:40]:
            print(f"[place-read]     {r['term']} {r['relation']} {r['key']}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
