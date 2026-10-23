"""Admin ingestion pipeline.

upload -> validate -> store original -> extract (OCR scanned pages) -> chunk ->
attach metadata -> embed into ChromaDB + local text cache -> mark indexed ->
bump the knowledge-base generation.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import faults
from .chunking import chunk_pages
from .config import get_settings
from .extraction import ExtractionError, extract, validate_upload
from .retrieval import index_text
from .runtime import get_store, get_vectors
from .store import ChunkRow, DocumentRow, VersionRow

log = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest")


class UploadRejected(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class UploadMetadata:
    title: str
    category: str
    semester: str | None = None
    academic_year: str | None = None
    effective_date: str | None = None


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def upload_document(
    filename: str, data: bytes, meta: UploadMetadata, replaces_id: str | None = None, run_async: bool = True
) -> tuple[str, int]:
    """Validate and register an upload, then process it. Returns (doc_id, version)."""
    store = get_store()
    title = (meta.title or "").strip()
    if not title:
        raise UploadRejected("Enter a title.")
    if not (meta.category or "").strip():
        raise UploadRejected("Choose a category.")
    try:
        kind = validate_upload(filename, data)
    except ExtractionError as exc:
        raise UploadRejected(str(exc)) from None

    sha = hashlib.sha256(data).hexdigest()
    duplicate = store.find_version_by_hash(sha)
    if duplicate is not None:
        dup_doc = store.get_document(duplicate.doc_id)
        name = dup_doc.title if dup_doc else duplicate.file_name
        raise UploadRejected(f'This exact file is already uploaded as "{name}" (v{duplicate.version}).', 409)

    existing = store.get_document(replaces_id) if replaces_id else None
    if replaces_id and existing is None:
        raise UploadRejected("The document to replace was not found.", 404)

    fields = dict(
        title=title, category=meta.category.strip(), semester=_clean(meta.semester),
        academic_year=_clean(meta.academic_year), effective_date=_clean(meta.effective_date),
    )
    if existing:
        doc_id = existing.id
        version = (store.versions(doc_id)[-1].version if store.versions(doc_id) else 0) + 1
        store.update_document_metadata(doc_id, **fields)
    else:
        doc_id = uuid.uuid4().hex[:16]
        version = 1
        store.create_document(DocumentRow(id=doc_id, active=True, created_at=time.time(), **fields))

    safe_name = filename.replace("\\", "/").split("/")[-1][:200]
    stored = get_settings().uploads_dir / f"{doc_id}_v{version}{_suffix(safe_name)}"
    stored.write_bytes(data)
    store.add_version(VersionRow(
        doc_id=doc_id, version=version, file_name=safe_name, file_kind=kind, size_bytes=len(data), sha256=sha,
        stored_path=str(stored), uploaded_at=time.time(), stage="uploaded", failed_at=None, error=None,
        ocr_required=False, chunk_count=0, indexed_at=None,
    ))
    log.info("Registered upload doc=%s v%d kind=%s size=%d", doc_id, version, kind, len(data))

    if run_async:
        _pool.submit(process_version, doc_id, version)
    else:
        process_version(doc_id, version)
    return doc_id, version


def _suffix(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot != -1 else ""


def process_version(doc_id: str, version: int) -> bool:
    """Run the pipeline for one version. Failures are recorded with a user-facing
    reason; details go to the protected log only."""
    store = get_store()
    settings = get_settings()
    row = store.get_version(doc_id, version)
    doc = store.get_document(doc_id)
    if row is None or doc is None:
        return False

    stage = "extracting"
    try:
        store.update_version(doc_id, version, stage=stage, failed_at=None, error=None)

        def on_ocr() -> None:
            nonlocal stage
            stage = "ocr"
            store.update_version(doc_id, version, stage="ocr", ocr_required=True)

        extraction = extract(Path(row.stored_path), row.file_kind, on_ocr=on_ocr)
        chunks = chunk_pages(extraction.pages, settings.chunk_tokens, settings.chunk_overlap_tokens)
        if not chunks:
            raise ExtractionError("No readable text was found in this file.")

        stage = "embedding"
        store.update_version(doc_id, version, stage=stage, ocr_required=extraction.ocr_required)
        key = f"{doc_id}:v{version}"
        rows = [
            ChunkRow(f"{doc_id}-v{version}-{c.ordinal:04d}", doc_id, version, c.page, c.ordinal, c.text)
            for c in chunks
        ]
        vectors = get_vectors()
        vectors.delete_version(key)
        vectors.add(
            ids=[r.chunk_id for r in rows],
            texts=[index_text(doc, r.text) for r in rows],
            metadatas=[{"doc_id": doc_id, "version": version, "version_key": key, "page": r.page} for r in rows],
        )
        store.replace_chunks(doc_id, version, rows)
        warning = "; ".join(extraction.warnings) or None
        store.update_version(doc_id, version, stage="indexed", chunk_count=len(rows), indexed_at=time.time(),
                             error=warning)
        generation = store.bump_generation()
        log.info("Indexed doc=%s v%d chunks=%d generation=%d", doc_id, version, len(rows), generation)
        return True
    except ExtractionError as exc:
        _fail(doc_id, version, stage, str(exc))
    except faults.InjectedFault:
        _fail(doc_id, version, stage, _stage_error(stage))
    except Exception:  # noqa: BLE001
        log.exception("Processing failed doc=%s v%d stage=%s", doc_id, version, stage)
        _fail(doc_id, version, stage, _stage_error(stage))
    return False


def _stage_error(stage: str) -> str:
    return {
        "extracting": "Text could not be extracted from this file. Check the file and reprocess.",
        "ocr": "OCR could not read the scanned pages. Upload a clearer scan or reprocess.",
        "embedding": "The embedding service did not respond. Try reprocessing.",
    }.get(stage, "Processing failed. Try reprocessing.")


def _fail(doc_id: str, version: int, stage: str, message: str) -> None:
    get_store().update_version(doc_id, version, stage="failed", failed_at=stage, error=message)
    log.warning("Processing failed doc=%s v%d at %s: %s", doc_id, version, stage, message)


def reprocess(doc_id: str, run_async: bool = True) -> None:
    store = get_store()
    versions = store.versions(doc_id)
    if not versions:
        raise UploadRejected("Document not found.", 404)
    current = versions[-1]
    if current.stage not in ("indexed", "failed"):
        raise UploadRejected("This document is still being processed.", 409)
    store.update_version(doc_id, current.version, stage="uploaded", failed_at=None, error=None)
    if run_async:
        _pool.submit(process_version, doc_id, current.version)
    else:
        process_version(doc_id, current.version)


def set_active(doc_id: str, active: bool) -> None:
    store = get_store()
    if store.get_document(doc_id) is None:
        raise UploadRejected("Document not found.", 404)
    store.update_document_metadata(doc_id, active=active)
    store.bump_generation()
