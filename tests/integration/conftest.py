"""
Integration test session setup.

Clears intermediate artefacts (JSON, CSV, PKL) from tests/test_output before
each session so the pipeline always runs from a clean state.  OWL files are
intentionally NOT deleted so they remain available for inspection after the run.
"""
import glob
import os
from pathlib import Path

import pytest
from dotenv import find_dotenv, load_dotenv

# load_dotenv() returns a bool and the old code threw it away, so three very
# different situations produced one identical symptom -- tests quietly skipping:
#   * no .env anywhere
#   * a .env that exists but could not be read (on an iCloud path an evicted,
#     dataless file reads as absent until macOS materialises it)
#   * a .env that loaded fine but has no OPENROUTER_API_KEY line
# Each is now reported separately, and the diagnosis is printed rather than
# inferred from an unexplained "s".
_KEY = "OPENROUTER_API_KEY"
_ALREADY_IN_SHELL = _KEY in os.environ
def _locate_dotenv() -> str:
    """Find .env without depending on the call stack.

    Bare find_dotenv() walks frames and asserts `frame.f_back is not None`, so it
    raises AssertionError outright when there is no parent frame -- running via
    `python -` is enough to trigger it. usecwd=True skips the frame walk; the
    explicit walk up from this file covers the case where pytest is invoked from
    somewhere else entirely.
    """
    found = find_dotenv(usecwd=True)
    if found:
        return found
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return ""


_DOTENV_PATH = _locate_dotenv()
_DOTENV_LOADED = bool(_DOTENV_PATH) and load_dotenv(_DOTENV_PATH)


def _credential_diagnosis() -> str:
    """Why is the key missing? Never make the reader guess."""
    if os.getenv(_KEY):
        return ""
    if _ALREADY_IN_SHELL:
        return f"{_KEY} is set in the shell but empty."
    if not _DOTENV_PATH:
        return (f"no .env file was found (searched upward from {Path.cwd()}). "
                f"{_KEY} is therefore unset.")
    if not _DOTENV_LOADED:
        return (f".env was found at {_DOTENV_PATH} but python-dotenv read nothing "
                "from it. On an iCloud path this usually means the file is still "
                "an unmaterialised placeholder — open it once and re-run.")
    return (f".env at {_DOTENV_PATH} loaded, but it contains no {_KEY} entry.")


#: Set by pytest_collection_modifyitems, reported by pytest_terminal_summary.
#: A skip nobody sees is a test nobody runs.
_SKIPPED: list[str] = []


def pytest_collection_modifyitems(items):
    """Skip only the tests that genuinely need the OpenRouter API.

    This used to skip *every* test under tests/integration/ when the key was
    absent. Most of them never call OpenRouter -- test_embeddings.py and
    test_term_mapper.py drive a local SapBERT model -- so 24+ real tests
    vanished with no signal in any shell without the key, and a clean run
    reported success while nothing had been exercised. Tests now opt in with
    @pytest.mark.needs_llm, so a new API test that forgets the marker fails
    loudly rather than skipping quietly.
    """
    _SKIPPED.clear()
    if os.getenv("OPENROUTER_API_KEY"):
        return
    skip = pytest.mark.skip(reason="needs OPENROUTER_API_KEY")
    for item in items:
        if item.get_closest_marker("needs_llm"):
            item.add_marker(skip)
            _SKIPPED.append(item.nodeid)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Say out loud how much was not run, and why."""
    if not _SKIPPED:
        return
    terminalreporter.write_sep("=", "SKIPPED FOR MISSING CREDENTIALS", yellow=True)
    terminalreporter.write_line(
        f"{len(_SKIPPED)} test(s) needed {_KEY} and did not run. "
        "This run did NOT exercise the live LLM path."
    )
    terminalreporter.write_line(f"Diagnosis: {_credential_diagnosis()}")
    for nodeid in _SKIPPED[:10]:
        terminalreporter.write_line(f"  - {nodeid}")
    if len(_SKIPPED) > 10:
        terminalreporter.write_line(f"  ... and {len(_SKIPPED) - 10} more")

_TEST_OUTPUT = Path(__file__).resolve().parents[1] / "test_output"

_STALE_PATTERNS = ["*.json", "*.csv", "*.pkl"]


def pytest_configure(config):
    """Remove intermediate cache/hierarchy files before the session starts."""
    config.addinivalue_line(
        "markers", "needs_llm: requires a live OPENROUTER_API_KEY")
    _TEST_OUTPUT.mkdir(parents=True, exist_ok=True)
    removed = failed = 0
    for pattern in _STALE_PATTERNS:
        for path in _TEST_OUTPUT.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                failed += 1
                print(f"[conftest] could not remove {path.name}: {exc}")
    if failed:
        print(f"[conftest] WARNING: {failed} stale artefact(s) survived cleanup — "
              "tests may run against leftover state")
    if removed:
        print(f"\n[conftest] Cleared {removed} stale artefact(s) from {_TEST_OUTPUT}")
