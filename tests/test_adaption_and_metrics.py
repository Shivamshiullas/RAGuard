import gzip
import io
import json
import tarfile
from dataclasses import replace

import pytest

from raguard.adaption_client import AdaptionNotAvailable, AdaptionService, match_adapted_rows
from raguard.config import ROOT
from raguard.datalab import load_golden
from raguard.evaluation import Evaluator, RecordOutcome, compute_metrics


# Adaption ------------------------------------------------------------------------------
def test_adaption_without_key_reports_not_configured(rag):
    svc = AdaptionService(rag.s)
    st = svc.status()
    assert st.installed and not st.configured and st.connected is None
    with pytest.raises(AdaptionNotAvailable, match="ADAPTION_API_KEY"):
        svc.client()


def test_adaption_with_bad_key_reports_error(rag, monkeypatch):
    svc = AdaptionService(replace(rag.s, adaption_api_key="pt_live_invalid", adaption_base_url="http://127.0.0.1:9"))
    st = svc.status(test_connection=True)
    assert st.configured and st.connected is False
    assert "network" in st.message.lower() or "connection" in st.message.lower()
    assert svc.operations(1)[0]["op"] == "connection_test" and svc.operations(1)[0]["ok"] is False


def test_parse_download_formats():
    rows = [{"record_id": "a", "prompt": "q1"}, {"record_id": "b", "prompt": "q2"}]
    jsonl = "\n".join(json.dumps(r) for r in rows).encode()
    assert AdaptionService._parse_download(jsonl) == rows
    assert AdaptionService._parse_download(gzip.compress(jsonl)) == rows
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("part-0.jsonl")
        info.size = len(jsonl)
        tar.addfile(info, io.BytesIO(jsonl))
    assert AdaptionService._parse_download(buf.getvalue()) == rows


def test_match_adapted_rows_never_guesses():
    originals = {"a": "orig-a"}
    pairs, unmatched = match_adapted_rows([{"record_id": "a", "prompt": "new q"}, {"prompt": "orphan"}], originals)
    assert pairs == [("orig-a", "new q")] and unmatched == 1


# Metrics -------------------------------------------------------------------------------
def _o(answerable, rank, abstained, cited=None, supported=None, latency=100.0, error=""):
    return RecordOutcome("id", "q", "factual", answerable, "s", rank, abstained, "x", cited, supported, "hybrid",
                         False, latency, error)


def test_metric_computation():
    outs = [_o(True, 1, False, True, True, 100), _o(True, 3, False, False, True, 200), _o(True, None, True, None, None, 300),
            _o(False, None, True, latency=50), _o(False, None, False, latency=60), _o(True, 1, False, error="boom")]
    m = compute_metrics(outs, k=2)
    assert m["n_answerable"] == 3 and m["n_unanswerable"] == 2 and m["n_errors"] == 1
    assert m["retrieval_hit_rate"] == round(100 / 3, 1)  # rank 1 only (rank 3 > k)
    assert m["mrr"] == round((1 + 1 / 3) / 3, 3)
    assert m["citation_correctness"] == 50.0
    assert m["evidence_support"] == 100.0
    assert m["correct_abstention"] == 50.0
    assert m["false_abstention"] == round(100 / 3, 1)
    assert m["latency_p50_ms"] == 100.0


def test_metrics_empty_denominators():
    m = compute_metrics([], k=5)
    assert m["retrieval_hit_rate"] is None and m["correct_abstention"] is None


def test_evaluation_run_normal_and_outage(rag):
    recs, _ = load_golden(ROOT / "evaluation" / "golden_questions.json", rag.registry.all_chunks())
    ev = Evaluator(rag, rag.s.eval_dir)
    normal = ev.run(recs, "golden", "normal", with_llm=False)
    outage = ev.run(recs, "golden", "outage", {"chroma_down": True}, with_llm=False)
    assert normal.metrics["n_total"] == outage.metrics["n_total"] == 24
    assert normal.metrics["retrieval_hit_rate"] >= 90
    assert normal.metrics["correct_abstention"] == 100.0
    assert outage.metrics["recovered_requests"] == 24
    assert outage.metrics["n_errors"] == 0
    assert any("Simulated" in lim for lim in outage.limitations)
    assert len(ev.list_runs()) >= 2
