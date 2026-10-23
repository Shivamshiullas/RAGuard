"""LLM access through a provider chain (Gemini and/or Ollama).

Each provider gets bounded retries with a timeout. A provider that fails is
skipped for a short cool-down so a missing local Ollama does not slow every
request. If every provider fails, `LLMUnavailable` is raised and callers fall
back to evidence-only answers; nothing is ever invented in that case.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from . import faults
from .config import Settings, get_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

COOL_DOWN_S = 120.0
HEALTH_CACHE_S = 30.0
MODEL_COOL_DOWN_S = 120.0


class LLMUnavailable(RuntimeError):
    """Every configured provider failed or returned unusable output."""


class _Provider:
    name = ""

    def __init__(self, settings: Settings):
        self.settings = settings

    def configured(self) -> bool:
        raise NotImplementedError

    def supports_vision(self) -> bool:
        return False

    def complete(self, prompt: str, system: str | None, json_mode: bool, image: bytes | None, image_mime: str) -> str:
        raise NotImplementedError

    def ping(self) -> bool:
        return self.configured()


class GeminiProvider(_Provider):
    name = "gemini"

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._client = None
        # Models that just timed out / were overloaded are skipped for a while.
        self._model_down_until: dict[str, float] = {}

    def configured(self) -> bool:
        return bool(self.settings.gemini_api_key)

    def supports_vision(self) -> bool:
        return True

    def _get_client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.settings.gemini_api_key,
                http_options=types.HttpOptions(timeout=int(self.settings.llm_timeout_s * 1000)),
            )
        return self._client

    def complete(self, prompt, system, json_mode, image, image_mime):
        from google.genai import types

        client = self._get_client()
        contents: list = [prompt]
        if image is not None:
            contents = [types.Part.from_bytes(data=image, mime_type=image_mime), prompt]
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.settings.gemini_temperature,
            max_output_tokens=self.settings.gemini_max_output_tokens,
            response_mime_type="application/json" if json_mode else None,
        )
        last_error: Exception | None = None
        models = [self.settings.gemini_model]
        if self.settings.gemini_fallback_model and self.settings.gemini_fallback_model not in models:
            models.append(self.settings.gemini_fallback_model)
        available = [m for m in models if self._model_down_until.get(m, 0) <= time.monotonic()] or models[-1:]
        for model in available:
            try:
                response = client.models.generate_content(model=model, contents=contents, config=config)
                text = response.text or ""
                if text.strip():
                    return text
                last_error = RuntimeError(f"empty response from {model}")
            except Exception as exc:  # noqa: BLE001 - provider errors are varied
                last_error = exc
                log.warning("Gemini model %s failed: %s", model, str(exc)[:200])
                if len(available) > 1:
                    self._model_down_until[model] = time.monotonic() + MODEL_COOL_DOWN_S
        raise RuntimeError(f"gemini failed: {last_error}")


class OllamaProvider(_Provider):
    name = "ollama"

    def configured(self) -> bool:
        return bool(self.settings.ollama_host and self.settings.ollama_model)

    def supports_vision(self) -> bool:
        return bool(self.settings.ollama_vision_model)

    def complete(self, prompt, system, json_mode, image, image_mime):
        model = self.settings.ollama_vision_model if image is not None else self.settings.ollama_model
        user: dict = {"role": "user", "content": prompt}
        if image is not None:
            user["images"] = [base64.b64encode(image).decode("ascii")]
        messages = ([{"role": "system", "content": system}] if system else []) + [user]
        body: dict = {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0.1}}
        if json_mode:
            body["format"] = "json"
        resp = httpx.post(
            f"{self.settings.ollama_host.rstrip('/')}/api/chat", json=body, timeout=self.settings.llm_timeout_s
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def ping(self) -> bool:
        try:
            resp = httpx.get(f"{self.settings.ollama_host.rstrip('/')}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False


_PROVIDER_TYPES = {"gemini": GeminiProvider, "ollama": OllamaProvider}


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.providers: list[_Provider] = [
            _PROVIDER_TYPES[name](self.settings) for name in self.settings.llm_providers if name in _PROVIDER_TYPES
        ]
        self._down_until: dict[str, float] = {}
        self._health_cache: dict[str, tuple[bool, float]] = {}
        self._lock = threading.Lock()

    # -- public API ---------------------------------------------------------

    def generate(self, prompt: str, system: str | None = None) -> str:
        return self._run(prompt, system, json_mode=False, image=None, image_mime="")

    def generate_json(self, prompt: str, model: type[T], system: str | None = None) -> T:
        """Generate JSON and validate it. Invalid output counts as a provider failure."""

        def parse(text: str) -> T:
            return model.model_validate(_extract_json(text))

        return self._run(prompt, system, json_mode=True, image=None, image_mime="", parser=parse)

    def read_image(self, image: bytes, mime: str, prompt: str) -> str:
        """Vision fallback: transcribe visible text. Only uses vision-capable providers."""
        faults.check("vision")
        return self._run(prompt, None, json_mode=False, image=image, image_mime=mime, vision=True)

    def has_vision(self) -> bool:
        return any(p.configured() and p.supports_vision() for p in self.providers)

    def health(self) -> dict[str, bool]:
        """Provider reachability, cached briefly (a refused local connection
        can take seconds on Windows)."""
        now = time.monotonic()
        result = {}
        for p in self.providers:
            cached = self._health_cache.get(p.name)
            if cached is None or now - cached[1] > HEALTH_CACHE_S:
                cached = (p.ping(), now)
                self._health_cache[p.name] = cached
            result[p.name] = cached[0]
        return result

    # -- internals ----------------------------------------------------------

    def _run(self, prompt, system, json_mode, image, image_mime, parser=None, vision=False):
        faults.check("llm")
        errors: list[str] = []
        for provider in self.providers:
            if not provider.configured() or (vision and not provider.supports_vision()):
                continue
            if self._down_until.get(provider.name, 0) > time.monotonic():
                errors.append(f"{provider.name}: cooling down")
                continue
            for attempt in range(1 + self.settings.llm_retries):
                try:
                    text = provider.complete(prompt, system, json_mode, image, image_mime)
                    return parser(text) if parser else text
                except (ValidationError, ValueError) as exc:
                    errors.append(f"{provider.name}: invalid output")
                    log.warning("LLM %s returned invalid output (attempt %d): %s", provider.name, attempt + 1, exc)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{provider.name}: {type(exc).__name__}")
                    log.warning("LLM %s failed (attempt %d): %s", provider.name, attempt + 1, str(exc)[:200])
                    if isinstance(exc, httpx.ConnectError):
                        # Not running: skip it for a while instead of retrying on every request.
                        with self._lock:
                            self._down_until[provider.name] = time.monotonic() + COOL_DOWN_S
                        break
        raise LLMUnavailable("; ".join(errors) or "no LLM provider configured")


def _extract_json(text: str) -> object:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError("no JSON object in model output") from None


_client: LLMClient | None = None
_client_lock = threading.Lock()


def get_llm() -> LLMClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = LLMClient()
        return _client


def set_llm(client: LLMClient | None) -> None:
    """Replace the shared client (used by tests)."""
    global _client
    with _client_lock:
        _client = client
