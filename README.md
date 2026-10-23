# RAGuard

**Your academic documents. Clear answers. Verifiable evidence.**

RAGuard answers questions about academic documents (syllabi, regulations, exam rules, notices) with
page-level citations. It is built in three stages that build on each other. Each stage runs, can be
demoed and is evaluated on its own:

| Stage | Adds | Status |
|---|---|---|
| 1. Basic RAG | Text PDFs, section-aware chunking, MiniLM + ChromaDB, grounded Gemini answers with citations | ✅ `stage-1` |
| 2. Multimodal | OCR for scanned pages and images, table/figure tagging, selective vision | planned |
| 3. Fault tolerance | BM25 fusion, retries/timeouts/circuit breaker, fallbacks, relevance gate, answer checks, fault injection | planned (code exists, being reworked) |

Pick the stage with `RAGUARD_STAGE=1|2|3` in `.env`. Individual features can be switched with
`FEATURE_<NAME>=1/0` (see `.env.example`).

## Setup

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate                  # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_models.py        # embedding model -> ./models (once)
copy .env.example .env                   # then set GEMINI_API_KEY
streamlit run app.py
```

The app never downloads models itself. If `./models` is missing it says so and tells you to run the script.

## Stage 1: Basic RAG

**What it does**

- **Upload checks:** file type (PDF only in Stage 1), size, page count, password protection and PDF signature.
  Uploads are de-duplicated by SHA-256, so the same file is never indexed twice.
- **Extraction:** PyMuPDF text blocks with page numbers. Running headers and footers are removed.
- **Section-aware chunking:** a heading (detected by font size or bold) starts a new chunk, and paragraphs
  are packed up to `CHUNK_CHARS` with `CHUNK_OVERLAP`. Every table is kept whole in one chunk. Chunks
  never cross pages. Each chunk stores `doc_id`, file name, page and chunk ID, and starts with a
  `[document | page | heading]` context line.
- **Retrieval:** `all-MiniLM-L6-v2` (ONNX Runtime) embeddings, ChromaDB cosine index, top-k (`TOP_K`).
- **Answering:** Gemini (`google-genai`, `GEMINI_MODEL`, temperature 0.1, capped output tokens). The
  prompt allows only the given passages. Passages are cited internally as `[E1]`, `[E2]` and shown in the
  UI as `[file, p.N]`. If the passages don't answer the question, the model replies `INSUFFICIENT_EVIDENCE`.
- **Source of truth:** `data/registry.json` and `data/chunks/*.jsonl`.
- **Token logging:** every LLM call appends prompt, output and thinking tokens, the question ID and the
  stage to `logs/usage.jsonl`.
- **UI:** Document Library (upload, list, delete, preview) and AI Assistant (chat with citations).

**Not in Stage 1, by design.** Scanned pages are skipped with a warning (OCR is Stage 2). There is no
keyword fallback, no retries and no relevance gate (Stage 3). If ChromaDB or Gemini fails, the answer
shows an error.

**Evaluate**

```bash
python eval/run_eval.py --stage 1 --delay 4      # live Gemini; --delay respects free-tier rate limits
python eval/run_eval.py --stage 1 --mock         # offline pipeline check with a fake LLM
```

The script builds a fresh index from `sample_docs/` and runs the shared question set (`eval/questions.json`):
20 text questions plus 8 unanswerable ones in Stage 1. Later stages add the OCR and visual questions
from the same file, so results stay comparable. It reports:

- retrieval hit rate@k (the expected source page is in the top k)
- answer correctness by key-fact matching
- correct abstention on unanswerable questions
- average tokens per question, and latency

Results are saved in `eval/results/`.

**Stage 1 results:** see `eval/results/` (filled in when the live run is done).

## Tests

```bash
pytest -q                 # everything (offline; the LLM is always mocked)
pytest -q tests/stage1    # Stage 1 only: needs no model files (uses a hashing test embedder)
```

`tests/stage3` and `tests/extras` use the real MiniLM model from `./models`; they are skipped if it hasn't
been downloaded. Four Stage 3 tests are marked as expected failures until the relevance gate is
recalibrated in Stage 3.

## Extras (off by default)

`FEATURE_EXTRAS=1` adds the Academic Data Lab (QA dataset generation, quality checks, review, JSONL/CSV export),
the Adaption Adaptive Data integration (`ADAPTION_API_KEY`) and an Evaluation page. These aren't part of any stage.

Claude is available as an optional extra provider (`LLM_CHAIN=gemini,anthropic`). It is not in the default chain.

## Known limitations

- Fault injection (Stage 3) is process-wide: toggling a fault affects every open browser session. Demo only.
- The sample documents describe a fictional institution and are tiny, so hit rates are high.
  Measure on your own documents.

## Project layout

```
app.py                 Streamlit entry point (pages depend on the stage)
raguard/
  config.py            settings, RAGUARD_STAGE, feature flags
  interfaces.py        Parser, Embedder, Retriever, LLMProvider, AnswerChecker
  ingestion.py         upload checks, PDFParser (stage 1) + OCR/visual parts (stage 2), ImageParser
  indexes.py           embedder (local model files only), ChromaDB, BM25
  retrieval.py         VectorRetriever (stage 1), ResilientRetriever (stage 3)
  providers.py         Gemini, Ollama, Claude providers; retryable-error rules
  llm.py               provider chain + token usage logging
  answering.py         grounded prompt, BasicCitations (stage 1), EvidenceChecker (stage 3)
  usage.py, scoring.py token log; eval scoring
  service.py           builds the stage's components
  faults.py            fault injection (stage 3)
  datalab.py, adaption_client.py, evaluation.py   extras
ui/                    pages
eval/                  questions.json, run_eval.py, results/
scripts/               download_models.py, make_sample_docs.py
tests/                 stage1/, stage3/, extras/
```
