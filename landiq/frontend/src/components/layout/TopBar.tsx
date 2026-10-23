import React from 'react';
import { Search, ChevronDown, Layers, HelpCircle, Database, FileStack } from 'lucide-react';
import { ProjectInfo, PageView } from '../../types';
import type { ApiHealth } from '../../api/client';

interface TopBarProps {
  projects: ProjectInfo[];
  selectedProject: ProjectInfo | null;
  onSelectProject: (proj: ProjectInfo) => void;
  currentPage: PageView;
  caseLabel?: string;
  onSearchCase: (query: string) => void;
  searchMessage: string | null;
  health: ApiHealth | null;
}

export const TopBar: React.FC<TopBarProps> = ({
  projects,
  selectedProject,
  onSelectProject,
  currentPage,
  caseLabel,
  onSearchCase,
  searchMessage,
  health,
}) => {
  const [dropdownOpen, setDropdownOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState('');

  const pageNames: Record<PageView, string> = {
    dashboard: 'Project Risk Overview',
    'high-risk-cases': 'High-Risk Acquisition Cases',
    'case-details': caseLabel ? `Case ${caseLabel} Deep Dive` : 'Case Deep Dive',
    'risk-explanation': 'Risk Explainability',
    'recommended-actions': 'Decision Support & Recommended Actions',
    'gis-map': 'GIS Spatial Risk Map',
    reports: 'Executive Decision Briefing',
    ingestion: 'Data Ingestion & Analysis Jobs',
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) onSearchCase(searchQuery.trim());
  };

  const isDemo = selectedProject?.isDemo ?? false;
  const prediction = health?.prediction.status ?? 'NOT_READY';

  return (
    <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-md border-b border-slate-200/90 shadow-2xs">
      <div className="bg-slate-900 text-slate-300 text-[11px] font-medium px-6 py-1.5 flex items-center justify-between border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
            <span className="font-bold tracking-wider text-white">LANDIQ • PROTOTYPE</span>
          </div>
          <span className="text-slate-500">|</span>
          <span className="text-slate-400">Predictive Land Acquisition Delay Prevention Platform</span>
        </div>

        <div className="flex items-center gap-4">
          {isDemo ? (
            <div className="flex items-center gap-1.5 bg-slate-800/90 text-amber-300 px-2 py-0.5 rounded text-[10px] font-semibold border border-amber-400/20">
              <Database className="h-3 w-3 text-amber-400" />
              <span>Illustrative Data</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 bg-slate-800/90 text-cyan-300 px-2 py-0.5 rounded text-[10px] font-semibold border border-cyan-400/20">
              <FileStack className="h-3 w-3 text-cyan-400" />
              <span>Uploaded Records</span>
            </div>
          )}
          <span className="text-slate-400 text-[10px] hidden sm:inline">
            Evidence: RAG (PDF + GIS) • Prediction model: <span className="font-mono text-amber-300">{prediction}</span>
          </span>
        </div>
      </div>

      <div className="px-6 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="relative">
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex items-center gap-2.5 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg px-3 py-1.5 text-left transition-all group"
            >
              <div className="h-7 w-7 rounded bg-blue-100 text-blue-800 flex items-center justify-center font-bold text-xs">
                <Layers className="h-4 w-4" />
              </div>
              <div>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-bold text-slate-900 group-hover:text-blue-600 transition-colors">
                    {selectedProject?.name ?? 'Loading…'}
                  </span>
                  <ChevronDown className="h-3.5 w-3.5 text-slate-400 group-hover:text-slate-600" />
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-500 font-mono">{selectedProject?.code}</span>
                  <span className="text-[10px] text-emerald-600 font-semibold bg-emerald-50 px-1 rounded">
                    {selectedProject?.totalCases ?? 0} Total Cases
                  </span>
                </div>
              </div>
            </button>

            {dropdownOpen && (
              <div className="absolute top-full left-0 mt-1 w-80 bg-white rounded-xl shadow-xl border border-slate-200 py-1.5 z-50">
                <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-slate-100">
                  Select Project Corridor
                </div>
                {projects.map((proj) => (
                  <button
                    key={proj.id}
                    onClick={() => {
                      onSelectProject(proj);
                      setDropdownOpen(false);
                    }}
                    className={`w-full text-left px-3 py-2 text-xs transition-colors flex items-center justify-between ${
                      proj.id === selectedProject?.id ? 'bg-blue-50/80 text-blue-900 font-semibold' : 'hover:bg-slate-50 text-slate-700'
                    }`}
                  >
                    <div>
                      <div className="font-medium">{proj.name}</div>
                      <div className="text-[10px] text-slate-500 font-mono">
                        {proj.code} • {proj.isDemo ? 'synthetic demo' : 'uploaded records'}
                      </div>
                    </div>
                    {proj.id === selectedProject?.id && <span className="h-2 w-2 rounded-full bg-blue-600" />}
                  </button>
                ))}
                <div className="px-3 py-1.5 text-[10px] text-amber-600 bg-amber-50/60 border-t border-slate-100 mt-1 flex items-center gap-1">
                  <HelpCircle className="h-3 w-3 shrink-0" />
                  <span>The demo corridor is an illustrative synthetic dataset</span>
                </div>
              </div>
            )}
          </div>

          <div className="hidden lg:flex items-center text-xs text-slate-500 gap-1.5 pl-2 border-l border-slate-200">
            <span>Section:</span>
            <span className="font-semibold text-slate-800 bg-slate-100 px-2 py-0.5 rounded text-[11px]">{pageNames[currentPage]}</span>
          </div>
        </div>

        <div className="relative">
          <form onSubmit={handleSearch} className="relative w-60">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search Case ID (e.g. #0472)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500 transition-all"
            />
          </form>
          {searchMessage && (
            <div role="status" className="absolute right-0 top-full mt-1 w-60 text-[11px] bg-slate-900 text-white px-3 py-2 rounded-lg shadow-lg">
              {searchMessage}
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
