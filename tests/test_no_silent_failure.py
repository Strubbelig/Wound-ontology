"""Nothing is allowed to go wrong silently.

Every serious defect found in this project was quiet, not loud:
``bool(float('nan')) is True`` corrupting the FCA lattice while runs reported
success; ~11,800 relations discarded at OWL export with no message; a local
``part_of`` invented when BFO's could not be found; classes minted into the
retired ``WOND_`` namespace; the reasoner gate reading its edges from an empty
provenance dict and reporting a clean result after inspecting nothing.

These tests pin the loudness itself, not the behaviour underneath it.
"""

from __future__ import annotations

import ast
import pathlib
import warnings

import pandas as pd
import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "wound_ontology"


# ── static: no handler may swallow without telling anyone ───────────────────

def _reports(node: ast.AST) -> bool:
    """Does this handler tell anyone — by raising, printing, or recording?"""
    for n in ast.walk(node):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", "") or getattr(n.func, "attr", "")
            if name in {"print", "warn", "warning", "error", "exception",
                        "critical", "info", "append", "add"}:
                return True
    return False


def _is_availability_guard(node: ast.ExceptHandler) -> bool:
    """`except ImportError: X = <fallback>` and friends.

    Not a runtime failure — it answers "is this optional thing present at all",
    and the body binds a concrete default. The one case that genuinely WAS a
    failure (an empty _PREDICATE_DEFINITIONS stripping every rule out of the
    extraction prompt) now warns, so it no longer matches this shape.
    """
    t = node.type
    names: set[str] = set()
    if isinstance(t, ast.Name):
        names = {t.id}
    elif isinstance(t, ast.Tuple):
        names = {e.id for e in t.elts if isinstance(e, ast.Name)}
    if not names or not names <= {"ImportError", "ModuleNotFoundError",
                                  "FileNotFoundError", "AttributeError"}:
        return False
    return all(isinstance(n, (ast.Assign, ast.AnnAssign, ast.Pass)) for n in node.body)


def _returns_an_error_value(node: ast.ExceptHandler) -> bool:
    """Returns a result object that itself carries the failure (verdict=ERROR)."""
    for n in node.body:
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Call):
            for kw in n.value.keywords:
                if kw.arg in {"verdict", "status", "error", "reason"}:
                    return True
    return False


def _handler_is_mute(node: ast.ExceptHandler) -> bool:
    if node.type is None:
        return True                     # a bare `except:` is never acceptable
    return not (_reports(node)
                or _is_availability_guard(node)
                or _returns_an_error_value(node))


#: The only place a silent handler is permitted, with its justification.
ALLOWED_MUTE = {
    # `int(iri.split("WOND_")[1])` — a ValueError here means "this IRI has no
    # numeric suffix", so the predicate's answer is legitimately False. A parse
    # test, not a failure path.
    "owl/upper_stub_replacer.py",
}


#: Per-handler opt-out. `except X:  # silent-ok: <reason>` exempts one handler
#: and REQUIRES a reason after the colon — an exemption you cannot explain is not
#: an exemption. Preferred over widening the rule, which would quietly re-permit
#: the whole shape everywhere.
_OPT_OUT = "# silent-ok:"


TESTS = pathlib.Path(__file__).resolve().parent


def _mute_handlers(root: pathlib.Path = SRC) -> list[str]:
    out = []
    for f in root.rglob("*.py"):
        rel = str(f.relative_to(root))
        if rel in ALLOWED_MUTE:
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        tree = ast.parse("\n".join(lines))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ExceptHandler) and _handler_is_mute(node)):
                continue
            line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            if _OPT_OUT in line and line.split(_OPT_OUT, 1)[1].strip():
                continue                      # exempted, with a stated reason
            out.append(f"{rel}:{node.lineno}")
    return sorted(out)


def test_opt_out_requires_a_reason():
    """`# silent-ok:` with nothing after it must not exempt anything."""
    import tempfile, textwrap
    src = textwrap.dedent("""
        def f():
            try:
                pass
            except ValueError:  # silent-ok:
                x = None
    """)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "m.py"
        p.write_text(src, encoding="utf-8")
        lines = src.splitlines()
        tree = ast.parse(src)
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        node = handlers[0]
        line = lines[node.lineno - 1]
        assert _OPT_OUT in line
        assert not line.split(_OPT_OUT, 1)[1].strip(), "reason is empty"
        assert _handler_is_mute(node), "an empty reason must not make it non-mute"


