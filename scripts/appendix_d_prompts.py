"""Write out the exact text of every prompt the thesis runs sent, for Anhang D.

    python scripts/appendix_d_prompts.py

Nothing is sent. Each prompt is built by the code that built it in the runs and
caught at the last step before the network: the OpenAI client's `create` for
everything that goes through `LLMClient._call_json` (which appends the JSON
schema of the expected answer), `_call_haiku` for the PubMed query validator.
The text in the appendix is therefore the text the code produces, not a copy
someone kept in step by hand.

Variable parts are filled with placeholders in angle brackets (`<term 1>`), so
the fixed wording and the place where the data goes are both visible. Where the
prompt depends on BFO categories (the licensing table of stage 2, the category
gloss in naming), real category names are used, because the text is looked up
from them.

The extraction ran on 2026-09-18 with the schema of commit 414bf98. The schema
was regenerated afterwards (2026-10-24, adding `temporal region`), so the
stage-1 and stage-2 prompts are built from that commit's
`extraction_models.py`, read from git. Every other prompt builder is unchanged
since its runs (checked 2026-10-29 by comparing the prompt strings across the
run-time commits).

Writes `output/appendix_d_prompts.json` ({key: {text, temperature, max_tokens,
model}}) and one `output/appendix_d_prompts/<key>.txt` per prompt.
"""
from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "output" / "appendix_d_prompts.json"
EXTRACTION_SCHEMA_COMMIT = "414bf98"
SCHEMA_SUFFIX = "Respond with valid JSON only — no markdown fences — matching this schema exactly:"


class Captured(BaseException):
    """Raised in place of the network call; BaseException so no retry loop eats it."""


def _fake_client(sink: dict):
    async def create(**kw):
        sink.update(text=kw["messages"][0]["content"], temperature=kw.get("temperature"),
                    max_tokens=kw.get("max_tokens"), model=kw.get("model"))
        raise Captured
    completions = types.SimpleNamespace(create=create)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions), api_key="x")


def capture(llm, coro_fn) -> dict:
    sink: dict = {}
    llm._client = _fake_client(sink)
    try:
        asyncio.run(coro_fn())
    except Captured:
        pass
    assert sink, "nothing reached the client: the prompt was not sent the way this script assumes"
    return sink


def _old_extraction_models():
    """The generated schema as it was when the extraction ran."""
    src = subprocess.run(
        ["git", "show", f"{EXTRACTION_SCHEMA_COMMIT}:src/wound_ontology/llm/extraction_models.py"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout
    mod = types.ModuleType("wound_ontology.llm.extraction_models")
    mod.__file__ = f"<git {EXTRACTION_SCHEMA_COMMIT}>"
    sys.modules[mod.__name__] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


def _script_prompt(script: str, models: tuple[str, ...], **closure):
    """`prompt_for` and the answer schema of a p4 script, without running its main()."""
    tree = ast.parse((ROOT / "scripts" / script).read_text(encoding="utf-8"))
    keep = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in models]
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "prompt_for")
    mod = ast.Module(body=keep + [fn], type_ignores=[])
    ns = {"BaseModel": __import__("pydantic").BaseModel, "Optional": __import__("typing").Optional,
          **closure}
    exec(compile(ast.fix_missing_locations(mod), script, "exec"), ns)
    for m in models:   # the classes refer to each other through this namespace, not a module
        ns[m].model_rebuild(_types_namespace=ns)
    return ns["prompt_for"], ns[models[-1]]


