"""Retrieval for RAG: exact/lexical (SQLite FTS5) + vector (ChromaDB, local
MiniLM embeddings), fused by reciprocal rank, with metadata filters.

Failure rules (failsafe #3):
- vector fails  -> lexical only, if lexical fallback is enabled and healthy (DEGRADED)
- vector fails and lexical unavailable/disabled -> FAILED; callers return
  insufficient evidence, never an unsupported answer
- lexical fails -> vector only (DEGRADED); exact ID lookups may be missed
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
from .runtime import get_repo
from .schemas import StageState

log = logging.getLogger(__name__)

COLLECTION = "landiq_chunks"
RRF_K = 60
EXACT_TOKEN = re.compile(r"#\d{3,5}|\b\d{1,5}/[\dA-Za-z]{1,4}\b|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|[₹]|\brs\.?\s*\d", re.I)

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="retrieval")


class VectorStore:
    def __init__(self):
        self._collection = None
        self._embedder = None
        self._lock = threading.Lock()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            self._embedder = DefaultEmbeddingFunction()
        return [list(map(float, v)) for v in self._embedder(texts)]

    def _get(self):
        faults.check("vector")
        with self._lock:
            if self._collection is None:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                client = chromadb.PersistentClient(path=str(get_settings().chroma_dir),
                                                   settings=ChromaSettings(anonymized_telemetry=False))
                self._collection = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"},
                                                                   embedding_function=None)
            return self._collection

    def index(self, project_id: str, document_id: str, rows: list[dict]) -> None:
        col = self._get()
        col.delete(where={"document_id": document_id})
        for start in range(0, len(rows), 64):
            batch = rows[start:start + 64]
            col.upsert(
                ids=[r["chunk_id"] for r in batch],
                embeddings=self._embed([r["text"] for r in batch]),
                documents=[r["text"] for r in batch],
                metadatas=[{"project_id": project_id, "document_id": document_id, "page": r["page"],
                            "case_ids": " ".join(r["case_ids"])} for r in batch],
            )

    def query(self, project_id: str, text: str, k: int, document_ids: list[str] | None) -> list[tuple[str, float]]:
        col = self._get()
        where: dict = {"project_id": project_id}
        if document_ids:
            where = {"$and": [where, {"document_id": {"$in": document_ids}}]}
        res = col.query(query_embeddings=self._embed([text]), n_results=k, where=where, include=["distances"])
        ids = res["ids"][0] if res["ids"] else []
        return [(cid, 1.0 - float(d)) for cid, d in zip(ids, res["distances"][0])]

    def ping(self) -> bool:
        try:
            self._get().count()
            return True
        except Exception:  # noqa: BLE001
            return False


_vectors: VectorStore | None = None


def get_vectors() -> VectorStore:
    global _vectors
    if _vectors is None:
        _vectors = VectorStore()
    return _vectors


def reset_vector_store() -> None:
    global _vectors
    _vectors = None


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    filename: str
    page: int
    text: str
    case_ids: list[str]
    score: float
    methods: set[str] = field(default_factory=set)


@dataclass
class RetrievalResult:
    hits: list[Hit]
    state: StageState
    methods: list[str]
    warnings: list[str]


def index_chunks(project_id: str, document_id: str, rows: list[dict]) -> tuple[StageState, list[str]]:
    """Lexical index is required; vector index is best-effort (a failure degrades, not fails)."""
    get_repo().replace_chunks(project_id, document_id, rows)
    if not get_settings().vector_enabled:
        return StageState.DEGRADED, ["Vector retrieval is disabled; lexical search only."]
    try:
        get_vectors().index(project_id, document_id, rows)
        return StageState.SUCCEEDED, []
    except Exception as exc:  # noqa: BLE001
        log.warning("Vector indexing failed for %s: %s", document_id, type(exc).__name__)
        return StageState.DEGRADED, ["Vector indexing failed; this document is searchable by exact/lexical lookup only."]


def _rrf(rankings: list[list[tuple[str, float]]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, (cid, _) in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    return scores


def retrieve(project_id: str, query: str, k: int | None = None, case_ref: str | None = None,
             document_ids: list[str] | None = None) -> RetrievalResult:
    settings = get_settings()
    k = k or settings.retrieval_top_k
    repo = get_repo()
    warnings: list[str] = []
    methods: list[str] = []
    rankings: list[list[tuple[str, float]]] = []
    method_of: dict[str, set[str]] = {}

    vector_ok = False
    if settings.vector_enabled:
        try:
            future = _pool.submit(get_vectors().query, project_id, query, k * 3, document_ids)
            vec = [(cid, s) for cid, s in future.result(timeout=settings.retrieval_timeout_s)
                   if s >= settings.min_vector_similarity]
            vector_ok = True
            methods.append("vector")
            rankings.append(vec)
            for cid, _ in vec:
                method_of.setdefault(cid, set()).add("vector")
        except (Exception, FutureTimeout) as exc:  # noqa: BLE001
            log.warning("Vector retrieval failed: %s", type(exc).__name__)
            warnings.append("Vector search is unavailable.")

    lexical_ok = False
    lexical_allowed = settings.lexical_fallback_enabled or vector_ok
    if lexical_allowed:
        try:
            faults.check("lexical")
            lex = repo.lexical_search(project_id, query, k * 3, document_ids)
            lexical_ok = True
            methods.append("lexical")
            rankings.append(lex)
            for cid, _ in lex:
                method_of.setdefault(cid, set()).add("lexical")
        except Exception as exc:  # noqa: BLE001
            log.warning("Lexical retrieval failed: %s", type(exc).__name__)
            warnings.append("Exact/lexical search is unavailable.")

    if not vector_ok and not lexical_ok:
        return RetrievalResult([], StageState.FAILED, [], warnings + ["No healthy retrieval method is available."])

    scores = _rrf(rankings)
    # Exact identifiers in the question (case refs, survey numbers, dates) must appear in the chunk.
    exact = [t.lower() for t in EXACT_TOKEN.findall(query) if t.startswith("#") or "/" in t]
    meta = repo.get_chunks(list(scores))
    hits: list[Hit] = []
    for cid, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        row = meta.get(cid)
        if row is None:
            continue
        if case_ref and case_ref not in row["case_ids"]:
            continue
        if exact and not any(e in row["text"].lower() or e in [c.lower() for c in row["case_ids"]] for e in exact):
            continue
        hits.append(Hit(cid, row["document_id"], row["filename"], row["page"], row["text"], row["case_ids"],
                        round(score, 5), method_of.get(cid, set())))
        if len(hits) >= k:
            break

    state = StageState.SUCCEEDED if (vector_ok or not settings.vector_enabled) and lexical_ok else StageState.DEGRADED
    if not settings.vector_enabled:
        state = StageState.DEGRADED if lexical_ok else StageState.FAILED
    return RetrievalResult(hits, state, methods, warnings)
