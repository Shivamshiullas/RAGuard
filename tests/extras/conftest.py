import pytest

from tests.conftest import make_settings, minilm_available


@pytest.fixture(scope="session")
def rag(tmp_path_factory, sample_dir):
    s = make_settings(tmp_path_factory, 3)
    if not minilm_available(s):
        pytest.skip("MiniLM model not downloaded: run python scripts/download_models.py")
    from raguard.llm import LLMClient
    from raguard.service import RAGuard

    r = RAGuard(s, llm=LLMClient(s, providers=[]))
    r.warm_up()
    for pdf in sorted(sample_dir.glob("*.pdf")):
        out = r.ingest(pdf.name, pdf.read_bytes())
        assert out.ok, out.message
    return r
