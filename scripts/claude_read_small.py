#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Claude Opus 5.5 reads the two small things it read by hand, as pipeline steps (2026-10-29).

    python -u scripts/claude_read_small.py                       # dry run
    python -u scripts/claude_read_small.py --test                # one request of each, wait, show
    python -u scripts/claude_read_small.py --submit --wait
    python -u scripts/claude_read_small.py --write

1. Restatements (`claude-opus-5-5_restatement`). DeepSeek's control asked of
   3,186 placements whether the term only restates its class ("C" under "carbon
   atom"); Claude read its `same` rows on 2026-10-02 and listed the exceptions,
   every unlisted row mapped onto its class. Here every `same` and `unclear`
   row is read, each with the class's definition, and answered like every
   pair in the term dict: `same`, `narrower`, `broader` or `different`
   (`PAIR_VERDICTS`). The first run (2026-10-29) answered `same`, `narrower`
   or `neither` -- answers of its own, which the author refused on 2026-10-30
   ("halt dich einfach an die regeln ... same, broader, narrower oder
   different wie alle"); it was asked again (`RESTATE_RUN_DIR`).
2. The author's clash decisions carried to statements of the same type
   (`claude-opus-5-5_same_type`). On 2026-10-10 and 10-12 Claude extended a
   decision of the author's to 22 further statements "of the same type". Here
   each is read against the author's decision as written, and answered
   `applies` or `does_not_apply`.

Curator, 2026-10-29: the session readings were "quick and easy, but not right".
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

REVIEW = ROOT / "data" / "review"
RESTATE = REVIEW / "placement_restatement_2026-10-02.json"
CLASH_FILES = ["relation_clash_decisions_2026-10-10.json", "relation_clash_decisions_2026-10-10b.json",
               "relation_clash_decisions_2026-10-10c.json", "axiom_note_decisions_2026-10-12.json"]
RUN_DIR = ROOT / "data" / "llm_runs" / "claude_small_2026-10-29"
RESTATE_RUN_DIR = ROOT / "data" / "llm_runs" / "claude_restatement_2026-10-30"   # the four pair answers
A_RESTATE, A_SAME_TYPE = "claude-opus-5-5_restatement", "claude-opus-5-5_same_type"
ROWS = 25


def _schema(enum):
    return {"type": "object",
            "properties": {"answers": {"type": "array", "items": {
                "type": "object",
                "properties": {"row": {"type": "integer"}, "verdict": {"type": "string", "enum": enum},
                               "why": {"type": "string"}},
                "required": ["row", "verdict", "why"], "additionalProperties": False}}},
            "required": ["answers"], "additionalProperties": False}


RESTATE_SCHEMA = _schema(["same", "narrower", "broader", "different"])
#: a restatement answer as the pair verdict it is, and what it says of the placement
PAIR_OF = {"same": "same_class", "narrower": "narrower", "broader": "broader", "different": "different"}
SAME_TYPE_SCHEMA = _schema(["applies", "does_not_apply"])

RESTATE_INSTRUCTIONS = """\
Terms extracted from wound-care abstracts were placed under classes of a wound
ontology (WONT, built on MILD, OBO modules and BFO 2020) as a KIND of the class
(is_a). A check then asked whether a term is in fact only a restatement of its
class: another name for exactly the same thing ("C" placed under "carbon atom").

Decide for EVERY row how the TERM stands to the CLASS:
- "same": the term names exactly the class; it is another name for it
  (spelling, plural, abbreviation, word order, a synonym).
- "narrower": the term names a genuine kind of the class: it adds a qualifier,
  or names a particular member, scale, grade, organism or substance
  ("herpes simplex virus" under "Viruses", "frostbite injury" under "Thermal wound").
- "broader": the class is a kind of what the term names; the term is the more
  general of the two ("wound" placed under "chronic wound").
- "different": none of these: a part, a measure, a process or a property
  related to the class, or another thing.

Read the class's definition where given. Give one sentence of reason for every row.

ROWS
"""

SAME_TYPE_INSTRUCTIONS = """\
The author of a wound ontology decided about statements extracted from wound-care
abstracts that contradicted the ontology. Each row below is another statement that
an earlier reading took to be "of the same type" as one the author decided, and so
held out of the ontology too. The author's decision is quoted with each row.

Decide for EVERY row whether the author's decision applies to this statement in
the same way:
- "applies": the same reason holds for this statement, so it is held out too.
- "does_not_apply": the reason does not carry over; the statement differs in what
  matters (another bearer, another kind of target, another sense).

Read the author's words closely; do not extend them beyond what they say. Give one
sentence of reason for every row.

ROWS
"""


def restate_prompt(rows):
    out = [RESTATE_INSTRUCTIONS]
    for r in rows:
        d = f' Definition: {r["definition"]}' if r.get("definition") else " (no definition)"
        out.append(f'ROW {r["row"]}: TERM "{r["term"]}" (in {r["abstracts"]} abstracts) placed under CLASS '
                   f'"{r["class"]}" ({r["class_category"] or "category unknown"}).{d}\n'
                   f'   The check said "{r["answer"]}": {r["reason"]}')
    return "\n".join(out)


def same_type_prompt(rows):
    out = [SAME_TYPE_INSTRUCTIONS]
    for r in rows:
        out.append(f'ROW {r["row"]}: STATEMENT "{r["subject"]} {r["predicate"]} {r["object"]}"\n'
                   f'   The earlier reading: {r["why"]}')
    return "\n".join(out)


def build(p, gt):
    from claude_read_placements import _ontology_index
    from wound_ontology.utils.string_utils import normalize_term as N
    _, by_label = _ontology_index()
    former: dict[str, list[str]] = {}
    for s in gt.records:
        try:
            now = gt.concept(gt.resolve(s))
        except RuntimeError:
            continue
        former.setdefault(now, []).append(s)

    by_key: dict[str, list[str]] = {}
    for s in gt.records:
        by_key.setdefault(N(s), []).append(s)
    restate, missing = [], []
    for x in json.loads(RESTATE.read_text(encoding="utf-8"))["rows"]:
        if x["answer"] not in ("same", "unclear"):
            continue
        info = by_label.get(x["class"].lower()) or {}
        cands = []
        for t in [x["term"], *by_key.get(N(x["term"]), [])]:   # the spelling may differ in case or form
            if t in gt.records:
                c = gt.concept(gt.resolve(t))
                cands += [t, c, *former.get(c, [])]
        holder = next(((t, k) for t in cands for k in (gt.records.get(t, {}).get("is_a") or {})
                       if k.lower() == x["class"].lower()), None)
        if holder is None:
            missing.append((x["term"], x["class"]))
            continue
        # the class the placement already names (the author's IRI, else the
        # proposer's), never one found again by label: a label can name two
        # classes (WONT's and HP's Pressure ulcer, 2026-10-30)
        js = gt.records[holder[0]]["is_a"][holder[1]]
        iri = next((j["iri"] for j in reversed(js) if j.get("iri") and j["by"] == "author"), None) \
            or next((j["iri"] for j in reversed(js) if j.get("iri")), None) or info.get("iri")
        restate.append(dict(x, record=holder[0], key=holder[1], iri=iri,
                            definition=info.get("definition", ""), class_category=info.get("category")))

    clash = {}
    for f in CLASH_FILES:
        for e in json.loads((REVIEW / f).read_text(encoding="utf-8")).get("reject", []):
            if e.get("by") == "same type":
                clash[(N(e["subject"]), N(e["predicate"].replace("_", " ")), N(e["object"]))] = dict(e, file=f)
    same_type, unmatched = [], []
    for t, rec in gt.records.items():
        for k, js in (rec.get("relations") or {}).items():
            if not any(j["by"] == "claude-opus-5-5" for j in js):
                continue
            pred, _, obj = k.partition(":")
            e = clash.get((N(t), N(pred.replace("_", " ")), N(obj)))
            if e is None:
                unmatched.append((t, k))
                continue
            same_type.append({"record": t, "key": k, "subject": t, "predicate": pred.strip().replace("_", " "),
                              "object": obj.strip(), "why": e["why"], "file": e["file"]})
    return restate, missing, same_type, unmatched


def requests_of(rows, prefix, prompt, schema):
    from wound_ontology.llm.claude_batch import request_body
    out = []
    for i in range(0, len(rows), ROWS):
        chunk = [dict(r, row=j + 1) for j, r in enumerate(rows[i:i + ROWS])]
        out.append((f"{prefix}{i // ROWS:03d}", request_body(prompt(chunk), schema), chunk))
    return out


def main(argv):
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.llm.claude_batch import BatchRun
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    restate, missing, same_type, unmatched = build(p, gt)
    reqs = (requests_of(restate, "r", restate_prompt, RESTATE_SCHEMA)
            + requests_of(same_type, "s", same_type_prompt, SAME_TYPE_SCHEMA))
    print(f"[small-read] restatement rows {len(restate)} (not found in the term dict: {len(missing)} {missing[:4]}); "
          f"same-type statements {len(same_type)} (without their decision: {unmatched}); {len(reqs)} request(s)")
    if "--test" in argv:
        run = BatchRun(RUN_DIR.with_name(RUN_DIR.name + "_test"))
        test = [next(q for q in reqs if q[0].startswith("r")), next(q for q in reqs if q[0].startswith("s"))]
        run.submit([(c, b) for c, b, _ in test])
        run.wait(poll=20)
        ans = run.answers()
        for c, _, chunk in test:
            a = ans[c]
            got = {x["row"]: x for x in (a.answer or {}).get("answers", [])}
            print(f"[small-read] {c}: {a.error or 'answered'}; unanswered: {[r['row'] for r in chunk if r['row'] not in got]}")
            for r in chunk[:25]:
                x = got.get(r["row"], {})
                what = f"{r['term']} < {r['class']}" if c.startswith("r") else f"{r['subject']} {r['predicate']} {r['object']}"
                print(f"   {what}: {x.get('verdict')}: {x.get('why', '')[:140]}")
        print(f"[small-read] test cost ${run.cost():.4f}")
        return 0
    if any(a in argv for a in ("--submit", "--wait", "--write")):
        # 2026-10-30: the restatements asked again with the four pair answers;
        # the same-type reading of 2026-10-29 stands as written (`--same-type`
        # works on it alone)
        same = "--same-type" in argv
        run = BatchRun(RUN_DIR if same else RESTATE_RUN_DIR)
        reqs = [q for q in reqs if q[0].startswith("s" if same else "r")]
        if "--submit" in argv:
            print(f"[small-read] sent {run.submit([(c, b) for c, b, _ in reqs])} request(s)")
        if "--wait" in argv:
            run.wait()
        if "--write" in argv:
            return write(gt, run, reqs)
        return 0
    (ROOT / "output" / "claude_restatement_prompt_example.txt").write_text(reqs[0][1]["messages"][0]["content"], encoding="utf-8")
    print("[small-read] dry run; one prompt in output/claude_restatement_prompt_example.txt")
    return 0


def write(gt, run, reqs) -> int:
    ans = run.answers()
    bad = {}
    for c, _, chunk in reqs:
        a = ans.get(c)
        got = {x["row"] for x in ((a.answer or {}) if a else {}).get("answers", [])}
        if not a or a.error or any(r["row"] not in got for r in chunk):
            bad[c] = a.error if a else "not sent"
    if bad:
        print(f"[small-read] *** {len(bad)} request(s) not answered soundly; nothing written: {list(bad.items())[:5]} ***")
        return 1
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_claude_small_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    snap = ", ".join(sorted(run.snapshots()))
    tally = Counter()
    for c, _, chunk in reqs:
        got = {x["row"]: x for x in ans[c].answer["answers"]}
        for r in chunk:
            x = got[r["row"]]
            why = f"{x['why']} ({snap})"
            if c.startswith("r"):
                # the answer is the pair verdict; the placement holds only for `narrower`
                gt._put(r["record"], "pairs", gt._j(PAIR_OF[x["verdict"]], A_RESTATE, why, iri=r["iri"]), r["key"])
                gt._put(r["record"], "is_a", gt._j("yes" if x["verdict"] == "narrower" else "no", A_RESTATE,
                                                   why if x["verdict"] == "narrower"
                                                   else f"{x['verdict']}, not a kind of it: {why}", iri=r["iri"]), r["key"])
                tally[f"restatement {x['verdict']}"] += 1
            else:
                v = "no" if x["verdict"] == "applies" else "yes"
                gt._put(r["record"], "relations", gt._j(v, A_SAME_TYPE,
                                                        f"the author's decision ({r['file']}) "
                                                        f"{'applies' if v == 'no' else 'does not carry over'}: {why}"),
                        r["key"])
                tally[f"same type {x['verdict']}"] += 1
    gt._dirty()
    gt.save()
    print(f"[small-read] backed up {live.name} -> {backup.relative_to(ROOT)}; written {dict(tally)}; cost ${run.cost():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
