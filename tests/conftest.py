"""Session-wide guard: the right interpreter, said out loud.

On 2026-08-21 the VS Code Test Explorer ran the suite under the python.org
framework build (/usr/local/bin/python3, 3.12.2) instead of onto_env, because
the workspace root is Ontology/ and only the nested "Wound ontology/.vscode/"
settings pinned an interpreter. The symptom was 24 identical
``ModuleNotFoundError: No module named 'torch'`` tracebacks in
test_embeddings.py -- which reads as "the embedding code is broken" rather than
"you are running the wrong Python".

So the interpreter is now stated in the pytest header on every run, whether or
not anything is wrong, and a missing core dependency stops the session with an
explanation instead of scattering import errors across the tests that happen to
touch it.
"""

from __future__ import annotations

import shutil
import sys

import pytest

#: Import name -> the reason the project needs it. These are the packages
#: without which a green run would be meaningless rather than merely partial.
_CORE = {
    "rdflib": "reads and writes the WONT/MILD Turtle artifacts",
    "owlready2": "OWL manipulation in the curator",
    "pandas": "every hierarchy is a DataFrame",
    "numpy": "must be <2 -- torch 2.2.2 is built against the NumPy 1.x C API",
    "torch": "SapBERT embeddings (no Intel-macOS wheel above 2.2.2)",
    "transformers": "must be <5 -- 5.x needs torch>=2.5 and silently disables it",
}

_EXPECTED_PREFIX = "/opt/anaconda3/envs/onto_env/bin/"


def _missing() -> list[str]:
    import importlib.util
    return [name for name in _CORE if importlib.util.find_spec(name) is None]


def pytest_report_header(config) -> list[str]:
    """Always name the interpreter, so a wrong one is visible before any test."""
    lines = [f"interpreter: {sys.executable}"]
    if not sys.executable.startswith(_EXPECTED_PREFIX):
        lines.append(
            f"WARNING: this is not onto_env ({_EXPECTED_PREFIX}python). "
            "Results below describe that interpreter, not the project's."
        )
    # importlib.metadata, not `pkg.__version__`: owlready2 exposes VERSION and
    # would otherwise be reported as broken while being perfectly installed.
    import importlib.metadata as md
    _DIST = {"torch": "torch", "owlready2": "owlready2", "rdflib": "rdflib",
             "pandas": "pandas", "numpy": "numpy", "transformers": "transformers"}
    versions = []
    for name in _CORE:
        try:
            versions.append(f"{name} {md.version(_DIST[name])}")
        except md.PackageNotFoundError:
            versions.append(f"{name} NOT INSTALLED")
    lines.append("core: " + ", ".join(versions))
    if shutil.which("robot") is None:
        lines.append("robot: NOT ON PATH -- reasoner gate tests will skip, not pass")
    return lines


def pytest_sessionstart(session) -> None:
    missing = _missing()
    if not missing:
        return
    detail = "\n".join(f"  - {n}: {_CORE[n]}" for n in missing)
    raise pytest.UsageError(
        "This interpreter cannot run the wound-ontology suite.\n"
        f"  interpreter: {sys.executable}\n"
        f"  missing:\n{detail}\n"
        "Select the onto_env interpreter "
        f"({_EXPECTED_PREFIX}python) -- in VS Code via 'Python: Select "
        "Interpreter', or run pytest from `conda activate onto_env`. "
        "Refusing to run rather than reporting import errors as test failures."
    )


# ── A real TermMapping over an in-memory file ────────────────────────────────
#
# Five test modules used to hand-roll a `_Mapping` double carrying `data`,
# `add_batch` and `remove`. The doubles drifted apart from each other and from
# the class, and when `remove` became `retire` all five went red at once for a
# reason that had nothing to do with what they test. A double that has to track
# a class this closely IS the class, so the tests use the real one -- refusals,
# retirement, the record format -- and only the file underneath is fake.

class MemoryDataManager:
    """DataManager's whole surface as far as TermMapping is concerned."""

    def __init__(self, records: dict | None = None) -> None:
        self.records = dict(records or {})
        self.written: dict | None = None

    def load_latest_json(self, name):
        return self.records

    def save_as_json(self, data, name):
        self.written = data
        return name


def memory_mapping(data: dict | None = None):
    """A real `TermMapping` whose file is a dict. Accepts the flat
    `term -> canonical` shape, which `_load` migrates exactly as it does on
    disk, or full records."""
    from wound_ontology.mappers.term_mapping import TermMapping
    return TermMapping(MemoryDataManager(dict(data or {})))


def memory_mapper(data: dict | None = None, name: str = "test"):
    """A real `TermMapper` over `memory_mapping`."""
    from wound_ontology.mappers.term_mapper import TermMapper
    return TermMapper(memory_mapping(data), name=name)
