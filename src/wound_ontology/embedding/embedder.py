from __future__ import annotations

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel


class Embedder:
    """
    SapBERT embedder for biomedical entity alignment.

    Model weights are downloaded and cached on first use (~438 MB, HuggingFace cache).
    GPU is used automatically when available.
    """

    MODEL_NAME = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"

    def __init__(self, batch_size: int = 64):
        self.batch_size   = batch_size
        self._device      = None
        self._tokenizer   = None
        self._model       = None

    # ── Lazy loading ──────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[Embedder] Loading SapBERT on {self._device}...")
        self._tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
        self._model     = AutoModel.from_pretrained(self.MODEL_NAME).to(self._device)
        self._model.eval()
        print("[Embedder] SapBERT ready.")

    # ── Core embedding ────────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        Return an (N, hidden_size) float32 array of [CLS]-token embeddings.

        Processes texts in mini-batches so VRAM usage stays bounded.
        SapBERT is trained to use the [CLS] token for entity representation.
        """
        self._ensure_loaded()
        all_vecs: list[np.ndarray] = []

        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            inputs = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=128,
                return_tensors="pt",
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            with torch.no_grad():
                out  = self._model(**inputs)
                vecs = out.last_hidden_state[:, 0, :]   # [CLS] token
            all_vecs.append(vecs.cpu().float().numpy())

        return np.vstack(all_vecs)

    async def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Async wrapper — returns list-of-lists for TermMapper compatibility."""
        return self.embed(texts).tolist()
