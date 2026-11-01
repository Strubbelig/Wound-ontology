"""Figure: from abstracts to the classes and axioms of the WONT addition. Read-only on the pipeline.

    python scripts/figure_abstracts_to_wont.py               # measure, then draw
    python scripts/figure_abstracts_to_wont.py --from FILE   # redraw from a measurement

Every number in the figure is measured here, from the evidence store, the
term dict (TermMappingAndGate), the class hierarchy and the exported files
(rule 15). The relations lane reads only the term dict's judgements and the
core build's account of the author's axioms; until 2026-10-30 it read the
typing check's and the reading's files, which no longer exist beside the
term dict (curator: "das machst du ganz sicher nicht"). Each exclusion is checked to add up: a box that says 7,576 -> 3,114
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
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))

FIG_DIR = ROOT.parent / "Thesis" / "figures"
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
    # the author's links between two terms are placements too (rule 89), both
    # ends past the evidence cut, as the hierarchy takes them (`Orchestrator`)
    kept += [(t, c) for t, c in reg_terms.term_links()
             if min(seen.get(t, 0), seen.get(c, 0)) >= PLACEMENT_MIN_ABSTRACTS]
    placed_terms = {K(t): t for t, _ in kept}
    N["terms with an adjudicated placement"] = len(placed_terms)
    N["terms without an adjudicated placement"] = len(ge2) - len(placed_terms)

    core = rdflib.Graph().parse(ROOT / "output" / "owl" / "wont_extended_core.ttl")
    ext = rdflib.Graph().parse(ROOT / "output" / "owl" / "wont_extended.ttl")
    ids = json.loads((ROOT / "data" / "registry" / "wont_ids.json").read_text(encoding="utf-8"))["entries"]
    # new = what the pipeline added, as the build counts it (the provenance it
    # writes); a WONT id alone is not new: Injury and Traumatic injury were
    # issued by the pipeline and have been WONT's own since 2026-10-20
    from build_wont_core import PROV
    from config.settings import GROUND_TRUTH_TTL
    new_iris = {str(s) for s in core.subjects(URIRef(PROV), None) if isinstance(s, URIRef)}
    core_new = {K(core.value(URIRef(s), RDFS.label)) for s in new_iris}
    rep = json.loads((ROOT / "output" / "owl" / "core_build_report.json").read_text(encoding="utf-8"))
    # the way each core class came in, as the build recorded it: a checked
    # placement or a link of the author's, or an edge of the concept lattice the
    # head-word rule licensed (rule 79); the rest are values of the author's axioms
    entered = rep["core classes, the way they came in"]
    via_place = {K(l) for l, h in entered.items() if h == "placement"}
    via_rule = {K(l) for l, h in entered.items() if h == "head-word rule"}
    fillers = core_new - via_place - via_rule
    stray = via_place - set(placed_terms)
    if stray or len(via_place) + len(via_rule) != rep["core"] \
            or len(fillers) != rep["classes brought in as curator-axiom fillers"]:
        raise RuntimeError(f"[figure] core classes do not match the core report: {len(via_place)} by placement + "
                           f"{len(via_rule)} by the head-word rule vs {rep['core']}, {len(fillers)} fillers vs "
                           f"{rep['classes brought in as curator-axiom fillers']}; by placement but no placed term: "
                           f"{sorted(stray)[:20]}")
    from_placements = core_new & set(placed_terms)
    rule_besides = via_rule - set(placed_terms)
    N["new classes from the placed terms"] = len(from_placements)
    N["new classes by the head-word rule besides"] = len(rule_besides)
    thin = sorted(l for l, h in entered.items() if h == "head-word rule" and K(l) in rule_besides
                  and max((c for t, c in seen.items() if K(t) == K(l)), default=0) < PLACEMENT_MIN_ABSTRACTS)
    N["of them in fewer than 2 abstracts"] = len(thin)
    N["of them in fewer than 2 abstracts (list)"] = thin
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
    gt = rdflib.Graph().parse(str(GROUND_TRUTH_TTL), format="turtle")
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

    # relations lane: the term dict's judgements (rules 66, 89), read where they count
    N.update(measure_relations(p, rep, core, gt, new_iris))

    # the addition
    N["subclass axioms from placements"] = rep["placed edges"]
    N["BFO category axioms"] = rep["typing edges"]
    N["unsatisfiable classes (ELK)"] = len(rep["unsatisfiable_below_curated"]) + rep["elk_left_unsatisfiable_below_curated"]
    N["candidate classes kept apart"] = rep["candidates"]
    N["identifiers issued"] = rep["minted"]
    return N


#: a rule that moves a relation to another predicate (rule 68): not a check
RENAMES = {"tendency-not-disposition"}


def measure_relations(p, rep: dict, core, gt, new_iris: set[str]) -> dict:
    """The relations lane, every number from the term dict and the core files.

    The lane starts from what the store view keeps plus what a judgement in
    the term dict leaves out of it (the view reports those itself, with the
    cells it read them on): the relations as the abstracts state them, after
    names, scope and the schema. Each relation in 2 or more abstracts lands
    where the machine judgement that counts on it now puts it (the author's
    aside: his word is the next box), so nothing is counted twice and a check
    that ran later counts over an earlier one, as in the pipeline. The
    author's axioms are followed into the core by the build's own account."""
    from collections import defaultdict
    from rdflib import OWL, RDFS, BNode
    from wound_ontology.mappers.judgements import AUTHOR, RELATION_READER, current, rank
    from relation_typing_check import AGENT as TYPING, EVIDENCE_CUT
    tdict = p.term_mapper._term_mapping
    if p.store.terms is not tdict:
        raise RuntimeError("[figure] the store reads another term dict than the term mapper")

    def cell(s, k):
        return ((tdict.records.get(s) or {}).get("relations") or {}).get(k) or []

    # one pass of the store view: what it keeps, and what a judgement leaves
    # out, with the cells that judgement is read on (under the names the
    # abstracts wrote as well as today's)
    kept, refused, owners_of = defaultdict(set), {}, defaultdict(set)
    def note(key, s, pred, t, owners, targets, value):  # noqa: E306
        if value == 1.0 and pred != "is_a":
            refused.setdefault((s, f"{pred}: {t}"), [set(), owners, targets, pred])[0].add(key)

    def note_kept(key, s, pred, t, owners, targets, value):
        if value == 1.0 and pred != "is_a":
            owners_of[(s, f"{pred}: {t}")].update(owners)
    for key, ents in p.store.view(on_refused=note, on_kept=note_kept):
        for s, attrs in ents.items():
            for t, v in attrs.items():
                pr, _, tg = t.partition(":")
                if v == 1.0 and tg.strip() and pr.strip() != "is_a":
                    kept[(s, f"{pr.strip()}: {tg.strip()}")].add(key)
    support = {r: set(ks) for r, ks in kept.items()}
    for r, (ks, *_) in refused.items():
        support.setdefault(r, set()).update(ks)
    N: dict = {"relation assertions": len(support)}
    strong = [r for r, ks in support.items() if len(ks) >= EVIDENCE_CUT]
    N["relations in >= 2 abstracts"] = len(strong)

    def deciding_cell(r):
        """(record, key) whose judgements decide relation `r`: its own cell when the
        view keeps it, else the cell whose `no` leaves it out -- followed through a
        change of predicate (rule 68) to the cell of the new predicate."""
        if r in kept:
            return r
        _, owners, targets, pred = refused[r]
        for o in owners:
            for t in targets:
                cj = tdict.cell(o, f"{pred}: {t}")
                if cj and cj["verdict"] == "no":
                    if cj["by"] in RENAMES and "predicate changed to " in cj["why"]:
                        return o, f"{cj['why'].rsplit('predicate changed to ', 1)[1].strip()}: {t}"
                    return o, f"{pred}: {t}"
        raise RuntimeError(f"[figure] {r}: left out of the view and no cell says no")

    where = {r: deciding_cell(r) for r in strong}

    def fate(r):
        """A machine `no` that counts leaves the relation out; otherwise the
        reading's answer decides -- a `yes` of the typing check or of ELK only
        says it has no objection, however late it came."""
        js = cell(*where[r])
        mc = current([j for j in js if rank(j) != AUTHOR])
        if mc and mc["verdict"] == "no" and mc["by"] != RELATION_READER:
            return {"elk": "contradiction (reasoner)", TYPING: "wrong kind of term"}.get(
                mc["by"], "same as a relation the author refused")
        # a kept relation is read wherever any of its cells carries the reading
        # (a spelling of either end), as the axioms count it
        pred_, _, t_ = r[1].partition(":")
        over = sorted((j for c in tdict.relation_cells(owners_of[r] | {r[0]}, pred_.strip(), t_.strip())
                       for j in cell(*c)), key=lambda j: j.get("when") or "") if r in kept else js
        read = current([j for j in over if j["by"] == RELATION_READER])
        if read:
            return f"read: {read['verdict']}"
        typed = [j for j in js if j["by"] == TYPING]
        if any(rank(j) == AUTHOR for j in js):
            return "decided by the author alone"      # never read: his word decides it
        if not typed:
            raise RuntimeError(f"[figure] {r} ({where[r]}): in the store view and never checked by {TYPING}")
        return {"undecided": "kind of term unclear", "yes": "passed, not read yet"}[typed[-1]["verdict"]]

    fates = {r: fate(r) for r in strong}
    N["relations by the judgement that counts"] = dict(Counter(fates.values()))
    read_yes = {r for r, f in fates.items() if f == "read: yes"}
    N["relations read"] = sum(1 for f in fates.values() if f.startswith("read"))
    N["relations true of every instance"] = len(read_yes)
    N["relations not true of every instance"] = N["relations read"] - len(read_yes)

    def author_said(c):
        a = current([j for j in cell(*c) if rank(j) == AUTHOR])
        return a and a["verdict"]
    said = {where[r]: author_said(where[r]) for r in read_yes}
    if len(said) != len(read_yes):
        raise RuntimeError("[figure] two relations read as true are decided on one cell")
    N["read true, confirmed by the author"] = sum(v == "yes" for v in said.values())
    N["read true, left out by the author"] = sum(v == "no" for v in said.values())
    N["read true, awaiting the author"] = sum(v is None for v in said.values())
    author_yes = {(subj, f"{pr}: {t}") for subj, pr, t, j in tdict.author_relations() if j["verdict"] == "yes"}
    N["author axioms"] = len(author_yes)
    N["author axioms beyond the reading"] = len(author_yes - {c for c, v in said.items() if v == "yes"})

    account = rep["author axioms (account)"]
    rel_acc = [a for a in account if a["property_iri"]]
    if len(rel_acc) != len(author_yes):
        raise RuntimeError(f"[figure] the build accounts for {len(rel_acc)} relation axioms of the author, "
                           f"the term dict holds {len(author_yes)}")
    out = Counter(a["outcome"] for a in rel_acc)
    N["author axioms by outcome"] = dict(out)
    links = Counter(a["outcome"] for a in account if not a["property_iri"])
    N["author links between terms by outcome"] = dict(links)

    def canon(g, n):                     # a class expression compared by content, not by blank node
        return str(n) if not isinstance(n, BNode) else tuple(sorted((str(q), canon(g, o)) for q, o in g.predicate_objects(n)))

    def restrictions(g):
        return {(str(c), str(g.value(b, OWL.onProperty)), canon(g, g.value(b, OWL.someValuesFrom)))
                for c, b in g.subject_objects(RDFS.subClassOf)
                if isinstance(b, BNode) and g.value(b, OWL.someValuesFrom) is not None}
    beyond = restrictions(core) - restrictions(gt)
    on_new = sum(1 for c, _, _ in beyond if c in new_iris)
    N["relations added"] = len(beyond)
    N["relations added on a new class"] = on_new
    N["relations added on a WONT class"] = len(beyond) - on_new
    if len(beyond) != out["added"] + out["already built"]:
        raise RuntimeError(f"[figure] the core states {len(beyond)} relations beyond WONT, the build's account "
                           f"{out['added']} added + {out['already built']} already built")
    if out["already built"] != rep.get("relations kept", 0):
        raise RuntimeError(f"[figure] {out['already built']} of the author's axioms were already built, the "
                           f"build kept {rep.get('relations kept', 0)} relations from the extension")
    N["links added"] = links["added"]
    N["relations held for the author"] = rep.get("relations held for the curator", 0)
    return N


def check(N: dict) -> None:
    """The arithmetic the figure shows. A box that does not add up is not drawn."""
    eq = [
        (N["terms in >= 2 abstracts"], N["terms with an adjudicated placement"] + N["terms without an adjudicated placement"]),
        (N["terms with an adjudicated placement"], N["new classes from the placed terms"]
         + sum(N["placed terms not in the addition"].values())),
        (N["new classes in the addition"], N["new classes from the placed terms"]
         + N["new classes by the head-word rule besides"] + N["new classes as curator-axiom values"]),
        # the head-word rule's edges clear the evidence cut too (rule 79, curator 2026-10-30: "ja")
        (N["of them in fewer than 2 abstracts"], 0),
        (N["relations in >= 2 abstracts"], sum(N["relations by the judgement that counts"].values())),
        (N["relations read"], N["relations true of every instance"] + N["relations not true of every instance"]),
        (N["relations true of every instance"], N["read true, confirmed by the author"]
         + N["read true, left out by the author"] + N["read true, awaiting the author"]),
        (N["author axioms"], N["read true, confirmed by the author"] + N["author axioms beyond the reading"]),
        (N["author axioms"], sum(N["author axioms by outcome"].values())),
        (N["relations added"], N["author axioms by outcome"].get("added", 0)
         + N["author axioms by outcome"].get("already built", 0)),
        (N["relations added"], N["relations added on a new class"] + N["relations added on a WONT class"]),
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
    hgt_ = lambda ls: 2 * PAD + sum(LH_SMALL if st in "si" else LH for _, st in ls) - 0.5  # noqa: E731
    besides = N["new classes by the head-word rule besides"] + N["new classes as curator-axiom values"]
    inn = [("Came in besides", "r"), (f"n = {f(besides)}", "n"),
           (f"{f(N['new classes by the head-word rule besides'])} by the head-word rule,", "s"),
           (f"{f(N['new classes as curator-axiom values'])} values of the author's axioms", "s")]
    top_ex = b + 2
    top_in = top_ex + hgt_(ex) + 2.5
    yl = top_in + hgt_(inn) + 2
    F.arrow([(lc, b), (lc, yl)])
    t0, t1 = F.box(*LX, top_ex, ex, "excl")
    F.arrow([(lc, (t0 + t1) / 2), (LX[1], (t0 + t1) / 2)])
    F.box(*LX, top_in, inn, "curator")
    F.arrow([(LX[1], top_in + hgt_(inn) / 2), (lc - 0.4, top_in + hgt_(inn) / 2)])
    b_cls = F.box(*LM, yl, [("New classes", "b"), (f"n = {f(N['new classes in the addition'])}", "n"),
                            (f"{f(N['new classes from the placed terms'])} from the placed terms", "s"),
                            (f"{f(besides)} came in besides", "s"),
                            ("each also gets its BFO type", "i")])[1]

    # ---- relations lane
    def excl_box(y0, lines):
        """An exclusion box hanging right of the lane, its top at y0; returns its bottom."""
        top, bot = F.box(*RX, y0, lines, "excl")
        F.arrow([(rc, (top + bot) / 2), (RX[0], (top + bot) / 2)])
        return bot

    yr = y_lane
    b = F.box(*RM, yr, [("Relations between terms", "b"), (f"n = {f(N['relation assertions'])}", "n"),
                        ("picked out by a language model", "i")])[1]
    ex = [("Found in one abstract only", "r"),
          (f"n = {f(N['relation assertions'] - N['relations in >= 2 abstracts'])}", "n")]
    yr = b + gap_for(ex); down(rc, b, yr, ex, "right", RX)
    b = F.box(*RM, yr, [("Found in 2 or more abstracts", "b"),
                        (f"n = {f(N['relations in >= 2 abstracts'])}", "n")])[1]
    fate = N["relations by the judgement that counts"]
    why_not = [("wrong kind of term", "wrong kind of term"), ("kind of term unclear", "kind of term unclear"),
               ("contradiction (reasoner)", "contradiction (reasoner)"),
               ("same as a relation the author refused", "like one the author refused"),
               ("passed, not read yet", "not read yet"),
               ("decided by the author alone", "decided by the author")]
    ex = [("Not read", "r"), (f"n = {f(N['relations in >= 2 abstracts'] - N['relations read'])}", "n")] + \
         [(f"{f(fate[k])} {text}", "s") for k, text in why_not if fate.get(k)]
    yr = b + gap_for(ex); down(rc, b, yr, ex, "right", RX)
    b = F.box(*RM, yr, [("Read by Claude", "b"), (f"n = {f(N['relations read'])}", "n"),
                        ("is it true of every instance?", "i")])[1]
    ex = [("Not true of every instance", "r"), (f"n = {f(N['relations not true of every instance'])}", "n")]
    yr = b + gap_for(ex); down(rc, b, yr, ex, "right", RX)
    b = F.box(*RM, yr, [("True of every instance", "b"), (f"n = {f(N['relations true of every instance'])}", "n")])[1]
    # the author: he leaves some out, has not decided others, and adds axioms of his own
    ex = [("Not taken up", "r"),
          (f"n = {f(N['read true, left out by the author'] + N['read true, awaiting the author'])}", "n"),
          (f"{f(N['read true, left out by the author'])} left out by the author", "s"),
          (f"{f(N['read true, awaiting the author'])} await the author", "s")]
    cur = [("Added by the author alone", "r"), (f"n = {f(N['author axioms beyond the reading'])}", "n"),
           ("his own axioms, and relations", "s"), ("the reading did not pass", "s")]
    hgt = lambda ls: 2 * PAD + sum(LH_SMALL if st in "si" else LH for _, st in ls) - 0.5  # noqa: E731
    top_ex = b + 2
    top_cur = top_ex + hgt(ex) + 2.5
    yr = top_cur + hgt(cur) + 2
    F.arrow([(rc, b), (rc, yr)])
    excl_box(top_ex, ex)
    F.box(*RX, top_cur, cur, "curator")
    F.arrow([(RX[0], top_cur + hgt(cur) / 2), (rc + 0.4, top_cur + hgt(cur) / 2)])
    b = F.box(*RM, yr, [("Axioms the author decided", "b"), (f"n = {f(N['author axioms'])}", "n"),
                        (f"{f(N['read true, confirmed by the author'])} confirmed from the reading", "s"),
                        (f"{f(N['author axioms beyond the reading'])} added by him alone", "s")])[1]
    out = N["author axioms by outcome"]
    ex = [("Not added", "r"), (f"n = {f(out.get('already in WONT', 0) + out.get('not built', 0))}", "n"),
          (f"{f(out.get('already in WONT', 0))} already in WONT", "s"),
          (f"{f(out.get('not built', 0))} no class to carry them", "s")]
    yr = b + gap_for(ex); down(rc, b, yr, ex, "right", RX)
    b_rel = F.box(*RM, yr, [("Added", "b"), (f"n = {f(N['relations added'])}", "n"),
                            (f"{f(N['relations added on a new class'])} on new classes", "s"),
                            (f"{f(N['relations added on a WONT class'])} on WONT classes", "s")])[1]

    # ---- the addition
    yres = max(b_cls, b_rel) + 7
    F.arrow([(lc, b_cls), (lc, yres)])
    F.arrow([(rc, b_rel), (rc, yres)])
    links = N["links added"]
    F.box(0, W, yres, [("Added to WONT", "b"),
                       (f"{f(N['new classes in the addition'])} new classes  ·  {f(N['subclass axioms from placements'])} "
                        f"links to a parent class  ·  {f(N['BFO category axioms'])} BFO types", "r"),
                       (f"{f(N['relations added'])} relations  ·  "
                        + (f"{f(links)} link{'s' if links != 1 else ''} between two terms by the author  ·  " if links else "")
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
