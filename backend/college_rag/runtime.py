"""Process-wide singletons (store, vector store), replaceable in tests."""

from __future__ import annotations

import threading

from .config import get_settings
from .store import Store
from .vector_store import VectorStore

_lock = threading.Lock()
_store: Store | None = None
_vectors: VectorStore | None = None


def get_store() -> Store:
    global _store
    with _lock:
        if _store is None:
            _store = Store(get_settings().db_path)
        return _store


def get_vectors() -> VectorStore:
    global _vectors
    with _lock:
        if _vectors is None:
            _vectors = VectorStore(get_settings().chroma_dir)
        return _vectors


def reset() -> None:
    """Drop singletons so the next call re-reads settings (tests)."""
    global _store, _vectors
    with _lock:
        _store = None
        _vectors = None
