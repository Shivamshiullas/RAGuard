"""Application facade: builds the components for the configured stage and exposes the operations
used by the UI, the evaluation script and the tests."""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .answering import Answerer, BasicCitations, EvidenceChecker
from .config import Settings, get_settings
from .faults import faults
from .indexes import BM25Store, ChromaStore, Embedder
from .ingestion import ImageParser, PDFParser, UploadRejected, ocr_status, safe_filename, validate_upload
from .interfaces import Parser, Retriever
from .llm import LLMClient
from .models import AnswerResult, RetrievalResult
from .registry import Registry
from .retrieval import ResilientRetriever, VectorRetriever

log = logging.getLogger(__name__)

STATUS_TTL_S = 15.0


@dataclass
class IngestOutcome:
    ok: bool
    doc_id: str | None
    filename: str
    message: str
    warnings: list[str] = field(default_factory=list)


class RAGuard:
    def __init__(self, settings: Settings | None = None, llm: LLMClient | None = None,
                 embedder: Embedder | None = None):
        self.s = settings or get_settings()
        self.registry = Registry(self.s)
        self.embedder = embedder or Embedder(self.s)
        self.chroma = ChromaStore(self.s)
        self.bm25 = BM25Store()
        self.llm = llm or LLMClient(self.s)
        self.parsers: list[Parser] = [PDFParser(self.s), ImageParser(self.s)]
        self.retriever: Retriever
        if self.s.on("bm25") or self.s.on("fallbacks"):
            self.retriever = ResilientRetriever(self.s, self.registry, self.embedder, self.chroma, self.bm25)
        else:
            self.retriever = VectorRetriever(self.s, self.registry, self.embedder, self.chroma)
        self.answerer = Answerer(self.s, self.llm, EvidenceChecker() if self.s.on("answer_checks") else BasicCitations())
        self._status_cache: tuple[float, dict] | None = None
        self.refresh_indexes()

    @property
    def controller(self) -> Retriever:  # kept for older callers
        return self.retriever

    # Index maintenance ------------------------------------------------------------------
    def refresh_indexes(self) -> None:
        chunks = self.registry.all_chunks()
        if self.s.on("bm25"):
            self.bm25.rebuild(chunks)
        if isinstance(self.retriever, VectorRetriever):
            self.retriever.refresh()
        self._status_cache = None

    refresh_keyword_index = refresh_indexes

    def warm_up(self) -> None:
        """Load the embedding model at startup, outside any request timeout."""
        try:
            self.embedder.load()
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
        self._status_cache = None
        return f"Rebuilt vector index: {len(chunks)} chunks re-embedded with {self.embedder.name}."

    def index_health(self) -> dict:
        docs = [d for d in self.registry.documents() if d.get("status") == "ready"]
        # Chunk counts come from the registry, not from re-reading every JSONL file.
        registry_chunks = sum(int(d.get("chunks", 0)) for d in docs)
        info = {"bm25_chunks": self.bm25.size, "registry_chunks": registry_chunks,
                "chroma": "unknown", "chroma_chunks": None, "location": self.chroma.location}
        try:
            info["chroma_chunks"] = self.chroma.count()
            info["chroma"] = "online"
        except Exception as e:
            info["chroma"] = f"unreachable ({type(e).__name__})"
        if isinstance(self.retriever, ResilientRetriever):
            info["manifest_ok"], info["manifest"] = self.retriever.check_manifest()
        else:
            m = self.registry.manifest()
            ok = not m or m.get("embedder") == self.embedder.name
            info["manifest_ok"], info["manifest"] = ok, f"index built with {m.get('embedder', 'n/a')}"
        info["in_sync"] = info["chroma_chunks"] == registry_chunks
        return info

    # Documents --------------------------------------------------------------------------
    def _parser_for(self, filename: str) -> Parser | None:
        return next((p for p in self.parsers if p.supports(filename)), None)

    def ingest(self, filename: str, data: bytes) -> IngestOutcome:
        name = safe_filename(filename)
        try:
            sha = validate_upload(name, data, self.s)
        except UploadRejected as e:
            return IngestOutcome(False, None, name, str(e))
        parser = self._parser_for(name)
        if parser is None:
            return IngestOutcome(False, None, name, "No parser is enabled for this file type.")
        doc_id = sha[:16]
        existing = self.registry.get(doc_id)
        if existing and existing.get("status") == "ready":
            return IngestOutcome(True, doc_id, existing["filename"], "Already in the library (identical file).")

        path = self.s.uploads_dir / f"{doc_id}{Path(name).suffix.lower()}"
        path.write_bytes(data)
        self.registry.upsert_document(doc_id, filename=name, sha256=sha, status="processing", size=len(data),
                                      path=str(path), error=None)
        try:
            result = parser.parse(path, doc_id, name, sha[:8])
        except UploadRejected as e:
            self.registry.upsert_document(doc_id, status="rejected", error=str(e))
            return IngestOutcome(False, doc_id, name, str(e))
        except Exception as e:
            log.exception("parsing failed")
            self.registry.upsert_document(doc_id, status="failed", error=f"{type(e).__name__}: {e}")
            return IngestOutcome(False, doc_id, name, f"Processing failed: {e}")

        chunks = result.chunks
        if not chunks:
            msg = "No readable text was found."
            if not self.s.on("ocr"):
                msg += " Scanned documents need OCR (Stage 2)."
            elif not ocr_status()[0]:
                msg += " OCR is unavailable."
            self.registry.upsert_document(doc_id, status="failed", error=msg, pages=result.pages)
            return IngestOutcome(False, doc_id, name, msg, result.warnings)
        self.registry.save_chunks(doc_id, chunks)

        warnings = list(result.warnings)
        vector_indexed = False
        try:
            vecs = self.embedder.embed([c.text for c in chunks])
            attempts = self.s.retry_attempts + 1 if self.s.on("fallbacks") else 1
            for attempt in range(attempts):
                try:
                    self.chroma.delete_document(doc_id)
                    self.chroma.upsert(chunks, vecs, self.embedder.name)
                    vector_indexed = True
                    break
                except Exception:
                    self.chroma.reset_connection()
                    if attempt == attempts - 1:
                        raise
                    time.sleep(self.s.backoff_base_s * 2 ** attempt)
            if not self.registry.manifest():
                self.registry.set_manifest(embedder=self.embedder.name, dimension=len(vecs[0]))
        except Exception as e:
            if not self.s.on("bm25"):
                self.registry.upsert_document(doc_id, status="failed", error=f"Indexing failed: {e}")
                return IngestOutcome(False, doc_id, name, f"Indexing failed: {type(e).__name__}: {e}", warnings)
            warnings.append(f"Vector indexing failed ({type(e).__name__}: {e}). The document is searchable "
                            "with keyword search; use 'Rebuild vector index' once ChromaDB is back.")

        self.registry.upsert_document(
            doc_id, status="ready", pages=result.pages, chunks=len(chunks), ocr_pages=result.ocr_pages,
            visual_pages=result.visual_pages, failed_pages=result.failed_pages, warnings=warnings,
            vector_indexed=vector_indexed, processed_at=time.time())
        self.refresh_indexes()
        return IngestOutcome(True, doc_id, name, f"Indexed {len(chunks)} chunks from {result.pages} pages.", warnings)

    def delete(self, doc_id: str) -> str:
        msg = "Removed document, chunks and page images."
        try:
            self.chroma.delete_document(doc_id)
        except Exception as e:
            msg += f" ChromaDB was unreachable ({type(e).__name__}); its vectors will be cleared on the next rebuild."
        doc = self.registry.get(doc_id) or {}
        if doc.get("path"):
            Path(doc["path"]).unlink(missing_ok=True)
        shutil.rmtree(self.s.pages_dir / doc_id, ignore_errors=True)
        self.registry.remove_document(doc_id)
        self.refresh_indexes()
        return msg

    def documents(self) -> list[dict]:
        return self.registry.documents()

    # Q&A --------------------------------------------------------------------------------
    def retrieve(self, question: str, doc_ids: list[str] | None = None) -> RetrievalResult:
        return self.retriever.retrieve(question, doc_ids)

    def ask(self, question: str, doc_ids: list[str] | None = None) -> AnswerResult:
        t0 = time.monotonic()
        try:
            retrieval = self.retrieve(question, doc_ids)
        except Exception as e:
            if self.s.on("fallbacks"):
                raise
            # Stage 1-2 have no fallbacks: report the failure instead of crashing the UI.
            retrieval = RetrievalResult(question, [], [], "none", False, f"Retrieval failed: {e}")
            return AnswerResult(question, "error", f"Retrieval failed: {type(e).__name__}: {e}", [], retrieval,
                                latency_ms=(time.monotonic() - t0) * 1000)
        result = self.answerer.answer(retrieval)
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    def system_status(self, max_age_s: float = STATUS_TTL_S) -> dict:
        """Cached for a few seconds: the UI calls this on every rerun."""
        now = time.monotonic()
        if self._status_cache and now - self._status_cache[0] < max_age_s:
            return {**self._status_cache[1], "faults": faults.flags.active()}
        ocr_ok, ocr_msg = ocr_status() if self.s.on("ocr") else (False, "OCR is a Stage 2 feature")
        status = {"stage": self.s.stage, "features": sorted(self.s.features), "llm": self.llm.description,
                  "llm_enabled": self.llm.enabled, "llm_status": self.llm.status,
                  "vision": self.s.on("vision") and self.llm.supports_images(), "ocr": ocr_ok, "ocr_message": ocr_msg,
                  "embedder": self.embedder.name, "embedder_loaded": self.embedder.loaded, **self.index_health()}
        self._status_cache = (now, status)
        return {**status, "faults": faults.flags.active()}
