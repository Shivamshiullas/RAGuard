import React, { useState } from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  ArrowRight,
  Zap,
  UserCheck,
} from 'lucide-react';
import { AcquisitionCase, PageView, RecommendationAction } from '../../types';
import { api } from '../../api/client';
import { UI_TO_WORKFLOW } from '../../api/adapter';
import { IllustrativeBadge, PredictionChip } from '../common/StatusChips';

interface RecommendedActionsViewProps {
  caseData: AcquisitionCase;
  onNavigate: (page: PageView) => void;
}

export const RecommendedActionsView: React.FC<RecommendedActionsViewProps> = ({
  caseData,
  onNavigate,
}) => {
  // Local state for actions so user can click and toggle review/escalation states in the demo
  const [actions, setActions] = useState<RecommendationAction[]>(caseData.recommendations);
  const [simulationActive, setSimulationActive] = useState<boolean>(false);
  const [notificationMsg, setNotificationMsg] = useState<string | null>(null);

  const canSimulate = caseData.isSynthetic && caseData.delayProbability !== null;
  const currentProb = caseData.delayProbability ?? 0;

  const handleActionToggle = async (actionId: string, newStatus: RecommendationAction['status']) => {
    const updated = actions.find((a) => a.id === actionId);
    if (updated?.backendId) {
      try {
        await api.setWorkflow(updated.backendId, UI_TO_WORKFLOW[newStatus]);
      } catch (err) {
        setNotificationMsg(err instanceof Error ? err.message : 'Could not save the workflow status.');
        setTimeout(() => setNotificationMsg(null), 3500);
        return;
      }
    }
    setActions((prev) => prev.map((act) => (act.id === actionId ? { ...act, status: newStatus } : act)));
    setNotificationMsg(`"${updated?.title}" marked as ${newStatus}. Recorded in LANDIQ only; nothing is sent to any authority.`);
    setTimeout(() => setNotificationMsg(null), 3500);
  };

  // Compute mitigated delay probability
  const completedOrInReviewDays = actions
    .filter((a) => a.status === 'In Review' || a.status === 'Escalated' || a.status === 'Completed')
    .reduce((acc, curr) => acc + Math.abs(curr.estimatedImpactDays ?? 0), 0);

  // Illustrative scenario arithmetic for the synthetic demo only; not a model output.
  const simulatedProb = simulationActive
    ? Math.max(38, Math.round(currentProb - completedOrInReviewDays * 0.45))
    : currentProb;

  return (
    <div className="space-y-6 pb-12">
      {/* Toast Notification */}
      {notificationMsg && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-900 text-white text-xs px-4 py-3 rounded-xl shadow-2xl border border-slate-700 flex items-center gap-2 animate-in fade-in slide-in-from-bottom-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          <span>{notificationMsg}</span>
        </div>
      )}

      {/* Header */}
      <div className="bg-white p-6 rounded-xl border border-slate-200/90 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 flex items-center gap-1.5">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
              Prescriptive Decision Support
            </span>
            <span className="text-[11px] text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md font-mono">
              Case {caseData.id} • {caseData.zone}
            </span>
            {caseData.isSynthetic && <IllustrativeBadge />}
          </div>

          <h1 className="text-2xl font-semibold text-slate-900 tracking-tight mt-1">
            Recommended Actions
          </h1>

          <p className="text-xs md:text-sm text-slate-500 mt-0.5">
            Evidence-backed suggestions for human review. They are decision support, not legal determinations.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => onNavigate('gis-map')}
            className="flex items-center gap-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 px-3.5 py-2 rounded-xl text-xs font-semibold border border-slate-200 transition-colors"
          >
            <span>Show Location on GIS</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* What-If Mitigation Simulator Banner */}
      <div className="bg-slate-900 text-white p-6 rounded-xl border border-slate-800 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
          <div className="space-y-1.5 max-w-xl">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider bg-white/10 text-slate-200 px-2 py-0.5 rounded border border-white/15 flex items-center gap-1">
                <Zap className="h-3 w-3" />
                Intervention Simulation
              </span>
              <span className="text-[11px] text-amber-300">Illustrative scenario, not a model forecast</span>
            </div>
            <h3 className="font-display font-bold text-lg text-white">What-If Delay Mitigation</h3>
            <p className="text-xs text-slate-300 leading-relaxed">
              {canSimulate
                ? 'A simple illustrative calculation for the synthetic demo storyline, showing how the workflow could look once a validated model exists.'
                : 'Unavailable: there is no trained, evaluated prediction model for this case, so LANDIQ does not estimate how actions change delay risk.'}
            </p>
          </div>

          {canSimulate ? (
            <div className="flex items-center gap-4 bg-slate-800/80 p-4 rounded-xl border border-slate-700">
              <div className="text-center px-2">
                <div className="text-[10px] uppercase font-bold text-slate-400">Current (illustrative)</div>
                <div className="text-2xl font-black text-rose-400">{currentProb}%</div>
              </div>
              <ArrowRight className="h-5 w-5 text-slate-500 shrink-0" />
              <div className="text-center px-2">
                <div className="text-[10px] uppercase font-bold text-slate-400">Scenario</div>
                <div className={`text-2xl font-black transition-all duration-500 ${simulationActive ? 'text-amber-300' : 'text-slate-400'}`}>
                  {simulatedProb}%
                </div>
                <div className={`text-[10px] font-semibold ${simulationActive ? 'text-amber-300' : 'text-slate-500'}`}>
                  {simulationActive ? `${simulatedProb - currentProb} pts (illustrative)` : 'No actions applied'}
                </div>
              </div>
              <button
                onClick={() => {
                  setSimulationActive(!simulationActive);
                  if (!simulationActive) {
                    setActions((prev) => prev.map((a) => ({ ...a, status: 'In Review' })));
                    setNotificationMsg('Illustrative scenario: all actions treated as in review.');
                    setTimeout(() => setNotificationMsg(null), 3000);
                  }
                }}
                className={`px-3.5 py-2 rounded-lg text-xs font-bold transition-all shadow-xs ${simulationActive ? 'bg-amber-400 hover:bg-amber-500 text-slate-950' : 'bg-blue-600 hover:bg-blue-700 text-white'}`}
              >
                {simulationActive ? 'Reset Scenario' : 'Simulate Mitigation'}
              </button>
            </div>
          ) : (
            <PredictionChip status={caseData.prediction.status} className="text-xs" />
          )}
        </div>
      </div>

      {/* Prioritized Action Cards */}
      <div className="space-y-4">
        {actions.length === 0 && (
          <div className="bg-white p-6 rounded-xl border border-slate-200 text-xs text-slate-500">
            No action is recommended: no evidence-backed trigger (dispute, pending compensation, delayed clearance, conflict) was found for this case.
          </div>
        )}
        {actions.map((act) => {
          const isHigh = act.priority === 'HIGH PRIORITY';
          const isMed = act.priority === 'MEDIUM PRIORITY';

          const priorityBadgeStyles = isHigh
            ? 'bg-rose-100 text-rose-800 border-rose-200'
            : isMed
            ? 'bg-amber-100 text-amber-800 border-amber-200'
            : 'bg-blue-100 text-blue-800 border-blue-200';

          const statusBadgeStyles = {
            Pending: 'bg-slate-100 text-slate-700 border-slate-200',
            'In Review': 'bg-amber-50 text-amber-800 border-amber-200',
            Escalated: 'bg-purple-50 text-purple-800 border-purple-200',
            Completed: 'bg-emerald-50 text-emerald-800 border-emerald-200',
          }[act.status];

          return (
            <div
              key={act.id}
              className="bg-white rounded-xl border border-slate-200/90 p-6 shadow-sm hover:shadow-md transition-all space-y-4"
            >
              {/* Top Row: Priority & Status */}
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-slate-100 pb-3">
                <div className="flex items-center gap-2.5">
                  <span
                    className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full border ${priorityBadgeStyles}`}
                  >
                    {act.priority}
                  </span>
                  <h3 className="font-display font-bold text-base text-slate-900">
                    {act.title}
                  </h3>
                </div>

                <div className="flex items-center gap-3">
                  {act.estimatedImpactDays !== null && caseData.isSynthetic && (
                    <span className="text-xs font-mono font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded">
                      Illustrative impact: {act.estimatedImpactDays} days
                    </span>
                  )}
                  <span
                    className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full border ${statusBadgeStyles}`}
                  >
                    Status: {act.status}
                  </span>
                </div>
              </div>

              {/* Middle: Reason & Suggested Action */}
              <div className="grid grid-cols-1 md:grid-cols-12 gap-4 text-xs">
                <div className="md:col-span-4 p-3.5 rounded-xl bg-slate-50 border border-slate-200/70 space-y-1">
                  <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">
                    Identified Risk Driver / Reason
                  </span>
                  <p className="text-slate-700 font-medium leading-relaxed">
                    {act.reason}
                  </p>
                </div>

                <div className="md:col-span-8 p-3.5 rounded-xl bg-blue-50/50 border border-blue-100 space-y-1">
                  <span className="text-[10px] uppercase font-bold text-blue-800 tracking-wider">
                    Suggested Prescriptive Action & Regulatory Route
                  </span>
                  <p className="text-slate-800 leading-relaxed font-medium">
                    {act.suggestedAction}
                  </p>
                  <div className="pt-1 text-[11px] text-blue-700 flex items-center gap-1.5">
                    <UserCheck className="h-3.5 w-3.5 text-blue-600 shrink-0" />
                    <span>Suggested owner: <strong>{act.targetAuthority}</strong></span>
                  </div>
                </div>
              </div>

              {act.evidence && act.evidence.length > 0 && (
                <div className="text-[11px] text-slate-600 space-y-1">
                  <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Evidence</span>
                  {act.evidence.map((e, i) => (
                    <div key={i} className="border-l-2 border-blue-300 pl-2">
                      <span className="font-mono text-blue-700">{e.label}</span>
                      {e.snippet && <span> — “{e.snippet}”</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Bottom: Interactive Workflow Buttons */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                <div className="text-[11px] text-slate-400 italic">
                  Human review required • status is recorded in LANDIQ only
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleActionToggle(act.id, 'In Review')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      act.status === 'In Review'
                        ? 'bg-amber-500 text-slate-950'
                        : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                    }`}
                  >
                    MARK FOR REVIEW
                  </button>

                  <button
                    onClick={() => handleActionToggle(act.id, 'Escalated')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      act.status === 'Escalated'
                        ? 'bg-purple-600 text-white'
                        : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                    }`}
                  >
                    ESCALATE TO AUTHORITY
                  </button>

                  <button
                    onClick={() => handleActionToggle(act.id, 'Completed')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      act.status === 'Completed'
                        ? 'bg-emerald-600 text-white'
                        : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                    }`}
                  >
                    RESOLVED
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Next Flow CTA to GIS Map */}
      <div className="p-6 rounded-xl bg-white border border-slate-200/90 shadow-sm flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h4 className="font-display font-bold text-base text-slate-900">
            Next: Verify Spatial Risk Hotspot on GIS Map
          </h4>
          <p className="text-xs text-slate-500 mt-0.5">
            Examine the corridor alignment and parcel boundary for Case {caseData.id}.
          </p>
        </div>

        <button
          onClick={() => onNavigate('gis-map')}
          className="flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white px-5 py-2.5 rounded-xl text-xs font-bold shadow-md transition-all"
        >
          <span>Open Parcel-Level GIS Map</span>
          <ArrowRight className="h-4 w-4 text-cyan-400" />
        </button>
      </div>
    </div>
  );
};
