"""A persistent WONT id for every class the pipeline mints (rule 71).

Until 2026-10-04 the export numbered minted classes from WONT's highest id on
every run, so an id meant a different class after any change upstream: after
the ulcer/wound renames WONT_0004067 was `Ligamentous Rupture`, not `Length`,
and a curator axiom holding that IRI emptied Wound. An id that moves cannot be
cited, published or reviewed against.

The registry maps what a name SHARES with its spellings (`Normalised.key`, so
case, plural, hyphen, British spelling, ulcer/wound fold away) to one IRI:

* a class seen before gets its id back;
* a renamed class keeps its id: the export hands over its former names (the
  term dict's spelling aliases and every term whose `to` is now this name) and
  any of them that is registered answers;
* two registered classes merged by a rename keep ONE id -- the one registered
  under the current name, else the older -- and the other is recorded obsolete,
  `replaced_by` the survivor (OBO practice: an id is never reused and never
  silently dropped);
* a new class gets the next number after every id ever issued AND after
  WONT's own highest id, so WONT's main series continues consecutively
  (curator, 2026-10-04: "I'll reset Protégé every time" -- the next free id is
  written to output/owl/NEXT_FREE_WONT_ID.txt after each export, and an id the
  registry holds turning up as a curated WONT class stops the export).

Stored in `data/registry/wont_ids.json` -- not under data/cache, which is
pruned. `save()` backs the previous file up and reads the new one back.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable

BLOCK_START = 1   # no separate block: WONT's main series continues (rule 71)
_ID = re.compile(r"WONT_(\d+)$")
#: A bracket that holds words, not an abbreviation. `Normalised.key` drops every
#: parenthetical, which is right for `Ulcers (DFU)`, but `Poly(ethylene Oxide)`
#: and `Poly (lactic-Co-Glycolic Acid)` both became `poly`, and on 2026-10-28
#: WONT_0005416 passed from the one polymer to the other.
_WORDS_IN_BRACKETS = re.compile(r"\(([^()]*\s[^()]*)\)")


def _num(iri: str) -> int:
    m = _ID.search(iri)
    return int(m.group(1)) if m else -1


class IdRegistry:
    def __init__(self, path: str | Path, namespace: str, id_width: int = 7):
        self.path = Path(path)
        self.namespace = namespace
        self.id_width = id_width
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.entries: dict[str, dict] = data.get("entries", {})
        self.changes = {"reused": 0, "issued": 0, "renamed": 0, "merged": []}
        self._rekey()
        self._index()

    @staticmethod
    def key(label: str) -> str:
        """`Normalised.key`, except that words in brackets are kept as words."""
        from wound_ontology.utils.normalise import normalise
        return normalise(_WORDS_IN_BRACKETS.sub(r" \1 ", label)).key

    def _rekey(self) -> None:
        """Entries keyed before brackets kept their words get their own key back.

        The old key (`poly`) is dropped, not kept beside the new one: it is the
        very key two classes shared.
        """
        from wound_ontology.utils.normalise import normalise
        moved = []
        for iri, e in self.entries.items():
            label = e.get("label", "")
            new, old = self.key(label), normalise(label).key
            if new != old and old in e.get("keys", []):
                e["keys"] = [new if k == old else k for k in e["keys"]]
                moved.append(f"{iri.rsplit('/', 1)[-1]} {label!r}: {old!r} -> {new!r}")
        if moved:
            print(f"[ids] {len(moved)} entr(y/ies) re-keyed, words in brackets now count: {moved}")

    def _index(self) -> None:
        self.by_key: dict[str, str] = {}
        for iri, e in self.entries.items():
            for k in e.get("keys", []):
                self.by_key.setdefault(k, iri)

    def _live(self, iri: str) -> str:
        seen = set()
        while self.entries.get(iri, {}).get("status") == "obsolete":
            if iri in seen:
                raise RuntimeError(f"[ids] replaced_by cycle at {iri}")
            seen.add(iri)
            iri = self.entries[iri]["replaced_by"]
        return iri

    def next_id(self, floor: int = BLOCK_START) -> int:
        issued = [_num(i) for i in self.entries]
        return max([floor - 1, *issued]) + 1

    def lookup(self, label: str, former: Iterable[str] = ()) -> str | None:
        """The live id for `label`, or None. Merges ids if a rename joined two."""
        own_key = self.key(label)
        own = self.by_key.get(own_key)
        hits = []
        for k in [own_key, *(self.key(f) for f in former)]:
            iri = self.by_key.get(k)
            if iri is not None:
                live = self._live(iri)
                if live not in hits:
                    hits.append(live)
        if not hits:
            return None
        keep = self._live(own) if own is not None else min(hits, key=_num)
        for gone in hits:
            if gone != keep:
                self.entries[gone].update({"status": "obsolete", "replaced_by": keep,
                                           "obsoleted": datetime.now().isoformat(timespec="seconds"),
                                           "why": f"merged into {label!r} by a rename"})
                self.entries[keep].setdefault("keys", [])
                for k in self.entries[gone].get("keys", []):
                    if k not in self.entries[keep]["keys"]:
                        self.entries[keep]["keys"].append(k)
                self.changes["merged"].append((gone, keep))
        e = self.entries[keep]
        renamed = own_key not in e["keys"]
        if renamed:
            e["keys"].append(own_key)
        # Only a real rename changes the label: two case variants of one name
        # meeting in one build must not flip it run after run.
        if renamed and e.get("label") != label:
            e.setdefault("former_labels", [])
            if e.get("label") and e["label"] not in e["former_labels"]:
                e["former_labels"].append(e["label"])
            e["label"] = label
            self.changes["renamed"] += 1
        self._index()
        self.changes["reused"] += 1
        return keep

    def issue(self, label: str, iri: str) -> None:
        self.entries[iri] = {"label": label, "keys": [self.key(label)], "status": "active",
                             "issued": datetime.now().isoformat(timespec="seconds")}
        self.by_key.setdefault(self.key(label), iri)
        self.changes["issued"] += 1

    def mint(self, label: str, taken: set[int], floor: int = BLOCK_START) -> str:
        n = self.next_id(floor)
        while n in taken:
            n += 1
        iri = f"{self.namespace}WONT_{n:0{self.id_width}d}"
        self.issue(label, iri)
        return iri

    def save(self, backup_dir: str | Path | None = None) -> None:
        if self.path.exists() and backup_dir is not None:
            Path(backup_dir).mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, Path(backup_dir) /
                         f"wont_ids_{datetime.now():%Y-%m-%d_%H-%M-%S}.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"about": "Persistent WONT ids of pipeline-minted classes (INSTRUCTIONS rule 71).",
                "entries": self.entries}
        self.path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        back = json.loads(self.path.read_text(encoding="utf-8"))
        if back["entries"] != self.entries:
            raise RuntimeError(f"[ids] {self.path} did not read back as written")
