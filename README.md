# College Assistant (multimodal RAG)

A college chatbot that answers student questions from the college's official documents, with a citation for every fact. Students can type a question or attach a screenshot of a notice; admins upload and manage the documents the assistant answers from.

- **Backend** (`backend/`): FastAPI, ChromaDB with local MiniLM embeddings, BM25 keyword search, PyMuPDF / python-docx extraction, RapidOCR, Gemini and/or Ollama for planning and answers, SQLite for metadata.
- **Frontend** (`frontend/`): React + Vite + TypeScript, student chat and an admin document area.

Built to `College_Multimodal_RAG_Backend_Implementation_Plan_v2.pdf` (phases 1–10).

## Quick start (Windows PowerShell)

Requires Python 3.12 and Node.js 20+.

```powershell
# 1. Backend dependencies (from the repository root)
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt

# 2. Configure: put GEMINI_API_KEY (and optionally Ollama settings) in .env at the repo root.
#    See backend\.env.example for every setting. Change ADMIN_PASSWORD before sharing the app.

# 3. Load the fictional sample documents (safe to rerun)
cd backend
python -m college_rag.seed

# 4. Start the API on http://127.0.0.1:8000
python -m uvicorn college_rag.api:app --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite forwards `/api` to the backend.

**Single server instead:** run `npm run build` in `frontend/` once; the backend then serves the built app at http://127.0.0.1:8000.

**Admin:** click *Admin sign in* and use `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env` (defaults `admin` / `admin123` for local use only).

## How a question is answered

```
message (+ optional screenshot)
  -> router: greeting/thanks/small talk ............ direct reply, no retrieval
             unclear / unrelated .................... clarifying question / polite decline
             college question ....................... 1 RAG task
             several questions ...................... up to 5 tasks (parallel, or after their dependencies)
  -> per task: negative-result cache check -> text agent or image agent
       text agent:  hybrid search (ChromaDB vectors + BM25, rank-fused) -> grounded answer with [n] citations
       image agent: validate -> OCR -> enhance & retry -> vision model (optional) -> same search
  -> citations checked against the retrieved passages -> one combined answer
```

Every reply includes `status`, `sources` (file + page + snippet), `warnings`, `tasks`, `agents`, `recovery` and a `requestId`.

| Status | Meaning |
|---|---|
| `general` | Small talk answered directly (no retrieval) |
| `success` | Answer fully grounded in cited documents |
| `partial` | Some parts answered, or answered via the keyword-search fallback |
| `no_evidence` | The documents don't contain the answer (nothing is guessed) |
| `degraded` | Generator unavailable or answer unverifiable; source passages shown instead |
| `failed` | Search unavailable; safe failure message |
| `clarification` / `declined` | Unclear or out-of-scope message |

### Fault tolerance

| Failure | What happens |
|---|---|
| ChromaDB / embeddings fail | Retry once, then BM25 over the local SQLite text cache |
| LLM fails or times out | Next model/provider in the chain (Gemini main → Gemini lite → Ollama); if all fail, the relevant passages are returned with a warning |
| Answer cites nothing / invalid sources | Answer rejected; passages shown instead |
| OCR reads too little | Image enhanced and OCR'd again, then the vision model (if available) |
| Image path fails | Text agent with the typed question and any partial OCR text |
| Text path fails and a screenshot exists | One attempt via the image agent |

Outages are never cached as "no answer". Users only see short messages; full details go to `backend/storage/logs/backend.log`.

### Negative-result cache

A question that completed retrieval but found no evidence is cached against the current knowledge-base generation (normalized text + semester/year filters, with a TTL). Repeat questions skip retrieval. Indexing, replacing, activating or deactivating any document bumps the generation, so the next ask searches again.

## Admin document pipeline

Upload (PDF, DOCX, TXT, PNG, JPG up to 25 MB) → validate type/size/integrity → reject exact duplicates → extract text per page → OCR pages with no selectable text → heading/paragraph-aware chunks (~500 tokens, ~75 overlap, never across pages) → embed into ChromaDB and the SQLite text cache → *Indexed*. The admin screen polls and shows each stage.

Uploading *as a new version* keeps history; only the newest indexed version of each active document is searched. If a new version fails, the previous one stays live. After a restart, jobs that were mid-processing are marked failed with a *Reprocess* button.

## Configuration

Settings come from `.env` in the repo root (or `backend/.env`). Main ones:

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | – | Gemini access |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` | `gemini-flash-latest` / `gemini-flash-lite-latest` | Tried in order |
| `LLM_CHAIN` | `gemini,ollama` | Provider order |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | `http://localhost:11434` / `qwen2.5:3b` | Local model |
| `OLLAMA_VISION_MODEL` | empty | Set only for a model that accepts images |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin123` | Admin sign-in |
| `TOP_K`, `MIN_SIMILARITY` | `6`, `0.25` | Retrieval |
| `MAX_SUBTASKS`, `TASK_CONCURRENCY` | `5`, `3` | Router limits |
| `NEGATIVE_CACHE_TTL_S` | 7 days | Negative cache safety net |
| `FAULTS` | empty | Simulate outages: `chroma,embedding,llm,ocr,bm25,vision` |

All data (uploads, ChromaDB, SQLite, logs) lives in `backend/storage/`, which is git-ignored.

## API

| Method | Path | |
|---|---|---|
| POST | `/api/chat` | multipart: `message`, optional `image` (PNG/JPG ≤ 5 MB) |
| GET | `/api/health` | provider, vector store and index status |
| POST | `/api/admin/login` | `{username, password}` → bearer token |
| GET | `/api/documents` | admin: documents with versions and stages |
| POST | `/api/documents` | admin, multipart: `file`, `title`, `category`, `semester`, `academicYear`, `effectiveDate`, `replacesId` |
| POST | `/api/documents/{id}/reprocess` | admin |
| POST | `/api/documents/{id}/active` | admin: `{active: bool}` |

Interactive docs: http://127.0.0.1:8000/docs

## Tests

```powershell
cd backend
python -m pytest
```

64 tests use a scripted fake LLM and real ChromaDB/OCR. They cover PDF/TXT/DOCX/scanned PDF/image ingestion, invalid uploads, duplicates and versions, greetings making zero retrieval calls, a three-part question producing one answer, parallel vs dependent task order, negative-cache reuse and invalidation, ChromaDB outage → BM25, LLM outage → evidence only, OCR failure → vision / cross-agent recovery, total failure, citation validation, conflicting versions, restart persistence and the HTTP API.

## Sample documents

`backend/sample_docs/` holds documents for a **fictional** "Northfield Institute of Technology" (fees, academic calendar, campus information, regulations, admissions notice, a syllabus and a scanned scholarship notice). Replace them with real documents through the admin screen, and edit `frontend/src/config/branding.ts` for the college name and logo.
