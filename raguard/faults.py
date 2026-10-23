"""Controlled fault injection for the Reliability Demo and the fault test suite.

Injected faults raise the same exception types a real outage would, so the retrieval
controller takes the exact same recovery path. Every event produced while a fault is
active is tagged ``simulated=True`` and labelled as such in the UI.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, fields


class SimulatedFault(Exception):
    """Marker mixin: this failure was injected on purpose."""


class SimulatedConnectionError(SimulatedFault, ConnectionError):
    pass


class SimulatedTimeout(SimulatedFault, TimeoutError):
    pass


@dataclass
class FaultFlags:
    chroma_down: bool = False  # every Chroma call raises a connection error
    embedding_down: bool = False  # the embedding model raises on every call
    embedding_slow: bool = False  # the embedding call sleeps past its timeout
    vector_empty: bool = False  # Chroma "succeeds" but returns no hits
    vector_irrelevant: bool = False  # Chroma returns random, unrelated hits
    llm_down: bool = False  # the language model provider raises

    def active(self) -> list[str]:
        return [f.name for f in fields(self) if getattr(self, f.name)]


LABELS = {
    "chroma_down": "ChromaDB outage",
    "embedding_down": "Embedding model unavailable",
    "embedding_slow": "Embedding timeout",
    "vector_empty": "Vector search returns nothing",
    "vector_irrelevant": "Vector search returns irrelevant chunks",
    "llm_down": "Language model unavailable",
}


class FaultInjector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.flags = FaultFlags()

    def set(self, **kwargs: bool) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if not hasattr(self.flags, k):
                    raise KeyError(k)
                setattr(self.flags, k, bool(v))

    def clear(self) -> None:
        with self._lock:
            self.flags = FaultFlags()

    def is_on(self, name: str) -> bool:
        return bool(getattr(self.flags, name))

    def any_active(self) -> bool:
        return bool(self.flags.active())

    @contextmanager
    def scoped(self, **kwargs: bool):
        """Temporarily enable faults (used by evaluation runs and tests)."""
        with self._lock:
            previous = FaultFlags(**{f.name: getattr(self.flags, f.name) for f in fields(FaultFlags)})
        self.set(**kwargs)
        try:
            yield self
        finally:
            with self._lock:
                self.flags = previous

    # Hooks called by the real components -------------------------------------------------
    def before_chroma(self) -> None:
        if self.flags.chroma_down:
            raise SimulatedConnectionError("Simulated fault: ChromaDB is unreachable")

    def before_embedding(self, timeout_s: float) -> None:
        if self.flags.embedding_down:
            raise SimulatedConnectionError("Simulated fault: embedding model unavailable")
        if self.flags.embedding_slow:
            time.sleep(timeout_s + 0.5)

    def before_llm(self) -> None:
        if self.flags.llm_down:
            raise SimulatedConnectionError("Simulated fault: language model unavailable")


faults = FaultInjector()
