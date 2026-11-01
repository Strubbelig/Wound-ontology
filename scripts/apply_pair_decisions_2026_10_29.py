#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The author's answers on the open synonym pairs of 2026-10-29, as author judgements.

    python -u scripts/apply_pair_decisions_2026_10_29.py            # dry run
    python -u scripts/apply_pair_decisions_2026_10_29.py --write

Rule 89 (curator, 2026-10-28): the synonym pairs whose two DeepSeek judgements
disagree and that have no author judgement go on the author's list. The author
answered them on the pair page (claude.ai/artifact/GebNSrsMEfMxGsdaF3vSXm);
its stored choices are in data/review/synonym_pairs_2026-10-29/decisions/.

Each choice becomes the author's judgement on the pair, with the note in `why`:

* same       -> `same_class`; a pair kept apart today is named as one
                (Wound healing disturbance by Wound healing disorder).
* different  -> `different`; a pair named as one today is taken apart: the
                term gets its own name back.
* a_under_b  -> `narrower`, b_under_a -> `broader`: taken apart as above, and
                written as is_a `yes` between the two, so the link acts in the
                hierarchy like the author's 44 answers of the same morning.

The notes are recorded, not acted on: what they ask (rename Necrosis in WONT,
a quality of Aseptic conditions, where Debridement method goes as a plan
specification) is asked in chat first.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

PAGE = "pair page (author, 2026-10-29)"
DECISIONS = ROOT / "data" / "review" / "synonym_pairs_2026-10-29" / "decisions"
#: card id -> the pairs it answers, as (term whose record holds the pair, candidate).
CARDS = {
    "acute-infection": [("Acute infection disorder", "Acute infection")],
    "anti-biofilm": [("Anti-biofilm function", "Anti-biofilm ability")],
    "aseptic": [("Aseptic conditions", "Aseptic")],
    "bacillus": [("Bacillus", "Bacillus species")],
    "broad-spectrum": [("Broad-spectrum antibacterial activity", "Broad-spectrum antimicrobial activity")],
    "complete-thickness": [("Complete-thickness skin wound", "Complete-thickness wound")],
    "debridement-method": [("Debridement method", "Debridement process"), ("Debridement modality", "Debridement process")],
    "dehiscence": [("Wound dehiscence process", "Wound dehiscence")],
    "dermal-scar": [("Dermal scar", "Skin scar")],
    "healing-disturbance": [("Wound healing disturbance", "Wound healing disorder")],
    "manual-npwt": [("Manual negative pressure wound therapy method",
                     "Manual negative pressure wound therapy method wound treatment")],
    "mri": [("Magnetic resonance imaging study", "MRI")],
    "necrosis": [("Necrosis process", "Necrosis")],
    "primary-intention": [("Wound healing by primary intention process", "Wound healing by primary intention")],
    "skin-perfusion": [("Skin perfusion", "Skin blood perfusion")],
    "skin-regeneration": [("Skin tissue regeneration", "Skin regeneration process")],
    "softening": [("Softening", "softened")],
}
VERDICT = {"same": "same_class", "different": "different", "a_under_b": "narrower", "b_under_a": "broader"}


