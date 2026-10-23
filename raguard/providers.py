"""LLM providers behind the LLMProvider interface: Gemini (default), Ollama, Claude (optional)."""
from __future__ import annotations

import base64
import os

import requests

from .config import Settings
from .interfaces import LLMReply


class LLMError(RuntimeError):
    """Base class for provider failures that the client understands."""

    retryable = False


class LLMBlocked(LLMError):
    """The provider refused or safety-blocked the request."""


class LLMEmpty(LLMError):
    """The provider returned no usable text."""


class GeminiProvider:
    name = "gemini"

    def __init__(self, s: Settings, client=None):
        self.s = s
        self.model = s.gemini_model
        self._client = client  # injectable for tests

    def available(self) -> tuple[bool, str]:
        try:
            from google import genai  # noqa: F401
        except ImportError:
            return False, "google-genai package not installed"
        if not self.s.gemini_api_key and self._client is None:
            return False, "GEMINI_API_KEY not set"
        return True, f"{self.model}"

    def _get_client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(api_key=self.s.gemini_api_key,
                                        http_options=types.HttpOptions(timeout=int(self.s.llm_timeout_s * 1000)))
        return self._client

    def generate(self, system: str, user: str, images: list[bytes], max_tokens: int) -> LLMReply:
        from google.genai import types

        contents: list = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images]
        contents.append(user)
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.s.gemini_temperature,
            max_output_tokens=min(max_tokens, self.s.gemini_max_output_tokens),
            thinking_config=(types.ThinkingConfig(thinking_budget=self.s.gemini_thinking_budget)
                             if self.s.gemini_thinking_budget is not None else None),
        )
        resp = self._get_client().models.generate_content(model=self.model, contents=contents, config=cfg)
        um = getattr(resp, "usage_metadata", None)
        reply = LLMReply("", self.name, getattr(resp, "model_version", None) or self.model,
                         getattr(um, "prompt_token_count", None), getattr(um, "candidates_token_count", None),
                         getattr(um, "thoughts_token_count", None))
        fb = getattr(resp, "prompt_feedback", None)
        if fb is not None and getattr(fb, "block_reason", None):
            raise _with_reply(LLMBlocked(f"prompt blocked: {fb.block_reason}"), reply)
        finish = None
        if getattr(resp, "candidates", None):
            finish = str(getattr(resp.candidates[0], "finish_reason", "") or "")
        text = (getattr(resp, "text", None) or "").strip()
        if finish and any(r in finish for r in ("SAFETY", "BLOCKLIST", "PROHIBITED", "SPII", "RECITATION")):
            raise _with_reply(LLMBlocked(f"response blocked ({finish})"), reply)
        if not text:
            raise _with_reply(LLMEmpty(f"empty response (finish_reason={finish or 'none'})"), reply)
        reply.text = text
        return reply


def _with_reply(e: LLMError, reply: LLMReply) -> LLMError:
    e.reply = reply  # tokens are still logged for failed calls
    return e


class OllamaProvider:
    name = "ollama"

    def __init__(self, s: Settings):
        self.s = s
        self.model = s.ollama_model

    def available(self) -> tuple[bool, str]:
        try:
            r = requests.get(f"{self.s.ollama_host}/api/tags", timeout=1.5)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return False, f"Ollama not reachable at {self.s.ollama_host}"
        if not any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names):
            return False, f"model '{self.model}' not pulled (ollama pull {self.model})"
        return True, f"{self.model} at {self.s.ollama_host}"

    def generate(self, system: str, user: str, images: list[bytes], max_tokens: int) -> LLMReply:
        msg: dict = {"role": "user", "content": user}
        if images and self.s.ollama_vision:
            msg["images"] = [base64.b64encode(i).decode("ascii") for i in images]
        r = requests.post(f"{self.s.ollama_host}/api/chat", timeout=self.s.llm_timeout_s, json={
            "model": self.model, "stream": False,
            "messages": [{"role": "system", "content": system}, msg],
            "options": {"num_predict": max_tokens, "temperature": 0.1},
        })
        r.raise_for_status()
        data = r.json()
        text = (data.get("message", {}).get("content") or "").strip()
        reply = LLMReply(text, self.name, self.model, data.get("prompt_eval_count"), data.get("eval_count"))
        if not text:
            raise _with_reply(LLMEmpty("empty response from Ollama"), reply)
        return reply


class AnthropicProvider:
    """Optional, off by default. Enable with LLM_CHAIN=gemini,anthropic (or anthropic)."""

    name = "anthropic"

    def __init__(self, s: Settings, client=None):
        self.s = s
        self.model = s.anthropic_model
        self._client = client

    def available(self) -> tuple[bool, str]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "anthropic package not installed"
        if self._client is None and not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            return False, "ANTHROPIC_API_KEY not set"
        return True, self.model

    def generate(self, system: str, user: str, images: list[bytes], max_tokens: int) -> LLMReply:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(timeout=self.s.llm_timeout_s, max_retries=0)
        content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                            "data": base64.standard_b64encode(i).decode("ascii")}}
                               for i in images]
        content.append({"type": "text", "text": user})
        response = self._client.beta.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"}, output_config={"effort": self.s.anthropic_effort},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        usage = getattr(response, "usage", None)
        reply = LLMReply("", self.name, self.model, getattr(usage, "input_tokens", None),
                         getattr(usage, "output_tokens", None))
        if response.stop_reason == "refusal":
            raise _with_reply(LLMBlocked("the model declined this request"), reply)
        reply.text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not reply.text:
            raise _with_reply(LLMEmpty("empty response"), reply)
        return reply


PROVIDERS = {"gemini": GeminiProvider, "ollama": OllamaProvider, "anthropic": AnthropicProvider}


def is_retryable(e: BaseException) -> bool:
    """Retry only failures that can go away: rate limits, server errors, timeouts, dropped connections."""
    if isinstance(e, LLMError):
        return e.retryable
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code is None and getattr(e, "response", None) is not None:
        code = getattr(e.response, "status_code", None)
    if isinstance(code, int):
        return code in {408, 429, 500, 502, 503, 504}
    return isinstance(e, (TimeoutError, ConnectionError, requests.ConnectionError, requests.Timeout))
