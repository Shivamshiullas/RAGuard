"""Negative-result cache for college questions that the indexed documents
cannot answer.

Entries are keyed by the normalized question plus intent/filters and are only
valid for the knowledge-base generation they were recorded in (with a TTL as a
safety net). Indexing, replacing or (de)activating a document bumps the
generation, so the next identical question retrieves again.
"""

from __future__ import annotations

import hashlib
import re
import time

from .config import get_settings
from .runtime import get_store

_FILLER = re.compile(
    r"\b(please|pls|plz|kindly|can you|could you|would you|tell me|let me know|i want to know|"
    r"do you know|hey|hi|hello)\b"
)


def normalize_query(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\bsem\b\.?", "semester", text)
    text = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", text)
    text = _FILLER.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def cache_key(question: str, intent: str = "college_specific", category: str | None = None,
              semester: str | None = None, academic_year: str | None = None) -> tuple[str, str]:
    normalized = normalize_query(question)
    parts = [normalized, intent, normalize_query(category or ""), normalize_query(semester or ""),
             normalize_query(academic_year or "")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest(), normalized


def lookup(key: str) -> bool:
    """True when a still-valid 'no evidence' result exists for this key."""
    store = get_store()
    entry = store.negative_get(key)
    if entry is None:
        return False
    generation, created_at = entry
    expired = time.time() - created_at > get_settings().negative_cache_ttl_s
    if generation != store.kb_generation() or expired:
        store.negative_delete(key)
        return False
    return True


def record(key: str, normalized: str, generation: int) -> None:
    """`generation` must be the one read *before* retrieval ran, so a document
    indexed mid-request never makes a stale miss look current."""
    get_store().negative_put(key, normalized, generation)
