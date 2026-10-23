"""FastAPI app: chat, chat-with-image, admin document management and health.

Run with:  uvicorn college_rag.api:app --port 8000   (from the backend folder)
"""

from __future__ import annotations

import hmac
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import faults, ingestion
from .agents import ImageInput
from .config import REPO_DIR, configure_logging, get_settings
from .ingestion import UploadMetadata, UploadRejected
from .llm import get_llm
from .ocr import ImageRejected, validate_image
from .orchestrator import MAX_MESSAGE_CHARS, handle_chat
from .runtime import get_store, get_vectors
from .schemas import ChatResponse, DocumentOut, DocumentVersionOut, HealthOut

log = logging.getLogger(__name__)

settings = get_settings()
configure_logging(settings)
faults.configure(settings.faults)

app = FastAPI(title="College Assistant API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    interrupted = get_store().mark_interrupted()
    if interrupted:
        log.warning("Marked %d interrupted processing job(s) as failed", interrupted)
    if settings.admin_password == "admin123":
        log.warning("Using the default admin password. Set ADMIN_USERNAME / ADMIN_PASSWORD in .env before sharing.")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    ref = uuid.uuid4().hex[:12]
    log.exception("Unhandled error ref=%s path=%s", ref, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Something went wrong. Reference: {ref}"})


# ---------------------------------------------------------------------------
# Admin auth (simple bearer tokens kept in memory)
# ---------------------------------------------------------------------------

_tokens: dict[str, tuple[str, float]] = {}
_tokens_lock = threading.Lock()


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    username: str
    role: str = "admin"


@app.post("/api/admin/login", response_model=LoginOut)
def admin_login(body: LoginIn) -> LoginOut:
    ok_user = hmac.compare_digest(body.username.strip().encode(), settings.admin_username.encode())
    ok_pass = hmac.compare_digest(body.password.encode(), settings.admin_password.encode())
    if not (ok_user and ok_pass):
        time.sleep(0.5)
        raise HTTPException(401, "Incorrect username or password.")
    token = secrets.token_urlsafe(32)
    with _tokens_lock:
        _tokens[token] = (settings.admin_username, time.time() + settings.admin_token_ttl_s)
    return LoginOut(token=token, username=settings.admin_username)


def require_admin(authorization: str = Header(default="")) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    with _tokens_lock:
        entry = _tokens.get(token)
        if entry and entry[1] < time.time():
            del _tokens[token]
            entry = None
    if not entry:
        raise HTTPException(401, "Your admin session has expired. Sign in again.")
    return entry[0]


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@app.post("/api/chat", response_model=ChatResponse, response_model_by_alias=True)
async def chat(message: str = Form(default=""), image: UploadFile | None = File(default=None)) -> ChatResponse:
    if len(message) > MAX_MESSAGE_CHARS:
        raise HTTPException(400, f"Messages can be at most {MAX_MESSAGE_CHARS} characters.")
    image_input = None
    if image is not None and image.filename:
        data = await image.read(settings.max_image_mb * 1024 * 1024 + 1)
        try:
            validate_image(data)
        except ImageRejected as exc:
            raise HTTPException(400, str(exc)) from None
        image_input = ImageInput(data=data, filename=image.filename)
    if not message.strip() and image_input is None:
        raise HTTPException(400, "Type a question or attach a screenshot.")
    # Agents block on I/O; run them in the threadpool.
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(handle_chat, message, image_input)


# ---------------------------------------------------------------------------
# Documents (admin)
# ---------------------------------------------------------------------------


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _document_out(doc_id: str) -> DocumentOut:
    store = get_store()
    doc = store.get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    versions = [
        DocumentVersionOut(
            version=v.version, file_name=v.file_name, file_kind=v.file_kind, size_bytes=v.size_bytes,
            uploaded_at=_iso(v.uploaded_at), stage=v.stage, failed_at=v.failed_at, error=v.error,
            ocr_required=v.ocr_required, chunk_count=v.chunk_count,
        )
        for v in store.versions(doc_id)
    ]
    return DocumentOut(
        id=doc.id, title=doc.title, category=doc.category, semester=doc.semester, academic_year=doc.academic_year,
        effective_date=doc.effective_date, active=doc.active, versions=versions,
    )


@app.get("/api/documents", response_model=list[DocumentOut], response_model_by_alias=True)
def list_documents(_: str = Depends(require_admin)) -> list[DocumentOut]:
    return [_document_out(d.id) for d in get_store().list_documents() if get_store().versions(d.id)]


@app.post("/api/documents", response_model=DocumentOut, response_model_by_alias=True, status_code=202)
async def upload(
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form(...),
    semester: str = Form(default=""),
    academicYear: str = Form(default=""),  # noqa: N803 - matches the frontend field names
    effectiveDate: str = Form(default=""),  # noqa: N803
    replacesId: str = Form(default=""),  # noqa: N803
    _: str = Depends(require_admin),
) -> DocumentOut:
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    meta = UploadMetadata(title=title, category=category, semester=semester, academic_year=academicYear,
                          effective_date=effectiveDate)
    try:
        doc_id, _version = ingestion.upload_document(file.filename or "upload", data, meta, replacesId or None)
    except UploadRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return _document_out(doc_id)


@app.post("/api/documents/{doc_id}/reprocess", response_model=DocumentOut, response_model_by_alias=True)
def reprocess(doc_id: str, _: str = Depends(require_admin)) -> DocumentOut:
    try:
        ingestion.reprocess(doc_id)
    except UploadRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return _document_out(doc_id)


class ActiveIn(BaseModel):
    active: bool


@app.post("/api/documents/{doc_id}/active", response_model=DocumentOut, response_model_by_alias=True)
def set_active(doc_id: str, body: ActiveIn, _: str = Depends(require_admin)) -> DocumentOut:
    try:
        ingestion.set_active(doc_id, body.active)
    except UploadRejected as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return _document_out(doc_id)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthOut, response_model_by_alias=True)
def health() -> HealthOut:
    store = get_store()
    llm = get_llm().health()
    vectors_ok = get_vectors().ping()
    ok = vectors_ok and any(llm.values())
    return HealthOut(
        status="ok" if ok else "degraded", llm=llm, vector_store=vectors_ok,
        documents_indexed=len(store.searchable_versions()), kb_generation=store.kb_generation(),
    )


# ---------------------------------------------------------------------------
# Built frontend (optional): `npm run build` in frontend/, then one server serves both.
# ---------------------------------------------------------------------------

_DIST = REPO_DIR / "frontend" / "dist"
if (_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        candidate = (_DIST / path).resolve()
        if path and candidate.is_file() and Path(_DIST.resolve()) in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
