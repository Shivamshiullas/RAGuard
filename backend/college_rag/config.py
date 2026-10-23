"""Settings, storage paths and logging.

Values come from environment variables or a `.env` file in the repository root
or in `backend/`. Every setting has a safe local default.
"""

from __future__ import annotations

import logging
import logging.handlers
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Storage
    storage_dir: Path = BACKEND_DIR / "storage"

    # LLM providers, tried in order. "gemini" and "ollama" are supported.
    llm_chain: str = "gemini,ollama"
    llm_timeout_s: float = 25.0
    llm_retries: int = 1
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    gemini_fallback_model: str = "gemini-flash-lite-latest"
    gemini_temperature: float = 0.1
    gemini_max_output_tokens: int = 2048
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    # Only set when the Ollama model is confirmed to accept images (e.g. qwen2.5vl:3b).
    ollama_vision_model: str = ""
    vision_fallback: bool = True

    # Chunking and retrieval
    chunk_tokens: int = 500
    chunk_overlap_tokens: int = 75
    top_k: int = 6
    min_similarity: float = 0.25
    retrieval_timeout_s: float = 20.0
    retrieval_retries: int = 1

    # Uploads
    max_upload_mb: int = 25
    max_image_mb: int = 5
    max_image_pixels: int = 40_000_000
    min_ocr_chars: int = 20
    scanned_page_min_chars: int = 30

    # Router and tasks
    max_subtasks: int = 5
    task_concurrency: int = 3
    task_timeout_s: float = 90.0

    # Negative-result cache
    negative_cache_ttl_s: int = 7 * 24 * 3600

    # Admin auth for the prototype. Change these before sharing the app.
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_token_ttl_s: int = 8 * 3600

    # Comma-separated fault injection for manual testing: chroma,embedding,llm,ocr,bm25
    faults: str = ""

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def chroma_dir(self) -> Path:
        return self.storage_dir / "chroma"

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "college_rag.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.storage_dir / "logs"

    @property
    def llm_providers(self) -> list[str]:
        return [p.strip().lower() for p in self.llm_chain.split(",") if p.strip()]

    def ensure_dirs(self) -> None:
        for path in (self.storage_dir, self.uploads_dir, self.chroma_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def configure_logging(settings: Settings) -> None:
    """Console gets short messages; the protected log file keeps full details."""
    root = logging.getLogger()
    if getattr(root, "_college_rag_configured", False):
        return
    root.setLevel(settings.log_level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.logs_dir / "backend.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    for noisy in ("httpx", "chromadb", "urllib3", "google_genai", "onnxruntime"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._college_rag_configured = True  # type: ignore[attr-defined]
