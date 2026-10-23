"""Upload validation and parsing (Parser implementations).

Stage 1: PDFParser extracts text blocks with PyMuPDF, detects headings by font size/weight,
keeps every table as one unit, and chunks by section and paragraph with overlap.
Stage 2 (FEATURE_OCR / FEATURE_VISUALS): scanned pages are OCR'd, image uploads are accepted,
tables and figures are tagged and page images are rendered.
"""
from __future__ import annotations

import hashlib
import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from .config import Settings
from .interfaces import ParseResult
from .models import Chunk

log = logging.getLogger(__name__)

PDF_TYPES = {".pdf"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg"}
_CAPTION = re.compile(r"^\s*(fig(ure)?|table|chart|diagram|graph)\b.*", re.IGNORECASE | re.MULTILINE)
_SENTENCE = re.compile(r"(?<=[.!?;])\s+")


class UploadRejected(ValueError):
    """The file cannot be processed; the message is safe to show to the user."""


# OCR (stage 2) ---------------------------------------------------------------------------
_ocr_engine = None
_ocr_error: str | None = None


def ocr_status() -> tuple[bool, str]:
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
    rows = sorted(result, key=lambda r: (round(r[0][0][1] / 12), r[0][0][0]))
    return "\n".join(r[1] for r in rows if float(r[2]) >= 0.5)


# Validation ------------------------------------------------------------------------------
def supported_types(s: Settings) -> set[str]:
    return PDF_TYPES | (IMAGE_TYPES if s.on("ocr") else set())


def validate_upload(filename: str, data: bytes, s: Settings) -> str:
    """Check type, size and signature; returns the SHA-256 used for de-duplication."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_TYPES and not s.on("ocr"):
        raise UploadRejected("Image uploads need OCR, which is a Stage 2 feature. Upload a text PDF.")
    if ext not in supported_types(s):
        allowed = ", ".join(sorted(t.strip(".").upper() for t in supported_types(s)))
        raise UploadRejected(f"Unsupported file type '{ext or 'none'}'. Upload {allowed}.")
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


# Layout blocks ---------------------------------------------------------------------------
@dataclass
class Block:
    kind: str  # heading | para | table
    text: str
    y: float
    size: float = 0.0


@dataclass
class PageContent:
    page: int
    blocks: list[Block]
    raw_text: str
    source: str = "text"  # text | ocr | none
    image_path: str | None = None
    has_visual: bool = False
    captions: list[str] = field(default_factory=list)


def _block_text(b: dict) -> tuple[str, float, bool]:
    lines, sizes, bold = [], [], True
    for line in b.get("lines", []):
        spans = line.get("spans", [])
        t = "".join(s.get("text", "") for s in spans).strip()
        if t:
            lines.append(t)
            sizes += [s.get("size", 0) for s in spans if s.get("text", "").strip()]
            bold = bold and all((s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower()
                                for s in spans if s.get("text", "").strip())
    return "\n".join(lines), (max(sizes) if sizes else 0.0), bold and bool(lines)


def _table_markdown(page: fitz.Page, table) -> str:
    """Markdown for a detected table, with each cell read from the page's words.

    PyMuPDF's own cell text can drop the spaces in bold text ("Conductedin"), so cell text is
    rebuilt from words inside each cell's rectangle.
    """
    rows = []
    for row in table.rows:
        cells = []
        for bbox in row.cells:
            if bbox is None:
                cells.append("")
                continue
            words = page.get_text("words", clip=fitz.Rect(bbox))
            cells.append(" ".join(w[4] for w in sorted(words, key=lambda w: (round(w[1]), w[0]))).replace("|", "/"))
        rows.append(cells)
    if not rows or not any(any(c for c in r) for r in rows):
        return ""
    width = max(len(r) for r in rows)
    lines = ["|" + "|".join(r + [""] * (width - len(r))) + "|" for r in rows]
    lines.insert(1, "|" + "|".join(["---"] * width) + "|")
    return "\n".join(lines)


def _overlaps(r: fitz.Rect, tables: list[fitz.Rect]) -> bool:
    for t in tables:
        inter = r & t
        if not inter.is_empty and inter.get_area() >= 0.5 * max(r.get_area(), 1e-6):
            return True
    return False


class PDFParser:
    def __init__(self, s: Settings):
        self.s = s
        self.ocr = s.on("ocr")
        self.visuals = s.on("visuals")

    def supports(self, filename: str) -> bool:
        return Path(filename).suffix.lower() in PDF_TYPES

    def parse(self, path: Path, doc_id: str, filename: str, version: str) -> ParseResult:
        try:
            doc = fitz.open(path)
        except Exception as e:
            raise UploadRejected(f"Could not open PDF: {e}") from e
        try:
            if doc.needs_pass:
                raise UploadRejected("The PDF is password-protected.")
            if doc.page_count == 0:
                raise UploadRejected("The PDF has no pages.")
            if doc.page_count > self.s.max_pages:
                raise UploadRejected(f"The PDF has {doc.page_count} pages; the limit is {self.s.max_pages}.")
            pages, warnings, failed, ocr_pages = [], [], [], []
            raw: list[tuple[fitz.Page, int]] = []
            for i, page in enumerate(doc, start=1):
                raw.append((page, i))
            body_size = self._body_font_size(doc)
            for page, i in raw:
                try:
                    pc = self._read_page(page, i, doc_id, body_size, warnings)
                    if pc.source == "ocr":
                        ocr_pages.append(i)
                    pages.append(pc)
                except Exception as e:  # one bad page must not fail the whole document
                    log.exception("page %s failed", i)
                    failed.append(i)
                    warnings.append(f"Page {i} could not be processed ({type(e).__name__}); it was skipped.")
        finally:
            doc.close()
        chunks = build_chunks(pages, doc_id, filename, version, self.s)
        visual = sorted({c.page for c in chunks if c.kind in {"table", "figure"}})
        return ParseResult(chunks, len(pages) + len(failed), warnings, ocr_pages, visual, failed)

    @staticmethod
    def _body_font_size(doc: fitz.Document) -> float:
        sizes: list[float] = []
        for page in doc:
            for b in page.get_text("dict").get("blocks", []):
                for line in b.get("lines", []):
                    for sp in line.get("spans", []):
                        sizes += [round(sp.get("size", 0), 1)] * len(sp.get("text", "").strip())
        return statistics.median(sizes) if sizes else 10.0

    def _read_page(self, page: fitz.Page, i: int, doc_id: str, body_size: float, warnings: list[str]) -> PageContent:
        table_rects, blocks = [], []
        try:
            for t in page.find_tables().tables:
                md = _table_markdown(page, t)
                if md and md.count("|") > 4:
                    table_rects.append(fitz.Rect(t.bbox))
                    blocks.append(Block("table", md, t.bbox[1]))
        except Exception:  # table detection is best-effort
            pass
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") != 0 or _overlaps(fitz.Rect(b["bbox"]), table_rects):
                continue
            text, size, bold = _block_text(b)
            if not text:
                continue
            short = len(text) <= 90 and "\n" not in text and not text.endswith((".", ","))
            heading = short and (size >= body_size * self.s.heading_size_ratio or bold)
            blocks.append(Block("heading" if heading else "para", text, b["bbox"][1], size))
        blocks.sort(key=lambda b: b.y)
        raw_text = page.get_text("text").strip()
        pc = PageContent(i, blocks, raw_text, "text" if raw_text else "none")

        scanned = len(raw_text) < self.s.min_page_chars
        has_visual = bool(page.get_images(full=True)) or len(page.get_drawings()) > 25
        if scanned and not self.ocr:
            warnings.append(f"Page {i} has little or no extractable text (it may be scanned). "
                            "OCR is a Stage 2 feature, so the page was not indexed.")
        if self.visuals or self.ocr:
            if scanned or has_visual:
                out = self.s.pages_dir / doc_id / f"p{i}.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                page.get_pixmap(dpi=self.s.render_dpi).save(str(out))
                pc.image_path = str(out)
            if scanned and self.ocr:
                ok, msg = ocr_status()
                text = run_ocr(Path(pc.image_path)).strip() if ok else ""
                if text:
                    pc.blocks = [Block("para", p, n) for n, p in enumerate(text.split("\n\n"))]
                    pc.source = "ocr"
                else:
                    warnings.append(f"Page {i}: " + ("OCR found no readable text." if ok else msg))
            pc.has_visual = self.visuals and (has_visual or scanned)
            pc.captions = [m.group(0).strip() for m in _CAPTION.finditer(raw_text)]
        return pc


class ImageParser:
    """Stage 2: a PNG/JPG upload is one page, read with OCR."""

    def __init__(self, s: Settings):
        self.s = s

    def supports(self, filename: str) -> bool:
        return self.s.on("ocr") and Path(filename).suffix.lower() in IMAGE_TYPES

    def parse(self, path: Path, doc_id: str, filename: str, version: str) -> ParseResult:
        out = self.s.pages_dir / doc_id / "p1.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        pix = fitz.Pixmap(str(path))
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        pix.save(str(out))
        ok, msg = ocr_status()
        text = run_ocr(out).strip() if ok else ""
        warnings = [] if ok else [f"OCR is unavailable: {msg}"]
        pc = PageContent(1, [Block("para", text, 0)] if text else [], text, "ocr" if text else "none",
                         str(out), self.s.on("visuals"))
        chunks = build_chunks([pc], doc_id, filename, version, self.s)
        return ParseResult(chunks, 1, warnings, [1] if text else [], [1] if pc.has_visual else [], [])


# Chunking --------------------------------------------------------------------------------
def _running_lines(pages: list[PageContent]) -> set[str]:
    """Lines repeated on most pages (running headers/footers) carry no page-specific meaning."""
    if len(pages) < 2:
        return set()
    counts: dict[str, int] = {}
    for p in pages:
        for line in {l.strip() for b in p.blocks for l in b.text.splitlines() if l.strip()}:
            counts[line] = counts.get(line, 0) + 1
    return {l for l, n in counts.items() if n >= max(2, round(len(pages) * 0.66))}


def _split_long(text: str, size: int) -> list[str]:
    """Split a paragraph longer than ``size`` at sentence (then word) boundaries."""
    out, cur = [], ""
    for sent in _SENTENCE.split(text):
        while len(sent) > size:
            cut = sent.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            out.append((cur + " " + sent[:cut]).strip())
            cur, sent = "", sent[cut:].strip()
        if len(cur) + len(sent) + 1 > size and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


def _tail(text: str, overlap: int) -> str:
    """The last ``overlap`` characters of ``text``, starting at a sentence or word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    m = _SENTENCE.search(tail)
    return tail[m.end():] if m else tail.split(" ", 1)[-1]


def build_chunks(pages: list[PageContent], doc_id: str, filename: str, version: str, s: Settings) -> list[Chunk]:
    """Section-aware chunking. Chunks never cross pages (so citations stay exact), a heading
    starts a new chunk, paragraphs are packed up to ``chunk_chars`` with overlap, and each
    table is kept whole in a single chunk."""
    running = _running_lines(pages)
    doc_title = Path(filename).stem.replace("_", " ")
    chunks: list[Chunk] = []
    heading = ""
    for p in pages:
        blocks = []
        for b in p.blocks:
            text = "\n".join(l for l in b.text.splitlines() if l.strip() not in running).strip()
            if text:
                blocks.append(Block(b.kind, text, b.y, b.size))
        kind_default = "ocr" if p.source == "ocr" else "text"
        n = 0

        def emit(body: str, kind: str) -> None:
            nonlocal n
            header = f"[{doc_title} | page {p.page}{' | ' + heading if heading else ''}]"
            chunks.append(Chunk(f"{doc_id}:p{p.page}:c{n}", doc_id, filename, p.page, f"{header}\n{body}", kind,
                                p.image_path, version))
            n += 1

        buf, has_body = "", False
        for b in blocks:
            if b.kind == "heading":
                if has_body:
                    emit(buf, kind_default)
                heading, buf, has_body = b.text, b.text, False
            elif b.kind == "table":
                if has_body:
                    emit(buf, kind_default)
                    buf, has_body = "", False
                emit(f"{buf}\n{b.text}".strip() if buf else b.text, "table" if s.on("visuals") else kind_default)
                buf = ""
            else:
                for piece in _split_long(b.text, s.chunk_chars):
                    if has_body and len(buf) + len(piece) + 1 > s.chunk_chars:
                        emit(buf, kind_default)
                        buf = _tail(buf, s.chunk_overlap)
                    buf, has_body = f"{buf}\n{piece}".strip(), True
        if has_body:
            emit(buf, kind_default)

        if p.has_visual and p.image_path:
            # A figure record lets image-aware questions find the page; the original image is kept
            # so a vision model can look at it instead of trusting this text description.
            head = " ".join(" ".join(b.text for b in blocks).split()[:60])
            desc = "; ".join(p.captions) or "no caption detected"
            chunks.append(Chunk(f"{doc_id}:p{p.page}:fig", doc_id, filename, p.page,
                                f"[{doc_title} | page {p.page}]\nVisual content (figure, chart, diagram or scanned "
                                f"image) on page {p.page}. Captions: {desc}. Page context: {head}", "figure",
                                p.image_path, version))
    return chunks
