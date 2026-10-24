// UNRATED: no prediction exists (NOT_READY) — never shown as low/medium/high.
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'UNRATED';

export type FieldStatus = 'KNOWN' | 'UNVERIFIED' | 'UNKNOWN' | 'CONFLICT';
export type PredictionStatus = 'NOT_READY' | 'DEMO_ONLY' | 'READY';

export interface ShapContribution {
  feature: string;
  label: string;
  value: number; // e.g., +0.31
  impact: 'high_positive' | 'moderate_positive' | 'low_positive' | 'negative';
  description: string;
}

export interface RecommendationAction {
  id: string;
  priority: 'HIGH PRIORITY' | 'MEDIUM PRIORITY' | 'MONITOR';
  title: string;
  reason: string;
  suggestedAction: string;
  status: 'Pending' | 'In Review' | 'Escalated' | 'Completed';
  targetAuthority: string;
  estimatedImpactDays: number | null;
  evidence?: EvidenceItem[];
  /** Backend workflow id; absent for illustrative demo actions. */
  backendId?: string;
}

/** One piece of source evidence behind a case field. */
export interface EvidenceItem {
  factId?: string;
  kind: 'document' | 'map';
  label: string; // "dossier.pdf p.3" or "parcels.geojson · parcels · feature 2"
  snippet?: string;
  validation?: string;
}

export interface ConflictInfo {
  conflictId: string;
  field: string;
  values: { value: string; source: string }[];
  status: 'OPEN' | 'INVESTIGATED';
  note?: string | null;
}

export interface Prediction {
  status: PredictionStatus;
  delayProbability: number | null;
  estimatedDelayDays: number | null;
  modelVersion: string | null;
  reason: string;
  missingFeatures: string[];
  explanation: { baseline_logit: number; contributions: Record<string, number> } | null;
}

export interface AcquisitionCase {
  id: string; // case ref as written in records, e.g. "#0472"
  uid: string; // backend case_id (URL-safe)
  projectId: string;
  isSynthetic: boolean;
  zone: string;
  subDivision: string;
  surveyNo: string;
  villageName: string;
  district: string;
  areaHectares: number | null;
  /** Illustrative figure for synthetic demo cases only; null when no model output exists. */
  delayProbability: number | null;
  riskCategory: RiskLevel;
  legalStatus: string;
  legalDetails: string;
  compensationStatus: string;
  compensationDetails: string;
  compensationDisbursedPercent: number | null;
  approvalStatus: string;
  approvalDetails: string;
  rrProgress: number | null;
  rrDetails: string;
  projectProgress: number | null;
  estDelayDays: number | null;
  shapContributions: ShapContribution[];
  recommendations: RecommendationAction[];
  coordinates: [number, number] | null; // [lat, lng]
  polygonCoords: [number, number][];
  prediction: Prediction;
  dataQuality: 'GOOD' | 'PARTIAL' | 'POOR';
  warnings: string[];
  fieldStatus: Record<string, FieldStatus>;
  evidence: Record<string, EvidenceItem[]>;
  conflicts: ConflictInfo[];
  spatial: {
    features?: number;
    area_hectares_computed?: number;
    intersects_alignment?: boolean | null;
    min_distance_to_alignment_m?: number | null;
    zone?: string | null;
  };
  parcelIds: string[];
}

export interface ProjectInfo {
  id: string;
  name: string;
  code: string;
  isDemo: boolean;
  description: string;
  totalCases: number;
  lowRiskCases: number;
  medRiskCases: number;
  highRiskCases: number;
}

export interface RiskTrendPoint {
  month: string;
  highRisk: number;
  avgDelayProb: number;
}

export type PageView =
  | 'dashboard'
  | 'high-risk-cases'
  | 'case-details'
  | 'risk-explanation'
  | 'recommended-actions'
  | 'gis-map'
  | 'reports'
  | 'chat'
  | 'ingestion';
