"""LLM client: runs the configured provider chain and logs token usage for every call.

Stage 1-2: one provider (Gemini), one attempt.
Stage 3 (fallbacks on): bounded retries for retryable errors, then the next provider in the chain;
the caller falls back to an extractive answer when the whole chain fails.
"""
from __future__ import annotations

import logging
import time

from .config import Settings
from .faults import SimulatedFault, faults
from .interfaces import LLMProvider, LLMReply
from .models import RecoveryEvent
from .providers import PROVIDERS, is_retryable
from .usage import UsageLog

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self, s: Settings, providers: list[LLMProvider] | None = None, usage: UsageLog | None = None):
        self.s = s
        self.usage = usage or UsageLog(s.usage_log, s.stage)
        self.status: dict[str, str] = {}
        self.providers: list[LLMProvider] = []
        candidates = providers if providers is not None else [PROVIDERS[n](s) for n in s.llm_chain if n in PROVIDERS]
        for p in candidates:
            ok, why = p.available()
            self.status[p.name] = why if ok else f"unavailable: {why}"
            if ok:
                self.providers.append(p)
        if not s.on("fallbacks"):
            self.providers = self.providers[:1]  # stages 1-2: no provider fallback

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @property
    def description(self) -> str:
        if not self.providers:
            reasons = "; ".join(f"{k}: {v}" for k, v in self.status.items()) or "no provider configured"
            return f"No language model available ({reasons})"
        return " → ".join(f"{p.name} · {p.model}" for p in self.providers)

    def supports_images(self) -> bool:
        if not self.providers:
            return False
        p = self.providers[0]
        return p.name in {"gemini", "anthropic"} or (p.name == "ollama" and self.s.ollama_vision)

    def complete(self, system: str, user: str, images: list[bytes] | None = None, max_tokens: int | None = None,
                 events: list[RecoveryEvent] | None = None, purpose: str = "answer") -> LLMReply:
        events = events if events is not None else []
        max_tokens = max_tokens or self.s.gemini_max_output_tokens
        if not self.providers:
            raise LLMUnavailable(self.description)
        retries = self.s.llm_retries if self.s.on("fallbacks") else 0
        last: Exception | None = None
        for i, p in enumerate(self.providers):
            for attempt in range(retries + 1):
                t0 = time.monotonic()
                try:
                    if self.s.on("fault_injection"):
                        faults.before_llm()
                    reply = p.generate(system, user, images or [], max_tokens)
                    ms = (time.monotonic() - t0) * 1000
                    self.usage.record(reply, purpose=purpose, ok=True, latency_ms=ms)
                    events.append(RecoveryEvent("llm", "ok", f"{p.name} ({reply.model}) answered", ms,
                                                faults.is_on("llm_down")))
                    return reply
                except Exception as e:
                    ms = (time.monotonic() - t0) * 1000
                    last = e
                    self.usage.record(getattr(e, "reply", None), purpose=purpose, ok=False, latency_ms=ms,
                                      provider=p.name, model=p.model, error=f"{type(e).__name__}: {e}")
                    retrying = attempt < retries and is_retryable(e)
                    events.append(RecoveryEvent("llm", "retry" if retrying else "failed",
                                                f"{p.name}: {type(e).__name__}: {str(e)[:200]}", ms,
                                                isinstance(e, SimulatedFault)))
                    if not retrying:
                        break
                    time.sleep(self.s.backoff_base_s * 2 ** attempt)
            if i + 1 < len(self.providers):
                events.append(RecoveryEvent("llm", "fallback", f"switching to {self.providers[i + 1].name}"))
        raise LLMUnavailable(f"all language model providers failed: {type(last).__name__}: {last}")
