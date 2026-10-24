"""PDF Intelligence Agent.

Reads selectable-text PDFs with PyMuPDF, page by page. Produces:
- chunks for RAG (never crossing a page, each tagged with the case refs it mentions)
- candidate facts (case refs, survey numbers, statuses, amounts, percentages, dates),
  each with document_id, page, chunk_id and the exact evidence line.

Facts from explicitly labelled lines ("Legal status: Dispute") are VALIDATED;
facts inferred from keywords in free text are UNVERIFIED. A fact is attached to
a case only when its case section is unambiguous. Pages without usable text are
read with OCR (see ocr.py) up to OCR_MAX_PAGES per document; facts from OCR pages
carry an "ocr:<engine>" extraction method and a warning to check them against the
scan. A document with no usable text even after OCR returns NEEDS_OCR.

Document text is data. Nothing in it can change what the agent does.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import faults
from .ocr import OcrUnavailable, ocr_page
from .config import get_settings
from .schemas import AgentState, DocumentProvenance, ErrorInfo, Fact, PageReport, PdfDocumentResult, ValidationStatus


class PermanentAgentError(Exception):
    """Invalid input: retrying will not help."""

    def __init__(self, code: str, message: str, remediation: str | None = None):
        super().__init__(message)
        self.code = code
        self.remediation = remediation


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

CASE_REF = re.compile(r"(?:\bcase\s*(?:id|no\.?|number|ref\.?)?\s*[:#]?\s*#?|#)\s?(\d{3,5})\b", re.I)
SURVEY = re.compile(
    r"\b(?:sy|survey|khasra)\.?\s*(?:no|nos|number)?s?\.?\s*[:\-]?\s*"
    r"(\d{1,5}(?:/[\dA-Za-z]{1,4})*(?:\s*(?:,|and|&)\s*\d{1,5}(?:/[\dA-Za-z]{1,4})*)*)", re.I)
PARCEL = re.compile(r"\bparcel\s*(?:id|no\.?|number)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/_.-]{1,30})", re.I)
VILLAGE = re.compile(r"\b[Vv]illage\s*[:\-]\s*([A-Z][A-Za-z .'-]{2,60}?)(?=[,;\n]|\s{2}|$)")
DISTRICT = re.compile(r"\b[Dd]istrict\s*[:\-]\s*([A-Z][A-Za-z ./'-]{2,60}?)(?=[,;\n]|\s{2}|$)")
AREA = re.compile(r"\b(\d{1,4}(?:\.\d{1,3})?)\s*(?:ha\b|hectares?\b)", re.I)
AMOUNT = re.compile(r"(?:₹|\brs\.?|\binr)\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|lacs?|l\b)?", re.I)
PERCENT = r"(\d{1,3}(?:\.\d{1,2})?)\s*%"
DATE = r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{4}-\d{2}-\d{2})"

LABELLED = re.compile(
    r"^\s*(?P<label>legal\s+status|litigation\s+status|compensation\s+status|award\s+status|"
    r"(?:approval|clearance)\s+status|r\s*&\s*r\s+status|rehabilitation\s+status)\s*[:\-]\s*(?P<value>.+)$",
    re.I | re.M,
)

LEGAL_VALUES = [
    ("CLEAR", re.compile(r"\b(clear|no (?:pending )?(?:litigation|dispute|case)s?|title (?:is )?(?:clear|verified))\b", re.I)),
    ("IN_COURT", re.compile(r"\b(in court|high court|supreme court|writ|stay order|interim stay|sub[- ]judice)\b", re.I)),
    ("PENDING_SETTLEMENT", re.compile(r"\b(settlement|mediation|lok adalat|arbitration)\b", re.I)),
    ("DISPUTE", re.compile(r"\b(disput\w*|contest\w*|objection\w*|tribunal)\b", re.I)),
]
COMP_VALUES = [
    ("DISPUTED", re.compile(r"\b(disput\w*|appeal\w*|contest\w*)\b", re.I)),
    ("DISBURSED", re.compile(r"\b(fully disbursed|disbursed in full|100\s*% (?:disbursed|paid)|completed|paid in full)\b", re.I)),
    ("IN_PROGRESS", re.compile(r"\b(in progress|partially (?:disbursed|paid)|partial)\b", re.I)),
    ("PENDING", re.compile(r"\b(pending|awaiting|not (?:yet )?(?:disbursed|paid)|stalled|withheld)\b", re.I)),
]
CLEARANCE_VALUES = [
    ("CLEARED", re.compile(r"\b(cleared|granted|obtained|approved|in place)\b", re.I)),
    ("DELAYED", re.compile(r"\b(delayed|overdue|stalled)\b", re.I)),
    ("UNDER_REVIEW", re.compile(r"\b(under review|under consideration|under examination)\b", re.I)),
    ("PENDING", re.compile(r"\b(pending|awaited|applied)\b", re.I)),
]
RR_VALUES = [
    ("COMPLETED", re.compile(r"\b(completed|complete|resettled)\b", re.I)),
    ("IN_PROGRESS", re.compile(r"\b(in progress|ongoing|underway|\d{1,3}\s*%)\b", re.I)),
    ("PENDING", re.compile(r"\b(pending|not started|awaiting)\b", re.I)),
]

KEYWORD_RULES = [  # free-text inference -> UNVERIFIED facts
    ("legal_status", re.compile(r"\b(litigation|dispute|writ|court|tribunal|stay)\b", re.I), LEGAL_VALUES),
    ("compensation_status", re.compile(r"\b(compensation|award)\b", re.I), COMP_VALUES),
    ("clearance_status", re.compile(r"\b(clearance|approval|noc|sanction)\b", re.I), CLEARANCE_VALUES),
]

PCT_RULES = [
    ("compensation_disbursed_pct", re.compile(r"(?:disbursed|paid)[^.\n%]{0,40}?" + PERCENT + r"|" + PERCENT +
                                              r"[^.\n]{0,40}?(?:disbursed|paid)", re.I)),
    ("rr_progress_pct", re.compile(r"\b(?:r\s*&\s*r|rehabilitation|resettlement)\b[^.\n%]{0,60}?" + PERCENT, re.I)),
    ("project_progress_pct", re.compile(r"\b(?:project|civil|physical|construction)\s+progress\b[^.\n%]{0,40}?" + PERCENT, re.I)),
]
DATE_RULES = [
    ("notification_date", re.compile(r"\bnotifi\w*[^.\n]{0,50}?" + DATE, re.I)),
    ("hearing_date", re.compile(r"\b(?:hearing|next date|listed)\b[^.\n]{0,50}?" + DATE, re.I)),
    ("deadline_date", re.compile(r"\b(?:deadline|last date|due by|due date)\b[^.\n]{0,50}?" + DATE, re.I)),
]
LABEL_FIELD = {
    "legal": ("legal_status", LEGAL_VALUES), "litigation": ("legal_status", LEGAL_VALUES),
    "compensation": ("compensation_status", COMP_VALUES), "award": ("compensation_status", COMP_VALUES),
    "approval": ("clearance_status", CLEARANCE_VALUES), "clearance": ("clearance_status", CLEARANCE_VALUES),
    "r": ("rr_status", RR_VALUES), "rehabilitation": ("rr_status", RR_VALUES),
}


def normalize_case_ref(number: str) -> str:
    return f"#{int(number):04d}"


def normalize_survey(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|and|&)\s*", text)
    return [p.strip().upper() for p in parts if p.strip()]


def _classify(value: str, table: list[tuple[str, re.Pattern]]) -> str | None:
    for label, pattern in table:
        if pattern.search(value):
            return label
    return None


def _amount_cr(number: str, unit: str | None) -> float | None:
    try:
        n = float(number.replace(",", ""))
    except ValueError:
        return None
    unit = (unit or "").lower()
    if unit.startswith("cr"):
        return round(n, 4)
    if unit.startswith(("lakh", "lac", "l")):
        return round(n / 100, 4)
    return round(n / 1e7, 4)  # plain rupees


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@dataclass
class ChunkOut:
    chunk_id: str
    page: int
    text: str
    case_ids: list[str]


@dataclass
class _Section:
    case_ref: str | None
    lines: list[str] = field(default_factory=list)


def _sections(lines: list[str], carried: str | None) -> list[_Section]:
    """Split a page into case sections: a line mentioning exactly one case ref
    starts that case's section. Lines mentioning several refs belong to none."""
    sections = [_Section(carried)]
    for line in lines:
        refs = {normalize_case_ref(m) for m in CASE_REF.findall(line)}
        if len(refs) == 1:
            ref = next(iter(refs))
            if ref != sections[-1].case_ref:
                sections.append(_Section(ref))
        elif len(refs) > 1:
            sections.append(_Section(None))  # ambiguous line: facts here are not attached
        sections[-1].lines.append(line)
    return [s for s in sections if s.lines]


