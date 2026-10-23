import json
from types import SimpleNamespace

import pytest

from raguard.answering import BasicCitations, render_citations
from raguard.llm import LLMClient
from raguard.providers import GeminiProvider, LLMBlocked, LLMEmpty, is_retryable
from raguard.scoring import Question, fact_present, key_fact_score, summarize, Outcome
from raguard.usage import UsageLog, tagged


# Retrieval -----------------------------------------------------------------------------
def test_vector_retrieval_returns_top_k(rag1):
    res = rag1.retrieve("condonation fee medical certificate")
    assert res.mode == "vector" and res.sufficient
    assert 0 < len(res.candidates) <= rag1.s.top_k
    assert all(c.found_by == ["vector"] for c in res.candidates)
    pages = [(c.chunk.filename, c.chunk.page) for c in res.candidates[:3]]
    assert ("Academic_Regulations_2026.pdf", 1) in pages


def test_document_filter(rag1):
    syl = next(d["doc_id"] for d in rag1.documents() if d["filename"].startswith("CS201"))
    res = rag1.retrieve("attendance", [syl])
    assert res.candidates and all(c.chunk.doc_id == syl for c in res.candidates)


def test_empty_question(rag1):
    res = rag1.retrieve("   ")
    assert not res.sufficient and not res.candidates


# Answering -----------------------------------------------------------------------------
def test_answer_with_citation_rendered_as_file_and_page(rag1, provider):
    with tagged("q-test"):
        res = rag1.ask("What minimum attendance is required?")
    assert res.status == "answered"
    shown = render_citations(res.text, res.cited)
    assert "[E" not in shown
    assert f"[{res.cited[0].chunk.filename}, p.{res.cited[0].chunk.page}]" in shown
    user_prompt = provider.calls[-1]["user"]
    assert '<evidence id="E1"' in user_prompt and "Question: What minimum attendance" in user_prompt


def test_basic_citations_renumbers_and_keeps_unknown_markers(rag1):
    ev = rag1.retrieve("condonation fee").evidence
    out = BasicCitations().check("Fee is Rs. 500 [E2]. Also [E1]. Bogus [E9].", ev)
    assert out.text.startswith("Fee is Rs. 500 [E1]. Also [E2].")
    assert "[?9]" in out.text and out.cited == [ev[1], ev[0]]
    assert out.warnings == []  # stage 1 does not verify


def test_model_reports_insufficient_evidence(s1, rag1, fake_provider):
    from raguard.answering import Answerer

    llm = LLMClient(s1, providers=[fake_provider(["INSUFFICIENT_EVIDENCE"])])
    res = Answerer(s1, llm, BasicCitations()).answer(rag1.retrieve("What is the hostel fee?"))
    assert res.status == "abstained"


def test_llm_failure_is_an_error_not_a_crash_in_stage_1(s1, rag1, fake_provider):
    from raguard.answering import Answerer

    llm = LLMClient(s1, providers=[fake_provider(error=ConnectionError("down"))])
    res = Answerer(s1, llm, BasicCitations()).answer(rag1.retrieve("attendance"))
    assert res.status == "error" and "failed" in res.text
    assert len(llm.providers[0].calls) == 1  # no retries before Stage 3


def test_no_llm_configured(s1, rag1):
    from raguard.answering import Answerer

    llm = LLMClient(s1)  # GEMINI_API_KEY is empty in tests
    assert not llm.enabled and "GEMINI_API_KEY" in llm.description
    res = Answerer(s1, llm, BasicCitations()).answer(rag1.retrieve("attendance"))
    assert res.status == "error"


# Gemini provider (mocked client) --------------------------------------------------------
def _resp(text="Answer [E1]", finish="STOP", block=None, pt=120, ot=9, th=30):
    return SimpleNamespace(
        text=text, model_version="gemini-test",
        candidates=[SimpleNamespace(finish_reason=finish)],
        prompt_feedback=SimpleNamespace(block_reason=block) if block else None,
        usage_metadata=SimpleNamespace(prompt_token_count=pt, candidates_token_count=ot, thoughts_token_count=th))


class _Client:
    def __init__(self, resp):
        self.resp, self.calls = resp, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


