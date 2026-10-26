"""Write the curator's category rulings into the term dict (rule 57).

    python -u scripts/apply_category_rulings.py [--write]

Two pages, one decision each per term:

  Category Rulings  https://claude.ai/artifact/X2Lk13zk1xXMnstbSp6RDf
                    term by term: a category, out of scope, or "two senses"
                    with a free-text note that is read by TERM_NOTES below
  Signature Words   https://claude.ai/artifact/2HY2b1T2FzQnts16CDcBFX
                    by head word, as `config/category_head_rules.py`

Precedence: a WONT/MILD class keeps the ontology's category; a term ruling
outranks a head rule; a head rule decides only a term whose abstracts disagree
irreconcilably (curator, 2026-09-29: "disputes only").

Dry by default. With `--write` the term dict is backed up, written, reloaded
from disk and every decision checked; then the view is read again and every
ruled term must come out with the category it was given.
"""
from __future__ import annotations

import glob
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

REVIEW = ROOT / "data" / "review"
QUEUE = REVIEW / "typing_queue_2026-09-29.json"
TERM_DEC = REVIEW / "category_rulings_2026-09-29" / "decisions"
SIG = REVIEW / "signature_words_2026-09-29.json"
SIG_DEC = REVIEW / "signature_words_2026-09-29" / "decisions"
REPORT = ROOT / "output" / f"category_rulings_applied_{date.today()}.json"
PAGE = "category rulings page, 2026-09-29"

PREP = ("of", "in", "with", "for", "on", "at", "after", "by", "to", "from")

# "Two senses" answered with a note instead of two sense names. Each note read
# as what it says; a note not in here stops the run (never guessed).
#   category  the category the note names
#   parent    a class the term is a kind of (a curator `narrower` pair: the
#             placement step reads it as a candidate parent)
#   maps_to   the note says the term IS another class (a curator mapping)
#   senses    genuinely two senses, no names given: {category: label}
TERM_NOTES: dict[str, dict] = {
    "postoperative complication": {"category": "material entity", "parent": "complication",
                                   "note": "type it under complication"},
    "dehiscence": {"category": "immaterial entity"},
    "recurrence of ulcer": {"category": "process boundary",
                            "note": "event (read as an instantaneous occurrent)"},
    "wound healing time": {"category": "temporal region"},
    "morbidity": {"category": "material entity", "maps_to": "material disease entity",
                  "note": "morbidity is just another name for disease"},
    "incision": {"category": "immaterial entity"},
    "healed state": {"category": "temporal region"},
    "disease": {"category": "material entity", "maps_to": "material disease entity",
                "note": "'material disease entity' is in MILD: the merge was missing"},
    "antibiotic": {"category": "material entity", "parent": "drug",
                   "note": "subclass of drug"},
    "hospital stay": {"category": "temporal region"},
    "recurrence": {"category": "process boundary",
                   "note": "event rather than a process (read as an instantaneous occurrent)"},
    "biopsy": {"senses": {"process": "biopsy", "material entity": "biopsy specimen"}},
    "operative time": {"category": "temporal region"},
    "therapy": {"category": "information entity", "note": "plan specification"},
    "loss of tissue": {"category": "immaterial entity"},
    "antibiotic use": {"category": "information entity", "note": "plan specification"},
    "time to healing": {"category": "temporal region"},
}


# "Two senses" whose note simply names a category (the second review pass,
# 2026-09-30). Read case-blind; a note not listed here stops the run.
NOTE_CATEGORY: dict[str, str] = {
    "material entity": "material entity",
    "immaterial entity": "immaterial entity",
    "quality": "quality",
    "role": "role",
    "realizable entity": "realizable entity",
    "continuant": "continuant",
    "plan specification": "information entity",
    "plan": "information entity",
    "classification result": "information entity",
    "time interval": "temporal region",
}

# A ruling whose note renames the term (curator, 2026-09-30, on `AKI`: "rename
# to acute kidney injury. no abbreviations ever").
TERM_MAPS: dict[str, str] = {"AKI": "acute kidney injury",
                             # curator, 2026-09-30: "yes rename"
                             "MRI": "magnetic resonance imaging",
                             "SSc": "systemic sclerosis"}


def head(t: str) -> str:
    w = [x for x in re.split(r"[\s-]+", t.lower().strip()) if x]
    for i, x in enumerate(w):
        if x in PREP and i > 0:
            return w[i - 1]
    return w[-1] if w else ""


