# LANDIQ — land-acquisition intelligence (prototype)

LANDIQ analyses land-acquisition and infrastructure-corridor bottlenecks from two kinds of input:

- **Selectable-text PDFs** (case dossiers, awards, tribunal orders, notices)
- **GIS data** (GeoJSON, zipped Shapefile, GeoPackage, KML; map images/PDFs as visual references only)

A persisted, bounded orchestrator runs a PDF agent and a map agent independently, indexes the text for retrieval-augmented answers, fuses evidence into cases by verified identifiers, and gates predictions. Every value shown for a real case links to a document page or map feature. Missing values stay **UNKNOWN**, conflicting sources stay **CONFLICT**, and without a trained model predictions are **NOT_READY**.

The React frontend reproduces the SIH 2026 LANDIQ screens (Overview, High-Risk Cases, Case Deep Dive, Risk Analysis, Recommended Actions, GIS Parcel Map, Executive Briefing) and adds **Data & Analysis Jobs**.

```
landiq/
├── backend/            FastAPI (/api/v1), agents, orchestrator, RAG, fusion, tests
│   ├── landiq/
│   │   ├── api.py           HTTP routes
│   │   ├── orchestrator.py  persisted decide→act→record loop, retries, checkpoints, recovery
│   │   ├── pdf_agent.py     PyMuPDF extraction, chunking, facts with page provenance
│   │   ├── map_agent.py     GIS validation (CRS, geometry), reprojection, spatial relations
│   │   ├── retrieval.py     SQLite FTS5 (exact/lexical) + ChromaDB vectors, RRF fusion, fallback rules
│   │   ├── rag.py           cited answers, citation validation, abstention
│   │   ├── fusion.py        cases from verified joins; conflicts; ambiguous matches
│   │   ├── prediction.py    NOT_READY / DEMO_ONLY / READY gate
│   │   ├── actions.py       evidence-backed recommendations for human review
│   │   ├── demo.py          synthetic demo corridor (one consistent dataset)
│   │   ├── storage.py       SQLite repository (swap for PostgreSQL/PostGIS later)
│   │   └── schemas.py       Pydantic models for everything
│   └── tests/          61 tests incl. failure injection and restart recovery
├── frontend/           React 19 + Vite + Tailwind v4 + Leaflet + Recharts + lucide-react
└── Dockerfile          single-container build (backend serves the built frontend)
```

## Run locally (Windows PowerShell)

Requires Python 3.12 and Node.js 20+. From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r landiq\backend\requirements.txt

# Optional: GEMINI_API_KEY in .env (repo root) to phrase RAG answers. See landiq\backend\.env.example.

