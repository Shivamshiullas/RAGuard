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
    correct: bool  # meaningless when error_type is set; errors are excluded from correctness
    missing_facts: list[str]
    prompt_tokens: int
    output_tokens: int
    thinking_tokens: int
    llm_calls: int
    latency_ms: float
    error: str = ""
    error_type: str = ""  # rate_limit | server | timeout | auth | blocked | other


def classify_error(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"429|resource_exhausted|rate limit|quota", t):
        return "rate_limit"
    if re.search(r"(500|502|503|504)|unavailable|internal|servererror", t):
        return "server"
    if "timeout" in t or "timed out" in t or "deadline" in t:
        return "timeout"
    if re.search(r"(401|403)|api key|permission|unauthenticated", t):
        return "auth"
    if "blocked" in t or "safety" in t:
        return "blocked"
    return "other"


HIT_KS = (1, 3)


def summarize(outcomes: list[Outcome], k: int) -> dict[str, Any]:
    ok = [o for o in outcomes if not o.error_type]
    errored = [o for o in outcomes if o.error_type]
    ans_all = [o for o in outcomes if o.modality != "none"]  # retrieval runs before the LLM, so errors still count here
    ans = [o for o in ok if o.modality != "none"]
    unans = [o for o in ok if o.modality == "none"]

    def pct(n: int, d: int) -> float | None:
        return round(100 * n / d, 1) if d else None

    def hit(kk: int) -> float | None:
        return pct(sum(1 for o in ans_all if o.hit_rank is not None and o.hit_rank <= kk), len(ans_all))

    lat = sorted(o.latency_ms for o in ok)
    err_types: dict[str, int] = {}
    for o in errored:
        err_types[o.error_type] = err_types.get(o.error_type, 0) + 1
    mean = lambda xs: round(statistics.mean(xs), 1) if xs else None  # noqa: E731
    out = {
        "n": len(outcomes), "n_answerable": len(ans_all), "n_unanswerable": len(outcomes) - len(ans_all),
        "n_scored": len(ok), "k": k,
        **{f"hit_at_{kk}": hit(kk) for kk in HIT_KS if kk < k},
        f"hit_at_{k}": hit(k),
        "hit_rate_at_k": hit(k),
        "mrr": round(sum(1.0 / o.hit_rank for o in ans_all if o.hit_rank) / len(ans_all), 3) if ans_all else None,
        "answer_correctness": pct(sum(o.correct for o in ans), len(ans)),
        "correct_abstention": pct(sum(o.correct for o in unans), len(unans)),
        "overall_correct": pct(sum(o.correct for o in ok), len(ok)),
        "errors": len(errored), "error_types": err_types,
        "avg_tokens_per_question": mean([o.prompt_tokens + o.output_tokens for o in ok]),
        "avg_prompt_tokens": mean([o.prompt_tokens for o in ok]),
        "avg_output_tokens": mean([o.output_tokens for o in ok]),
        "avg_thinking_tokens": mean([o.thinking_tokens for o in ok]),
        "llm_calls": sum(o.llm_calls for o in outcomes),
        "latency_p50_ms": round(lat[len(lat) // 2], 1) if lat else None,
        "latency_p95_ms": round(lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))], 1) if lat else None,
    }
    return out


def outcome_dict(o: Outcome) -> dict[str, Any]:
    return asdict(o)
