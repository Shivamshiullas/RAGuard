"""Upload validation, page-level extraction, OCR fallback, table/visual detection and chunking."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from .config import Settings
from .models import Chunk

log = logging.getLogger(__name__)

PDF_TYPES = {".pdf"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg"}
SUPPORTED = PDF_TYPES | IMAGE_TYPES
_CAPTION = re.compile(r"^\s*(fig(ure)?|table|chart|diagram|graph)\b.*", re.IGNORECASE | re.MULTILINE)


class UploadRejected(ValueError):
    """The file cannot be processed; the message is safe to show to the user."""


# OCR -------------------------------------------------------------------------------------
_ocr_engine = None
_ocr_error: str | None = None


def ocr_status() -> tuple[bool, str]:
    """Whether OCR is usable, and why not."""
    _get_ocr()
    return (_ocr_engine is not None, _ocr_error or "RapidOCR (ONNX) ready")


def _get_ocr():
    global _ocr_engine, _ocr_error
    if _ocr_engine is None and _ocr_error is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ocr_engine = RapidOCR()
        except Exception as e:  # optional dependency
            _ocr_error = f"OCR unavailable ({type(e).__name__}: {e}). Install rapidocr-onnxruntime."
    return _ocr_engine


def run_ocr(image_path: Path) -> str:
    engine = _get_ocr()
    if engine is None:
        return ""
    result, _ = engine(str(image_path))
    if not result:
        return ""
    # result rows: [box, text, confidence]; keep reading order top-to-bottom, left-to-right
    rows = sorted(result, key=lambda r: (round(r[0][0][1] / 12), r[0][0][0]))
    return "\n".join(r[1] for r in rows if float(r[2]) >= 0.5)


# Validation ------------------------------------------------------------------------------
def validate_upload(filename: str, data: bytes, s: Settings) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise UploadRejected(f"Unsupported file type '{ext or 'none'}'. Upload PDF, PNG or JPG.")
    if not data:
        raise UploadRejected("The file is empty.")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise UploadRejected(f"File is larger than {s.max_upload_mb} MB.")
    if ext in PDF_TYPES and not data.startswith(b"%PDF"):
        raise UploadRejected("The file has a .pdf extension but is not a valid PDF.")
    if ext in IMAGE_TYPES and not (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8")):
        raise UploadRejected("The image file is not a valid PNG or JPEG.")
    return hashlib.sha256(data).hexdigest()


def safe_filename(name: str) -> str:
    base = Path(name).name
    return re.sub(r"[^A-Za-z0-9._ \-()]", "_", base)[:120] or "document"


# Extraction ------------------------------------------------------------------------------
@dataclass
class PageInfo:
    page: int
    text: str
    source: str  # text | ocr | none
    has_visual: bool
    image_path: str | None
    tables: list[str] = field(default_factory=list)
    captions: list[str] = field(default_factory=list)


@dataclass
class ExtractionReport:
    pages: list[PageInfo]
    ocr_pages: list[int]
    visual_pages: list[int]
    failed_pages: list[int]
    warnings: list[str]


def _render(page: fitz.Page, out: Path, dpi: int) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    page.get_pixmap(dpi=dpi).save(str(out))
    return str(out)


def extract(path: Path, doc_id: str, s: Settings) -> ExtractionReport:
    ext = path.suffix.lower()
    if ext in IMAGE_TYPES:
        return _extract_image(path, doc_id, s)
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise UploadRejected(f"Could not open PDF: {e}") from e
    if doc.needs_pass:
        raise UploadRejected("The PDF is password-protected.")
    if doc.page_count == 0:
        raise UploadRejected("The PDF has no pages.")
    if doc.page_count > s.max_pages:
        raise UploadRejected(f"The PDF has {doc.page_count} pages; the limit is {s.max_pages}.")

    pages, ocr_pages, visual_pages, failed, warnings = [], [], [], [], []
    ocr_ok, ocr_msg = ocr_status() if s.ocr_enabled else (False, "OCR disabled in configuration")
    page_dir = s.pages_dir / doc_id
    for i, page in enumerate(doc, start=1):
        try:
            text = page.get_text("text").strip()
            images = page.get_images(full=True)
            drawings = len(page.get_drawings())
            scanned = len(text) < s.min_page_chars
            has_visual = bool(images) or drawings > 25
            image_path = None
            source = "text" if text else "none"
            if scanned or has_visual:
                image_path = _render(page, page_dir / f"p{i}.png", s.render_dpi)
            if scanned:
                if ocr_ok:
                    ocr_text = run_ocr(Path(image_path)).strip()
                    if ocr_text:
                        text, source = (text + "\n" + ocr_text).strip(), "ocr"
                        ocr_pages.append(i)
                    else:
                        warnings.append(f"Page {i}: OCR found no readable text.")
                else:
                    warnings.append(f"Page {i} looks scanned but OCR is unavailable: {ocr_msg}")
            tables = []
            try:
                for t in page.find_tables().tables:
                    md = t.to_markdown().strip()
                    if md and md.count("|") > 4:
                        tables.append(md)
            except Exception:  # table detection is best-effort
                pass
            if has_visual or tables:
                visual_pages.append(i)
            pages.append(PageInfo(i, text, source, has_visual or scanned, image_path, tables,
                                  [m.group(0).strip() for m in _CAPTION.finditer(text)]))
        except Exception as e:  # one bad page must not fail the whole document
            log.exception("page %s failed", i)
            failed.append(i)
            warnings.append(f"Page {i} could not be processed ({type(e).__name__}); it was skipped.")
    doc.close()
    return ExtractionReport(pages, ocr_pages, visual_pages, failed, warnings)


def _extract_image(path: Path, doc_id: str, s: Settings) -> ExtractionReport:
    out = s.pages_dir / doc_id / "p1.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    pix = fitz.Pixmap(str(path))
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)
    pix.save(str(out))
    ocr_ok, ocr_msg = ocr_status() if s.ocr_enabled else (False, "OCR disabled in configuration")
    text = run_ocr(out).strip() if ocr_ok else ""
    warnings = [] if ocr_ok else [f"Image uploaded but OCR is unavailable: {ocr_msg}"]
    return ExtractionReport([PageInfo(1, text, "ocr" if text else "none", True, str(out))],
                            [1] if text else [], [1], [], warnings)


# Chunking --------------------------------------------------------------------------------
def _split(text: str, size: int, overlap: int) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.:;])\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        p = re.sub(r"[ \t]+", " ", p)
        if len(cur) + len(p) + 1 <= size:
            cur = f"{cur}\n{p}".strip()
            continue
        if cur:
            chunks.append(cur)
            cur = cur[-overlap:].split(" ", 1)[-1] if overlap else ""
        while len(p) > size:  # very long paragraph: hard split at a word boundary
            cut = p.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            chunks.append((cur + " " + p[:cut]).strip())
            cur, p = "", p[cut:].strip()
        cur = f"{cur}\n{p}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def _running_lines(pages: list[PageInfo]) -> set[str]:
    """Lines repeated on most pages (running headers/footers) carry no page-specific meaning."""
    if len(pages) < 2:
        return set()
    counts: dict[str, int] = {}
    for p in pages:
        for line in {l.strip() for l in p.text.splitlines() if l.strip()}:
            counts[line] = counts.get(line, 0) + 1
    return {l for l, n in counts.items() if n >= max(2, round(len(pages) * 0.66))}


def _page_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if 4 <= len(line) <= 90 and not line.endswith((".", ",")):
            return line
    return ""


def build_chunks(report: ExtractionReport, doc_id: str, filename: str, version: str, s: Settings) -> list[Chunk]:
    chunks: list[Chunk] = []
    running = _running_lines(report.pages)
    doc_title = Path(filename).stem.replace("_", " ")
    for p in report.pages:
        p.text = "\n".join(l for l in p.text.splitlines() if l.strip() not in running).strip()
        kind = "ocr" if p.source == "ocr" else "text"
        # Each chunk starts with a short context line (document + page heading) so a passage like
        # "Unit 3: Trees" can still be found by a question that mentions the course or syllabus.
        title = _page_title(p.text)
        header = f"[{doc_title} | page {p.page}{' | ' + title if title else ''}]"
        for n, piece in enumerate(_split(p.text, s.chunk_chars, s.chunk_overlap)):
            chunks.append(Chunk(f"{doc_id}:p{p.page}:t{n}", doc_id, filename, p.page, f"{header}\n{piece}", kind,
                                p.image_path, version))
        for n, table in enumerate(p.tables):
            chunks.append(Chunk(f"{doc_id}:p{p.page}:tbl{n}", doc_id, filename, p.page,
                                f"Table on page {p.page}:\n{table[:3000]}", "table", p.image_path, version))
        if p.has_visual and p.image_path:
            # A visual record lets image-aware questions find the page; the original image is
            # kept so a vision model can look at it instead of trusting this text description.
            head = " ".join(p.text.split()[:60])
            desc = "; ".join(p.captions) or "no caption detected"
            chunks.append(Chunk(f"{doc_id}:p{p.page}:vis", doc_id, filename, p.page,
                                f"Visual content (figure, chart, diagram or scanned image) on page {p.page}. "
                                f"Captions: {desc}. Page context: {head}", "visual", p.image_path, version))
    return chunks
