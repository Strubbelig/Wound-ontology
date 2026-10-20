"""The concept lattice of the thesis's FCA example (Tabelle 2.2), as a figure.

    python scripts/figure_fca_example.py

Writes ../Thesis/figures/fca_example.svg, plus .pdf and .png through headless
Chrome (the same renderer as figure_abstracts_to_wont.py). The concepts are
COMPUTED from the table below, not drawn by hand, and the run stops if they
are not the five the thesis text names -- so the text, the table and the
figure cannot drift apart. The example is invented and simplified; it says so
in the thesis.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from html import escape
from itertools import combinations
from pathlib import Path

from figure_abstracts_to_wont import CHAR, FIG_DIR, FS, FS_SMALL, LH, LH_SMALL, PAD, ROOT, render

#: Tabelle 2.2, row by row: the wound and the features it has.
CONTEXT = {
    "Dekubitus": {"heilt verzögert", "durch Druck verursacht"},
    "Diabetisches Fußulkus": {"heilt verzögert", "an der unteren Extremität", "durch Druck verursacht"},
    "Ulcus cruris venosum": {"heilt verzögert", "an der unteren Extremität"},
    "Schnittwunde": set(),
}
FEATURES = ["heilt verzögert", "an der unteren Extremität", "durch Druck verursacht"]
#: A concept whose intent is exactly this already has a class; every other inner node is a candidate.
NAMED = {frozenset({"heilt verzögert"}): "chronische Wunde"}

W = 160                      # mm; the text block is 155 mm, Word scales to it
BOX_W = {0: 88, 1: 88, 2: 72, 3: 72}
GAP_Y = 9


def concepts() -> list[tuple[frozenset, frozenset]]:
    def extent(b):
        return frozenset(g for g, a in CONTEXT.items() if b <= a)

    def intent(a):
        return frozenset(set.intersection(*(CONTEXT[g] for g in a)) if a else FEATURES)
    found = {(extent(frozenset(b)), intent(extent(frozenset(b))))
             for k in range(len(FEATURES) + 1) for b in combinations(FEATURES, k)}
    return sorted(found, key=lambda c: (len(c[1]), sorted(c[1])))


def covers(cs):
    """(upper, lower) pairs of the Hasse diagram: lower's extent is a maximal proper subset of upper's."""
    out = []
    for up in cs:
        for lo in cs:
            if lo[0] < up[0] and not any(lo[0] < mid[0] < up[0] for mid in cs):
                out.append((up, lo))
    return out


def lines_of(c) -> list[tuple[str, str]]:
    ext, itt = c
    names = [g for g in CONTEXT if g in ext]
    umfang = "alle vier Wunden" if len(names) == len(CONTEXT) else ", ".join(names)
    inhalt = ("kein gemeinsames Merkmal" if not itt else
              "alle drei Merkmale" if len(itt) == len(FEATURES) else ", ".join(f for f in FEATURES if f in itt))
    out = [(f"Umfang: {umfang}", "b"), (f"Inhalt: {inhalt}", "r")]
    if itt in NAMED:
        out.append((f"bekannte Klasse: {NAMED[itt]}", "s"))
    elif 0 < len(ext) < len(CONTEXT) and len(ext) > 1:
        out.append(("Kandidat für eine Zwischenklasse, noch ohne Namen", "s"))
    return out


def draw() -> str:
    cs = concepts()
    if len(cs) != 5:
        raise RuntimeError(f"[figure] the example has {len(cs)} concepts; the thesis text names five")
    levels: dict[int, list] = {}
    for c in cs:
        levels.setdefault(len(c[1]), []).append(c)
    parts, pos, y = [], {}, 2.0
    for lvl in sorted(levels):
        row = sorted(levels[lvl], key=lambda c: sorted(c[1]))
        bw = BOX_W[lvl]
        span = len(row) * bw + (len(row) - 1) * 8
        x = (W - span) / 2
        h_row = 0
        for c in row:
            ls = lines_of(c)
            h = 2 * PAD + sum(LH_SMALL if st == "s" else LH for _, st in ls) - 0.5
            cand = any("Kandidat" in t for t, _ in ls)
            dash = ' stroke-dasharray="1.2 0.8"' if cand else ""
            parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bw}" height="{h:.2f}" rx="0.8" fill="#FFFFFF" '
                         f'stroke="#1A1A1A" stroke-width="{0.6 if c[1] in NAMED else 0.3}"{dash}/>')
            ty = y + PAD
            for text, st in ls:
                size, lh = (FS_SMALL, LH_SMALL) if st == "s" else (FS, LH)
                if len(text) > (bw - 2 * PAD) / (size * CHAR):
                    raise ValueError(f"[figure] line too long for its box: {text!r}")
                ty += lh
                weight = ' font-weight="bold"' if st == "b" else ""
                style = ' font-style="italic" fill="#555555"' if st == "s" else ""
                parts.append(f'<text x="{x + bw / 2:.2f}" y="{ty - 0.75:.2f}" font-size="{size}" '
                             f'text-anchor="middle"{weight}{style}>{escape(text)}</text>')
            pos[c] = (x + bw / 2, y, y + h)
            h_row = max(h_row, h)
            x += bw + 8
        y += h_row + GAP_Y
    for up, lo in covers(cs):
        (x1, _, b1), (x2, t2, _) = pos[up], pos[lo]
        parts.insert(0, f'<line x1="{x1:.2f}" y1="{b1:.2f}" x2="{x2:.2f}" y2="{t2:.2f}" '
                        f'stroke="#1A1A1A" stroke-width="0.3"/>')
    h = y - GAP_Y + 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{h:.1f}mm" viewBox="0 0 {W} {h:.1f}" '
            f'font-family="Arial, Helvetica, sans-serif" fill="#1A1A1A">\n<rect width="{W}" height="{h:.1f}" '
            f'fill="#FFFFFF"/>\n' + "\n".join(parts) + "\n</svg>\n")


def main() -> int:
    svg = FIG_DIR / "fca_example.svg"
    if svg.exists():
        bak = ROOT / "data" / "backup" / "figures"
        bak.mkdir(parents=True, exist_ok=True)
        shutil.copy2(svg, bak / f"fca_example_{datetime.now():%Y-%m-%d_%H-%M-%S}.svg")
    text = draw()
    svg.write_text(text, encoding="utf-8")
    if svg.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"[figure] {svg} did not read back as written")
    made = [svg, *render(svg)]
    print("[figure] written: " + ", ".join(str(m.relative_to(ROOT.parent)) for m in made))
    for ext, itt in concepts():
        print(f"  {sorted(ext)}  {sorted(itt)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
