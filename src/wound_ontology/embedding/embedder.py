import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel

class Embedder:
    def __init__(self):
        # We use the SapBERT model specifically trained for entity alignment
        self.model_name = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModel.from_pretrained(self.model_name)

        self.model.eval()

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        Returns entity embeddings using the [CLS] token.
        SapBERT is specifically trained to use the [CLS] representation.
        """
        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            return_tensors="pt"
        )

        with torch.no_grad():
            outputs = self.model(**inputs)
            
            # SapBERT documentation recommends using the [CLS] token (index 0) 
            # for entity representation rather than mean pooling.
            embeddings = outputs.last_hidden_state[:, 0, :]

        return embeddings.cpu().numpy()
    
    async def create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Async wrapper for embed method, returns list of lists for compatibility.
        """
        embeddings = self.embed(texts)
        return embeddings.tolist()
    
pmb = Embedder()
# Test embedding
test_texts = ["Wound healing involves inflammation and tissue repair.", "Chronic wounds are difficult to heal."]
embeddings = pmb.embed(test_texts)
print("Embeddings shape:", embeddings.shape)
print("First embedding:", embeddings[0][:5])  # Print first 5 values    