def main(argv: list[str]) -> int:
    from wound_ontology.orchestrator import Orchestrator, PLACEMENT_MIN_ABSTRACTS
    from wound_ontology.mappers.judgements import current
    o = Orchestrator()
    gt = o.term_mapper._term_mapping
    live = max((ROOT / "data" / "cache").glob("term_mapping_2026-*.json"), key=lambda f: f.stat().st_mtime)
    concept = lambda t: gt.concept(gt.resolve(t))  # noqa: E731

    choices = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(DECISIONS.glob("*.json"))}
    if set(choices) != set(CARDS):
        raise SystemExit(f"[pairs] decisions {sorted(set(choices) ^ set(CARDS))} do not match the cards; nothing written")
    if any(c["choice"] not in VERDICT for c in choices.values()):
        raise SystemExit(f"[pairs] a choice outside {sorted(VERDICT)}: "
                         f"{ {k: c['choice'] for k, c in choices.items() if c['choice'] not in VERDICT} }; nothing written")
    for pairs in CARDS.values():
        for a, b in pairs:
            if b not in ((gt.records.get(a) or {}).get("pairs") or {}):
                raise SystemExit(f"[pairs] no pair {a!r} / {b!r} in {live.name}; nothing written")
    print(f"[pairs] {live.name}: {len(choices)} cards, {sum(map(len, CARDS.values()))} pairs")

    links = []
    for card, pairs in CARDS.items():
        ch = choices[card]
        verdict = VERDICT[ch["choice"]]
        why = f"{PAGE}: {ch['choice_text']}" + (f"; note: {ch['note']}" if ch["note"] else "")
        for a, b in pairs:
            was_one = concept(a) == concept(b)
            gt._put(a, "pairs", gt._j(verdict, "author", why), b)
            if verdict == "same_class" and not was_one:
                gt._put(a, "name", gt._j(concept(b), "author", why))
            elif verdict != "same_class" and was_one:
                gt._put(a, "name", gt._j(a, "author", why))
                if concept(a) == concept(b):            # b was the one named by a
                    gt._put(b, "name", gt._j(b, "author", why))
            if verdict in ("narrower", "broader"):
                child, parent = (concept(a), concept(b)) if verdict == "narrower" else (concept(b), concept(a))
                gt._put(child, "is_a", gt._j("yes", "author", why), parent)
                links.append((child, parent))
            now_one = concept(a) == concept(b)
            if now_one != (verdict == "same_class"):
                raise SystemExit(f"[pairs] {a!r} / {b!r}: {verdict} but one class: {now_one}; nothing written")
            print(f"  {a} / {b}: {verdict}" + ("" if was_one == now_one else
                  (" (named as one)" if now_one else " (taken apart)")))
    gt._dirty()

    if "--write" not in argv:
        print("[pairs] dry run; --write to apply")
        return 0
    backup = ROOT / "data" / "backup" / f"term_mapping_before_pair_decisions_{datetime.now():%Y-%m-%d_%H-%M}.json"
    shutil.copy2(live, backup)
    print(f"[pairs] backed up {live.name} -> {backup.relative_to(ROOT)}")
    gt.save()

    o2 = Orchestrator()
    g2 = o2.term_mapper._term_mapping
    c2 = lambda t: g2.concept(g2.resolve(t))  # noqa: E731
    seen: dict[str, set] = {}
    for key, ents in o2.store.view():
        for e in ents:
            seen.setdefault(e, set()).add(key)
    bad = []
    tl = set(g2.term_links())
    for card, pairs in CARDS.items():
        verdict = VERDICT[choices[card]["choice"]]
        for a, b in pairs:
            cj = current(g2.records[a]["pairs"][b])
            if (cj["verdict"], cj["by"]) != (verdict, "author"):
                bad.append(f"{a} / {b}: pair reads {cj['verdict']} by {cj['by']}")
            if (c2(a) == c2(b)) != (verdict == "same_class"):
                bad.append(f"{a} / {b}: one class is {c2(a) == c2(b)}")
    for child, parent in links:
        if (child, parent) not in tl and g2.gate_verdict(child)[0] != "out" and g2.gate_verdict(parent)[0] != "out":
            bad.append(f"link not read back: {child} is_a {parent}")
    print(f"[pairs] read back: problems: {bad or 'none'}")
    print("[pairs] the classes now (abstracts in the cleaned store; scope):")
    for card, pairs in CARDS.items():
        for x in dict.fromkeys(c2(t) for p in pairs for t in p):
            n = len(seen.get(x, ()))
            print(f"  {x}: {n} abstract(s){'' if n >= PLACEMENT_MIN_ABSTRACTS else ' (below the cut)'}; "
                  f"scope {g2.gate_verdict(x)[0] or 'none yet'}")
    for child, parent in links:
        n_c, n_p = len(seen.get(child, ())), len(seen.get(parent, ()))
        print(f"  link {child} is_a {parent}: "
              + ("built" if min(n_c, n_p) >= PLACEMENT_MIN_ABSTRACTS else f"below the cut ({n_c} / {n_p})"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
