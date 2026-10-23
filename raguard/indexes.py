"""Embedding model, ChromaDB vector store and the independent BM25 keyword index."""
from __future__ import annotations

import logging
import threading
from typing import Sequence

from rank_bm25 import BM25Okapi

from .config import Settings
from .faults import faults
from .models import Chunk
from .text import tokenize

log = logging.getLogger(__name__)


class IndexMismatch(RuntimeError):
    """The vector index was built with a different embedding model or dimension."""


# Embeddings ------------------------------------------------------------------------------
MODEL_FILES = ("tokenizer.json", "onnx/model.onnx")


class EmbedderNotReady(RuntimeError):
    """The embedding model files are not on disk. Run: python scripts/download_models.py"""


def model_repo(model: str) -> str:
    return model if "/" in model else f"sentence-transformers/{model}"


def download_model(model: str, cache_dir) -> list[str]:
    """Fetch the ONNX model files into ``cache_dir`` (the only place the app downloads from the network)."""
    from huggingface_hub import hf_hub_download

    return [hf_hub_download(model_repo(model), f, cache_dir=str(cache_dir)) for f in MODEL_FILES]


def _onnx_embedder(model: str, cache_dir):
    """Sentence-transformers model run with ONNX Runtime (no PyTorch): mean pooling + L2 norm.

    Loads from the local cache only, so it never downloads inside a request timeout.
    """
    import numpy as np
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    repo = model_repo(model)
    try:
        tok_path, onnx_path = (hf_hub_download(repo, f, cache_dir=str(cache_dir), local_files_only=True)
                               for f in MODEL_FILES)
    except Exception as e:
        raise EmbedderNotReady(f"Embedding model '{model}' is not downloaded. "
                               "Run: python scripts/download_models.py") from e
    tok = Tokenizer.from_file(tok_path)
    tok.enable_truncation(256)
    tok.enable_padding(pad_id=0, pad_token="[PAD]")
    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    input_names = {i.name for i in session.get_inputs()}

    def embed(texts):
        out: list[list[float]] = []
        texts = list(texts)
        for start in range(0, len(texts), 32):
            enc = tok.encode_batch(texts[start:start + 32])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in input_names:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = session.run(None, feeds)[0]
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            out.extend(pooled.astype(float).tolist())
        return out

    return embed


def _hash_embedder(dim: int = 384):
    """Deterministic bag-of-words hashing embedder. For offline tests only, not for real use."""
    import hashlib
    import math

    def embed(texts):
        out = []
        for t in texts:
            v = [0.0] * dim
            for tok in tokenize(t):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % dim] += 1.0 if (h >> 8) % 2 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out

    return embed


