#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Claude Opus 5.5 reads whether each relation holds for every instance, as a pipeline step.

    python -u scripts/claude_read_universality.py                # dry run: rows, one prompt
    python -u scripts/claude_read_universality.py --test 25      # send the first 25 rows, wait, show
    python -u scripts/claude_read_universality.py --submit --wait
    python -u scripts/claude_read_universality.py --write        # the answers into the term dict
    python -u scripts/claude_read_universality.py --unread ...   # the same, on the relations never read

Rule 66 (2026-10-03): only relations read as true of every instance become
axioms of the WONT addition; rule 88 (2026-10-27): the same reading decides
which attributes the concept lattice lets a class inherit. Both readings were
done by Claude in Claude Code sessions (2026-10-02: 1,007 rows; 2026-10-27: 34)
-- "quick and easy, but not right" (curator, 2026-10-29). Here the same rows are
read again by the pipeline, each with the definitions of its predicate and of
its ends where the ontologies define them, and every row gets an answer.

A row `C | R | T` is read as the axiom it would become, `C SubClassOf (R some T)`,
and answered like every relation in the term dict (rule 89): `yes` (true of
every instance of C) or `no` (true of some instances only, or false, or not a
sound statement); when unsure, `no` -- the criteria of the 2026-10-02 reading.

`--write` puts every answer into the term dict, as a judgement of AGENT on the
relation (`<predicate>: <target>`) of the subject's concept. Nothing of it
lives beside the term dict (curator, 2026-10-30, on "Diese Lesung liegt in
eigenen Ergebnisdateien neben TermMappingAndGate": "das machst du ganz sicher
nicht"). The first run (2026-10-29) answered `all`, `some` or `no` -- answers
of its own -- and wrote them into `result.json` folders that the export and
the concept lattice read; both now read the term dict
(`TermMappingAndGate.read_relations`), and the folders are in
`data/backup/relation_universality_files_2026-10-30/`. The rows to read are the
session readings' row lists (`data/review/_superseded_sessions/*/rows.json`):
the relations that passed the typing check of both ends and the evidence cut.

`--unread` reads the relations that pass the typing check now and were never
read: the check was run again on the categories of 2026-10-30 (curator: "neu
laufen lassen") and writes into the term dict; a relation its `yes` passes in
2 or more abstracts, with no answer of AGENT, is read in its own run folder.
`--run NAME` gives a later such reading a folder of its own
(`..._unread_NAME`): a run folder skips the requests it has sent, by their
ids, so a second reading in the first folder would hand back the first one's
answers to rows it never saw.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

AGENT = "claude-opus-5-5_universality"
REVIEW = ROOT / "data" / "review"
#: session reading -> the folder its new reading goes into
SOURCES = {"relation_universality_2026-10-02": "relation_universality_2026-10-29_export",
           "relation_universality_2026-10-27": "relation_universality_2026-10-29_fca"}
SUPERSEDED = REVIEW / "_superseded_sessions"
RUN_DIR = ROOT / "data" / "llm_runs" / "claude_universality_2026-10-30"   # the term dict's yes / no
UNREAD_DIR = ROOT / "data" / "llm_runs" / "claude_universality_2026-10-30_unread"
ROWS_PER_REQUEST = 25

SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {"row": {"type": "integer"},
                       "verdict": {"type": "string", "enum": ["yes", "no"]},
                       "why": {"type": "string"}},
        "required": ["row", "verdict", "why"],
        "additionalProperties": False}}},
    "required": ["answers"],
    "additionalProperties": False,
}

INSTRUCTIONS = """\
You are deciding which relations extracted from wound-care abstracts may become
axioms of a wound ontology (WONT, built on the disease ontology MILD, on OBO
modules and on BFO 2020).

Each row "C | R | T" is read as the OWL axiom it would become:
    C SubClassOf (R some T)  --  EVERY instance of C stands in R to some T.

Answer every row with one of:
- "yes": the axiom is true of every instance of C ("Burn injury has_quality
  depth": every burn has some depth).
- "no": not an axiom, because it is true of some instances only ("Wound
  has_quality contaminated": there are clean wounds; "X participates_in wound
  healing": not every wound heals or is treated; "amputation risk
  has_realization amputation": not every risk is realized; "area inheres_in
  Wound": not every area is a wound's), or because it is false or not a sound
  statement:
  - a subclass statement misread as part-hood ("Acute wound part_of Wound",
    "Chronic wound has_part Diabetic foot ulcer", "antibiotic has_part meropenem");
  - a self-loop ("Burn injury part_of Burn injury");
  - the wrong bearer ("Burn injury has_quality total body surface area": that is
    the body's quality, not the burn's);
  - a vague or study-local term ("index extremity", "sustained release");
  - ends of the wrong kind for the relation, as its definition states.

Be strict: when unsure, answer "no". Only "yes" may become an axiom. Read the
relation's definition and, where given, the definitions of C and T; the
categories say what kind of thing each end is. Give one sentence of reason for
every row.

RELATIONS USED BELOW
"""


