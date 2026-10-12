"""Figure: from abstracts to the classes and axioms of the WONT addition. Read-only on the pipeline.

    python scripts/figure_abstracts_to_wont.py               # measure, then draw
    python scripts/figure_abstracts_to_wont.py --from FILE   # redraw from a measurement

Every number in the figure is measured here, from the evidence store, the
terminology decision register, the class hierarchy and the exported files
(rule 15). Each exclusion is checked to add up: a box that says 7,576 -> 3,114
with 4,462 excluded is asserted, and every term that does not reach the
addition is put into a named reason or the script stops (no silent failure).

Writes output/figure_abstracts_to_wont_<stamp>.json (read back) and
../Thesis/figures/abstracts_to_wont.svg, plus .pdf and .png when Google Chrome
is installed (it renders the SVG; a failed render is reported, not hidden).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

FIG_DIR = ROOT.parent / "Thesis" / "figures"
WONT = ROOT / "data" / "ground truth" / "ground_truth_final.owl"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ALT_TERM = "http://purl.obolibrary.org/obo/IAO_0000118"


# ---------------------------------------------------------------- measuring
def measure() -> dict:
    import rdflib
    from rdflib import OWL, RDF, RDFS, URIRef
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from wound_ontology.orchestrator import Orchestrator, PLACEMENT_MIN_ABSTRACTS
    from wound_ontology.owl.extend import default_lexicon, lexicon_index
    from wound_ontology.utils.normalise import normalise

    # `.strict`, not `.key`: the key drops a final s case-sensitively
    # ("Retro-Rectus" -> "retrorectu"), the strict form does not.
    K = lambda s: normalise(str(s)).strict  # noqa: E731
    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    reg_terms = p.term_mapper._term_mapping
    N: dict = {"measured": datetime.now().isoformat(timespec="seconds")}

    # shared top
    raw = p.store.dict
    N["abstracts"] = sum(1 for r in raw.values() if isinstance(r, dict) and "entities" in r)
    N["term strings as extracted"] = len({n for r in raw.values() if isinstance(r, dict)
                                          for n in r.get("entities", {})})
    seen: Counter = Counter()
    for _, ents in p.store.view():
        seen.update(ents.keys())
    N["preferred terms in scope"] = len(seen)

    # classes lane
    ge2 = {t for t, c in seen.items() if c >= PLACEMENT_MIN_ABSTRACTS}
    N["terms in >= 2 abstracts"] = len(ge2)
    kept = [(t, c) for t, c in reg_terms.placements() if seen.get(t, 0) >= PLACEMENT_MIN_ABSTRACTS]
    placed_terms = {K(t): t for t, _ in kept}
    N["terms with an adjudicated placement"] = len(placed_terms)
    N["terms without an adjudicated placement"] = len(ge2) - len(placed_terms)

    core = rdflib.Graph().parse(ROOT / "output" / "owl" / "wont_extended_core.ttl")
    ext = rdflib.Graph().parse(ROOT / "output" / "owl" / "wont_extended.ttl")
    ids = json.loads((ROOT / "data" / "registry" / "wont_ids.json").read_text(encoding="utf-8"))["entries"]
    core_new = {K(core.value(s, RDFS.label)) for s in core.subjects(RDF.type, OWL.Class) if str(s) in ids}
    rep = json.loads((ROOT / "output" / "owl" / "core_build_report.json").read_text(encoding="utf-8"))
    from_placements = core_new & set(placed_terms)
    fillers = core_new - set(placed_terms)
    if len(from_placements) != rep["core"] or len(fillers) != rep["classes brought in as curator-axiom fillers"]:
        raise RuntimeError(f"[figure] core classes do not match the core report: {len(from_placements)} from "
                           f"placements vs {rep['core']}, {len(fillers)} fillers vs "
                           f"{rep['classes brought in as curator-axiom fillers']}")
    N["new classes from placements"] = len(from_placements)
    N["new classes as curator-axiom values"] = len(fillers)
    N["new classes in the addition"] = len(core_new)

    # why a placed term is not in the addition: every one gets a reason
    hier_parents: dict[str, list[str]] = {}
    for child in p.class_hier.df.index:
        for par in p.class_hier.parents_of(child):
            if child != par and p.class_hier.source_of(child, par) == "placed":
                hier_parents.setdefault(K(child), []).append(str(par))
    q = json.load(open(max(glob.glob(str(ROOT / "output" / "quarantine" / "edges_*.json")),
                           key=os.path.getmtime)))
    quarantined = {(K(a), K(b)) for a, b in q["edges"]}
    gt = rdflib.Graph().parse(WONT, format="turtle")
    wont_labels = {K(o) for o in gt.objects(None, RDFS.label)}
    lexicon = lexicon_index(default_lexicon())
    alt_terms = {K(o) for o in ext.objects(None, URIRef(ALT_TERM))}
    # a term the export never gave a new class resolved to an existing one
    minted_keys = {K(o) for s, o in ext.subject_objects(RDFS.label) if str(s) in ids}
    existing = lambda k, name: (k in wont_labels or k in alt_terms or lexicon.get(name)[0] is not None  # noqa: E731
                                or k not in minted_keys)
    why: Counter = Counter()
    unexplained = []
    for k, term in placed_terms.items():
        if k in core_new:
            continue
        if k not in hier_parents:
            if all((k, K(c)) in quarantined for t, c in kept if K(t) == k):
                why["placement inconsistent (reasoner)"] += 1
            elif existing(k, term):
                why["already an existing class"] += 1
            else:
                unexplained.append((term, "no placed edge"))
        elif existing(k, term):
            why["already an existing class"] += 1
        elif all(K(par) not in core_new and K(par) not in wont_labels for par in hier_parents[k]):
            why["parent class not placed itself"] += 1
        else:
            unexplained.append((term, hier_parents[k]))
    if unexplained:
        raise RuntimeError(f"[figure] {len(unexplained)} placed term(s) missing from the addition "
                           f"for no named reason: {unexplained[:10]}")
    N["placed terms not in the addition"] = dict(why)
    if sum(why.values()) != len(placed_terms) - len(from_placements):
        raise RuntimeError("[figure] placed-term exclusions do not add up")

    # relations lane
    tc = json.loads((ROOT / "data" / "review" / "relation_typing_check_2026-10-02.json").read_text(encoding="utf-8"))
    v2 = tc["verdicts_at_2_abstracts"]
    N["relation assertions"] = tc["triples"]
    N["relations in >= 2 abstracts"] = sum(v2.values())
    N["relations typed consistently"] = v2["ok"]
    N["relations violating domain or range"] = v2["violates"]
    N["relations with undetermined category"] = v2["undetermined"]
    u = json.loads((ROOT / "data" / "review" / "relation_universality_2026-10-02" / "result.json").read_text(encoding="utf-8"))
    if u["rows"] != v2["ok"]:
        raise RuntimeError(f"[figure] the reading covers {u['rows']} rows, the typing check passed {v2['ok']}")
    N["relations true of every instance"] = u["verdicts"]["all"]
    N["relations true of some instances"] = u["verdicts"]["some"]
    N["relations not true"] = u["verdicts"]["no"]
    resolve = p.store.resolver(mapped=True)
    rels = {(resolve(a["subject"])[1], a["predicate"], resolve(a["value"])[1]) for a in u["axioms"]}
    live = {k for e in ids.values() if e.get("status") != "obsolete" for k in e["keys"]}
    on_new = sum(1 for s, _, _ in rels if normalise(s).key in live)
    N["relations distinct after naming rulings"] = len(rels)
    N["relations on a new class"] = on_new
    N["relations on an existing class"] = len(rels) - on_new
    left = {"subject not in the addition": rep["relations left out (subject is a candidate)"],
            "value not in the addition": rep["relations left out (filler not in core)"],
            "inconsistent (reasoner)": rep.get("relations left out (ELK: unsatisfiable with them)", 0)}
    waiting = rep.get("relations held for the curator", 0)
    if rep.get("relations kept", 0) + waiting + sum(left.values()) != on_new:
        raise RuntimeError(f"[figure] relations on new classes: {on_new} measured, report accounts for "
                           f"{rep.get('relations kept', 0) + waiting + sum(left.values())}")
    N["relations in the addition"] = rep.get("relations kept", 0)
    N["relations waiting for the curator"] = waiting
    N["relations left out"] = left
    w = json.loads((ROOT / "data" / "review" / "withheld_relations_2026-10-03.json").read_text(encoding="utf-8"))
    N["relations on existing classes at curator review"] = len(w["rows"])
    N["curator axioms"] = rep["curator axioms"] + rep["curator axioms already stated"]
    N["curator axioms added"] = rep["curator axioms"]
    N["curator axioms already stated"] = rep["curator axioms already stated"]

    # the addition
    N["subclass axioms from placements"] = rep["placed edges"]
    N["BFO category axioms"] = rep["typing edges"]
    N["unsatisfiable classes (ELK)"] = len(rep["unsatisfiable_below_curated"]) + rep["elk_left_unsatisfiable_below_curated"]
    N["candidate classes kept apart"] = rep["candidates"]
    N["identifiers issued"] = rep["minted"]
    return N


def check(N: dict) -> None:
    """The arithmetic the figure shows. A box that does not add up is not drawn."""
    eq = [
        (N["terms in >= 2 abstracts"], N["terms with an adjudicated placement"] + N["terms without an adjudicated placement"]),
        (N["terms with an adjudicated placement"], N["new classes from placements"] + sum(N["placed terms not in the addition"].values())),
        (N["new classes in the addition"], N["new classes from placements"] + N["new classes as curator-axiom values"]),
        (N["relations in >= 2 abstracts"], N["relations typed consistently"] + N["relations violating domain or range"]
         + N["relations with undetermined category"]),
        (N["relations typed consistently"], N["relations true of every instance"] + N["relations true of some instances"]
         + N["relations not true"]),
        (N["relations distinct after naming rulings"], N["relations on a new class"] + N["relations on an existing class"]),
        (N["relations on a new class"], N["relations in the addition"] + N.get("relations waiting for the curator", 0)
         + sum(N["relations left out"].values())),
        (N["curator axioms"], N["curator axioms added"] + N["curator axioms already stated"]),
        (N["identifiers issued"], N["new classes in the addition"] + N["candidate classes kept apart"]),
    ]
    bad = [(a, b) for a, b in eq if a != b]
    if bad:
        raise RuntimeError(f"[figure] {len(bad)} box(es) do not add up: {bad}")


# ---------------------------------------------------------------- drawing
# Units are millimetres; the figure is 180 mm wide (full text width).
W = 180
FS, FS_SMALL = 2.47, 2.15            # 7 pt and 6.1 pt in mm
LH, LH_SMALL = 3.25, 2.85
PAD = 1.9
CHAR = 0.53                           # Arial: mean advance in em, generous


def f(n: int) -> str:
    return f"{n:,}"


class Fig:
    def __init__(self):
        self.parts: list[str] = []
        self.bottom = 0.0

    def box(self, x0, x1, y, lines, kind="main"):
        """lines: (text, style) with style in b (bold), n (count), r (regular), s (small), i (who)."""
        h = 2 * PAD + sum(LH_SMALL if st in "si" else LH for _, st in lines) - 0.5
        fill, stroke, sw = {"main": ("#FFFFFF", "#1A1A1A", 0.3), "excl": ("#EFEFEF", "#8C8C8C", 0.25),
                            "result": ("#FFFFFF", "#1A1A1A", 0.6), "curator": ("#FFFFFF", "#1A1A1A", 0.3)}[kind]
        dash = ' stroke-dasharray="1.2 0.8"' if kind == "curator" else ""
        self.parts.append(f'<rect x="{x0}" y="{y:.2f}" width="{x1 - x0}" height="{h:.2f}" rx="0.8" '
                          f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash}/>')
        cx, ty = (x0 + x1) / 2, y + PAD
        anchor, tx = ("middle", cx) if kind != "excl" else ("start", x0 + PAD)
        for text, st in lines:
            size = FS_SMALL if st in "si" else FS
            lh = LH_SMALL if st in "si" else LH
            room = (x1 - x0 - 2 * PAD) / (size * CHAR)
            if len(text) > room:
                raise ValueError(f"[figure] line too long for its box ({len(text)} > {room:.0f} chars): {text!r}")
            ty += lh
            weight = ' font-weight="bold"' if st in "bn" else ""
            style = ' font-style="italic" fill="#555555"' if st == "i" else ""
            self.parts.append(f'<text x="{tx:.2f}" y="{ty - 0.75:.2f}" font-size="{size}" text-anchor="{anchor}"'
                              f'{weight}{style}>{escape(text)}</text>')
        self.bottom = max(self.bottom, y + h)
        return y, y + h

    def arrow(self, pts):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.2f},{y:.2f}" for i, (x, y) in enumerate(pts))
        self.parts.append(f'<path d="{d}" fill="none" stroke="#1A1A1A" stroke-width="0.3" marker-end="url(#a)"/>')

    def label(self, x, y, text, anchor="start"):
        self.parts.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{FS_SMALL}" font-style="italic" '
                          f'fill="#555555" text-anchor="{anchor}">{escape(text)}</text>')

    def heading(self, x, y, text):
        self.parts.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{FS}" font-weight="bold" '
                          f'letter-spacing="0.25" text-anchor="middle">{escape(text.upper())}</text>')

    def svg(self) -> str:
        h = self.bottom + 1
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{h:.1f}mm" '
                f'viewBox="0 0 {W} {h:.1f}" font-family="Arial, Helvetica, sans-serif" fill="#1A1A1A">\n'
                '<defs><marker id="a" viewBox="0 0 6 6" refX="5.4" refY="3" markerWidth="5" markerHeight="5" '
                'orient="auto-start-reverse"><path d="M0,0.6 L5.6,3 L0,5.4 z" fill="#1A1A1A"/></marker></defs>\n'
                f'<rect width="{W}" height="{h:.1f}" fill="#FFFFFF"/>\n' + "\n".join(self.parts) + "\n</svg>\n")


def draw(N: dict) -> str:
    F = Fig()
    LX, LM, RM, RX = (0, 40), (44, 88), (92, 136), (140, 180)
    lc, rc = (LM[0] + LM[1]) / 2, (RM[0] + RM[1]) / 2
    sc = (LM[0] + RM[1]) / 2

    def step(col, y_top, lines, excl=None, side=None, gap=7.0, kind="main"):
        """A box at y_top; returns its bottom. `excl` hangs off the arrow above it."""
        return F.box(*col, y_top, lines, kind)[1]

    def down(x, y0, y1, excl=None, side=None, out_col=None):
        """Arrow from y0 to y1 at x; an exclusion box branches off at the middle."""
        F.arrow([(x, y0), (x, y1)])
        if excl:
            hgt = 2 * PAD + sum(LH_SMALL if st in "si" else LH for _, st in excl) - 0.5
            mid = (y0 + y1) / 2
            top = mid - hgt / 2
            F.box(*out_col, top, excl, "excl")
            edge = out_col[1] if side == "left" else out_col[0]
            F.arrow([(x, mid), (edge, mid)])

    def gap_for(excl):
        if not excl:
            return 6.0
        return 2 * PAD + sum(LH_SMALL if st in "si" else LH for _, st in excl) + 3.0

    # shared top
    y = 1.0
    b = F.box(LM[0], RM[1], y, [("PubMed abstracts on wound care", "b"),
                                 (f"n = {f(N['abstracts'])}", "n")])[1]
    y = b + 6
    F.arrow([(sc, b), (sc, y)])
    F.label(sc + 1.5, b + 3.6, "a language model picks out terms and how they relate")
    b = F.box(LM[0], RM[1], y, [("Terms as the abstracts wrote them", "b"),
                                 (f"n = {f(N['term strings as extracted'])}", "n")])[1]
    y = b + 6
    F.arrow([(sc, b), (sc, y)])
    F.label(sc + 1.5, b + 3.6, "spellings unified, synonyms merged, off-topic terms removed")
    b = F.box(LM[0], RM[1], y, [("Distinct wound-care terms", "b"),
                                 (f"n = {f(N['preferred terms in scope'])}", "n")])[1]
    split_y = b
    y_lane = b + 9
    # lane headings sit beside the arrows, not across them
    F.parts.append(f'<text x="{lc - 2:.2f}" y="{y_lane - 2.2:.2f}" font-size="{FS}" font-weight="bold" '
                   f'letter-spacing="0.25" text-anchor="end">CLASSES</text>')
    F.parts.append(f'<text x="{rc + 2:.2f}" y="{y_lane - 2.2:.2f}" font-size="{FS}" font-weight="bold" '
                   f'letter-spacing="0.25" text-anchor="start">RELATIONS</text>')
    F.arrow([(sc, split_y), (sc, split_y + 2.5), (lc, split_y + 2.5), (lc, y_lane)])
    F.arrow([(sc, split_y + 2.5), (rc, split_y + 2.5), (rc, y_lane)])

    # ---- classes lane
    yl = y_lane
    b = F.box(*LM, yl, [("Terms in 2 or more abstracts", "b"), (f"n = {f(N['terms in >= 2 abstracts'])}", "n"),
                        ("one-abstract terms are not used", "i")])[1]
    ex = [("No parent class found", "r"), (f"n = {f(N['terms without an adjudicated placement'])}", "n"),
          ("kept for later", "s")]
    yl = b + gap_for(ex); down(lc, b, yl, ex, "left", LX)
    b = F.box(*LM, yl, [("Given a parent class from", "b"), ("WONT, MILD or another ontology", "b"),
                        (f"n = {f(N['terms with an adjudicated placement'])}", "n"),
                        ("suggested by a language model,", "i"), ("checked twice, reviewed by hand", "i")])[1]
    why = N["placed terms not in the addition"]
    ex = [("Not added", "r"), (f"n = {f(sum(why.values()))}", "n"),
          (f"{f(why.get('parent class not placed itself', 0))} parent not added either", "s"),
          (f"{f(why.get('already an existing class', 0))} already in an ontology", "s"),
          (f"{f(why.get('placement inconsistent (reasoner)', 0))} contradiction (reasoner)", "s")]
    yl = b + gap_for(ex); down(lc, b, yl, ex, "left", LX)
    b_cls = F.box(*LM, yl, [("New classes", "b"), (f"n = {f(N['new classes in the addition'])}", "n"),
                            (f"{f(N['new classes from placements'])} under a checked parent", "s"),
                            (f"{f(N['new classes as curator-axiom values'])} needed by hand-written axioms", "s"),
                            ("each also gets its BFO type", "i")])[1]

    # ---- relations lane
    yr = y_lane
    b = F.box(*RM, yr, [("Relations between terms", "b"), (f"n = {f(N['relation assertions'])}", "n"),
                        ("picked out by a language model", "i")])[1]
    ex = [("Found in one abstract only", "r"),
          (f"n = {f(N['relation assertions'] - N['relations in >= 2 abstracts'])}", "n")]
    yr = b + gap_for(ex); down(rc, b, yr, ex, "right", RX)
    b = F.box(*RM, yr, [("Found in 2 or more abstracts", "b"),
                        (f"n = {f(N['relations in >= 2 abstracts'])}", "n")])[1]
    ex = [("Does not fit its terms", "r"),
          (f"n = {f(N['relations violating domain or range'] + N['relations with undetermined category'])}", "n"),
          (f"{f(N['relations violating domain or range'])} wrong kind of term", "s"),
          (f"{f(N['relations with undetermined category'])} kind of term unclear", "s")]
    yr = b + gap_for(ex); down(rc, b, yr, ex, "right", RX)
    b = F.box(*RM, yr, [("Relation fits both terms", "b"), (f"n = {f(N['relations typed consistently'])}", "n"),
                        ("checked against BFO and RO", "i")])[1]
    ex = [("Not true in every case", "r"),
          (f"n = {f(N['relations true of some instances'] + N['relations not true'])}", "n"),
          (f"{f(N['relations true of some instances'])} true only sometimes", "s"),
          (f"{f(N['relations not true'])} false", "s")]
    yr = b + gap_for(ex); down(rc, b, yr, ex, "right", RX)
    b = F.box(*RM, yr, [("True in every case", "b"), (f"n = {f(N['relations true of every instance'])}", "n"),
                        (f"{f(N['relations distinct after naming rulings'])} left after merging synonyms", "s"),
                        ("each one read by Claude", "i")])[1]
    # branch: relations on existing classes go to the curator
    cur = [("On an existing WONT class", "r"), (f"n = {f(N['relations on an existing class'])}", "n"),
           ("checked by hand (curator):", "s"),
           (f"{f(N['curator axioms'])} axioms, {f(N['curator axioms added'])} of them new,", "s"),
           (f"{f(N['curator axioms already stated'])} were already in WONT", "s")]
    hc = 2 * PAD + sum(LH_SMALL if st in "si" else LH for _, st in cur) - 0.5
    yr2 = b + hc + 4
    mid = b + 2 + hc / 2
    F.arrow([(rc, b), (rc, yr2)])
    cy0, cy1 = F.box(*RX, b + 2, cur, "curator")
    F.arrow([(rc, mid), (RX[0], mid)])
    b = F.box(*RM, yr2, [("On a new class", "b"), (f"n = {f(N['relations on a new class'])}", "n")])[1]
    lo = N["relations left out"]
    yr = b + 5
    F.arrow([(rc, b), (rc, yr)])
    wait = N.get("relations waiting for the curator", 0)
    lines = ([("Added", "b"), (f"n = {f(N['relations in the addition'])}", "n")] if N["relations in the addition"]
             else [("Waiting for curator review", "b"), (f"n = {f(wait)}", "n"), ("not added until decided", "s")])
    if N["relations in the addition"] and wait:
        lines.append((f"{f(wait)} wait for curator review", "s"))
    lines += [(f"left out: {lo['subject not in the addition']} their class not added,", "s"),
              (f"{lo['value not in the addition']} the related class not added", "s")]
    if lo["inconsistent (reasoner)"]:
        lines.append((f"{lo['inconsistent (reasoner)']} contradiction (reasoner)", "s"))
    b_rel = F.box(*RM, yr, lines, "main" if N["relations in the addition"] else "curator")[1]

    # ---- the addition
    yres = max(b_cls, b_rel, cy1) + 7
    F.arrow([(lc, b_cls), (lc, yres)])
    if N["relations in the addition"]:
        F.arrow([(rc, b_rel), (rc, yres)])
    xc = (RX[0] + RX[1]) / 2
    F.arrow([(xc, cy1), (xc, yres)])
    F.box(0, W, yres, [("Added to WONT", "b"),
                       (f"{f(N['new classes in the addition'])} new classes  ·  {f(N['subclass axioms from placements'])} "
                        f"links to a parent class  ·  {f(N['BFO category axioms'])} BFO types", "r"),
                       (f"{f(N['relations in the addition'])} relations from the abstracts  ·  "
                        if N['relations in the addition'] else "no relations from the abstracts yet  ·  "
                        f"{f(N['curator axioms added'])} hand-checked axioms on existing WONT classes  ·  "
                        + ("no contradictory classes (ELK reasoner)" if not N['unsatisfiable classes (ELK)'] else
                           f"{f(N['unsatisfiable classes (ELK)'])} contradictory classes (ELK reasoner)"), "r")], "result")
    return F.svg()


# ---------------------------------------------------------------- output
def render(svg: Path) -> list[Path]:
    """PDF and PNG through headless Chrome. Reported when it fails, never skipped quietly."""
    if not Path(CHROME).exists():
        print(f"[figure] WARNING: {CHROME} not found; only the SVG was written")
        return []
    import re
    w_mm, h_mm = (float(x) for x in re.search(r'width="([\d.]+)mm" height="([\d.]+)mm"', svg.read_text()).groups())
    page = svg.with_suffix(".render.html")
    page.write_text(f"<!doctype html><meta charset=utf-8><style>@page{{size:{w_mm}mm {h_mm}mm;margin:0}}"
                    f"html,body{{margin:0}}img{{display:block;width:{w_mm}mm;height:{h_mm}mm}}</style>"
                    f"<img src='{svg.name}'>", encoding="utf-8")
    out = []
    jobs = [(svg.with_suffix(".pdf"), ["--no-pdf-header-footer", f"--print-to-pdf={svg.with_suffix('.pdf')}"]),
            (svg.with_suffix(".png"), [f"--screenshot={svg.with_suffix('.png')}", "--force-device-scale-factor=4",
                                       f"--window-size={round(w_mm / 25.4 * 96)},{round(h_mm / 25.4 * 96)}"])]
    try:
        for target, args in jobs:
            if target.exists():
                target.unlink()
            try:
                subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                "--allow-file-access-from-files", *args, page.as_uri()],
                               capture_output=True, timeout=180)
            except subprocess.TimeoutExpired:
                pass        # Chrome often lingers after writing; the file decides
            if target.exists() and target.stat().st_size > 0:
                out.append(target)
            else:
                print(f"[figure] WARNING: Chrome did not write {target.name}")
    finally:
        page.unlink(missing_ok=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", help="redraw from a measurement JSON")
    a = ap.parse_args()
    if a.src:
        N = json.loads(Path(a.src).read_text(encoding="utf-8"))
    else:
        N = measure()
        out = ROOT / "output" / f"figure_abstracts_to_wont_{datetime.now():%Y-%m-%d_%H-%M}.json"
        out.write_text(json.dumps(N, ensure_ascii=False, indent=1), encoding="utf-8")
        if json.loads(out.read_text(encoding="utf-8")) != N:
            raise RuntimeError(f"[figure] {out} did not read back as written")
        print(f"[figure] measurement written and read back: {out.name}")
    check(N)
    svg = FIG_DIR / "abstracts_to_wont.svg"
    if svg.exists():
        bak = ROOT / "data" / "backup" / "figures"
        bak.mkdir(parents=True, exist_ok=True)
        shutil.copy2(svg, bak / f"abstracts_to_wont_{datetime.now():%Y-%m-%d_%H-%M-%S}.svg")
    text = draw(N)
    svg.write_text(text, encoding="utf-8")
    if svg.read_text(encoding="utf-8") != text:
        raise RuntimeError(f"[figure] {svg} did not read back as written")
    made = [svg, *render(svg)]
    print("[figure] written: " + ", ".join(str(m.relative_to(ROOT.parent)) for m in made))
    print(json.dumps(N, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