def _chunk_page(document_id: str, page: int, text: str, words_per_chunk: int, overlap: int,
                carried: str | None, single_case: str | None) -> list[ChunkOut]:
    """Chunk one page, never mixing two case sections in one chunk."""
    chunks: list[ChunkOut] = []
    lines = [ln for ln in text.split("\n") if ln.strip()]
    for section in _sections(lines, carried):
        default = section.case_ref or (single_case if carried is None else None)
        words = " ".join(section.lines).split()
        start = 0
        while start < len(words):
            body = " ".join(words[start:start + words_per_chunk])
            refs = sorted({normalize_case_ref(m) for m in CASE_REF.findall(body)} | ({default} if default else set()))
            chunks.append(ChunkOut(f"{document_id}-p{page}-c{len(chunks) + 1}", page, body, refs))
            if start + words_per_chunk >= len(words):
                break
            start += max(1, words_per_chunk - overlap)
    return chunks


def _line_chunk(line: str, chunks: list[ChunkOut]) -> str | None:
    probe = " ".join(line.split()[:8])
    for c in chunks:
        if probe and probe in c.text:
            return c.chunk_id
    return chunks[0].chunk_id if chunks else None


def _facts_for_page(document_id: str, filename: str, page: int, text: str, chunks: list[ChunkOut],
                    carried: str | None, single_case: str | None,
                    method: str = "rule:pattern") -> tuple[list[Fact], str | None]:
    facts: list[Fact] = []
    lines = [ln for ln in text.split("\n") if ln.strip()]

    def add(field_name: str, value: str, normalized, line: str, case_ref: str | None, method_valid: bool,
            parcel: str | None = None, source_date: str | None = None) -> None:
        digest = hashlib.sha1(f"{document_id}|{page}|{field_name}|{normalized}|{line}".encode()).hexdigest()[:12]
        facts.append(Fact(
            fact_id=f"F-{digest}", field=field_name, value=value.strip()[:200], normalized_value=normalized,
            case_id=case_ref, parcel_id=parcel, extraction_method=method,
            validation_status=ValidationStatus.VALIDATED if method_valid else ValidationStatus.UNVERIFIED,
            provenance=DocumentProvenance(document_id=document_id, filename=filename, page=page,
                                          chunk_id=_line_chunk(line, chunks), snippet=line.strip()[:300]),
            source_date=source_date,
        ))

    last_case = carried
    for section in _sections(lines, carried):
        case_ref = section.case_ref or (single_case if section.case_ref is None and carried is None else None)
        if section.case_ref:
            last_case = section.case_ref
        for line in section.lines:
            for m in CASE_REF.finditer(line):
                ref = normalize_case_ref(m.group(1))
                if ref == section.case_ref:
                    add("case_id", m.group(0), ref, line, ref, True)
            for m in SURVEY.finditer(line):
                for sn in normalize_survey(m.group(1)):
                    add("survey_numbers", sn, sn, line, case_ref, True)
            for m in PARCEL.finditer(line):
                pid = m.group(1).upper().rstrip(".")
                add("parcel_id", pid, pid, line, case_ref, True, parcel=pid)
            for m in VILLAGE.finditer(line):
                add("village", m.group(1), m.group(1).strip().title(), line, case_ref, True)
            for m in DISTRICT.finditer(line):
                add("district", m.group(1), m.group(1).strip().title(), line, case_ref, True)
            for m in AREA.finditer(line):
                add("area_hectares", m.group(0), float(m.group(1)), line, case_ref, True)

            labelled = LABELLED.match(line)
            if labelled:
                key = re.split(r"[\s&]+", labelled.group("label").lower())[0]
                field_name, table = LABEL_FIELD[key]
                normalized = _classify(labelled.group("value"), table)
                if normalized:
                    add(field_name, labelled.group("value"), normalized, line, case_ref, True)
            else:
                for field_name, trigger, table in KEYWORD_RULES:
                    if trigger.search(line):
                        normalized = _classify(line, table)
                        if normalized:
                            add(field_name, line, normalized, line, case_ref, False)

            if re.search(r"\b(compensation|award)\b", line, re.I):
                for m in AMOUNT.finditer(line):
                    cr = _amount_cr(m.group(1), m.group(2))
                    if cr is not None:
                        add("compensation_amount_cr", m.group(0), cr, line, case_ref, True)
            for field_name, pattern in PCT_RULES:
                m = pattern.search(line)
                if m:
                    pct = float(next(g for g in m.groups() if g is not None))
                    if 0 <= pct <= 100:
                        add(field_name, m.group(0), pct, line, case_ref, True)
            for field_name, pattern in DATE_RULES:
                m = pattern.search(line)
                if m:
                    add(field_name, m.group(1), m.group(1), line, case_ref, True, source_date=m.group(1))
    return facts, last_case


