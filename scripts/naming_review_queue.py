"""Build the queue for the Naming Rulings page. Read-only.

Two queues, both decisions the rules cannot take on their own:

* **mappings** -- a term the scope pass judged `in` whose reason names an
  existing ontology class in parentheses ("A wound complication (surgical
  site infection)"). The model recognised the concept but had no way to map
  it; the mapping build cannot either, because a paraphrase or an
  abbreviation is far below the embedding threshold (`DFU` / `Diabetic foot
  ulcer`). Candidates whose class is an upper-level category or a generic
  class (`biological_process`, `protein`) are dropped: those reasons describe
  what kind of thing the term is, not what it is.
* **adjectives** -- one row per leading adjective (curator, 2026-09-28: "I hate
  these adjectives like massive"). Praise and filler words are proposed for
  stripping, severity and size words for keeping as a subtype of the head.

Row ids come from the term or the word, so the page can be republished and
every answer stays attached to its question.

    python scripts/naming_review_queue.py [--out data/review/naming_queue_<date>.json]
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

GENERIC_TARGETS = {
    "biological_process", "biological process", "protein", "device", "wound",
    "injury", "quality", "process", "material entity", "disease", "disorder",
    "cell", "molecule", "drug", "treatment", "therapy", "procedure",
}

#: Proposed default per word. `strip` = praise or filler, the name without it
#: is the same concept; `subtype` = a severity or size grade, kept as its own
#: term under the head; `leave` = too often part of a fixed name to touch.
ADJECTIVES = {
    "strip": ["novel", "promising", "effective", "successful", "innovative",
              "optimal", "potential", "possible", "various", "different",
              "significant", "important", "key", "main", "certain",
              "appropriate", "adequate", "proper", "better", "excellent",
              "favorable", "favourable", "emerging", "modern"],
    "subtype": ["massive", "severe", "mild", "moderate", "large", "small",
                "extensive", "substantial", "marked", "profound", "excessive",
                "giant"],
    "leave": ["new", "multiple", "standard", "conventional", "traditional",
              "advanced", "current", "good", "poor", "improved", "major",
              "minor", "big"],
}

#: Names that are fixed terms whatever the word list says.
FIXED = [
    "standard deviation", "standard error", "large language model",
    "small molecule", "big toe", "big data", "major amputation",
    "minor amputation", "multiple organ failure",
    "multiple organ dysfunction syndrome", "multiple sclerosis",
    "multiple myeloma", "traditional chinese medicine",
    "mild cognitive impairment", "severe acute respiratory syndrome",
    "small intestine", "large intestine", "small bowel", "large bowel",
    "major adverse limb event", "major adverse cardiovascular event",
    "current smoker", "new zealand", "key opinion leader", "main effect",
    "marked improvement", "moderate evidence", "small artery disease",
]


def _id(prefix: str, key: str) -> str:
    return prefix + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def main(argv: list[str]) -> int:
    from wound_ontology.llm.category_vocab import declared_category
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.utils.string_utils import normalize_term

    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else \
        ROOT / "data" / "review" / f"naming_queue_{date.today()}.json"
    p = Orchestrator()
    gt = p.term_mapper._term_mapping
    labels = {normalize_term(str(l)): str(l) for l in p.ontology_labels()}
    freq: Counter = Counter()
    for _, ents in p.store.view(mapped=False):
        freq.update(ents.keys())

    mappings = []
    for term, rec in gt.records.items():
        if gt.is_alias(term) or rec.get("to") or term not in freq:
            continue
        reason = ((rec.get("gate") or {}).get("pass2") or {}).get("reason", "")
        seen = set()
        for inner in re.findall(r"\(([^)]+)\)", reason):
            for part in re.split(r",|;|/| or | e\.g\.,? | i\.e\.,? ", inner):
                key = normalize_term(part.strip())
                target = labels.get(key)
                if (not target or key == normalize_term(term) or target in seen
                        or declared_category(target) is not None
                        or key in GENERIC_TARGETS):
                    continue
                seen.add(target)
                mappings.append({"id": _id("m", term + "→" + target),
                                 "term": term, "target": target,
                                 "mentions": freq[term], "reason": reason})
    mappings.sort(key=lambda r: (-r["mentions"], r["term"].lower()))

    by_word: dict[str, Counter] = defaultdict(Counter)
    for name, n in freq.items():
        first = name.split(" ", 1)[0].lower()
        if " " in name:
            by_word[first][name] += n
    fixed = {normalize_term(f) for f in FIXED}
    adjectives = []
    for proposal, words in ADJECTIVES.items():
        for w in words:
            names = by_word.get(w, Counter())
            if not names:
                continue
            exceptions = sorted({n for n in names if normalize_term(n) in fixed
                                 or normalize_term(n) in labels})
            adjectives.append({
                "id": _id("a", w), "word": w, "proposal": proposal,
                "names": len(names), "mentions": sum(names.values()),
                "examples": [[n, c] for n, c in names.most_common(10)],
                "exceptions": exceptions})
    adjectives.sort(key=lambda r: (["strip", "subtype", "leave"].index(r["proposal"]),
                                   -r["mentions"]))

    out.write_text(json.dumps({"mappings": mappings, "adjectives": adjectives},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(out.read_text(encoding="utf-8"))
    print(f"[naming] {len(back['mappings']):,} mapping candidate(s), "
          f"{sum(r['mentions'] for r in back['mappings']):,} mentions; "
          f"{len(back['adjectives'])} adjective(s) -> {out.relative_to(ROOT)}")
    for r in back["mappings"][:12]:
        print(f"  {r['mentions']:4}  {r['term']!r} -> {r['target']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
