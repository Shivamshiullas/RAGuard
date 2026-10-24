// Typed client for the LANDIQ backend (/api/v1). In development Vite proxies
// /api to http://127.0.0.1:8000; set VITE_API_BASE_URL for another origin.

const BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/v1${path}`, { ...init, headers });
  } catch {
    throw new ApiError('Cannot reach the LANDIQ backend. Is it running on port 8000?', 0);
  }
  if (!res.ok) {
    let message = `Request failed (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body.detail === 'string') message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ');
    } catch {
      // keep generic message
    }
    throw new ApiError(message, res.status);
  }
  return (await res.json()) as T;
}

// ---- Backend shapes (snake_case, as served) -----------------------------------

export interface ApiProject {
  project_id: string;
  name: string;
  corridor_id: string;
  description: string | null;
  is_demo: boolean;
  created_at: string;
}

export interface ApiFieldValue {
  value: string | number | string[] | null;
  status: 'KNOWN' | 'UNVERIFIED' | 'UNKNOWN' | 'CONFLICT';
  facts: string[];
  alternatives: (string | number)[];
}

export interface ApiPrediction {
  status: 'NOT_READY' | 'DEMO_ONLY' | 'READY';
  delay_probability: number | null;
  estimated_delay_days: number | null;
  model_version: string | null;
  feature_snapshot_id: string | null;
  explanation_ref: string | null;
  reason: string;
  missing_features: string[];
}

export interface ApiEvidenceRef {
  fact_id: string | null;
  document_id: string | null;
  page: number | null;
  map_id: string | null;
  feature_id: string | null;
  snippet: string | null;
}

export interface ApiAction {
  action_id: string;
  case_id: string;
  title: string;
  rationale: string;
  evidence: ApiEvidenceRef[];
  suggested_owner: string;
  priority: 'HIGH' | 'MEDIUM' | 'MONITOR';
  workflow_status: 'PROPOSED' | 'IN_REVIEW' | 'ESCALATED' | 'RESOLVED' | 'DISMISSED';
  requires_human_review: true;
}

export interface ApiCase {
  case_id: string;
  case_ref: string;
  project_id: string;
  corridor_id: string | null;
  parcel_ids: string[];
  is_synthetic: boolean;
  fields: Record<string, ApiFieldValue>;
  geometry_refs: { map_id: string; feature_id: string }[];
  spatial: AcquisitionSpatial;
  conflicts: string[];
  data_quality: 'GOOD' | 'PARTIAL' | 'POOR';
  warnings: string[];
  prediction: ApiPrediction;
  actions: ApiAction[];
  illustrative: Record<string, unknown> | null;
}

export interface AcquisitionSpatial {
  features?: number;
  area_hectares_computed?: number;
  intersects_alignment?: boolean | null;
  min_distance_to_alignment_m?: number | null;
  zone?: string | null;
}

export interface ApiFact {
  fact_id: string;
  field: string;
  value: string;
  normalized_value: string | number | null;
  case_id: string | null;
  validation_status: 'VALIDATED' | 'CONFLICT' | 'UNVERIFIED';
  extraction_method: string;
  provenance:
    | { kind: 'document'; document_id: string; filename: string; page: number; chunk_id: string | null; snippet: string }
    | { kind: 'map'; map_id: string; filename: string; layer: string; feature_id: string; crs: string | null };
}

export interface ApiConflict {
  conflict_id: string;
  case_id: string;
  field: string;
  values: { value: string | number; fact_id: string; source: string }[];
  status: 'OPEN' | 'INVESTIGATED';
  note: string | null;
}

export interface ApiCaseDetail {
  case: ApiCase;
  facts: Record<string, ApiFact>;
  conflicts: ApiConflict[];
}

export interface ApiSummary {
  project_id: string;
  is_demo: boolean;
  total: number;
  counts?: { HIGH: number; MEDIUM: number; LOW: number };
  percent?: { HIGH: number; MEDIUM: number; LOW: number };
  trend?: { month: string; highRisk: number; avgDelayProb: number }[];
  label?: string;
  data_quality?: { GOOD: number; PARTIAL: number; POOR: number };
  conflicts?: number;
  unresolved_matches?: number;
  prediction?: string;
}

export interface ApiHealth {
  status: string;
  vector_store: boolean;
  lexical_fallback: boolean;
  prediction: { status: 'NOT_READY' | 'DEMO_ONLY' | 'READY'; reason: string };
  faults: string[];
}

export interface ApiError_ {
  code: string;
  message: string;
  stage: string | null;
  transient: boolean;
  remediation: string | null;
  input_id?: string | null;
  filename?: string | null;
  failsafe?: string | null;
  at: string;
}

export interface ApiFailsafe {
  agent: 'pdf' | 'gis';
  trigger: string;
  input_id: string | null;
  filename: string | null;
  reason: string;
  fallback: string;
  recovery: 'SUCCEEDED' | 'PARTIAL' | 'FAILED';
  at: string;
}

export interface ApiAgentStatus {
  state: 'PENDING' | 'RUNNING' | 'RETRYING' | 'SUCCEEDED' | 'PARTIAL' | 'FAILED' | 'NEEDS_OCR' | 'SKIPPED';
  attempts: number;
  max_attempts: number;
  checkpoint: boolean;
  checkpoint_at: string | null;
  inputs: string[];
  errors: ApiError_[];
  warnings: string[];
  failsafes: ApiFailsafe[];
}

export interface ApiStage {
  state: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'DEGRADED' | 'FAILED' | 'SKIPPED';
  checkpoint: boolean;
  detail: string | null;
  warnings: string[];
}

