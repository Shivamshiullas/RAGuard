"""Typed schemas for agents, evidence, jobs, cases, predictions and the API.

Identifiers are always distinct fields: project_id, corridor_id, case_id,
parcel_id, document_id, map_id, chunk_id, feature_id and job_id.
Missing information stays None/"UNKNOWN"; absence of evidence is never "NO".
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


class AgentState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"  # some inputs/pages/features valid, others not
    FAILED = "FAILED"
    NEEDS_OCR = "NEEDS_OCR"  # PDF with no selectable text; OCR out of scope
    SKIPPED = "SKIPPED"  # no inputs of this modality


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StageState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"  # completed with a fallback (e.g. lexical-only retrieval)
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PredictionStatus(str, Enum):
    NOT_READY = "NOT_READY"
    DEMO_ONLY = "DEMO_ONLY"
    READY = "READY"


class ValidationStatus(str, Enum):
    VALIDATED = "VALIDATED"  # schema-valid, provenance resolvable
    CONFLICT = "CONFLICT"  # another source disagrees
    UNVERIFIED = "UNVERIFIED"  # extracted but weakly supported


UNKNOWN = "UNKNOWN"


class ErrorInfo(Model):
    code: str
    message: str  # user-facing, no stack traces / paths / secrets
    stage: str | None = None
    transient: bool = False
    remediation: str | None = None
    at: str = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Provenance and facts
# ---------------------------------------------------------------------------


class DocumentProvenance(Model):
    kind: Literal["document"] = "document"
    document_id: str
    filename: str
    page: int = Field(ge=1)
    chunk_id: str | None = None
    snippet: str = Field(max_length=600)


class MapProvenance(Model):
    kind: Literal["map"] = "map"
    map_id: str
    filename: str
    layer: str
    feature_id: str
    crs: str | None


FactField = Literal[
    "case_id", "parcel_id", "survey_numbers", "village", "district", "area_hectares",
    "legal_status", "compensation_status", "compensation_amount_cr", "compensation_disbursed_pct",
    "clearance_status", "rr_status", "rr_progress_pct", "project_progress_pct", "notification_date",
    "hearing_date", "deadline_date",
]


class Fact(Model):
    fact_id: str
    field: FactField
    value: str
    normalized_value: str | float | None = None
    case_id: str | None = None
    parcel_id: str | None = None
    extraction_method: Literal["rule:pattern", "gis:attribute", "gis:spatial"]
    validation_status: ValidationStatus = ValidationStatus.VALIDATED
    provenance: DocumentProvenance | MapProvenance
    source_date: str | None = None


# ---------------------------------------------------------------------------
# Agent outputs (validated before checkpointing and before fusion)
# ---------------------------------------------------------------------------


class PageReport(Model):
    page: int
    chars: int
    usable: bool
    chunk_ids: list[str] = Field(default_factory=list)
    fact_count: int = 0


class PdfDocumentResult(Model):
    document_id: str
    filename: str
    state: AgentState
    page_count: int = 0
    pages: list[PageReport] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    case_ids_found: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


class PdfAgentOutput(Model):
    agent: Literal["pdf_agent"] = "pdf_agent"
    state: AgentState
    documents: list[PdfDocumentResult]
    generated_at: str = Field(default_factory=utcnow)

    @field_validator("documents")
    @classmethod
    def facts_reference_own_document(cls, docs: list[PdfDocumentResult]) -> list[PdfDocumentResult]:
        for doc in docs:
            for fact in doc.facts:
                prov = fact.provenance
                if not isinstance(prov, DocumentProvenance) or prov.document_id != doc.document_id:
                    raise ValueError(f"fact {fact.fact_id} has provenance outside document {doc.document_id}")
                if doc.page_count and prov.page > doc.page_count:
                    raise ValueError(f"fact {fact.fact_id} cites page {prov.page} beyond page count")
        return docs


class MapFeature(Model):
    feature_id: str
    map_id: str
    layer: str
    geometry_type: str
    geometry: dict[str, Any]  # GeoJSON geometry in EPSG:4326
    parcel_id: str | None = None
    case_id: str | None = None
    survey_numbers: list[str] = Field(default_factory=list)
    zone: str | None = None
    role: Literal["parcel", "alignment", "other"] = "other"
    area_hectares: float | None = None
    distance_to_alignment_m: float | None = None
    intersects_alignment: bool | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    valid: bool = True
    issues: list[str] = Field(default_factory=list)


class MapResult(Model):
    map_id: str
    filename: str
    state: AgentState
    input_type: Literal["vector", "raster_unreferenced", "pdf_unreferenced"]
    source_crs: str | None = None
    output_crs: str | None = None
    layers: list[str] = Field(default_factory=list)
    feature_count: int = 0
    invalid_feature_count: int = 0
    features: list[MapFeature] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    bounds: list[float] | None = None
    spatial_analysis: Literal["COMPUTED", "UNAVAILABLE"] = "UNAVAILABLE"
    warnings: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


class MapAgentOutput(Model):
    agent: Literal["map_agent"] = "map_agent"
    state: AgentState
    maps: list[MapResult]
    generated_at: str = Field(default_factory=utcnow)

    @field_validator("maps")
    @classmethod
    def features_are_wgs84_geojson(cls, maps: list[MapResult]) -> list[MapResult]:
        for m in maps:
            if m.input_type != "vector" and m.features:
                raise ValueError("unreferenced map inputs cannot carry precise features")
            if m.features and m.output_crs != "EPSG:4326":
                raise ValueError("features must be normalized to EPSG:4326")
            for f in m.features:
                if f.map_id != m.map_id or "type" not in f.geometry or "coordinates" not in f.geometry:
                    raise ValueError(f"feature {f.feature_id} is not valid GeoJSON for map {m.map_id}")
        return maps


# ---------------------------------------------------------------------------
# Retrieval / RAG
# ---------------------------------------------------------------------------


class Evidence(Model):
    evidence_id: str  # E1, E2 … within one answer
    chunk_id: str
    document_id: str
    filename: str
    page: int
    case_ids: list[str] = Field(default_factory=list)
    snippet: str
    score: float
    retrieval: Literal["vector", "lexical", "hybrid"]


class RetrievalInfo(Model):
    state: StageState
    methods: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    coverage: Literal["SUFFICIENT", "INSUFFICIENT", "NONE"] = "NONE"


class RagAnswer(Model):
    question: str
    status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE", "UNAVAILABLE", "EVIDENCE_ONLY"]
    answer: str | None
    claims_unverified: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    retrieval: RetrievalInfo
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fusion, cases, predictions, actions
# ---------------------------------------------------------------------------


class FieldValue(Model):
    """A case field after fusion: the value plus every supporting/contradicting fact."""

    value: str | float | list[str] | None = None  # None = UNKNOWN
    status: Literal["KNOWN", "UNVERIFIED", "UNKNOWN", "CONFLICT"] = "UNKNOWN"
    facts: list[str] = Field(default_factory=list)  # fact_ids
    alternatives: list[str | float] = Field(default_factory=list)


class Conflict(Model):
    conflict_id: str
    case_id: str
    field: str
    values: list[dict[str, Any]]  # [{value, fact_id, source}]
    status: Literal["OPEN", "INVESTIGATED"] = "OPEN"
    note: str | None = None


class UnresolvedMatch(Model):
    match_id: str
    kind: Literal["parcel_to_case", "fact_to_case"]
    key: str  # e.g. survey number that matched several cases
    candidates: list[str]
    source: str
    question: str  # clarification asked of the user
    resolution: str | None = None


class Prediction(Model):
    status: PredictionStatus
    delay_probability: float | None = None
    estimated_delay_days: int | None = None
    model_version: str | None = None
    feature_snapshot_id: str | None = None
    generated_at: str = Field(default_factory=utcnow)
    explanation_ref: str | None = None
    reason: str
    missing_features: list[str] = Field(default_factory=list)


class EvidenceRef(Model):
    fact_id: str | None = None
    document_id: str | None = None
    page: int | None = None
    map_id: str | None = None
    feature_id: str | None = None
    snippet: str | None = None


class Action(Model):
    action_id: str
    case_id: str
    title: str
    rationale: str
    evidence: list[EvidenceRef]
    suggested_owner: str
    priority: Literal["HIGH", "MEDIUM", "MONITOR"]
    workflow_status: Literal["PROPOSED", "IN_REVIEW", "ESCALATED", "RESOLVED", "DISMISSED"] = "PROPOSED"
    requires_human_review: Literal[True] = True


class Case(Model):
    case_id: str  # globally unique: "<project_id>.<case number>", safe in URLs
    case_ref: str  # as written in source records, e.g. "#0472"
    project_id: str
    corridor_id: str | None = None
    parcel_ids: list[str] = Field(default_factory=list)
    is_synthetic: bool = False
    fields: dict[str, FieldValue] = Field(default_factory=dict)
    geometry_refs: list[dict[str, str]] = Field(default_factory=list)  # [{map_id, feature_id}]
    spatial: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)  # conflict_ids
    data_quality: Literal["GOOD", "PARTIAL", "POOR"] = "POOR"
    warnings: list[str] = Field(default_factory=list)
    prediction: Prediction
    actions: list[Action] = Field(default_factory=list)
    illustrative: dict[str, Any] | None = None  # synthetic demo figures, always labelled
    updated_at: str = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class AgentStatus(Model):
    state: AgentState = AgentState.PENDING
    attempts: int = 0
    max_attempts: int = 0
    checkpoint: bool = False
    checkpoint_at: str | None = None
    inputs: list[str] = Field(default_factory=list)
    errors: list[ErrorInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None


class StageStatus(Model):
    state: StageState = StageState.PENDING
    checkpoint: bool = False
    detail: str | None = None
    warnings: list[str] = Field(default_factory=list)


class AuditEvent(Model):
    at: str = Field(default_factory=utcnow)
    step: int
    action: str
    outcome: str
    detail: str | None = None


class Job(Model):
    job_id: str
    project_id: str
    idempotency_key: str
    state: JobState = JobState.QUEUED
    document_ids: list[str] = Field(default_factory=list)
    map_ids: list[str] = Field(default_factory=list)
    pdf_agent: AgentStatus = Field(default_factory=AgentStatus)
    map_agent: AgentStatus = Field(default_factory=AgentStatus)
    retrieval: StageStatus = Field(default_factory=StageStatus)
    fusion: StageStatus = Field(default_factory=StageStatus)
    prediction_readiness: PredictionStatus = PredictionStatus.NOT_READY
    prediction_reason: str | None = None
    steps_used: int = 0
    step_budget: int = 0
    errors: list[ErrorInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    clarifications: list[UnresolvedMatch] = Field(default_factory=list)
    audit: list[AuditEvent] = Field(default_factory=list)
    remediation: str | None = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    resumed_count: int = 0


class JobResults(Model):
    job_id: str
    state: JobState
    complete: bool
    pdf: PdfAgentOutput | None = None
    map: MapAgentOutput | None = None
    cases: list[Case] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    unresolved_matches: list[UnresolvedMatch] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API requests / small responses
# ---------------------------------------------------------------------------


class ProjectIn(Model):
    name: str = Field(min_length=1, max_length=200)
    corridor_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    description: str | None = Field(default=None, max_length=2000)


class Project(Model):
    project_id: str
    name: str
    corridor_id: str
    description: str | None = None
    is_demo: bool = False
    created_at: str = Field(default_factory=utcnow)


class UploadOut(Model):
    project_id: str
    kind: Literal["document", "map"]
    id: str
    filename: str
    size_bytes: int
    sha256: str
    status: Literal["STORED", "QUARANTINED", "DUPLICATE"]
    detail: str | None = None


class JobIn(Model):
    document_ids: list[str] | None = None  # None = all documents in the project
    map_ids: list[str] | None = None


class AskIn(Model):
    question: str = Field(min_length=3, max_length=1000)


class ClarifyIn(Model):
    match_id: str
    case_id: str | None  # None = "none of these"
