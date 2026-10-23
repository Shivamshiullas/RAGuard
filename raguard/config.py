"""Central configuration. Every value can be overridden with an environment variable or `.env`.

RAGUARD_STAGE (1, 2 or 3) decides which features are on by default:

  Stage 1  basic RAG: text PDFs, vector retrieval, grounded Gemini answers
  Stage 2  + OCR, tables/figures, selective vision
  Stage 3  + BM25 fusion, retries/timeouts/fallbacks, relevance gate, answer checks, fault injection

Each feature can still be switched individually with FEATURE_<NAME>=1/0.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

FEATURES = (
    "ocr",              # stage 2: OCR scanned pages and image uploads
    "visuals",          # stage 2: tag table/figure chunks, render page images
    "vision",           # stage 2: send selected page images to the LLM
    "vision_parser",    # stage 2 (optional): parse visual pages with the LLM at upload
    "bm25",             # stage 3: independent keyword index fused with vector results
    "fallbacks",        # stage 3: timeouts, retries, circuit breaker, keyword fallback
    "relevance_gate",   # stage 3: abstain before calling the LLM when evidence is weak
    "answer_checks",    # stage 3: citation and number validation
    "fault_injection",  # stage 3: simulated faults (process-wide, demo only)
    "extras",           # not a stage: Data Lab, Adaption, Evaluation pages
)

STAGE_FEATURES = {
    1: set(),
    2: {"ocr", "visuals", "vision"},
    3: {"ocr", "visuals", "vision", "bm25", "fallbacks", "relevance_gate", "answer_checks", "fault_injection"},
}
STAGE_LLM_CHAIN = {1: "gemini", 2: "gemini", 3: "gemini,ollama"}


def _bool(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    stage: int
    features: frozenset[str]
    data_dir: Path
    logs_dir: Path

    # Upload validation
    max_upload_mb: int
    max_pages: int

    # Chunking
    chunk_chars: int
    chunk_overlap: int
    min_page_chars: int  # below this a page is treated as scanned / image-only
    heading_size_ratio: float  # font size vs. body text that marks a heading

    # Embeddings and vector store
    embedding_backend: str  # "onnx-minilm" | "sentence-transformers" | "hash" (tests only)
    embedding_model: str
    models_dir: Path
    chroma_host: str  # empty -> embedded PersistentClient under data_dir
    chroma_port: int
    chroma_collection: str
    top_k: int

    # Stage 3 retrieval controller
    retry_attempts: int  # extra attempts after the first
    backoff_base_s: float
    embed_timeout_s: float
    vector_timeout_s: float
    request_deadline_s: float
    min_cosine: float  # best cosine similarity below this counts as a weak vector result
    min_term_coverage: float  # share of query content words a keyword hit needs
    sufficiency_min_score: float
    strong_cosine_margin: float  # a hit this far above min_cosine is relevant on its own
    weak_match_coverage: float  # coverage a moderate vector hit needs to count
    rrf_k: int

    # OCR / vision
    render_dpi: int

    # Language models
    llm_chain: tuple[str, ...]  # tried in order: gemini, ollama, anthropic
    gemini_api_key: str
    gemini_model: str
    gemini_temperature: float
    gemini_max_output_tokens: int
    gemini_thinking_budget: int | None  # None = model default; stage 1 defaults to 0 (no thinking)
    gemini_thinking_level: str  # for models that use levels (e.g. "minimal"); empty = not set
    anthropic_model: str
    anthropic_effort: str
    ollama_host: str
    ollama_model: str
    ollama_vision: bool
    llm_timeout_s: float
    llm_retries: int
    max_evidence: int  # passages sent to the LLM
    max_images_per_query: int

    # Adaption (extras)
    adaption_api_key: str
    adaption_base_url: str
    adaption_max_rows: int

    def on(self, feature: str) -> bool:
        if feature not in FEATURES:
            raise KeyError(feature)
        return feature in self.features

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

    @property
    def usage_log(self) -> Path:
        return self.logs_dir / "usage.jsonl"

    def ensure_dirs(self) -> None:
        for d in (self.chunks_dir, self.uploads_dir, self.pages_dir, self.chroma_dir, self.datasets_dir,
                  self.eval_dir, self.adaption_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_settings(overrides: Mapping[str, str] | None = None) -> Settings:
    """Build settings from the environment, with optional overrides (used by tests and eval)."""
    env = {**os.environ, **(overrides or {})}

    def get(name: str, default: str) -> str:
        # An empty value in .env (e.g. "GEMINI_THINKING_BUDGET=") means "use the default".
        v = env.get(name)
        return default if v is None or str(v).strip() == "" else str(v).strip()

    stage = int(get("RAGUARD_STAGE", "1"))
    if stage not in STAGE_FEATURES:
        raise ValueError(f"RAGUARD_STAGE must be 1, 2 or 3, not {stage}")
    features = set(STAGE_FEATURES[stage])
    for f in FEATURES:
        v = env.get(f"FEATURE_{f.upper()}")
        if v is not None and v.strip() != "":
            (features.add if _bool(v) else features.discard)(f)

    budget = get("GEMINI_THINKING_BUDGET", "0" if stage == 1 else "")
    s = Settings(
        stage=stage,
        features=frozenset(features),
        data_dir=Path(get("RAGUARD_DATA_DIR", str(ROOT / "data"))),
        logs_dir=Path(get("RAGUARD_LOGS_DIR", str(ROOT / "logs"))),
        max_upload_mb=int(get("MAX_UPLOAD_MB", "25")),
        max_pages=int(get("MAX_PAGES", "300")),
        chunk_chars=int(get("CHUNK_CHARS", "900")),
        chunk_overlap=int(get("CHUNK_OVERLAP", "150")),
        min_page_chars=int(get("MIN_PAGE_CHARS", "40")),
        heading_size_ratio=float(get("HEADING_SIZE_RATIO", "1.15")),
        embedding_backend=get("EMBEDDING_BACKEND", "onnx-minilm"),
        embedding_model=get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        models_dir=Path(get("MODELS_DIR", str(ROOT / "models"))),
        chroma_host=get("CHROMA_HOST", ""),
        chroma_port=int(get("CHROMA_PORT", "8000")),
        chroma_collection=get("CHROMA_COLLECTION", "raguard_chunks"),
        top_k=int(get("TOP_K", "6")),
        retry_attempts=int(get("RETRY_ATTEMPTS", "2")),
        backoff_base_s=float(get("BACKOFF_BASE_S", "0.2")),
        embed_timeout_s=float(get("EMBED_TIMEOUT_S", "3")),
        vector_timeout_s=float(get("VECTOR_TIMEOUT_S", "4")),
        request_deadline_s=float(get("REQUEST_DEADLINE_S", "20")),
        min_cosine=float(get("MIN_COSINE", "0.35")),
        min_term_coverage=float(get("MIN_TERM_COVERAGE", "0.5")),
        sufficiency_min_score=float(get("SUFFICIENCY_MIN_SCORE", "0.4")),
        strong_cosine_margin=float(get("STRONG_COSINE_MARGIN", "0.15")),
        weak_match_coverage=float(get("WEAK_MATCH_COVERAGE", "0.25")),
        rrf_k=int(get("RRF_K", "60")),
        render_dpi=int(get("RENDER_DPI", "130")),
        llm_chain=tuple(p.strip().lower() for p in get("LLM_CHAIN", STAGE_LLM_CHAIN[stage]).split(",") if p.strip()),
        gemini_api_key=get("GEMINI_API_KEY", ""),
        gemini_model=get("GEMINI_MODEL", "gemini-flash-latest"),
        gemini_temperature=float(get("GEMINI_TEMPERATURE", "0.1")),
        gemini_max_output_tokens=int(get("GEMINI_MAX_OUTPUT_TOKENS", "1024")),
        gemini_thinking_budget=int(budget) if budget else None,
        gemini_thinking_level=get("GEMINI_THINKING_LEVEL", ""),
        anthropic_model=get("ANTHROPIC_MODEL", "claude-opus-5-5"),
        anthropic_effort=get("ANTHROPIC_EFFORT", "medium"),
        ollama_host=get("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=get("OLLAMA_MODEL", "qwen2.5vl:3b"),
        ollama_vision=_bool(get("OLLAMA_VISION", "1")),
        llm_timeout_s=float(get("LLM_TIMEOUT_S", "60")),
        llm_retries=int(get("LLM_RETRIES", "1")),
        max_evidence=int(get("MAX_EVIDENCE", "6")),
        max_images_per_query=int(get("MAX_IMAGES_PER_QUERY", "1")),
        adaption_api_key=get("ADAPTION_API_KEY", ""),
        adaption_base_url=get("ADAPTION_BASE_URL", ""),
        adaption_max_rows=int(get("ADAPTION_MAX_ROWS", "500")),
    )
    s.ensure_dirs()
    return s


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
