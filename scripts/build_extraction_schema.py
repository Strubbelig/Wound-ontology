#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Regenerate the LLM extraction schema from WONT + MILD.

    python scripts/build_extraction_schema.py

The builder itself lives in `wound_ontology.llm.schema_builder`, because the
pipeline now calls it too: `Orchestrator.run_extract_to_store` checks the
schema's age against the ontologies and rebuilds it before extracting. This
file is the command line for running that by hand.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from wound_ontology.llm.schema_builder import main  # noqa: E402

if __name__ == "__main__":
    main()
