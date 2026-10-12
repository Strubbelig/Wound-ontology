"""Fill the FCA context's gaps with a strong model, on one subtree. Sandbox only.

    python -u scripts/fca_fill_trial.py [--root "Chronic Wound"] [--model anthropic/claude-opus-5.5]
                                        [--budget-usd 3]

Curator, 2026-10-02: "try using a good model to fill fca gaps. Try a subtree
and show me the numbers." The Wound context (closed world, >= 2 abstracts,
class-level inheritance, rule 65) is built as `run_fca` builds it; its rows are
restricted to the subtree, its columns stay the 94 measured attributes of the
whole Wound subtree (the subtree's own would be a handful). For every class
the model rules on EVERY measured attribute, stated or not:

  all     -- holds of every (or essentially every) instance: a class-level property
  some    -- holds of some instances, not characteristic of the class
  no      -- does not hold, does not apply, or is not a sensible statement
  unsure

Cells the abstracts state are asked too, so the model's agreement with the
evidence is measured, not assumed. The filled context is: stated in >= 2
abstracts, or `all`. Nothing is written into the store (rule 33: the store is
what abstracts say); the verdicts go to
`data/review/fca_fill_trial_<root>_2026-10-02.json`, read back.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

PREDICATES = ["has_quality", "part_of", "has_participant", "has_disposition", "inheres_in"]
MIN_SUPPORT = 2
ANSWERS = ("all", "some", "no", "unsure")


class Ruling(BaseModel):
    answers: dict[str, str]


def _opt(argv, flag, default):
    return argv[argv.index(flag) + 1] if flag in argv else default


def _slug(s):
    return "".join(c if c.isalnum() else "_" for c in s.lower()).strip("_")


def prompt_for(cls, parents, attrs):
    lines = "\n".join(f"{i}. {a}" for i, a in enumerate(attrs, 1))
    return (
        "You are a wound-care clinician and ontologist. Below is one class from a wound "
        f"ontology and a numbered list of candidate statements about it.\n\n"
        f'Class: "{cls}"' + (f" (a kind of: {', '.join(parents)})" if parents else "") + "\n\n"
        "Each statement reads `predicate: value` about the class: has_quality = instances bear "
        "this quality or measurable feature; part_of = instances are located in / part of the "
        "value; has_disposition = instances have this tendency or risk; has_participant = this "
        "takes part in instances; inheres_in = instances inhere in the value.\n\n"
        "For EVERY number answer exactly one of:\n"
        "  all    -- true of every (or essentially every) instance of the class; a property of the class itself\n"
        "  some   -- true of some instances, but not characteristic of the class\n"
        "  no     -- false, not applicable, or not a sensible statement about this class "
        "(for example a wound being part of another kind of wound)\n"
        "  unsure -- you cannot tell\n\n"
        f"{lines}\n\n"
        'Return {"answers": {"1": "all", "2": "no", ...}} with every number.'
    )


def lattice_numbers(objs, cols, rows, below, subtrees, root):
    """concepts and new groupings of a boolean context (same definition as rule 65)."""
    from concepts import Context
    lat = Context(objs, cols, rows).lattice
    groupings = []
    for c in lat:
        ext = frozenset(c.extent)
        measured = [a for a in c.intent if not a.startswith("is_a:")]
        maximal = [o for o in ext if not (below[o] & ext)]
        if len(ext) < 2 or ext in subtrees or not measured or root in ext or len(maximal) < 2:
            continue
        groupings.append({"extent": sorted(ext), "maximal": sorted(maximal), "intent": sorted(measured)})
    return len(lat), groupings


def main(argv: list[str]) -> int:
    from config.settings import ALLOWED_PREDICATES, BASE_PATH, ENTREZ_EMAIL
    from p4_verify_placements import _usage
    from wound_ontology.llm.llm_client import LLMClient
    from wound_ontology.orchestrator import Orchestrator
    from wound_ontology.store.concept_store import records_of
    from wound_ontology.utils.string_utils import smart_title
    import os

    root = _opt(argv, "--root", "Chronic Wound")
    model = _opt(argv, "--model", "anthropic/claude-opus-5.5")
    budget = float(_opt(argv, "--budget-usd", "3"))
    out = ROOT / "data" / "review" / f"fca_fill_trial_{_slug(root)}_2026-10-02.json"

    p = Orchestrator(entrez_email=ENTREZ_EMAIL, allowed_predicates=ALLOWED_PREDICATES, base_path=BASE_PATH)
    hier = p.class_hier
    p.run_fca(subtree_root="Wound", predicates=PREDICATES, min_support=MIN_SUPPORT,
              inherit="class_level", unknown="absent", name=False)
    df = p.context_matrix.df.fillna(0.0)
    measured = [a for a in p.context_matrix.attributes if not a.startswith("is_a:")]
    isa = [a for a in p.context_matrix.attributes if a.startswith("is_a:")]
    sub = {smart_title(x) for x in hier.subtree_of(root)}
    objs = sorted(o for o in df.index if o in sub)
    print(f"[fill] subtree {root!r}: {len(sub)} classes, {len(objs)} in the context; "
          f"{len(measured)} measured attributes -> {len(objs) * len(measured):,} cells to rule on", flush=True)

    support = defaultdict(lambda: defaultdict(int))
    for _, ents in records_of(p.store):
        for e, attrs in ents.items():
            for t, v in attrs.items():
                if v == 1.0 and ":" in str(t):
                    pr, tg = t.split(":", 1)
                    if pr.strip().lower() in PREDICATES:
                        support[smart_title(e)][f"{pr.strip().lower()}: {tg.strip()}".lower()] += 1
    own = {o: {a for a in measured if support[o].get(a, 0) >= MIN_SUPPORT} for o in objs}

    done = {}
    if out.exists():
        done = json.loads(out.read_text(encoding="utf-8")).get("verdicts", {})
    todo = [o for o in objs if o not in done]
    llm = LLMClient(os.environ["OPENROUTER_API_KEY"], model_id=model)
    sem = asyncio.Semaphore(int(_opt(argv, "--concurrency", "8")))
    failed = []
    u0 = _usage()

    async def ask(o):
        parents = [smart_title(x) for x in hier.parents_of(o)]
        async with sem:
            try:
                res = await llm._execute_with_retry(llm._call_json, prompt_for(o, parents, measured), Ruling,
                                                    temperature=0.0, timeout=400, max_tokens=6000)
            except Exception as exc:
                failed.append(o)
                print(f"[fill]   {o}: FAILED {type(exc).__name__}: {exc}", flush=True)
                return
        got = {}
        for k, v in res.answers.items():
            try:
                i = int(str(k).strip().rstrip("."))
            except ValueError:
                continue
            v = str(v).strip().lower()
            if 1 <= i <= len(measured) and v in ANSWERS:
                got[measured[i - 1]] = v
        missing = len(measured) - len(got)
        if missing:
            print(f"[fill]   {o}: {missing} attribute(s) not ruled on -> counted as unsure", flush=True)
        done[o] = {a: got.get(a, "unsure") for a in measured}

    async def drive():
        for i in range(0, len(todo), 8):
            await asyncio.gather(*(ask(o) for o in todo[i:i + 8]))
            spent = _usage() - u0
            n = min(i + 8, len(todo))
            print(f"[fill]   {n}/{len(todo)} classes, ${spent:.2f}", flush=True)
            out.write_text(json.dumps({"verdicts": done}, ensure_ascii=False), encoding="utf-8")
            if n < len(todo) and spent * len(todo) / n > budget:
                print(f"[fill] STOP: projected ${spent * len(todo) / n:.2f} > budget ${budget:.2f}", flush=True)
                return

    t0 = time.time()
    asyncio.run(drive())
    spent = _usage() - u0
    if failed or any(o not in done for o in objs):
        print(f"[fill] {len([o for o in objs if o not in done])} class(es) without verdicts: "
              f"{[o for o in objs if o not in done][:10]} -- numbers below cover the rest only", flush=True)
    objs = [o for o in objs if o in done]

    # ── the numbers ──
    inherited = {o: {a for a in measured if df.loc[o, a] == 1.0} - own[o] for o in objs}
    tally = Counter(v for o in objs for v in done[o].values())
    def rate(cells):
        c = Counter(done[o][a] for o, a in cells)
        n = sum(c.values()) or 1
        return {k: c[k] for k in ANSWERS} | {"n": sum(c.values()), "all_share": round(c["all"] / n, 3)}
    stated = [(o, a) for o in objs for a in own[o]]
    inh = [(o, a) for o in objs for a in inherited[o]]
    unstated = [(o, a) for o in objs for a in measured if a not in own[o] and a not in inherited[o]]
    per_attr = sorted(((a, sum(done[o][a] == "all" for o in objs)) for a in measured), key=lambda x: -x[1])

    below = {o: {smart_title(x) for x in hier.ancestors_of(o)} for o in objs}
    oset = set(objs)
    subtrees = set()
    for c in sub:
        full = frozenset(smart_title(d) for d in hier.subtree_of(c)) & oset
        subtrees |= {full, full - {c}}
    cols = isa + measured
    ctx = {
        "abstracts only": {o: own[o] for o in objs},
        "abstracts + class-level inheritance (current)": {o: own[o] | inherited[o] for o in objs},
        "abstracts + model 'all'": {o: own[o] | {a for a in measured if done[o][a] == "all"} for o in objs},
    }
    lattices = {}
    for name, cells in ctx.items():
        rows = [tuple(bool(df.loc[o, a] == 1.0) if a.startswith("is_a:") else (a in cells[o]) for a in cols)
                for o in objs]
        n_con, groups = lattice_numbers(objs, cols, rows, below, subtrees, smart_title(root))
        lattices[name] = {"true_cells": sum(len(v) for v in cells.values()), "concepts": n_con,
                          "new_groupings": len(groups),
                          "groupings": sorted(groups, key=lambda g: -len(g["maximal"]))}

    result = {"root": root, "model": model, "cost_usd": round(spent, 2), "seconds": round(time.time() - t0),
              "classes": len(objs), "attributes": len(measured), "answers": dict(tally),
              "on_cells_the_abstracts_state": rate(stated),
              "on_cells_class_level_inheritance_adds": rate(inh),
              "on_cells_nobody_states": rate(unstated),
              "attributes_by_all": per_attr, "lattices": lattices, "verdicts": done}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(out.read_text(encoding="utf-8"))
    assert set(back["verdicts"]) == set(objs) and back["lattices"].keys() == lattices.keys()
    print(f"\n[fill] written and read back: {out.relative_to(ROOT)}  (${spent:.2f}, {result['seconds']}s, {model})")
    print(f"[fill] answers over {len(objs)} classes x {len(measured)} attributes: {dict(tally)}")
    for k in ("on_cells_the_abstracts_state", "on_cells_class_level_inheritance_adds", "on_cells_nobody_states"):
        print(f"[fill]   {k}: {result[k]}")
    print("[fill] attributes the model calls class-level most often:",
          [(a, n) for a, n in per_attr[:15]])
    for name, l in lattices.items():
        print(f"[fill] {name:48} true cells {l['true_cells']:5}  concepts {l['concepts']:4}  "
              f"new groupings {l['new_groupings']:3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