def universality_prompt(rows: list[dict], relations: dict[str, str]) -> str:
    """The prompt for one request: the instructions, the relations' definitions, the rows."""
    used = sorted({r["predicate"] for r in rows})
    out = [INSTRUCTIONS]
    for p in used:
        out.append(f"- {p}: {relations.get(p) or '(no definition found)'}")
    out.append("\nROWS")
    for r in rows:
        out.append(f'ROW {r["row"]}: {r["subject"]} | {r["predicate"]} | {r["value"]}   '
                   f'(stated in {r["abstracts"]} abstracts)')
        for side in ("subject", "value"):
            info = r.get(f"{side}_info") or {}
            what = info.get("category") or "category unknown"
            d = f' Definition: {info["definition"]}' if info.get("definition") else ""
            out.append(f'   {"C" if side == "subject" else "T"} = {r[side]}: {what}.{d}')
    return "\n".join(out)


def _relation_definitions() -> dict[str, str]:
    """predicate (store spelling) -> its definition in the ontologies (RO, BFO, OBI, IAO, MILD)."""
    import rdflib
    from rdflib.namespace import RDFS
    from config.settings import GROUND_TRUTH_TTL, MILD_TTL, MILD_MODULES_DIR
    from wound_ontology.llm.extraction_models import RELATION_IRI
    g = rdflib.Graph()
    g.parse(str(GROUND_TRUTH_TTL), format="turtle")
    g.parse(str(MILD_TTL), format="turtle")
    for m in sorted(Path(MILD_MODULES_DIR).glob("*_module.owl")):
        g.parse(str(m))
    # BFO 2020 writes its definitions as skos:definition or as an elucidation
    # (IAO_0000600), RO and IAO as IAO_0000115
    fields = [rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000115"),
              rdflib.URIRef("http://www.w3.org/2004/02/skos/core#definition"),
              rdflib.URIRef("http://purl.obolibrary.org/obo/IAO_0000600"), RDFS.comment]
    out = {}
    for name, iri in RELATION_IRI.items():
        d = next((g.value(rdflib.URIRef(iri), f) for f in fields if g.value(rdflib.URIRef(iri), f)), None)
        lab = g.value(rdflib.URIRef(iri), RDFS.label)
        out[name.replace(" ", "_")] = (f'"{lab}" ({iri.rsplit("/", 1)[-1]}): {d}' if d else
                                       f'"{lab or name}" ({iri.rsplit("/", 1)[-1]})')
    return out


def unread_rows(p, gt) -> list[dict]:
    """The relations of the store view in >= 2 abstracts that the typing check
    passes (its last word `yes`) and that AGENT never answered."""
    from collections import defaultdict
    from relation_typing_check import AGENT as TYPING, EVIDENCE_CUT
    support, owners_of = defaultdict(set), defaultdict(set)

    def note_kept(key, s, pred, t, owners, targets, value):
        if value == 1.0 and pred != "is_a":
            owners_of[(s, pred, t)].update(owners)
    for key, ents in p.store.view(on_kept=note_kept):
        for s, attrs in ents.items():
            for t, v in attrs.items():
                pr, _, tg = t.partition(":")
                if v == 1.0 and tg.strip() and pr.strip() != "is_a":
                    support[(s, pr.strip(), tg.strip())].add(key)
    cell = lambda o, k: ((gt.records.get(o) or {}).get("relations") or {}).get(k) or []  # noqa: E731
    rows = []
    for (s, pr, tg), keys in sorted(support.items()):
        js = cell(s, f"{pr}: {tg}")
        typed = [j for j in js if j["by"] == TYPING]
        # read already when any cell of the relation carries the reading, under
        # any spelling of either end (2026-10-30: read twice, no and yes)
        read = any(j["by"] == AGENT for c in gt.relation_cells(owners_of[(s, pr, tg)] | {s}, pr, tg)
                   for j in cell(*c))
        if len(keys) < EVIDENCE_CUT or not typed or typed[-1]["verdict"] != "yes" or read:
            continue
        m = re.search(r"subject ok \(([^)]*)\); value ok \(([^)]*)\)", typed[-1]["why"])
        if not m:
            raise RuntimeError(f"{s} | {pr} | {tg}: the typing check's yes names no categories: {typed[-1]['why']!r}")
        rows.append({"id": f"unread-{len(rows) + 1}", "subject": s, "predicate": pr, "value": tg,
                     "abstracts": len(keys), "subject_check": ["ok", m.group(1)], "value_check": ["ok", m.group(2)]})
    return rows


