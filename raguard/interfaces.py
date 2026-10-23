"""Component interfaces. Later stages add implementations; callers depend only on these."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from .models import Candidate, Chunk, RecoveryEvent, RetrievalResult


@dataclass
class ParseResult:
    chunks: list[Chunk]
    pages: int
    warnings: list[str] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    visual_pages: list[int] = field(default_factory=list)
    failed_pages: list[int] = field(default_factory=list)


@runtime_checkable
class Parser(Protocol):
    def supports(self, filename: str) -> bool: ...

    def parse(self, path: Path, doc_id: str, filename: str, version: str) -> ParseResult: ...


@runtime_checkable
class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def dimension(self) -> int: ...


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, doc_ids: list[str] | None = None, k: int | None = None) -> RetrievalResult: ...


@dataclass
class LLMReply:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    def available(self) -> tuple[bool, str]: ...

    def generate(self, system: str, user: str, images: list[bytes], max_tokens: int) -> LLMReply: ...


@dataclass
class CheckedAnswer:
    text: str  # [E#] markers renumbered to match ``cited``
    cited: list[Candidate]
    warnings: list[str] = field(default_factory=list)
    events: list[RecoveryEvent] = field(default_factory=list)


@runtime_checkable
class AnswerChecker(Protocol):
    def check(self, text: str, evidence: list[Candidate]) -> CheckedAnswer: ...
