import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  UploadCloud,
  FileText,
  Map as MapIcon,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RotateCcw,
  HelpCircle,
  FolderPlus,
  ListTree,
} from 'lucide-react';
import { ProjectInfo } from '../../types';
import { api, ApiAgentStatus, ApiError, ApiInput, ApiJob, ApiStage } from '../../api/client';
import { PredictionChip } from '../common/StatusChips';
import { FailsafeReport, UploadResult, UploadResults } from './FailsafePanels';

interface IngestionViewProps {
  project: ProjectInfo;
  onProjectCreated: (projectId: string) => void;
  onDataChanged: () => void;
  onOpenCases: () => void;
}

const ACTIVE = new Set(['QUEUED', 'RUNNING']);

const STATE_STYLE: Record<string, string> = {
  SUCCEEDED: 'bg-emerald-100 text-emerald-800',
  PARTIAL: 'bg-amber-100 text-amber-800',
  DEGRADED: 'bg-amber-100 text-amber-800',
  NEEDS_CLARIFICATION: 'bg-indigo-100 text-indigo-800',
  NEEDS_OCR: 'bg-amber-100 text-amber-800',
  FAILED: 'bg-rose-100 text-rose-800',
  QUARANTINED: 'bg-rose-100 text-rose-800',
  RETRYING: 'bg-amber-100 text-amber-800',
  RUNNING: 'bg-blue-100 text-blue-800',
  QUEUED: 'bg-slate-100 text-slate-700',
  PENDING: 'bg-slate-100 text-slate-700',
  SKIPPED: 'bg-slate-100 text-slate-500',
  CANCELLED: 'bg-slate-200 text-slate-700',
};

