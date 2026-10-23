"""Test fixtures: isolated storage per test and a scriptable fake LLM."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from college_rag import config, faults, llm, runtime  # noqa: E402
from college_rag.ingestion import UploadMetadata, upload_document  # noqa: E402
from college_rag.llm import LLMClient, LLMUnavailable  # noqa: E402


class FakeLLM(LLMClient):
    """Deterministic stand-in for Gemini/Ollama.

    answer_mode: "cite" (answer with the first passage's first line, cited),
    "insufficient", "uncited", "bad_citation", "conflict" or "down".
    plan: a dict returned for planner prompts, or None to raise LLMUnavailable.
    """

    def __init__(self):
        self.answer_mode = "cite"
        self.plan: dict | None = None
        self.vision_text: str | None = None
        self.calls: list[str] = []

    def generate(self, prompt, system=None):
        self.calls.append("generate")
        raise LLMUnavailable("fake")

    def generate_json(self, prompt, model, system=None):
        if system and "request router" in system:
            self.calls.append("plan")
            if self.plan is None:
                raise LLMUnavailable("planner down")
            return model.model_validate(self.plan)
        self.calls.append("answer")
        mode = self.answer_mode
        if mode == "down":
            raise LLMUnavailable("fake outage")
        passage = re.search(r"\[S1\] \(.*?\)\n<<<\n(.*?)\n", prompt, re.S)
        first = passage.group(1).strip() if passage else ""
        data = {
            "cite": {"answer": f"{first} [S1]"},
            "insufficient": {"answer": "The documents do not mention this.", "insufficient_evidence": True},
            "uncited": {"answer": "The fee is Rs. 1,00,000."},
            "bad_citation": {"answer": f"{first} [S99]"},
            "conflict": {"answer": f"{first} [S1] but another says otherwise [S2]", "conflict": True},
        }[mode]
        return model.model_validate(data)

    def read_image(self, image, mime, prompt):
        faults.check("vision")
        if self.vision_text is None:
            raise LLMUnavailable("no vision")
        return self.vision_text

    def has_vision(self):
        return self.vision_text is not None

    def health(self):
        return {"fake": True}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("FAULTS", "")
    monkeypatch.setenv("MIN_SIMILARITY", "0.2")
    config.get_settings.cache_clear()
    runtime.reset()
    faults.configure("")
    fake = FakeLLM()
    llm.set_llm(fake)
    yield fake
    llm.set_llm(None)
    runtime.reset()
    config.get_settings.cache_clear()


@pytest.fixture
def fake_llm(isolated) -> FakeLLM:
    return isolated


# ---------------------------------------------------------------------------
# Sample file builders
# ---------------------------------------------------------------------------

FEES_TEXT = """Fee Structure 2026-27
Semester 5 tuition fee is Rs. 64,500 and other fees are Rs. 7,500.
Semester 6 tuition fee is Rs. 64,500.
Fees must be paid by 31 July 2026. A late fee of Rs. 100 per day applies."""

CAMPUS_TEXT = """Campus Information
The campus is located at 42 Lakeview Road, Northfield.
The library is open from 8:00 am to 9:00 pm on weekdays."""

CALENDAR_TEXT = """Academic Calendar 2026-27
Course registration closes on 31 July 2026.
End-semester examinations run from 26 November to 12 December 2026."""


def make_pdf(pages: list[str]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), text, fontsize=11)
    return doc.tobytes()


def text_image(text: str, width: int = 900, height: int = 300) -> bytes:
    """Render text to a PNG via PyMuPDF (real glyphs, so OCR can read it)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=width / 2, height=height / 2)
    page.insert_textbox(pymupdf.Rect(10, 10, width / 2 - 10, height / 2 - 10), text, fontsize=14)
    return page.get_pixmap(dpi=144).tobytes("png")


def make_scanned_pdf(text: str) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=300)
    page.insert_image(page.rect, stream=text_image(text, 1200, 600))
    return doc.tobytes()


def make_docx(paragraphs: list[str]) -> bytes:
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def index(filename: str, data: bytes, title: str, category: str = "Other", replaces_id: str | None = None,
          **meta) -> tuple[str, int]:
    return upload_document(filename, data, UploadMetadata(title=title, category=category, **meta), replaces_id,
                           run_async=False)


@pytest.fixture
def college_kb():
    """Fees (PDF), campus (TXT) and calendar (DOCX) indexed."""
    fees = index("fees.pdf", make_pdf([FEES_TEXT]), "Fee Structure 2026-27", "Fees", semester="All semesters")
    campus = index("campus.txt", CAMPUS_TEXT.encode(), "Campus Information", "Campus & facilities")
    calendar = index("calendar.docx", make_docx(CALENDAR_TEXT.split("\n")), "Academic Calendar", "Academic calendar")
    return {"fees": fees, "campus": campus, "calendar": calendar}