def main() -> int:
    from wound_ontology.llm.llm_client import LLMClient

    llm = LLMClient(api_key="x")
    out: dict[str, dict] = {}

    # ── Extraction, with the September schema ────────────────────────────────
    _old_extraction_models()
    from wound_ontology.llm import extraction_prompt
    from wound_ontology.llm.schemas import RelationResponse, TypingResponse
    out["extraction_stage1"] = capture(llm, lambda: llm._call_json(
        extraction_prompt.typing_prompt("<title and abstract of one paper>"),
        TypingResponse, timeout=240))
    typed = {"<term 1>": "material entity", "<term 2>": "process", "<term 3>": "quality"}
    out["extraction_stage2"] = capture(llm, lambda: llm._call_json(
        extraction_prompt.relation_prompt("<title and abstract of one paper>", typed),
        RelationResponse, timeout=240))
    # The rest uses the current schema module again.
    del sys.modules["wound_ontology.llm.extraction_models"]
    import wound_ontology.llm.extraction_models as em

    # ── Scope ────────────────────────────────────────────────────────────────
    out["scope"] = capture(llm, lambda: llm.gate_scope_batch([
        ("<term 1>", "<n>", ["<attribute 1>", "<attribute 2>"]),
        ("<term 2>", "<n>", []),
    ]))

    # ── Synonym judgement (first and second opinion use the same prompt) ─────
    out["synonyms"] = capture(llm, lambda: llm.adjudicate_mappings_batch([
        {"store_term": "<store term 1>", "ontology_class": "<ontology class 1>",
         "store_category": "<category>", "ontology_category": "<category>",
         "ontology_definition": "<definition of the class>"},
        {"store_term": "<store term 2>", "ontology_class": "<ontology class 2>",
         "store_category": "<category>", "ontology_category": "<category>",
         "ontology_parents": ["<parent class>"]},
        {"store_term": "<store term 3>", "ontology_class": "<ontology class 3>"},
    ]))

    # ── Naming of the FCA concepts ───────────────────────────────────────────
    em.CATEGORY_GLOSS.setdefault("<category>", "<the gloss of that category, as in stage 1>")
    out["naming"] = capture(llm, lambda: llm.generate_semantic_name(
        ["<attribute 1>", "<attribute 2>"], {"<name already used>"},
        extent_categories=("<category>",), parent_names=("<parent class>",),
        differentia=("<attribute 2>",), extent_sample=("<member 1>", "<member 2>")))
    out["naming_top_level"] = capture(llm, lambda: llm.generate_semantic_name(
        ["<attribute 1>", "<attribute 2>"], {"<name already used>"},
        extent_categories=("<category>",), extent_sample=("<member 1>", "<member 2>")))

    # ── Placement and its two checks (p4 scripts) ────────────────────────────
    cands = {"<term 1>": [("<candidate 1>", "", "", "<definition, first 110 characters>"),
                          ("<candidate 2>", "", "", "")]}
    prompt_for, schema = _script_prompt("p4_place_terms.py", ("Placement", "PlacementBatch"), cands=cands)
    out["placement"] = capture(llm, lambda: llm._call_json(
        prompt_for([("<term 1>", "<category>", "<n>")]), schema, temperature=0.0,
        timeout=360, max_tokens=llm.BATCH_MAX_TOKENS))
    prompt_for, schema = _script_prompt("p4_verify_placements.py", ("Verdict", "VerdictBatch"))
    out["placement_check"] = capture(llm, lambda: llm._call_json(prompt_for([
        {"id": "<id 1>", "relation": "is_a", "term": "<term 1>", "parent": "<class 1>", "category": "<category>"},
        {"id": "<id 2>", "relation": "same", "term": "<term 2>", "parent": "<class 2>", "category": "<category>"},
    ]), schema, temperature=0.0, timeout=600, max_tokens=8000))
    prompt_for, schema = _script_prompt("p4_restatement_check.py", ("Verdict", "VerdictBatch"))
    out["restatement_check"] = capture(llm, lambda: llm._call_json(prompt_for([
        {"id": "<id 1>", "term": "<term 1>", "class": "<class 1>"},
    ]), schema, temperature=0.0, timeout=600, max_tokens=8000))

    # ── PubMed query validator (sent directly, not through _call_json) ───────
    from wound_ontology.connectors import pubmed_query_validator as pv
    val = pv.PubMedQueryValidator(entrez_email="x", api_key="x")
    for key, call in (
        ("query_check", lambda: val._evaluate("<PubMed query>", [
            {"title": "<title 1>", "abstract": "<abstract 1>"},
            {"title": "<title 2>", "abstract": "<abstract 2>"}])),
        ("query_revision", lambda: val._revise("<PubMed query>", "<problem named by the check>")),
    ):
        sink = {}
        def _haiku(prompt, sink=sink):
            sink.update(text=prompt, temperature=None, max_tokens=512, model=pv._OPENROUTER_MODEL)
            raise Captured
        val._call_haiku = _haiku
        try:
            call()
        except Captured:
            pass
        assert sink, key
        out[key] = sink

    # ── Claude Opus 5.5 as pipeline steps (2026-10-29) ──────────────────────
    # Built by the scripts that send them (OpenRouter batch, Anthropic Messages
    # body). The answer schema goes separately, as `output_config.format`, so it
    # is printed after the prompt; Claude Opus 5.5 takes no temperature.
    sys.path.insert(0, str(ROOT / "scripts"))
    import claude_read_placements as crp
    import claude_read_small as crs
    import claude_read_universality as cru
    from wound_ontology.llm.claude_batch import MODEL as CLAUDE

    def claude(prompt: str, schema: dict) -> dict:
        return {"text": prompt + "\n\nThe answer is constrained to this JSON schema (output_config.format):\n"
                + json.dumps(schema, indent=1),
                "temperature": None, "max_tokens": 12000,
                "model": f"{CLAUDE} (adaptive thinking, effort high, OpenRouter batch)"}

    cls = {"label": "<class 1>", "category": "<category>", "parent": "<parent class>",
           "definition": "<definition, first 220 characters>"}
    out["claude_placement"] = claude(crp.placement_prompt([
        {"row": 1, "term": "<term 1>", "category": "<category>", "abstracts": "<n>", "relation": "is_a",
         "proposed": 1, "reason": "<the first model's reason>",
         "offered": [cls, dict(cls, label="<class 2>", definition="")]}]), crp.SCHEMA)
    out["claude_universality"] = claude(cru.universality_prompt([
        {"row": 1, "subject": "<C>", "predicate": "<relation>", "value": "<T>", "abstracts": "<n>",
         "subject_info": {"category": "<category>", "definition": "<definition of C, where it is a class>"},
         "value_info": {"category": "<category>", "definition": ""}}],
        {"<relation>": "<label (identifier): its definition in RO, BFO, OBI, IAO or MILD>"}), cru.SCHEMA)
    out["claude_restatement"] = claude(crs.restate_prompt([
        {"row": 1, "term": "<term 1>", "abstracts": "<n>", "class": "<class 1>", "class_category": "<category>",
         "definition": "<definition of the class>", "answer": "same", "reason": "<the check's reason>"}]),
        crs.RESTATE_SCHEMA)
    out["claude_same_type"] = claude(crs.same_type_prompt([
        {"row": 1, "subject": "<subject>", "predicate": "<relation>", "object": "<object>",
         "why": "<the earlier reading, quoting the author's decision>"}]), crs.SAME_TYPE_SCHEMA)

    # The LLMClient builders write their prompts as triple-quoted strings
    # indented by 8 spaces; that indentation is sent too, but it is source
    # layout, not wording. Inserted data lines carry none, so `textwrap.dedent`
    # would find no common prefix: the 8 spaces are taken off where present.
    # The JSON schema appended by `_call_json` is left as it is.
    for k, v in out.items():
        head, sep, tail = v["text"].partition(SCHEMA_SUFFIX)
        lines = head.split("\n")
        if k in ("scope", "synonyms", "naming", "naming_top_level"):
            lines = [l[8:] if l.startswith(" " * 8) else l for l in lines]
        head = "\n".join(l.rstrip() for l in lines).strip("\n")
        v["text"] = head + ("\n\n" + sep + tail if sep else "")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    folder = OUT.with_suffix("")
    folder.mkdir(exist_ok=True)
    for k, v in out.items():
        (folder / f"{k}.txt").write_text(v["text"] + "\n", encoding="utf-8")
    for k, v in out.items():
        print(f"{k:20s} {len(v['text']):6,} chars  T={v['temperature']}  max_tokens={v['max_tokens']}")
    print(f"wrote {OUT.relative_to(ROOT)} and {folder.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