def _decisions(folder: Path) -> dict[str, dict]:
    return {Path(f).stem: json.load(open(f, encoding="utf-8"))
            for f in glob.glob(str(folder / "*.json"))}


def _category_of(p, typings):
    def category(k):
        c = set(typings.get(k, ()))
        if not c:
            return None, "untyped"
        if len(c) == 1:
            return next(iter(c)), "one"
        lc = p.reasoner_gate.least_common_category(c)
        return (lc, "common") if lc else (None, "irreconcilable")
    return category


def _read_view(p, N):
    typings = defaultdict(set); name_of = {}
    for _, ents in p.store.view():
        for name, attrs in ents.items():
            k = N(name); name_of.setdefault(k, name)
            for t in attrs:
                pr, _, tg = t.partition(":")
                if pr.strip() == "is_a":
                    typings[k].add(tg.strip())
    return typings, name_of


def main(argv: list[str]) -> int:
    from config.category_head_rules import HEAD_CATEGORY, HEAD_OUT
    from wound_ontology.llm.category_vocab import declared_category
    from wound_ontology.llm.extraction_models import CATEGORY_PARENT
    from wound_ontology.mappers.term_mapping_and_gate import TERM_RULING
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import normalize_term as N

    write = "--write" in argv

    # ── the rulings, checked against the pages ──────────────────────────────
    bad = {h: c for h, c in HEAD_CATEGORY.items() if declared_category(c) != c}
    if bad:
        raise SystemExit(f"head rules name no category: {bad}")
    sig_rows = {r["id"]: r["head"] for r in json.load(open(SIG, encoding="utf-8"))["rows"]}
    answered = {sig_rows[i] for i in _decisions(SIG_DEC)}
    missing = answered - set(HEAD_CATEGORY) - set(HEAD_OUT)
    if missing:
        raise SystemExit(f"answered on the page but not in config/category_head_rules.py: {missing}")

    queue = {r["id"]: r for r in json.load(open(QUEUE, encoding="utf-8"))["rows"]}
    term_rulings = {}
    for rid, d in _decisions(TERM_DEC).items():
        term = queue[rid]["term"]
        v = d.get("verdict")
        if v == "__senses" and term not in TERM_NOTES:
            cat = NOTE_CATEGORY.get((d.get("note") or "").strip().lower())
            if cat is not None:
                term_rulings[term] = {"category": cat, "note": d.get("note", "").strip()}
                continue
        if v == "__senses":
            if term not in TERM_NOTES:
                raise SystemExit(f"'two senses' on {term!r} with note {d.get('note')!r}: "
                                 f"add it to TERM_NOTES")
            term_rulings[term] = dict(TERM_NOTES[term], page_note=d.get("note", ""))
        elif v == "__out":
            term_rulings[term] = {"out": True}
        elif declared_category(v) == v:
            term_rulings[term] = {"category": v, "note": d.get("note", "")}
            if term in TERM_MAPS:
                term_rulings[term]["maps_to"] = TERM_MAPS[term]
        else:
            raise SystemExit(f"{term!r}: verdict {v!r} is not a category")

    # ── the terms, before ───────────────────────────────────────────────────
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    onto_cat = {N(k): v for k, v in p.ontology_categories().items()}
    typings, name_of = _read_view(p, N)
    category = _category_of(p, typings)
    in_scope = lambda name: gt.effective_gate_verdict(gt.resolve(name))[0] == "in"

    ruled_keys = {N(t) for t in term_rulings}
    plan = {"term category": [], "term out": [], "term senses": [], "maps": [], "parents": [],
            "head category": [], "head out": [], "curated skipped": []}
    for term, r in sorted(term_rulings.items()):
        if N(term) in onto_cat:
            plan["curated skipped"].append((term, "term ruling", onto_cat[N(term)]))
            continue
        if r.get("out"):
            plan["term out"].append(term); continue
        if r.get("senses"):
            plan["term senses"].append((term, r["senses"])); continue
        plan["term category"].append((term, r["category"], r.get("note") or r.get("page_note", "")))
        if r.get("maps_to"):
            plan["maps"].append((term, r["maps_to"], r.get("note", "")))
        if r.get("parent"):
            plan["parents"].append((term, r["parent"], r.get("note", "")))
    for k, name in sorted(name_of.items()):
        if k in ruled_keys or not in_scope(name):
            continue
        h = head(name)
        if h in HEAD_OUT:
            if k in onto_cat:
                plan["curated skipped"].append((name, f"head out: {h}", onto_cat[k]))
            else:
                plan["head out"].append((name, h))
            continue
        if h not in HEAD_CATEGORY or category(k)[1] != "irreconcilable":
            continue
        if k in onto_cat:
            plan["curated skipped"].append((name, f"head rule: {h}", onto_cat[k])); continue
        plan["head category"].append((name, HEAD_CATEGORY[h], h))

    for key, rows in plan.items():
        print(f"[rulings] {key:16s} {len(rows):5d}  e.g. {rows[:4]}")
    disputed_before = sum(1 for k, n in name_of.items()
                          if category(k)[1] == "irreconcilable" and in_scope(n) and k not in onto_cat)
    print(f"[rulings] in-scope irreconcilable terms now: {disputed_before}")
    if not write:
        print("[rulings] dry run; --write to apply")
        return 0

    # ── write ───────────────────────────────────────────────────────────────
    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_category_rulings_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[rulings] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    outcome = Counter()
    for term, cat, note in plan["term category"]:
        outcome["term " + gt.set_category(term, cat, source=TERM_RULING, note=note)] += 1
    for name, cat, h in plan["head category"]:
        outcome["head " + gt.set_category(name, cat, source=f"head rule: {h}")] += 1
    for term in plan["term out"]:
        gt.gate(term, curator={"verdict": "out", "reason": "", "when": when, "by": PAGE})
    for name, h in plan["head out"]:
        gt.gate(name, curator={"verdict": "out", "reason": f"head word '{h}'", "when": when,
                               "by": "signature words page, 2026-09-29"})
    for term, senses in plan["term senses"]:
        gt.record(term)["senses"] = senses
    for term, target, note in plan["maps"]:
        # the mentions now read as the target: it carries the decision too, or
        # the abstracts' disagreement reappears under its name
        gt.set_category(target, dict((t, c) for t, c, _ in plan["term category"])[term],
                        source=TERM_RULING, note=f"mapped from {term!r}")
        gt.add(term, target, method="curator", override=True)
        gt.judge(term, target, curator={"verdict": "same_class", "reason": note, "when": when})
    for term, parent, note in plan["parents"]:
        gt.judge(term, parent, curator={"verdict": "narrower", "reason": note, "when": when})
    gt._dirty()
    gt.save()
    print(f"[rulings] written: {dict(outcome)}")
    # the blocklist/whitelist files are views of the gate and must not drift

    # ── read back: the file, then the view ──────────────────────────────────
    p2 = Orchestrator()
    gt2 = p2.term_mapper._term_mapping
    cats = {t.lower(): c for t, c in gt2.categories().items()}
    lost = [(t, c) for t, c, _ in plan["term category"] if cats.get(gt2.resolve(t).lower(), {}).get("verdict") != c]
    lost += [(t, c) for t, c, _ in plan["head category"] if cats.get(gt2.resolve(t).lower(), {}).get("verdict") != c]
    lost += [(t, "out") for t in plan["term out"] + [n for n, _ in plan["head out"]]
             if gt2.peek_gate(gt2.resolve(t)).get("curator", {}).get("verdict") != "out"]
    lost += [(t, m) for t, m, _ in plan["maps"] if gt2.data.get(t) != m]
    if lost:
        raise RuntimeError(f"{len(lost)} decision(s) did not land: {lost[:10]}")
    typings2, name_of2 = _read_view(p2, N)
    category2 = _category_of(p2, typings2)

    def chain(c):
        out = set()
        while c:
            out.add(c); c = CATEGORY_PARENT.get(c)
        return out
    wrong = []
    for t, c, *_ in plan["term category"] + plan["head category"]:
        k = N(gt2.data.get(t) or t)
        got = category2(k)[0]
        if k in name_of2 and (got is None or c not in chain(got)):
            wrong.append((t, c, got))
    in2 = lambda name: gt2.effective_gate_verdict(gt2.resolve(name))[0] == "in"
    # a WONT/MILD class is not in dispute: the ontology decides its category
    # (curator, 2026-09-30: "there is no dispute, the ontology decides")
    left = sorted(n for k, n in name_of2.items()
                  if category2(k)[1] == "irreconcilable" and in2(n) and k not in onto_cat)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({"plan": plan, "outcome": dict(outcome), "wrong": wrong,
                                  "disputed before": disputed_before, "disputed after": len(left),
                                  "still disputed": left}, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(f"[rulings] read back: every decision on file; view disagrees on {len(wrong)}: {wrong[:10]}")
    print(f"[rulings] in-scope irreconcilable terms: {disputed_before} -> {len(left)}")
    print(f"[rulings] report {REPORT.relative_to(ROOT)}")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
