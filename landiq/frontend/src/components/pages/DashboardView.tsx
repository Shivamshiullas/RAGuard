import React from 'react';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
  BarChart,
  Bar,
} from 'recharts';
import { AlertTriangle, CheckCircle2, Clock, ArrowUpRight, TrendingUp, MapPin, FileCheck, ChevronRight, GitCompare } from 'lucide-react';
import { ProjectInfo, PageView, AcquisitionCase, RiskTrendPoint } from '../../types';
import { KpiCard } from '../common/KpiCard';
import { RiskBadge } from '../common/RiskBadge';
import { IllustrativeBadge, PredictionChip } from '../common/StatusChips';

interface DashboardViewProps {
  project: ProjectInfo;
  cases: AcquisitionCase[];
  trend: RiskTrendPoint[];
  onNavigate: (page: PageView) => void;
  onSelectCase: (caseItem: AcquisitionCase) => void;
}

const pct = (n: number, total: number) => (total ? `${Math.round((100 * n) / total)}%` : '0%');

export const DashboardView: React.FC<DashboardViewProps> = ({ project, cases, trend, onNavigate, onSelectCase }) => {
  const total = cases.length;
  const counts = {
    LOW: cases.filter((c) => c.riskCategory === 'LOW').length,
    MEDIUM: cases.filter((c) => c.riskCategory === 'MEDIUM').length,
    HIGH: cases.filter((c) => c.riskCategory === 'HIGH').length,
    UNRATED: cases.filter((c) => c.riskCategory === 'UNRATED').length,
  };
  const quality = {
    GOOD: cases.filter((c) => c.dataQuality === 'GOOD').length,
    PARTIAL: cases.filter((c) => c.dataQuality === 'PARTIAL').length,
    POOR: cases.filter((c) => c.dataQuality === 'POOR').length,
  };
  const withConflicts = cases.filter((c) => Object.values(c.fieldStatus).includes('CONFLICT')).length;
  const rated = project.isDemo || counts.UNRATED < total;
  const bandSource = project.isDemo ? 'Illustrative' : 'Rule-based';
  const bandLabel = project.isDemo ? 'synthetic risk band' : 'scorecard risk band';

  const donutData = rated
    ? [
        { name: 'Low Risk', value: counts.LOW, color: '#10b981' },
        { name: 'Medium Risk', value: counts.MEDIUM, color: '#f59e0b' },
        { name: 'High Risk', value: counts.HIGH, color: '#e11d48' },
      ]
    : [
        { name: 'Good evidence', value: quality.GOOD, color: '#10b981' },
        { name: 'Partial evidence', value: quality.PARTIAL, color: '#f59e0b' },
        { name: 'Poor evidence', value: quality.POOR, color: '#94a3b8' },
      ];

  const coverage = ['legal_status', 'compensation_status', 'clearance_status'].map((field) => ({
    field: field.replace('_status', '').replace('clearance', 'approval'),
    Known: cases.filter((c) => c.fieldStatus[field] === 'KNOWN').length,
    Unverified: cases.filter((c) => c.fieldStatus[field] === 'UNVERIFIED').length,
    Conflict: cases.filter((c) => c.fieldStatus[field] === 'CONFLICT').length,
    Unknown: cases.filter((c) => !c.fieldStatus[field] || c.fieldStatus[field] === 'UNKNOWN').length,
  }));

  const topCases = rated
    ? [...cases].filter((c) => c.riskCategory === 'HIGH').sort((a, b) => (b.delayProbability ?? 0) - (a.delayProbability ?? 0)).slice(0, 4)
    : [...cases].sort((a, b) => b.recommendations.length - a.recommendations.length).slice(0, 4);

  return (
    <div className="space-y-6 pb-12 animate-in fade-in duration-300">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-bold uppercase tracking-wider bg-blue-50 text-blue-700 border border-blue-200 px-2.5 py-0.5 rounded-full">
              Predictive Intelligence Overview
            </span>
            {project.isDemo ? <IllustrativeBadge text="Illustrative Project Data" /> : <PredictionChip status={rated ? 'READY' : 'NOT_READY'} />}
          </div>
          <h1 className="font-display text-2xl md:text-3xl font-extrabold text-slate-900 tracking-tight mt-1.5">{project.name}</h1>
          <p className="text-xs md:text-sm text-slate-500 mt-0.5">
            {project.code} • {project.description || (project.isDemo ? 'Synthetic demo corridor' : 'Cases fused from uploaded PDFs and GIS layers')}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => onNavigate('gis-map')}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 transition-colors"
          >
            <MapPin className="h-3.5 w-3.5 text-slate-600" />
            <span>Open GIS Map</span>
          </button>
          <button
            onClick={() => onNavigate('high-risk-cases')}
            className="flex items-center gap-2 bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-sm shadow-rose-500/20 transition-all hover:scale-[1.02]"
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>{rated ? `View High-Risk Cases (${counts.HIGH})` : `View Case Queue (${total})`}</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          title="TOTAL ACQUISITION CASES"
          value={total.toLocaleString()}
          subtitle={project.isDemo ? 'Synthetic cases along corridor' : 'Fused from uploaded records'}
          icon={FileCheck}
          variant="blue"
          trend={{ value: `${cases.filter((c) => c.polygonCoords.length).length}`, isPositive: true, label: 'with parcel geometry' }}
          onClick={() => onNavigate('high-risk-cases')}
        />
        {rated ? (
          <>
            <KpiCard title="LOW RISK" value={counts.LOW} subtitle={`${pct(counts.LOW, total)} of cases`} icon={CheckCircle2} variant="emerald" trend={{ value: bandSource, isPositive: true, label: bandLabel }} />
            <KpiCard title="MEDIUM RISK" value={counts.MEDIUM} subtitle={`${pct(counts.MEDIUM, total)} of cases`} icon={Clock} variant="amber" trend={{ value: bandSource, isPositive: false, label: bandLabel }} />
            <KpiCard
              title="HIGH RISK"
              value={counts.HIGH}
              subtitle={`${pct(counts.HIGH, total)} of cases`}
              icon={AlertTriangle}
              variant="rose"
              trend={{ value: 'Review', isPositive: false, label: 'human review required' }}
              onClick={() => onNavigate('high-risk-cases')}
              className="ring-2 ring-rose-500/30 ring-offset-1"
            />
          </>
        ) : (
          <>
            <KpiCard title="GOOD EVIDENCE" value={quality.GOOD} subtitle="Legal, compensation & approval all known" icon={CheckCircle2} variant="emerald" />
            <KpiCard title="PARTIAL / POOR" value={quality.PARTIAL + quality.POOR} subtitle="Some statuses UNKNOWN" icon={Clock} variant="amber" />
            <KpiCard title="CONFLICTING RECORDS" value={withConflicts} subtitle="Sources disagree; not resolved automatically" icon={GitCompare} variant="rose" onClick={() => onNavigate('high-risk-cases')} />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-5 bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div>
                <h3 className="font-display font-bold text-base text-slate-900">{rated ? 'DELAY RISK OVERVIEW' : 'EVIDENCE QUALITY'}</h3>
                <p className="text-xs text-slate-500">Distribution across {total} cases</p>
              </div>
              {rated ? <IllustrativeBadge text={project.isDemo ? 'Illustrative Data' : 'Rule-based scorecard'} /> : <span className="text-[10px] font-bold text-slate-500 uppercase px-2 py-0.5 rounded bg-slate-100">From fusion</span>}
            </div>

            <div className="h-56 relative flex items-center justify-center mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={donutData} cx="50%" cy="50%" innerRadius={62} outerRadius={86} paddingAngle={4} dataKey="value">
                    {donutData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} strokeWidth={0} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(val: unknown, name: unknown) => [`${val} cases`, String(name)]}
                    contentStyle={{ borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '12px' }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="font-display text-2xl font-extrabold text-slate-900">{total}</span>
                <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500">Total Cases</span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 pt-4 border-t border-slate-100 text-center">
            {donutData.map((d, i) => (
              <div
                key={d.name}
                className={`p-2 rounded-xl border ${['bg-emerald-50/60 border-emerald-100', 'bg-amber-50/60 border-amber-100', rated ? 'bg-rose-50/60 border-rose-100' : 'bg-slate-50 border-slate-200'][i]}`}
              >
                <span className="text-[11px] font-bold text-slate-800 block">{d.name}</span>
                <span className="text-base font-extrabold" style={{ color: d.color }}>{pct(d.value, total)}</span>
                <span className="text-[10px] text-slate-500 block">{d.value} Cases</span>
              </div>
            ))}
          </div>
        </div>

        <div className="lg:col-span-7 bg-white p-6 rounded-2xl border border-slate-200/90 shadow-2xs flex flex-col justify-between">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-display font-bold text-base text-slate-900">{project.isDemo ? 'RISK TREND' : 'STATUS COVERAGE'}</h3>
                <TrendingUp className="h-4 w-4 text-blue-600" />
              </div>
              <p className="text-xs text-slate-500">
                {project.isDemo
                  ? 'Monthly synthetic progression (illustrative, not historical data)'
                  : 'How many cases have each status backed by evidence'}
              </p>
            </div>
            {project.isDemo && <IllustrativeBadge />}
          </div>

          <div className="h-56 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              {project.isDemo ? (
                <LineChart data={trend} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: '#64748b' }} stroke="#cbd5e1" />
                  <YAxis tick={{ fontSize: 11, fill: '#64748b' }} stroke="#cbd5e1" />
                  <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '12px' }} />
                  <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }} />
                  <Line type="monotone" dataKey="avgDelayProb" name="Avg Illustrative Delay Probability (%)" stroke="#2563eb" strokeWidth={2.5} dot={{ r: 4, fill: '#2563eb' }} />
                  <Line type="monotone" dataKey="highRisk" name="High Risk Count" stroke="#e11d48" strokeWidth={2} strokeDasharray="4 4" dot={{ r: 3, fill: '#e11d48' }} />
                </LineChart>
              ) : (
                <BarChart data={coverage} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="field" tick={{ fontSize: 11, fill: '#64748b' }} stroke="#cbd5e1" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#64748b' }} stroke="#cbd5e1" />
                  <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '12px' }} />
                  <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }} />
                  <Bar dataKey="Known" stackId="a" fill="#10b981" />
                  <Bar dataKey="Unverified" stackId="a" fill="#f59e0b" />
                  <Bar dataKey="Conflict" stackId="a" fill="#e11d48" />
                  <Bar dataKey="Unknown" stackId="a" fill="#cbd5e1" />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>

          <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span className="flex items-center gap-1 text-[11px]">
              <span className="h-2 w-2 rounded-full bg-blue-600" />
              {project.isDemo || !rated
                ? 'No trained prediction model yet: no accuracy or forecast figures are reported.'
                : 'Risk from the rule-based scorecard (not a trained model): no accuracy is claimed.'}
            </span>
            <PredictionChip status={project.isDemo ? 'DEMO_ONLY' : rated ? 'READY' : 'NOT_READY'} />
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-2xs overflow-hidden">
        <div className="p-6 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-display font-bold text-lg text-slate-900">{rated ? 'RECENT HIGH-RISK CASES' : 'CASES NEEDING REVIEW'}</h3>
              <span className="bg-rose-100 text-rose-700 text-[10px] font-bold px-2 py-0.5 rounded-full">Attention Required</span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              {rated ? (project.isDemo ? 'Highest illustrative delay probabilities' : 'Highest rule-based delay risk') : 'Cases with the most evidence-backed recommended actions'}
            </p>
          </div>
          <button onClick={() => onNavigate('high-risk-cases')} className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-600 hover:text-blue-800 group">
            <span>VIEW ALL CASES</span>
            <ChevronRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50/90 text-slate-600 font-bold uppercase tracking-wider text-[11px] border-b border-slate-200">
              <tr>
                <th className="py-3 px-6">Case ID</th>
                <th className="py-3 px-6">Location / Zone</th>
                <th className="py-3 px-6">Delay Probability</th>
                <th className="py-3 px-6">Risk Category</th>
                <th className="py-3 px-6">Key Status</th>
                <th className="py-3 px-6 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {topCases.map((item) => {
                const isHero = item.id === '#0472';
                return (
                  <tr
                    key={item.uid}
                    onClick={() => {
                      onSelectCase(item);
                      onNavigate('case-details');
                    }}
                    className={`cursor-pointer transition-colors ${isHero ? 'bg-blue-50/40 hover:bg-blue-100/60 ring-1 ring-blue-400/30' : 'hover:bg-slate-50/80'}`}
                  >
                    <td className="py-4 px-6 font-mono font-bold text-slate-900">{item.id}</td>
                    <td className="py-4 px-6">
                      <div className="font-semibold text-slate-800">{item.zone}</div>
                      <div className="text-[11px] text-slate-500">{item.villageName}</div>
                    </td>
                    <td className="py-4 px-6">
                      {item.delayProbability === null ? (
                        <span className="text-[11px] text-slate-500 font-mono">— not predicted</span>
                      ) : (
                        <div className="flex items-center gap-2.5">
                          <div className="w-20 bg-slate-200 h-2 rounded-full overflow-hidden">
                            <div className="bg-rose-600 h-full rounded-full" style={{ width: `${item.delayProbability}%` }} />
                          </div>
                          <span className="font-mono font-extrabold text-rose-700 text-sm">{item.delayProbability}%</span>
                        </div>
                      )}
                    </td>
                    <td className="py-4 px-6">
                      <RiskBadge level={item.riskCategory} size="sm" />
                    </td>
                    <td className="py-4 px-6">
                      <div className="font-medium text-slate-700">Legal: {item.legalStatus}</div>
                      <div className="text-[11px] text-slate-400 truncate max-w-xs">Compensation: {item.compensationStatus}</div>
                    </td>
                    <td className="py-4 px-6 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectCase(item);
                          onNavigate('case-details');
                        }}
                        className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${isHero ? 'bg-blue-600 hover:bg-blue-700 text-white shadow-xs' : 'bg-slate-100 hover:bg-slate-200 text-slate-800'}`}
                      >
                        {isHero ? 'Deep Dive' : 'Review'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="p-4 bg-slate-50/70 border-t border-slate-100 flex items-center justify-end">
          <button onClick={() => onNavigate('high-risk-cases')} className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white px-4 py-2 rounded-xl text-xs font-bold transition-all shadow-xs">
            <span>VIEW CASE QUEUE</span>
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
