"""Write `src/wound_ontology/utils/proper_nouns.py`: the words a name keeps capitalised mid-name.

    python -u scripts/build_proper_nouns.py [--write]

Curator, 2026-10-24: names are written in lowercase with a capital first
letter, abbreviations excepted ("Sie wandelt in Kleinschreibung mit großem
erstem Buchstaben und klammert Abkürzungen von dieser Regel aus" -- "änder den
code"). WONT already writes its labels that way (380 of 582), and it keeps the
capital of a name inside a name: `Methicillin-resistant Staphylococcus aureus
infection`, `Gustilo and Anderson wound classification`. Lowercasing every word
after the first would destroy exactly those, so the rule needs to know which
words are names. Nobody is asked per word, and no model guesses: the corpus
already says.

The evidence is every string an author or WONT/MILD wrote with a DELIBERATE
capital -- a word capitalised after the first word, in a string that is neither
Title Case nor all capitals (in those the capital says nothing). A word is a
name when, at a non-initial position in such strings,

  * it is capitalised in at least 80 % of its occurrences, and
  * in at least 3 different strings.

`EXTRA` and `NOT_NAMES` are the rows Claude read on 2026-10-24 and settled
against that rule: eponyms the corpus lowercases often enough to fall under
80 % (`achilles`, `charcot`), and common nouns that clear it only because they
sit in the titles of instruments (`Numerical Rating Scale`, `Compact Bone`).

Sources: the newest `data/cache/term_mapping_*.json` -- its keys are the
strings as extracted (rule 51) -- and the labels of WONT and MILD.
Dry by default: prints the list and what changed against the current module.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "src" / "wound_ontology" / "utils" / "proper_nouns.py"
MIN_SHARE, MIN_STRINGS = 0.8, 3

#: Read, and names after all: the corpus lowercases them often enough to fall
#: under 80 %, but each is an eponym, a genus or a place.
EXTRA = frozenset({
    "achilles", "american", "behcet", "charcot", "china", "lemeshow", "naranjo",
    "sachs", "streptococcus", "vaseline", "wagner",
    # read 2026-10-24 on the pass 0 dry run, where sentence case would have
    # lowered them mid-name: `Costa Rica`, `Ferguson hemorrhoidectomy`,
    # `Mason-Allen suture`, `Burdenko neurosurgery center`
    "allen", "burdenko", "costa", "ferguson", "mason", "rica",
})
#: Read, and not names: they clear the rule only as words in the title of an
#: instrument or a compound (`Numerical Rating Scale`).
NOT_NAMES = frozenset({
    "carboxypeptidase", "compact", "consolability", "digestive", "multidimensional",
    "numerical", "plumbagin", "redesign",
})

WORD = re.compile(r"[A-Za-z][A-Za-z']*")
SPLIT = re.compile(r"[\s/-]+")


def is_title_case(s: str) -> bool:
    words = [w for w in SPLIT.split(s) if w[:1].isalpha()]
    return len(words) > 1 and all(w[0].isupper() for w in words)


def evidence(strings) -> tuple[collections.Counter, collections.Counter, dict]:
    cap, low = collections.Counter(), collections.Counter()
    where: dict[str, set] = collections.defaultdict(set)
    for s in strings:
        if is_title_case(s) or s.isupper():
            continue
        for i, m in enumerate(WORD.finditer(s)):
            w = re.sub(r"'s?$", "", m.group(0))
            if i == 0 or len(w) < 2 or any(c.isupper() for c in w[1:]):
                continue
            if w[0].isupper():
                cap[w.lower()] += 1
                where[w.lower()].add(s)
            else:
                low[w.lower()] += 1
    return cap, low, where


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    tm = sorted((ROOT / "data" / "cache").glob("term_mapping_*.json"))[-1]
    entries = json.loads(tm.read_text())
    entries = entries.get("entries", entries)
    strings = set(entries)

    from rdflib import RDFS
    from wound_ontology.hierarchies.curated_seed import default_curated_sources
    from wound_ontology.utils.rdf_io import parse_graph
    sources, _ = default_curated_sources()
    for src in sources:
        strings |= {str(o) for _, _, o in parse_graph(src).triples((None, RDFS.label, None))}

    cap, low, where = evidence(strings)
    ruled = {w for w in cap
             if len(where[w]) >= MIN_STRINGS and cap[w] / (cap[w] + low[w]) >= MIN_SHARE}
    names = sorted((ruled | EXTRA) - NOT_NAMES)
    print(f"{len(strings):,} strings from {tm.name} and {len(sources)} ontology file(s)")
    print(f"{len(ruled)} word(s) by the rule, {len(EXTRA)} added, "
          f"{len(ruled & NOT_NAMES)} removed -> {len(names)}")
    unused = (EXTRA - set(cap)) | (NOT_NAMES - ruled)
    if unused:
        print(f"WARNING: hand rows the evidence no longer supports: {sorted(unused)}")

    try:
        from wound_ontology.utils.proper_nouns import PROPER_NOUNS as old
    except ImportError:
        old = frozenset()
    print(f"against the current module: +{sorted(set(names) - old)}  -{sorted(old - set(names))}")
    if not args.write:
        print("dry run -- pass --write to write", OUT.relative_to(ROOT))
        return

    body = "\n".join(f'    "{w}",' for w in names)
    OUT.write_text(
        '"""GENERATED FILE - DO NOT EDIT BY HAND.\n\n'
        "Regenerate with:  python scripts/build_proper_nouns.py --write\n"
        f"Source:           {tm.name} + WONT + MILD labels\n"
        f"Generated:        {dt.date.today().isoformat()}\n\n"
        "Words a name keeps capitalised after its first word (see `utils.normalise.sentence_case`).\n"
        '"""\n'
        f"PROPER_NOUNS: frozenset[str] = frozenset({{\n{body}\n}})\n")
    from importlib import reload
    import wound_ontology.utils.proper_nouns as mod
    assert reload(mod).PROPER_NOUNS == frozenset(names), "written module does not read back"
    print(f"wrote {OUT.relative_to(ROOT)}: {len(names)} word(s), read back")


if __name__ == "__main__":
    main()
