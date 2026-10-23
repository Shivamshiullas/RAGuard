import os
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


@pytest.fixture(scope="session")
def rag(tmp_path_factory, sample_dir):
    os.environ["RAGUARD_DATA_DIR"] = str(tmp_path_factory.mktemp("data"))
    os.environ["LLM_PROVIDER"] = "none"
    os.environ["ADAPTION_API_KEY"] = ""
    from raguard.config import get_settings

    get_settings.cache_clear()
    from raguard.service import RAGuard

    r = RAGuard()
    r.warm_up()
    for pdf in sorted(sample_dir.glob("*.pdf")):
        out = r.ingest(pdf.name, pdf.read_bytes())
        assert out.ok, out.message
    return r


@pytest.fixture(autouse=True)
def no_faults():
    from raguard.faults import faults

    faults.clear()
    yield
    faults.clear()


class FakeLLM:
    """Stands in for a language model so answer validation can be tested deterministically."""

    def __init__(self, reply: str = "", fail: bool = False):
        self.reply, self.fail = reply, fail
        self.enabled = True
        self.description = "fake"
        self.calls = []

    def supports_images(self):
        return False

    def complete(self, system, user, images=None, max_tokens=2000, events=None):
        from raguard.llm import LLMReply, LLMUnavailable

        self.calls.append(user)
        if self.fail:
            raise LLMUnavailable("fake failure")
        return LLMReply(self.reply, "fake", "fake-model")


@pytest.fixture
def fake_llm():
    return FakeLLM