def _open(path: Path):
    import pymupdf

    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise PermanentAgentError("PDF_INVALID", "The file is not a PDF.", "Upload a valid, selectable-text PDF.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001
        raise PermanentAgentError("PDF_CORRUPT", "The PDF is damaged and could not be opened.",
                                  "Re-export the PDF from its source and upload it again.") from None
    if doc.needs_pass:
        raise PermanentAgentError("PDF_ENCRYPTED", "The PDF is password-protected.", "Upload an unprotected copy.")
    if doc.page_count == 0:
        if doc.is_repaired:  # MuPDF "repaired" a broken file into nothing
            raise PermanentAgentError("PDF_CORRUPT", "The PDF is damaged and no pages could be recovered.",
                                      "Re-export the PDF from its source and upload it again.")
        raise PermanentAgentError("PDF_EMPTY", "The PDF has no pages.", "Upload a PDF with content.")
    if doc.page_count > get_settings().max_pdf_pages:
        raise PermanentAgentError("PDF_TOO_LARGE", f"The PDF has more than {get_settings().max_pdf_pages} pages.",
                                  "Split the document and upload the parts.")
    return doc


def extract_document(document_id: str, filename: str, path: Path, mode: str = "text",
                     only_pages: list[int] | None = None) -> tuple[PdfDocumentResult, list[ChunkOut]]:
    """Process one PDF. `mode="blocks"` is the alternative reading order used for
    targeted page re-extraction. Raises PermanentAgentError for invalid input."""
    faults.check("pdf_agent")
    if faults.is_active("pdf_transient") or (faults.is_active("pdf_flaky") and faults.hit("pdf_flaky") == 1):
        raise faults.InjectedTransientFault("injected transient PDF fault")
    settings = get_settings()
    if faults.is_active("pdf_timeout"):
        import time

        time.sleep(settings.agent_timeout_s + 0.5)
    doc = _open(path)

    page_texts: dict[int, str] = {}
    reports: list[PageReport] = []
    ocr_errors: set[str] = set()
    ocr_skipped: list[int] = []
    for index, page in enumerate(doc):
        number = index + 1
        if only_pages and number not in only_pages:
            continue
        if mode == "blocks":
            blocks = page.get_text("blocks", sort=True)
            raw = "\n".join(b[4] for b in blocks if b[6] == 0)
        else:
            raw = page.get_text("text", sort=True)
        text = clean_text(raw)
        usable = sum(ch.isalnum() for ch in text) >= settings.min_page_chars
        engine = None
        if not usable:
            if sum(1 for r in reports if r.ocr_engine) >= settings.ocr_max_pages:
                ocr_skipped.append(number)
            else:
                try:
                    ocr_text, engine = ocr_page(page)
                    text = clean_text(ocr_text)
                    usable = sum(ch.isalnum() for ch in text) >= settings.min_page_chars
                except OcrUnavailable as exc:
                    ocr_errors.add(str(exc))
        reports.append(PageReport(page=number, chars=len(text), usable=usable, ocr_engine=engine if usable else None))
        if usable:
            page_texts[number] = text
    page_count = doc.page_count
    doc.close()

    if not page_texts:
        detail = f" OCR could not read it ({'; '.join(sorted(ocr_errors))})." if ocr_errors else " OCR found no readable text."
        return PdfDocumentResult(
            document_id=document_id, filename=filename, state=AgentState.NEEDS_OCR, page_count=page_count,
            pages=reports, error=ErrorInfo(code="NEEDS_OCR", stage="pdf_agent",
                                           message="The PDF has no selectable text (it looks scanned)." + detail,
                                           remediation="Install rapidocr or configure GEMINI_API_KEY for OCR, "
                                                       "or upload a text-based PDF."),
        ), []

    all_refs = sorted({normalize_case_ref(m) for t in page_texts.values() for m in CASE_REF.findall(t)})
    single_case = all_refs[0] if len(all_refs) == 1 else None
    chunks: list[ChunkOut] = []
    facts: list[Fact] = []
    carried: str | None = None
    for report in reports:
        text = page_texts.get(report.page)
        if text is None:
            continue
        page_chunks = _chunk_page(document_id, report.page, text, settings.chunk_words, settings.chunk_overlap_words,
                                  carried, single_case)
        method = f"ocr:{report.ocr_engine}+rule:pattern" if report.ocr_engine else "rule:pattern"
        page_facts, carried = _facts_for_page(document_id, filename, report.page, text, page_chunks, carried, single_case,
                                              method)
        report.chunk_ids = [c.chunk_id for c in page_chunks]
        report.fact_count = len(page_facts)
        chunks.extend(page_chunks)
        facts.extend(page_facts)

    # De-duplicate identical facts (same field/value/page/line).
    unique = {f.fact_id: f for f in facts}
    warnings = []
    unusable = [r.page for r in reports if not r.usable]
    if unusable:
        warnings.append(f"Pages without readable text were skipped: {', '.join(map(str, unusable))}.")
    ocr_read = [r.page for r in reports if r.ocr_engine]
    if ocr_read:
        engines = ", ".join(sorted({r.ocr_engine for r in reports if r.ocr_engine}))
        warnings.append(f"Pages read by OCR ({engines}): {', '.join(map(str, ocr_read))}. "
                        "Check OCR-derived values against the scan.")
    if ocr_skipped:
        warnings.append(f"OCR page limit ({settings.ocr_max_pages}) reached; pages not OCR'd: "
                        f"{', '.join(map(str, ocr_skipped))}.")
    unattached = sum(1 for f in unique.values() if f.case_id is None and f.field != "case_id")
    if unattached:
        warnings.append(f"{unattached} extracted fact(s) could not be tied to a single case and were left unattached.")
    return PdfDocumentResult(
        document_id=document_id, filename=filename,
        state=AgentState.PARTIAL if unusable else AgentState.SUCCEEDED,
        page_count=page_count, pages=reports, facts=list(unique.values()), case_ids_found=all_refs,
        chunk_count=len(chunks), warnings=warnings,
    ), chunks
