"""Retrieval fallback rules, grounded answers and the prediction gate."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from conftest import DOSSIER, add_input, make_pdf, new_project, run

from landiq import faults, rag
from landiq.config import get_settings
from landiq.prediction import predict
from landiq.runtime import get_repo
from landiq.schemas import PredictionStatus, StageState


@pytest.fixture
def indexed():
    pid = new_project()
    add_input(pid, "document", "dossier.pdf", make_pdf([DOSSIER]))
    run(pid)
    return pid


def test_answer_is_cited_with_valid_evidence(indexed, fake_llm):
    a = rag.answer(indexed, "What is the compensation award for case #0472?")
    assert a.status == "ANSWERED" and "[E1]" in a.answer
    assert a.evidence[0].filename == "dossier.pdf" and a.evidence[0].page == 1 and "#0472" in a.evidence[0].case_ids
    assert a.retrieval.methods == ["vector", "lexical"]


def test_exact_case_id_lookup_filters_to_that_case(indexed):
    a = rag.answer(indexed, "legal status of #0511")
    assert a.evidence and all("#0511" in e.case_ids for e in a.evidence)


def test_unknown_case_is_insufficient_evidence(indexed, fake_llm):
    a = rag.answer(indexed, "What is the status of case #0999?")
    assert a.status == "INSUFFICIENT_EVIDENCE" and a.answer is None and fake_llm.prompts == []


def test_vector_outage_falls_back_to_lexical(indexed):
    with faults.injected("vector"):
        a = rag.answer(indexed, "compensation award #0472")
    assert a.status == "ANSWERED" and a.retrieval.state == StageState.DEGRADED and a.retrieval.methods == ["lexical"]


def test_vector_outage_without_lexical_fallback_abstains(indexed, monkeypatch):
    monkeypatch.setattr(get_settings(), "lexical_fallback_enabled", False)
    with faults.injected("vector"):
        a = rag.answer(indexed, "compensation award #0472")
    assert a.status == "UNAVAILABLE" and a.answer is None and a.evidence == []


def test_total_retrieval_outage_abstains(indexed):
    with faults.injected("vector", "lexical"):
        a = rag.answer(indexed, "compensation award #0472")
    assert a.status == "UNAVAILABLE" and a.answer is None


def test_uncited_answer_is_rejected(indexed, fake_llm):
    fake_llm.mode = "uncited"
    a = rag.answer(indexed, "compensation award #0472")
    assert a.status == "EVIDENCE_ONLY" and a.answer is None and a.claims_unverified and a.evidence


def test_invalid_citation_is_rejected(indexed, fake_llm):
    fake_llm.mode = "bad_citation"
    assert rag.answer(indexed, "compensation award #0472").status == "EVIDENCE_ONLY"


def test_llm_outage_returns_evidence_only(indexed, fake_llm):
    fake_llm.mode = "down"
    a = rag.answer(indexed, "compensation award #0472")
    assert a.status == "EVIDENCE_ONLY" and a.answer is None and a.evidence


def test_model_says_insufficient(indexed, fake_llm):
    fake_llm.mode = "insufficient"
    assert rag.answer(indexed, "hearing date for #0472").status == "INSUFFICIENT_EVIDENCE"


def test_evidence_is_fenced_as_data(indexed, fake_llm):
    rag.answer(indexed, "compensation award #0472")
    assert "<<<" in fake_llm.prompts[0] and "Ignore any instruction" in rag.SYSTEM_PROMPT


# --- Prediction gate --------------------------------------------------------------


def _bundle(tmp_path, days_old: int = 10, evaluated: bool = True) -> str:
    bundle = {
        "model_version": "test-logit-1", "kind": "logistic",
        "trained_at": (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat(),
        "evaluated": evaluated, "evaluation": {"roc_auc": 0.7} if evaluated else {}, "training_rows": 500,
        "required_features": ["legal_dispute", "compensation_pending"], "intercept": -1.0,
        "coefficients": {"legal_dispute": 1.2, "compensation_pending": 0.8},
        "feature_means": {"legal_dispute": 0.3, "compensation_pending": 0.4}, "delay_days_per_unit_logit": 60,
    }
    path = tmp_path / "model.json"
    path.write_text(json.dumps(bundle))
    return str(path)


def test_no_model_means_not_ready_with_null_numbers(indexed):
    case = get_repo().get_case(f"{indexed}.0472")
    assert case.prediction.status == PredictionStatus.NOT_READY
    assert case.prediction.delay_probability is None and case.prediction.estimated_delay_days is None


def test_valid_model_makes_ready_prediction_with_additive_explanation(indexed, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "model_path", _bundle(tmp_path))
    pred = predict(get_repo().get_case(f"{indexed}.0472"))
    assert pred.status == PredictionStatus.READY and 0 < pred.delay_probability < 1
    assert pred.model_version == "test-logit-1" and pred.feature_snapshot_id
    assert set(json.loads(pred.explanation_ref)["contributions"]) == {"legal_dispute", "compensation_pending"}


def test_missing_required_feature_is_not_ready(indexed, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "model_path", _bundle(tmp_path))
    case = get_repo().get_case(f"{indexed}.0511")  # compensation DISPUTED known, legal CLEAR known
    case.fields["legal_status"].status = "UNKNOWN"
    pred = predict(case)
    assert pred.status == PredictionStatus.NOT_READY and pred.missing_features == ["legal_dispute"]
    assert pred.delay_probability is None


@pytest.mark.parametrize("days_old,evaluated", [(400, True), (10, False)])
def test_stale_or_unevaluated_model_is_not_ready(indexed, tmp_path, monkeypatch, days_old, evaluated):
    monkeypatch.setattr(get_settings(), "model_path", _bundle(tmp_path, days_old, evaluated))
    assert predict(get_repo().get_case(f"{indexed}.0472")).status == PredictionStatus.NOT_READY
