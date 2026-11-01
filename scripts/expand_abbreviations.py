"""Rename every abbreviation-only term to the full form its own abstracts define (rule 58).

    python -u scripts/expand_abbreviations.py [--write]

Curator, 2026-09-30: "no abbreviations ever" and "you can rename without
guessing". The full form is read from the abstracts that use the abbreviation,
never proposed by a model: the Schwartz & Hearst (2003) rule finds
`long form (SF)` and `SF (long form)` pairs, where every character of the
short form must occur, in order, in the long form, and the short form's
first character must start a word of it.

Per abbreviation-only term (the typographic test of rule 58) that is in scope:

  expand     every abstract that defines it agrees on one full form -> map it
  ambiguous  the abstracts define it differently (`PI` = pressure injury in
             some, prediction interval in others) -> reported, not mapped
  undefined  no abstract that uses it defines it -> reported, not mapped
  decided    a curator already ruled on it (scope or mapping) -> untouched

Dry by default. `--write` backs up the term dict, writes curator mappings
tagged with the defining PMIDs, re-reads the file and checks each one.
"""
from __future__ import annotations

import glob
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

REPORT = ROOT / "output" / "abbreviation_expansion_2026-09-30.json"
ABBR = re.compile(r"^(?=(?:[^A-Z]*[A-Z]){2})[A-Z0-9][A-Z0-9\-/&+.]*?(s)?$")
BY = "rule 58: full form defined in the abstract"
# --wide (curator, 2026-10-02: "there are still abbreviations like MSC-Exo and
# i-PRF"): one token with a run of two or more capitals that the strict test
# above misses because it also holds lowercase letters.
WIDE = re.compile(r"[A-Z]{2,}")


def is_wide(name: str) -> bool:
    n = name.strip()
    return " " not in n and bool(WIDE.search(n)) and not ABBR.match(n)


def _sh_match(sf: str, cand: str) -> str | None:
    """Schwartz & Hearst: the shortest tail of `cand` that spells `sf`."""
    s, l = len(sf) - 1, len(cand) - 1
    while s >= 0:
        c = sf[s].lower()
        if not c.isalnum():
            s -= 1
            continue
        while l >= 0 and (cand[l].lower() != c or (s == 0 and l > 0 and cand[l - 1].isalnum())):
            l -= 1
        if l < 0:
            return None
        l -= 1
        s -= 1
    return cand[l + 1:].strip()


STOP = {"of", "the", "and", "in", "with", "for", "to", "on", "by", "a", "an", "or", "at", "from"}


def spells(sf: str, lf: str, keep_stop: bool = False) -> bool:
    """Does the long form spell the short form word by word?

    Every content word of the long form must start with the next letter of
    the short form, and a word may supply further letters from inside itself
    (`osteoNecrosis` in MRONJ, `interLeukin` in IL). Digits and stop words are
    ignored. Schwartz & Hearst alone accept `protective equipment` for PPE,
    taking the second P from inside `equiPment`; this is the check that
    refuses it. What fails goes to the curator, never to a guess.

    `keep_stop` (2026-10-02) lets a stop word supply a letter: `range of
    motion` spells ROM only with `of` counted."""
    letters = [c.lower() for c in (sf[:-1] if sf.endswith("s") and sf[:-1].isupper() else sf)
               if c.isalpha()]
    words = [w.lower() for w in re.split(r"[\s\-/]+", lf) if w and (keep_stop or w.lower() not in STOP)
             and not re.fullmatch(r"[\d.,+]+", w)]
    words = [re.sub(r"[^a-z0-9]", "", w) for w in words]
    words = [w for w in words if w and w[0].isalpha()]

    def go(i: int, j: int) -> bool:           # letters[i:], words[j:]
        if j == len(words):
            return i == len(letters)
        if i == len(letters) or words[j][0] != letters[i]:
            return False
        w, k = words[j], i + 1
        pos = 1
        while True:
            if go(k, j + 1):
                return True
            if k == len(letters):
                return False
            nxt = w.find(letters[k], pos)
            if nxt < 0:
                return False
            k, pos = k + 1, nxt + 1
    return bool(letters) and bool(words) and go(0, 0)


def definitions(text: str) -> dict[str, str]:
    """{short form: long form} defined in one abstract."""
    out = {}
    for m in re.finditer(r"\(([^()]{1,60})\)", text):
        inside = m.group(1).strip()
        before = text[:m.start()].rstrip()
        words = re.findall(r"\S+", before)
        # long form (SF)
        if ABBR.match(inside) or (1 < len(inside) <= 10 and " " not in inside and any(c.isupper() for c in inside)):
            sf = inside
            base = sf[:-1] if sf.endswith("s") and sf[:-1].isupper() else sf
            n = min(len(base) + 5, len(base) * 2)
            cand = " ".join(words[-n:])
            cand = re.split(r"[;:.!?\[\]]\s", cand)[-1]
            lf = _sh_match(base, cand)
            if lf and len(lf) > len(base) and lf.lower() != base.lower():
                out.setdefault(sf, lf.strip(",;: "))
        # SF (long form)
        elif words and ABBR.match(words[-1].strip(",;:")) and len(inside.split()) >= 2:
            sf = words[-1].strip(",;:")
            base = sf[:-1] if sf.endswith("s") and sf[:-1].isupper() else sf
            lf = _sh_match(base, inside)
            if lf and len(lf) > len(base):
                out.setdefault(sf, lf.strip(",;: "))
    return out


