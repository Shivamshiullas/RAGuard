import React from 'react';
import { ShieldAlert, ShieldCheck, Ban } from 'lucide-react';
import { ApiError_, ApiJob } from '../../api/client';

// ---- Failsafe report ------------------------------------------------------------------

interface FailsafeRow {
  severity: 'error' | 'degraded';
  source: string;
  problem: string;
  action: string;
  fix?: string | null;
}

// Warning text -> what LANDIQ did about it.
const WARNING_ACTIONS: [RegExp, string][] = [
  [/attempt \d+ failed .*retrying/i, 'Transient failure: retried automatically with exponential backoff.'],
  [/invalid geometry .*quarantined|no geometry and was quarantined/i, 'Bad feature quarantined; the valid features were kept.'],
  [/read by OCR/i, 'Scanned pages were read by OCR; their values are flagged for checking against the scan.'],
  [/no georeference/i, 'Kept as a visual reference only; no parcel geometry or distances are derived from it.'],
  [/without readable text were skipped/i, 'Unreadable pages skipped; the rest of the document was used.'],
  [/OCR page limit/i, 'OCR stopped at the page limit to stay within the time budget.'],
  [/No corridor alignment/i, 'Distance and intersection were not computed rather than guessed.'],
  [/declares no CRS; WGS84 assumed/i, 'WGS84 assumed, as the file format requires.'],
  [/could not be tied to a single case/i, 'Ambiguous facts were not merged into any case.'],
  [/No validated spatial data/i, 'Spatial conclusions are disabled for these cases.'],
];

const errorRow = (e: ApiError_, fallbackSource: string): FailsafeRow => ({
  severity: 'error',
  source: e.filename ?? fallbackSource,
  problem: `${e.code}: ${e.message}`,
  action: e.failsafe ?? (e.transient ? 'Retried with backoff, then gave up on this input; other results were kept.' : 'Recorded; the rest of the job continued.'),
  fix: e.remediation,
});

const warningRow = (w: string, source: string): FailsafeRow => ({
  severity: 'degraded',
  source,
  problem: w,
  action:
    WARNING_ACTIONS.find(([re]) => re.test(w))?.[1] ??
    (source === 'Retrieval' ? 'Retrieval fell back to the remaining index (DEGRADED) instead of failing.' : 'Recorded as a warning; processing continued.'),
});

function failsafeRows(job: ApiJob): FailsafeRow[] {
  const rows: FailsafeRow[] = [
    ...job.pdf_agent.errors.map((e) => errorRow(e, 'PDF agent')),
    ...job.map_agent.errors.map((e) => errorRow(e, 'Map agent')),
    ...job.errors.map((e) => errorRow(e, 'Orchestrator')),
    ...job.pdf_agent.warnings.map((w) => warningRow(w, 'PDF agent')),
    ...job.map_agent.warnings.map((w) => warningRow(w, 'Map agent')),
    ...job.retrieval.warnings.map((w) => warningRow(w, 'Retrieval')),
    ...job.fusion.warnings.map((w) => warningRow(w, 'Fusion')),
  ];
  const failed = [job.pdf_agent, job.map_agent].filter((a) => a.state === 'FAILED').length;
  const ran = [job.pdf_agent, job.map_agent].filter((a) => a.state !== 'SKIPPED').length;
  if (failed === 1 && ran === 2) {
    const [bad, good] = job.pdf_agent.state === 'FAILED' ? ['PDF', 'map'] : ['map', 'PDF'];
    rows.push({
      severity: 'degraded',
      source: 'Orchestrator',
      problem: `The ${bad} agent failed.`,
      action: `Agents are independent: the ${good} agent's validated results were kept and the job finished PARTIAL.`,
    });
  }
  if (job.clarifications.length) {
    rows.push({
      severity: 'degraded',
      source: 'Fusion',
      problem: `${job.clarifications.length} parcel(s) match more than one case.`,
      action: 'Not merged into any case until you answer the question below (job NEEDS CLARIFICATION).',
    });
  }
  return rows;
}

export const FailsafeReport: React.FC<{ job: ApiJob }> = ({ job }) => {
  const rows = failsafeRows(job);
  if (!rows.length) {
    return (
      <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4" /> No failsafe was needed: every input was processed normally.
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-slate-200 overflow-hidden">
      <div className="px-4 py-2.5 bg-slate-900 text-white text-xs font-bold flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-amber-300" /> Failsafes triggered ({rows.length})
        <span className="font-normal text-slate-300">what went wrong, and what LANDIQ did instead of failing or guessing</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="bg-slate-50 text-slate-500 uppercase text-[10px]">
            <tr>
              <th className="text-left px-3 py-2">Input / stage</th>
              <th className="text-left px-3 py-2">What went wrong</th>
              <th className="text-left px-3 py-2">Failsafe response</th>
              <th className="text-left px-3 py-2">How to fix</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r, i) => (
              <tr key={i} className={r.severity === 'error' ? 'bg-rose-50/40' : 'bg-amber-50/30'}>
                <td className="px-3 py-2 font-semibold text-slate-800 align-top whitespace-nowrap">
                  <span className={`inline-block h-2 w-2 rounded-full mr-1.5 ${r.severity === 'error' ? 'bg-rose-500' : 'bg-amber-500'}`} />
                  {r.source}
                </td>
                <td className="px-3 py-2 text-slate-700 align-top">{r.problem}</td>
                <td className="px-3 py-2 text-slate-900 align-top">{r.action}</td>
                <td className="px-3 py-2 text-slate-500 italic align-top">{r.fix ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ---- Upload results ---------------------------------------------------------------------

export interface UploadResult {
  file: string;
  ok: boolean;
  httpStatus?: number;
  message: string;
}

export const UploadResults: React.FC<{ results: UploadResult[] }> = ({ results }) => {
  if (!results.length) return null;
  return (
    <div className="space-y-1.5">
      {results.map((r, i) =>
        r.ok ? (
          <div key={i} className="text-[11px] text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-1.5">
            <b>{r.file}</b>: {r.message}
          </div>
        ) : (
          <div key={i} className="text-[11px] bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 space-y-0.5">
            <div className="flex items-center gap-1.5 font-bold text-rose-800">
              <Ban className="h-3.5 w-3.5" /> {r.file} — rejected at upload{r.httpStatus ? ` (HTTP ${r.httpStatus})` : ''}
            </div>
            <div className="text-slate-700">{r.message}</div>
            <div className="text-slate-500">Failsafe: the file was checked before storage and never stored, so it cannot reach the agents.</div>
          </div>
        ),
      )}
    </div>
  );
};
