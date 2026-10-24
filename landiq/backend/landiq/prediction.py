"""Prediction adapter with an explicit readiness gate.

No labelled historical dataset exists yet, so by default every prediction is
NOT_READY with all numeric fields null. Synthetic demo cases are DEMO_ONLY,
also with null numeric fields (their illustrative figures live elsewhere and
are labelled as such).

READY requires a model bundle (MODEL_PATH, a JSON file) that:
- declares evaluated=true with evaluation metrics and a training date within
  MODEL_MAX_AGE_DAYS,
- lists required features, every one of which is KNOWN (not unknown, not in
  conflict) for the case.
The bundle format is a linear/logistic model, so per-feature contributions
(coefficient x centred value) are the model's exact additive explanation.
No pickle files are loaded.

Without a configured bundle, RISK_SCORER=rules (the default) scores cases with a
transparent rule-based scorecard: fixed, expert-set log-odds weights on the
case's status fields. It is labelled as such everywhere (model_version
"rules-v1"), is not trained on outcomes, and reports no accuracy. A case needs
at least RULES_MIN_FIELDS scored status fields, otherwise it stays NOT_READY.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .config import get_settings
from .schemas import Case, Prediction, PredictionStatus

FEATURE_ENCODERS = {
    "legal_dispute": lambda c: _cat(c, "legal_status", {"DISPUTE": 1, "IN_COURT": 1, "PENDING_SETTLEMENT": 0.5, "CLEAR": 0}),
    "compensation_pending": lambda c: _cat(c, "compensation_status", {"PENDING": 1, "DISPUTED": 1, "IN_PROGRESS": 0.5, "DISBURSED": 0}),
    "clearance_pending": lambda c: _cat(c, "clearance_status", {"DELAYED": 1, "PENDING": 1, "UNDER_REVIEW": 0.5, "CLEARED": 0}),
    "compensation_disbursed_pct": lambda c: _num(c, "compensation_disbursed_pct"),
    "rr_progress_pct": lambda c: _num(c, "rr_progress_pct"),
    "project_progress_pct": lambda c: _num(c, "project_progress_pct"),
}


def _field(case: Case, name: str):
    fv = case.fields.get(name)
    if fv is None or fv.status != "KNOWN" or fv.value is None:
        return None
    return fv.value


def _cat(case: Case, name: str, mapping: dict) -> float | None:
    v = _field(case, name)
    return float(mapping[v]) if v in mapping else None


def _num(case: Case, name: str) -> float | None:
    v = _field(case, name)
    try:
        return float(v) / 100.0 if v is not None else None
    except (TypeError, ValueError):
        return None


class ModelBundle(BaseModel):
    model_version: str
    kind: str = Field(pattern="^logistic$")
    trained_at: str
    evaluated: bool
    evaluation: dict[str, float]
    training_rows: int = Field(gt=0)
    required_features: list[str]
    intercept: float
    coefficients: dict[str, float]
    feature_means: dict[str, float]
    delay_days_per_unit_logit: float | None = None


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> ModelBundle:
    return ModelBundle.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def model_status() -> tuple[ModelBundle | None, str]:
    """(bundle, reason). bundle is None unless a valid, evaluated, fresh model is configured."""
    settings = get_settings()
    if not settings.model_path:
        return None, "No trained model is configured. No labelled historical dataset is available yet."
    path = Path(settings.model_path)
    if not path.is_file():
        return None, "The configured model file was not found."
    try:
        bundle = _load(str(path), path.stat().st_mtime)
    except (ValidationError, ValueError, json.JSONDecodeError):
        return None, "The configured model file is invalid."
    if not bundle.evaluated or not bundle.evaluation:
        return None, "The configured model has not been evaluated."
    unknown = [f for f in bundle.required_features if f not in FEATURE_ENCODERS or f not in bundle.coefficients]
    if unknown:
        return None, f"The model requires unsupported features: {', '.join(unknown)}."
    try:
        trained = datetime.fromisoformat(bundle.trained_at.replace("Z", "+00:00"))
    except ValueError:
        return None, "The model's training date is invalid."
    if trained.tzinfo is None:
        trained = trained.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - trained).days > settings.model_max_age_days:
        return None, "The configured model is stale and must be retrained."
    return bundle, "ready"


RULES_VERSION = "rules-v1"
RULES_REASON = "Rule-based scorecard (expert-set weights, not trained on historical outcomes; no accuracy is claimed)."
RULES_INTERCEPT = -1.5
RULES_WEIGHTS: dict[str, dict[str, float]] = {  # log-odds per status value
    "legal_status": {"IN_COURT": 2.0, "DISPUTE": 1.6, "PENDING_SETTLEMENT": 0.8, "CLEAR": -0.6},
    "compensation_status": {"DISPUTED": 1.3, "PENDING": 1.0, "IN_PROGRESS": 0.4, "DISBURSED": -0.6},
    "clearance_status": {"DELAYED": 1.2, "PENDING": 0.8, "UNDER_REVIEW": 0.5, "CLEARED": -0.5},
    "rr_status": {"PENDING": 0.6, "IN_PROGRESS": 0.3, "COMPLETED": -0.4},
}
RULES_CONFLICT_WEIGHT = 0.8  # contradictory records are themselves a delay risk
RULES_UNVERIFIED_FACTOR = 0.5  # free-text inferences count half
RULES_MIN_FIELDS = 2


def risk_band(probability: float | None) -> str:
    """Same thresholds as the frontend's risk badge."""
    if probability is None:
        return "UNRATED"
    return "HIGH" if probability >= 0.65 else "MEDIUM" if probability >= 0.35 else "LOW"