DIRTY_CHARS = re.compile(r"[;\"“”（）]")


def dirty(lf: str) -> bool:
    """A sentence fragment, not a name: unbalanced brackets (`MOF), PCN-222`),
    a bracket holding an abbreviation (`polyurethane (PU) foam`), a
    semicolon or a quote. `poly(L-lactic acid)` and `CO(2)` are names."""
    if DIRTY_CHARS.search(lf):
        return True
    depth = 0
    for ch in lf:
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(ch, 0)
        if depth < 0:
            return True
    if depth:
        return True
    return any(re.search(r"[A-Z]{2,}", b) for b in re.findall(r"[(\[]([^()\[\]]*)[)\]]", lf))


def _spelled_tail(sf: str, cand: str) -> str | None:
    """The tail of `cand`, cut at a space, that spells `sf` (2026-10-02).

    `_sh_match` takes the SHORTEST tail and lets a hyphen start a word, so
    `low-level laser therapy (LLLT)` gave `level laser therapy`, `small
    saphenous vein (SSV)` gave `saphenous vein` (the second S from inside
    `saphenouS`), `abdominal aortic calcification (AAC)` gave `aortic
    calcification`. Here a tail starts only after a space, must pass `spells`,
    and among the tails that do, the one whose content words come closest to
    one word per letter wins (shortest on a tie)."""
    toks = cand.split(" ")
    letters = sum(c.isalpha() for c in (sf[:-1] if sf.endswith("s") and sf[:-1].isupper() else sf))
    best = None
    for k in range(len(toks) - 1, -1, -1):
        tail = " ".join(toks[k:]).strip(",;: ")
        if not tail or not (spells(sf, tail) or spells(sf, tail, keep_stop=True)):
            continue
        n = len([w for w in re.split(r"[\s\-/]+", tail) if w and w.lower() not in STOP
                 and re.match(r"[A-Za-z]", w)])
        score = (abs(letters - n), len(tail))
        if best is None or score < best[0]:
            best = (score, tail)
    return best[1] if best else None


