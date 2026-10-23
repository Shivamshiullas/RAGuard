// Converts backend records into the view model the pages render.
// Synthetic demo cases carry their figures under `illustrative`; uploaded cases
// are built only from evidence-backed fields. Missing values stay null/Unknown.

import type {
  AcquisitionCase,
  ConflictInfo,
  EvidenceItem,
  FieldStatus,
  Prediction,
  ProjectInfo,
  RecommendationAction,
  RiskLevel,
  ShapContribution,
} from '../types';
import type { ApiAction, ApiCase, ApiCaseDetail, ApiFact, ApiProject, ApiSummary, GeoFeature } from './client';

const STATUS_LABEL: Record<string, string> = {
  DISPUTE: 'Dispute',
  IN_COURT: 'In Court',
  PENDING_SETTLEMENT: 'Pending Settlement',
  CLEAR: 'Clear',
  PENDING: 'Pending',
  DISPUTED: 'Disputed',
  IN_PROGRESS: 'In Progress',
  DISBURSED: 'Disbursed',
  DELAYED: 'Delayed',
  UNDER_REVIEW: 'Under Review',
  CLEARED: 'Cleared',
  COMPLETED: 'Completed',
};

export const WORKFLOW_TO_UI: Record<ApiAction['workflow_status'], RecommendationAction['status']> = {
  PROPOSED: 'Pending',
  IN_REVIEW: 'In Review',
  ESCALATED: 'Escalated',
  RESOLVED: 'Completed',
  DISMISSED: 'Completed',
};

export const UI_TO_WORKFLOW: Record<RecommendationAction['status'], ApiAction['workflow_status']> = {
  Pending: 'PROPOSED',
  'In Review': 'IN_REVIEW',
  Escalated: 'ESCALATED',
  Completed: 'RESOLVED',
};

export function toProject(p: ApiProject, summary?: ApiSummary): ProjectInfo {
  return {
    id: p.project_id,
    name: p.name,
    code: p.corridor_id,
    isDemo: p.is_demo,
    description: p.description ?? '',
    totalCases: summary?.total ?? 0,
    lowRiskCases: summary?.counts?.LOW ?? 0,
    medRiskCases: summary?.counts?.MEDIUM ?? 0,
    highRiskCases: summary?.counts?.HIGH ?? 0,
  };
}

function prediction(c: ApiCase): Prediction {
  let explanation: Prediction['explanation'] = null;
  if (c.prediction.explanation_ref) {
    try {
      explanation = JSON.parse(c.prediction.explanation_ref);
    } catch {
      explanation = null;
    }
  }
  return {
    status: c.prediction.status,
    delayProbability: c.prediction.delay_probability,
    estimatedDelayDays: c.prediction.estimated_delay_days,
    modelVersion: c.prediction.model_version,
    reason: c.prediction.reason,
    missingFeatures: c.prediction.missing_features,
    explanation,
  };
}

function riskFromProbability(p: number | null): RiskLevel {
  if (p === null) return 'UNRATED';
  if (p >= 0.65) return 'HIGH';
  if (p >= 0.35) return 'MEDIUM';
  return 'LOW';
}

function centroid(ring: [number, number][]): [number, number] | null {
  if (!ring.length) return null;
  const lat = ring.reduce((s, p) => s + p[0], 0) / ring.length;
  const lng = ring.reduce((s, p) => s + p[1], 0) / ring.length;
  return [lat, lng];
}

/** First outer ring of a (Multi)Polygon as [lat, lng] pairs. */
export function outerRing(geometry: GeoFeature['geometry']): [number, number][] {
  const coords = geometry.coordinates as number[][][] | number[][][][];
  if (geometry.type === 'Polygon') return (coords as number[][][])[0].map(([lng, lat]) => [lat, lng]);
  if (geometry.type === 'MultiPolygon') return (coords as number[][][][])[0][0].map(([lng, lat]) => [lat, lng]);
  return [];
}

function factEvidence(f: ApiFact): EvidenceItem {
  const p = f.provenance;
  return p.kind === 'document'
    ? { factId: f.fact_id, kind: 'document', label: `${p.filename} p.${p.page}`, snippet: p.snippet, validation: f.validation_status }
    : { factId: f.fact_id, kind: 'map', label: `${p.filename} · ${p.layer} · ${p.feature_id}`, validation: f.validation_status };
}

