"""Fault injection used by tests and manual demos (FAULTS=chroma,llm,...).

Components call `check(name)` at their entry points; an active fault raises
`InjectedFault`, which callers treat exactly like a real outage.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

KNOWN_FAULTS = {"chroma", "embedding", "llm", "ocr", "bm25", "vision"}

_lock = threading.Lock()
_active: set[str] = set()


class InjectedFault(RuntimeError):
    pass


def configure(spec: str) -> None:
    with _lock:
        _active.clear()
        _active.update(f.strip() for f in spec.split(",") if f.strip() in KNOWN_FAULTS)


def check(name: str) -> None:
    if name in _active:
        raise InjectedFault(f"injected {name} fault")


def is_active(name: str) -> bool:
    return name in _active


@contextmanager
def injected(*names: str) -> Iterator[None]:
    with _lock:
        added = set(names) - _active
        _active.update(added)
    try:
        yield
    finally:
        with _lock:
            _active.difference_update(added)
