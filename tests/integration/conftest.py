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
from dotenv import load_dotenv

load_dotenv()


def pytest_collection_modifyitems(items):
    """Skip all integration tests when OPENROUTER_API_KEY is not set."""
    if os.getenv("OPENROUTER_API_KEY"):
        return
    skip = pytest.mark.skip(reason="OPENROUTER_API_KEY not set")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)

_TEST_OUTPUT = Path(__file__).resolve().parents[1] / "test_output"

_STALE_PATTERNS = ["*.json", "*.csv", "*.pkl"]


def pytest_configure(config):
    """Remove intermediate cache/hierarchy files before the session starts."""
    _TEST_OUTPUT.mkdir(parents=True, exist_ok=True)
    removed = 0
    for pattern in _STALE_PATTERNS:
        for path in _TEST_OUTPUT.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"\n[conftest] Cleared {removed} stale artefact(s) from {_TEST_OUTPUT}")