function fromDemo(c: ApiCase): AcquisitionCase {
  const r = (c.illustrative ?? {}) as Record<string, unknown>;
  const recs = ((r.recommendations as Record<string, unknown>[]) ?? []).map(
    (a): RecommendationAction => ({
      id: String(a.id),
      priority: a.priority as RecommendationAction['priority'],
      title: String(a.title),
      reason: String(a.reason),
      suggestedAction: String(a.suggestedAction),
      status: a.status as RecommendationAction['status'],
      targetAuthority: String(a.targetAuthority),
      estimatedImpactDays: (a.estimatedImpactDays as number) ?? null,
    }),
  );
  return {
    id: c.case_ref,
    uid: c.case_id,
    projectId: c.project_id,
    isSynthetic: true,
    zone: String(r.zone ?? ''),
    subDivision: String(r.subDivision ?? ''),
    surveyNo: String(r.surveyNo ?? ''),
    villageName: String(r.villageName ?? ''),
    district: String(r.district ?? ''),
    areaHectares: (r.areaHectares as number) ?? null,
    delayProbability: (r.delayProbability as number) ?? null,
    riskCategory: (r.riskCategory as RiskLevel) ?? 'UNRATED',
    legalStatus: String(r.legalStatus ?? 'Unknown'),
    legalDetails: String(r.legalDetails ?? ''),
    compensationStatus: String(r.compensationStatus ?? 'Unknown'),
    compensationDetails: String(r.compensationDetails ?? ''),
    compensationDisbursedPercent: (r.compensationDisbursedPercent as number) ?? null,
    approvalStatus: String(r.approvalStatus ?? 'Unknown'),
    approvalDetails: String(r.approvalDetails ?? ''),
    rrProgress: (r.rrProgress as number) ?? null,
    rrDetails: String(r.rrDetails ?? ''),
    projectProgress: (r.projectProgress as number) ?? null,
    estDelayDays: (r.estDelayDays as number) ?? null,
    shapContributions: (r.shapContributions as ShapContribution[]) ?? [],
    recommendations: recs,
    coordinates: (r.coordinates as [number, number]) ?? null,
    polygonCoords: (r.polygonCoords as [number, number][]) ?? [],
    prediction: prediction(c),
    dataQuality: c.data_quality,
    warnings: c.warnings,
    fieldStatus: {},
    evidence: {},
    conflicts: [],
    spatial: c.spatial ?? {},
    parcelIds: c.parcel_ids,
  };
}

function fieldValue(c: ApiCase, name: string): { value: string | number | string[] | null; status: FieldStatus } {
  const f = c.fields[name];
  return f ? { value: f.value, status: f.status } : { value: null, status: 'UNKNOWN' };
}

function statusLabel(c: ApiCase, name: string): string {
  const { value, status } = fieldValue(c, name);
  if (status === 'CONFLICT') return 'Conflict';
  if (value === null || status === 'UNKNOWN') return 'Unknown';
  const label = STATUS_LABEL[String(value)] ?? String(value);
  return status === 'UNVERIFIED' ? `${label} (unverified)` : label;
}

function num(c: ApiCase, name: string): number | null {
  const { value, status } = fieldValue(c, name);
  return status === 'KNOWN' && typeof value === 'number' ? value : null;
}

function text(c: ApiCase, name: string): string {
  const { value } = fieldValue(c, name);
  if (Array.isArray(value)) return value.join(', ');
  return value === null ? '' : String(value);
}

function toAction(a: ApiAction): RecommendationAction {
  return {
    id: a.action_id,
    backendId: a.action_id,
    priority: a.priority === 'HIGH' ? 'HIGH PRIORITY' : a.priority === 'MEDIUM' ? 'MEDIUM PRIORITY' : 'MONITOR',
    title: a.title,
    reason: a.rationale,
    suggestedAction: 'Review the cited evidence and decide on the appropriate statutory route.',
    status: WORKFLOW_TO_UI[a.workflow_status],
    targetAuthority: a.suggested_owner,
    estimatedImpactDays: null,
    evidence: a.evidence.map((e) => ({
      factId: e.fact_id ?? undefined,
      kind: e.document_id ? 'document' : 'map',
      label: e.document_id ? `document ${e.document_id} p.${e.page}` : `map ${e.map_id} · ${e.feature_id}`,
      snippet: e.snippet ?? undefined,
    })),
  };
}