def test_no_new_silent_exception_handlers():
    """A handler that neither raises nor reports makes a failure invisible."""
    mute = _mute_handlers()
    assert mute == [], (
        "these exception handlers swallow silently; make them raise, print, or "
        f"record into a report: {mute}"
    )


def test_the_tests_themselves_do_not_swallow():
    """A silent handler in a fixture corrupts a measurement, not just a run.

    ``real_graph`` in test_competency.py loaded the MILD modules under
    ``except Exception: pass``. A module that stopped parsing would have been
    dropped without a word and the competency score recomputed against an
    incomplete closure -- so a regression in the modules would have surfaced as
    CQs quietly failing to answer, and the baseline would have moved to match.
    """
    mute = _mute_handlers(TESTS)
    assert mute == [], (
        "test-side handlers swallow silently; a fixture that hides a failure "
        f"makes every assertion downstream of it meaningless: {mute}"
    )


# ── the reasoner gate must never report success without looking ─────────────

def test_gate_reads_committed_edges_not_just_stamped_ones():
    """The gate used to take its edges from ``hier._prov``. On live data that
    was 0 of 5054 committed edges, so it printed "No committed edges to gate"
    and returned clean having inspected nothing."""
    src = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    fn = src[src.index("def run_gate_hierarchy_edges"):]
    fn = fn[:fn.index("\n    def ", 10)]
    assert "hier._prov.keys()" not in fn, (
        "run_gate_hierarchy_edges is sourcing edges from provenance again; "
        "unstamped edges would go ungated and the run would look clean"
    )
    assert "df.at[c, p] == 1.0" in fn


def test_gate_shouts_when_it_cannot_run():
    src = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    fn = src[src.index("def run_gate_hierarchy_edges"):]
    fn = fn[:fn.index("\n    def ", 10)]
    assert "GATE DID NOT RUN" in fn and "WITHOUT" in fn, (
        "a gate that fails open must say so; 'skipped' on a result object that "
        "nobody prints is a silent pass"
    )


# ── provenance may not disable itself quietly ───────────────────────────────

class _FakeDM:
    """Fails only for the *provenance* CSV, so the hierarchy itself still loads."""

    def __init__(self, exc=None, df=None):
        self.exc, self.df = exc, df

    def load_latest_csv(self, prefix):
        if not prefix.endswith("_provenance"):
            return None
        if self.exc:
            raise self.exc
        return self.df

    def load_latest_json(self, prefix):
        return None

    def save_as_csv(self, *a, **k):
        pass


def _hierarchy(dm):
    from wound_ontology.hierarchies.class_hierarchy import ClassHierarchy
    return ClassHierarchy(dm)


def test_unreadable_provenance_raises_rather_than_disabling_precedence():
    """Swallowing this turned off curated > text > fca for the whole run."""
    dm = _FakeDM(exc=PermissionError("locked"))
    with pytest.raises(RuntimeError, match="provenance"):
        _hierarchy(dm)


def test_malformed_provenance_columns_raise():
    dm = _FakeDM(df=pd.DataFrame({"kid": ["A"], "mum": ["B"], "src": ["curated"]}))
    with pytest.raises(ValueError, match="missing column"):
        _hierarchy(dm)


def test_missing_provenance_is_allowed_but_announced(capsys):
    """A first run legitimately has no provenance — it must still be said."""
    dm = _FakeDM(df=None)
    _hierarchy(dm)
    out = capsys.readouterr().out
    assert "no provenance" in out.lower()
    assert "not in force" in out.lower()


def test_provenance_summary_distinguishes_unstamped_from_absent():
    """An empty summary must not be readable as 'no conflicts'."""
    dm = _FakeDM(df=None)
    h = _hierarchy(dm)
    h.df = pd.DataFrame([[1.0]], index=["Child"], columns=["Parent"])
    assert h.provenance_summary().get("_unstamped") == 1


# ── prompt degradation must be visible ──────────────────────────────────────

def test_missing_settings_warns_about_empty_predicate_definitions():
    src = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    head = src[:src.index("class Orchestrator")]
    assert "_warnings.warn" in head, (
        "an empty _PREDICATE_DEFINITIONS strips every predicate rule from the "
        "extraction prompt; that cannot happen quietly"
    )


