"""ChromaDB persistence with local ONNX MiniLM embeddings."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from . import faults

log = logging.getLogger(__name__)

COLLECTION = "college_chunks"


@dataclass
class VectorHit:
    chunk_id: str
    similarity: float


class VectorStore:
    def __init__(self, path: Path):
        self.path = path
        self._collection = None
        self._embedder = None
        self._lock = threading.Lock()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        faults.check("embedding")
        if self._embedder is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            self._embedder = DefaultEmbeddingFunction()
        return [list(map(float, v)) for v in self._embedder(texts)]

    def _get(self):
        faults.check("chroma")
        with self._lock:
            if self._collection is None:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                client = chromadb.PersistentClient(
                    path=str(self.path), settings=ChromaSettings(anonymized_telemetry=False)
                )
                self._collection = client.get_or_create_collection(
                    COLLECTION, metadata={"hnsw:space": "cosine"}, embedding_function=None
                )
            return self._collection

    def add(self, ids: list[str], texts: list[str], metadatas: list[dict]) -> None:
        collection = self._get()
        for start in range(0, len(ids), 64):
            batch = slice(start, start + 64)
            collection.upsert(
                ids=ids[batch], documents=texts[batch], metadatas=metadatas[batch], embeddings=self._embed(texts[batch])
            )

    def delete_version(self, version_key: str) -> None:
        self._get().delete(where={"version_key": version_key})

    def query(self, text: str, version_keys: list[str], k: int) -> list[VectorHit]:
        if not version_keys:
            return []
        collection = self._get()
        embedding = self._embed([text])[0]
        where = {"version_key": version_keys[0]} if len(version_keys) == 1 else {"version_key": {"$in": version_keys}}
        result = collection.query(query_embeddings=[embedding], n_results=k, where=where, include=["distances"])
        ids = result["ids"][0] if result["ids"] else []
        distances = result["distances"][0] if result.get("distances") else []
        return [VectorHit(cid, 1.0 - float(d)) for cid, d in zip(ids, distances)]

    def ping(self) -> bool:
        try:
            self._get().count()
            return True
        except Exception:  # noqa: BLE001
            return False