def rules_active() -> bool:
    settings = get_settings()
    return not settings.model_path and settings.risk_scorer == "rules"


def readiness() -> tuple[PredictionStatus, str]:
    bundle, reason = model_status()
    if bundle:
        return PredictionStatus.READY, f"Model {bundle.model_version} is available."
    if rules_active():
        return PredictionStatus.READY, f"{RULES_VERSION}: {RULES_REASON}"
    return PredictionStatus.NOT_READY, reason


def score_rules(case: Case) -> Prediction:
    contributions: dict[str, float] = {}
    missing: list[str] = []
    for name, weights in RULES_WEIGHTS.items():
        fv = case.fields.get(name)
        if fv is not None and fv.status == "CONFLICT":
            contributions[name] = RULES_CONFLICT_WEIGHT
        elif fv is not None and fv.status in ("KNOWN", "UNVERIFIED") and fv.value in weights:
            factor = 1.0 if fv.status == "KNOWN" else RULES_UNVERIFIED_FACTOR
            contributions[name] = weights[fv.value] * factor
        else:
            missing.append(name)
    if len(contributions) < RULES_MIN_FIELDS:
        return Prediction(status=PredictionStatus.NOT_READY, model_version=RULES_VERSION, missing_features=missing,
                          reason=f"Too little evidence to score: fewer than {RULES_MIN_FIELDS} status fields are known.")
    logit = RULES_INTERCEPT + sum(contributions.values())
    snapshot = hashlib.sha256(json.dumps({k: str(case.fields[k].value) for k in contributions}, sort_keys=True)
                              .encode()).hexdigest()[:16]
    return Prediction(
        status=PredictionStatus.READY, delay_probability=round(1 / (1 + math.exp(-logit)), 4),
        model_version=RULES_VERSION, feature_snapshot_id=snapshot, missing_features=missing,
        explanation_ref=json.dumps({"method": "rule-scorecard", "baseline_logit": RULES_INTERCEPT,
                                    "contributions": {k: round(v, 4) for k, v in contributions.items()}}),
        reason=RULES_REASON,
    )


def predict(case: Case) -> Prediction:
    if case.is_synthetic:
        return Prediction(status=PredictionStatus.DEMO_ONLY,
                          reason="Synthetic demo case. Illustrative figures are not model output.")
    bundle, reason = model_status()
    if bundle is None:
        return score_rules(case) if rules_active() else Prediction(status=PredictionStatus.NOT_READY, reason=reason)
    values: dict[str, float] = {}
    missing = []
    for name in bundle.required_features:
        v = FEATURE_ENCODERS[name](case)
        if v is None:
            missing.append(name)
        else:
            values[name] = v
    if missing:
        return Prediction(status=PredictionStatus.NOT_READY, model_version=bundle.model_version, missing_features=missing,
                          reason="Required features are unknown or in conflict for this case.")
    contributions = {n: bundle.coefficients[n] * (values[n] - bundle.feature_means.get(n, 0.0)) for n in values}
    baseline = bundle.intercept + sum(bundle.coefficients[n] * bundle.feature_means.get(n, 0.0) for n in values)
    logit = baseline + sum(contributions.values())
    prob = 1 / (1 + math.exp(-logit))
    snapshot = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]
    days = round(max(0.0, logit) * bundle.delay_days_per_unit_logit) if bundle.delay_days_per_unit_logit else None
    return Prediction(
        status=PredictionStatus.READY, delay_probability=round(prob, 4), estimated_delay_days=days,
        model_version=bundle.model_version, feature_snapshot_id=snapshot,
        explanation_ref=json.dumps({"method": "linear-additive", "baseline_logit": round(baseline, 4),
                                    "contributions": {k: round(v, 4) for k, v in contributions.items()}}),
        reason="Model output from validated features.",
    )
