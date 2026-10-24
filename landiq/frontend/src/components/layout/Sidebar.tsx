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
  UploadCloud,
  MessagesSquare,
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

interface NavItem {
  id: PageView;
  label: string;
  icon: React.ElementType;
  badge?: string;
}

const PREDICTION_LABEL: Record<string, string> = {
  READY: 'Ready',
  DEMO_ONLY: 'Demo only',
  NOT_READY: 'Not ready',
};

export const Sidebar: React.FC<SidebarProps> = ({ currentPage, onNavigate, highRiskCount, health, project }) => {
  const sections: { title: string; items: NavItem[] }[] = [
    {
      title: 'Analysis',
      items: [
        { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
        { id: 'high-risk-cases', label: 'High-Risk Cases', icon: AlertTriangle, badge: highRiskCount ? String(highRiskCount) : undefined },
        { id: 'case-details', label: 'Acquisition Cases', icon: FileSearch },
        { id: 'risk-explanation', label: 'Risk Analysis', icon: BrainCircuit },
        { id: 'recommended-actions', label: 'Recommended Actions', icon: ShieldCheck },
        { id: 'gis-map', label: 'GIS Parcel Map', icon: MapPin },
        { id: 'chat', label: 'Ask the Documents', icon: MessagesSquare },
      ],
    },
    { title: 'Reporting', items: [{ id: 'reports', label: 'Executive Briefing', icon: FileText }] },
    { title: 'Data', items: [{ id: 'ingestion', label: 'Data & Analysis Jobs', icon: UploadCloud }] },
  ];

  const online = health !== null;
  const prediction = health?.prediction.status ?? 'NOT_READY';

  return (
    <aside className="w-60 shrink-0 bg-slate-950 text-slate-300 border-r border-slate-800/80 flex flex-col justify-between select-none">
      <div>
        <div className="h-16 px-5 flex items-center gap-3 border-b border-slate-800/80">
          <div className="h-8 w-8 rounded-md bg-blue-600 flex items-center justify-center">
            <Layers className="h-4 w-4 text-white" />
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight text-white">LANDIQ</div>
            <div className="text-[11px] text-slate-400">Land Acquisition Intelligence</div>
          </div>
        </div>

        <nav className="px-3 py-4 space-y-5">
          {sections.map((section) => (
            <div key={section.title} className="space-y-0.5">
              <div className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500">{section.title}</div>
              {section.items.map((item) => {
                const isActive = currentPage === item.id;
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    onClick={() => onNavigate(item.id)}
                    aria-current={isActive ? 'page' : undefined}
                    className={`relative w-full flex items-center justify-between px-3 py-2 rounded-md text-[13px] transition-colors ${
                      isActive ? 'bg-white/[0.08] text-white font-medium' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-100'
                    }`}
                  >
                    {isActive && <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-blue-500" />}
                    <span className="flex items-center gap-2.5">
                      <Icon className={`h-4 w-4 ${isActive ? 'text-blue-400' : 'text-slate-500'}`} />
                      {item.label}
                    </span>
                    {item.badge && (
                      <span className="min-w-5 text-center text-[10px] font-semibold px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-300">
                        {item.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
      </div>

      <div className="p-4 border-t border-slate-800/80 space-y-2 text-[11px]">
        <div className="flex items-center justify-between">
          <span className="text-slate-500">API</span>
          <span className={`flex items-center gap-1.5 font-medium ${online ? 'text-emerald-400' : 'text-rose-400'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${online ? 'bg-emerald-400' : 'bg-rose-500'}`} />
            {online ? 'Online' : 'Offline'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-500">Retrieval</span>
          <span className="text-slate-300">{health ? (health.vector_store ? 'Vector + lexical' : 'Lexical only') : '—'}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-500">Risk model</span>
          <span className="text-slate-300">{PREDICTION_LABEL[prediction] ?? prediction}</span>
        </div>
        {project && (
          <div className="flex items-center justify-between">
            <span className="text-slate-500">Data</span>
            <span className="text-slate-300">{project.isDemo ? 'Synthetic demo' : 'Uploaded records'}</span>
          </div>
        )}
      </div>
    </aside>
  );
};
