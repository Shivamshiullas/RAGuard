from raguard.answering import Answerer, validate_answer
from raguard.faults import faults


def test_citations_validated_against_retrieved_chunks(rag):
    res = rag.retrieve("How much is the condonation fee?")
    ev = res.evidence
    text = "The condonation fee is Rs. 500 per course [E1]. It is waived for toppers [E9]."
    out, cited, warnings = validate_answer(text, ev)
    assert "[E9]" not in out
    assert cited and cited[0] is ev[0]
    assert any("not retrieved" in w for w in warnings)


def test_invented_numbers_flagged(rag):
    ev = rag.retrieve("How much is the condonation fee?").evidence
    _, _, warnings = validate_answer("The condonation fee is Rs. 750 per course [E1].", ev)
    assert any("750" in w for w in warnings)


def test_grounded_answer_with_fake_llm(rag, fake_llm):
    llm = fake_llm("A student needs at least 75% attendance in each course [E1].")
    res = Answerer(llm).answer(rag.retrieve("What minimum attendance is required?"))
    assert res.status == "answered"
    assert res.cited and res.cited[0].chunk.page == 1
    assert "[E1]" in res.text


def test_answer_without_citations_is_unverified(rag, fake_llm):
    res = Answerer(fake_llm("You need 75% attendance.")).answer(rag.retrieve("What minimum attendance is required?"))
    assert res.status == "unverified"


def test_model_reports_insufficient_evidence(rag, fake_llm):
    res = Answerer(fake_llm("INSUFFICIENT_EVIDENCE")).answer(rag.retrieve("What minimum attendance is required?"))
    assert res.status == "abstained"


def test_no_llm_call_when_evidence_insufficient(rag, fake_llm):
    llm = fake_llm("should not be called")
    res = Answerer(llm).answer(rag.retrieve("What is the hostel fee for international students?"))
    assert res.status == "abstained" and not llm.calls


def test_llm_failure_falls_back_to_extractive(rag, fake_llm):
    res = Answerer(fake_llm(fail=True)).answer(rag.retrieve("What minimum attendance is required?"))
    assert res.status == "extractive"
    assert "75%" in res.text
    assert any(e.stage == "llm" and e.status == "fallback" for e in res.llm_events)


def test_prompt_marks_evidence_as_untrusted(rag, fake_llm):
    llm = fake_llm("ok [E1]")
    Answerer(llm).answer(rag.retrieve("What minimum attendance is required?"))
    assert "<evidence id=\"E1\"" in llm.calls[0]


def test_full_pipeline_during_outage(rag):
    with faults.scoped(chroma_down=True):
        res = rag.ask("When do the hostel gates close?")
    assert res.status == "extractive"  # no LLM configured in tests
    assert res.retrieval.mode == "keyword_fallback"
    assert res.cited and res.cited[0].chunk.filename == "Admission_Notice_2026.pdf"
