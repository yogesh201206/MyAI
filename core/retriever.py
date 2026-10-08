"""
core/retriever.py — Persistent FAISS vector index management and retrieval.

Features:
  - Uses faiss.IndexIDMap(faiss.IndexFlatIP(384)) for cosine similarity
  - Vector IDs map 1-to-1 with SQLite chunk_id primary keys
  - Persistent index file at ~/.myai/kb/faiss.index
  - Incremental addition, deletion by chunk IDs, and fast nearest-neighbor search
"""

import os
import faiss
import numpy as np

import config

_INDEX = None
_DIM = 384


def get_index_path() -> str:
    """Return the absolute path to the FAISS index file."""
    return config.KB_INDEX_FILE


def _init_empty_index() -> faiss.Index:
    """Create a new empty IndexIDMap wrapping IndexFlatIP."""
    flat_index = faiss.IndexFlatIP(_DIM)
    return faiss.IndexIDMap(flat_index)


def get_index() -> faiss.Index:
    """
    Get or load the FAISS index singleton from disk.
    If the index file does not exist, an empty index is initialized.
    """
    global _INDEX
    if _INDEX is not None:
        return _INDEX

    index_path = get_index_path()
    if os.path.exists(index_path):
        try:
            _INDEX = faiss.read_index(index_path)
            return _INDEX
        except Exception:
            _INDEX = _init_empty_index()
            return _INDEX
    else:
        _INDEX = _init_empty_index()
        return _INDEX


def save_index():
    """Persist the in-memory FAISS index to disk."""
    global _INDEX
    if _INDEX is None:
        return

    index_path = get_index_path()
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    faiss.write_index(_INDEX, index_path)


def add_chunks_to_index(chunk_ids: list[int], vectors: np.ndarray):
    """
    Add vectors with their explicit SQLite chunk IDs into the FAISS index and persist.

    Args:
        chunk_ids: list of int IDs (positive integers)
        vectors: float32 np.ndarray of shape (len(chunk_ids), 384)
    """
    if not chunk_ids or len(vectors) == 0:
        return

    index = get_index()
    ids_arr = np.array(chunk_ids, dtype=np.int64)

    # Ensure vectors are float32 and 2D
    vecs = np.ascontiguousarray(vectors, dtype=np.float32)
    if vecs.ndim == 1:
        vecs = vecs.reshape(1, -1)

    index.add_with_ids(vecs, ids_arr)
    save_index()


def remove_chunks_from_index(chunk_ids: list[int]):
    """
    Remove vectors corresponding to the given chunk IDs from the FAISS index.
    """
    if not chunk_ids:
        return

    index = get_index()
    ids_arr = np.array(chunk_ids, dtype=np.int64)
    try:
        index.remove_ids(ids_arr)
        save_index()
    except Exception:
        pass


def clear_index():
    """Reset the FAISS index to empty and remove or overwrite index file."""
    global _INDEX
    _INDEX = _init_empty_index()
    save_index()


def search_index(query_vector: np.ndarray, top_k: int = 5) -> list[tuple[int, float]]:
    """
    Search nearest vectors by cosine similarity.

    Args:
        query_vector: float32 array of shape (1, 384) or (384,)
        top_k: maximum number of nearest neighbors to retrieve

    Returns:
        list of (chunk_id: int, similarity_score: float), sorted by score descending
    """
    index = get_index()
    if index.ntotal == 0:
        return []

    q = np.ascontiguousarray(query_vector, dtype=np.float32)
    if q.ndim == 1:
        q = q.reshape(1, -1)

    k = min(top_k, index.ntotal)
    distances, indices = index.search(q, k)

    results = []
    if len(indices) > 0 and len(distances) > 0:
        for chunk_id, score in zip(indices[0], distances[0]):
            if chunk_id != -1:  # FAISS uses -1 for unfilled slots
                results.append((int(chunk_id), float(score)))

    return results


def get_total_vectors() -> int:
    """Return the total number of vectors in the index."""
    try:
        index = get_index()
        return int(index.ntotal)
    except Exception:
        return 0


def get_index_size_bytes() -> int:
    """Return the size of the index file on disk in bytes."""
    path = get_index_path()
    return os.path.getsize(path) if os.path.exists(path) else 0
