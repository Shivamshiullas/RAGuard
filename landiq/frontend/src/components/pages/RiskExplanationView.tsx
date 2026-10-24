import React from 'react';
import { BrainCircuit, AlertTriangle, ShieldCheck, ArrowRight, Ban, Database } from 'lucide-react';
import { AcquisitionCase, PageView, ShapContribution } from '../../types';
import { IllustrativeBadge, PredictionChip } from '../common/StatusChips';

interface RiskExplanationViewProps {
  caseData: AcquisitionCase;
  onNavigate: (page: PageView) => void;
}

const FEATURE_LABELS: Record<string, string> = {
  legal_dispute: 'Legal dispute',
  compensation_pending: 'Compensation pending',
  clearance_pending: 'Clearance pending',
  compensation_disbursed_pct: 'Compensation disbursed',
  rr_progress_pct: 'R&R progress',
  project_progress_pct: 'Project progress',
  legal_status: 'Legal status',
  compensation_status: 'Compensation status',
  clearance_status: 'Approval / clearance status',
  rr_status: 'R&R status',
};

const ContributionCard: React.FC<{ label: string; value: number; description?: string; unit: string }> = ({ label, value, description, unit }) => {
  const positive = value > 0;
  return (
    <div className={`p-5 rounded-xl border space-y-3 ${positive ? 'border-rose-200 bg-rose-50/30' : 'border-blue-200 bg-blue-50/40'}`}>
      <div className="flex items-center justify-between gap-2">
        <span className={`text-xs font-bold uppercase ${positive ? 'text-rose-800' : 'text-blue-900'}`}>{label}</span>
        <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${positive ? 'bg-rose-100 text-rose-800' : 'bg-blue-100 text-blue-800'}`}>
          {positive ? '+' : ''}{value.toFixed(2)} {unit}
        </span>
      </div>
      <div className="w-full bg-slate-200 h-2.5 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${positive ? 'bg-rose-500' : 'bg-blue-500'}`} style={{ width: `${Math.min(Math.abs(value) * 220, 100)}%` }} />
      </div>
      {description && <p className="text-xs text-slate-600 leading-relaxed">{description}</p>}
    </div>
  );
};

