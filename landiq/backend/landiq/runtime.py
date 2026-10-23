"""Process-wide singletons, replaceable in tests."""

from __future__ import annotations

import threading

from .config import get_settings
from .storage import SqliteRepository

_lock = threading.Lock()
_repo: SqliteRepository | None = None


def get_repo() -> SqliteRepository:
    global _repo
    with _lock:
        if _repo is None:
            _repo = SqliteRepository(get_settings().db_path)
        return _repo


def reset() -> None:
    global _repo
    with _lock:
        _repo = None
    from . import retrieval

    retrieval.reset_vector_store()
