"""Dataset-based evaluation of RAGuard. Every number reported here is measured on a real run.

Metrics
- retrieval hit rate@k: answerable records whose source page appears in the top-k candidates
- MRR: mean reciprocal rank of the first candidate from the source page
- citation correctness: answered records with at least one citation on the source page
  (citations are already validated against retrieved chunks by the answerer)
- evidence support: answered records with no validation warnings
- correct abstention: unanswerable records that RAGuard declined to answer
- false abstention: answerable records RAGuard declined to answer
- latency p50 / p95
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .datalab import QARecord
from .faults import LABELS, faults


@dataclass
class RecordOutcome:
    record_id: str
    question: str
    question_type: str
    answerable: bool
    source: str
    hit_rank: int | None  # 1-based rank of the source page in retrieval, None if missing
    abstained: bool
    status: str
    cited_source: bool | None
    supported: bool | None
    mode: str
    recovered: bool
    latency_ms: float
    error: str = ""


@dataclass
class EvalRun:
    run_id: str
    dataset: str
    label: str
    created_at: float
    config: dict[str, Any]
    metrics: dict[str, Any]
    outcomes: list[RecordOutcome] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _pct(num: int, den: int) -> float | None:
    return round(100.0 * num / den, 1) if den else None


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round(p / 100 * (len(values) - 1))))
    return round(values[idx], 1)


def compute_metrics(outcomes: list[RecordOutcome], k: int) -> dict[str, Any]:
    ans = [o for o in outcomes if o.answerable and not o.error]
    unans = [o for o in outcomes if not o.answerable and not o.error]
    answered = [o for o in ans if not o.abstained]
    hits = [o for o in ans if o.hit_rank is not None and o.hit_rank <= k]
    lat = [o.latency_ms for o in outcomes if not o.error]
    return {
        "n_total": len(outcomes),
        "n_answerable": len(ans),
        "n_unanswerable": len(unans),
        "n_errors": sum(1 for o in outcomes if o.error),
        "retrieval_hit_rate": _pct(len(hits), len(ans)),
        "mrr": round(sum(1.0 / o.hit_rank for o in ans if o.hit_rank) / len(ans), 3) if ans else None,
        "citation_correctness": _pct(sum(1 for o in answered if o.cited_source), len([o for o in answered if o.cited_source is not None])),
        "evidence_support": _pct(sum(1 for o in answered if o.supported), len([o for o in answered if o.supported is not None])),
        "correct_abstention": _pct(sum(1 for o in unans if o.abstained), len(unans)),
        "false_abstention": _pct(sum(1 for o in ans if o.abstained), len(ans)),
        "recovered_requests": sum(1 for o in outcomes if o.recovered),
        "latency_p50_ms": _percentile(lat, 50),
        "latency_p95_ms": _percentile(lat, 95),
        "k": k,
    }


class Evaluator:
    def __init__(self, rag, eval_dir: Path):
        self.rag = rag
        self.dir = eval_dir

    def run(self, records: list[QARecord], dataset: str, label: str = "normal", fault_flags: dict[str, bool] | None = None,
            with_llm: bool = True, k: int | None = None, progress: Callable[[int, int], None] | None = None,
            question_override: dict[str, str] | None = None) -> EvalRun:
        """Evaluate RAGuard on ``records``. ``question_override`` maps record_id -> alternative
        question text (used to evaluate Adaption-adapted prompts against the same sources)."""
        k = k or self.rag.s.top_k
        fault_flags = {f: v for f, v in (fault_flags or {}).items() if v}
        usable = [r for r in records if r.review_status != "rejected" and r.question.strip()]
        outcomes: list[RecordOutcome] = []
        use_llm = with_llm and self.rag.llm.enabled
        with faults.scoped(**fault_flags):
            for i, r in enumerate(usable):
                q = (question_override or {}).get(r.record_id, r.question)
                t0 = time.monotonic()
                try:
                    if use_llm:
                        res = self.rag.ask(q)
                        retrieval, abstained, status = res.retrieval, res.status == "abstained", res.status
                        cited_source = (any(c.chunk.page == r.source_page and c.chunk.doc_id == r.source_doc_id
                                            for c in res.cited) if r.answerable and res.status == "answered" else None)
                        supported = (not res.warnings) if res.status == "answered" else None
                    else:
                        retrieval = self.rag.retrieve(q)
                        abstained, status = not retrieval.sufficient, ("abstained" if not retrieval.sufficient else "retrieved")
                        cited_source = supported = None
                    rank = None
                    if r.answerable:
                        for pos, c in enumerate(retrieval.candidates, start=1):
                            if c.chunk.doc_id == r.source_doc_id and c.chunk.page == r.source_page:
                                rank = pos
                                break
                    outcomes.append(RecordOutcome(r.record_id, q, r.question_type, r.answerable,
                                                  f"{r.source_filename} p.{r.source_page}" if r.answerable else "",
                                                  rank, abstained, status, cited_source, supported, retrieval.mode,
                                                  retrieval.recovered, (time.monotonic() - t0) * 1000))
                except Exception as e:
                    outcomes.append(RecordOutcome(r.record_id, q, r.question_type, r.answerable, "", None, False,
                                                  "error", None, None, "none", False,
                                                  (time.monotonic() - t0) * 1000, f"{type(e).__name__}: {e}"))
                if progress:
                    progress(i + 1, len(usable))

        limitations = [f"Measured on {len(usable)} records from dataset '{dataset}'. Small test sets give wide error margins."]
        if not use_llm:
            limitations.append("No language model was used: abstention is the retrieval relevance gate's decision, "
                               "and citation correctness / evidence support were not measured.")
        if fault_flags:
            limitations.append("Simulated faults active during this run: " +
                               ", ".join(LABELS.get(f, f) for f in fault_flags) + ".")
        gen = {r.generator.split(":")[0] for r in usable}
        if "template" in gen:
            limitations.append("Some records were template-generated; their phrasing is less natural than real user questions.")
        if any(r.review_status == "ai_generated" for r in usable):
            limitations.append("Includes records that failed automatic checks and were not human-reviewed.")

        run = EvalRun(
            run_id=time.strftime("%Y%m%d-%H%M%S"), dataset=dataset, label=label, created_at=time.time(),
            config={"top_k": k, "llm": self.rag.llm.description if use_llm else "none (retrieval only)",
                    "embedder": self.rag.embedder.name, "faults": list(fault_flags),
                    "vector_min_similarity": self.rag.s.vector_min_similarity,
                    "min_term_coverage": self.rag.s.min_term_coverage},
            metrics=compute_metrics(outcomes, k), outcomes=outcomes, limitations=limitations)
        self.save(run)
        return run

    def save(self, run: EvalRun) -> Path:
        p = self.dir / f"{run.run_id}_{run.label.replace(' ', '_')[:40]}.json"
        p.write_text(json.dumps(run.to_dict(), indent=2, default=str), encoding="utf-8")
        return p

    def list_runs(self) -> list[dict[str, Any]]:
        runs = []
        for p in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                d["_path"] = str(p)
                runs.append(d)
            except json.JSONDecodeError:
                continue
        return runs
