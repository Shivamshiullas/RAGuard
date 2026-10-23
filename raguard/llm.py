"""Replaceable language-model client: Anthropic (Claude), local Ollama, or none.

Every call has a timeout and bounded retries; if the primary provider fails, the next
configured provider is tried. With no provider, callers fall back to extractive answers.
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import Settings
from .faults import SimulatedFault, faults
from .models import RecoveryEvent

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMReply:
    text: str
    provider: str
    model: str


def _b64(path: str) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, s: Settings):
        import anthropic

        self.s = s
        self.model = s.anthropic_model
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(timeout=s.llm_timeout_s, max_retries=0)  # retries handled by LLMClient

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "anthropic package not installed"
        import os

        if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
            return True, "API key configured"
        return False, "ANTHROPIC_API_KEY not set"

    def complete(self, system: str, user: str, images: list[str], max_tokens: int) -> str:
        content: list[dict] = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(p)}}
            for p in images
        ]
        content.append({"type": "text", "text": user})
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"},
            output_config={"effort": self.s.anthropic_effort},
            # Server-side fallback: if a safety classifier declines, the API reroutes the request.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise LLMUnavailable("the model declined this request")
        return "".join(b.text for b in response.content if b.type == "text").strip()


class OllamaProvider:
    name = "ollama"

    def __init__(self, s: Settings):
        self.s = s
        self.model = s.ollama_model

    @staticmethod
    def available(s: Settings) -> tuple[bool, str]:
        try:
            r = requests.get(f"{s.ollama_host}/api/tags", timeout=1.5)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return False, f"Ollama not reachable at {s.ollama_host}"
        if not any(n == s.ollama_model or n.split(":")[0] == s.ollama_model.split(":")[0] for n in names):
            return False, f"model '{s.ollama_model}' not pulled (run: ollama pull {s.ollama_model})"
        return True, f"{s.ollama_model} at {s.ollama_host}"

    def complete(self, system: str, user: str, images: list[str], max_tokens: int) -> str:
        msg: dict = {"role": "user", "content": user}
        if images and self.s.ollama_vision:
            msg["images"] = [_b64(p) for p in images]
        r = requests.post(f"{self.s.ollama_host}/api/chat", timeout=self.s.llm_timeout_s, json={
            "model": self.model, "stream": False,
            "messages": [{"role": "system", "content": system}, msg],
            "options": {"num_predict": max_tokens, "temperature": 0.1},
        })
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


class LLMClient:
    def __init__(self, s: Settings):
        self.s = s
        self.providers: list = []
        self.status: dict[str, str] = {}
        self._configure()

    def _configure(self) -> None:
        want = self.s.llm_provider
        order = {"auto": ["anthropic", "ollama"], "anthropic": ["anthropic", "ollama"],
                 "ollama": ["ollama", "anthropic"], "none": []}.get(want, ["anthropic", "ollama"])
        for name in order:
            if name == "anthropic":
                ok, why = AnthropicProvider.available()
                self.status["anthropic"] = why
                if ok:
                    self.providers.append(AnthropicProvider(self.s))
            elif name == "ollama":
                ok, why = OllamaProvider.available(self.s)
                self.status["ollama"] = why
                if ok:
                    self.providers.append(OllamaProvider(self.s))
        if want == "none":
            self.status["mode"] = "LLM disabled by configuration (LLM_PROVIDER=none)"

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @property
    def description(self) -> str:
        if not self.providers:
            return "No language model configured - extractive answers only"
        p = self.providers[0]
        return f"{p.name} · {p.model}"

    def supports_images(self) -> bool:
        if not self.providers:
            return False
        p = self.providers[0]
        return p.name == "anthropic" or self.s.ollama_vision

    def complete(self, system: str, user: str, images: list[str] | None = None,
                 max_tokens: int = 2000, events: list[RecoveryEvent] | None = None) -> LLMReply:
        events = events if events is not None else []
        if not self.providers:
            raise LLMUnavailable("no language model configured")
        last: Exception | None = None
        for i, p in enumerate(self.providers):
            for attempt in range(self.s.llm_retries + 1):
                t0 = time.monotonic()
                try:
                    faults.before_llm()
                    text = p.complete(system, user, images or [], max_tokens)
                    events.append(RecoveryEvent("llm", "ok", f"{p.name} ({p.model}) answered",
                                                (time.monotonic() - t0) * 1000, faults.is_on("llm_down")))
                    return LLMReply(text, p.name, p.model)
                except Exception as e:
                    last = e
                    sim = isinstance(e, SimulatedFault)
                    retrying = attempt < self.s.llm_retries and not isinstance(e, LLMUnavailable)
                    status = "retry" if retrying else "failed"
                    events.append(RecoveryEvent("llm", status, f"{p.name}: {type(e).__name__}: {str(e)[:200]}",
                                                (time.monotonic() - t0) * 1000, sim))
                    if isinstance(e, LLMUnavailable):
                        break
                    if attempt < self.s.llm_retries:
                        time.sleep(0.5 * (2 ** attempt))
            if i + 1 < len(self.providers):
                events.append(RecoveryEvent("llm", "fallback", f"switching to {self.providers[i + 1].name}"))
        raise LLMUnavailable(f"all language model providers failed: {last}")
