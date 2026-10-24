"""Agentic orchestrator with persisted, bounded job execution.

Each job runs a decide -> act -> record loop. `next_action()` inspects the
persisted job state and returns one action from a fixed whitelist; nothing
outside the whitelist can run, and no model output chooses actions. Every action
is audited, every validated stage is checkpointed, and the loop stops at the
step/time budget.

Actions:
  RUN_AGENTS             PDF and map agents concurrently, each input independently
  REEXTRACT_PAGES        targeted re-read of pages that had text but yielded no facts
  CHECK_RETRIEVAL        probe the indexes for the extracted case refs
  FUSE                   evidence fusion -> cases, conflicts, unresolved matches
  INVESTIGATE_CONFLICT   retrieve more evidence for one open conflict (never resolves it)
  CHECK_PREDICTION       prediction-readiness gate
  FINALIZE               terminal state (SUCCEEDED / PARTIAL / NEEDS_CLARIFICATION / FAILED)

Durability: state lives in SQLite, not in memory. A crashed or restarted
process re-queues RUNNING jobs; inputs with a checkpoint are not re-processed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable

from pydantic import ValidationError

from . import faults
from .config import get_settings
from .fusion import fuse
from .map_agent import process_map
from .pdf_agent import ChunkOut, PermanentAgentError, extract_document
from .prediction import readiness
from .retrieval import index_chunks, retrieve
from .runtime import get_repo
from .schemas import (
    AgentState, AgentStatus, AuditEvent, ErrorInfo, Job, JobIn, JobResults, JobState, MapAgentOutput, MapResult,
    PdfAgentOutput, PdfDocumentResult, StageState, utcnow,
)

log = logging.getLogger(__name__)

TERMINAL = {JobState.SUCCEEDED, JobState.PARTIAL, JobState.NEEDS_CLARIFICATION, JobState.FAILED, JobState.CANCELLED}
FIELD_LABEL = {
    "legal_status": "legal status dispute court", "compensation_status": "compensation award disbursed",
    "clearance_status": "approval clearance", "rr_status": "rehabilitation resettlement R&R",
    "compensation_amount_cr": "compensation award amount", "compensation_disbursed_pct": "compensation disbursed",
    "rr_progress_pct": "R&R progress", "project_progress_pct": "project progress", "area_hectares": "area hectares",
    "village": "village", "district": "district",
}


class TransientError(Exception):
    pass


class OutputRejected(Exception):
    """Agent output failed schema/provenance validation; it never reaches fusion."""


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------


def create_job(project_id: str, body: JobIn, idempotency_key: str | None) -> tuple[Job, bool]:
    """Returns (job, created). The same inputs (or key) return the existing job."""
    repo = get_repo()
    docs = [i.input_id for i in repo.list_inputs(project_id, "document") if i.status == "STORED"]
    maps = [i.input_id for i in repo.list_inputs(project_id, "map") if i.status == "STORED"]
    doc_ids = sorted(body.document_ids) if body.document_ids is not None else docs
    map_ids = sorted(body.map_ids) if body.map_ids is not None else maps
    for input_id in doc_ids + map_ids:
        row = repo.get_input(input_id)
        if row is None or row.project_id != project_id:
            raise KeyError(input_id)
    if not doc_ids and not map_ids:
        raise ValueError("Upload at least one document or map before starting an analysis job.")
    hashes = sorted(repo.get_input(i).sha256 for i in doc_ids + map_ids)
    key = idempotency_key or hashlib.sha256(f"{project_id}|{'|'.join(hashes)}".encode()).hexdigest()
    settings = get_settings()
    job = Job(job_id="job_" + uuid.uuid4().hex[:12], project_id=project_id, idempotency_key=key,
              document_ids=doc_ids, map_ids=map_ids, step_budget=settings.job_max_steps)
    job.pdf_agent = AgentStatus(inputs=doc_ids, max_attempts=settings.agent_max_attempts,
                                state=AgentState.PENDING if doc_ids else AgentState.SKIPPED)
    job.map_agent = AgentStatus(inputs=map_ids, max_attempts=settings.agent_max_attempts,
                                state=AgentState.PENDING if map_ids else AgentState.SKIPPED)
    stored = repo.create_job(job)
    return stored, stored.job_id == job.job_id


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class JobRunner:
    def __init__(self, workers: int):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._active: set[str] = set()
        self._cancel: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._active:
                return
            self._active.add(job_id)
        self._pool.submit(self._run, job_id)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancel.add(job_id)

    def _run(self, job_id: str) -> None:
        try:
            run_job(job_id, cancelled=lambda: job_id in self._cancel)
        except Exception:  # noqa: BLE001
            log.exception("Job %s crashed", job_id)
            _safe_fail(job_id)
        finally:
            with self._lock:
                self._active.discard(job_id)
                self._cancel.discard(job_id)

    def resume_pending(self) -> int:
        """After a restart: re-queue QUEUED/RUNNING jobs. Checkpointed inputs are reused."""
        jobs = get_repo().list_jobs(states=[JobState.QUEUED, JobState.RUNNING])
        for job in jobs:
            self.submit(job.job_id)
        return len(jobs)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _safe_fail(job_id: str) -> None:
    repo = get_repo()
    job = repo.get_job(job_id)
    if job and job.state not in TERMINAL:
        job.state = JobState.FAILED
        job.errors.append(ErrorInfo(code="ORCHESTRATOR_ERROR", message="The analysis stopped because of an internal error.",
                                    remediation="Retry the job. If it fails again, check the server log."))
        job.remediation = "Retry the job. Valid results saved before the error are kept."
        repo.save_job(job)


# ---------------------------------------------------------------------------
# Decide -> act -> record
# ---------------------------------------------------------------------------


class Ctx:
    def __init__(self, job: Job):
        self.job = job
        self.repo = get_repo()
        self.settings = get_settings()
        self.started = time.monotonic()
        self.pdf_results: dict[str, PdfDocumentResult] = {}
        self.map_results: dict[str, MapResult] = {}
        self.reextracted: set[tuple[str, int]] = set()
        self.investigated: set[str] = set()
        self.done: set[str] = set()
        self._save_lock = threading.Lock()

    def save(self) -> None:
        with self._save_lock:
            self.repo.save_job(self.job)

    def audit(self, action: str, outcome: str, detail: str | None = None) -> None:
        self.job.audit.append(AuditEvent(step=self.job.steps_used, action=action, outcome=outcome, detail=detail))
        self.job.audit = self.job.audit[-200:]
        self.save()


def next_action(ctx: Ctx) -> tuple[str, str | None]:
    """Choose the next permitted action from persisted state."""
    job = ctx.job
    if "RUN_AGENTS" not in ctx.done:
        return "RUN_AGENTS", None
    if "REEXTRACT_PAGES" not in ctx.done and _pages_to_reextract(ctx):
        return "REEXTRACT_PAGES", None
    if "CHECK_RETRIEVAL" not in ctx.done and ctx.pdf_results:
        return "CHECK_RETRIEVAL", None
    if "FUSE" not in ctx.done:
        return "FUSE", None
    if job.fusion.state in (StageState.SUCCEEDED, StageState.DEGRADED):
        for conflict in ctx.repo.list_conflicts(job.project_id):
            if (conflict.status == "OPEN" and conflict.conflict_id not in ctx.investigated
                    and len(ctx.investigated) < ctx.settings.max_conflict_investigations):
                return "INVESTIGATE_CONFLICT", conflict.conflict_id
    if "CHECK_PREDICTION" not in ctx.done:
        return "CHECK_PREDICTION", None
    return "FINALIZE", None


def run_job(job_id: str, cancelled: Callable[[], bool] = lambda: False) -> Job:
    repo = get_repo()
    job = repo.get_job(job_id)
    if job is None or job.state in TERMINAL:
        return job
    if job.state == JobState.RUNNING:
        job.resumed_count += 1
        job.warnings.append("The job was resumed after an interruption; saved checkpoints were reused.")
    job.state = JobState.RUNNING
    ctx = Ctx(job)
    ctx.audit("START", "ok", f"resume #{job.resumed_count}" if job.resumed_count else None)

    while True:
        if cancelled():
            job.state = JobState.CANCELLED
            job.remediation = "The job was cancelled. Start a new job to analyse these inputs."
            ctx.audit("CANCEL", "stopped")
            return job
        if job.steps_used >= job.step_budget or time.monotonic() - ctx.started > ctx.settings.job_max_seconds:
            ctx.audit("STOP_BUDGET", "stopped", "step or time budget exhausted")
            job.warnings.append("The analysis stopped at its step/time budget; results so far are kept.")
            _finalize(ctx, budget_hit=True)
            return job
        action, arg = next_action(ctx)
        job.steps_used += 1
        if action == "FINALIZE":
            _finalize(ctx)
            return job
        try:
            outcome = ACTIONS[action](ctx, arg)
        except Exception as exc:  # noqa: BLE001 - every action failure is recorded, never hidden
            log.exception("Action %s failed in job %s", action, job.job_id)
            outcome = f"error: {type(exc).__name__}"
            job.errors.append(ErrorInfo(code=f"{action}_FAILED", stage=action.lower(),
                                        message=f"The {action.replace('_', ' ').lower()} step failed."))
            if action == "FUSE":
                job.fusion.state = StageState.FAILED
        if action != "INVESTIGATE_CONFLICT":
            ctx.done.add(action)
        ctx.audit(action, outcome, arg)


# ---------------------------------------------------------------------------
# RUN_AGENTS
# ---------------------------------------------------------------------------


def _backoff(attempt: int) -> float:
    s = get_settings()
    return min(s.retry_max_delay_s, s.retry_base_delay_s * (2 ** (attempt - 1))) * (0.8 + 0.4 * random.random())


def _call_with_timeout(fn, timeout: float):
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=timeout)
    except FutureTimeout:
        raise TransientError("AGENT_TIMEOUT") from None
    finally:
        pool.shutdown(wait=False)


def _with_retries(ctx: Ctx, status: AgentStatus, label: str, fn):
    """Bounded retries with exponential backoff for transient errors only."""
    attempt = 0
    while True:
        attempt += 1
        status.attempts += 1
        try:
            return _call_with_timeout(fn, ctx.settings.agent_timeout_s)
        except PermanentAgentError:
            raise
        except (TransientError, faults.InjectedTransientFault, OutputRejected, TimeoutError, OSError) as exc:
            code = "AGENT_TIMEOUT" if "TIMEOUT" in str(exc) else (
                "AGENT_OUTPUT_INVALID" if isinstance(exc, OutputRejected) else "TRANSIENT_ERROR")
            if attempt >= ctx.settings.agent_max_attempts:
                raise TransientError(code) from exc
            status.state = AgentState.RETRYING
            status.warnings.append(f"{label}: attempt {attempt} failed ({code}); retrying.")
            ctx.save()
            time.sleep(_backoff(attempt))


FAILSAFE_PERMANENT = "Not retried: retrying cannot fix an invalid file. The file was quarantined; other inputs and the other agent carried on."


def _failsafe_transient(ctx: Ctx) -> str:
    return (f"Retried {ctx.settings.agent_max_attempts} times with exponential backoff, then gave up on this file. "
            "Results from other inputs were kept; re-running the job retries only this file.")


def _quarantine(ctx: Ctx, input_id: str, reason: str) -> None:
    row = ctx.repo.get_input(input_id)
    if row is None or row.status == "QUARANTINED":
        return
    target = ctx.settings.quarantine_dir / row.path.name
    try:
        shutil.move(str(row.path), target)
    except OSError:
        target = row.path
    ctx.repo.set_input_status(input_id, "QUARANTINED", reason, target)


def _pdf_one(ctx: Ctx, status: AgentStatus, document_id: str) -> PdfDocumentResult | None:
    saved = ctx.repo.get_checkpoint(ctx.job.job_id, "pdf", document_id)
    if saved:
        return PdfDocumentResult.model_validate_json(saved)
    row = ctx.repo.get_input(document_id)

    def attempt():
        result, chunks = extract_document(document_id, row.filename, row.path)
        if faults.is_active("pdf_invalid_output") and result.facts:
            result = result.model_copy(deep=True)
            result.facts[0].provenance.page = result.page_count + 5  # provenance points nowhere
        try:  # validate the agent's output before anything is stored
            PdfAgentOutput(state=result.state, documents=[PdfDocumentResult.model_validate(result.model_dump())])
        except ValidationError as exc:
            raise OutputRejected(str(exc)[:200]) from None
        return result, chunks

    try:
        result, chunks = _with_retries(ctx, status, row.filename, attempt)
    except PermanentAgentError as exc:
        status.errors.append(ErrorInfo(code=exc.code, message=str(exc), stage="pdf_agent", remediation=exc.remediation,
                                       input_id=document_id, filename=row.filename, failsafe=FAILSAFE_PERMANENT))
        _quarantine(ctx, document_id, exc.code)
        return PdfDocumentResult(document_id=document_id, filename=row.filename, state=AgentState.FAILED,
                                 error=status.errors[-1])
    except TransientError as exc:
        status.errors.append(ErrorInfo(code=str(exc), stage="pdf_agent", transient=True,
                                       message=f"{row.filename}: the PDF agent failed after {ctx.settings.agent_max_attempts} attempts.",
                                       remediation="Retry the job later.", input_id=document_id, filename=row.filename,
                                       failsafe=_failsafe_transient(ctx)))
        return PdfDocumentResult(document_id=document_id, filename=row.filename, state=AgentState.FAILED,
                                 error=status.errors[-1])

    if result.state in (AgentState.SUCCEEDED, AgentState.PARTIAL):
        _index(ctx, result, chunks)
    elif result.error:
        status.errors.append(result.error.model_copy(update={
            "input_id": document_id, "filename": row.filename,
            "failsafe": "OCR was attempted on every page; no readable text was recovered. The document was skipped "
                        "(nothing guessed from it); other inputs carried on."}))
    ctx.repo.put_checkpoint(ctx.job.job_id, "pdf", document_id, result.model_dump_json())
    return result


def _index(ctx: Ctx, result: PdfDocumentResult, chunks: list[ChunkOut]) -> None:
    state, warnings = index_chunks(ctx.job.project_id, result.document_id, [
        {"chunk_id": c.chunk_id, "page": c.page, "text": c.text, "case_ids": c.case_ids, "filename": result.filename}
        for c in chunks])
    ctx.repo.replace_facts(ctx.job.project_id, result.document_id, result.facts)
    if state == StageState.DEGRADED:
        ctx.job.retrieval.warnings.extend(w for w in warnings if w not in ctx.job.retrieval.warnings)
        ctx.job.retrieval.state = StageState.DEGRADED


def _map_one(ctx: Ctx, status: AgentStatus, map_id: str) -> MapResult | None:
    saved = ctx.repo.get_checkpoint(ctx.job.job_id, "map", map_id)
    if saved:
        return MapResult.model_validate_json(saved)
    row = ctx.repo.get_input(map_id)

    def attempt():
        result = process_map(map_id, row.filename, row.path)
        if faults.is_active("map_invalid_output") and result.features:
            result = result.model_copy(deep=True)
            result.output_crs = "EPSG:32643"  # claims features are not WGS84
        try:
            MapAgentOutput(state=result.state, maps=[MapResult.model_validate(result.model_dump())])
        except ValidationError as exc:
            raise OutputRejected(str(exc)[:200]) from None
        return result

    try:
        result = _with_retries(ctx, status, row.filename, attempt)
    except PermanentAgentError as exc:
        status.errors.append(ErrorInfo(code=exc.code, message=str(exc), stage="map_agent", remediation=exc.remediation,
                                       input_id=map_id, filename=row.filename, failsafe=FAILSAFE_PERMANENT))
        _quarantine(ctx, map_id, exc.code)
        return MapResult(map_id=map_id, filename=row.filename, state=AgentState.FAILED, input_type="vector",
                         error=status.errors[-1])
    except TransientError as exc:
        status.errors.append(ErrorInfo(code=str(exc), stage="map_agent", transient=True,
                                       message=f"{row.filename}: the map agent failed after {ctx.settings.agent_max_attempts} attempts.",
                                       remediation="Retry the job later.", input_id=map_id, filename=row.filename,
                                       failsafe=_failsafe_transient(ctx)))
        return MapResult(map_id=map_id, filename=row.filename, state=AgentState.FAILED, input_type="vector",
                         error=status.errors[-1])
    if result.state == AgentState.FAILED and result.error:
        status.errors.append(result.error.model_copy(update={
            "input_id": map_id, "filename": row.filename,
            "failsafe": ("Every feature failed geometry validation, so none were stored or fused. "
                         if result.error.code == "GEOMETRY_INVALID" else "Nothing to analyse. ")
                        + "The file was quarantined; spatial conclusions for affected cases are disabled."}))
        _quarantine(ctx, map_id, result.error.code)
    ctx.repo.replace_features(ctx.job.project_id, map_id, result.features)
    ctx.repo.replace_facts(ctx.job.project_id, map_id, result.facts)
    ctx.repo.put_checkpoint(ctx.job.job_id, "map", map_id, result.model_dump_json())
    return result


def _aggregate(states: list[AgentState]) -> AgentState:
    if not states:
        return AgentState.SKIPPED
    ok = [s for s in states if s in (AgentState.SUCCEEDED, AgentState.PARTIAL)]
    if all(s == AgentState.SUCCEEDED for s in states):
        return AgentState.SUCCEEDED
    if all(s == AgentState.NEEDS_OCR for s in states):
        return AgentState.NEEDS_OCR
    return AgentState.PARTIAL if ok else AgentState.FAILED


def _run_agent(ctx: Ctx, kind: str) -> None:
    """One agent over all its inputs. Its failure never touches the other agent."""
    status = ctx.job.pdf_agent if kind == "pdf" else ctx.job.map_agent
    if not status.inputs:
        status.state = AgentState.SKIPPED
        return
    status.state = AgentState.RUNNING
    status.started_at = status.started_at or utcnow()
    results = ctx.pdf_results if kind == "pdf" else ctx.map_results
    for input_id in status.inputs:
        try:
            res = (_pdf_one if kind == "pdf" else _map_one)(ctx, status, input_id)
        except Exception as exc:  # noqa: BLE001 - unexpected agent crash: record, keep going
            log.exception("%s agent crashed on %s", kind, input_id)
            status.errors.append(ErrorInfo(code="AGENT_CRASH", stage=f"{kind}_agent",
                                           message=f"The {kind} agent stopped unexpectedly on one input ({type(exc).__name__})."))
            res = None
        if res is not None:
            results[input_id] = res
            status.warnings.extend(w for w in res.warnings if w not in status.warnings)
        ctx.save()
    status.state = _aggregate([r.state for r in results.values()] + [AgentState.FAILED] * (len(status.inputs) - len(results)))
    status.checkpoint = bool(results)
    status.checkpoint_at = utcnow() if results else None
    status.finished_at = utcnow()


def act_run_agents(ctx: Ctx, _arg) -> str:
    # Agents run concurrently and independently; each keeps its own status.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent") as pool:
        futures = {kind: pool.submit(_run_agent, ctx, kind) for kind in ("pdf", "map")}
        for kind, fut in futures.items():
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                status = ctx.job.pdf_agent if kind == "pdf" else ctx.job.map_agent
                status.state = AgentState.FAILED
                status.errors.append(ErrorInfo(code="AGENT_CRASH", stage=f"{kind}_agent",
                                               message=f"The {kind} agent stopped unexpectedly ({type(exc).__name__})."))
    if ctx.job.retrieval.state == StageState.PENDING and ctx.pdf_results:
        ctx.job.retrieval.state = StageState.SUCCEEDED
    ctx.job.retrieval.checkpoint = any(r.chunk_count for r in ctx.pdf_results.values())
    return f"pdf={ctx.job.pdf_agent.state.value} map={ctx.job.map_agent.state.value}"


# ---------------------------------------------------------------------------
# REEXTRACT_PAGES / CHECK_RETRIEVAL
# ---------------------------------------------------------------------------


def _pages_to_reextract(ctx: Ctx) -> list[tuple[str, int]]:
    todo = []
    for doc_id, res in ctx.pdf_results.items():
        if res.state not in (AgentState.SUCCEEDED, AgentState.PARTIAL):
            continue
        for page in res.pages:
            if page.usable and page.fact_count == 0 and (doc_id, page.page) not in ctx.reextracted:
                todo.append((doc_id, page.page))
    return todo[: ctx.settings.max_page_reextractions]


def act_reextract(ctx: Ctx, _arg) -> str:
    """Pages with text but no facts are re-read once in block order; new facts are merged."""
    added = 0
    for doc_id, page in _pages_to_reextract(ctx):
        ctx.reextracted.add((doc_id, page))
        row = ctx.repo.get_input(doc_id)
        try:
            again, _ = extract_document(doc_id, row.filename, row.path, mode="blocks", only_pages=[page])
        except Exception:  # noqa: BLE001
            continue
        res = ctx.pdf_results[doc_id]
        known = {f.fact_id for f in res.facts}
        new = [f for f in again.facts if f.fact_id not in known and f.provenance.page == page]
        if new:
            res.facts.extend(new)
            for p in res.pages:
                if p.page == page:
                    p.fact_count = len(new)
            added += len(new)
            ctx.repo.replace_facts(ctx.job.project_id, doc_id, res.facts)
            ctx.repo.put_checkpoint(ctx.job.job_id, "pdf", doc_id, res.model_dump_json())
    return f"pages={len(ctx.reextracted)} new_facts={added}"


def act_check_retrieval(ctx: Ctx, _arg) -> str:
    refs = sorted({r for res in ctx.pdf_results.values() for r in res.case_ids_found})[:5]
    if not ctx.repo.chunk_count(ctx.job.project_id):
        ctx.job.retrieval.state = StageState.SKIPPED
        ctx.job.retrieval.detail = "No text was indexed."
        return "nothing indexed"
    probe = retrieve(ctx.job.project_id, " ".join(refs) or "land acquisition case", k=3)
    if probe.state == StageState.FAILED:
        ctx.job.retrieval.state = StageState.FAILED
        ctx.job.retrieval.detail = "No retrieval method is healthy; questions will return insufficient evidence."
    elif probe.state == StageState.DEGRADED or ctx.job.retrieval.state == StageState.DEGRADED:
        ctx.job.retrieval.state = StageState.DEGRADED
        ctx.job.retrieval.detail = "Only " + ", ".join(probe.methods or ["lexical"]) + " retrieval is available."
    else:
        ctx.job.retrieval.state = StageState.SUCCEEDED
        ctx.job.retrieval.detail = "Vector and lexical retrieval are healthy."
    for w in probe.warnings:
        if w not in ctx.job.retrieval.warnings:
            ctx.job.retrieval.warnings.append(w)
    return f"{ctx.job.retrieval.state.value} hits={len(probe.hits)}"


# ---------------------------------------------------------------------------
# FUSE / INVESTIGATE_CONFLICT / CHECK_PREDICTION
# ---------------------------------------------------------------------------


def act_fuse(ctx: Ctx, _arg) -> str:
    faults.check("fusion")
    project = ctx.repo.get_project(ctx.job.project_id)
    ctx.job.fusion.state = StageState.RUNNING
    # Fuse only outputs that passed validation: facts/features in storage come from checkpointed results.
    valid_sources = {d for d, r in ctx.pdf_results.items() if r.state in (AgentState.SUCCEEDED, AgentState.PARTIAL)}
    valid_sources |= {m for m, r in ctx.map_results.items() if r.state in (AgentState.SUCCEEDED, AgentState.PARTIAL)}
    facts = [f for f in ctx.repo.list_facts(ctx.job.project_id)
             if (f.provenance.document_id if f.provenance.kind == "document" else f.provenance.map_id) in valid_sources
             or not _in_job(ctx, f)]
    features = [f for f in ctx.repo.list_features(ctx.job.project_id) if f.map_id in valid_sources or f.map_id not in ctx.job.map_ids]
    cases, conflicts, matches, warnings = fuse(ctx.job.project_id, project.corridor_id if project else None, facts,
                                               features, ctx.repo.list_resolutions(ctx.job.project_id))
    if ctx.job.map_agent.state in (AgentState.FAILED, AgentState.SKIPPED) and not features:
        warnings.append("No validated spatial data: spatial conclusions are disabled.")
    if ctx.job.pdf_agent.state in (AgentState.FAILED, AgentState.NEEDS_OCR, AgentState.SKIPPED) and not any(
            f.provenance.kind == "document" for f in facts):
        warnings.append("No validated document facts: case statuses remain UNKNOWN.")
    ctx.repo.replace_project_cases(ctx.job.project_id, cases, conflicts, matches)
    ctx.job.fusion.state = StageState.SUCCEEDED
    ctx.job.fusion.checkpoint = True
    ctx.job.fusion.detail = f"{len(cases)} case(s), {len(conflicts)} conflict(s), {len(matches)} unresolved match(es)."
    ctx.job.fusion.warnings = warnings
    ctx.job.clarifications = matches
    return ctx.job.fusion.detail


def _in_job(ctx: Ctx, f) -> bool:
    src = f.provenance.document_id if f.provenance.kind == "document" else f.provenance.map_id
    return src in ctx.job.document_ids or src in ctx.job.map_ids


def act_investigate(ctx: Ctx, conflict_id: str) -> str:
    """Gather more evidence about a conflict. Records it; never picks a winner."""
    ctx.investigated.add(conflict_id)
    conflict = next((c for c in ctx.repo.list_conflicts(ctx.job.project_id) if c.conflict_id == conflict_id), None)
    if conflict is None:
        return "gone"
    case = ctx.repo.get_case(conflict.case_id)
    query = f"{case.case_ref if case else ''} {FIELD_LABEL.get(conflict.field, conflict.field)}"
    probe = retrieve(ctx.job.project_id, query, k=4, case_ref=case.case_ref if case else None)
    pages = sorted({f"{h.filename} p.{h.page}" for h in probe.hits})
    conflict.status = "INVESTIGATED"
    conflict.note = (f"Additional evidence reviewed: {', '.join(pages)}. Values still disagree; human review required."
                     if pages else "No further evidence found. Human review required.")
    cases = ctx.repo.list_cases(ctx.job.project_id)
    conflicts = [conflict if c.conflict_id == conflict_id else c for c in ctx.repo.list_conflicts(ctx.job.project_id)]
    ctx.repo.replace_project_cases(ctx.job.project_id, cases, conflicts, ctx.repo.list_matches(ctx.job.project_id))
    return f"{conflict.field}: {len(pages)} source(s) reviewed"


def act_check_prediction(ctx: Ctx, _arg) -> str:
    status, reason = readiness()
    ctx.job.prediction_readiness = status
    ctx.job.prediction_reason = reason
    return status.value


ACTIONS = {
    "RUN_AGENTS": act_run_agents,
    "REEXTRACT_PAGES": act_reextract,
    "CHECK_RETRIEVAL": act_check_retrieval,
    "FUSE": act_fuse,
    "INVESTIGATE_CONFLICT": act_investigate,
    "CHECK_PREDICTION": act_check_prediction,
}


# ---------------------------------------------------------------------------
# FINALIZE
# ---------------------------------------------------------------------------


def _finalize(ctx: Ctx, budget_hit: bool = False) -> None:
    job = ctx.job
    pdf, mp = job.pdf_agent.state, job.map_agent.state
    good = {AgentState.SUCCEEDED, AgentState.PARTIAL}
    any_valid = pdf in good or mp in good
    all_clean = all(s in (AgentState.SUCCEEDED, AgentState.SKIPPED) for s in (pdf, mp))
    fused = job.fusion.state == StageState.SUCCEEDED

    if not any_valid:
        job.state = JobState.FAILED
        reasons = [e.message for e in job.pdf_agent.errors + job.map_agent.errors][:3]
        job.remediation = ("No input produced validated results. " + " ".join(reasons) +
                           " Fix or replace the inputs and start a new job.").strip()
    elif job.clarifications:
        job.state = JobState.NEEDS_CLARIFICATION
        job.remediation = "Some map parcels match more than one case. Confirm the matches to complete fusion."
    elif all_clean and fused and not budget_hit and job.retrieval.state != StageState.FAILED:
        job.state = JobState.SUCCEEDED
    else:
        job.state = JobState.PARTIAL
        if not fused:
            job.remediation = "Agent results were saved but fusion did not complete. Retry the job."
        elif pdf not in good and pdf != AgentState.SKIPPED:
            job.remediation = "Document analysis did not complete; map results are kept. Fix the PDF and re-run."
        elif mp not in good and mp != AgentState.SKIPPED:
            job.remediation = "Map analysis did not complete; document results are kept. Fix the map and re-run."
    ctx.audit("FINALIZE", job.state.value)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def job_results(job: Job) -> JobResults:
    repo = get_repo()
    pdf_docs = [PdfDocumentResult.model_validate_json(b) for d in job.document_ids
                if (b := repo.get_checkpoint(job.job_id, "pdf", d))]
    maps = [MapResult.model_validate_json(b) for m in job.map_ids if (b := repo.get_checkpoint(job.job_id, "map", m))]
    fused = job.fusion.state in (StageState.SUCCEEDED, StageState.DEGRADED)
    return JobResults(
        job_id=job.job_id, state=job.state, complete=job.state == JobState.SUCCEEDED,
        pdf=PdfAgentOutput(state=job.pdf_agent.state, documents=pdf_docs) if pdf_docs else None,
        map=MapAgentOutput(state=job.map_agent.state, maps=maps) if maps else None,
        cases=repo.list_cases(job.project_id) if fused else [],
        conflicts=repo.list_conflicts(job.project_id) if fused else [],
        unresolved_matches=repo.list_matches(job.project_id) if fused else [],
        warnings=job.warnings + job.fusion.warnings + job.retrieval.warnings,
    )


def summarize(job: Job) -> dict:
    return json.loads(job.model_dump_json())


def refuse_project(project_id: str):
    """Re-run fusion after a user answered a clarification. Returns remaining matches.
    Jobs waiting on clarification are completed once nothing is left to confirm."""
    repo = get_repo()
    project = repo.get_project(project_id)
    cases, conflicts, matches, warnings = fuse(project_id, project.corridor_id if project else None,
                                               repo.list_facts(project_id), repo.list_features(project_id),
                                               repo.list_resolutions(project_id))
    repo.replace_project_cases(project_id, cases, conflicts, matches)
    for job in repo.list_jobs(project_id, [JobState.NEEDS_CLARIFICATION]):
        job.clarifications = matches
        if not matches:
            clean = all(s in (AgentState.SUCCEEDED, AgentState.SKIPPED) for s in (job.pdf_agent.state, job.map_agent.state))
            job.state = JobState.SUCCEEDED if clean else JobState.PARTIAL
            job.remediation = None
        job.audit.append(AuditEvent(step=job.steps_used, action="USER_CLARIFICATION",
                                    outcome=f"{len(matches)} open", detail=None))
        repo.save_job(job)
    return matches
