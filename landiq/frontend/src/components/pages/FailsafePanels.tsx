import React from 'react';
import { ShieldAlert, ShieldCheck, Ban, FileText, Map as MapIcon } from 'lucide-react';
import { ApiAgentStatus, ApiFailsafe, ApiJob } from '../../api/client';

// ---- Per-agent failsafe status ----------------------------------------------------------

type Recovery = ApiFailsafe['recovery'];

const RECOVERY_STYLE: Record<Recovery, string> = {
  SUCCEEDED: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  PARTIAL: 'bg-amber-100 text-amber-800 border-amber-300',
  FAILED: 'bg-rose-100 text-rose-800 border-rose-300',
};

const RECOVERY_LABEL: Record<Recovery, string> = {
  SUCCEEDED: 'Recovery succeeded',
  PARTIAL: 'Partially recovered',
  FAILED: 'Recovery failed',
};

const RecoveryBadge: React.FC<{ recovery: Recovery }> = ({ recovery }) => (
  <span className={`inline-block text-[10px] font-bold uppercase border px-2 py-0.5 rounded ${RECOVERY_STYLE[recovery]}`}>
    {RECOVERY_LABEL[recovery]}
  </span>
);

/** Overall outcome for an agent: succeeded only if every fallback succeeded. */
function overallRecovery(status: ApiAgentStatus): Recovery {
  if (status.failsafes.every((f) => f.recovery === 'SUCCEEDED')) return 'SUCCEEDED';
  if (status.state === 'FAILED' || status.state === 'NEEDS_OCR') return 'FAILED';
  return 'PARTIAL';
}

const AgentFailsafeCard: React.FC<{ title: string; icon: React.ElementType; status: ApiAgentStatus }> = ({ title, icon: Icon, status }) => {
  const triggered = status.failsafes.length > 0;
  const running = status.state === 'RUNNING' || status.state === 'RETRYING' || status.state === 'PENDING';
  return (
    <div className={`rounded-xl border p-4 space-y-3 ${triggered ? 'border-amber-300 bg-amber-50/30' : 'border-emerald-200 bg-emerald-50/30'}`}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="font-bold text-sm text-slate-900 flex items-center gap-1.5">
          <Icon className="h-4 w-4 text-blue-600" /> {title}
        </span>
        {triggered && <RecoveryBadge recovery={overallRecovery(status)} />}
      </div>

      <div className={`text-sm font-extrabold flex items-center gap-1.5 ${triggered ? 'text-amber-800' : 'text-emerald-700'}`}>
        {triggered ? <ShieldAlert className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
        {triggered ? `Failsafe Triggered: YES (${status.failsafes.length})` : 'Failsafe Triggered: NO.'}
      </div>
      {!triggered && (
        <p className="text-[11px] text-slate-500">
          {status.state === 'SKIPPED' ? 'Agent not run: no inputs of this type.' : running ? 'Agent still running; no failsafe so far.' : 'Every input was processed normally.'}
        </p>
      )}

      {status.failsafes.map((f, i) => (
        <dl key={i} className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-[11px] p-3 rounded-lg bg-white border border-slate-200">
          <dt className="font-semibold text-slate-500">Agent</dt>
          <dd className="text-slate-900">{f.agent === 'pdf' ? 'PDF Agent (PyMuPDF)' : 'GIS Agent'}</dd>
          <dt className="font-semibold text-slate-500">Input</dt>
          <dd className="text-slate-900 font-mono break-all">{f.filename ?? 'whole agent'}</dd>
          <dt className="font-semibold text-slate-500">Trigger</dt>
          <dd className="text-slate-900 font-mono">{f.trigger}</dd>
          <dt className="font-semibold text-slate-500">Reason</dt>
          <dd className="text-slate-800">{f.reason}</dd>
          <dt className="font-semibold text-slate-500">Fallback used</dt>
          <dd className="text-slate-800">{f.fallback}</dd>
          <dt className="font-semibold text-slate-500">Recovery</dt>
          <dd><RecoveryBadge recovery={f.recovery} /></dd>
        </dl>
      ))}
    </div>
  );
};

export const FailsafeStatusPanel: React.FC<{ job: ApiJob }> = ({ job }) => (
  <div className="space-y-2">
    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">Failsafe status</h4>
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <AgentFailsafeCard title="PDF Agent (PyMuPDF)" icon={FileText} status={job.pdf_agent} />
      <AgentFailsafeCard title="GIS Agent" icon={MapIcon} status={job.map_agent} />
    </div>
  </div>
);

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
