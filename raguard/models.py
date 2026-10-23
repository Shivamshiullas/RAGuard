"""Shared data shapes passed between ingestion, retrieval, answering and the Data Lab."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    filename: str
    page: int  # 1-indexed
    text: str
    kind: str = "text"  # text | ocr | table | visual
    image_path: str | None = None  # rendered page image, when one exists
    doc_version: str = ""

    @property
    def citation(self) -> str:
        return f"{self.filename}, p.{self.page}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Chunk":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Candidate:
    chunk: Chunk
    score: float = 0.0  # fused score used for ranking
    vector_similarity: float | None = None
    keyword_score: float | None = None
    term_coverage: float = 0.0
    found_by: list[str] = field(default_factory=list)  # "vector", "keyword", "visual"
    relevant: bool = False


@dataclass
class RecoveryEvent:
    stage: str  # embed | vector | keyword | manifest | relevance | visual | llm | validation
    status: str  # ok | retry | failed | fallback | skipped | weak | abstain
    detail: str
    latency_ms: float = 0.0
    simulated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    query: str
    candidates: list[Candidate]
    events: list[RecoveryEvent]
    mode: str  # hybrid | keyword_fallback | hybrid_recovery | none
    sufficient: bool
    reason: str
    visual_query: bool = False
    latency_ms: float = 0.0

    @property
    def evidence(self) -> list[Candidate]:
        return [c for c in self.candidates if c.relevant]

    @property
    def recovered(self) -> bool:
        return any(e.status in {"fallback", "retry"} for e in self.events)

    @property
    def simulated(self) -> bool:
        return any(e.simulated for e in self.events)


@dataclass
class AnswerResult:
    question: str
    status: str  # answered | abstained | extractive | unverified
    text: str
    cited: list[Candidate]
    retrieval: RetrievalResult
    warnings: list[str] = field(default_factory=list)
    llm_events: list[RecoveryEvent] = field(default_factory=list)
    provider: str = "none"
    latency_ms: float = 0.0
    used_images: list[str] = field(default_factory=list)

    @property
    def all_events(self) -> list[RecoveryEvent]:
        return self.retrieval.events + self.llm_events
