import React, { useState } from 'react';
import {
  AlertTriangle,
  Search,
  Info,
  Layers,
  Sparkles,
} from 'lucide-react';
import { AcquisitionCase, PageView, ProjectInfo } from '../../types';
import { RiskBadge } from '../common/RiskBadge';
import { IllustrativeBadge, PredictionChip } from '../common/StatusChips';

interface HighRiskCasesViewProps {
  project: ProjectInfo;
  cases: AcquisitionCase[];
  onSelectCase: (caseItem: AcquisitionCase) => void;
  onNavigate: (page: PageView) => void;
}

const bar = (value: number | null, color: string) =>
  value === null ? (
    <span className="text-[11px] text-slate-400">Unknown</span>
  ) : (
    <div className="flex items-center gap-1.5">
      <div className="w-12 bg-slate-100 h-1.5 rounded-full overflow-hidden">
        <div className={`${color} h-full`} style={{ width: `${value}%` }} />
      </div>
      <span>{value}%</span>
    </div>
  );

const statusChip = (value: string, bad: string[], good: string[]) => {
  const cls = value === 'Conflict'
    ? 'bg-rose-200 text-rose-900 ring-1 ring-rose-400'
    : value.startsWith('Unknown')
    ? 'bg-slate-100 text-slate-500'
    : bad.some((b) => value.startsWith(b))
    ? 'bg-rose-100 text-rose-800'
    : good.some((g) => value.startsWith(g))
    ? 'bg-emerald-50 text-emerald-700'
    : 'bg-amber-50 text-amber-800';
  return <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${cls}`}>{value}</span>;
};

export const HighRiskCasesView: React.FC<HighRiskCasesViewProps> = ({
  project,
  cases,
  onSelectCase,
  onNavigate,
}) => {
  const [selectedZone, setSelectedZone] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const rated = cases.some((c) => c.riskCategory !== 'UNRATED');
  const [riskFilter, setRiskFilter] = useState<'ALL' | 'HIGH' | 'MEDIUM' | 'LOW'>(rated ? 'HIGH' : 'ALL');
  const count = (r: string) => cases.filter((c) => c.riskCategory === r).length;

  // Filter cases
  const filteredCases = cases.filter((c) => {
    const matchesRisk = riskFilter === 'ALL' || c.riskCategory === riskFilter;
    const matchesZone = selectedZone === 'ALL' || c.zone === selectedZone;
    const matchesSearch =
      c.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.villageName.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.zone.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.surveyNo.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesRisk && matchesZone && matchesSearch;
  });

  const zones = ['ALL', ...Array.from(new Set(cases.map((c) => c.zone))).sort()];
  const hero = cases.find((c) => c.id === '#0472');

  return (
    <div className="space-y-6 pb-12">
      {/* Header Banner */}
      <div className="bg-white p-6 rounded-xl border border-slate-200/90 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 flex items-center gap-1.5">
              <AlertTriangle className="h-3 w-3" />
              Prioritized Queue
            </span>
            {project.isDemo ? <IllustrativeBadge /> : <PredictionChip status={rated ? 'READY' : 'NOT_READY'} />}
          </div>
          <h1 className="text-2xl font-semibold text-slate-900 tracking-tight mt-1">
            High-Risk Acquisition Cases
          </h1>
          <p className="text-xs md:text-sm text-slate-500 mt-0.5">
            {rated
              ? project.isDemo
                ? 'Cases ranked by illustrative delay risk (synthetic demo figures).'
                : 'Cases ranked by rule-based delay risk (scorecard on evidence-backed statuses, not a trained model).'
              : 'No prediction model is available, so cases are listed with their evidence-backed statuses, not risk scores.'}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => onNavigate('gis-map')}
            className="flex items-center gap-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 px-3.5 py-2 rounded-xl text-xs font-semibold border border-slate-200 transition-colors"
          >
            <Layers className="h-3.5 w-3.5 text-blue-600" />
            <span>View on GIS Map</span>
          </button>
          {hero && (
            <button
              onClick={() => {
                onSelectCase(hero);
                onNavigate('case-details');
              }}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-sm transition-all"
            >
              <Sparkles className="h-3.5 w-3.5 text-cyan-300" />
              <span>Open Hero Case #0472</span>
            </button>
          )}
        </div>
      </div>

      {/* Filter and Search Toolbar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200/90 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search by Case ID, village, survey number..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 transition-all"
          />
        </div>

        {/* Risk Filter Buttons */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 md:pb-0">
          <div className="flex bg-slate-100 p-1 rounded-lg border border-slate-200 text-xs font-semibold">
            <button
              onClick={() => setRiskFilter('HIGH')}
              className={`px-3 py-1 rounded-md transition-all ${
                riskFilter === 'HIGH'
                  ? 'bg-rose-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              High Risk ({count('HIGH')})
            </button>
            <button
              onClick={() => setRiskFilter('MEDIUM')}
              className={`px-3 py-1 rounded-md transition-all ${
                riskFilter === 'MEDIUM'
                  ? 'bg-amber-500 text-slate-950 shadow-xs font-bold'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Medium ({count('MEDIUM')})
            </button>
            <button
              onClick={() => setRiskFilter('LOW')}
              className={`px-3 py-1 rounded-md transition-all ${
                riskFilter === 'LOW'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Low ({count('LOW')})
            </button>
            <button
              onClick={() => setRiskFilter('ALL')}
              className={`px-3 py-1 rounded-md transition-all ${
                riskFilter === 'ALL'
                  ? 'bg-slate-900 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              All Cases ({cases.length})
            </button>
          </div>

          {/* Zone Selector */}
          <select
            value={selectedZone}
            onChange={(e) => setSelectedZone(e.target.value)}
            className="bg-slate-50 border border-slate-200 text-slate-700 text-xs font-medium rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
          >
            {zones.map((z) => (
              <option key={z} value={z}>
                {z === 'ALL' ? 'All Zones' : z}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Main Cases Table */}
      <div className="bg-white rounded-xl border border-slate-200/90 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50/90 text-slate-600 font-bold uppercase tracking-wider text-[11px] border-b border-slate-200">
              <tr>
                <th className="py-3.5 px-5">CASE ID</th>
                <th className="py-3.5 px-5">LOCATION</th>
                <th className="py-3.5 px-5">DELAY PROBABILITY</th>
                <th className="py-3.5 px-5">RISK</th>
                <th className="py-3.5 px-5">LEGAL</th>
                <th className="py-3.5 px-5">COMPENSATION</th>
                <th className="py-3.5 px-5">APPROVAL</th>
                <th className="py-3.5 px-5">R&R</th>
                <th className="py-3.5 px-5">PROJECT PROGRESS</th>
                <th className="py-3.5 px-5 text-right">ACTION</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-medium">
              {filteredCases.map((item) => {
                const isHero = item.id === '#0472';
                return (
                  <tr
                    key={item.uid}
                    onClick={() => {
                      onSelectCase(item);
                      onNavigate('case-details');
                    }}
                    className={`cursor-pointer transition-all ${
                      isHero
                        ? 'bg-blue-50/50 hover:bg-blue-100/70 ring-1 ring-blue-400/40'
                        : 'hover:bg-slate-50'
                    }`}
                  >
                    {/* Case ID */}
                    <td className="py-4 px-5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-slate-900 text-sm">
                          {item.id}
                        </span>
                        {isHero && (
                          <span className="text-[10px] uppercase font-bold bg-blue-600 text-white px-1.5 py-0.5 rounded shadow-xs">
                            Hero
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-slate-400 font-mono">
                        {item.surveyNo.split(',')[0]}
                        {item.conflicts.length > 0 || Object.values(item.fieldStatus).includes('CONFLICT') ? ' • conflict' : ''}
                      </span>
                    </td>

                    {/* Location */}
                    <td className="py-4 px-5">
                      <div className="font-bold text-slate-800">{item.zone}</div>
                      <div className="text-[11px] text-slate-500">{item.villageName}</div>
                    </td>

                    {/* Delay Probability */}
                    <td className="py-4 px-5">
                      {item.delayProbability === null ? (
                        <span className="text-[11px] text-slate-500 font-mono" title={item.prediction.reason}>— {item.prediction.status}</span>
                      ) : (
                      <div className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span
                            className={`font-mono font-bold text-sm ${
                              item.delayProbability >= 70
                                ? 'text-rose-700'
                                : item.delayProbability >= 40
                                ? 'text-amber-700'
                                : 'text-emerald-700'
                            }`}
                          >
                            {item.delayProbability}%
                          </span>
                          <span className="text-[10px] text-slate-400">
                            {item.estDelayDays === null ? '' : `+${item.estDelayDays}d est`}
                          </span>
                        </div>
                        <div className="w-24 bg-slate-100 h-2 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              item.delayProbability >= 70
                                ? 'bg-rose-600'
                                : item.delayProbability >= 40
                                ? 'bg-amber-500'
                                : 'bg-emerald-500'
                            }`}
                            style={{ width: `${item.delayProbability}%` }}
                          />
                        </div>
                      </div>
                      )}
                    </td>

                    {/* Risk Badge */}
                    <td className="py-4 px-5">
                      <RiskBadge level={item.riskCategory} size="sm" />
                    </td>

                    {/* Legal */}
                    <td className="py-4 px-5">{statusChip(item.legalStatus, ['Dispute', 'In Court'], ['Clear'])}</td>

                    {/* Compensation */}
                    <td className="py-4 px-5">{statusChip(item.compensationStatus, ['Pending', 'Disputed'], ['Disbursed'])}</td>

                    {/* Approval */}
                    <td className="py-4 px-5">{statusChip(item.approvalStatus, ['Delayed'], ['Cleared'])}</td>

                    {/* R&R */}
                    <td className="py-4 px-5 font-mono text-slate-700 font-semibold">{bar(item.rrProgress, 'bg-indigo-600')}</td>

                    {/* Project Progress */}
                    <td className="py-4 px-5 font-mono text-slate-700 font-semibold">{bar(item.projectProgress, 'bg-blue-600')}</td>

                    {/* Action */}
                    <td className="py-4 px-5 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectCase(item);
                          onNavigate('case-details');
                        }}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                          isHero
                            ? 'bg-blue-600 hover:bg-blue-700 text-white shadow-xs'
                            : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                        }`}
                      >
                        {isHero ? 'Inspect Case' : 'Details'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Table Footer */}
        <div className="p-4 bg-slate-50/80 border-t border-slate-200 flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center gap-2">
            <Info className="h-4 w-4 text-slate-400" />
            <span>
              Showing {filteredCases.length} cases •{' '}
              {rated ? (project.isDemo ? 'Ranked by illustrative synthetic delay figures' : 'Ranked by rule-based scorecard') : 'No model ranking: prediction NOT_READY'}
            </span>
          </div>
          <span className="font-mono text-[11px] text-slate-400">
            Click any row to open full Case Intelligence View
          </span>
        </div>
      </div>
    </div>
  );
};
