"""Evaluate RAGuard on the shared question set (eval/questions.json).

Builds a fresh index from the sample documents in an isolated data folder, asks every question,
and reports retrieval hit rate@k, key-fact answer correctness, correct abstention, tokens per
question (from logs/usage.jsonl) and latency. Results are saved to eval/results/.

Usage:
  python eval/run_eval.py --stage 1                 # live Gemini (needs GEMINI_API_KEY)
  python eval/run_eval.py --stage 1 --mock          # offline pipeline check, fake LLM
  python eval/run_eval.py --stage 1 --limit 5 --delay 4
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
from raguard.scoring import Outcome, key_fact_score, load_questions, outcome_dict, summarize  # noqa: E402
from raguard.service import RAGuard  # noqa: E402
from raguard.usage import UsageLog, tagged  # noqa: E402

STAGE_MODALITIES = {1: {"text", "none"}, 2: {"text", "ocr", "visual", "none"}, 3: {"text", "ocr", "visual", "none"}}


class MockGemini:
    """Offline stand-in: answers with the first evidence passage. Checks the pipeline, not quality."""

    name, model = "gemini", "mock"

    def available(self):
        return True, "mock"

    def generate(self, system, user, images, max_tokens):
        start = user.find(">\n") + 2
        first = user[start:user.find("</evidence>")].split("\n", 1)[-1][:400]
        return LLMReply(f"{first} [E1]", "gemini", "mock", len(user) // 4, len(first) // 4)


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
    print(f"\nRun {run_id}: stage {s.stage}, {len(questions)} questions, LLM {rag.llm.description}, k={s.top_k}\n")
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
        if q.answerable:
            ok, missing = key_fact_score(q, answer) if res.status in {"answered", "unverified", "extractive"} else (False, q.key_facts)
        else:
            ok, missing = res.status == "abstained", []
        outcomes.append(Outcome(q.id, q.modality, q.question, res.status, answer, hit, ok, missing,
                                sum(e["prompt_tokens"] or 0 for e in calls), sum(e["output_tokens"] or 0 for e in calls),
                                sum(e["thinking_tokens"] or 0 for e in calls), len(calls), ms,
                                res.text if res.status == "error" else ""))
        mark = "✓" if ok else "✗"
        print(f"  [{i:2}/{len(questions)}] {mark} {q.id} {res.status:10} hit@{hit or '-':<2} "
              f"tok={outcomes[-1].prompt_tokens + outcomes[-1].output_tokens:<5} {q.question[:60]}")
        if not ok and q.answerable and res.status != "error":
            print(f"           missing: {missing} | answer: {answer[:140]!r}")
        if res.status == "error":
            print(f"           error: {res.text[:200]}")
        if args.delay and i < len(questions):
            time.sleep(args.delay)

    summary = summarize(outcomes, s.top_k)
    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or ("mock" if args.mock else "live")
    result = {"run_id": run_id, "stage": s.stage, "label": label, "llm": rag.llm.description,
              "embedder": rag.embedder.name, "features": sorted(s.features), "modalities": sorted(modalities),
              "summary": summary, "outcomes": [outcome_dict(o) for o in outcomes]}
    path = out_dir / f"{run_id}_{label}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("\n" + "=" * 64)
    print(f"Stage {s.stage} results ({label}) - {summary['n']} questions ({summary['n_answerable']} answerable, "
          f"{summary['n_unanswerable']} unanswerable)")
    print("=" * 64)
    rows = [("Retrieval hit rate@k", f"{summary['hit_rate_at_k']}%  (k={summary['k']})"),
            ("Answer correctness (key facts)", f"{summary['answer_correctness']}%"),
            ("Correct abstention (unanswerable)", f"{summary['correct_abstention']}%"),
            ("Overall correct", f"{summary['overall_correct']}%"),
            ("Avg tokens / question", f"{summary['avg_tokens_per_question']}  (prompt {summary['avg_prompt_tokens']}, "
                                      f"output {summary['avg_output_tokens']}, thinking {summary['avg_thinking_tokens']})"),
            ("LLM calls", str(summary["llm_calls"])),
            ("Latency p50 / p95", f"{summary['latency_p50_ms']} / {summary['latency_p95_ms']} ms"),
            ("Errors", str(summary["errors"]))]
    for name, val in rows:
        print(f"  {name:<36} {val}")
    print(f"\nSaved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
