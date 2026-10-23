"""Shared test fixtures. All tests run offline: the LLM is always mocked.

Stage 1 tests use the hash embedder (no model files needed). Stage 3 and extras tests use the
real MiniLM model from ./models and are skipped if it hasn't been downloaded
(python scripts/download_models.py).
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("samples")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_sample_docs.py"), str(out)], check=True,
                   capture_output=True)
    return out


def make_settings(tmp_path_factory, stage: int, **overrides):
    from raguard.config import load_settings

    env = {"RAGUARD_STAGE": str(stage), "RAGUARD_DATA_DIR": str(tmp_path_factory.mktemp(f"data{stage}")),
           "RAGUARD_LOGS_DIR": str(tmp_path_factory.mktemp(f"logs{stage}")), "ADAPTION_API_KEY": "",
           "GEMINI_API_KEY": "", "LLM_CHAIN": "gemini"}
    env.update({k: str(v) for k, v in overrides.items()})
    return load_settings(env)


def minilm_available(s) -> bool:
    from raguard.indexes import EmbedderNotReady, Embedder

    try:
        Embedder(s).load()
        return True
    except EmbedderNotReady:
        return False


class FakeProvider:
    """LLMProvider stand-in with scripted replies or errors."""

    name = "gemini"
    model = "fake-model"

    def __init__(self, replies=None, error: Exception | None = None, prompt_tokens=100, output_tokens=20):
        self.replies = list(replies or ["ok [E1]"])
        self.error = error
        self.calls = []
        self.pt, self.ot = prompt_tokens, output_tokens

    def available(self):
        return True, "fake"

    def generate(self, system, user, images, max_tokens):
        from raguard.interfaces import LLMReply

        self.calls.append({"system": system, "user": user, "images": images, "max_tokens": max_tokens})
        if self.error:
            raise self.error
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return LLMReply(text, self.name, self.model, self.pt, self.ot)


class FakeLLM:
    """Stands in for an LLMClient so answer validation can be tested deterministically."""

    def __init__(self, reply: str = "", fail: bool = False):
        self.reply, self.fail = reply, fail
        self.enabled = True
        self.description = "fake"
        self.calls = []

    def supports_images(self):
        return False

    def complete(self, system, user, images=None, max_tokens=None, events=None, purpose="answer"):
        from raguard.interfaces import LLMReply
        from raguard.llm import LLMUnavailable

        self.calls.append(user)
        if self.fail:
            raise LLMUnavailable("fake failure")
        return LLMReply(self.reply, "fake", "fake-model")


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture
def fake_provider():
    return FakeProvider


@pytest.fixture(autouse=True)
def no_faults():
    from raguard.faults import faults

    faults.clear()
    yield
    faults.clear()
