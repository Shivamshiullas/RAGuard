import React from 'react';
import {
  LayoutDashboard,
  AlertTriangle,
  FileSearch,
  BrainCircuit,
  ShieldCheck,
  MapPin,
  FileText,
  Layers,
  Info,
  UploadCloud,
} from 'lucide-react';
import { PageView, ProjectInfo } from '../../types';
import type { ApiHealth } from '../../api/client';

interface SidebarProps {
  currentPage: PageView;
  onNavigate: (page: PageView) => void;
  highRiskCount: number;
  health: ApiHealth | null;
  project: ProjectInfo | null;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentPage,
  onNavigate,
  highRiskCount,
  health,
  project,
}) => {
  const navItems: { id: PageView; label: string; icon: React.ElementType; badge?: string; badgeColor?: string }[] = [
    { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
    {
      id: 'high-risk-cases',
      label: 'High-Risk Cases',
      icon: AlertTriangle,
      badge: highRiskCount ? String(highRiskCount) : undefined,
      badgeColor: 'bg-rose-100 text-rose-700',
    },
    { id: 'case-details', label: 'Acquisition Cases', icon: FileSearch },
    { id: 'risk-explanation', label: 'Risk Analysis & SHAP', icon: BrainCircuit },
    { id: 'recommended-actions', label: 'Recommended Actions', icon: ShieldCheck },
    { id: 'gis-map', label: 'GIS Parcel Map', icon: MapPin },
    { id: 'reports', label: 'Executive Briefing', icon: FileText },
    { id: 'ingestion', label: 'Data & Analysis Jobs', icon: UploadCloud },
  ];

  const online = health !== null;
  const prediction = health?.prediction.status ?? 'NOT_READY';

  return (
    <aside className="w-64 shrink-0 bg-slate-900 text-slate-200 border-r border-slate-800 flex flex-col justify-between select-none">
      {/* Brand Header */}
      <div>
        <div className="p-5 border-b border-slate-800/80">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-gradient-to-tr from-blue-700 via-indigo-600 to-cyan-500 flex items-center justify-center shadow-md shadow-indigo-950/50">
              <Layers className="h-5 w-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-display text-xl font-bold tracking-tight text-white">
                  LAND<span className="text-cyan-400">IQ</span>
                </span>
              </div>
              <p className="text-[11px] font-medium text-slate-400 tracking-tight leading-none mt-0.5">
                Land Acquisition Intelligence
              </p>
            </div>
          </div>
        </div>



        {/* Navigation links */}
        <nav className="px-3 py-2 space-y-1">
          <div className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            Platform Navigation
          </div>
          {navItems.map((item) => {
            const isActive = currentPage === item.id;
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                onClick={() => onNavigate(item.id)}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-blue-600 text-white font-semibold shadow-xs shadow-blue-900/50'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon className={`h-4 w-4 ${isActive ? 'text-white' : 'text-slate-400'}`} />
                  <span>{item.label}</span>
                </div>
                {item.badge && (
                  <span
                    className={`text-[10px] font-bold px-1.5 py-0.5 rounded-md ${
                      isActive ? 'bg-white/20 text-white' : item.badgeColor
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Footer System Status & Disclaimer */}
      <div className="p-4 border-t border-slate-800 bg-slate-950/60 space-y-3">
        <div className="rounded-lg bg-slate-900/80 border border-slate-800 p-2.5 text-[11px] text-slate-400 space-y-1.5">
          <div className="flex items-center justify-between text-slate-300">
            <span className="font-semibold text-white flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${online ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500'}`} />
              System Status
            </span>
            <span className={`text-[10px] font-mono ${online ? 'text-emerald-400' : 'text-rose-400'}`}>
              {online ? 'API ONLINE' : 'API OFFLINE'}
            </span>
          </div>
          <p className="text-[10px] text-slate-400 leading-tight">
            Retrieval: {health ? (health.vector_store ? 'vector + lexical' : 'lexical only (vector down)') : 'unknown'}
          </p>
          <p className="text-[10px] text-slate-400 leading-tight">
            Prediction model: <span className="font-mono text-amber-300">{prediction}</span>
          </p>
        </div>

        <div className="flex items-center gap-2 text-[10px] text-slate-400 bg-slate-900/40 px-2 py-1.5 rounded border border-slate-800/60">
          <Info className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
          <span>{project?.isDemo ? 'Prototype Mode • Illustrative Data' : 'Prototype Mode • Uploaded records'}</span>
        </div>
      </div>
    </aside>
  );
};