class Embedder:
    def __init__(self, s: Settings):
        self.s = s
        self._fn = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return f"{self.s.embedding_backend}:{self.s.embedding_model}"

    @property
    def loaded(self) -> bool:
        return self._fn is not None

    def load(self):
        """Load the model. Call this at startup, outside any request timeout."""
        with self._lock:
            if self._fn is None:
                backend = self.s.embedding_backend
                if backend == "hash":
                    self._fn = _hash_embedder()
                elif backend == "sentence-transformers":
                    from sentence_transformers import SentenceTransformer

                    model = SentenceTransformer(self.s.embedding_model, cache_folder=str(self.s.models_dir),
                                                local_files_only=True)
                    self._fn = lambda texts: model.encode(list(texts), normalize_embeddings=True).tolist()
                else:
                    self._fn = _onnx_embedder(self.s.embedding_model, self.s.models_dir)
        return self._fn

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.s.on("fault_injection"):
            faults.before_embedding(self.s.embed_timeout_s)
        if self._fn is None:
            raise EmbedderNotReady("Embedding model not loaded; the service warms it up at startup.")
        return self._fn(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def dimension(self) -> int:
        return len(self.load()(["dimension probe"])[0])


# ChromaDB --------------------------------------------------------------------------------
class ChromaStore:
    def __init__(self, s: Settings):
        self.s = s
        self._client = None
        self._collection = None
        self._lock = threading.Lock()

    @property
    def location(self) -> str:
        return f"http://{self.s.chroma_host}:{self.s.chroma_port}" if self.s.chroma_host else f"embedded ({self.s.chroma_dir})"

    def _coll(self):
        if self.s.on("fault_injection"):
            faults.before_chroma()
        with self._lock:
            if self._collection is None:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                cfg = ChromaSettings(anonymized_telemetry=False)
                if self.s.chroma_host:
                    self._client = chromadb.HttpClient(host=self.s.chroma_host, port=self.s.chroma_port, settings=cfg)
                else:
                    self._client = chromadb.PersistentClient(path=str(self.s.chroma_dir), settings=cfg)
                self._collection = self._client.get_or_create_collection(
                    self.s.chroma_collection, metadata={"hnsw:space": "cosine"}, embedding_function=None)
        return self._collection

    def reset_connection(self) -> None:
        """Drop the cached client so the next call reconnects (used between retries)."""
        with self._lock:
            self._client, self._collection = None, None

    def heartbeat(self) -> bool:
        self._coll()
        self._client.heartbeat()
        return True

    def count(self) -> int:
        return self._coll().count()

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]], embedder_name: str) -> None:
        coll = self._coll()
        for start in range(0, len(chunks), 256):
            batch = chunks[start:start + 256]
            coll.upsert(
                ids=[c.chunk_id for c in batch],
                embeddings=embeddings[start:start + 256],
                documents=[c.text for c in batch],
                metadatas=[{"doc_id": c.doc_id, "page": c.page, "kind": c.kind, "filename": c.filename,
                            "embedder": embedder_name} for c in batch],
            )

    def delete_document(self, doc_id: str) -> None:
        self._coll().delete(where={"doc_id": doc_id})

    def ids_for(self, doc_id: str) -> list[str]:
        return self._coll().get(where={"doc_id": doc_id}, include=[])["ids"]

    def query(self, embedding: list[float], k: int, doc_ids: list[str] | None = None) -> list[tuple[str, float]]:
        """Return (chunk_id, cosine similarity) pairs, best first."""
        coll = self._coll()
        n = coll.count()
        if n == 0:
            return []
        where = None
        if doc_ids:
            where = {"doc_id": doc_ids[0]} if len(doc_ids) == 1 else {"doc_id": {"$in": list(doc_ids)}}
        res = coll.query(query_embeddings=[embedding], n_results=min(k, n), where=where, include=["distances"])
        ids, dists = res["ids"][0], res["distances"][0]
        return [(i, 1.0 - float(d)) for i, d in zip(ids, dists)]


# BM25 ------------------------------------------------------------------------------------
class BM25Store:
    """Keyword index built from the registry's chunk files, held in memory.

    It never touches ChromaDB, so it stays available during a vector-store outage.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chunks: list[Chunk] = []
        self._bm25: BM25Okapi | None = None

    def rebuild(self, chunks: list[Chunk]) -> None:
        corpus = [tokenize(c.text) for c in chunks]
        with self._lock:
            self._chunks = list(chunks)
            self._bm25 = BM25Okapi(corpus) if corpus else None

    @property
    def size(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> list[Chunk]:
        with self._lock:
            return list(self._chunks)

    def idf(self) -> tuple[dict[str, float], float]:
        """Term weights from the corpus, plus the weight used for words not in the corpus."""
        with self._lock:
            bm25 = self._bm25
        if bm25 is None:
            return {}, 1.0
        idf = dict(bm25.idf)
        return idf, max(idf.values(), default=1.0)

    def search(self, query: str, k: int, doc_ids: list[str] | None = None) -> list[tuple[Chunk, float]]:
        with self._lock:
            bm25, chunks = self._bm25, self._chunks
        terms = tokenize(query)
        if bm25 is None or not terms:
            return []
        scores = bm25.get_scores(terms)
        allowed = set(doc_ids) if doc_ids else None
        ranked = sorted(
            ((chunks[i], float(sc)) for i, sc in enumerate(scores)
             if sc > 0 and (allowed is None or chunks[i].doc_id in allowed)),
            key=lambda x: x[1], reverse=True)
        return ranked[:k]
