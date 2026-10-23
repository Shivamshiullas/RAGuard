import pytest

from tests.conftest import FakeProvider, make_settings


@pytest.fixture(scope="session")
def s1(tmp_path_factory):
    return make_settings(tmp_path_factory, 1, EMBEDDING_BACKEND="hash")


@pytest.fixture(scope="session")
def provider():
    return FakeProvider(["A student needs at least 75% attendance in each course [E1]."])


@pytest.fixture(scope="session")
def rag1(s1, provider, sample_dir):
    from raguard.llm import LLMClient
    from raguard.service import RAGuard

    r = RAGuard(s1, llm=LLMClient(s1, providers=[provider]))
    r.warm_up()
    for pdf in sorted(sample_dir.glob("*.pdf")):
        out = r.ingest(pdf.name, pdf.read_bytes())
        assert out.ok, out.message
    return r