def test_gemini_request_shape_and_usage(s1):
    client = _Client(_resp())
    reply = GeminiProvider(s1, client=client).generate("sys", "user prompt", [b"\x89PNG"], 4000)
    call = client.calls[0]
    assert call["model"] == s1.gemini_model
    assert call["config"].temperature == 0.1
    assert call["config"].max_output_tokens == s1.gemini_max_output_tokens  # capped
    assert call["config"].system_instruction == "sys"
    assert call["contents"][-1] == "user prompt" and len(call["contents"]) == 2  # image part + text
    assert (reply.text, reply.prompt_tokens, reply.output_tokens, reply.thinking_tokens) == ("Answer [E1]", 120, 9, 30)


@pytest.mark.parametrize("resp,exc", [
    (_resp(text=None, finish="SAFETY"), LLMBlocked),
    (_resp(text="", finish="STOP"), LLMEmpty),
    (_resp(block="SAFETY"), LLMBlocked),
    (_resp(text=None, finish="MAX_TOKENS"), LLMEmpty),
])
def test_gemini_empty_or_blocked_is_a_failure(s1, resp, exc):
    with pytest.raises(exc) as info:
        GeminiProvider(s1, client=_Client(resp)).generate("s", "u", [], 100)
    assert info.value.reply.prompt_tokens == 120  # tokens are still known for logging


def test_retryable_classification():
    from google.genai import errors

    assert not is_retryable(errors.ClientError(400, {"error": {"message": "bad"}}))
    assert not is_retryable(errors.ClientError(403, {"error": {"message": "denied"}}))
    assert is_retryable(errors.ClientError(429, {"error": {"message": "slow down"}}))
    assert is_retryable(errors.ServerError(503, {"error": {"message": "unavailable"}}))
    assert is_retryable(errors.ServerError(500, {"error": {"message": "oops"}}))
    assert not is_retryable(LLMBlocked("x")) and not is_retryable(LLMEmpty("x"))
    assert is_retryable(TimeoutError()) and not is_retryable(ValueError())


def test_usage_logged_per_call_with_question_and_stage(s1):
    log = UsageLog(s1.logs_dir / "u.jsonl", s1.stage)
    llm = LLMClient(s1, providers=[GeminiProvider(s1, client=_Client(_resp()))], usage=log)
    with tagged("t01", "run-1"):
        llm.complete("sys", "user")
    bad = LLMClient(s1, providers=[GeminiProvider(s1, client=_Client(_resp(text="", finish="STOP")))], usage=log)
    with tagged("t02", "run-1"), pytest.raises(Exception):
        bad.complete("sys", "user")
    entries = log.entries("run-1")
    assert [e["question_id"] for e in entries] == ["t01", "t02"]
    assert (entries[0]["stage"], entries[0]["prompt_tokens"], entries[0]["output_tokens"], entries[0]["ok"]) == (1, 120, 9, True)
    assert entries[1]["ok"] is False and entries[1]["prompt_tokens"] == 120 and "LLMEmpty" in entries[1]["error"]
    json.dumps(entries)  # serialisable


# Scoring -------------------------------------------------------------------------------
def test_key_fact_matching():
    assert fact_present("75%", "You need 75 % attendance [Regs.pdf, p.1].")
    assert fact_present("7 days|seven days", "within seven days")
    assert not fact_present("15", "on 150 days")  # whole numbers only
    assert not fact_present("1", "[Academic_Regulations_2026.pdf, p.1]")  # citations are ignored
    assert fact_present("re-register", "must re–register")  # dash variants
    q = Question("x", "text", "q", key_facts=["40%", "50%"])
    assert key_fact_score(q, "40% in ESE and 50% aggregate") == (True, [])
    assert key_fact_score(q, "40% only") == (False, ["50%"])


def test_summary_metrics():
    def o(mod, hit, ok, pt=100, ot=10):
        return Outcome("i", mod, "q", "answered", "a", hit, ok, [], pt, ot, 0, 1, 10.0)
    m = summarize([o("text", 1, True), o("text", None, False), o("none", None, True), o("none", None, False)], k=6)
    assert m["hit_rate_at_k"] == 50.0 and m["answer_correctness"] == 50.0 and m["correct_abstention"] == 50.0
    assert m["avg_tokens_per_question"] == 110.0 and m["llm_calls"] == 4