def build_rows(p, gt, unread: bool = False) -> tuple[list[dict], dict[str, str]]:
    from claude_read_placements import _ontology_index
    _, by_label = _ontology_index()
    typings = {}
    for _, ents in p.store.view():
        for name, attrs in ents.items():
            for t in attrs:
                pr, _, tg = t.partition(":")
                if pr.strip() == "is_a":
                    typings.setdefault(name.lower(), set()).add(tg.strip())
    cats = {t.lower(): c["verdict"] for t, c in gt.categories().items()}
    resolve = p.store.resolver(mapped=True)

    def info(name: str, checked: str | None) -> dict:
        onto = by_label.get(name.lower())
        now = resolve(name)[1]
        cat = (onto or {}).get("category") or cats.get(now.lower()) or checked
        if not cat and typings.get(now.lower()):
            ts = typings[now.lower()]
            cat = next(iter(ts)) if len(ts) == 1 else p.reasoner_gate.least_common_category(ts)
        return {"category": cat, "definition": (onto or {}).get("definition", "")}

    if unread:
        return [dict(r, reading="unread", subject_info=info(r["subject"], r["subject_check"][1]),
                     value_info=info(r["value"], r["value_check"][1])) for r in unread_rows(p, gt)], \
            _relation_definitions()
    rows = []
    for src, dst in SOURCES.items():
        for r in json.loads((SUPERSEDED / src / "rows.json").read_text(encoding="utf-8")):
            sc = (r.get("subject_check") or [None, None])[1]
            vc = (r.get("value_check") or [None, None])[1]
            rows.append(dict(r, reading=dst, subject_info=info(r["subject"], sc and sc.lower()),
                             value_info=info(r["value"], vc and vc.lower())))
    return rows, _relation_definitions()


def requests_of(rows, relations):
    from wound_ontology.llm.claude_batch import request_body
    out = []
    for i in range(0, len(rows), ROWS_PER_REQUEST):
        chunk = [dict(r, row=j + 1) for j, r in enumerate(rows[i:i + ROWS_PER_REQUEST])]
        out.append((f"u{i // ROWS_PER_REQUEST:04d}",
                    request_body(universality_prompt(chunk, relations), SCHEMA), chunk))
    return out


def check(answer, chunk) -> list[str]:
    if not answer:
        return ["no answer"]
    got = {a["row"]: a for a in answer.get("answers", [])}
    return [f"row {r['row']} unanswered" for r in chunk if r["row"] not in got]


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.llm.claude_batch import BatchRun
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    unread = "--unread" in argv
    rows, relations = build_rows(p, gt, unread)
    reqs = requests_of(rows, relations)
    print(f"[univ-read] {len(rows)} rows ({dict(Counter(r['reading'] for r in rows))}); {len(reqs)} request(s); "
          f"relations without a definition: {[k for k, v in relations.items() if 'no definition' in v or ':' not in v]}")
    if "--test" in argv and not unread:
        n = int(argv[argv.index("--test") + 1])
        run = BatchRun(RUN_DIR.with_name(RUN_DIR.name + f"_test{n}"))
        test = requests_of(rows[:n], relations)
        run.submit([(c, b) for c, b, _ in test])
        run.wait(poll=20)
        ans = run.answers()
        old = {}
        for src in SOURCES:
            for r in json.loads((SUPERSEDED / src / "result.json").read_text(encoding="utf-8"))["all_rows"]:
                old[r["id"]] = r["universality"]
        for c, _, chunk in test:
            a = ans[c]
            print(f"[univ-read] {c}: {a.error or 'answered'}; usage {a.usage.get('input_tokens')} in / "
                  f"{a.usage.get('output_tokens')} out; problems: {check(a.answer, chunk) or 'none'}")
            got = {x["row"]: x for x in (a.answer or {}).get("answers", [])}
            for r in chunk:
                x = got.get(r["row"], {})
                print(f"   {r['subject']} | {r['predicate']} | {r['value']}: session {old.get(r['id'])} -> "
                      f"{x.get('verdict')}: {x.get('why', '')[:140]}")
        print(f"[univ-read] test cost ${run.cost():.4f}")
        return 0
    if "--submit" in argv or "--wait" in argv or "--write" in argv:
        folder = UNREAD_DIR if unread else RUN_DIR
        if "--run" in argv:
            folder = folder.with_name(f"{folder.name}_{argv[argv.index('--run') + 1]}")
        run = BatchRun(folder)
        if "--submit" in argv:
            print(f"[univ-read] sent {run.submit([(c, b) for c, b, _ in reqs])} request(s)")
        if "--wait" in argv:
            run.wait()
        if "--write" in argv:
            return write(gt, run, reqs)
        return 0
    sample = ROOT / "output" / "claude_universality_prompt_example.txt"
    sample.write_text(universality_prompt([dict(r, row=j + 1) for j, r in enumerate(rows[:ROWS_PER_REQUEST])],
                                          relations), encoding="utf-8")
    print(f"[univ-read] dry run; one prompt in {sample.relative_to(ROOT)}")
    return 0


