"""Shared Pydantic models: agent results, router plans and API responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

# ---------------------------------------------------------------------------
# Evidence and agent results
# ---------------------------------------------------------------------------


class Passage(BaseModel):
    """One retrieved chunk with the metadata needed to cite it."""

    chunk_id: str
    doc_id: str
    version: int
    title: str
    filename: str
    page: int
    category: str = ""
    semester: str = ""
    academic_year: str = ""
    effective_date: str = ""
    text: str
    score: float = 0.0


class Source(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    filename: str
    page: int
    title: str = ""
    doc_id: str = ""
    version: int = 1
    snippet: str = ""


AgentName = Literal["text_agent", "image_agent", "general", "router"]
AgentStatus = Literal["success", "partial", "no_evidence", "degraded", "failed"]
RecoveryStatus = Literal["not_needed", "recovered", "failed"]


class AgentResult(BaseModel):
    agent: AgentName
    status: AgentStatus
    answer: str = ""
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    failed_stage: str | None = None
    error_code: str | None = None
    recovery_attempts: int = 0
    recovery_status: RecoveryStatus = "not_needed"
    recovery_method: str | None = None
    # True only when retrieval completed normally and found nothing usable.
    # Outages never set this, so they are never written to the negative cache.
    cacheable_miss: bool = False
    from_negative_cache: bool = False


# ---------------------------------------------------------------------------
# Router plan
# ---------------------------------------------------------------------------

Intent = Literal["general", "college_specific", "multi_task", "unclear", "out_of_scope"]
ExecutionMode = Literal["direct", "parallel", "sequential", "mixed"]


class PlanTask(BaseModel):
    task_id: str
    question: str = Field(min_length=1, max_length=1000)
    category: str | None = None
    semester: str | None = None
    academic_year: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    suggested_agent: Literal["text_agent", "image_agent"] = "text_agent"


class RouterPlan(BaseModel):
    intent: Intent
    requires_rag: bool
    tasks: list[PlanTask] = Field(default_factory=list)
    execution_mode: ExecutionMode = "direct"
    clarification_question: str | None = None
    direct_response: str | None = None

    @field_validator("tasks")
    @classmethod
    def unique_ids(cls, tasks: list[PlanTask]) -> list[PlanTask]:
        ids = [t.task_id for t in tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task ids must be unique")
        return tasks

    @model_validator(mode="after")
    def check_consistency(self) -> RouterPlan:
        ids = {t.task_id for t in self.tasks}
        for task in self.tasks:
            unknown = set(task.dependencies) - ids
            if unknown or task.task_id in task.dependencies:
                raise ValueError(f"task {task.task_id} has invalid dependencies")
        if self.requires_rag and not self.tasks:
            raise ValueError("a RAG plan needs at least one task")
        _assert_acyclic(self.tasks)
        return self


def _assert_acyclic(tasks: list[PlanTask]) -> None:
    deps = {t.task_id: set(t.dependencies) for t in tasks}
    done: set[str] = set()
    while deps:
        ready = [tid for tid, d in deps.items() if d <= done]
        if not ready:
            raise ValueError("task dependencies contain a cycle")
        for tid in ready:
            done.add(tid)
            del deps[tid]


# ---------------------------------------------------------------------------
# API responses (camelCase for the React frontend)
# ---------------------------------------------------------------------------


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


ChatStatus = Literal["general", "success", "partial", "no_evidence", "degraded", "failed", "clarification", "declined"]


class TaskItem(CamelModel):
    task_id: str
    question: str
    status: AgentStatus | Literal["skipped"]
    agent: str


class TaskSummary(CamelModel):
    completed: int = 0
    total: int = 0
    items: list[TaskItem] = Field(default_factory=list)


class RecoveryInfo(CamelModel):
    attempted: bool = False
    method: str | None = None
    status: RecoveryStatus = "not_needed"


class ChatResponse(CamelModel):
    answer: str
    status: ChatStatus
    route: Intent
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tasks: TaskSummary = Field(default_factory=TaskSummary)
    agents: list[str] = Field(default_factory=list)
    recovery: RecoveryInfo = Field(default_factory=RecoveryInfo)
    request_id: str


class DocumentVersionOut(CamelModel):
    version: int
    file_name: str
    file_kind: str
    size_bytes: int
    uploaded_at: str
    stage: str
    failed_at: str | None = None
    error: str | None = None
    ocr_required: bool = False
    chunk_count: int = 0


class DocumentOut(CamelModel):
    id: str
    title: str
    category: str
    semester: str | None = None
    academic_year: str | None = None
    effective_date: str | None = None
    active: bool
    versions: list[DocumentVersionOut]


class HealthOut(CamelModel):
    status: Literal["ok", "degraded"]
    llm: dict[str, bool]
    vector_store: bool
    documents_indexed: int
    kb_generation: int