cd landiq\backend
python -m uvicorn landiq.api:app --port 8000
```

Second terminal:

```powershell
cd landiq\frontend
npm ci
npm run dev          # http://localhost:5173 (proxies /api to :8000)
```

**Single server:** `npm run build` in `landiq\frontend`, restart the backend, open http://127.0.0.1:8000.

The synthetic demo corridor is seeded on first start. To analyse your own data: **Data & Analysis Jobs → Create project → upload PDFs and GIS files → Run analysis job**.

## Deploy

```bash
docker build -t landiq ./landiq
docker run -p 8000:8000 -e GEMINI_API_KEY=... -v landiq-data:/app/backend/storage landiq
```

The Dockerfile was written for this layout but has **not been built in this environment** (Docker was not available). Deployment notes:

- **Persistent volume** for `backend/storage/` (SQLite, uploads, quarantine, vector index, logs). Losing it loses jobs and checkpoints.
- **One instance only.** SQLite and the in-process job runner are not shared across replicas. Scaling out means PostgreSQL/PostGIS behind `storage.py` and an external job queue.
- **Secrets via environment variables** (`GEMINI_API_KEY`); never commit `.env`.
- **No authentication yet.** Put it behind an authenticating reverse proxy (and HTTPS) before exposing it; uploads and jobs are open to anyone who can reach the API.
- The local embedding model (~80 MB) is downloaded on first use; the Docker image pre-downloads it.

## How a job runs

`POST /projects/{id}/analysis-jobs` returns **202** immediately. The job runner then loops, choosing one whitelisted action at a time from the persisted state:

| Action | What it does |
|---|---|
| `RUN_AGENTS` | PDF and map agents run concurrently, each input separately. Output is schema-validated, then checkpointed. |
| `REEXTRACT_PAGES` | Pages with text but no facts are re-read once in block order (bounded). |
| `CHECK_RETRIEVAL` | Probes the indexes; records SUCCEEDED / DEGRADED / FAILED. |
| `FUSE` | Builds cases from validated facts + features; records conflicts and ambiguous matches. |
| `INVESTIGATE_CONFLICT` | Retrieves more evidence for each conflict (bounded). Never picks a value. |
| `CHECK_PREDICTION` | Prediction-readiness gate. |
| `FINALIZE` | SUCCEEDED, PARTIAL, NEEDS_CLARIFICATION or FAILED (with remediation). |

No model output selects actions or calls tools. Budgets: steps, wall time, attempts per input, conflict investigations, page re-extractions, file sizes, page and feature counts.

### Fault tolerance and failsafes

| Situation | Behaviour |
|---|---|
| PDF agent fails | Map results kept; case statuses stay UNKNOWN; job PARTIAL |
| Map agent fails | PDF results kept; spatial conclusions disabled |
| Transient error / timeout | Retried with exponential backoff, at most `AGENT_MAX_ATTEMPTS` |
| Invalid file (corrupt PDF, missing `.prj`, bad CRS) | No retry; structured error with remediation; file quarantined |
| Invalid geometry | Feature quarantined; map PARTIAL (FAILED if none valid) |
| Agent returns schema-invalid output | Rejected; never stored or fused |
| Scanned PDF | `NEEDS_OCR` (OCR not in scope) |
| Vector store down | Lexical-only retrieval if enabled (DEGRADED); otherwise `UNAVAILABLE` |
| LLM down / uncited answer | Retrieved evidence only (`EVIDENCE_ONLY`), no unsupported answer |
| Conflicting sources | Field CONFLICT, both values with sources, "Reconcile" action |
| Parcel matches several cases | Not merged; job NEEDS_CLARIFICATION until the user answers |
| No trained model | Prediction NOT_READY, all numbers null |
| Server restart | RUNNING jobs resume; checkpointed inputs are not re-processed |
| Instructions inside documents | Treated as quoted data; never change behaviour |

## API (`/api/v1`)

| Method | Route | |
|---|---|---|
| GET | `/health` | retrieval health, prediction readiness, active faults |
| GET/POST | `/projects` | list / create (`{name, corridor_id}`) |
| GET | `/projects/{id}/summary` | counts derived from cases |
| POST | `/projects/{id}/documents` | PDF upload (400/404/413/415) |
| POST | `/projects/{id}/maps` | GIS or map image upload |
| GET | `/projects/{id}/inputs` | uploaded files and status |
| POST | `/projects/{id}/analysis-jobs` | start job → **202**; idempotent (`Idempotency-Key` header optional) |
| GET | `/projects/{id}/jobs`, `/jobs/{job_id}` | per-agent state, attempts, checkpoints, errors, audit |
| GET | `/jobs/{job_id}/results` | partial or complete validated outputs |
| POST | `/jobs/{job_id}/cancel` | cancel a running job |
| GET | `/projects/{id}/cases`, `/cases/{case_id}` | cases; detail includes facts with provenance and conflicts |
| POST | `/cases/{case_id}/ask`, `/projects/{id}/ask` | cited RAG answer |
| GET | `/projects/{id}/map-features` | Leaflet-ready GeoJSON (EPSG:4326) |
| POST | `/projects/{id}/clarifications` | answer an ambiguous match (`{match_id, case_id}`) |
| POST | `/actions/{action_id}/workflow` | record review status (nothing is sent anywhere) |

Interactive docs: http://127.0.0.1:8000/docs

## Tests

```powershell
cd landiq\backend
python -m pytest            # 61 tests, ~1 minute

cd ..\frontend
npm run build               # type-check + production build
npm run lint
```

Coverage includes PDF facts and page provenance, `NEEDS_OCR`, corrupt/encrypted PDFs, all GIS formats, CRS rejection, invalid-geometry quarantine, unreferenced images, independent agent failures, bounded retries and timeouts, invalid output rejection, fusion failure, step budget, restart recovery from checkpoints, conflicts, ambiguous matches and clarification, retrieval fallback rules, citation validation, prediction gate (NOT_READY / READY / stale / missing features), API status codes, idempotency, and demo data consistency.

## Prediction

No labelled historical dataset exists, so no model ships. `MODEL_PATH` can point to a JSON logistic-model bundle (`model_version`, `trained_at`, `evaluated: true`, `evaluation`, `required_features`, `coefficients`, `feature_means`, `intercept`). The prediction is READY only if the bundle is evaluated, fresh, and every required feature is KNOWN for the case; explanations are the model's exact additive contributions. No pickles are loaded.

## Demo data

The **Delhi-Mumbai Express Corridor (Package 4)** project is synthetic: 840 cases (650 low / 162 medium / 28 high), generated with a fixed seed around the eight prototype hero cases (#0472 = 82% illustrative). All counts, percentages and the trend are computed from this one dataset and labelled *Illustrative Data*. Its predictions are DEMO_ONLY with null numeric fields; its SHAP-style values are labelled placeholders. The corridor is read-only.

## Limitations

- OCR is not implemented (scanned PDFs → NEEDS_OCR).
- Fact extraction is rule-based (labelled lines are VALIDATED; free-text inferences are UNVERIFIED). Unusual document layouts may yield few facts.
- Georeferenced rasters/GeoPDFs are not parsed; only vector GIS gives precise geometry.
- No authentication or multi-tenant separation.
- Single-process job runner; durability comes from SQLite checkpoints, not from the thread pool.
- The frontend bundle is ~900 KB (no code splitting yet).