def test_corrupt_competency_file_raises_instead_of_emptying_the_prompt():
    src = (SRC / "llm" / "llm_client.py").read_text(encoding="utf-8")
    start = src.index("def _build_cq_block")
    fn = src[start:start + 1500]
    assert "JSONDecodeError" in fn and "raise ValueError" in fn


# ── dropped data is counted, everywhere it is dropped ───────────────────────

def test_extend_report_surfaces_everything_it_declined_to_do():
    from wound_ontology.owl.extend import ExtendReport
    r = ExtendReport()
    for field in ("withheld_existing", "skipped_no_iri", "minted", "resolved"):
        assert hasattr(r, field), f"ExtendReport lost {field}"
    assert "withheld" in r.summary()
    assert "skipped" in r.summary()


def test_typing_records_empty_labels_rather_than_dropping_them():
    src = (SRC / "llm" / "llm_client.py").read_text(encoding="utf-8")
    assert 'rejected.append((t.label or "", cat, "empty label"))' in src


# ── a missing credential must explain itself ────────────────────────────────

def test_conftest_checks_whether_dotenv_actually_loaded():
    """python-dotenv returns a bool saying whether it read anything. Discarding
    it made three different causes — no .env, an unreadable .env, and a .env
    without the key — produce one identical symptom: tests quietly skipping."""
    src = (pathlib.Path(__file__).resolve().parents[0]
           / "integration" / "conftest.py").read_text(encoding="utf-8")
    assert "_DOTENV_LOADED" in src, "load_dotenv()'s return value is being thrown away"
    assert "_credential_diagnosis" in src
    assert "Diagnosis:" in src, "the reason must reach the terminal summary"


def test_only_tests_that_need_the_api_are_gated_on_it():
    """test_embeddings.py and test_term_mapper.py drive a local SapBERT model.
    Gating them on OPENROUTER_API_KEY hid 33 real tests."""
    integration = pathlib.Path(__file__).resolve().parents[0] / "integration"
    for name in ("test_embeddings.py", "test_term_mapper.py"):
        src = (integration / name).read_text(encoding="utf-8")
        assert "needs_llm" not in src, (
            f"{name} uses no LLM API; marking it needs_llm would hide it again"
        )
    pipeline = (integration / "test_pipeline.py").read_text(encoding="utf-8")
    assert "needs_llm" in pipeline


def test_dotenv_lookup_does_not_depend_on_the_call_stack():
    """python-dotenv's bare find_dotenv() walks frames and asserts
    `frame.f_back is not None`, so it raises AssertionError when there is no
    parent frame — running via `python -` is enough. A credential loader that
    crashes depending on how the interpreter was started is exactly the kind of
    environment-dependent failure that produced the original mystery skip."""
    conftest = (pathlib.Path(__file__).resolve().parents[0]
                / "integration" / "conftest.py")
    tree = ast.parse(conftest.read_text(encoding="utf-8"))
    # Check calls in the AST, not the text — the explanation in the docstring
    # legitimately mentions the pattern it is warning about.
    bare = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "find_dotenv"
        and not n.args and not n.keywords
    ]
    assert bare == [], (
        f"bare find_dotenv() at line(s) {bare} walks the call stack and raises "
        "AssertionError when there is no parent frame"
    )
    assert "usecwd=True" in conftest.read_text(encoding="utf-8")


# ── a cached artefact is only valid while it is newer than its sources ───────
#
# `build_reasoner_skeleton` reused `skeleton_tbox.ttl` on existence alone.
# Measured 2026-09-10: the skeleton was written 20 Aug 22:13 and
# ground_truth_final.owl 4 Sep 19:32, so BOTH reasoner gates had spent fifteen
# days reasoning over a WONT that no longer existed -- and neither said so.

