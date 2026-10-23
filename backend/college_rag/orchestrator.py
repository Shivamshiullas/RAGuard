"""Executes a router plan and builds the single combined chat response.

- General/unclear/out-of-scope messages are answered directly with no retrieval.
- College tasks check the negative-result cache first, then run an agent.
- Independent tasks run concurrently (bounded); dependent tasks run after
  their prerequisites, with prerequisite answers passed as context.
- Cross-agent recovery is attempted once, only after an agent's own fallbacks
  failed and only when the other agent has usable input.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait

from . import negative_cache
from .agents import ImageInput, run_image_agent, run_text_agent
from .answering import NO_EVIDENCE_ANSWER
from .config import get_settings
from .router import DECLINE_REPLY, IMAGE_ONLY_QUESTION, route
from .runtime import get_store
from .schemas import AgentResult, ChatResponse, PlanTask, RecoveryInfo, RouterPlan, Source, TaskItem, TaskSummary

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 2000
TIMEOUT_ANSWER = "This part took too long to answer. Please try asking it again on its own."


def _negative_hit() -> AgentResult:
    return AgentResult(agent="text_agent", status="no_evidence", answer=NO_EVIDENCE_ANSWER, from_negative_cache=True)


def run_task(task: PlanTask, image: ImageInput | None, context_notes: list[str]) -> AgentResult:
    if task.suggested_agent == "image_agent" and image is not None:
        result, partial_text = run_image_agent(task.question, image, context_notes)
        typed_question = task.question.strip() and task.question != IMAGE_ONLY_QUESTION
        if result.status == "failed" and result.failed_stage == "ocr" and typed_question:
            # Cross-agent recovery: typed question plus whatever OCR managed to read.
            log.info("Image agent failed; recovering with the text agent")
            notes = list(context_notes)
            if partial_text.strip():
                notes.append(f'Partially readable text from the screenshot (may be inaccurate):\n"""\n{partial_text[:800]}\n"""')
            recovered = run_text_agent(task.question, notes)
            recovered.recovery_attempts = result.recovery_attempts + 1
            recovered.recovery_method = "cross_agent_text"
            recovered.recovery_status = "recovered" if recovered.status != "failed" else "failed"
            recovered.warnings.insert(0, "The screenshot couldn't be read, so this answer is based on your typed question.")
            recovered.cacheable_miss = False
            return recovered
        return result

    key, normalized = negative_cache.cache_key(task.question, "college_specific", task.category, task.semester,
                                               task.academic_year)
    if not context_notes and negative_cache.lookup(key):
        return _negative_hit()

    generation = get_store().kb_generation()
    result = run_text_agent(task.question, context_notes)
    if result.cacheable_miss and not context_notes:
        negative_cache.record(key, normalized, generation)

    if result.status == "failed" and image is not None:
        # Cross-agent recovery: the text path is down; try once more via the image agent.
        log.info("Text agent failed; trying the image agent")
        recovered, _ = run_image_agent(task.question, image, context_notes)
        recovered.recovery_attempts = result.recovery_attempts + 1
        recovered.recovery_method = "cross_agent_image"
        recovered.recovery_status = "recovered" if recovered.status != "failed" else "failed"
        return recovered
    return result


def execute_plan(plan: RouterPlan, image: ImageInput | None) -> dict[str, AgentResult]:
    settings = get_settings()
    tasks = {t.task_id: t for t in plan.tasks}
    results: dict[str, AgentResult] = {}
    pending = dict(tasks)

    pool = ThreadPoolExecutor(max_workers=settings.task_concurrency, thread_name_prefix="task")
    try:
        while pending:
            ready = [t for t in pending.values() if all(d in results for d in t.dependencies)]
            if not ready:  # cannot happen for a validated plan; stop rather than loop
                break
            futures = {}
            for task in ready:
                del pending[task.task_id]
                prerequisites = [results[d] for d in task.dependencies]
                if any(p.status == "failed" for p in prerequisites):
                    results[task.task_id] = AgentResult(
                        agent=task.suggested_agent, status="failed",
                        answer="Skipped because an earlier step it depends on could not be completed.",
                        failed_stage="dependency", error_code="dependency_failed",
                    )
                    continue
                notes = [
                    f"Earlier finding for \"{tasks[d].question}\": {results[d].answer}"
                    for d in task.dependencies if results[d].status in ("success", "partial", "degraded")
                ]
                futures[pool.submit(run_task, task, image, notes)] = task
            done, not_done = wait(futures, timeout=settings.task_timeout_s)
            for future in done:
                task = futures[future]
                try:
                    results[task.task_id] = future.result()
                except Exception:  # noqa: BLE001
                    log.exception("Task %s crashed", task.task_id)
                    results[task.task_id] = AgentResult(
                        agent=task.suggested_agent, status="failed",
                        answer="Something went wrong while answering this part.", error_code="task_error",
                    )
            for future in not_done:
                future.cancel()
                task = futures[future]
                results[task.task_id] = AgentResult(
                    agent=task.suggested_agent, status="failed", answer=TIMEOUT_ANSWER, error_code="timeout"
                )
    finally:
        # Don't block the reply on a timed-out task; it finishes in the background.
        pool.shutdown(wait=False, cancel_futures=True)
    return results


_MARKER = re.compile(r"\[(\d+)\]")


def combine(plan: RouterPlan, results: dict[str, AgentResult]) -> tuple[str, list[Source]]:
    """Merge task answers into one reply with one de-duplicated, renumbered source list."""
    sources: list[Source] = []
    index: dict[tuple, int] = {}

    def renumber(result: AgentResult) -> str:
        local: dict[int, int] = {}
        for i, s in enumerate(result.sources, 1):
            key = (s.doc_id, s.version, s.page, s.filename)
            if key not in index:
                sources.append(s)
                index[key] = len(sources)
            local[i] = index[key]
        return _MARKER.sub(lambda m: f"[{local.get(int(m.group(1)), int(m.group(1)))}]", result.answer)

    if len(plan.tasks) == 1:
        return renumber(results[plan.tasks[0].task_id]), sources
    sections = []
    for n, task in enumerate(plan.tasks, 1):
        result = results.get(task.task_id)
        body = renumber(result) if result else "This part could not be answered."
        sections.append(f"**{n}. {task.question.strip()}**\n{body}")
    return "\n\n".join(sections), sources


def overall_status(results: list[AgentResult]) -> str:
    statuses = [r.status for r in results]
    if not statuses or all(s == "failed" for s in statuses):
        return "failed"
    if all(s == "no_evidence" for s in statuses):
        return "no_evidence"
    if all(s == "success" for s in statuses):
        return "success"
    if any(s == "degraded" for s in statuses) and not any(s in ("success", "partial") for s in statuses):
        return "degraded"
    return "partial"


def handle_chat(message: str, image: ImageInput | None = None) -> ChatResponse:
    request_id = uuid.uuid4().hex[:12]
    started = time.monotonic()
    message = (message or "").strip()[:MAX_MESSAGE_CHARS]

    plan = route(message, has_image=image is not None)
    response = _respond(plan, image, request_id)
    # Privacy: log sizes and outcomes, not the student's question text.
    log.info(
        "chat request=%s route=%s status=%s tasks=%d chars=%d image=%s ms=%d",
        request_id, plan.intent, response.status, len(plan.tasks), len(message), image is not None,
        (time.monotonic() - started) * 1000,
    )
    return response


def _respond(plan: RouterPlan, image: ImageInput | None, request_id: str) -> ChatResponse:
    if plan.intent == "general":
        return ChatResponse(answer=plan.direct_response or "", status="general", route="general",
                            agents=["router"], request_id=request_id)
    if plan.intent == "unclear":
        return ChatResponse(answer=plan.clarification_question or "", status="clarification", route="unclear",
                            agents=["router"], request_id=request_id)
    if plan.intent == "out_of_scope":
        return ChatResponse(answer=DECLINE_REPLY, status="declined", route="out_of_scope", agents=["router"],
                            request_id=request_id)

    results = execute_plan(plan, image)
    ordered = [results[t.task_id] for t in plan.tasks if t.task_id in results]
    answer, sources = combine(plan, results)

    warnings: list[str] = []
    for r in ordered:
        for w in r.warnings:
            if w not in warnings:
                warnings.append(w)

    attempted = [r for r in ordered if r.recovery_attempts > 0]
    methods = list(dict.fromkeys(r.recovery_method for r in attempted if r.recovery_method))
    recovery = RecoveryInfo(
        attempted=bool(attempted),
        method=", ".join(methods) or None,
        status="not_needed" if not attempted else (
            "recovered" if all(r.recovery_status == "recovered" for r in attempted) else "failed"),
    )
    items = [
        TaskItem(task_id=t.task_id, question=t.question, status=results[t.task_id].status if t.task_id in results else "skipped",
                 agent=results[t.task_id].agent if t.task_id in results else t.suggested_agent)
        for t in plan.tasks
    ]
    return ChatResponse(
        answer=answer,
        status=overall_status(ordered),
        route=plan.intent,
        sources=sources,
        warnings=warnings,
        tasks=TaskSummary(completed=sum(1 for r in ordered if r.status != "failed"), total=len(plan.tasks), items=items),
        agents=["router", *dict.fromkeys(r.agent for r in ordered)],
        recovery=recovery,
        request_id=request_id,
    )