function fromEvidence(c: ApiCase, features: GeoFeature[]): AcquisitionCase {
  const pred = prediction(c);
  const ring = features
    .filter((f) => f.properties.case_id === c.case_id && f.properties.role === 'parcel')
    .map((f) => outerRing(f.geometry))
    .find((r) => r.length) ?? [];
  const missing = 'No evidence found in the analysed records.';
  return {
    id: c.case_ref,
    uid: c.case_id,
    projectId: c.project_id,
    isSynthetic: false,
    zone: c.spatial?.zone ?? 'Zone unknown',
    subDivision: c.parcel_ids.join(', '),
    surveyNo: text(c, 'survey_numbers') || 'Unknown',
    villageName: text(c, 'village') || 'Unknown village',
    district: text(c, 'district') || 'Unknown',
    areaHectares: num(c, 'area_hectares'),
    delayProbability: pred.status === 'READY' && pred.delayProbability !== null ? Math.round(pred.delayProbability * 100) : null,
    riskCategory: pred.status === 'READY' ? riskFromProbability(pred.delayProbability) : 'UNRATED',
    legalStatus: statusLabel(c, 'legal_status'),
    legalDetails: missing,
    compensationStatus: statusLabel(c, 'compensation_status'),
    compensationDetails: missing,
    compensationDisbursedPercent: num(c, 'compensation_disbursed_pct'),
    approvalStatus: statusLabel(c, 'clearance_status'),
    approvalDetails: missing,
    rrProgress: num(c, 'rr_progress_pct'),
    rrDetails: statusLabel(c, 'rr_status'),
    projectProgress: num(c, 'project_progress_pct'),
    estDelayDays: pred.status === 'READY' ? pred.estimatedDelayDays : null,
    shapContributions: [],
    recommendations: c.actions.map(toAction),
    coordinates: centroid(ring),
    polygonCoords: ring,
    prediction: pred,
    dataQuality: c.data_quality,
    warnings: c.warnings,
    fieldStatus: Object.fromEntries(Object.entries(c.fields).map(([k, v]) => [k, v.status])),
    evidence: {},
    conflicts: [],
    spatial: c.spatial ?? {},
    parcelIds: c.parcel_ids,
  };
}

export function toCase(c: ApiCase, features: GeoFeature[] = []): AcquisitionCase {
  return c.is_synthetic ? fromDemo(c) : fromEvidence(c, features);
}

/** Adds per-field evidence and conflicts from the case detail endpoint. */
export function withDetail(base: AcquisitionCase, detail: ApiCaseDetail): AcquisitionCase {
  const evidence: Record<string, EvidenceItem[]> = {};
  for (const [name, fv] of Object.entries(detail.case.fields)) {
    const items = fv.facts.map((id) => detail.facts[id]).filter(Boolean).map(factEvidence);
    // One source line can yield several facts (e.g. three survey numbers); show it once.
    evidence[name] = items.filter((e, i) => items.findIndex((x) => x.label === e.label && x.snippet === e.snippet) === i);
  }
  const conflicts: ConflictInfo[] = detail.conflicts.map((c) => ({
    conflictId: c.conflict_id,
    field: c.field,
    values: c.values.map((v) => ({ value: STATUS_LABEL[String(v.value)] ?? String(v.value), source: v.source })),
    status: c.status,
    note: c.note,
  }));
  const first = (name: string) => evidence[name]?.find((e) => e.snippet)?.snippet;
  return {
    ...base,
    evidence,
    conflicts,
    legalDetails: first('legal_status') ?? base.legalDetails,
    compensationDetails: first('compensation_status') ?? first('compensation_amount_cr') ?? base.compensationDetails,
    approvalDetails: first('clearance_status') ?? base.approvalDetails,
    rrDetails: first('rr_progress_pct') ?? first('rr_status') ?? base.rrDetails,
  };
}

export const FIELD_LABELS: Record<string, string> = {
  legal_status: 'Legal status',
  compensation_status: 'Compensation status',
  clearance_status: 'Approval / clearance',
  rr_status: 'R&R status',
  rr_progress_pct: 'R&R progress (%)',
  project_progress_pct: 'Project progress (%)',
  compensation_amount_cr: 'Compensation award (₹ Cr)',
  compensation_disbursed_pct: 'Compensation disbursed (%)',
  area_hectares: 'Recorded area (ha)',
  survey_numbers: 'Survey numbers',
  parcel_id: 'Parcel IDs',
  village: 'Village',
  district: 'District',
  notification_date: 'Notification date',
  hearing_date: 'Hearing date',
  deadline_date: 'Deadline',
};
