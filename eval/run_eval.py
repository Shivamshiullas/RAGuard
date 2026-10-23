"""Evaluate RAGuard on the shared question set (eval/questions.json).

Builds a fresh index from the sample documents in an isolated data folder, asks every question,
and reports retrieval hit@1/@3/@k and MRR, key-fact answer correctness, correct abstention,
tokens per question (from logs/usage.jsonl, thinking tokens separately) and latency. API errors
(rate limits, server errors, timeouts) are counted separately and are not scored as wrong.
Results are saved to eval/results/stage<N>_<date>.json.

Usage:
  python eval/run_eval.py --stage 1 --delay 4      # live Gemini (needs GEMINI_API_KEY)
  python eval/run_eval.py --stage 1 --mock         # offline pipeline check, fake LLM
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from raguard.answering import render_citations  # noqa: E402
from raguard.config import load_settings  # noqa: E402
from raguard.interfaces import LLMReply  # noqa: E402
from raguard.llm import LLMClient  # noqa: E402
from raguard.scoring import (Outcome, classify_error, key_fact_score, load_questions, outcome_dict,  # noqa: E402
                             summarize)
from raguard.service import RAGuard  # noqa: E402
from raguard.usage import UsageLog, tagged  # noqa: E402

STAGE_MODALITIES = {1: {"text", "none"}, 2: {"text", "ocr", "visual", "none"}, 3: {"text", "ocr", "visual", "none"}}


class MockGemini:
    """Offline stand-in: answers with the first evidence passage. Checks the pipeline, not quality."""

    name, model = "gemini", "mock"
    thinking_mode = "n/a (mock)"

    def available(self):
        return True, "mock"

    def generate(self, system, user, images, max_tokens):
        start = user.find(">\n") + 2
        first = user[start:user.find("</evidence>")].split("\n", 1)[-1][:400]
        return LLMReply(f"{first} [E1]", "gemini", "mock", len(user) // 4, len(first) // 4, 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", type=int, default=None, help="1, 2 or 3 (default: RAGUARD_STAGE)")
    ap.add_argument("--questions", default=str(ROOT / "eval" / "questions.json"))
    ap.add_argument("--modalities", default="", help="comma list: text,ocr,visual,none (default: by stage)")
    ap.add_argument("--k", type=int, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between questions (rate limits)")
    ap.add_argument("--mock", action="store_true", help="use a fake LLM (offline)")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    overrides = {}
    if args.stage:
        overrides["RAGUARD_STAGE"] = str(args.stage)
    workdir = ROOT / "eval" / ".work" / f"stage{args.stage or 'env'}"
    shutil.rmtree(workdir, ignore_errors=True)
    overrides["RAGUARD_DATA_DIR"] = str(workdir)
    if args.k:
        overrides["TOP_K"] = str(args.k)
    s = load_settings(overrides)
    modalities = set(args.modalities.split(",")) if args.modalities else STAGE_MODALITIES[s.stage]

    llm = LLMClient(s, providers=[MockGemini()]) if args.mock else None
    rag = RAGuard(s, llm=llm)
    rag.warm_up()
    if not rag.embedder.loaded:
        sys.exit("Embedding model not loaded. Run: python scripts/download_models.py")
    if not rag.llm.enabled:
        sys.exit(f"No language model: {rag.llm.description}. Set GEMINI_API_KEY in .env or use --mock.")

    samples = ROOT / "sample_docs"
    if not list(samples.glob("*.pdf")):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_sample_docs.py"), str(samples)], check=True)
    for f in sorted(samples.iterdir()):
        if f.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}:
            out = rag.ingest(f.name, f.read_bytes())
            print(f"  ingest {f.name}: {out.message}" + (f" ({len(out.warnings)} warning(s))" if out.warnings else ""))

    questions = load_questions(Path(args.questions), modalities)
    if args.limit:
        questions = questions[: args.limit]
    run_id = f"stage{s.stage}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    usage = UsageLog(s.usage_log, s.stage)
    outcomes: list[Outcome] = []
    print(f"\nRun {run_id}: stage {s.stage}, {len(questions)} questions, k={s.top_k}")
    print(f"  embedder: {rag.embedder.name} (loaded: {rag.embedder.loaded})")
    print(f"  LLM: {rag.llm.description}\n")
    for i, q in enumerate(questions, start=1):
        with tagged(q.id, run_id):
            t0 = time.monotonic()
            res = rag.ask(q.question)
            ms = (time.monotonic() - t0) * 1000
        calls = [e for e in usage.entries(run_id) if e["question_id"] == q.id]
        hit = None
        if q.answerable:
            for pos, c in enumerate(res.retrieval.candidates[: s.top_k], start=1):
                if c.chunk.filename == q.file and c.chunk.page == q.page:
                    hit = pos
                    break
        answer = render_citations(res.text, res.cited)
        error_type = classify_error(res.text) if res.status == "error" else ""
        if q.answerable:
            scored = res.status in {"answered", "unverified", "extractive"}
            ok, missing = key_fact_score(q, answer) if scored else (False, list(q.key_facts))
        else:
            ok, missing = res.status == "abstained", []
        o = Outcome(q.id, q.modality, q.question, res.status, answer, hit, ok, missing,
                    sum(e["prompt_tokens"] or 0 for e in calls), sum(e["output_tokens"] or 0 for e in calls),
                    sum(e["thinking_tokens"] or 0 for e in calls), len(calls), ms,
                    res.text if res.status == "error" else "", error_type)
        outcomes.append(o)
        mark = "!" if error_type else ("✓" if ok else "✗")
        print(f"  [{i:2}/{len(questions)}] {mark} {q.id} {res.status:10} hit@{hit or '-':<2} "
              f"tok={o.prompt_tokens + o.output_tokens:<5} think={o.thinking_tokens:<4} {q.question[:55]}")
        if args.delay and i < len(questions):
            time.sleep(args.delay)

    summary = summarize(outcomes, s.top_k)
    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or ("mock" if args.mock else "live")
    thinking = getattr(rag.llm.providers[0], "thinking_mode", "n/a") if rag.llm.providers else "n/a"
    result = {"run_id": run_id, "stage": s.stage, "label": label, "llm": rag.llm.description,
              "gemini_thinking": thinking, "embedder": rag.embedder.name, "features": sorted(s.features),
              "modalities": sorted(modalities), "k": s.top_k, "summary": summary,
              "outcomes": [outcome_dict(o) for o in outcomes]}
    suffix = "" if label == "live" else f"_{label}"
    path = out_dir / f"stage{s.stage}_{time.strftime('%Y%m%d-%H%M')}{suffix}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    k = summary["k"]
    n_ans = sum(1 for o in outcomes if o.modality != "none" and not o.error_type)
    n_un = sum(1 for o in outcomes if o.modality == "none" and not o.error_type)
    print("\n" + "=" * 70)
    print(f"Stage {s.stage} results ({label}): {summary['n']} questions "
          f"({summary['n_answerable']} answerable, {summary['n_unanswerable']} unanswerable)")
    print("=" * 70)
    rows = [(f"Retrieval hit@1 / hit@3 / hit@{k}",
             f"{summary.get('hit_at_1')}% / {summary.get('hit_at_3')}% / {summary[f'hit_at_{k}']}%"),
            ("Retrieval MRR", str(summary["mrr"])),
            ("Answer correctness (key facts)", f"{summary['answer_correctness']}%  (of {n_ans} scored)"),
            ("Correct abstention (unanswerable)", f"{summary['correct_abstention']}%  (of {n_un} scored)"),
            ("Overall correct", f"{summary['overall_correct']}%  (of {summary['n_scored']} scored)"),
            ("API errors (not scored)", f"{summary['errors']} {summary['error_types'] or ''}".strip()),
            ("Avg tokens / question", f"{summary['avg_tokens_per_question']}  (prompt {summary['avg_prompt_tokens']}, "
                                      f"output {summary['avg_output_tokens']})"),
            ("Avg thinking tokens / question", f"{summary['avg_thinking_tokens']}  (Gemini thinking: {thinking})"),
            ("LLM calls", str(summary["llm_calls"])),
            ("Latency p50 / p95", f"{summary['latency_p50_ms']} / {summary['latency_p95_ms']} ms")]
    for name, val in rows:
        print(f"  {name:<36} {val}")

    problems = [o for o in outcomes if o.error_type or not o.correct]
    if problems:
        print("\nQuestions not answered correctly:")
        for o in problems:
            if o.error_type:
                kind = f"API error ({o.error_type})"
            elif o.modality == "none":
                kind = "answered an unanswerable question"
            elif o.status == "abstained":
                kind = "abstained wrongly"
            else:
                kind = f"incorrect, missing {o.missing_facts}"
            shown = o.error if o.error_type else o.answer
            print(f"  - {o.id} [{kind}] {o.question}\n      -> {shown[:500]!r}")
    print(f"\nSaved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
