# RAGuard

**Your academic documents. Clear answers. Verifiable evidence.**

RAGuard is a fault-tolerant multimodal RAG assistant for academic documents: syllabi, regulations, exam
rules, admission notices and handbooks. It answers questions with page-level citations, recovers when
retrieval fails, and says plainly when the documents don't contain the answer. Its Academic Data Lab builds
a quality-checked question-answer dataset with Adaption, and RAGuard is evaluated against that dataset.

This is a hackathon prototype, not a production system.

## Quick start

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # optional: add ANTHROPIC_API_KEY / ADAPTION_API_KEY
streamlit run app.py
```

Then open **Document Library → Load sample documents** and go to the **AI Assistant**.

The first start downloads the embedding model (all-MiniLM-L6-v2, about 90 MB) from Hugging Face.

## What works without any keys

| Capability | Needs | Without it |
|---|---|---|
| Upload, extraction, page mapping, BM25 + ChromaDB retrieval, recovery, abstention | nothing | – |
| OCR for scanned pages | `rapidocr-onnxruntime` (in requirements) | Scanned pages are flagged as unreadable |
| Written answers, vision on page images, LLM-generated datasets, Malayalam variants | `ANTHROPIC_API_KEY` or a local Ollama model | Extractive answers (verbatim passages with citations) and template-generated datasets, clearly labelled |
| Adaption upload / adapt / evaluation / download | `ADAPTION_API_KEY` | Adaption steps are disabled and say why. They are never simulated. |

## How it works

```
upload → validate → PyMuPDF text per page ─┬─ OCR if a page is scanned (RapidOCR)
                                           ├─ tables → markdown chunks
                                           └─ figures/charts/scans → page image + "visual" record
chunks (+ "[document | page | heading]" context line) → local JSONL store (source of truth)
                                           ├─ ChromaDB (cosine, MiniLM embeddings)
                                           └─ BM25 (in-memory, rebuilt from JSONL, independent of ChromaDB)

question → manifest check → embed (timeout, retries) → ChromaDB (timeout, retries, reconnect)
         → BM25 (always) → route: hybrid | hybrid_recovery (weak vectors) | keyword_fallback (vector path down)
         → reciprocal-rank fusion → visual records for chart/diagram questions
         → relevance gate (IDF-weighted term coverage + similarity) → sufficient? → answer : abstain
         → LLM with [E#] evidence → citation validation, number check, support check
```

Every step is recorded as a recovery event, and the UI shows the trace. Injected failures are labelled **SIMULATED**.

## Pages

- **Dashboard**: document stats, recent uploads, live system status.
- **Document Library**: upload, processing status, previews, extracted chunks, delete, rebuild the vector index.
- **AI Assistant**: chat with citations, supporting passages, page images, interpretation and conflict markers, and a recovery trace.
- **Academic Data Lab**: generate factual, conceptual, procedural, comparative and unanswerable QA pairs (optional Malayalam). Quality checks cover duplicates, inconsistent answers, missing fields, unsupported claims or numbers, traceability and answerability. Includes a review workflow (AI-generated, auto-validated, human-reviewed, rejected), export to JSONL or CSV, and the Adaption workflow.
- **Reliability Demo**: side-by-side normal vs. injected failure, a fault suite, and persistent fault switches.
- **Evaluation**: hit rate@k, MRR, citation correctness, evidence support, correct and false abstention, and p50/p95 latency under normal and simulated-failure conditions. Every run is saved, and its limitations are listed.

## Adaption integration

RAGuard uses the official `adaption` SDK ([docs](https://docs.adaptionlabs.ai)):

1. **Upload**: validated QA records go up as `prompt` / `completion` / `context` rows, plus `record_id` (`datasets.upload_file`, `get_status`).
2. **Estimate**: `datasets.adapt(..., estimate=True)` returns the credit cost before anything is spent.
3. **Adapt**: a real Adaptive Data run, started only after an explicit confirmation checkbox.
4. **Evaluate**: `datasets.get_evaluation` returns Adaption's own quality score and grade, before and after.
5. **Download**: adapted rows are joined back to their source pages by `record_id`. Rows that can't be joined are reported, not guessed. The result is saved as `<dataset>_adapted`, so the Evaluation page can compare the original and adapted question sets on the same sources.

Every call is logged to `data/adaption/operations.jsonl` and shown in the UI.

## Tests

```bash
pytest -q
```

The suite covers extraction and page mapping, OCR, invalid uploads, idempotent re-upload, deletion, relevant
retrieval, abstention, ChromaDB outage and embedding failure or timeout fallback, empty and irrelevant vector
results, manifest mismatch, citation validation, invented-number detection, LLM-failure fallback, dataset
duplicate, inconsistency and answerability checks, export round-trips, Adaption status and error handling,
download parsing, and metric correctness.

## Measured on the sample set (retrieval only, no LLM)

On the 24 hand-written golden questions (`evaluation/golden_questions.json`), with the three synthetic sample documents:

| Condition | Hit rate@6 | MRR | Correct abstention | False abstention | Recovered requests |
|---|---|---|---|---|---|
| Normal | 100% | 0.95 | 100% (5/5) | 0% | 0 |
| ChromaDB outage (simulated) | 100% | 0.97 | 100% (5/5) | 10.5% (2/19) | 24/24 |

Limitations: this is a tiny synthetic corpus. The relevance thresholds were checked against this same set,
so expect lower numbers on real documents. Re-run the Evaluation page on your own documents.

## Sample documents

`scripts/make_sample_docs.py` creates three PDFs for a **fictional** institution (regulations with a table and
a bar chart, a syllabus with a diagram, and an admission notice with a scanned page). They are not real policies.

## Project layout

```
app.py                 Streamlit entry point
raguard/               config, ingestion, indexes, retrieval controller, answering, LLM client,
                       data lab, Adaption client, evaluation, fault injection, service facade
ui/                    one module per page + shared components
scripts/               sample document generator
evaluation/            golden question set
tests/                 pytest suite
data/                  runtime data (uploads, indexes, datasets, eval runs) - not committed
```
