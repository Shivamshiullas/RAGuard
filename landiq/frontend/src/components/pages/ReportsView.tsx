import React from 'react';
import { FileText, Download, Printer, BrainCircuit, AlertTriangle, ListChecks } from 'lucide-react';
import { ProjectInfo, AcquisitionCase, PageView } from '../../types';
import type { ApiHealth } from '../../api/client';
import { IllustrativeBadge, PredictionChip } from '../common/StatusChips';

interface ReportsViewProps {
  project: ProjectInfo;
  cases: AcquisitionCase[];
  health: ApiHealth | null;
  onNavigate: (page: PageView) => void;
}

const ADVERSE: [string, (c: AcquisitionCase) => boolean][] = [
  ['Legal dispute / court proceeding', (c) => /^(Dispute|In Court)/.test(c.legalStatus)],
  ['Compensation pending or disputed', (c) => /^(Pending|Disputed)/.test(c.compensationStatus)],
  ['Approval / clearance delayed or pending', (c) => /^(Delayed|Pending|Under Review)/.test(c.approvalStatus)],
  ['R&R below 70% complete', (c) => c.rrProgress !== null && c.rrProgress < 70],
  ['Conflicting source records', (c) => Object.values(c.fieldStatus).includes('CONFLICT')],
];

export const ReportsView: React.FC<ReportsViewProps> = ({ project, cases, health, onNavigate }) => {
  const count = (r: string) => cases.filter((c) => c.riskCategory === r).length;
  const focus = project.isDemo ? cases.filter((c) => c.riskCategory === 'HIGH') : cases;
  const drivers = ADVERSE.map(([name, test]) => ({ name, n: focus.filter(test).length })).sort((a, b) => b.n - a.n);
  const maxN = Math.max(1, ...drivers.map((d) => d.n));
  const prediction = health?.prediction ?? { status: 'NOT_READY' as const, reason: 'Backend status unavailable.' };
  const priority = cases
    .flatMap((c) => c.recommendations.filter((a) => a.priority === 'HIGH PRIORITY').map((a) => ({ c, a })))
    .slice(0, 4);

  const exportBriefing = () => {
    const lines = [
      `LANDIQ Executive Briefing — ${project.name} (${project.code})`,
      `Generated: ${new Date().toISOString()}`,
      project.isDemo ? 'DATA: ILLUSTRATIVE SYNTHETIC DEMO — not real records.' : 'DATA: fused from uploaded PDFs and GIS layers.',
      `Prediction model: ${prediction.status} — ${prediction.reason}`,
      '',
      `Cases: ${cases.length}` + (project.isDemo ? ` (high ${count('HIGH')}, medium ${count('MEDIUM')}, low ${count('LOW')}, illustrative)` : ''),
      '',
      `Most common adverse statuses (${project.isDemo ? 'among high-risk cases' : 'all cases'}; descriptive counts, not model importance):`,
      ...drivers.map((d) => `  - ${d.name}: ${d.n}`),
      '',
      'Priority actions (for human review):',
      ...priority.map(({ c, a }) => `  - ${c.id}: ${a.title} — owner: ${a.targetAuthority}`),
      '',
      'Limitations: no trained prediction model (uploaded cases use a rule-based scorecard); no accuracy is claimed; recommendations are decision support, not legal determinations.',
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `landiq-briefing-${project.code}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6 pb-12 animate-in fade-in duration-300">
      <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-bold uppercase tracking-wider bg-slate-100 text-slate-700 px-2.5 py-0.5 rounded-full flex items-center gap-1.5">
              <FileText className="h-3 w-3" />
              Executive Decision Briefing
            </span>
            {project.isDemo ? <IllustrativeBadge /> : <span className="text-[11px] text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md">Uploaded records</span>}
          </div>
          <h1 className="font-display text-2xl md:text-3xl font-extrabold text-slate-900 tracking-tight mt-1.5">Executive Risk & Intelligence Dossier</h1>
          <p className="text-xs md:text-sm text-slate-500 mt-0.5">Evidence summary and decision-support brief for {project.name}.</p>
        </div>
        <div className="flex items-center gap-3 print:hidden">
          <button onClick={() => window.print()} className="flex items-center gap-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 px-3.5 py-2 rounded-xl text-xs font-semibold border border-slate-200 transition-colors">
            <Printer className="h-3.5 w-3.5" />
            <span>Print Dossier</span>
          </button>
          <button onClick={exportBriefing} className="flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-xs transition-all">
            <Download className="h-3.5 w-3.5" />
            <span>Export Executive Summary</span>
          </button>
        </div>
      </div>

      <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs space-y-5">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-indigo-600" />
            <h3 className="font-display font-bold text-base text-slate-900">Model & Pipeline Status</h3>
          </div>
          <PredictionChip status={prediction.status} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
            <span className="text-[10px] uppercase font-bold text-slate-400">Primary Classifier</span>
            <div className="font-bold text-slate-900 mt-1">{prediction.status === 'READY' ? 'Configured model' : 'Not available'}</div>
            <div className="text-slate-500 mt-1">{prediction.reason}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
            <span className="text-[10px] uppercase font-bold text-slate-400">Baseline Comparison</span>
            <div className="font-bold text-slate-900 mt-1">Not evaluated</div>
            <div className="text-slate-500 mt-1">No accuracy is reported until a real evaluation exists.</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
            <span className="text-[10px] uppercase font-bold text-slate-400">Explainability</span>
            <div className="font-bold text-slate-900 mt-1">Additive contributions</div>
            <div className="text-slate-500 mt-1">Only from the configured model; demo SHAP values are labelled placeholders.</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
            <span className="text-[10px] uppercase font-bold text-slate-400">Evidence Engine</span>
            <div className="font-bold text-slate-900 mt-1">RAG over PDFs + GIS</div>
            <div className="text-slate-500 mt-1">
              Retrieval: {health ? (health.vector_store ? 'vector + lexical' : 'lexical only') : 'unknown'}; SQLite + local files.
            </div>
          </div>
        </div>

        <div className="pt-2">
          <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-1">
            Most common adverse statuses {project.isDemo ? '(among high-risk demo cases)' : '(all cases)'}
          </h4>
          <p className="text-[11px] text-slate-500 mb-3">Descriptive counts from case records, not model feature importance.</p>
          <div className="space-y-2.5">
            {drivers.map((d) => (
              <div key={d.name} className="flex items-center gap-3 text-xs">
                <span className="w-64 font-semibold text-slate-700 truncate">{d.name}</span>
                <div className="flex-1 bg-slate-100 h-2.5 rounded-full overflow-hidden">
                  <div className="bg-indigo-600 h-full rounded-full" style={{ width: `${(100 * d.n) / maxN}%` }} />
                </div>
                <span className="w-16 font-mono font-bold text-slate-800 text-right">{d.n} / {focus.length}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs space-y-4">
          <h3 className="font-display font-bold text-base text-slate-900">Corridor Summary</h3>
          <div className="space-y-3 text-xs">
            {[
              ['Corridor code', project.code],
              ['Cases analysed', String(cases.length)],
              ...(project.isDemo
                ? [['High / Medium / Low (illustrative)', `${count('HIGH')} / ${count('MEDIUM')} / ${count('LOW')}`]]
                : [['Good / Partial / Poor evidence', `${cases.filter((c) => c.dataQuality === 'GOOD').length} / ${cases.filter((c) => c.dataQuality === 'PARTIAL').length} / ${cases.filter((c) => c.dataQuality === 'POOR').length}`]]),
              ['Cases with parcel geometry', String(cases.filter((c) => c.polygonCoords.length).length)],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-200">
                <span className="text-slate-600">{k}:</span>
                <strong className="text-slate-900 font-mono">{v}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs space-y-4">
          <h3 className="font-display font-bold text-base text-slate-900 flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-blue-600" /> Priority Actions for Review
          </h3>
          <div className="space-y-2.5 text-xs text-slate-700">
            {priority.length === 0 && <p className="text-slate-500">No high-priority actions.</p>}
            {priority.map(({ c, a }) => (
              <button
                key={`${c.uid}-${a.id}`}
                onClick={() => onNavigate('high-risk-cases')}
                className="w-full text-left flex items-start gap-2.5 p-3 rounded-xl bg-rose-50/60 border border-rose-100"
              >
                <span className="h-2 w-2 rounded-full bg-rose-600 mt-1 shrink-0" />
                <span>
                  <strong>{c.id}:</strong> {a.title} <span className="text-slate-500">— {a.targetAuthority}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-white p-6 rounded-2xl border border-amber-200 shadow-2xs space-y-3">
        <h3 className="font-display font-bold text-base text-slate-900 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-600" /> Methodology & Limitations
        </h3>
        <ul className="list-disc pl-5 text-xs text-slate-600 space-y-1.5">
          <li>Facts are extracted from PDFs with page-level provenance. Scanned pages are read by OCR (local RapidOCR, then a vision LLM if configured); OCR-derived facts are marked and should be checked against the scan. A document is NEEDS_OCR only if no engine can read it.</li>
          <li>GIS layers are validated (CRS, geometry) and reprojected to WGS84; unreferenced map images are never treated as precise parcels.</li>
          <li>Cases and parcels are joined only by exact identifiers; ambiguous matches require user confirmation; conflicting records are kept, not resolved.</li>
          <li>No labelled historical dataset exists yet, so no trained model, accuracy or SHAP value exists. Uploaded cases are scored by a transparent rule-based scorecard (fixed weights on legal, compensation, approval and R&R status; rules-v1); cases with fewer than two known statuses stay NOT_READY.</li>
          {project.isDemo && <li>All demo corridor figures, trends, geometries and SHAP-style values are synthetic and illustrative.</li>}
          <li>Recommended actions are decision support for human review, not legal determinations; LANDIQ sends nothing to any authority.</li>
        </ul>
      </div>
    </div>
  );
};
