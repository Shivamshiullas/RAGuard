"""Settings, storage paths, resource limits and logging.

Values come from environment variables (prefix-free, e.g. GEMINI_API_KEY) or a
`.env` file in the repository root or `landiq/backend/`.
"""

from __future__ import annotations

import logging
import logging.handlers
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
LANDIQ_DIR = BACKEND_DIR.parent
REPO_DIR = LANDIQ_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    storage_dir: Path = BACKEND_DIR / "storage"

    # Upload limits (files larger than these are rejected with 413).
    max_pdf_mb: int = 50
    max_map_mb: int = 100
    max_pdf_pages: int = 500
    max_features: int = 50_000

    # PDF intelligence
    min_page_chars: int = 20  # a page with fewer alphanumerics has no usable text
    chunk_words: int = 220
    chunk_overlap_words: int = 40

    # Retrieval
    vector_enabled: bool = True
    lexical_fallback_enabled: bool = True
    retrieval_top_k: int = 8
    min_vector_similarity: float = 0.25
    retrieval_timeout_s: float = 20.0

    # Chatbot (POST /projects/{id}/chat)
    chat_top_k: int = 6
    # Cosine distance (MiniLM): on-topic questions land ~0.5-0.74, unrelated ones ~0.8+. Farther chunks are dropped.
    chat_max_distance: float = 0.75

    # LLM (used only for grounded RAG answers; never for decisions or tool selection)
    llm_chain: str = "gemini,ollama"
    llm_timeout_s: float = 25.0
    llm_retries: int = 1
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    gemini_fallback_model: str = "gemini-flash-lite-latest"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"

    # Orchestration budgets
    agent_max_attempts: int = 3  # transient failures only
    retry_base_delay_s: float = 0.5
    retry_max_delay_s: float = 8.0
    agent_timeout_s: float = 120.0
    job_max_steps: int = 60
    job_max_seconds: float = 600.0
    job_workers: int = 2
    max_conflict_investigations: int = 10
    max_page_reextractions: int = 5

    # Prediction: path to a trained, evaluated model bundle. Empty = NOT_READY.
    model_path: str = ""
    model_max_age_days: int = 180
    # Without a model bundle: "rules" = transparent rule-based scorecard, "off" = NOT_READY.
    risk_scorer: str = "rules"

    # OCR for pages without selectable text, tried in order: rapidocr (local), llm (vision).
    ocr_engines: str = "rapidocr,llm"
    ocr_dpi: int = 200
    ocr_max_pages: int = 20  # ~3 s/page locally; keep within AGENT_TIMEOUT_S
    ocr_min_confidence: float = 0.8  # lower-confidence lines are usually garbled; drop them

    # Comma-separated fault injection: pdf_agent,map_agent,vector,lexical,llm,fusion,
    # pdf_transient,map_transient,pdf_invalid_output,map_invalid_output,pdf_timeout
    faults: str = ""
    # Allow switching faults at runtime from the UI (PUT /api/v1/faults). Local demo setting.
    allow_fault_injection: bool = True

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def quarantine_dir(self) -> Path:
        return self.storage_dir / "quarantine"

    @property
    def chroma_dir(self) -> Path:
        return self.storage_dir / "chroma"

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "landiq.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.storage_dir / "logs"

    @property
    def llm_providers(self) -> list[str]:
        return [p.strip().lower() for p in self.llm_chain.split(",") if p.strip()]

    def ensure_dirs(self) -> None:
        for path in (self.storage_dir, self.uploads_dir, self.quarantine_dir, self.chroma_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def configure_logging(settings: Settings) -> None:
    """Console gets short lines; the protected log file keeps full detail.
    Document contents are never logged."""
    root = logging.getLogger()
    if getattr(root, "_landiq_configured", False):
        return
    root.setLevel(settings.log_level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    file_handler = logging.handlers.RotatingFileHandler(
        settings.logs_dir / "landiq.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    for noisy in ("httpx", "chromadb", "urllib3", "google_genai", "onnxruntime", "pyogrio", "fiona"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._landiq_configured = True  # type: ignore[attr-defined]
