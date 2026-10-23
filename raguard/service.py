"""Application facade used by the UI, the evaluation runner and the tests."""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .answering import Answerer
from .config import Settings, get_settings
from .faults import faults
from .indexes import BM25Store, ChromaStore, Embedder
from .ingestion import UploadRejected, build_chunks, extract, ocr_status, safe_filename, validate_upload
from .llm import LLMClient
from .models import AnswerResult, RetrievalResult
from .registry import Registry
from .retrieval import RetrievalController

log = logging.getLogger(__name__)


@dataclass
class IngestOutcome:
    ok: bool
    doc_id: str | None
    filename: str
    message: str
    warnings: list[str] = field(default_factory=list)


class RAGuard:
    def __init__(self, settings: Settings | None = None, llm: LLMClient | None = None):
        self.s = settings or get_settings()
        self.registry = Registry(self.s)
        self.embedder = Embedder(self.s)
        self.chroma = ChromaStore(self.s)
        self.bm25 = BM25Store()
        self.llm = llm or LLMClient(self.s)
        self.controller = RetrievalController(self.s, self.registry, self.embedder, self.chroma, self.bm25)
        self.answerer = Answerer(self.llm)
        self.refresh_keyword_index()

    # Index maintenance ------------------------------------------------------------------
    def refresh_keyword_index(self) -> None:
        self.bm25.rebuild(self.registry.all_chunks())

    def warm_up(self) -> None:
        """Load the embedding model once so the first question doesn't hit the embed timeout."""
        try:
            dim = self.embedder.dimension()
            if not self.registry.manifest():
                self.registry.set_manifest(embedder=self.embedder.name, dimension=dim)
        except Exception as e:
            log.warning("embedding warm-up failed: %s", e)

    def rebuild_vector_index(self) -> str:
        """Re-embed every chunk from the local source of truth (fixes stale/mismatched indexes)."""
        chunks = self.registry.all_chunks()
        try:
            self.chroma.reset_connection()
            coll = self.chroma._coll()
            existing = coll.get(include=[])["ids"]
            if existing:
                coll.delete(ids=existing)
        except Exception as e:
            return f"Could not reach ChromaDB: {e}"
        if chunks:
            vecs = self.embedder.embed([c.text for c in chunks])
            self.chroma.upsert(chunks, vecs, self.embedder.name)
            self.registry.set_manifest(embedder=self.embedder.name, dimension=len(vecs[0]), rebuilt_at=time.time())
        for d in self.registry.documents():
            if d.get("status") == "ready":
                self.registry.upsert_document(d["doc_id"], vector_indexed=True)
        return f"Rebuilt vector index: {len(chunks)} chunks re-embedded with {self.embedder.name}."

    def index_health(self) -> dict:
        info = {"bm25_chunks": self.bm25.size, "registry_chunks": len(self.registry.all_chunks()),
                "chroma": "unknown", "chroma_chunks": None, "location": self.chroma.location}
        try:
            info["chroma_chunks"] = self.chroma.count()
            info["chroma"] = "online"
        except Exception as e:
            info["chroma"] = f"unreachable ({type(e).__name__})"
        ok, msg = self.controller.check_manifest()
        info["manifest_ok"], info["manifest"] = ok, msg
        info["in_sync"] = info["chroma_chunks"] == info["registry_chunks"]
        return info

    # Documents --------------------------------------------------------------------------
    def ingest(self, filename: str, data: bytes) -> IngestOutcome:
        name = safe_filename(filename)
        try:
            sha = validate_upload(name, data, self.s)
        except UploadRejected as e:
            return IngestOutcome(False, None, name, str(e))
        doc_id = sha[:16]
        existing = self.registry.get(doc_id)
        if existing and existing.get("status") == "ready":
            return IngestOutcome(True, doc_id, existing["filename"], "Already in the library (identical file).")

        path = self.s.uploads_dir / f"{doc_id}{Path(name).suffix.lower()}"
        path.write_bytes(data)
        self.registry.upsert_document(doc_id, filename=name, sha256=sha, status="processing", size=len(data),
                                      path=str(path), error=None)
        try:
            report = extract(path, doc_id, self.s)
        except UploadRejected as e:
            self.registry.upsert_document(doc_id, status="rejected", error=str(e))
            return IngestOutcome(False, doc_id, name, str(e))
        except Exception as e:
            log.exception("extraction failed")
            self.registry.upsert_document(doc_id, status="failed", error=f"{type(e).__name__}: {e}")
            return IngestOutcome(False, doc_id, name, f"Processing failed: {e}")

        chunks = build_chunks(report, doc_id, name, sha[:8], self.s)
        if not chunks:
            msg = "No readable text was found" + ("; OCR is unavailable." if not ocr_status()[0] else ".")
            self.registry.upsert_document(doc_id, status="failed", error=msg, pages=len(report.pages))
            return IngestOutcome(False, doc_id, name, msg, report.warnings)
        self.registry.save_chunks(doc_id, chunks)

        # Vector indexing is retried; if ChromaDB is down the document is still searchable via BM25.
        warnings = list(report.warnings)
        vector_indexed = False
        try:
            vecs = self.embedder.embed([c.text for c in chunks])
            for attempt in range(self.s.retry_attempts + 1):
                try:
                    self.chroma.delete_document(doc_id)
                    self.chroma.upsert(chunks, vecs, self.embedder.name)
                    vector_indexed = True
                    break
                except Exception:
                    self.chroma.reset_connection()
                    if attempt == self.s.retry_attempts:
                        raise
                    time.sleep(self.s.backoff_base_s * 2 ** attempt)
            if not self.registry.manifest():
                self.registry.set_manifest(embedder=self.embedder.name, dimension=len(vecs[0]))
        except Exception as e:
            warnings.append(f"Vector indexing failed ({type(e).__name__}: {e}). The document is searchable "
                            "with keyword search; use 'Rebuild vector index' once ChromaDB is back.")

        self.registry.upsert_document(
            doc_id, status="ready", pages=len(report.pages), chunks=len(chunks),
            ocr_pages=report.ocr_pages, visual_pages=report.visual_pages, failed_pages=report.failed_pages,
            warnings=warnings, vector_indexed=vector_indexed, processed_at=time.time())
        self.refresh_keyword_index()
        return IngestOutcome(True, doc_id, name, f"Indexed {len(chunks)} chunks from {len(report.pages)} pages.",
                             warnings)

    def delete(self, doc_id: str) -> str:
        msg = "Removed document, chunks, page images and keyword index entries."
        try:
            self.chroma.delete_document(doc_id)
        except Exception as e:
            msg += f" ChromaDB was unreachable ({type(e).__name__}); its vectors will be cleared on the next rebuild."
        doc = self.registry.get(doc_id) or {}
        if doc.get("path"):
            Path(doc["path"]).unlink(missing_ok=True)
        shutil.rmtree(self.s.pages_dir / doc_id, ignore_errors=True)
        self.registry.remove_document(doc_id)
        self.refresh_keyword_index()
        return msg

    def documents(self) -> list[dict]:
        return self.registry.documents()

    # Q&A --------------------------------------------------------------------------------
    def retrieve(self, question: str, doc_ids: list[str] | None = None) -> RetrievalResult:
        return self.controller.retrieve(question, doc_ids)

    def ask(self, question: str, doc_ids: list[str] | None = None) -> AnswerResult:
        t0 = time.monotonic()
        result = self.answerer.answer(self.retrieve(question, doc_ids))
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    def system_status(self) -> dict:
        ocr_ok, ocr_msg = ocr_status()
        return {"llm": self.llm.description, "llm_enabled": self.llm.enabled, "llm_status": self.llm.status,
                "vision": self.llm.supports_images(), "ocr": ocr_ok, "ocr_message": ocr_msg,
                "embedder": self.embedder.name, "faults": faults.flags.active(), **self.index_health()}
