"""Fault injection for failure tests and demos (FAULTS=pdf_agent,vector,...).

Components call `check(name)` at their entry points; an active fault raises
the matching exception so callers exercise their real failure paths.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

KNOWN = {
    "pdf_agent",  # permanent PDF agent crash
    "map_agent",  # permanent map agent crash
    "pdf_transient",  # transient error on every PDF attempt
    "map_transient",
    "pdf_flaky",  # transient error on the first attempt only
    "pdf_invalid_output",  # agent returns schema-invalid output
    "map_invalid_output",
    "pdf_timeout",  # agent exceeds its time budget
    "vector",  # vector store outage
    "lexical",  # lexical index outage
    "llm",  # answer generator outage
    "fusion",  # fusion crash
}

_lock = threading.Lock()
_active: set[str] = set()
_hits: dict[str, int] = {}


class InjectedFault(RuntimeError):
    """Permanent injected failure."""


class InjectedTransientFault(RuntimeError):
    """Transient injected failure (eligible for retry)."""


def configure(spec: str) -> None:
    with _lock:
        _active.clear()
        _hits.clear()
        _active.update(f.strip() for f in spec.split(",") if f.strip() in KNOWN)


def is_active(name: str) -> bool:
    return name in _active


def hit(name: str) -> int:
    """Count calls for faults that only fire on some attempts."""
    with _lock:
        _hits[name] = _hits.get(name, 0) + 1
        return _hits[name]


def check(name: str, transient: bool = False) -> None:
    if name in _active:
        raise (InjectedTransientFault if transient else InjectedFault)(f"injected {name} fault")


@contextmanager
def injected(*names: str) -> Iterator[None]:
    with _lock:
        added = set(names) - _active
        _active.update(added)
        for n in names:
            _hits.pop(n, None)
    try:
        yield
    finally:
        with _lock:
            _active.difference_update(added)