export const RiskExplanationView: React.FC<RiskExplanationViewProps> = ({ caseData, onNavigate }) => {
  const pred = caseData.prediction;
  const placeholders: ShapContribution[] = caseData.isSynthetic ? caseData.shapContributions : [];
  const modelContribs = pred.status === 'READY' && pred.explanation ? Object.entries(pred.explanation.contributions) : [];
  const rulesBased = pred.modelVersion?.startsWith('rules') ?? false;

  return (
    <div className="space-y-6 pb-12">
      <div className="bg-white p-6 rounded-xl border border-slate-200/90 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 flex items-center gap-1.5">
              <BrainCircuit className="h-3.5 w-3.5 text-indigo-600" />
              Explainable AI (XAI)
            </span>
            <PredictionChip status={pred.status} />
            {caseData.isSynthetic && <IllustrativeBadge text="Illustrative placeholder attribution" />}
          </div>
          <h1 className="text-2xl font-semibold text-slate-900 tracking-tight mt-1">
            Risk drivers for Case {caseData.id}
          </h1>
          <p className="text-xs md:text-sm text-slate-500 mt-0.5">
            {pred.status === 'READY'
              ? rulesBased
                ? `Additive contributions from the ${pred.modelVersion} rule-based scorecard (fixed weights, not a trained model).`
                : `Additive contributions from model ${pred.modelVersion} for this case's validated features.`
              : 'Explanations are shown only when they come from a trained, evaluated model and this case\'s actual inputs.'}
          </p>
        </div>
        <button onClick={() => onNavigate('recommended-actions')} className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-sm transition-all">
          <ShieldCheck className="h-3.5 w-3.5" />
          <span>View Recommended Actions</span>
        </button>
      </div>

      {pred.status !== 'READY' && (
        <div className="p-6 rounded-xl bg-slate-50 border border-slate-300 shadow-sm flex items-start gap-4">
          <div className="h-10 w-10 rounded-xl bg-slate-700 text-white flex items-center justify-center shrink-0">
            <Ban className="h-5 w-5" />
          </div>
          <div className="space-y-1.5">
            <h3 className="font-display font-bold text-base text-slate-900">No model explanation is available ({pred.status})</h3>
            <p className="text-xs text-slate-700">{pred.reason}</p>
            {pred.missingFeatures.length > 0 && <p className="text-xs text-slate-600">Missing or conflicting features: {pred.missingFeatures.join(', ')}</p>}
            <p className="text-[11px] text-slate-500">
              LANDIQ does not fabricate SHAP values, probabilities or accuracy figures. Real attributions require a model trained on labelled
              historical acquisition outcomes, evaluated, and configured via MODEL_PATH.
            </p>
          </div>
        </div>
      )}

      {modelContribs.length > 0 && (
        <div className="bg-white p-6 rounded-xl border border-slate-200/90 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3 text-xs font-mono">
            <h3 className="font-display font-bold text-lg text-slate-900">{rulesBased ? 'Scorecard attribution (log-odds)' : 'Model attribution (log-odds)'}</h3>
            <span>Baseline: {pred.explanation!.baseline_logit.toFixed(2)} → p = {((pred.delayProbability ?? 0) * 100).toFixed(1)}%</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {modelContribs.map(([name, v]) => <ContributionCard key={name} label={FEATURE_LABELS[name] ?? name} value={v} unit="logit" />)}
          </div>
        </div>
      )}

      {caseData.isSynthetic && (
        <div className="bg-white p-6 rounded-xl border border-slate-200/90 shadow-sm space-y-5">
          <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0" />
            <p className="text-xs text-amber-900">
              These contributions are illustrative placeholders for this synthetic demo case. They were not computed by a trained model and must
              not be used for decisions.
            </p>
          </div>
          {placeholders.length ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {placeholders.map((c) => <ContributionCard key={c.label} label={c.label} value={c.value} description={c.description} unit="(illustrative)" />)}
            </div>
          ) : (
            <p className="text-xs text-slate-500">This synthetic case has no placeholder attribution.</p>
          )}
        </div>
      )}

      <div className="p-5 rounded-xl bg-slate-900 text-white space-y-3">
        <div className="flex items-center gap-2 border-b border-slate-800 pb-3">
          <Database className="h-4 w-4 text-cyan-400" />
          <span className="text-xs font-bold uppercase tracking-wider">Model status</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
          <div className="p-3 rounded-lg bg-slate-800/80 border border-slate-700">
            <span className="text-[10px] uppercase font-bold text-cyan-400">Prediction model</span>
            <div className="font-bold text-white text-sm">{pred.modelVersion ?? 'None configured'}</div>
            <div className="text-[11px] text-slate-400">
              {rulesBased ? 'Rule-based scorecard: expert-set weights, not trained on outcomes.' : 'No labelled historical dataset is available yet.'}
            </div>
          </div>
          <div className="p-3 rounded-lg bg-slate-800/80 border border-slate-700">
            <span className="text-[10px] uppercase font-bold text-slate-400">Reported accuracy</span>
            <div className="font-bold text-slate-300 text-sm">Not reported</div>
            <div className="text-[11px] text-slate-400">Shown only after a real evaluation.</div>
          </div>
          <div className="p-3 rounded-lg bg-slate-800/80 border border-slate-700">
            <span className="text-[10px] uppercase font-bold text-amber-400">Explanation method</span>
            <div className="font-bold text-white text-sm">Additive (linear) contributions</div>
            <div className="text-[11px] text-slate-300">
              {rulesBased ? 'Exact: the score is the sum of these weights.' : 'Exact for the supported linear model bundle.'}
            </div>
          </div>
        </div>
      </div>

      <div className="pt-2 flex items-center justify-between">
        <button onClick={() => onNavigate('case-details')} className="text-xs font-semibold text-slate-500 hover:text-slate-800 transition-colors">
          ← Back to Case {caseData.id} Details
        </button>
        <button onClick={() => onNavigate('recommended-actions')} className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-xl text-xs font-bold shadow-md transition-all">
          <span>Proceed to Recommended Actions</span>
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};
