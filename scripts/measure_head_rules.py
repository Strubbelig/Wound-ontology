"""Measure what the curator's head-word category rulings would change. Read-only.

    python -u scripts/measure_head_rules.py

Curator, 2026-09-29: "whenever there is injury as a last word, that is a
material entity. Whenever there is inflammation or infection, that is a
process. make a list of signature words and ask me that first." The Signature
Words page (82 head words) holds the answers; the Category Rulings page holds
term-by-term answers, which outrank a head-word rule.

Nothing is written but a report. For every in-scope term whose head word has a
ruling, the term's category today (one category across its abstracts, the
least common BFO category of several, or none when they are irreconcilable) is
compared with the ruling:

  settles   the abstracts disagree irreconcilably; the rule decides
  agrees    today's category is the ruled one, or on its branch of BFO
  flips     today's category is consistent but on another branch: the rule
            would overturn what every abstract said
  curated   the term is a WONT/MILD class label; the ontology's category holds
  by term   a term-level ruling exists and outranks the head rule

The head word is the word before the first preposition, else the last word --
the definition the Signature Words page was built with.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

REVIEW = ROOT / "data" / "review"
SIG = REVIEW / "signature_words_2026-09-29.json"
SIG_DEC = REVIEW / "signature_words_2026-09-29" / "decisions"
CAT = REVIEW / "typing_queue_2026-09-29.json"
CAT_DEC = REVIEW / "category_rulings_2026-09-29" / "decisions"
OUT = ROOT / "output" / "head_rules_measure_2026-09-29.json"

PREP = ("of", "in", "with", "for", "on", "at", "after", "by", "to", "from")

# Free-text answers on the Signature Words page, read as categories. A note
# that is not listed here is reported, never guessed.
NOTE_CATEGORY = {"plan specification": "information entity",
                 "plan specifation": "information entity"}
# BFO_0000031 is generically dependent continuant; the pipeline calls it
# "information entity" (extraction_models.CATEGORY_IRI).
ALIAS = {"generically dependent continuant": "information entity"}


def head(t: str) -> str:
    w = [x for x in re.split(r"[\s-]+", t.lower().strip()) if x]
    for i, x in enumerate(w):
        if x in PREP and i > 0:
            return w[i - 1]
    return w[-1] if w else ""


def _decisions(folder: Path) -> dict[str, dict]:
    return {Path(f).stem: json.load(open(f, encoding="utf-8"))
            for f in glob.glob(str(folder / "*.json"))}


def main() -> int:
    from wound_ontology.llm.extraction_models import CATEGORY_IRI, CATEGORY_PARENT
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import normalize_term as N

    # ── the rulings ─────────────────────────────────────────────────────────
    sig_rows = {r["id"]: r for r in json.load(open(SIG, encoding="utf-8"))["rows"]}
    rules, unread = {}, []
    for rid, d in _decisions(SIG_DEC).items():
        h = sig_rows[rid]["head"]
        v = d.get("verdict")
        if v == "__note_only":
            v = NOTE_CATEGORY.get((d.get("note") or "").strip().lower())
            if v is None:
                unread.append((h, d.get("note"))); continue
        v = ALIAS.get(v, v)
        if v in ("__none",):
            continue
        if v != "__out" and v not in CATEGORY_IRI:
            unread.append((h, v)); continue
        rules[h] = v
    undecided = sorted(r["head"] for rid, r in sig_rows.items() if rid not in _decisions(SIG_DEC))

    cat_rows = {r["id"]: r for r in json.load(open(CAT, encoding="utf-8"))["rows"]}
    by_term = {}
    for rid, d in _decisions(CAT_DEC).items():
        by_term[N(cat_rows[rid]["term"])] = d.get("verdict")

    # ── the terms, as split_extension sees them ─────────────────────────────
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    onto_cat = {N(k): v for k, v in p.ontology_categories().items()}
    docs: Counter = Counter(); typings = defaultdict(Counter); name_of = {}
    for _, ents in p.store.view():
        for name, attrs in ents.items():
            k = N(name); docs[k] += 1; name_of.setdefault(k, name)
            for t in attrs:
                pr, _, tg = t.partition(":")
                if pr.strip() == "is_a":
                    typings[k][tg.strip()] += 1

    def anc(c):
        out = set()
        while c:
            out.add(c); c = CATEGORY_PARENT.get(c)
        return out

    def category(k):
        c = set(typings.get(k, ()))
        if not c:
            return None, "untyped"
        if len(c) == 1:
            return next(iter(c)), "one"
        lc = p.reasoner_gate.least_common_category(c)
        return (lc, "common") if lc else (None, "irreconcilable")

    per = defaultdict(lambda: defaultdict(list))
    for k, name in name_of.items():
        h = head(name)
        if h not in rules:
            continue
        if gt.effective_gate_verdict(gt.resolve(name))[0] != "in":
            continue
        R = rules[h]
        cat, how = category(k)
        if k in onto_cat:
            bucket = "curated"
        elif k in by_term:
            bucket = "by term"
        elif R == "__out":
            bucket = "out"
        elif how == "untyped":
            bucket = "untyped"
        elif how == "irreconcilable":
            bucket = "settles"
        elif cat in anc(R) or R in anc(cat):
            bucket = "agrees"
        else:
            bucket = "flips"
        per[h][bucket].append((name, docs[k], cat, dict(typings[k].most_common(3))))

    # ── report ──────────────────────────────────────────────────────────────
    buckets = ("settles", "agrees", "flips", "out", "curated", "by term", "untyped")
    tot = Counter(); tot2 = Counter()
    rows = []
    for h in sorted(per, key=lambda h: (-len(per[h]["flips"]), h)):
        b = per[h]
        c = {x: len(b[x]) for x in buckets}
        c2 = {x: sum(1 for t in b[x] if t[1] >= 2) for x in buckets}
        tot.update(c); tot2.update(c2)
        flips = sorted(b["flips"], key=lambda t: -t[1])
        rows.append({"head": h, "rule": rules[h], "counts": c, "counts_2plus": c2,
                     "flip_categories": dict(Counter(t[2] for t in flips).most_common()),
                     "flip_examples": [[t[0], t[1], t[2]] for t in flips[:12]],
                     "settle_examples": [t[0] for t in sorted(b["settles"], key=lambda t: -t[1])[:6]],
                     "by_term_disagree": [[t[0], by_term[N(t[0])]] for t in b["by term"]
                                          if by_term[N(t[0])] != rules[h]]})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"rules": rules, "unread": unread, "undecided": undecided,
                               "total": dict(tot), "total_2plus": dict(tot2), "heads": rows},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(OUT.read_text(encoding="utf-8"))
    assert len(back["heads"]) == len(rows)
    print(f"[heads] {len(rules)} head rules; unread {unread}; undecided {undecided}")
    print(f"[heads] all terms   : {dict(tot)}")
    print(f"[heads] >=2 abstracts: {dict(tot2)}")
    for r in rows:
        c = r["counts"]
        print(f"  {r['head']:13s} -> {r['rule']:34s} settles {c['settles']:4d} agrees {c['agrees']:5d} "
              f"flips {c['flips']:4d} out {c['out']:4d} curated {c['curated']:3d} byterm {c['by term']:3d} "
              f"| flips from {r['flip_categories']}")
    print(f"[heads] written and read back: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
