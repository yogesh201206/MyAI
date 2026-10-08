"""
core/embeddings.py — Embedding generation and model lifecycle.

Features:
  - Lazy loading: model is never loaded on AIZEN startup unless KB is accessed
  - Uses sentence-transformers/all-MiniLM-L6-v2 (384-dimensional)
  - Unit L2 normalized float32 vectors for cosine similarity
  - Safe error handling
"""

import numpy as np

_EMBEDDING_MODEL = None
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


def get_model_name() -> str:
    """Return the active embedding model identifier."""
    return _MODEL_NAME


def get_embedding_dimension() -> int:
    """Return the vector dimensionality."""
    return _EMBEDDING_DIM


def is_model_loaded() -> bool:
    """Check if the embedding model is currently in memory."""
    return _EMBEDDING_MODEL is not None


def get_embedding_model():
    """
    Lazy-load and return the embedding model singleton.
    Raises RuntimeError on failure.
    """
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL

    # Prefer fastembed (ONNX runtime, lightweight, no PyTorch overhead)
    try:
        from fastembed import TextEmbedding
        _EMBEDDING_MODEL = TextEmbedding(model_name=_MODEL_NAME)
        return _EMBEDDING_MODEL
    except ImportError:
        pass

    # Fallback to sentence_transformers if installed
    try:
        from sentence_transformers import SentenceTransformer
        _EMBEDDING_MODEL = SentenceTransformer(_MODEL_NAME)
        return _EMBEDDING_MODEL
    except Exception as e:
        raise RuntimeError(
            f"Failed to load embedding model '{_MODEL_NAME}': {e}\n"
            "Please ensure fastembed or sentence-transformers is installed."
        )


def _normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize 2D numpy array along axis 1."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def embed_texts(texts: list[str]) -> np.ndarray:
    """
    Generate normalized float32 embeddings for a list of text strings.

    Returns:
        np.ndarray of shape (len(texts), 384), dtype=float32
    """
    if not texts:
        return np.empty((0, _EMBEDDING_DIM), dtype=np.float32)

    model = get_embedding_model()

    # Fastembed returns a generator of numpy arrays
    if hasattr(model, "embed"):
        generator = model.embed(texts)
        embeddings = np.array(list(generator), dtype=np.float32)
    else:
        # SentenceTransformer returns numpy array directly
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        embeddings = np.array(embeddings, dtype=np.float32)

    return _normalize(embeddings)


def embed_query(query: str) -> np.ndarray:
    """
    Generate a normalized float32 embedding for a single search query.

    Returns:
        np.ndarray of shape (1, 384), dtype=float32
    """
    cleaned = (query or "").strip()
    if not cleaned:
        vec = np.zeros((1, _EMBEDDING_DIM), dtype=np.float32)
        return vec

    embeddings = embed_texts([cleaned])
    return embeddings
