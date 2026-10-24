import React, { useEffect, useState } from 'react';
import {
  Scale,
  Coins,
  FileCheck2,
  Home,
  TrendingUp,
  BrainCircuit,
  ShieldCheck,
  MapPin,
  ArrowRight,
  Calendar,
  FileText,
  GitCompare,
  AlertTriangle,
  MessageSquareText,
  Loader2,
} from 'lucide-react';
import { AcquisitionCase, PageView, ProjectInfo, EvidenceItem } from '../../types';
import { RiskBadge } from '../common/RiskBadge';
import { FieldStatusChip, IllustrativeBadge, PredictionChip } from '../common/StatusChips';
import { api, ApiRagAnswer } from '../../api/client';
import { FIELD_LABELS } from '../../api/adapter';

interface CaseDetailsViewProps {
  caseData: AcquisitionCase;
  project: ProjectInfo;
  onNavigate: (page: PageView) => void;
}

const EvidenceList: React.FC<{ items?: EvidenceItem[] }> = ({ items }) =>
  items && items.length ? (
    <ul className="mt-2 space-y-1">
      {items.slice(0, 3).map((e, i) => (
        <li key={i} className="text-[10px] text-slate-500 flex gap-1">
          <FileText className="h-3 w-3 shrink-0 text-slate-400 mt-0.5" />
          <span>
            <span className="font-mono text-slate-700">{e.label}</span>
            {e.validation === 'UNVERIFIED' && <span className="text-amber-700"> (unverified)</span>}
          </span>
        </li>
      ))}
    </ul>
  ) : null;

interface StatusCardProps {
  icon: React.ElementType;
  title: string;
  value: string;
  chip?: string;
  detail: string;
  progress?: number | null;
  tone: 'rose' | 'amber' | 'indigo' | 'blue' | 'slate';
  status?: string;
  evidence?: EvidenceItem[];
}

const TONES = {
  rose: 'border-rose-200/80 text-rose-700',
  amber: 'border-amber-200/80 text-amber-700',
  indigo: 'border-indigo-200/80 text-indigo-700',
  blue: 'border-blue-200/80 text-blue-700',
  slate: 'border-slate-200 text-slate-600',
};

const StatusCard: React.FC<StatusCardProps> = ({ icon: Icon, title, value, chip, detail, progress, tone, status, evidence }) => (
  <div className={`bg-white p-5 rounded-xl border shadow-2xs transition-all ${TONES[tone].split(' ')[0]}`}>
    <div className={`flex items-center justify-between text-xs font-bold uppercase tracking-wider mb-2 ${TONES[tone].split(' ')[1]}`}>
      <span className="flex items-center gap-1.5">
        <Icon className="h-4 w-4" />
        {title}
      </span>
      {chip && <span className="bg-slate-100 text-slate-700 px-2 py-0.5 rounded text-[10px] normal-case">{chip}</span>}
    </div>
    <div className="font-display text-lg font-bold text-slate-900 flex items-center gap-2">
      {value}
      <FieldStatusChip status={status} />
    </div>
    {progress !== undefined && progress !== null && (
      <div className="w-full bg-slate-100 h-1.5 rounded-full mt-2 overflow-hidden">
        <div className="bg-indigo-600 h-full" style={{ width: `${progress}%` }} />
      </div>
    )}
    <p className="text-[11px] text-slate-500 mt-1.5 line-clamp-3">{detail}</p>
    <EvidenceList items={evidence} />
  </div>
);

const toneFor = (value: string, bad: string[], good: string[]): StatusCardProps['tone'] =>
  value === 'Conflict' || bad.some((b) => value.startsWith(b)) ? 'rose' : good.some((g) => value.startsWith(g)) ? 'blue' : value.startsWith('Unknown') ? 'slate' : 'amber';