const StateChip: React.FC<{ state: string }> = ({ state }) => (
  <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${STATE_STYLE[state] ?? 'bg-slate-100 text-slate-700'}`}>{state.replace('_', ' ')}</span>
);

const AgentCard: React.FC<{ title: string; icon: React.ElementType; status: ApiAgentStatus }> = ({ title, icon: Icon, status }) => (
  <div className="p-4 rounded-xl border border-slate-200 bg-white space-y-2 text-xs">
    <div className="flex items-center justify-between">
      <span className="font-bold text-slate-900 flex items-center gap-1.5"><Icon className="h-4 w-4 text-blue-600" />{title}</span>
      <StateChip state={status.state} />
    </div>
    <div className="grid grid-cols-3 gap-2 text-[11px] text-slate-600">
      <span>Inputs: <b>{status.inputs.length}</b></span>
      <span>Attempts: <b>{status.attempts}</b>{status.max_attempts ? ` (max ${status.max_attempts}/input)` : ''}</span>
      <span>Checkpoint: <b>{status.checkpoint ? 'saved' : '—'}</b></span>
    </div>
    {status.errors.map((e, i) => (
      <div key={i} className="p-2 rounded-lg bg-rose-50 border border-rose-100 text-[11px]">
        <div className="font-bold text-rose-800">{e.code}{e.transient ? ' (transient)' : ''}{e.filename ? ` · ${e.filename}` : ''}</div>
        <div className="text-slate-700">{e.message}</div>
        {e.remediation && <div className="text-slate-500 italic">Fix: {e.remediation}</div>}
      </div>
    ))}
    {status.warnings.slice(0, 4).map((w) => (
      <div key={w} className="text-[11px] text-amber-700">⚠ {w}</div>
    ))}
  </div>
);

const StageRow: React.FC<{ label: string; stage: ApiStage }> = ({ label, stage }) => (
  <div className="flex items-start justify-between gap-3 py-2 border-b border-slate-100 last:border-0 text-xs">
    <span className="font-semibold text-slate-700">{label}</span>
    <span className="text-right">
      <StateChip state={stage.state} />
      {stage.detail && <span className="block text-[11px] text-slate-500 mt-1">{stage.detail}</span>}
      {stage.warnings.slice(0, 3).map((w) => <span key={w} className="block text-[11px] text-amber-700">{w}</span>)}
    </span>
  </div>
);

export const IngestionView: React.FC<IngestionViewProps> = ({ project, onProjectCreated, onDataChanged, onOpenCases }) => {
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [inputs, setInputs] = useState<ApiInput[]>([]);
  const [jobs, setJobs] = useState<ApiJob[]>([]);
  const [job, setJob] = useState<ApiJob | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [uploads, setUploads] = useState<UploadResult[]>([]);
  const docRef = useRef<HTMLInputElement>(null);
  const mapRef = useRef<HTMLInputElement>(null);
  const wasActive = useRef(false);

  const refresh = useCallback(async () => {
    if (project.isDemo) return;
    try {
      const [ins, js] = await Promise.all([api.inputs(project.id), api.jobs(project.id)]);
      setInputs(ins);
      setJobs(js);
      setJob((cur) => js.find((j) => j.job_id === cur?.job_id) ?? js[0] ?? null);
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Could not load project inputs.' });
    }
  }, [project.id, project.isDemo]);

  useEffect(() => {
    setJob(null);
    void refresh();
  }, [refresh]);

  // Poll the selected job while it runs; refresh app data when it finishes.
  useEffect(() => {
    if (!job || !ACTIVE.has(job.state)) {
      if (wasActive.current && job) {
        wasActive.current = false;
        onDataChanged();
        void refresh();
      }
      return;
    }
    wasActive.current = true;
    const t = setTimeout(async () => {
      try {
        setJob(await api.job(job.job_id));
      } catch {
        // keep polling on transient errors
      }
    }, 1200);
    return () => clearTimeout(t);
  }, [job, onDataChanged, refresh]);

  const createProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy('project');
    setMessage(null);
    try {
      const p = await api.createProject(name.trim(), code.trim());
      setName('');
      setCode('');
      onProjectCreated(p.project_id);
      setMessage({ kind: 'ok', text: `Project "${p.name}" created. Upload documents and maps next.` });
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Could not create the project.' });
    } finally {
      setBusy(null);
    }
  };

  const upload = async (kind: 'documents' | 'maps', files: FileList | null) => {
    if (!files?.length) return;
    setBusy(kind);
    setMessage(null);
    const results: UploadResult[] = [];
    for (const file of Array.from(files)) {
      try {
        const res = await api.upload(project.id, kind, file);
        results.push({ file: file.name, ok: true, message: `${res.status}${res.detail ? ` — ${res.detail}` : ''}` });
      } catch (err) {
        results.push({
          file: file.name,
          ok: false,
          httpStatus: err instanceof ApiError && err.status ? err.status : undefined,
          message: err instanceof Error ? err.message : 'Upload failed.',
        });
      }
    }
    setUploads(results);
    if (docRef.current) docRef.current.value = '';
    if (mapRef.current) mapRef.current.value = '';
    setBusy(null);
    void refresh();
  };

  const startJob = async () => {
    setBusy('job');
    setMessage(null);
    try {
      const j = await api.startJob(project.id);
      setJob(j);
      setJobs((prev) => [j, ...prev.filter((x) => x.job_id !== j.job_id)]);
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Could not start the job.' });
    } finally {
      setBusy(null);
    }
  };

  const answer = async (matchId: string, caseRef: string | null) => {
    try {
      await api.clarify(project.id, matchId, caseRef);
      if (job) setJob(await api.job(job.job_id));
      onDataChanged();
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Could not save the answer.' });
    }
  };

  const createForm = (
    <form onSubmit={createProject} className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs space-y-3">
      <h3 className="font-display font-bold text-base text-slate-900 flex items-center gap-2"><FolderPlus className="h-4 w-4 text-blue-600" /> Create a project corridor</h3>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name, e.g. NH-48 Package 2"
          className="md:col-span-2 px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg" />
        <input required value={code} onChange={(e) => setCode(e.target.value)} pattern="[A-Za-z0-9._\-]+" title="Letters, digits, . _ -"
          placeholder="Corridor code, e.g. NHAI-48-P2" className="px-3 py-2 text-xs bg-slate-50 border border-slate-200 rounded-lg font-mono" />
      </div>
      <button disabled={busy === 'project'} className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white px-4 py-2 rounded-xl text-xs font-bold">
        {busy === 'project' ? 'Creating…' : 'Create project'}
      </button>
    </form>
  );

  return (
    <div className="space-y-6 pb-12 animate-in fade-in duration-300">
      <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs">
        <span className="text-[11px] font-bold uppercase tracking-wider bg-blue-50 text-blue-700 border border-blue-200 px-2.5 py-0.5 rounded-full inline-flex items-center gap-1.5">
          <UploadCloud className="h-3 w-3" /> Multimodal ingestion
        </span>
        <h1 className="font-display text-2xl md:text-3xl font-extrabold text-slate-900 tracking-tight mt-1.5">Data & Analysis Jobs</h1>
        <p className="text-xs md:text-sm text-slate-500 mt-0.5">
          Upload PDFs (scanned pages are read by OCR) and GIS layers. Each job runs the PDF and map agents independently, saves checkpoints, retries only
          transient failures, fuses evidence by verified IDs and reports partial results honestly.
        </p>
      </div>

      {message && (
        <div className={`p-3 rounded-xl text-xs border ${message.kind === 'ok' ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-rose-50 border-rose-200 text-rose-800'}`}>
          {message.text}
        </div>
      )}

      {project.isDemo ? (
        <>
          <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-900">
            The demo corridor is a read-only synthetic dataset. Create a project to analyse your own documents and maps.
          </div>
          {createForm}
        </>
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs space-y-4">
              <h3 className="font-display font-bold text-base text-slate-900">1. Upload inputs</h3>
              <label className="block p-4 rounded-xl border-2 border-dashed border-slate-300 hover:border-blue-400 cursor-pointer text-xs text-slate-600">
                <span className="font-bold text-slate-800 flex items-center gap-1.5"><FileText className="h-4 w-4 text-blue-600" /> PDF documents</span>
                Case files, awards, notices (text or scanned), up to 50 MB.
                <input ref={docRef} type="file" accept=".pdf,application/pdf" multiple className="sr-only" onChange={(e) => upload('documents', e.target.files)} />
              </label>
              <label className="block p-4 rounded-xl border-2 border-dashed border-slate-300 hover:border-blue-400 cursor-pointer text-xs text-slate-600">
                <span className="font-bold text-slate-800 flex items-center gap-1.5"><MapIcon className="h-4 w-4 text-blue-600" /> GIS / map files</span>
                GeoJSON, zipped Shapefile (.shp+.shx+.dbf+.prj), GeoPackage, KML. PNG/JPG/PDF maps are kept as visual references only.
                <input ref={mapRef} type="file" accept=".geojson,.json,.zip,.gpkg,.kml,.png,.jpg,.jpeg,.pdf" multiple className="sr-only" onChange={(e) => upload('maps', e.target.files)} />
              </label>
              {(busy === 'documents' || busy === 'maps') && <p className="text-xs text-slate-500 flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Uploading…</p>}
              <UploadResults results={uploads} />
            </div>

            <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-display font-bold text-base text-slate-900">2. Inputs ({inputs.length})</h3>
                <button onClick={startJob} disabled={busy === 'job' || !inputs.some((i) => i.status === 'STORED')}
                  className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white px-4 py-2 rounded-xl text-xs font-bold">
                  {busy === 'job' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} Run analysis job
                </button>
              </div>
              <div className="max-h-64 overflow-y-auto divide-y divide-slate-100">
                {inputs.length === 0 && <p className="text-xs text-slate-500">No files uploaded yet.</p>}
                {inputs.map((i) => (
                  <div key={i.id} className="py-2 flex items-center justify-between gap-2 text-xs">
                    <span className="flex items-center gap-1.5 min-w-0">
                      {i.kind === 'document' ? <FileText className="h-3.5 w-3.5 text-slate-400 shrink-0" /> : <MapIcon className="h-3.5 w-3.5 text-slate-400 shrink-0" />}
                      <span className="truncate font-medium text-slate-800">{i.filename}</span>
                      <span className="text-[10px] text-slate-400">{(i.size_bytes / 1024).toFixed(0)} KB</span>
                    </span>
                    <span className="text-right">
                      <StateChip state={i.status === 'QUARANTINED' ? 'QUARANTINED' : 'SUCCEEDED'} />
                      <span className="block text-[10px] text-slate-500">{i.status}{i.detail ? ` · ${i.detail}` : ''}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {job && (
            <div className="bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs space-y-5">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 border-b border-slate-100 pb-3">
                <div>
                  <h3 className="font-display font-bold text-base text-slate-900 flex items-center gap-2">
                    3. Job <span className="font-mono text-sm">{job.job_id}</span> <StateChip state={job.state} />
                    {ACTIVE.has(job.state) && <Loader2 className="h-4 w-4 animate-spin text-blue-600" />}
                  </h3>
                  <p className="text-[11px] text-slate-500">
                    Steps {job.steps_used}/{job.step_budget}{job.resumed_count ? ` • resumed ${job.resumed_count}× after restart` : ''} • updated {new Date(job.updated_at).toLocaleTimeString()}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <PredictionChip status={job.prediction_readiness} />
                  {ACTIVE.has(job.state) && (
                    <button onClick={() => api.cancelJob(job.job_id).catch(() => undefined)} className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200">Cancel</button>
                  )}
                  {!ACTIVE.has(job.state) && (
                    <button onClick={onOpenCases} className="text-xs font-bold px-3 py-1.5 rounded-lg bg-slate-900 text-white">Open cases</button>
                  )}
                </div>
              </div>

              {job.remediation && (
                <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-900 flex gap-2">
                  <RotateCcw className="h-4 w-4 shrink-0" /> {job.remediation}
                </div>
              )}

              {!ACTIVE.has(job.state) && <FailsafeReport job={job} />}

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <AgentCard title="PDF Intelligence Agent" icon={FileText} status={job.pdf_agent} />
                <AgentCard title="Map Intelligence Agent" icon={MapIcon} status={job.map_agent} />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl border border-slate-200">
                  <StageRow label="Retrieval index" stage={job.retrieval} />
                  <StageRow label="Evidence fusion" stage={job.fusion} />
                  <div className="pt-2 text-[11px] text-slate-500">Prediction: {job.prediction_reason ?? '—'}</div>
                </div>
                <div className="p-4 rounded-xl border border-slate-200 text-xs">
                  <div className="font-bold text-slate-800 flex items-center gap-1.5 mb-2"><ListTree className="h-4 w-4 text-blue-600" /> Orchestrator audit trail</div>
                  <ol className="space-y-1 max-h-48 overflow-y-auto">
                    {job.audit.map((a, i) => (
                      <li key={i} className="flex items-start gap-2 text-[11px]">
                        {a.outcome.startsWith('error') || a.outcome === 'FAILED' ? <XCircle className="h-3.5 w-3.5 text-rose-500 shrink-0" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />}
                        <span><span className="font-mono font-bold">{a.action}</span> — {a.outcome}{a.detail ? ` (${a.detail})` : ''}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>

              {job.clarifications.length > 0 && (
                <div className="p-4 rounded-xl border border-indigo-200 bg-indigo-50/40 space-y-3">
                  <div className="font-bold text-indigo-900 text-xs flex items-center gap-1.5"><HelpCircle className="h-4 w-4" /> Confirmation needed (records are not merged until you answer)</div>
                  {job.clarifications.map((m) => (
                    <div key={m.match_id} className="text-xs space-y-2">
                      <p className="text-slate-700">{m.question}</p>
                      <div className="flex gap-2 flex-wrap">
                        {m.candidates.map((c) => (
                          <button key={c} onClick={() => answer(m.match_id, c)} className="px-3 py-1 rounded-lg bg-indigo-600 text-white font-bold">{c}</button>
                        ))}
                        <button onClick={() => answer(m.match_id, null)} className="px-3 py-1 rounded-lg bg-white border border-slate-300 font-semibold">None of these</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {job.warnings.length > 0 && (
                <div className="text-[11px] text-amber-700 space-y-1">
                  {job.warnings.map((w) => <div key={w} className="flex gap-1"><AlertTriangle className="h-3.5 w-3.5 shrink-0" />{w}</div>)}
                </div>
              )}
            </div>
          )}

          {jobs.length > 1 && (
            <div className="bg-white p-4 rounded-2xl border border-slate-200/90 shadow-2xs text-xs">
              <div className="font-bold text-slate-800 mb-2">Previous jobs</div>
              <div className="flex flex-wrap gap-2">
                {jobs.map((j) => (
                  <button key={j.job_id} onClick={() => setJob(j)} className={`px-2.5 py-1 rounded-lg border font-mono ${job?.job_id === j.job_id ? 'border-blue-400 bg-blue-50' : 'border-slate-200'}`}>
                    {j.job_id} · {j.state}
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};