def _skeleton_harness(tmp_path, monkeypatch, gt_mtime, mild_mtime, sk_mtime):
    """Three files with chosen mtimes, and a build_skeleton that records calls."""
    import config.settings as settings
    import wound_ontology.reasoning.skeleton as skel
    from wound_ontology.orchestrator import Orchestrator

    gt   = tmp_path / "ground_truth_final.owl"
    mild = tmp_path / "mild.ttl"
    sk   = tmp_path / "skeleton_tbox.ttl"
    for f in (gt, mild, sk):
        f.write_text("# stub\n")
    import os
    for f, when in ((gt, gt_mtime), (mild, mild_mtime), (sk, sk_mtime)):
        os.utime(f, (when, when))

    monkeypatch.setattr(settings, "GROUND_TRUTH_TTL", gt)
    monkeypatch.setattr(settings, "MILD_TTL", mild)
    monkeypatch.setattr(settings, "REASONER_SKELETON", sk)
    # The skeleton also reads the import modules (BFO's axioms, the relations'
    # domains and ranges, 2026-10-03), so they count for staleness too: one
    # module, as old as the oldest source.
    mods = tmp_path / "modules"
    mods.mkdir()
    mod = mods / "obi_module.owl"
    mod.write_text("# stub\n")
    os.utime(mod, (min(gt_mtime, mild_mtime),) * 2)
    monkeypatch.setattr(settings, "MILD_MODULES_DIR", mods)

    built: list = []

    def fake_build(ground_truth, mild_, output, modules=None):
        built.append((ground_truth, mild_, output))
        return pathlib.Path(output), 1
    monkeypatch.setattr(skel, "build_skeleton", fake_build)

    # build_reasoner_skeleton never touches self, and constructing a real
    # Orchestrator costs ~2 minutes.
    return Orchestrator.build_reasoner_skeleton, built, (gt, mild, sk)


def test_a_skeleton_older_than_wont_is_rebuilt_not_reused(tmp_path, monkeypatch, capsys):
    run, built, (gt, _mild, _sk) = _skeleton_harness(
        tmp_path, monkeypatch, gt_mtime=2_000, mild_mtime=1_000, sk_mtime=1_500)
    run(None)
    assert built, "a skeleton older than WONT must be rebuilt"
    assert "STALE" in capsys.readouterr().out


def test_a_skeleton_older_than_mild_is_rebuilt_too(tmp_path, monkeypatch, capsys):
    run, built, _ = _skeleton_harness(
        tmp_path, monkeypatch, gt_mtime=1_000, mild_mtime=2_000, sk_mtime=1_500)
    run(None)
    assert built
    assert "STALE" in capsys.readouterr().out


def test_a_current_skeleton_is_still_reused(tmp_path, monkeypatch, capsys):
    """The cache is the point; only staleness is the defect."""
    run, built, _ = _skeleton_harness(
        tmp_path, monkeypatch, gt_mtime=1_000, mild_mtime=1_000, sk_mtime=2_000)
    run(None)
    assert not built, "a current skeleton must not be rebuilt"
    assert "Reusing" in capsys.readouterr().out


def test_a_skeleton_older_than_a_module_is_rebuilt(tmp_path, monkeypatch, capsys):
    import os
    run, built, (gt, _mild, _sk) = _skeleton_harness(
        tmp_path, monkeypatch, gt_mtime=1_000, mild_mtime=1_000, sk_mtime=1_500)
    os.utime(tmp_path / "modules" / "obi_module.owl", (2_000, 2_000))
    run(None)
    assert built, "a skeleton older than an import module must be rebuilt"
    assert "obi_module.owl" in capsys.readouterr().out


def test_the_rebuild_names_which_source_moved(tmp_path, monkeypatch, capsys):
    run, _built, (gt, _mild, _sk) = _skeleton_harness(
        tmp_path, monkeypatch, gt_mtime=2_000, mild_mtime=1_000, sk_mtime=1_500)
    run(None)
    assert gt.name in capsys.readouterr().out


def test_a_missing_source_raises_rather_than_building_a_partial_skeleton(
        tmp_path, monkeypatch):
    run, built, (gt, _mild, _sk) = _skeleton_harness(
        tmp_path, monkeypatch, gt_mtime=1_000, mild_mtime=1_000, sk_mtime=2_000)
    gt.unlink()
    with pytest.raises(FileNotFoundError, match="cannot read its sources"):
        run(None)
    assert not built


def test_the_gate_goes_through_the_staleness_check(tmp_path, monkeypatch):
    """Taking REASONER_SKELETON directly is what kept the stale file in service,
    so the one consumer must route through the checked builder."""
    import ast
    src = (SRC / "orchestrator.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "reasoner_gate")
    # The docstring explains why it must NOT name REASONER_SKELETON, so read the
    # statements and not the prose.
    stmts = [n for n in fn.body
             if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    body = "".join(ast.dump(n) for n in stmts)
    assert "build_reasoner_skeleton" in body
    assert "REASONER_SKELETON" not in body