export const CaseDetailsView: React.FC<CaseDetailsViewProps> = ({ caseData, project, onNavigate }) => {
  const [animated, setAnimated] = useState(0);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<ApiRagAnswer | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  const prob = caseData.delayProbability;
  const rulesBased = caseData.prediction.modelVersion?.startsWith('rules') ?? false;

  useEffect(() => {
    setAnswer(null);
    setAskError(null);
    if (prob === null) return;
    setAnimated(0);
    const start = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const t = Math.min((now - start) / 1200, 1);
      setAnimated(Math.round((1 - Math.pow(1 - t, 3)) * prob));
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [caseData.uid, prob]);

  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim().length < 3) return;
    setAsking(true);
    setAskError(null);
    try {
      setAnswer(await api.ask(caseData.uid, question.trim()));
    } catch (err) {
      setAskError(err instanceof Error ? err.message : 'The question could not be answered.');
    } finally {
      setAsking(false);
    }
  };

  const ev = caseData.evidence;
  const fs = caseData.fieldStatus;

  return (
    <div className="space-y-6 pb-12 animate-in fade-in duration-300">
      <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-extrabold bg-blue-100 text-blue-800 px-2.5 py-0.5 rounded-md border border-blue-200">
              CASE {caseData.id}
            </span>
            <span className="text-xs font-semibold text-slate-500">
              {caseData.zone} • {project.name}
            </span>
            {caseData.isSynthetic ? <IllustrativeBadge text="Synthetic demo case" /> : (
              <span className="text-[11px] font-semibold bg-slate-100 text-slate-700 px-2 py-0.5 rounded">Data quality: {caseData.dataQuality}</span>
            )}
          </div>
          <h1 className="font-display text-2xl md:text-3xl font-extrabold text-slate-900 tracking-tight mt-1.5 flex items-center gap-3 flex-wrap">
            <span>{caseData.villageName} Parcel Cluster</span>
            {caseData.subDivision && <span className="text-sm font-normal text-slate-400 font-mono">({caseData.subDivision})</span>}
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Survey Numbers: {caseData.surveyNo} • Recorded Area: {caseData.areaHectares ?? 'Unknown'}
            {caseData.areaHectares !== null && ' Hectares'} • District: {caseData.district}
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <button onClick={() => onNavigate('risk-explanation')} className="flex items-center gap-1.5 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 px-3.5 py-2 rounded-xl text-xs font-bold transition-all">
            <BrainCircuit className="h-4 w-4 text-indigo-600" />
            <span>Risk Explainability</span>
          </button>
          <button onClick={() => onNavigate('recommended-actions')} className="flex items-center gap-1.5 bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 px-3.5 py-2 rounded-xl text-xs font-bold transition-all">
            <ShieldCheck className="h-4 w-4 text-amber-700" />
            <span>Recommended Actions ({caseData.recommendations.length})</span>
          </button>
          <button onClick={() => onNavigate('gis-map')} className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white px-3.5 py-2 rounded-xl text-xs font-bold shadow-xs transition-all">
            <MapPin className="h-4 w-4 text-cyan-400" />
            <span>Locate on GIS Map</span>
          </button>
        </div>
      </div>

      {/* Prediction panel: illustrative figure for demo cases, readiness gate otherwise */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-rose-950 via-slate-900 to-indigo-950 text-white p-7 shadow-xl border border-rose-900/40">
        <div className="absolute top-0 right-0 -mt-8 -mr-8 h-48 w-48 rounded-full bg-rose-500/20 blur-3xl pointer-events-none" />
        <div className="relative z-10 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
          <div className="space-y-2 max-w-xl">
            <div className="flex items-center gap-2 flex-wrap">
              <PredictionChip status={caseData.prediction.status} />
              {caseData.isSynthetic && <span className="text-[11px] text-amber-300 italic">Illustrative figure — not model output</span>}
            </div>
            <h2 className="font-display text-lg font-bold tracking-tight text-slate-200 uppercase">
              {prob === null ? 'Delay prediction not available' : caseData.isSynthetic ? 'Illustrative delay probability' : rulesBased ? 'Rule-based delay risk' : 'Predicted delay probability'}
            </h2>
            <p className="text-xs text-slate-300 leading-relaxed">{caseData.prediction.reason}</p>
            {caseData.prediction.missingFeatures.length > 0 && (
              <p className="text-[11px] text-slate-400">Missing features: {caseData.prediction.missingFeatures.join(', ')}</p>
            )}
            {caseData.estDelayDays !== null && (
              <div className="pt-2 flex items-center gap-4 text-xs font-mono text-slate-300">
                <span className="flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5 text-rose-400" />
                  Est. Schedule Impact: <strong className="text-rose-300">+{caseData.estDelayDays} Days</strong>
                  {caseData.isSynthetic && <span className="text-amber-300">(illustrative)</span>}
                </span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-6 bg-slate-900/80 p-5 rounded-2xl border border-rose-500/30 shadow-inner">
            <div className="text-center">
              <div className="font-display text-6xl md:text-7xl font-black text-rose-400 tracking-tight flex items-baseline justify-center">
                {prob === null ? <span className="text-slate-500 text-5xl">—</span> : (
                  <>
                    <span>{animated}</span>
                    <span className="text-3xl font-bold text-rose-500/80 ml-1">%</span>
                  </>
                )}
              </div>
              <div className="mt-1">
                <RiskBadge level={caseData.riskCategory} size="lg" />
              </div>
            </div>
            <div className="h-20 w-px bg-slate-800" />
            <div className="space-y-1.5 text-xs text-slate-300">
              <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Hazard Level</div>
              <div className="font-semibold text-rose-300">
                {caseData.riskCategory === 'UNRATED' ? 'Not assessed' : caseData.isSynthetic ? `${caseData.riskCategory} (illustrative)` : rulesBased ? `${caseData.riskCategory} (rule-based)` : caseData.riskCategory}
              </div>
              <div className="text-[10px] text-slate-400 font-mono">Model: {caseData.prediction.modelVersion ?? 'none configured'}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatusCard icon={Scale} title="Legal Status" value={caseData.legalStatus} status={fs.legal_status} detail={caseData.legalDetails}
          tone={toneFor(caseData.legalStatus, ['Dispute', 'In Court'], ['Clear'])} evidence={ev.legal_status} />
        <StatusCard icon={Coins} title="Compensation" value={caseData.compensationStatus} status={fs.compensation_status}
          chip={caseData.compensationDisbursedPercent !== null ? `${caseData.compensationDisbursedPercent}% Paid` : undefined}
          detail={caseData.compensationDetails} tone={toneFor(caseData.compensationStatus, ['Pending', 'Disputed'], ['Disbursed'])}
          evidence={ev.compensation_status ?? ev.compensation_amount_cr} />
        <StatusCard icon={FileCheck2} title="Approval" value={caseData.approvalStatus} status={fs.clearance_status} detail={caseData.approvalDetails}
          tone={toneFor(caseData.approvalStatus, ['Delayed'], ['Cleared'])} evidence={ev.clearance_status} />
        <StatusCard icon={Home} title="R&R Progress" value={caseData.rrProgress !== null ? `${caseData.rrProgress}% Completed` : 'Unknown'}
          status={fs.rr_progress_pct} progress={caseData.rrProgress} detail={caseData.rrDetails} tone="indigo" evidence={ev.rr_progress_pct} />
        <StatusCard icon={TrendingUp} title="Civil Progress" value={caseData.projectProgress !== null ? `${caseData.projectProgress}%` : 'Unknown'}
          status={fs.project_progress_pct} progress={caseData.projectProgress}
          detail={caseData.isSynthetic ? 'Synthetic record.' : (ev.project_progress_pct?.[0]?.snippet ?? 'No evidence found in the analysed records.')}
          tone="blue" evidence={ev.project_progress_pct} />
      </div>

      {(caseData.conflicts.length > 0 || caseData.warnings.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {caseData.conflicts.length > 0 && (
            <div className="bg-white p-5 rounded-2xl border border-rose-200 shadow-2xs space-y-3">
              <h3 className="font-display font-bold text-sm text-rose-800 flex items-center gap-2">
                <GitCompare className="h-4 w-4" /> Conflicting records (not resolved automatically)
              </h3>
              {caseData.conflicts.map((c) => (
                <div key={c.conflictId} className="text-xs border border-rose-100 bg-rose-50/40 rounded-lg p-3 space-y-1">
                  <div className="font-bold text-slate-800">{FIELD_LABELS[c.field] ?? c.field}</div>
                  {c.values.map((v, i) => (
                    <div key={i} className="flex justify-between gap-2">
                      <span className="font-semibold text-rose-700">{v.value}</span>
                      <span className="font-mono text-[10px] text-slate-500">{v.source}</span>
                    </div>
                  ))}
                  {c.note && <p className="text-[11px] text-slate-500 italic pt-1">{c.note}</p>}
                </div>
              ))}
            </div>
          )}
          {caseData.warnings.length > 0 && (
            <div className="bg-white p-5 rounded-2xl border border-amber-200 shadow-2xs space-y-2">
              <h3 className="font-display font-bold text-sm text-amber-800 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4" /> Data-quality warnings
              </h3>
              <ul className="list-disc pl-5 text-xs text-slate-600 space-y-1">
                {caseData.warnings.map((w) => <li key={w}>{w}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {!caseData.isSynthetic && (
        <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <h3 className="font-display text-lg font-bold text-slate-900">EVIDENCE BEHIND THIS CASE</h3>
              <p className="text-xs text-slate-500">Every value links to the document page or map feature it came from. Missing values stay UNKNOWN.</p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[11px] uppercase text-slate-500 border-b border-slate-200">
                <tr><th className="py-2 pr-4">Field</th><th className="py-2 pr-4">Status</th><th className="py-2">Sources</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {Object.keys(FIELD_LABELS).filter((f) => fs[f] || ev[f]?.length).map((f) => (
                  <tr key={f} className="align-top">
                    <td className="py-2 pr-4 font-semibold text-slate-800">{FIELD_LABELS[f]}</td>
                    <td className="py-2 pr-4"><FieldStatusChip status={fs[f]} />{fs[f] === 'KNOWN' && <span className="text-emerald-700 font-bold text-[10px]">KNOWN</span>}</td>
                    <td className="py-2 space-y-1">
                      {(ev[f] ?? []).map((e, i) => (
                        <div key={i}>
                          <span className="font-mono text-[10px] text-blue-700">{e.label}</span>
                          {e.snippet && <span className="text-slate-500"> — “{e.snippet}”</span>}
                        </div>
                      ))}
                      {!ev[f]?.length && <span className="text-slate-400">Loading evidence…</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <form onSubmit={ask} className="pt-3 border-t border-slate-100 space-y-3">
            <label className="text-xs font-bold text-slate-800 flex items-center gap-2" htmlFor="ask-case">
              <MessageSquareText className="h-4 w-4 text-blue-600" /> Ask the case records (answers cite page-level evidence)
            </label>
            <div className="flex gap-2">
              <input id="ask-case" value={question} onChange={(e) => setQuestion(e.target.value)}
                placeholder={`e.g. What is the compensation award for ${caseData.id}?`}
                className="flex-1 px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/30" />
              <button disabled={asking || question.trim().length < 3} className="bg-blue-600 disabled:bg-slate-300 text-white px-4 py-2 rounded-lg text-xs font-bold flex items-center gap-1.5">
                {asking && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Ask
              </button>
            </div>
            {askError && <p className="text-xs text-rose-700">{askError}</p>}
            {answer && (
              <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 space-y-2 text-xs">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`font-bold px-2 py-0.5 rounded text-[10px] ${answer.status === 'ANSWERED' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>{answer.status.replace('_', ' ')}</span>
                  <span className="text-[10px] text-slate-500">Retrieval: {answer.retrieval.methods.join(' + ') || 'none'} ({answer.retrieval.state})</span>
                </div>
                {answer.answer ? <p className="text-slate-800 leading-relaxed">{answer.answer}</p> : (
                  <p className="text-slate-600">No answer is given without supporting evidence.{answer.evidence.length ? ' Retrieved evidence:' : ''}</p>
                )}
                {answer.evidence.map((e) => (
                  <div key={e.evidence_id} className="text-[11px] text-slate-600 border-l-2 border-blue-300 pl-2">
                    <span className="font-mono font-bold text-blue-700">[{e.evidence_id}] {e.filename} p.{e.page}</span> — {e.snippet}
                  </div>
                ))}
                {[...answer.warnings, ...answer.conflicts].map((w) => <p key={w} className="text-[11px] text-amber-700">⚠ {w}</p>)}
              </div>
            )}
          </form>
        </div>
      )}

      <div className="p-4 rounded-xl bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-blue-600 text-white flex items-center justify-center shrink-0">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h4 className="text-xs font-bold text-blue-950">
              {caseData.recommendations.length} recommended action(s) for Case {caseData.id}
            </h4>
            <p className="text-[11px] text-blue-700">Decision support for human review — not legal determinations.</p>
          </div>
        </div>
        <button onClick={() => onNavigate('recommended-actions')} className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-xs transition-all whitespace-nowrap">
          <span>Proceed to Recommended Actions</span>
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
};
