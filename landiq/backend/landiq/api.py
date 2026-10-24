"""LANDIQ HTTP API (/api/v1).

Run from landiq/backend:  python -m uvicorn landiq.api:app --port 8000

Uploads are validated and stored; analysis jobs return 202 immediately and run
in the persisted job runner. Processing failures appear in job status, never as
a misleading 2xx "success".
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import chat, demo, faults, orchestrator, rag
from .config import LANDIQ_DIR, configure_logging, get_settings
from .map_agent import IMAGE_EXT, PDF_EXT, SUPPORTED_EXT, VECTOR_EXT
from .prediction import predict, readiness, risk_band
from .retrieval import get_vectors
from .runtime import get_repo
from .schemas import (
    AskIn, Case, ChatIn, ChatOut, ClarifyIn, Conflict, Fact, Job, JobIn, JobResults, JobState, Project, ProjectIn, RagAnswer, UploadOut,
)

log = logging.getLogger(__name__)
runner: orchestrator.JobRunner | None = None

ERRORS = {
    400: {"description": "Invalid request"}, 404: {"description": "Not found"}, 409: {"description": "Conflict"},
    413: {"description": "File too large"}, 415: {"description": "Unsupported file type"},
    422: {"description": "Validation error"}, 500: {"description": "Internal error (details in the server log)"},
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global runner
    settings = get_settings()
    configure_logging(settings)
    faults.configure(settings.faults)
    seeded = demo.seed_demo()
    if seeded:
        log.info("Seeded synthetic demo corridor with %d cases", seeded)
    rescored = get_repo().rescore_cases(predict)
    if rescored:
        log.info("Re-scored %d stored case(s) with the current risk scorer", rescored)
    runner = orchestrator.JobRunner(settings.job_workers)
    resumed = runner.resume_pending()
    if resumed:
        log.warning("Resumed %d interrupted job(s) from checkpoints", resumed)
    yield
    runner.shutdown()


app = FastAPI(title="LANDIQ API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    ref = uuid.uuid4().hex[:10]
    log.exception("Unhandled error ref=%s path=%s", ref, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Internal error. Reference {ref}."})


def _project(project_id: str) -> Project:
    project = get_repo().get_project(project_id)
    if project is None:
        raise HTTPException(404, "Project not found.")
    return project


# ---------------------------------------------------------------------------
# Health and projects
# ---------------------------------------------------------------------------


@app.get("/api/v1/health")
def health() -> dict:
    status, reason = readiness()
    vector = get_vectors().ping() if get_settings().vector_enabled else False
    return {"status": "ok", "vector_store": vector, "lexical_fallback": get_settings().lexical_fallback_enabled,
            "prediction": {"status": status.value, "reason": reason}, "faults": sorted(faults._active)}


class FaultsIn(BaseModel):
    faults: list[str]


@app.get("/api/v1/faults")
def get_faults() -> dict:
    return {"active": sorted(faults._active), "known": sorted(faults.KNOWN),
            "allowed": get_settings().allow_fault_injection}


@app.put("/api/v1/faults", responses=ERRORS)
def set_faults(body: FaultsIn) -> dict:
    """Simulate failures for the next jobs (demo/testing). Applies process-wide until changed."""
    if not get_settings().allow_fault_injection:
        raise HTTPException(403, "Fault injection is disabled (ALLOW_FAULT_INJECTION=false).")
    unknown = sorted(set(body.faults) - faults.KNOWN)
    if unknown:
        raise HTTPException(400, f"Unknown fault(s): {', '.join(unknown)}.")
    faults.configure(",".join(body.faults))
    log.warning("Fault injection set to: %s", ",".join(sorted(faults._active)) or "none")
    return get_faults()


@app.get("/api/v1/projects", response_model=list[Project])
def list_projects() -> list[Project]:
    return get_repo().list_projects()


@app.post("/api/v1/projects", response_model=Project, status_code=201, responses=ERRORS)
def create_project(body: ProjectIn) -> Project:
    project = Project(project_id="prj_" + uuid.uuid4().hex[:10], name=body.name, corridor_id=body.corridor_id,
                      description=body.description)
    get_repo().put_project(project)
    return project


@app.get("/api/v1/projects/{project_id}", response_model=Project, responses=ERRORS)
def get_project(project_id: str) -> Project:
    return _project(project_id)


@app.get("/api/v1/projects/{project_id}/summary", responses=ERRORS)
def project_summary(project_id: str) -> dict:
    project = _project(project_id)
    cases = get_repo().list_cases(project_id)
    if project.is_demo:
        return {"project_id": project_id, "is_demo": True, **demo.summary(cases)}
    quality = {"GOOD": 0, "PARTIAL": 0, "POOR": 0}
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNRATED": 0}
    for c in cases:
        quality[c.data_quality] += 1
        counts[risk_band(c.prediction.delay_probability)] += 1
    return {"project_id": project_id, "is_demo": False, "total": len(cases), "counts": counts, "data_quality": quality,
            "conflicts": len(get_repo().list_conflicts(project_id)),
            "unresolved_matches": len(get_repo().list_matches(project_id)),
            "prediction": readiness()[0].value}


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


async def _store_upload(project_id: str, kind: Literal["document", "map"], file: UploadFile) -> UploadOut | JSONResponse:
    project = _project(project_id)
    if project.is_demo:
        raise HTTPException(400, "The demo corridor is read-only. Create a project to upload files.")
    settings = get_settings()
    name = Path(file.filename or "upload").name[:200]
    ext = Path(name).suffix.lower()
    limit_mb = settings.max_pdf_mb if kind == "document" else settings.max_map_mb
    data = await file.read(limit_mb * 1024 * 1024 + 1)
    if len(data) > limit_mb * 1024 * 1024:
        raise HTTPException(413, f"The file is larger than {limit_mb} MB.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    if kind == "document":
        if ext != ".pdf" or not data.startswith(b"%PDF"):
            raise HTTPException(415, "This is not a PDF file (its content does not start with a PDF header). "
                                     "Only PDF documents are accepted.")
    else:
        if ext not in SUPPORTED_EXT:
            raise HTTPException(415, "Supported map formats: GeoJSON, zipped Shapefile, GeoPackage, KML, PNG/JPG, PDF.")
        if ext == ".zip" and not data.startswith(b"PK"):
            raise HTTPException(415, "The .zip file is not a valid archive.")
        if ext in PDF_EXT and not data.startswith(b"%PDF"):
            raise HTTPException(415, "The map PDF is not a valid PDF.")
    sha = hashlib.sha256(data).hexdigest()
    repo = get_repo()
    existing = repo.find_input_by_hash(project_id, kind, sha)
    if existing:  # idempotent upload
        return UploadOut(project_id=project_id, kind=kind, id=existing.input_id, filename=existing.filename,
                         size_bytes=existing.size_bytes, sha256=sha, status="DUPLICATE",
                         detail="This exact file was already uploaded.")
    input_id = ("doc_" if kind == "document" else "map_") + uuid.uuid4().hex[:12]
    path = settings.uploads_dir / f"{input_id}{ext}"
    path.write_bytes(data)
    repo.add_input(input_id, project_id, kind, name, sha, len(data), path, "STORED")
    detail = None
    if kind == "map" and ext in IMAGE_EXT | PDF_EXT:
        detail = "Unreferenced map: kept as a visual reference only, no precise GIS analysis."
    return UploadOut(project_id=project_id, kind=kind, id=input_id, filename=name, size_bytes=len(data), sha256=sha,
                     status="STORED", detail=detail)


@app.post("/api/v1/projects/{project_id}/documents", response_model=UploadOut, status_code=201, responses=ERRORS)
async def upload_document(project_id: str, file: UploadFile = File(...)):
    return await _store_upload(project_id, "document", file)


@app.post("/api/v1/projects/{project_id}/maps", response_model=UploadOut, status_code=201, responses=ERRORS)
async def upload_map(project_id: str, file: UploadFile = File(...)):
    return await _store_upload(project_id, "map", file)


@app.get("/api/v1/projects/{project_id}/inputs", responses=ERRORS)
def list_inputs(project_id: str) -> list[dict]:
    _project(project_id)
    return [{"id": i.input_id, "kind": i.kind, "filename": i.filename, "size_bytes": i.size_bytes, "status": i.status,
             "detail": i.detail, "created_at": i.created_at} for i in get_repo().list_inputs(project_id)]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@app.post("/api/v1/projects/{project_id}/analysis-jobs", response_model=Job, status_code=202, responses=ERRORS)
def start_job(project_id: str, body: JobIn | None = None, idempotency_key: str | None = Header(default=None)) -> Job:
    project = _project(project_id)
    if project.is_demo:
        raise HTTPException(400, "The demo corridor has no uploaded inputs to analyse.")
    try:
        job, created = orchestrator.create_job(project_id, body or JobIn(), idempotency_key)
    except KeyError as exc:
        raise HTTPException(404, f"Input {exc.args[0]} not found in this project.") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if created and runner is not None:
        runner.submit(job.job_id)
    return job


@app.get("/api/v1/projects/{project_id}/jobs", response_model=list[Job], responses=ERRORS)
def list_jobs(project_id: str) -> list[Job]:
    _project(project_id)
    return get_repo().list_jobs(project_id)


def _job(job_id: str) -> Job:
    job = get_repo().get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@app.get("/api/v1/jobs/{job_id}", response_model=Job, responses=ERRORS)
def get_job(job_id: str) -> Job:
    return _job(job_id)


@app.get("/api/v1/jobs/{job_id}/results", response_model=JobResults, responses=ERRORS)
def get_results(job_id: str) -> JobResults:
    return orchestrator.job_results(_job(job_id))


@app.post("/api/v1/jobs/{job_id}/cancel", response_model=Job, responses=ERRORS)
def cancel_job(job_id: str) -> Job:
    job = _job(job_id)
    if job.state in orchestrator.TERMINAL:
        raise HTTPException(409, f"The job is already {job.state.value}.")
    if runner is not None:
        runner.cancel(job_id)
    return job


# ---------------------------------------------------------------------------
# Cases, evidence, map features, clarifications, actions
# ---------------------------------------------------------------------------


class CaseDetail(BaseModel):
    case: Case
    facts: dict[str, Fact]
    conflicts: list[Conflict]


@app.get("/api/v1/projects/{project_id}/cases", response_model=list[Case], responses=ERRORS)
def list_cases(project_id: str) -> list[Case]:
    _project(project_id)
    cases = get_repo().list_cases(project_id)
    return sorted(cases, key=lambda c: (-(c.illustrative or {}).get("delayProbability", 0),
                                        -(c.prediction.delay_probability or 0), c.case_ref))


@app.get("/api/v1/cases/{case_id}", response_model=CaseDetail, responses=ERRORS)
def get_case(case_id: str) -> CaseDetail:
    repo = get_repo()
    case = repo.get_case(case_id)
    if case is None:
        raise HTTPException(404, "Case not found.")
    ids = {fid for fv in case.fields.values() for fid in fv.facts}
    facts = {f.fact_id: f for f in repo.list_facts(case.project_id) if f.fact_id in ids}
    conflicts = [c for c in repo.list_conflicts(case.project_id) if c.case_id == case_id]
    return CaseDetail(case=case, facts=facts, conflicts=conflicts)


@app.post("/api/v1/cases/{case_id}/ask", response_model=RagAnswer, responses=ERRORS)
async def ask_case(case_id: str, body: AskIn) -> RagAnswer:
    case = get_repo().get_case(case_id)
    if case is None:
        raise HTTPException(404, "Case not found.")
    if case.is_synthetic:
        raise HTTPException(400, "Synthetic demo cases have no source documents to question.")
    return await run_in_threadpool(rag.answer, case.project_id, body.question, case.case_ref)


@app.post("/api/v1/projects/{project_id}/ask", response_model=RagAnswer, responses=ERRORS)
async def ask_project(project_id: str, body: AskIn) -> RagAnswer:
    _project(project_id)
    return await run_in_threadpool(rag.answer, project_id, body.question, None)


@app.post("/api/v1/projects/{project_id}/chat", response_model=ChatOut, responses=ERRORS)
async def chat_project(project_id: str, body: ChatIn) -> ChatOut:
    """Q&A over the project's indexed documents. LLM failures degrade to EVIDENCE_ONLY, never a 500."""
    _project(project_id)
    case_ref = None
    if body.case_id:
        case = get_repo().get_case(body.case_id)
        if case is None or case.project_id != project_id:
            raise HTTPException(404, "Case not found in this project.")
        case_ref = case.case_ref
    return await run_in_threadpool(chat.chat, project_id, body, case_ref)


