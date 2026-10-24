"""OCR for scanned PDFs and the rule-based risk scorecard."""

from __future__ import annotations

import pytest
from conftest import DOSSIER, add_input, make_pdf, make_scanned_pdf, new_project, run

from landiq import config, faults, llm, ocr
from landiq.pdf_agent import extract_document
from landiq.prediction import RULES_VERSION, predict, readiness, risk_band
from landiq.runtime import get_repo
from landiq.schemas import AgentState, Case, FieldValue, JobState, Prediction, PredictionStatus


def _scan(text: str) -> bytes:
    import pymupdf

    src = pymupdf.open()
    src.new_page().insert_textbox(pymupdf.Rect(50, 50, 545, 800), text, fontsize=12)
    png = src[0].get_pixmap(dpi=150).tobytes("png")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=png)
    return doc.tobytes()


def _settings(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()


def _pdf(tmp_path, data: bytes):
    path = tmp_path / "scan.pdf"
    path.write_bytes(data)
    return extract_document("D1", "scan.pdf", path)


# --- OCR -----------------------------------------------------------------------


def test_assemble_lines_joins_label_and_value_boxes():
    boxes = [
        [[[200, 10], [300, 10], [300, 30], [200, 30]], "Dispute", 0.9],
        [[[10, 12], [150, 12], [150, 31], [10, 31]], "Legal status:", 0.95],
        [[[10, 50], [120, 50], [120, 70], [10, 70]], "Case ID: #0472", 0.97],
        [[[10, 90], [120, 90], [120, 110], [10, 110]], "noise", 0.2],
    ]
    assert ocr.assemble_lines(boxes, 0.5) == "Legal status: Dispute\nCase ID: #0472"


def test_scanned_pdf_is_read_by_local_ocr(tmp_path, monkeypatch):
    pytest.importorskip("rapidocr")
    _settings(monkeypatch, OCR_ENGINES="rapidocr")
    result, chunks = _pdf(tmp_path, _scan("Case ID: #0472\nLegal status: Dispute\nCompensation status: Pending"))
    assert result.state == AgentState.SUCCEEDED and result.case_ids_found == ["#0472"] and chunks
    assert result.pages[0].ocr_engine == "rapidocr"
    facts = {f.field: f for f in result.facts}
    assert facts["legal_status"].normalized_value == "DISPUTE"
    assert facts["legal_status"].extraction_method == "ocr:rapidocr+rule:pattern"
    assert any("read by OCR" in w for w in result.warnings)


def test_ocr_falls_back_to_vision_llm(tmp_path, monkeypatch, fake_llm):
    _settings(monkeypatch, OCR_ENGINES="rapidocr,llm")
    monkeypatch.setitem(ocr.ENGINES, "rapidocr", lambda png: (_ for _ in ()).throw(RuntimeError("model missing")))
    monkeypatch.setattr(fake_llm, "has_vision", lambda: True, raising=False)
    monkeypatch.setattr(fake_llm, "transcribe_image", lambda *a: "Case ID: #0900\nLegal status: Clear", raising=False)
    result, _ = _pdf(tmp_path, make_scanned_pdf())
    assert result.state == AgentState.SUCCEEDED and result.pages[0].ocr_engine == "llm"
    assert {f.field: f.normalized_value for f in result.facts}["legal_status"] == "CLEAR"


def test_needs_ocr_when_every_engine_fails(tmp_path, monkeypatch):
    _settings(monkeypatch, OCR_ENGINES="rapidocr,llm")
    llm.set_llm(None)
    with faults.injected("ocr"):
        result, chunks = _pdf(tmp_path, make_scanned_pdf())
    assert result.state == AgentState.NEEDS_OCR and not chunks
    assert "OCR could not read it" in result.error.message


def test_ocr_page_limit_is_enforced(tmp_path, monkeypatch):
    _settings(monkeypatch, OCR_ENGINES="rapidocr", OCR_MAX_PAGES="1")
    monkeypatch.setitem(ocr.ENGINES, "rapidocr", lambda png: "Case ID: #0472\nLegal status: Clear")
    import pymupdf

    doc = pymupdf.open(stream=make_scanned_pdf())
    doc.insert_pdf(pymupdf.open(stream=make_scanned_pdf()))
    result, _ = _pdf(tmp_path, doc.tobytes())
    assert result.state == AgentState.PARTIAL and [p.ocr_engine for p in result.pages] == ["rapidocr", None]
    assert any("OCR page limit" in w for w in result.warnings)


# --- Rule-based scorecard -----------------------------------------------------------


def _case(**fields: tuple[str, object]) -> Case:
    return Case(case_id="P.1", case_ref="#0001", project_id="P",
                fields={k: FieldValue(status=s, value=v) for k, (s, v) in fields.items()},
                prediction=Prediction(status=PredictionStatus.NOT_READY, reason="pending"))


def test_scorecard_is_default_and_labelled(monkeypatch):
    _settings(monkeypatch, RISK_SCORER="rules")
    status, reason = readiness()
    assert status == PredictionStatus.READY and RULES_VERSION in reason and "not trained" in reason
    p = predict(_case(legal_status=("KNOWN", "DISPUTE"), compensation_status=("KNOWN", "PENDING"),
                      clearance_status=("KNOWN", "DELAYED")))
    assert p.status == PredictionStatus.READY and p.model_version == RULES_VERSION
    assert risk_band(p.delay_probability) == "HIGH" and p.estimated_delay_days is None
    assert p.missing_features == ["rr_status"]


def test_scorecard_weights_unverified_and_conflicts(monkeypatch):
    _settings(monkeypatch, RISK_SCORER="rules")
    import json

    p = predict(_case(legal_status=("CONFLICT", None), compensation_status=("UNVERIFIED", "PENDING")))
    contrib = json.loads(p.explanation_ref)["contributions"]
    assert contrib == {"legal_status": 0.8, "compensation_status": 0.5}
    low = predict(_case(legal_status=("KNOWN", "CLEAR"), compensation_status=("KNOWN", "DISBURSED"),
                        clearance_status=("KNOWN", "CLEARED"), rr_status=("KNOWN", "COMPLETED")))
    assert risk_band(low.delay_probability) == "LOW"


def test_scorecard_needs_minimum_evidence(monkeypatch):
    _settings(monkeypatch, RISK_SCORER="rules")
    p = predict(_case(legal_status=("KNOWN", "CLEAR")))
    assert p.status == PredictionStatus.NOT_READY and p.delay_probability is None


def test_configured_model_path_disables_scorecard_fallback(monkeypatch, tmp_path):
    _settings(monkeypatch, RISK_SCORER="rules", MODEL_PATH=str(tmp_path / "missing.json"))
    assert readiness()[0] == PredictionStatus.NOT_READY
    assert predict(_case(legal_status=("KNOWN", "DISPUTE"), compensation_status=("KNOWN", "PENDING"))).status \
        == PredictionStatus.NOT_READY


def test_pipeline_scores_cases_and_rescore_updates_stored_cases(monkeypatch):
    pid = new_project()
    add_input(pid, "document", "dossier.pdf", make_pdf([DOSSIER]))
    job = run(pid)
    assert job.state == JobState.SUCCEEDED
    assert get_repo().get_case(f"{pid}.0472").prediction.status == PredictionStatus.NOT_READY
    _settings(monkeypatch, RISK_SCORER="rules")
    assert get_repo().rescore_cases(predict) >= 1
    case = get_repo().get_case(f"{pid}.0472")
    assert case.prediction.status == PredictionStatus.READY and case.prediction.model_version == RULES_VERSION
    assert get_repo().rescore_cases(predict) == 0  # idempotent