export interface ApiMatch {
  match_id: string;
  kind: string;
  key: string;
  candidates: string[];
  source: string;
  question: string;
}

export interface ApiJob {
  job_id: string;
  project_id: string;
  state: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'PARTIAL' | 'NEEDS_CLARIFICATION' | 'FAILED' | 'CANCELLED';
  document_ids: string[];
  map_ids: string[];
  pdf_agent: ApiAgentStatus;
  map_agent: ApiAgentStatus;
  retrieval: ApiStage;
  fusion: ApiStage;
  prediction_readiness: 'NOT_READY' | 'DEMO_ONLY' | 'READY';
  prediction_reason: string | null;
  steps_used: number;
  step_budget: number;
  errors: ApiError_[];
  warnings: string[];
  clarifications: ApiMatch[];
  audit: { at: string; step: number; action: string; outcome: string; detail: string | null }[];
  remediation: string | null;
  created_at: string;
  updated_at: string;
  resumed_count: number;
}

export interface ApiInput {
  id: string;
  kind: 'document' | 'map';
  filename: string;
  size_bytes: number;
  status: 'STORED' | 'QUARANTINED' | 'DUPLICATE';
  detail: string | null;
  created_at: string;
}

export interface ApiUpload {
  id: string;
  filename: string;
  status: 'STORED' | 'QUARANTINED' | 'DUPLICATE';
  detail: string | null;
}

export interface ApiChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface ApiChatCitation {
  label: string;
  chunk_id: string;
  document: string;
  page: number;
  snippet: string;
}

export interface ApiChatAnswer {
  status: 'ANSWERED' | 'EVIDENCE_ONLY' | 'INSUFFICIENT_EVIDENCE';
  answer: string | null;
  citations: ApiChatCitation[];
  note: string | null;
}

export interface ApiRagAnswer {
  question: string;
  status: 'ANSWERED' | 'INSUFFICIENT_EVIDENCE' | 'UNAVAILABLE' | 'EVIDENCE_ONLY';
  answer: string | null;
  claims_unverified: boolean;
  evidence: { evidence_id: string; filename: string; page: number; snippet: string; case_ids: string[]; retrieval: string }[];
  conflicts: string[];
  retrieval: { state: string; methods: string[]; warnings: string[]; coverage: string };
  warnings: string[];
}

export interface GeoFeature {
  type: 'Feature';
  id: string;
  geometry: { type: string; coordinates: unknown };
  properties: {
    feature_id: string;
    map_id: string;
    layer: string;
    role: 'parcel' | 'alignment' | 'other';
    parcel_id: string | null;
    case_ref: string | null;
    case_id: string | null;
    survey_numbers: string[];
    zone: string | null;
    area_hectares: number | null;
    distance_to_alignment_m: number | null;
    intersects_alignment: boolean | null;
    synthetic: boolean;
    risk_category: string | null;
  };
}

export interface FeatureCollection {
  type: 'FeatureCollection';
  features: GeoFeature[];
  synthetic: boolean;
}

// ---- Calls ------------------------------------------------------------------------

export const api = {
  health: () => request<ApiHealth>('/health'),
  projects: () => request<ApiProject[]>('/projects'),
  createProject: (name: string, corridorId: string) =>
    request<ApiProject>('/projects', { method: 'POST', body: JSON.stringify({ name, corridor_id: corridorId }) }),
  summary: (projectId: string) => request<ApiSummary>(`/projects/${projectId}/summary`),
  cases: (projectId: string) => request<ApiCase[]>(`/projects/${projectId}/cases`),
  caseDetail: (caseId: string) => request<ApiCaseDetail>(`/cases/${encodeURIComponent(caseId)}`),
  mapFeatures: (projectId: string) => request<FeatureCollection>(`/projects/${projectId}/map-features`),
  inputs: (projectId: string) => request<ApiInput[]>(`/projects/${projectId}/inputs`),
  upload: (projectId: string, kind: 'documents' | 'maps', file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<ApiUpload>(`/projects/${projectId}/${kind}`, { method: 'POST', body: form });
  },
  startJob: (projectId: string) => request<ApiJob>(`/projects/${projectId}/analysis-jobs`, { method: 'POST' }),
  jobs: (projectId: string) => request<ApiJob[]>(`/projects/${projectId}/jobs`),
  job: (jobId: string) => request<ApiJob>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) => request<ApiJob>(`/jobs/${jobId}/cancel`, { method: 'POST' }),
  clarify: (projectId: string, matchId: string, caseRef: string | null) =>
    request<ApiMatch[]>(`/projects/${projectId}/clarifications`, {
      method: 'POST',
      body: JSON.stringify({ match_id: matchId, case_id: caseRef }),
    }),
  ask: (caseId: string, question: string) =>
    request<ApiRagAnswer>(`/cases/${encodeURIComponent(caseId)}/ask`, { method: 'POST', body: JSON.stringify({ question }) }),
  chat: (projectId: string, question: string, options: { caseId?: string | null; history?: ApiChatTurn[] } = {}) =>
    request<ApiChatAnswer>(`/projects/${projectId}/chat`, {
      method: 'POST',
      body: JSON.stringify({ question, case_id: options.caseId ?? null, history: options.history ?? [] }),
    }),
  setWorkflow: (actionId: string, status: ApiAction['workflow_status']) =>
    request<{ note: string }>(`/actions/${actionId}/workflow`, { method: 'POST', body: JSON.stringify({ status }) }),
};