@app.get("/api/v1/projects/{project_id}/map-features", responses=ERRORS)
def map_features(project_id: str) -> dict:
    project = _project(project_id)
    feats = get_repo().list_features(project_id)
    # Link features to cases only through fusion's verified geometry references.
    case_by_feature = {ref["feature_id"]: c for c in get_repo().list_cases(project_id) for ref in c.geometry_refs}
    out = []
    for f in feats:
        if not f.valid:
            continue
        case = case_by_feature.get(f.feature_id)
        out.append({"type": "Feature", "id": f.feature_id, "geometry": f.geometry, "properties": {
            "feature_id": f.feature_id, "map_id": f.map_id, "layer": f.layer, "role": f.role,
            "parcel_id": f.parcel_id, "case_ref": case.case_ref if case else None,
            "case_id": case.case_id if case else None,
            "survey_numbers": f.survey_numbers, "zone": f.zone, "area_hectares": f.area_hectares,
            "distance_to_alignment_m": f.distance_to_alignment_m, "intersects_alignment": f.intersects_alignment,
            "synthetic": bool(f.attributes.get("synthetic")),
            "risk_category": (case.illustrative or {}).get("riskCategory") if case and case.is_synthetic else None,
        }})
    return {"type": "FeatureCollection", "features": out, "synthetic": project.is_demo}