def write(gt, run, reqs) -> int:
    """Every answer as a judgement of AGENT on the relation of the subject's concept.

    A relation read twice (two rows that land on one relation after renames)
    with different answers gets `no` last: the weaker answer counts, as in
    the 2026-10-02 reading. The `result.json` folders of the first run leave
    `data/review` for `data/backup`."""
    from datetime import datetime
    ans = run.answers()
    problems = {c: (check(ans[c].answer, chunk) if not ans[c].error else [ans[c].error])
                for c, _, chunk in reqs if c in ans}
    problems = {c: b for c, b in problems.items() if b}
    missing = [c for c, _, _ in reqs if c not in ans]
    if problems or missing:
        print(f"[univ-read] *** {len(problems)} request(s) not answered soundly, {len(missing)} not sent; "
              f"nothing written: {list(problems.items())[:5]} ***")
        return 1
    snap = ", ".join(sorted(run.snapshots()))
    norm = lambda p: p.strip().lower().replace(" ", "_")  # noqa: E731
    found: dict[tuple[str, str], list[tuple[str, str, dict]]] = {}
    unplaced = []
    for c, _, chunk in reqs:
        got = {x["row"]: x for x in ans[c].answer["answers"]}
        for r in chunk:
            x = got[r["row"]]
            try:
                subj = gt.concept(gt.resolve(r["subject"]))
                tgt = gt.concept(gt.resolve(r["value"]))
            except RuntimeError as e:
                unplaced.append((r["subject"], r["predicate"], r["value"], str(e)))
                continue
            # the cell the row names as the store view does, else another key the
            # record has for this relation, else predicate: target (2026-10-30:
            # the first key found was a spelling's, `Risk of infection`, which the
            # figure and the search for unread relations did not ask)
            rels = (gt.records.get(subj) or {}).get("relations") or {}
            own = f"{norm(r['predicate'])}: {r['value']}"
            have = own if own in rels else next(
                (k for k in rels if (norm(k.partition(":")[0]), gt.concept(gt.resolve(k.partition(":")[2].strip())))
                 == (norm(r["predicate"]), tgt)), None)
            key = have or f"{norm(r['predicate'])}: {tgt}"
            found.setdefault((subj, key), []).append((x["verdict"], r["id"], x))
    if unplaced:
        for u in unplaced:
            print(f"[univ-read] *** {u[0]} | {u[1]} | {u[2]}: no term ({u[3]}) ***")
        print(f"[univ-read] *** {len(unplaced)} row(s) name no term; nothing written ***")
        return 1
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_universality_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[univ-read] backed up {live.name} -> {backup.relative_to(ROOT)}")
    tally, twice = Counter(), []
    for (subj, key), hits in found.items():
        if len({v for v, _, _ in hits}) > 1:
            twice.append((subj, key, [(v, i) for v, i, _ in hits]))
        for v, i, x in sorted(hits, key=lambda h: h[0] == "no"):       # `no` last: the weaker counts
            gt._put(subj, "relations", gt._j(v, AGENT, f"{x['why']} (row {i}; {snap})"), key)
        tally[sorted(hits, key=lambda h: h[0] == "no")[-1][0]] += 1
    gt._dirty()
    gt.save()
    print(f"[univ-read] written: {sum(len(h) for h in found.values())} answer(s) on {len(found)} relation(s); "
          f"counting: {dict(tally)}; cost ${run.cost():.2f}")
    if twice:
        print(f"[univ-read] {len(twice)} relation(s) read twice with different answers, `no` counts: "
              + "; ".join(f"{s} {k} {h}" for s, k, h in twice[:10]))
    # the first run's result folders: the term dict holds the reading now
    gone = ROOT / "data" / "backup" / "relation_universality_files_2026-10-30"
    gone.mkdir(parents=True, exist_ok=True)
    for dst in SOURCES.values():
        if (REVIEW / dst).exists():
            shutil.move(str(REVIEW / dst), str(gone / dst))
            print(f"[univ-read] {dst} moved to {gone.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
