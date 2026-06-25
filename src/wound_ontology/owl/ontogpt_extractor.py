"""Structured wound-care entity extraction via OntoGPT / SPIRES."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Ensure the local ontogpt checkout is on sys.path
_ONTOGPT_SRC = Path(__file__).parents[3] / "ontogpt" / "src"
if str(_ONTOGPT_SRC) not in sys.path:
    sys.path.insert(0, str(_ONTOGPT_SRC))

# Load .env from project root so OPENROUTER_API_KEY is available
_PROJECT_ROOT = Path(__file__).parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# LiteLLM / ontogpt: expose OpenRouter key as OPENAI_API_KEY + base URL
if "OPENROUTER_API_KEY" in os.environ and "OPENAI_API_KEY" not in os.environ:
    os.environ["OPENAI_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
    os.environ.setdefault("OPENAI_API_BASE", "https://openrouter.ai/api/v1")

_TEMPLATE_DIR = _ONTOGPT_SRC / "ontogpt" / "templates"
_WOUND_TEMPLATE = "wound_care"


class OntoGPTExtractor:
    """Extract structured wound-care entities from free text using SPIRES.

    Uses the wound_care LinkML template and grounds extracted terms against
    OBO ontologies (HP, DOID, CHEBI, PATO, GO, OBI, NCBITaxon).

    Usage::

        extractor = OntoGPTExtractor(model="gpt-4o")
        result = extractor.extract(text)
        print(result.extracted_object.wound_types)
    """

    def __init__(
        self,
        model: str = "openrouter/anthropic/claude-sonnet-4-5",
        template: str = _WOUND_TEMPLATE,
    ) -> None:
        self.model = model
        self.template = template
        self._engine = None

    def _get_engine(self):
        if self._engine is not None:
            return self._engine

        from ontogpt.engines.spires_engine import SPIRESEngine
        from ontogpt.io.template_loader import get_template_details

        template_details = get_template_details(template=self.template)
        self._engine = SPIRESEngine(
            template_details=template_details,
            model=self.model,
        )
        return self._engine

    def extract(self, text: str) -> Any:
        """Extract wound-care entities from a single text.

        Returns an ontogpt ExtractionResult with `.extracted_object` containing
        a WoundCaseReport (wound_types, treatments, pathogens, comorbidities,
        wound_characteristics, healing_processes).
        """
        return self._get_engine().extract_from_text(text)

    def extract_batch(self, texts: list[str]) -> list[Any]:
        """Extract from multiple texts, returning one ExtractionResult per text."""
        return [self.extract(t) for t in texts]

    @staticmethod
    def result_to_dict(result: Any) -> dict:
        """Convert an ExtractionResult to a plain dict for comparison/storage.

        Falls back to parsing the raw LLM output when SPIRES grounding fails
        (which happens when the model returns comma-separated items inside a
        single <...> rather than semicolon-separated individual <...> tokens).
        """
        import re

        obj = result.extracted_object

        def _ids(items):
            if not items:
                return []
            out = []
            for i in items:
                eid   = getattr(i, "id", None)
                label = getattr(i, "label", None)
                # Grounding succeeded → use as-is
                if eid or label:
                    out.append({"id": eid, "label": label})
                    continue
                # Grounding failed: the raw string is stored as the item itself.
                raw = str(i)
                # Strip surrounding <...> if present
                raw = re.sub(r"^<|>$", "", raw.strip())
                # Split on comma or semicolon
                for part in re.split(r"[;,]", raw):
                    part = part.strip(" <>")
                    if part:
                        out.append({"id": None, "label": part})
            return out

        if obj is None:
            # Last resort: parse raw completion output
            return OntoGPTExtractor._parse_raw(result.raw_completion_output or "")

        d = {
            "wound_types":           _ids(getattr(obj, "wound_types", []) or []),
            "treatments":            _ids(getattr(obj, "treatments", []) or []),
            "pathogens":             _ids(getattr(obj, "pathogens", []) or []),
            "comorbidities":         _ids(getattr(obj, "comorbidities", []) or []),
            "wound_characteristics": _ids(getattr(obj, "wound_characteristics", []) or []),
            "healing_processes":     _ids(getattr(obj, "healing_processes", []) or []),
        }
        # If every field came back empty, fall back to raw parsing
        if not any(d.values()):
            return OntoGPTExtractor._parse_raw(result.raw_completion_output or "")
        return d

    @staticmethod
    def _parse_raw(raw: str) -> dict:
        """Parse SPIRES-style raw completion into a plain dict."""
        import re
        result: dict[str, list] = {
            "wound_types": [], "treatments": [], "pathogens": [],
            "comorbidities": [], "wound_characteristics": [], "healing_processes": [],
        }
        slot_map = {
            "wound_types": "wound_types",
            "treatments": "treatments",
            "pathogens": "pathogens",
            "comorbidities": "comorbidities",
            "wound_characteristics": "wound_characteristics",
            "healing_processes": "healing_processes",
        }
        for line in raw.splitlines():
            for key, field in slot_map.items():
                if line.lower().startswith(key + ":"):
                    content = line[len(key) + 1:].strip()
                    for term in re.split(r"[;,]", re.sub(r"[<>]", "", content)):
                        term = term.strip()
                        if term:
                            result[field].append({"id": None, "label": term})
        return result
