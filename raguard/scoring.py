"""Scoring for eval/run_eval.py: key-fact matching, retrieval hits and token totals."""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_CITES = re.compile(r"\[(E\d+|\?\d+|[^\[\]]+?, p\.\d+)\]")


@dataclass
class Question:
    id: str
    modality: str  # text | ocr | visual | none
    question: str
    expected_answer: str = ""
    key_facts: list[str] = field(default_factory=list)
    file: str = ""
    page: int = 0

    @property
    def answerable(self) -> bool:
        return self.modality != "none"


def load_questions(path: Path, modalities: set[str] | None = None) -> list[Question]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    qs = [Question(**{k: v for k, v in q.items() if k in Question.__dataclass_fields__}) for q in data["questions"]]
    return [q for q in qs if modalities is None or q.modality in modalities]


def normalize(text: str) -> str:
    text = _CITES.sub(" ", text or "").lower()
    text = text.replace("–", "-").replace("—", "-").replace("’", "'").replace("*", "")
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)  # 1,000 -> 1000
    text = re.sub(r"\s*%", "%", text)
    return re.sub(r"\s+", " ", text).strip()


def fact_present(fact: str, answer: str) -> bool:
    """True if any '|'-separated alternative appears in the answer as a whole word/phrase."""
    norm = normalize(answer)
    for alt in fact.split("|"):
        alt = normalize(alt)
        if alt and re.search(rf"(?<![\w.]){re.escape(alt)}(?![\w])", norm):
            return True
    return False


def key_fact_score(q: Question, answer: str) -> tuple[bool, list[str]]:
    """(all facts present, missing facts)."""
    missing = [f for f in q.key_facts if not fact_present(f, answer)]
    return (not missing, missing)


@dataclass
class Outcome:
    id: str
    modality: str
    question: str
    status: str
    answer: str
    hit_rank: int | None
    correct: bool
    missing_facts: list[str]
    prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    llm_calls: int
    latency_ms: float
    error: str = ""


def summarize(outcomes: list[Outcome], k: int) -> dict[str, Any]:
    ans = [o for o in outcomes if o.modality != "none"]
    unans = [o for o in outcomes if o.modality == "none"]

    def pct(n: int, d: int) -> float | None:
        return round(100 * n / d, 1) if d else None

    tokens = [o.prompt_tokens + o.output_tokens + o.thinking_tokens for o in outcomes]
    lat = sorted(o.latency_ms for o in outcomes)
    return {
        "n": len(outcomes), "n_answerable": len(ans), "n_unanswerable": len(unans),
        "k": k,
        "hit_rate_at_k": pct(sum(1 for o in ans if o.hit_rank is not None and o.hit_rank <= k), len(ans)),
        "answer_correctness": pct(sum(o.correct for o in ans), len(ans)),
        "correct_abstention": pct(sum(o.correct for o in unans), len(unans)),
        "overall_correct": pct(sum(o.correct for o in outcomes), len(outcomes)),
        "errors": sum(1 for o in outcomes if o.status == "error"),
        "avg_tokens_per_question": round(statistics.mean(tokens), 1) if tokens else None,
        "avg_prompt_tokens": round(statistics.mean(o.prompt_tokens for o in outcomes), 1) if outcomes else None,
        "avg_output_tokens": round(statistics.mean(o.output_tokens for o in outcomes), 1) if outcomes else None,
        "avg_thinking_tokens": round(statistics.mean(o.thinking_tokens for o in outcomes), 1) if outcomes else None,
        "llm_calls": sum(o.llm_calls for o in outcomes),
        "latency_p50_ms": round(lat[len(lat) // 2], 1) if lat else None,
        "latency_p95_ms": round(lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))], 1) if lat else None,
    }


def outcome_dict(o: Outcome) -> dict[str, Any]:
    return asdict(o)
