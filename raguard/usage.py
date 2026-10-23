"""Token usage log: one JSON line per LLM call in logs/usage.jsonl."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .interfaces import LLMReply

# The question being answered and the eval run it belongs to, set by the caller.
_question: ContextVar[str] = ContextVar("question_id", default="")
_run: ContextVar[str] = ContextVar("run_id", default="")
_lock = threading.Lock()


@contextmanager
def tagged(question_id: str = "", run_id: str | None = None):
    """Tag every LLM call inside this block with a question id (and optionally an eval run id)."""
    tq = _question.set(question_id)
    tr = _run.set(run_id) if run_id is not None else None
    try:
        yield
    finally:
        _question.reset(tq)
        if tr is not None:
            _run.reset(tr)


class UsageLog:
    def __init__(self, path: Path, stage: int):
        self.path = path
        self.stage = stage

    def record(self, reply: LLMReply | None, *, purpose: str, ok: bool, latency_ms: float,
               provider: str = "", model: str = "", error: str = "") -> dict[str, Any]:
        entry = {
            "ts": time.time(), "stage": self.stage, "question_id": _question.get(), "run_id": _run.get(),
            "purpose": purpose, "provider": reply.provider if reply else provider,
            "model": reply.model if reply else model, "ok": ok,
            "prompt_tokens": reply.prompt_tokens if reply else None,
            "output_tokens": reply.output_tokens if reply else None,
            "thinking_tokens": reply.thinking_tokens if reply else None,
            "latency_ms": round(latency_ms, 1), "error": error[:300],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def entries(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [e for e in out if run_id is None or e.get("run_id") == run_id]
