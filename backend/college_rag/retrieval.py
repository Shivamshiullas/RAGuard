"""Retrieval: hybrid ChromaDB vector search + BM25 keyword search (fused by
reciprocal rank), with a bounded retry. When the vector path fails, BM25 over
the local text cache is used on its own.

Only the newest indexed version of each active document is searchable.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field

from . import faults
from .config import get_settings
from .runtime import get_store, get_vectors
from .schemas import Passage
from .store import ChunkRow, DocumentRow, VersionRow, version_key

log = logging.getLogger(__name__)

STOPWORDS = set(
    "a an and are as at be by can do does for from has have how i in is it me my of on or please the "
    "this to what when where which who will with you your tell about give know".split()
)

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="retrieval")


@dataclass
class RetrievalOutcome:
    passages: list[Passage]
    method: str  # "vector" | "bm25" | "none"
    completed: bool  # False only when every retrieval path failed
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    attempts: int = 0


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def index_text(doc: DocumentRow, text: str) -> str:
    """Text that gets embedded/keyword-indexed: chunk plus its document context."""
    context = ", ".join(x for x in (doc.category, doc.semester, doc.academic_year) if x)
    return f"{doc.title} ({context})\n{text}"


def _passage(chunk: ChunkRow, doc: DocumentRow, version: VersionRow, score: float) -> Passage:
    return Passage(
        chunk_id=chunk.chunk_id, doc_id=doc.id, version=version.version, title=doc.title,
        filename=version.file_name, page=chunk.page, category=doc.category, semester=doc.semester or "",
        academic_year=doc.academic_year or "", effective_date=doc.effective_date or "", text=chunk.text,
        score=round(score, 4),
    )


class _Bm25Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._index = None
        self._chunks: list[ChunkRow] = []
        self._corpus: list[list[str]] = []

    def search(self, query: str, keys: set[str], generation: int, k: int) -> list[tuple[ChunkRow, float]]:
        faults.check("bm25")
        # BM25Plus keeps IDF positive on small corpora (BM25Okapi scores a term
        # found in half the documents as zero).
        from rank_bm25 import BM25Plus

        with self._lock:
            cache_key = (generation, frozenset(keys))
            if cache_key != self._key:
                self._chunks = get_store().chunks_for_versions(keys)
                searchable = get_store().searchable_versions()
                self._corpus = [
                    tokenize(index_text(searchable[version_key(c.doc_id, c.version)][0], c.text)) for c in self._chunks
                ]
                self._index = BM25Plus(self._corpus) if self._corpus else None
                self._key = cache_key
            index, chunks, corpus = self._index, self._chunks, self._corpus
        terms = tokenize(query)
        if index is None or not terms:
            return []
        scores = index.get_scores(terms)
        # Only chunks sharing at least one query term count as keyword matches.
        matched = [(c, float(s)) for c, s, toks in zip(chunks, scores, corpus) if set(terms) & set(toks)]
        return sorted(matched, key=lambda x: x[1], reverse=True)[:k]


_bm25 = _Bm25Cache()


RRF_K = 60


def _rrf(rankings: list[list[tuple[ChunkRow, float]]]) -> list[tuple[ChunkRow, float]]:
    """Reciprocal-rank fusion of vector and keyword rankings."""
    scores: dict[str, float] = {}
    chunks: dict[str, ChunkRow] = {}
    for ranking in rankings:
        for rank, (chunk, _) in enumerate(ranking):
            chunks[chunk.chunk_id] = chunk
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    order = sorted(scores, key=scores.get, reverse=True)
    return [(chunks[cid], scores[cid]) for cid in order]


def _vector_search(query: str, keys: list[str], k: int):
    return get_vectors().query(query, keys, k)


def retrieve(query: str, k: int | None = None) -> RetrievalOutcome:
    settings = get_settings()
    k = k or settings.top_k
    store = get_store()
    searchable = store.searchable_versions()
    if not searchable:
        return RetrievalOutcome([], "none", completed=True)
    keys = list(searchable)
    warnings: list[str] = []
    attempts = 0

    # 1) Vector search with one bounded retry.
    for attempt in range(1 + settings.retrieval_retries):
        attempts += 1
        try:
            future = _pool.submit(_vector_search, query, keys, k * 2)
            hits = future.result(timeout=settings.retrieval_timeout_s)
        except (Exception, FutureTimeout) as exc:  # noqa: BLE001
            log.warning("Vector search attempt %d failed: %s", attempt + 1, exc)
            continue
        chunk_rows = store.get_chunks([h.chunk_id for h in hits])
        vector_ranked = [
            (chunk_rows[h.chunk_id], h.similarity)
            for h in hits if h.chunk_id in chunk_rows and h.similarity >= settings.min_similarity
        ]
        try:
            keyword_ranked = _bm25.search(query, set(keys), store.kb_generation(), k * 2)
        except Exception as exc:  # noqa: BLE001 - keyword search only refines vector results here
            log.warning("BM25 (hybrid) failed: %s", exc)
            keyword_ranked = []
        fused = _rrf([vector_ranked, keyword_ranked])[:k]
        passages = [_passage(c, *searchable[version_key(c.doc_id, c.version)], score) for c, score in fused]
        return RetrievalOutcome(passages, "vector", completed=True, attempts=attempts)

    # 2) BM25 over the local text cache.
    warnings.append("The main search index was unavailable, so keyword search was used instead.")
    attempts += 1
    try:
        ranked = _bm25.search(query, set(keys), store.kb_generation(), k)
    except Exception as exc:  # noqa: BLE001
        log.error("BM25 fallback failed: %s", exc)
        return RetrievalOutcome([], "none", completed=False, warnings=warnings,
                                error_code="retrieval_unavailable", attempts=attempts)
    passages = []
    for chunk, score in ranked:
        passages.append(_passage(chunk, *searchable[version_key(chunk.doc_id, chunk.version)], score))
    return RetrievalOutcome(passages, "bm25", completed=True, warnings=warnings, attempts=attempts)
