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

# Install the package and all runtime deps
subprocess.run([sys.executable, "-m", "pip", "install", "-e", "Wound-ontology", "-q"], check=True)
subprocess.run([sys.executable, "-m", "pip", "install",
    "transformers", "torch", "scikit-learn", "openai", "nest_asyncio", "python-dotenv",
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


# ── CELL 4: API keys ─────────────────────────────────────────
# Option A (recommended): store secrets in Colab → Secrets (key icon on left sidebar)
#   Add keys named OPENROUTER_API_KEY and ENTREZ_EMAIL, then run this cell.
try:
    from google.colab import userdata
    os.environ["OPENROUTER_API_KEY"] = userdata.get("OPENROUTER_API_KEY")
    os.environ["ENTREZ_EMAIL"]        = userdata.get("ENTREZ_EMAIL")
    print("API keys loaded from Colab Secrets.")
except Exception:
    # Option B: paste keys directly (less secure)
    os.environ["OPENROUTER_API_KEY"] = "sk-or-..."   # ← replace
    os.environ["ENTREZ_EMAIL"]        = "you@example.com"  # ← replace
    print("API keys set manually.")

assert os.environ.get("OPENROUTER_API_KEY", "").startswith("sk-"), \
    "OPENROUTER_API_KEY looks wrong — double-check it."


# ── CELL 5: copy concept store from Drive into repo cache ────
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


# ── CELL 6: set up Python path & pipeline ────────────────────
import sys, nest_asyncio
nest_asyncio.apply()

sys.path.insert(0, "/content/Wound-ontology")
sys.path.insert(0, "/content/Wound-ontology/config")

from wound_ontology.orchestrator import Orchestrator
from wound_ontology.llm.llm_client import LLMClient

pipeline = Orchestrator(
    base_path=str(REPO_CACHE),
    allowed_predicates=[
        "is_a", "part_of", "has_quality", "occurs_in", "caused_by", "is_treatment_for",
    ],
)
print(f"Concept store loaded: {len(pipeline.store.dict)} PubMed entries")
print(f"Existing mappings   : {len(pipeline.term_mapper.mapping)} terms already mapped")


# ── CELL 7: build GPU-accelerated SapBERT embedder ───────────
import numpy as np
from transformers import AutoTokenizer, AutoModel

class GPUEmbedder:
    """SapBERT embedder with explicit CUDA placement."""

    MODEL_NAME = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"

    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Loading SapBERT on {self.device}…")
        self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
        self.model     = AutoModel.from_pretrained(self.MODEL_NAME).to(self.device)
        self.model.eval()
        print("SapBERT ready.")

    def embed(self, texts: list[str], batch_size: int = 256) -> np.ndarray:
        all_vecs = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            inputs = self.tokenizer(chunk, padding=True, truncation=True,
                                    return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                out = self.model(**inputs)
                vecs = out.last_hidden_state[:, 0, :]  # [CLS] token
            all_vecs.append(vecs.cpu().float().numpy())
        return np.vstack(all_vecs)

    async def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts).tolist()


embedder = GPUEmbedder()


# ── CELL 8: combined client (GPU embeddings + OpenRouter LLM) ─
class CombinedMappingClient:
    """
    Satisfies the TermMapper interface:
      - create_embeddings  → SapBERT on GPU  (fast similarity lookup)
      - create_normalization_mapping → OpenRouter LLM (fallback for low-similarity terms)
    """

    def __init__(self, embedder: GPUEmbedder, llm: LLMClient):
        self._emb = embedder
        self._llm = llm

    async def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await self._emb.create_embeddings(texts)

    async def create_normalization_mapping(self, terms, standards) -> dict:
        return await self._llm.create_normalization_mapping(terms, standards)


llm    = LLMClient(api_key=os.environ["OPENROUTER_API_KEY"])
client = CombinedMappingClient(embedder, llm)
print("Combined client ready.")


# ── CELL 9: run the mapping ───────────────────────────────────
import asyncio

terms = pipeline._collect_store_terms()
print(f"Total unique terms in store : {len(terms)}")
new   = [t for t in terms if t not in pipeline.term_mapper.mapping]
print(f"Terms not yet mapped        : {len(new)}")

if new:
    loop   = asyncio.get_event_loop()
    result = loop.run_until_complete(
        pipeline.term_mapper.map_new_terms(terms, client)
    )
    print(f"Mapping complete. Total entries: {len(result)}")
else:
    print("All terms already mapped — nothing to do.")


# ── CELL 10: save mapping back to Drive ──────────────────────
latest_mapping = sorted(glob.glob(str(REPO_CACHE / "term_mapping_*.json")))
if latest_mapping:
    src  = latest_mapping[-1]
    dest = Path(DRIVE_CACHE) / Path(src).name
    shutil.copy(src, dest)
    print(f"Saved to Drive: {Path(dest).name}")
else:
    print("No mapping file found to copy — check for errors above.")