def spelled_definitions(text: str) -> dict[str, str]:
    """{short form: long form} defined in one abstract, every long form spelled.

    The reading the inside-the-name step uses since 2026-10-02 (rule 62
    incident): a long form must spell its short form letter by letter
    (`spells`) and must not carry a bracket, a semicolon or a quote -- `MOF),
    PCN-222, into a polyurethane (PU) foam` is a sentence fragment, not a name,
    and `the APG group` (a long form holding its own short form) is no
    definition."""
    out = {}
    for m in re.finditer(r"\(([^()]{1,60})\)", text):
        inside = m.group(1).strip()
        before = text[:m.start()].rstrip()
        words = re.findall(r"\S+", before)
        lf = sf = None
        if ABBR.match(inside) or (1 < len(inside) <= 10 and " " not in inside and any(c.isupper() for c in inside)):
            sf = inside
            base = sf[:-1] if sf.endswith("s") and sf[:-1].isupper() else sf
            n = min(len(base) + 5, len(base) * 2)
            cand = " ".join(words[-n:])
            cand = re.split(r"[;:.!?\[\]]\s", cand)[-1]
            lf = _spelled_tail(base, cand)
        elif words and ABBR.match(words[-1].strip(",;:")) and len(inside.split()) >= 2:
            sf = words[-1].strip(",;:")
            base = sf[:-1] if sf.endswith("s") and sf[:-1].isupper() else sf
            lf = inside.strip(",;: ") if (spells(base, inside) or spells(base, inside, keep_stop=True)) else None
        if (lf and sf and len(lf) > len(sf) and lf.lower() != sf.lower() and not dirty(lf)
                and not re.search(r"(?<![A-Za-z0-9])" + re.escape(sf.rstrip("s")) + r"s?(?![A-Za-z0-9])", lf)):
            out.setdefault(sf, lf)
    return out


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.normalise import normalise

    write = "--write" in argv
    wide = "--wide" in argv
    test = is_wide if wide else (lambda n: bool(ABBR.match(n.strip())))
    report = REPORT.with_name("abbreviation_expansion_wide_2026-10-02.json") if wide else REPORT
    by = BY + (" (widened test, 2026-10-02)" if wide else "")
    frames = [pd.read_csv(f) for f in sorted(glob.glob(str(ROOT / "data/cache/pubmed_abstracts_*.csv")))]
    df = pd.concat(frames).drop_duplicates("pmid")
    text = {str(r.pmid): f"{r.title or ''}. {r.abstract or ''}" for r in df.itertuples()}

    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    where = defaultdict(set)                   # spelled name -> pmids
    names_by_key = defaultdict(Counter)        # folded key -> store names
    for key, ents in p.store.view(mapped=False):
        for name in ents:
            where[name].add(key)
            names_by_key[normalise(name).key][name] += 1

    rows = {"expand": [], "unspelled": [], "ambiguous": [], "undefined": [], "decided": []}
    defs_cache: dict[str, dict] = {}
    for name in sorted(where):
        if not test(name):
            continue
        if gt.effective_gate_verdict(gt.resolve(name))[0] != "in":
            continue
        rec = gt.records.get(gt.resolve(name)) or {}
        if (rec.get("gate") or {}).get("curator") or rec.get("to") and rec.get("method") == "curator":
            rows["decided"].append({"term": name, "to": rec.get("to")})
            continue
        found = Counter(); pm = defaultdict(list)
        for k in where[name]:
            d = defs_cache.get(k)
            if d is None:
                d = defs_cache[k] = definitions(text.get(k, ""))
            lf = d.get(name) or d.get(name.rstrip("s"))
            if lf:
                kk = normalise(lf).key
                found[kk] += 1; pm[kk].append((k, lf))
        row = {"term": name, "abstracts": len(where[name])}
        if not found:
            rows["undefined"].append(row)
        elif len(found) > 1:
            row["forms"] = {pm[k][0][1]: n for k, n in found.most_common()}
            rows["ambiguous"].append(row)
        else:
            kk = next(iter(found))
            existing = names_by_key.get(kk)
            target = existing.most_common(1)[0][0] if existing else normalise(pm[kk][0][1]).name
            row.update({"to": target, "defined in": [x for x, _ in pm[kk]][:10],
                        "as written": pm[kk][0][1], "existing name": bool(existing)})
            rows["expand" if spells(name, pm[kk][0][1]) else "unspelled"].append(row)

    for k, v in rows.items():
        n2 = sum(1 for r in v if r.get("abstracts", 0) >= 2)
        print(f"[abbr] {k:10s} {len(v):5d}  (>=2 abstracts: {n2})  e.g. "
              f"{[(r['term'], r.get('to') or r.get('forms')) for r in sorted(v, key=lambda r: -r.get('abstracts', 0))[:8]]}")
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[abbr] report {report.relative_to(ROOT)}")
    if not write:
        print("[abbr] dry run; --write to map the `expand` rows")
        return 0

    latest = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    backup = ROOT / "data" / "backup" / f"term_mapping_before_abbreviations_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    shutil.copy2(latest, backup)
    print(f"[abbr] backed up {latest.name} -> {backup.relative_to(ROOT)}")
    when = datetime.now().isoformat(timespec="seconds")
    skipped = []
    # One save at the end: `add` saves the 45 MB file on every call, and a run
    # killed between two of those saves left a truncated file as the latest
    # (2026-09-30; quarantined, restored from the backup).
    for r in rows["expand"]:
        if gt.is_refused(r["term"], r["to"]):
            skipped.append(r["term"]); continue
        rec = gt.record(r["term"])
        rec.update({"to": r["to"], "confidence": 1.0, "method": "curator"})
        rec.pop("retired", None)
        gt.judge(r["term"], r["to"], curator={
            "verdict": "same_class", "when": when, "by": by,
            "reason": f"defined as {r['as written']!r} in PMID {', '.join(r['defined in'][:3])}"})
    # Undefined in every abstract that uses it, and used in only one: it
    # cannot be renamed without guessing, so it goes (rule 58). Those used in
    # two or more abstracts go to the curator's page instead.
    out = [r["term"] for r in rows["undefined"] if r["abstracts"] < 2]
    for t in out:
        gt.gate(t, curator={"verdict": "out", "when": when, "by": by,
                            "reason": "abbreviation only; no abstract that uses it defines it"})
    gt._dirty()
    gt.save()
    gt2 = Orchestrator().term_mapper._term_mapping
    lost = [r["term"] for r in rows["expand"] if r["term"] not in skipped and gt2.data.get(r["term"]) != r["to"]]
    lost += [t for t in out if gt2.peek_gate(gt2.resolve(t)).get("curator", {}).get("verdict") != "out"]
    if lost:
        raise RuntimeError(f"{len(lost)} decision(s) did not land: {lost[:10]}")
    print(f"[abbr] {len(out)} undefined single-abstract abbreviations put out of scope")
    print(f"[abbr] written and read back: {len(rows['expand']) - len(skipped)} mapped; "
          f"{len(skipped)} skipped as refused pairs: {skipped[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
