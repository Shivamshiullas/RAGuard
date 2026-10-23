import pytest

from raguard.faults import faults


def _top_source(res):
    c = res.evidence[0].chunk
    return c.filename, c.page


def test_retrieves_relevant_passage(rag):
    res = rag.retrieve("What minimum attendance is required to write the end-semester exam?")
    assert res.sufficient
    assert res.mode == "hybrid"
    top3 = [(c.chunk.filename, c.chunk.page) for c in res.evidence[:3]]
    assert ("Academic_Regulations_2026.pdf", 1) in top3  # page 1 states the 75% rule


@pytest.mark.xfail(strict=True, reason="Stage 3: relevance gate recalibration pending")
def test_unsupported_question_abstains(rag):
    for q in ["What is the hostel fee for international students?", "Who won the football world cup?"]:
        res = rag.retrieve(q)
        assert not res.sufficient, q


def test_document_filter(rag):
    syllabus = next(d["doc_id"] for d in rag.documents() if d["filename"].startswith("CS201"))
    res = rag.retrieve("What is the minimum attendance?", [syllabus])
    assert all(c.chunk.doc_id == syllabus for c in res.candidates)


def test_chromadb_outage_falls_back_to_bm25(rag):
    with faults.scoped(chroma_down=True):
        res = rag.retrieve("What minimum attendance is required to write the end-semester exam?")
    assert res.mode == "keyword_fallback"
    assert res.sufficient
    assert _top_source(res) == ("Academic_Regulations_2026.pdf", 1)
    stages = [(e.stage, e.status) for e in res.events]
    assert ("vector", "retry") in stages and ("vector", "fallback") in stages
    assert all(e.simulated for e in res.events if e.stage == "vector")


def test_chromadb_outage_still_abstains_on_unsupported(rag):
    with faults.scoped(chroma_down=True):
        res = rag.retrieve("What is the hostel fee for international students?")
    assert not res.sufficient


def test_embedding_failure_falls_back(rag):
    with faults.scoped(embedding_down=True):
        res = rag.retrieve("When do the hostel gates close?")
    assert res.mode == "keyword_fallback" and res.sufficient
    assert _top_source(res) == ("Admission_Notice_2026.pdf", 2)


def test_embedding_timeout_respects_deadline(rag):
    with faults.scoped(embedding_slow=True):
        res = rag.retrieve("When do the hostel gates close?")
    assert res.mode == "keyword_fallback"
    assert res.latency_ms < rag.s.request_deadline_s * 1000 + 1500


def test_empty_vector_results_recovered(rag):
    with faults.scoped(vector_empty=True):
        res = rag.retrieve("How much is the condonation fee?")
    assert res.mode == "hybrid_recovery" and res.sufficient
    assert _top_source(res)[1] == 1


def test_irrelevant_vector_results_gated(rag):
    with faults.scoped(vector_irrelevant=True):
        res = rag.retrieve("How much is the condonation fee?")
    assert res.sufficient
    assert _top_source(res) == ("Academic_Regulations_2026.pdf", 1)
    # random vector hits must not pass the relevance gate on their own
    assert all(c.relevant is False for c in res.candidates if c.found_by == ["vector"])


def test_manifest_mismatch_disables_vector_search(rag):
    original = rag.registry.manifest()
    rag.registry.set_manifest(embedder="some-other-model")
    try:
        res = rag.retrieve("When do the hostel gates close?")
        assert res.mode == "keyword_fallback"
        assert any(e.stage == "manifest" and e.status == "failed" for e in res.events)
    finally:
        rag.registry.set_manifest(**original)


def test_visual_question_attaches_page_image(rag):
    res = rag.retrieve("What does the grade distribution chart show?")
    assert res.visual_query
    assert any(c.chunk.kind == "figure" and c.chunk.image_path for c in res.evidence)
