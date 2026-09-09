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


# ── a write to a config file is verified, never assumed ─────────────────────
#
# `BlockKeywordList.remove()` and `SuspiciousList.remove()` removed nothing,
# returned 0 and said nothing, for as long as those two literals were written
# several entries to a line. Adding worked, so the asymmetry was invisible:
# block a keyword interactively, and you could not unblock it. The list objects
# now confirm the file actually changed, and raise naming the terms if it did
# not. Found 2026-09-09, the day after the curation-list audit.


class _TinyList:
    """A BaseList over a temp file, so the guard itself can be exercised."""

    def __new__(cls, path, var):
        from wound_ontology.store.term_lists import KeywordList

        klass = type("_TinyList", (KeywordList,), {
            "_PATH": path, "_VAR_NAME": var,
            "load": lambda self: setattr(self, "_terms", frozenset(_read(path, var))),
        })
        obj = klass()
        obj.load()
        return obj


def _read(path, var):
    ns: dict = {}
    exec(compile(path.read_text(), str(path), "exec"), ns)
    return ns[var]


def test_a_removal_that_cannot_land_raises_instead_of_returning_zero(tmp_path):
    """The exact failure: a packed literal, which the remover cannot touch."""
    p = tmp_path / "packed.py"
    p.write_text('PACKED: frozenset[str] = frozenset({\n    "alpha", "beta",\n})\n')
    lst = _TinyList(p, "PACKED")

    with pytest.raises(RuntimeError) as exc:
        lst.remove({"beta"})
    message = str(exc.value)
    assert "beta" in message and "PACKED" in message
    assert "one entry per line" in message, "the message must say what to do"
    assert "beta" in _read(p, "PACKED"), "and it really did not remove it"


def test_a_removal_that_lands_returns_normally(tmp_path):
    """The guard must not fire on the working case."""
    p = tmp_path / "ok.py"
    p.write_text('OK: frozenset[str] = frozenset({\n    "alpha",\n    "beta",\n})\n')
    lst = _TinyList(p, "OK")

    assert lst.remove({"beta"}) == 1
    assert set(_read(p, "OK")) == {"alpha"}


def test_removing_a_term_that_was_never_there_is_not_a_failure(tmp_path):
    """A no-op removal is legitimate and must stay quiet.

    The guard checks the terms that WERE present, not every term asked for --
    otherwise `_save_review_results` would explode every time it whitelisted a
    term that had never been blocklisted, which is the normal case.
    """
    p = tmp_path / "noop.py"
    p.write_text('NOOP: frozenset[str] = frozenset({\n    "alpha",\n})\n')
    lst = _TinyList(p, "NOOP")

    assert lst.remove({"never-present"}) == 0
    assert set(_read(p, "NOOP")) == {"alpha"}


def test_an_add_is_verified_too(tmp_path):
    """Same claim in the other direction."""
    p = tmp_path / "add.py"
    p.write_text('ADD: frozenset[str] = frozenset({\n    "alpha",\n})\n')
    lst = _TinyList(p, "ADD")

    assert lst.add({"beta"}) == 1
    assert set(_read(p, "ADD")) == {"alpha", "beta"}
    assert lst.add({"alpha"}) == 0, "already present, nothing written, no error"


def test_an_add_that_does_not_land_raises(tmp_path):
    """The realistic way an add fails: writing to one file, reading another.

    That is not hypothetical — it is the shape of the bug fixed in 398aacf,
    where `_find_block_end` matched `WHITELIST` inside `KEYWORD_WHITELIST` and
    every write landed in the wrong literal while the right one stayed empty.
    Here `_PATH` and `load()` are deliberately pointed at different files, so
    the write succeeds and the term still never appears.
    """
    from wound_ontology.store.term_lists import KeywordList

    written = tmp_path / "written.py"
    read_instead = tmp_path / "read_instead.py"
    for f in (written, read_instead):
        f.write_text('L: frozenset[str] = frozenset({\n    "alpha",\n})\n')

    klass = type("_Divergent", (KeywordList,), {
        "_PATH": written, "_VAR_NAME": "L",
        "load": lambda self: setattr(self, "_terms", frozenset(_read(read_instead, "L"))),
    })
    lst = klass()
    lst.load()

    with pytest.raises(RuntimeError) as exc:
        lst.add({"beta"})
    assert "beta" in str(exc.value) and "add" in str(exc.value)
    assert "beta" in _read(written, "L"), "it really was written"
    assert "beta" not in _read(read_instead, "L"), "and really is not where it is read from"


def test_the_five_lists_share_one_verified_write_path(tmp_path):
    """The guard is one implementation, not five copies that can drift.

    The five concrete classes held byte-identical add/remove pairs until
    2026-09-09; they are now inherited from BaseList.
    """
    from wound_ontology.store.term_lists import (
        BaseList, BlockKeywordList, BlockList, SuspiciousList,
        WhiteKeywordList, WhiteList,
    )

    for cls in (BlockList, WhiteList, BlockKeywordList, WhiteKeywordList, SuspiciousList):
        assert cls.add is BaseList.add, f"{cls.__name__} has its own add again"
        assert cls.remove is BaseList.remove, f"{cls.__name__} has its own remove again"
