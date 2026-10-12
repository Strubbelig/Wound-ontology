"""Cut the placement answers no check has seen yet into chunks for reading. Sandbox only.

    python -u scripts/placement_check_chunks.py [--write]

The two checks of rule 59 are read from numbered chunk files
(`merge_placement_checks.py`): the verify rows (with the model's yes/no) in
`placement_verifycheck_2026-10-01/`, every other usable answer in
`placement_selfcheck_2026-10-01/`. Names renamed after the chunks were cut get
fresh answers (`p4_place_terms.py`) that neither folder holds; this appends
them -- new rows numbered after the last, new chunk files after the last -- so
that every answer the merge uses has been read. Rows already cut are never
renumbered or rewritten; a row whose term is no longer current simply stops
matching anything.

Line formats (as the earlier chunks):
  self    n|term|cat|< parent|1:alt ; 2:alt ; 3:alt ; 4:alt     (`=` for same)
  verify  n|term|cat|< parent|Y or N(reason)|1:alt ; ...
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))

from merge_placement_checks import SELF, SRC, VCHECK, VERIFY, key  # noqa: E402

CHUNK = 600


def line(r, extra=None):
    alts = [c for c, _ in r.get("candidates") or [] if c != r["parent"]][:4]
    rel = "<" if r["relation"] == "is_a" else "="
    parts = [str(r["n"]), r["term"], r["category"][:4], f"{rel} {r['parent']}"]
    if extra is not None:
        parts.append(extra)
    parts.append(" ; ".join(f"{i}:{a}" for i, a in enumerate(alts, 1)))
    return "|".join(parts)


def main(argv: list[str]) -> int:
    from p4_verify_placements import selected
    rows = json.loads(SRC.read_text(encoding="utf-8"))["rows"]
    usable = [r for r in rows if r["relation"] in ("is_a", "same") and r.get("parent") and not r.get("unlisted")]
    vsel = {key(r) for r in selected(rows)}
    verify = {(v["term"], v["relation"], v["parent"]): v
              for v in json.loads(VERIFY.read_text(encoding="utf-8"))["rows"]}
    out = {}
    for folder, want in ((VCHECK, [r for r in usable if key(r) in vsel]),
                         (SELF, [r for r in usable if key(r) not in vsel])):
        have = json.loads((folder / "rows.json").read_text(encoding="utf-8"))
        seen = {key(r) for r in have["rows"]}
        new = [dict(r) for r in want if key(r) not in seen]
        if folder == VCHECK:
            unanswered = [r for r in new if key(r) not in verify]
            if unanswered:
                print(f"[chunks] {len(unanswered)} verify row(s) have no model answer yet -- run "
                      f"p4_verify_placements.py first; e.g. {[r['term'] for r in unanswered[:5]]}")
                new = [r for r in new if key(r) in verify]
        n0 = max((r["n"] for r in have["rows"]), default=-1) + 1
        for i, r in enumerate(new):
            r["n"] = n0 + i
        c0 = max((int(f.stem.split("_")[1]) for f in folder.glob("chunk_*.txt")), default=-1) + 1
        chunks = [new[i:i + CHUNK] for i in range(0, len(new), CHUNK)]
        out[folder] = (have, new, c0, chunks)
        print(f"[chunks] {folder.name}: {len(new)} new row(s) -> "
              f"{'chunks ' + str(c0) + ' .. ' + str(c0 + len(chunks) - 1) if chunks else 'nothing to cut'}")
    if "--write" not in argv:
        print("[chunks] dry run; --write to append")
        return 0
    for folder, (have, new, c0, chunks) in out.items():
        if not new:
            continue
        bk = ROOT / "data" / "backup" / f"{folder.name}_rows_before_chunks_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
        shutil.copy2(folder / "rows.json", bk)
        have["rows"].extend(new)
        (folder / "rows.json").write_text(json.dumps(have, ensure_ascii=False, indent=1), encoding="utf-8")
        for j, ch in enumerate(chunks):
            lines = []
            for r in ch:
                if folder == VCHECK:
                    v = verify[key(r)]
                    ans = "Y" if v["answer"] == "yes" else f"N({(v.get('reason') or '')[:70]})"
                    lines.append(line(r, ans))
                else:
                    lines.append(line(r))
            (folder / f"chunk_{c0 + j:02d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        back = json.loads((folder / "rows.json").read_text(encoding="utf-8"))["rows"]
        if len(back) != len(have["rows"]):
            raise RuntimeError(f"[chunks] {folder.name}: rows.json read back {len(back)} != {len(have['rows'])}")
        print(f"[chunks] {folder.name}: written and read back ({len(new)} rows; backup {bk.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
