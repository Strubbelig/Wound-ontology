# ============================================================
# Wound Ontology — Term Mapping on Google Colab Pro (GPU)
# ============================================================
# Copy each cell block into a separate Colab code cell.
# Runtime → Change runtime type → GPU (T4 or A100)
# ============================================================

# ── CELL 1: verify GPU ───────────────────────────────────────
import torch
assert torch.cuda.is_available(), "No GPU detected — change runtime type to GPU"
print(f"GPU: {torch.cuda.get_device_name(0)}")


# ── CELL 2: clone repo & install ─────────────────────────────
import subprocess, sys

# Clone (skip if already done)
subprocess.run(["git", "clone", "https://github.com/Strubbelig/Wound-ontology.git"], check=False)

# Install the package and all declared deps (includes rapidfuzz, transformers, etc.)
subprocess.run([sys.executable, "-m", "pip", "install", "-e", "Wound-ontology", "-q"], check=True)
subprocess.run([sys.executable, "-m", "pip", "install",
    "nest_asyncio", "python-dotenv",
    "-q"], check=True)

print("Installation complete.")


# ── CELL 3: mount Google Drive ───────────────────────────────
from google.colab import drive
drive.mount("/content/drive")

# Folder in your Drive where the concept store JSON lives.
# Change this to match your actual Drive path.
DRIVE_CACHE = "/content/drive/MyDrive/wound_ontology/cache"

import os
os.makedirs(DRIVE_CACHE, exist_ok=True)
print(f"Drive cache folder: {DRIVE_CACHE}")


# ── CELL 4: copy concept store from Drive into repo cache ────
import glob, shutil
from pathlib import Path

REPO_CACHE = Path("/content/Wound-ontology/data/cache")
REPO_CACHE.mkdir(parents=True, exist_ok=True)

# Copy the latest concept_store JSON from Drive into the repo cache
drive_files = sorted(glob.glob(f"{DRIVE_CACHE}/concept_store_*.json"))
if not drive_files:
    raise FileNotFoundError(
        f"No concept_store_*.json found in {DRIVE_CACHE}. "
        "Upload your latest concept_store JSON from your local machine first."
    )

for f in drive_files:
    dest = REPO_CACHE / Path(f).name
    shutil.copy(f, dest)
    print(f"Copied: {Path(f).name}")

# Also copy any existing term_mapping JSON so incremental mapping is preserved
for f in sorted(glob.glob(f"{DRIVE_CACHE}/term_mapping_*.json")):
    dest = REPO_CACHE / Path(f).name
    shutil.copy(f, dest)
    print(f"Copied existing mapping: {Path(f).name}")


# ── CELL 5: set up pipeline ──────────────────────────────────
import sys, nest_asyncio
nest_asyncio.apply()

sys.path.insert(0, "/content/Wound-ontology")
sys.path.insert(0, "/content/Wound-ontology/config")

from wound_ontology.orchestrator import Orchestrator
from wound_ontology.embedding.embedder import Embedder

pipeline = Orchestrator(
    base_path=str(REPO_CACHE),
    allowed_predicates=[
        "is_a", "part_of", "has_quality", "occurs_in", "caused_by", "is_treatment_for",
    ],
)
print(f"Concept store loaded: {len(pipeline.store.dict)} PubMed entries")
print(f"Existing mappings   : {len(pipeline.term_mapper.mapping)} terms already mapped")

# Larger batch size takes advantage of Colab GPU VRAM
embedder = Embedder(batch_size=256)


# ── CELL 6: run the mapping ───────────────────────────────────
# Dual-threshold: cosine >= SIMILARITY_THRESHOLD AND string_sim >= STRING_THRESHOLD.
# Only near-identical surface forms merge (case, hyphen, whitespace variants).
# Abbreviation pairs (DFU ↔ Diabetic Foot Ulcer) bypass string_sim check.
# Generic single-word terms (wound, pain, skin…) require string_sim >= 0.90.
# If max cluster size >= 20, an error is raised — raise SIMILARITY_THRESHOLD.
SIMILARITY_THRESHOLD = 0.95   # cosine threshold (must be 0.93–0.98)
STRING_THRESHOLD     = 0.92   # string similarity threshold after normalization

freq   = pipeline._collect_store_terms_with_freq()
terms  = list(freq.keys())
print(f"Unique terms in store: {len(terms)}")

result = pipeline.term_mapper.build_from_embeddings(
    terms,
    embedder=embedder,
    similarity_threshold=SIMILARITY_THRESHOLD,
    string_threshold=STRING_THRESHOLD,
    frequencies=freq,
)
print(f"Mapping complete. Total entries: {len(result)}")


# ── CELL 7: save mapping back to Drive ───────────────────────
latest_mapping = sorted(glob.glob(str(REPO_CACHE / "term_mapping_*.json")))
if latest_mapping:
    src  = latest_mapping[-1]
    dest = Path(DRIVE_CACHE) / Path(src).name
    shutil.copy(src, dest)
    print(f"Saved to Drive: {Path(dest).name}")
else:
    print("No mapping file found to copy — check for errors above.")
