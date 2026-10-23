"""Central configuration. Every value can be overridden with an environment variable or `.env`."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path

    # Upload validation
    max_upload_mb: int
    max_pages: int

    # Chunking
    chunk_chars: int
    chunk_overlap: int
    min_page_chars: int  # below this a page is treated as scanned / image-only

    # Embeddings and vector store
    embedding_backend: str  # "onnx-minilm" | "sentence-transformers"
    embedding_model: str
    chroma_host: str  # empty -> embedded PersistentClient under data_dir
    chroma_port: int
    chroma_collection: str

    # Retrieval controller
    top_k: int
    retry_attempts: int  # extra attempts after the first
    backoff_base_s: float
    embed_timeout_s: float
    vector_timeout_s: float
    request_deadline_s: float
    vector_min_similarity: float  # cosine similarity a vector hit needs to count as relevant
    min_term_coverage: float  # share of query content words a keyword hit needs
    sufficiency_min_score: float

    # OCR / vision
    ocr_enabled: bool
    render_dpi: int

    # Language model
    llm_provider: str  # "auto" | "anthropic" | "ollama" | "none"
    anthropic_model: str
    anthropic_effort: str
    ollama_host: str
    ollama_model: str
    ollama_vision: bool
    llm_timeout_s: float
    llm_retries: int

    # Adaption
    adaption_api_key: str
    adaption_base_url: str
    adaption_max_rows: int

    @property
    def chunks_dir(self) -> Path:
        return self.data_dir / "chunks"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "pages"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "indexes" / "chroma"

    @property
    def datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def eval_dir(self) -> Path:
        return self.data_dir / "eval_runs"

    @property
    def adaption_dir(self) -> Path:
        return self.data_dir / "adaption"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "registry.json"

    def ensure_dirs(self) -> None:
        for d in (self.chunks_dir, self.uploads_dir, self.pages_dir, self.chroma_dir,
                  self.datasets_dir, self.eval_dir, self.adaption_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings(
        data_dir=Path(_env("RAGUARD_DATA_DIR", str(ROOT / "data"))),
        max_upload_mb=_int("MAX_UPLOAD_MB", 25),
        max_pages=_int("MAX_PAGES", 300),
        chunk_chars=_int("CHUNK_CHARS", 900),
        chunk_overlap=_int("CHUNK_OVERLAP", 150),
        min_page_chars=_int("MIN_PAGE_CHARS", 40),
        embedding_backend=_env("EMBEDDING_BACKEND", "onnx-minilm"),
        embedding_model=_env("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        chroma_host=_env("CHROMA_HOST", ""),
        chroma_port=_int("CHROMA_PORT", 8000),
        chroma_collection=_env("CHROMA_COLLECTION", "raguard_chunks"),
        top_k=_int("TOP_K", 6),
        retry_attempts=_int("RETRY_ATTEMPTS", 2),
        backoff_base_s=_float("BACKOFF_BASE_S", 0.2),
        embed_timeout_s=_float("EMBED_TIMEOUT_S", 8.0),
        vector_timeout_s=_float("VECTOR_TIMEOUT_S", 4.0),
        request_deadline_s=_float("REQUEST_DEADLINE_S", 20.0),
        vector_min_similarity=_float("VECTOR_MIN_SIMILARITY", 0.35),
        min_term_coverage=_float("MIN_TERM_COVERAGE", 0.5),
        sufficiency_min_score=_float("SUFFICIENCY_MIN_SCORE", 0.4),
        ocr_enabled=_bool("OCR_ENABLED", True),
        render_dpi=_int("RENDER_DPI", 130),
        llm_provider=_env("LLM_PROVIDER", "auto").lower(),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-opus-5-5"),
        anthropic_effort=_env("ANTHROPIC_EFFORT", "medium"),
        ollama_host=_env("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=_env("OLLAMA_MODEL", "qwen2.5vl:3b"),
        ollama_vision=_bool("OLLAMA_VISION", True),
        llm_timeout_s=_float("LLM_TIMEOUT_S", 120.0),
        llm_retries=_int("LLM_RETRIES", 1),
        adaption_api_key=_env("ADAPTION_API_KEY", ""),
        adaption_base_url=_env("ADAPTION_BASE_URL", ""),
        adaption_max_rows=_int("ADAPTION_MAX_ROWS", 500),
    )
    s.ensure_dirs()
    return s
