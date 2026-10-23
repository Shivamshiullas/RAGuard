"""Document registry: the local source of truth for documents, chunks and the index manifest.

Chunks are stored as JSONL on disk, independent of ChromaDB. The BM25 fallback and any
index rebuild read from here, so a ChromaDB outage or corruption never loses content.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .models import Chunk


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Registry:
    def __init__(self, settings: Settings):
        self.s = settings
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.s.registry_path.exists():
            try:
                return json.loads(self.s.registry_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                # A corrupt registry is rebuilt from the chunk files that still exist.
                return self._rebuild_from_chunks()
        return {"documents": {}, "manifest": {}}

    def _rebuild_from_chunks(self) -> dict[str, Any]:
        docs: dict[str, Any] = {}
        for f in self.s.chunks_dir.glob("*.jsonl"):
            chunks = [Chunk.from_dict(json.loads(l)) for l in f.read_text(encoding="utf-8").splitlines() if l]
            if chunks:
                docs[f.stem] = {"doc_id": f.stem, "filename": chunks[0].filename, "status": "ready",
                                "pages": max(c.page for c in chunks), "chunks": len(chunks),
                                "recovered": True}
        return {"documents": docs, "manifest": {}}

    def _save(self) -> None:
        _atomic_write(self.s.registry_path, json.dumps(self._data, indent=2))

    # Documents --------------------------------------------------------------------------
    def documents(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._data["documents"].values(), key=lambda d: d.get("uploaded_at", 0), reverse=True)

    def get(self, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data["documents"].get(doc_id)

    def upsert_document(self, doc_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            doc = self._data["documents"].setdefault(doc_id, {"doc_id": doc_id, "uploaded_at": time.time()})
            doc.update(fields)
            self._save()
            return dict(doc)

    def remove_document(self, doc_id: str) -> None:
        with self._lock:
            self._data["documents"].pop(doc_id, None)
            self._save()
            p = self.chunk_path(doc_id)
            if p.exists():
                p.unlink()

    # Chunks -----------------------------------------------------------------------------
    def chunk_path(self, doc_id: str) -> Path:
        return self.s.chunks_dir / f"{doc_id}.jsonl"

    def save_chunks(self, doc_id: str, chunks: list[Chunk]) -> None:
        _atomic_write(self.chunk_path(doc_id), "\n".join(json.dumps(c.to_dict(), ensure_ascii=False) for c in chunks))

    def load_chunks(self, doc_id: str) -> list[Chunk]:
        p = self.chunk_path(doc_id)
        if not p.exists():
            return []
        return [Chunk.from_dict(json.loads(l)) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def all_chunks(self, ready_only: bool = True) -> list[Chunk]:
        out: list[Chunk] = []
        for d in self.documents():
            if ready_only and d.get("status") != "ready":
                continue
            out.extend(self.load_chunks(d["doc_id"]))
        return out

    def chunk_by_id(self) -> dict[str, Chunk]:
        return {c.chunk_id: c for c in self.all_chunks(ready_only=False)}

    # Index manifest ---------------------------------------------------------------------
    def manifest(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data.get("manifest", {}))

    def set_manifest(self, **fields: Any) -> None:
        with self._lock:
            self._data.setdefault("manifest", {}).update(fields)
            self._save()