@app.post("/api/v1/projects/{project_id}/clarifications", response_model=list, responses=ERRORS)
def clarify(project_id: str, body: ClarifyIn) -> list:
    _project(project_id)
    repo = get_repo()
    match = next((m for m in repo.list_matches(project_id) if m.match_id == body.match_id), None)
    if match is None:
        raise HTTPException(404, "That clarification is no longer open.")
    if body.case_id is not None and body.case_id not in match.candidates:
        raise HTTPException(400, "Choose one of the candidate cases, or none.")
    repo.put_resolution(project_id, body.match_id, body.case_id)
    remaining = orchestrator.refuse_project(project_id)
    return [m.model_dump() for m in remaining]


class WorkflowIn(BaseModel):
    status: Literal["PROPOSED", "IN_REVIEW", "ESCALATED", "RESOLVED", "DISMISSED"]


@app.post("/api/v1/actions/{action_id}/workflow", responses=ERRORS)
def set_workflow(action_id: str, body: WorkflowIn) -> dict:
    get_repo().set_action_status(action_id, body.status)
    return {"action_id": action_id, "workflow_status": body.status,
            "note": "Recorded in LANDIQ only. No message or order is sent to any authority."}


# ---------------------------------------------------------------------------
# Built frontend
# ---------------------------------------------------------------------------

_DIST = LANDIQ_DIR / "frontend" / "dist"
if (_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        candidate = (_DIST / path).resolve()
        if path and candidate.is_file() and _DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
