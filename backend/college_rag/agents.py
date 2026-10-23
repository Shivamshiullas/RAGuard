"""Specialist agents. Both return the shared `AgentResult` schema.

Text agent: ChromaDB retrieval (BM25 fallback) -> grounded answer.
Image agent: validate -> OCR -> preprocess+retry -> optional vision fallback ->
retrieval from the same knowledge base, keeping the typed question alongside
the text read from the image.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .answering import generate_answer
from .llm import LLMUnavailable, get_llm
from .ocr import ImageRejected, is_usable, ocr_image, validate_image
from .retrieval import retrieve
from .router import COLLEGE_TERMS
from .schemas import AgentResult

log = logging.getLogger(__name__)

MAX_OCR_CONTEXT_CHARS = 1500
RETRIEVAL_UNAVAILABLE = (
    "I couldn't search the college documents right now because the search service is unavailable. "
    "Please try again in a few minutes."
)
VISION_PROMPT = (
    "Transcribe all readable text in this image exactly, line by line. "
    "Output only the transcribed text. If no text is readable, output nothing."
)


@dataclass
class ImageInput:
    data: bytes
    filename: str = "screenshot"


def run_text_agent(question: str, context_notes: list[str] | None = None, search_query: str | None = None,
                   agent: str = "text_agent") -> AgentResult:
    outcome = retrieve(search_query or question)
    if not outcome.completed:
        return AgentResult(
            agent=agent, status="failed", answer=RETRIEVAL_UNAVAILABLE, warnings=outcome.warnings,
            failed_stage="retrieval", error_code=outcome.error_code or "retrieval_unavailable",
            recovery_attempts=1, recovery_status="failed", recovery_method="bm25_fallback",
        )

    answer = generate_answer(question, outcome.passages, context_notes)
    result = AgentResult(
        agent=agent, status=answer.status, answer=answer.answer, sources=answer.sources,
        warnings=[*outcome.warnings, *answer.warnings], failed_stage=answer.failed_stage,
        error_code=answer.error_code, cacheable_miss=answer.cacheable_miss,
    )
    if outcome.method == "bm25":
        result.recovery_attempts += 1
        result.recovery_status = "recovered"
        result.recovery_method = "bm25_fallback"
        if result.status == "success":
            result.status = "partial"
    if answer.error_code == "llm_unavailable":
        result.recovery_attempts += 1
        result.recovery_status = "recovered"
        result.recovery_method = "evidence_only"
    # A degraded search path could have missed evidence; never cache that as "no answer".
    if outcome.method != "vector":
        result.cacheable_miss = False
    return result


@dataclass
class ImageReading:
    text: str
    usable: bool
    method: str  # "ocr" | "ocr_preprocessed" | "vision" | "none"
    attempts: int
    error_code: str | None = None


def read_image(image: ImageInput) -> ImageReading:
    try:
        pil, mime = validate_image(image.data)
    except ImageRejected:
        return ImageReading("", False, "none", 0, "invalid_image")

    attempts = 0
    partial = ""
    try:
        ocr = ocr_image(pil)
        attempts = ocr.attempts
        partial = ocr.text
        if ocr.usable:
            return ImageReading(ocr.text, True, "ocr_preprocessed" if ocr.preprocessed else "ocr", attempts)
    except Exception as exc:  # noqa: BLE001
        attempts = 2
        log.warning("OCR failed after retry: %s", exc)

    llm = get_llm()
    if llm.has_vision():
        attempts += 1
        try:
            text = llm.read_image(image.data, mime, VISION_PROMPT).strip()
            if is_usable(text):
                return ImageReading(text, True, "vision", attempts)
        except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
            log.warning("Vision fallback failed: %s", exc)
    return ImageReading(partial, False, "none", attempts, "ocr_unreadable")


def run_image_agent(question: str, image: ImageInput, context_notes: list[str] | None = None) -> tuple[AgentResult, str]:
    """Returns the result and whatever text (possibly partial) was read from the image."""
    reading = read_image(image)
    if not reading.usable:
        message = (
            "The attached image isn't a valid PNG or JPG file."
            if reading.error_code == "invalid_image"
            else "I couldn't read the text in the attached image. Try a sharper, uncropped screenshot."
        )
        return AgentResult(
            agent="image_agent", status="failed", answer=message, failed_stage="ocr",
            error_code=reading.error_code, recovery_attempts=max(0, reading.attempts - 1),
            recovery_status="failed" if reading.attempts > 1 else "not_needed",
            recovery_method="ocr_preprocess_retry" if reading.attempts > 1 else None,
        ), reading.text

    ocr_text = reading.text[:MAX_OCR_CONTEXT_CHARS]
    notes = [*(context_notes or []), f'Text read from the student\'s screenshot:\n"""\n{ocr_text}\n"""']
    asked = question.strip() or "Explain what this screenshot says, using the official college documents."
    result = run_text_agent(asked, notes, search_query=f"{asked}\n{ocr_text}", agent="image_agent")
    if reading.method != "ocr":
        result.recovery_attempts += reading.attempts - 1
        result.recovery_method = "vision_fallback" if reading.method == "vision" else "ocr_preprocess_retry"
        if result.recovery_status != "failed":
            result.recovery_status = "recovered"
    result.cacheable_miss = False  # image questions are not keyed in the negative cache
    return result, reading.text
